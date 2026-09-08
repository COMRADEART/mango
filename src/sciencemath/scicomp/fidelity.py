"""scicomp fidelity — parameter fidelity and planner-schema enforcement
(T12.2–T12.9).

The T11 failure modes this module eliminates:

* the planner silently MUTATING invalid scientific inputs (σ=−1 → 1,
  p=1.5 → 0.5, repairing a malformed expression) so the engine returned
  PASS on an ill-posed problem;
* the planner INVENTING scientific values that the question never gave
  (initial conditions, coefficients, brackets);
* provenance-free parameters, so a hallucinated number is
  indistinguishable from a user-given one.

Contract (fail-closed, engine untouched — the engine stays frozen per
T12.1):

1. The planner must emit a strict request carrying BOTH
   ``source_inputs`` (the scientific values exactly as the question
   states them) and ``parameters`` (what will be executed), plus a
   per-field ``parameter_provenance`` map.
2. Every source→compute transformation is classified. Only four
   normalization classes are approved (unit normalization, canonical
   numeric formatting, whitespace, symbol normalization); each approved
   transformation is logged explicitly (T12.5). Anything else —
   especially changing a value, repairing an invalid one, inventing a
   missing one, replacing NaN/Inf, shrinking a sweep, changing bounds —
   is a PARAMETER_FIDELITY_FAIL and the request is NOT executed
   (T12.6).
3. Every numeric value claimed as user-given must actually appear in
   the question text (anti-hallucination); ``MODEL_INVENTED``
   provenance is rejected everywhere except fields the operation
   explicitly marks model-selectable (method/quantity choices — never
   the scientific facts being solved).
4. The semantic parameter hash is computed once over the approved
   request and travels with the result envelope, so adoption (T12.11)
   binds to the exact inputs that were executed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field as dc_field

# --------------------------------------------------------------------------
# statuses / error labels
# --------------------------------------------------------------------------
FIDELITY_OK = "FIDELITY_OK"
FIDELITY_FAIL = "PARAMETER_FIDELITY_FAIL"
SCHEMA_FAIL = "PLANNER_SCHEMA_FAIL"

STATUS_INVALID_INPUT = "INVALID_INPUT"
STATUS_NEEDS_INFORMATION = "NEEDS_INFORMATION"

# Provenance categories (T12.3). USER_GIVEN and RETRIEVED_VERIFIED and
# DETERMINISTIC_DERIVATION are acceptable for scientific facts;
# MODEL_INVENTED is acceptable ONLY on model-selectable fields.
P_USER_GIVEN = "USER_GIVEN"
P_RETRIEVED = "RETRIEVED_VERIFIED"
P_DERIVED = "DETERMINISTIC_DERIVATION"
P_MODEL_INVENTED = "MODEL_INVENTED"
P_TOOL_DEFAULT = "DEFAULT_DECLARED_BY_TOOL"
_ALLOWED_PROVENANCE = {P_USER_GIVEN, P_RETRIEVED, P_DERIVED,
                       P_MODEL_INVENTED, P_TOOL_DEFAULT}

# --------------------------------------------------------------------------
# field policy (T12.3): what the planner may choose vs must transmit.
# Anything not listed defaults to PROTECTED (fail-closed).
# --------------------------------------------------------------------------
PROTECTED = "PROTECTED"
MODEL_SELECTABLE = "MODEL_SELECTABLE"

_FIELD_POLICY: dict[str, dict[str, str]] = {
    "vector_or_matrix_norm": {"norm": MODEL_SELECTABLE},
    "numerical_derivative": {"order": MODEL_SELECTABLE},
    "distribution_value": {"quantity": MODEL_SELECTABLE},
    "confidence_interval_mean": {"confidence": MODEL_SELECTABLE,
                                 "method": MODEL_SELECTABLE},
    "correlation": {"method": MODEL_SELECTABLE},
    "hypothesis_test": {"test": MODEL_SELECTABLE,
                        "equal_var": MODEL_SELECTABLE},
    "linear_regression": {},  # all protected: x, y are data
    "curve_fit": {"parameters": MODEL_SELECTABLE},  # parameter NAMES only
}

# Fields whose value may be a planner-constructed grid DERIVED from
# question ranges (never new scientific facts): the sweep grid and the
# independent-variable grid for cumulative integration.
_DERIVABLE_FIELDS = {"sweeps", "x", "t_eval"}


def field_policy(operation: str, field_name: str) -> str:
    op_policy = _FIELD_POLICY.get(operation, {})
    return op_policy.get(field_name, PROTECTED)


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------
_FRACTION_RE = re.compile(
    r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?![\d.])")
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def numbers_in(text: str | None) -> list[float]:
    """Numeric literals in a text, simple fractions resolved (7/5→1.4)."""
    if not text:
        return []
    text = _FRACTION_RE.sub(
        lambda m: repr(float(m.group(1)) / float(m.group(2))), text)
    out = []
    for m in _NUM_RE.finditer(text):
        try:
            out.append(float(m.group(0)))
        except ValueError:  # pragma: no cover
            continue
    return out


def _num_eq(a: float, b: float) -> bool:
    if a == b:
        return True
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))
    return False


# --------------------------------------------------------------------------
# unit normalization (the only approved semantic-value transformation)
# --------------------------------------------------------------------------
# to canonical SI: (unit, factor). Prefixes handled for m/g/s/L.
_UNIT_TABLE: dict[str, float] = {
    "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
    "mg": 1e-6, "g": 0.001, "kg": 1.0,
    "ms": 0.001, "s": 1.0, "min": 60.0, "hour": 3600.0, "h": 3600.0,
    "ml": 0.001, "l": 1.0, "liter": 1.0, "litre": 1.0,
}
_VALUE_UNIT_RE = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([a-zA-Z]+)\s*$")


def _unit_convert(value: float, unit: str) -> float | None:
    factor = _UNIT_TABLE.get(unit.lower())
    return value * factor if factor is not None else None


def _split_value_unit(v: object) -> tuple[float | None, str | None]:
    if isinstance(v, (int, float)):
        return float(v), None
    if isinstance(v, str):
        m = _VALUE_UNIT_RE.match(v)
        if m:
            return float(m.group(1)), m.group(2)
    return None, None


# --------------------------------------------------------------------------
# expression normalization (approved symbol normalization only — never a
# repair). Canonical form: whitespace removed, '^'→'**', implicit
# multiplication made explicit ('2x'→'2*x', '3('→'3*('), trailing
# operators REMAIN (they make the canonical form unequal — a malformed
# expression can never silently become a valid one).
# --------------------------------------------------------------------------
def canonical_expression(expr: str) -> str:
    s = re.sub(r"\s+", "", expr)
    s = s.replace("^", "**")
    s = re.sub(r"(\d)([a-zA-Z(])", r"\1*\2", s)
    s = re.sub(r"\)([a-zA-Z0-9(])", r")*\1", s)
    return s


# --------------------------------------------------------------------------
# transformation classification (T12.2/T12.5)
# --------------------------------------------------------------------------
UNIT_NORMALIZATION = "UNIT_NORMALIZATION"
NUMERIC_FORMATTING = "NUMERIC_FORMATTING"
WHITESPACE_NORMALIZATION = "WHITESPACE_NORMALIZATION"
SYMBOL_NORMALIZATION = "SYMBOL_NORMALIZATION"
DISALLOWED = "DISALLOWED"


# specificity order used to propagate the strongest sub-classification
# out of list/dict element comparisons
_CLASS_PRIORITY = [NUMERIC_FORMATTING, WHITESPACE_NORMALIZATION,
                   SYMBOL_NORMALIZATION, UNIT_NORMALIZATION, DISALLOWED]


def _merge_sub_results(subs: list[dict]) -> dict:
    """Merge element classifications: fail on any disallowed element,
    otherwise report the most specific approved class seen (so a unit
    normalization inside a list is logged, not erased)."""
    if any(s["class"] == DISALLOWED for s in subs):
        bad = next(s for s in subs if s["class"] == DISALLOWED)
        return bad
    verified = all(s.get("semantic_equivalence_verified") for s in subs)
    strongest = max((s["class"] for s in subs),
                    key=_CLASS_PRIORITY.index)
    merged = {"class": strongest, "semantic_equivalence_verified": verified}
    details = [s["field_detail"] for s in subs if "field_detail" in s]
    if details:
        merged["field_detail"] = details[0]
    return merged


def classify_transformation(source: object, compute: object) -> dict:
    """Classify one source→compute value transformation.

    Returns {"class": ..., "semantic_equivalence_verified": bool} and,
    for UNIT_NORMALIZATION, the from/to/reason detail (T12.5).
    """
    # equal numeric value (canonical formatting of numbers)
    if isinstance(source, (int, float)) and not isinstance(source, bool):
        if isinstance(compute, (int, float)) and not isinstance(compute, bool):
            if _num_eq(float(source), float(compute)):
                return {"class": NUMERIC_FORMATTING,
                        "semantic_equivalence_verified": True}
            return {"class": DISALLOWED,
                    "semantic_equivalence_verified": False,
                    "reason": "NUMERIC_VALUE_CHANGED"}
        # "2 km" -> 2000 style: source str, compute number
        return {"class": DISALLOWED,
                "semantic_equivalence_verified": False,
                "reason": "TYPE_CHANGED"}

    if isinstance(source, str):
        if not isinstance(compute, str):
            # possible unit normalization: "2 km" -> 2000
            sv, sunit = _split_value_unit(source)
            if sv is not None and sunit and isinstance(compute, (int, float)):
                canon = _unit_convert(sv, sunit)
                if canon is not None and _num_eq(canon, float(compute)):
                    return {
                        "class": UNIT_NORMALIZATION,
                        "semantic_equivalence_verified": True,
                        "field_detail": {
                            "from": source, "to": compute,
                            "reason": UNIT_NORMALIZATION},
                    }
                return {"class": DISALLOWED,
                        "semantic_equivalence_verified": False,
                        "reason": "UNIT_CONVERSION_UNVERIFIED"}
            return {"class": DISALLOWED,
                    "semantic_equivalence_verified": False,
                    "reason": "TYPE_CHANGED"}
        # string → string: whitespace, symbol normalization, or repair?
        if re.sub(r"\s+", "", source) == re.sub(r"\s+", "", compute):
            return {"class": WHITESPACE_NORMALIZATION,
                    "semantic_equivalence_verified": True}
        if canonical_expression(source) == canonical_expression(compute):
            return {"class": SYMBOL_NORMALIZATION,
                    "semantic_equivalence_verified": True}
        return {"class": DISALLOWED,
                "semantic_equivalence_verified": False,
                "reason": "STRING_MODIFIED"}

    if isinstance(source, list):
        if not isinstance(compute, list):
            return {"class": DISALLOWED,
                    "semantic_equivalence_verified": False,
                    "reason": "TYPE_CHANGED"}
        if len(source) != len(compute):
            return {"class": DISALLOWED,
                    "semantic_equivalence_verified": False,
                    "reason": "SHAPE_CHANGED"}
        subs = [classify_transformation(s, c)
                for s, c in zip(source, compute)]
        return _merge_sub_results(subs)

    if isinstance(source, dict):
        if not isinstance(compute, dict):
            return {"class": DISALLOWED,
                    "semantic_equivalence_verified": False,
                    "reason": "TYPE_CHANGED"}
        if set(source) != set(compute):
            return {"class": DISALLOWED,
                    "semantic_equivalence_verified": False,
                    "reason": "KEYS_CHANGED"}
        subs = [classify_transformation(source[k], compute[k])
                for k in source]
        return _merge_sub_results(subs)

    if source is None or compute is None:
        ok = source is None and compute is None
        return {"class": NUMERIC_FORMATTING if ok else DISALLOWED,
                "semantic_equivalence_verified": ok}

    return {"class": DISALLOWED, "semantic_equivalence_verified": False,
            "reason": "UNCLASSIFIED_TRANSFORMATION"}


# --------------------------------------------------------------------------
# semantic parameter hash (T12.4)
# --------------------------------------------------------------------------
def _canonicalize(value: object) -> object:
    """Canonical JSON-able form: ints/floats unified, nested sorted."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        f = float(value)
        if f == int(f) and abs(f) < 1e15:
            return int(f)
        return round(f, 12)
    if isinstance(value, dict):
        return {k: _canonicalize(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    return value


def semantic_hash(parameters: object) -> str:
    """Deterministic hash over semantically canonical parameters."""
    payload = json.dumps(_canonicalize(parameters), sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# planner-schema validation (T12.7)
# --------------------------------------------------------------------------
REQUIRED_PLANNER_FIELDS = (
    "operation", "compute_required", "parameters", "source_inputs",
    "parameter_provenance", "expected_result_type", "reason_for_compute")
_CODE_KEYS = {"code", "script", "python", "source", "exec", "command",
              "shell", "path"}


def validate_planner_request(request: object) -> dict:
    """Strict schema gate on the planner's JSON (T12.7).

    Checks required fields, code-smuggling keys, provenance presence and
    category, and MODEL_INVENTED on protected fields. Fidelity of VALUES
    is checked separately by :func:`check_fidelity` (which also needs
    the question text).
    """
    failures: list[str] = []
    if not isinstance(request, dict):
        return {"ok": False, "failures": ["request_not_object"]}
    for f in REQUIRED_PLANNER_FIELDS:
        if f not in request:
            failures.append(f"missing_field:{f}")
    op = request.get("operation")
    if not isinstance(op, str) or not op:
        failures.append("operation_missing")
    params = request.get("parameters") or {}
    srcs = request.get("source_inputs") or {}
    prov = request.get("parameter_provenance") or {}
    if not isinstance(params, dict):
        failures.append("parameters_not_object")
    if not isinstance(srcs, dict):
        failures.append("source_inputs_not_object")
    if not isinstance(prov, dict):
        failures.append("provenance_not_object")
    if isinstance(request.get("preserve_verbatim"), str):
        failures.append("preserve_verbatim_must_be_list")
    if not request.get("reason_for_compute"):
        failures.append("reason_for_compute_missing")
    if not request.get("expected_result_type"):
        failures.append("expected_result_type_missing")

    # code smuggling (T11.33 guard, extended to the T12 schema)
    for section_name in ("parameters", "source_inputs", "options"):
        section = request.get(section_name)
        if isinstance(section, dict):
            for k in section:
                if str(k).lower() in _CODE_KEYS:
                    failures.append(f"code_key:{section_name}.{k}")

    if failures:
        return {"ok": False, "failures": failures}

    # provenance completeness + category legality
    if op != "NO_COMPUTE":
        for k in params:
            p = prov.get(k)
            if p not in _ALLOWED_PROVENANCE:
                failures.append(f"provenance_missing_or_invalid:{k}")
                continue
            policy = field_policy(op, _root_field(k))
            if p == P_MODEL_INVENTED and policy == PROTECTED:
                failures.append(f"model_invented_on_protected:{k}")
    return {"ok": not failures, "failures": failures}


def _root_field(field_path: str) -> str:
    return str(field_path).split(".")[0]


# --------------------------------------------------------------------------
# fidelity gate (T12.2/T12.4/T12.6)
# --------------------------------------------------------------------------
@dataclass
class FidelityResult:
    ok: bool
    status: str                      # FIDELITY_OK | PARAMETER_FIDELITY_FAIL
    failures: list[str] = dc_field(default_factory=list)
    normalization_log: list[dict] = dc_field(default_factory=list)
    derivation_log: list[dict] = dc_field(default_factory=list)
    source_parameter_hash: str = ""
    envelope: dict = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "status": self.status,
            "failures": self.failures,
            "normalization_log": self.normalization_log,
            "derivation_log": self.derivation_log,
            "source_parameter_hash": self.source_parameter_hash,
        }


def check_fidelity(request: dict, question: str) -> FidelityResult:
    """Compare source_inputs vs parameters field-by-field (T12.2),
    verify user-given values exist in the question text
    (anti-hallucination), and compute the semantic hash (T12.4).

    A FAIL here means the request is NOT executed (T12.6): the pipeline
    returns PARAMETER_FIDELITY_FAIL to the reasoner instead.
    """
    op = request["operation"]
    params = request.get("parameters") or {}
    srcs = request.get("source_inputs") or {}
    prov = request.get("parameter_provenance") or {}
    failures: list[str] = []
    norm_log: list[dict] = []
    deriv_log: list[dict] = []
    q_numbers = numbers_in(question)

    if op == "NO_COMPUTE":
        return FidelityResult(ok=True, status=FIDELITY_OK,
                              source_parameter_hash=semantic_hash({}))

    # every protected compute field must be traceable to a source field
    for k in params:
        root = _root_field(k)
        policy = field_policy(op, root)
        p = prov.get(k, P_MODEL_INVENTED)
        if k not in srcs:
            # derivable grids may be planner-constructed, declared as such
            if root in _DERIVABLE_FIELDS and p == P_DERIVED:
                deriv_log.append({"field": k, "provenance": P_DERIVED,
                                  "reason": "DERIVED_GRID_DECLARED"})
                continue
            if policy == MODEL_SELECTABLE:
                continue  # planner/tool choice, no question source exists
            failures.append(f"no_source_input:{k}")
            continue

        src = srcs[k]
        # anti-hallucination: user-given scalars must exist in the text
        if p in (P_USER_GIVEN, P_RETRIEVED):
            for v in numbers_in(json.dumps(src)):
                if not any(_num_eq(v, q) for q in q_numbers):
                    failures.append(f"value_not_in_question:{k}:{v}")

        comp = params[k]
        cls = classify_transformation(src, comp)
        if cls["class"] == DISALLOWED:
            failures.append(
                f"disallowed_transformation:{k}:{cls.get('reason')}")
        elif cls["class"] == UNIT_NORMALIZATION:
            norm_log.append({
                "field": k,
                "from": cls.get("field_detail", {}).get("from", src),
                "to": comp, "reason": UNIT_NORMALIZATION,
                "semantic_equivalence_verified": True})
        elif cls["class"] in (WHITESPACE_NORMALIZATION,
                              SYMBOL_NORMALIZATION):
            norm_log.append({
                "field": k, "from": src, "to": comp,
                "reason": cls["class"],
                "semantic_equivalence_verified": True})
        # NUMERIC_FORMATTING needs no log entry (invisible by design:
        # int/float canonical form is identical semantics)

    # source fields declared but not executed: for protected fields this
    # is a silent drop of a given scientific value — reject
    for k in srcs:
        if k not in params \
                and field_policy(op, _root_field(k)) == PROTECTED \
                and _root_field(k) not in _DERIVABLE_FIELDS:
            failures.append(f"source_input_dropped:{k}")

    h = semantic_hash(params)
    ok = not failures
    env = {
        "operation": op,
        "parameters": params,
        "provenance": prov,
        "source_parameter_hash": h,
        "normalization_log": norm_log,
        "derivation_log": deriv_log,
    }
    return FidelityResult(ok=ok,
                          status=FIDELITY_OK if ok else FIDELITY_FAIL,
                          failures=failures, normalization_log=norm_log,
                          derivation_log=deriv_log, source_parameter_hash=h,
                          envelope=env)