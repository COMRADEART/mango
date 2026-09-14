"""scicomp result contract — T14R.5–T14R.11.

Turns a verified engine envelope into the canonical object the adopter
must bind to, deterministically:

* T14R.5  canonical contract: one authoritative value with its source
          span (field), semantic provenance, and the frozen
          source_parameter_hash binding — no free-form prose.
* T14R.6  DO_NOT_RECOMPUTE: the contract states the reasoner must not
          recompute or re-derive the verified value; the adopter prompt
          restates it and the observation carries the raw value itself.
* T14R.7  deterministic display: the contract fixes the display value
          and its rounding rule from a policy parsed OUT OF THE
          QUESTION TEXT ONLY (T14R.8: never from an expected answer).
          The model is never asked to choose precision.
* T14R.9  expected_result_type verification: the contract rejects
          (fail-closed) when the engine payload's authoritative field
          does not match the request's declared expected_result_type.
* T14R.10 unit preservation: the contract carries the result units and
          a deterministic guard that rejects answers which attach a
          DIFFERENT unit token to the verified number (m/s -> m, kg ->
          g, dimensioned -> dimensionless conversions must come from a
          verified conversion, which the SciComp lane never performs).
* T14R.11 stale invalidation: the contract carries the conflict policy
          (PREFER_VERIFIED_RESULT) so any value the reasoner asserted
          before the tool result is superseded, not preserved.

Fail-closed: when no authoritative field can be identified for the
operation + expected_result_type, or the payload shape does not match
the expected type, the contract marks binding NOT_CONTRACTABLE — the
adopter must not present a number as verified.
"""
from __future__ import annotations

import math
import re

from sciencemath.scicomp.adoption import (
    NOT_AUTHORITATIVE, VERIFIED)

# --------------------------------------------------------------------------
# T14R.9 — authoritative field per operation, in preference order
# --------------------------------------------------------------------------
_AUTHORITATIVE_FIELDS: dict[str, tuple[str, ...]] = {
    "definite_integral": ("integral",),
    "cumulative_integral": ("cumulative",),
    "numerical_derivative": ("derivative",),
    "solve_ode": ("final_state",),
    "minimize": ("optimum_x",),
    "minimize_scalar": ("optimum_x", "optimum_value"),
    "bracketed_root": ("root",),
    "scalar_root": ("root",),
    "system_root": ("solution",),
    "solve_linear_system": ("solution",),
    "determinant": ("determinant",),
    "matrix_inverse": ("inverse",),
    "matrix_multiply": ("matrix",),
    "eigen_decompose": ("eigenvalues",),
    "vector_or_matrix_norm": ("norm",),
    "matrix_rank": ("rank",),
    "confidence_interval_mean": ("ci_low", "ci_high", "mean"),
    "correlation": ("correlation",),
    "hypothesis_test": ("p_value", "t_statistic"),
    "distribution_value": ("value",),
    "parameter_sweep": ("row_count", "rows"),
    "curve_fit": ("parameters",),
    "least_squares": ("solution", "parameters"),
    "linear_regression": ("parameters", "slope"),
    "linear_interpolate": ("value",),
    "polynomial_interpolate": ("value", "coefficients"),
    "describe": ("mean", "value"),
}

# expected_result_type -> field preference for ops with several fields
_TYPE_FIELD: dict[str, dict[str, str]] = {
    "minimize_scalar": {"OPTIMUM_LOCATION": "optimum_x",
                        "OPTIMUM_VALUE": "optimum_value"},
    "hypothesis_test": {"STATISTIC": "t_statistic",
                        "P_VALUE": "p_value"},
    "parameter_sweep": {"SCALAR": "row_count",
                        "VECTOR": "rows"},
    "confidence_interval_mean": {
        "CONFIDENCE_INTERVAL": "ci_low",
        "SCALAR": "mean"},
}

_VALID_EXPECTED_TYPES = {"SCALAR", "VECTOR", "MATRIX", "ROOT", "INTEGRAL",
                         "DERIVATIVE", "OPTIMUM_LOCATION", "OPTIMUM_VALUE",
                         "ODE_FINAL_STATE", "STATISTIC", "P_VALUE",
                         "CONFIDENCE_INTERVAL", "PARAMETERS"}
NOT_CONTRACTABLE = "NOT_CONTRACTABLE"

# Fine-grained declared types are fail-closed on shape mismatch; the
# coarse planner vocabulary (scalar/vector/matrix/object, T12 prompt)
# only warns — a coarse declaration must not fail-close a verified
# value whose authoritative field the map already selected correctly.
_FINE_GRAINED_TYPES = {"ROOT", "INTEGRAL", "DERIVATIVE", "OPTIMUM_LOCATION",
                       "OPTIMUM_VALUE", "ODE_FINAL_STATE", "STATISTIC",
                       "P_VALUE", "CONFIDENCE_INTERVAL"}

# expected_result_type -> acceptable shapes for the authoritative value
_TYPE_CHECKS: dict[str, str] = {
    "SCALAR": "number", "ROOT": "number", "INTEGRAL": "number",
    "DERIVATIVE": "number", "OPTIMUM_VALUE": "number", "P_VALUE": "number",
    "VECTOR": "vector", "OPTIMUM_LOCATION": "number_or_vector",
    "ODE_FINAL_STATE": "vector", "MATRIX": "matrix",
    "STATISTIC": "number", "CONFIDENCE_INTERVAL": "pair",
    "PARAMETERS": "any",
}


# --------------------------------------------------------------------------
# T14R.5 / T14R.9 — canonical contract construction
# --------------------------------------------------------------------------
def result_contract(envelope_doc: dict, request: dict, question: str,
                    expected_result_type: str | None = None) -> dict:
    """Canonical verified-result contract (T14R.5).

    Returns the contract dict; binding is VERIFIED only for a PASS
    envelope whose authoritative field exists and matches the expected
    result type — otherwise NOT_CONTRACTABLE (fail-closed).
    """
    if envelope_doc.get("binding") != VERIFIED:
        return {
            "binding": NOT_AUTHORITATIVE,
            "reason": f"engine status {envelope_doc.get('status')} is not "
                      "an authoritative PASS envelope",
            "policy": "DO_NOT_ASSERT",
        }
    op = (request or {}).get("operation") or ""
    result = envelope_doc.get("result")
    expected = (expected_result_type
                or (request or {}).get("expected_result_type") or "").upper()

    field, value = _pick_authoritative(op, result, expected)
    if field is None:
        return {
            "binding": NOT_CONTRACTABLE,
            "reason": f"no authoritative field for {op} / {expected or '?'}",
            "policy": "DO_NOT_PRESENT_AS_VERIFIED",
        }
    shape_ok, shape_reason = _check_type_shape(value, expected)
    if not shape_ok and expected in _FINE_GRAINED_TYPES:
        return {
            "binding": NOT_CONTRACTABLE,
            "reason": shape_reason,
            "policy": "DO_NOT_PRESENT_AS_VERIFIED",
        }

    policy = format_policy(question)
    display = display_value(value, policy)
    units = envelope_doc.get("units") or ""
    raw = display["raw_value"]
    out = {
        "binding": VERIFIED,
        "type_match": shape_ok,
        "shape_warning": None if shape_ok else shape_reason,
        "operation": op,
        "authoritative_field": field,
        "authoritative_value": value,
        "expected_result_type": expected or "UNSPECIFIED",
        "units": units,
        "source_parameter_hash": envelope_doc.get("source_parameter_hash"),
        "display": display,
        "policy": "ADOPT_RAW_DO_NOT_RECOMPUTE",
        # T14R.11: the policy is static — any pre-compute value that
        # conflicts is superseded by the verified value (the runtime
        # conflict_state() call detects actual conflicts per answer)
        "stale_policy": "PREFER_VERIFIED_RESULT",
        "rules": [
            "DO_NOT_RECOMPUTE: use the verified value exactly as given; "
            "do not re-derive or re-compute it.",
            "UNIT_PRESERVATION: keep the result's units verbatim; never "
            "convert or drop a unit without a verified conversion.",
            "STALE_INVALIDATION: any value computed, guessed, or asserted "
            "BEFORE this result is superseded by the verified value.",
            ("DISPLAY: the display value already follows the question's "
             "stated rounding policy; do not re-round."
             if display["rounding_rule"] != "DEFAULT_SAFE_DISPLAY" else
             "DISPLAY: report the raw verified value; do not invent a "
             "rounding precision."),
        ],
    }
    if isinstance(value, list):
        out["policy"] = "ADOPT_VERIFIED_SEQUENCE"
        out["verified_sequence"] = raw
    else:
        out["policy"] = "ADOPT_VERIFIED_VALUE"
    return out


def _pick_authoritative(op: str, result: object,
                        expected: str) -> tuple[str | None, object]:
    if not isinstance(result, dict):
        # bare scalar payload
        if isinstance(result, (int, float)) \
                and not isinstance(result, bool) \
                and math.isfinite(float(result)):
            return ("value", float(result))
        return (None, None)
    candidates = list(_AUTHORITATIVE_FIELDS.get(op, ()))
    type_pref = _TYPE_FIELD.get(op, {}).get(expected)
    if type_pref and type_pref in result:
        candidates = [type_pref] + [c for c in candidates
                                    if c != type_pref]
    # a confidence interval is the PAIR [low, high] — selecting ci_low
    # alone would drop half the verified answer (unit/pair loss)
    if op == "confidence_interval_mean" \
            and "ci_low" in result and "ci_high" in result \
            and result["ci_low"] is not None \
            and result["ci_high"] is not None:
        return ("ci_low+ci_high",
                [result["ci_low"], result["ci_high"]])
    for field in candidates:
        if field in result and result[field] is not None:
            value = result[field]
            if isinstance(value, (int, float)) \
                    and not isinstance(value, bool) \
                    and not math.isfinite(float(value)):
                continue
            return (field, value)
    return (None, None)


def _check_type_shape(value: object, expected: str
                      ) -> tuple[bool, str]:
    want = _TYPE_CHECKS.get(expected)
    if want is None or want == "any":
        return True, ""   # unspecified type or shape-agnostic
    nums = _numeric_shape(value)
    if want == "number":
        if nums == "scalar":
            return True, ""
        return False, (f"expected_result_type {expected} requires a "
                       f"scalar; authoritative payload is {nums}")
    if want == "number_or_vector":
        if nums in ("scalar", "vector", "pair"):
            return True, ""
        return False, (f"expected_result_type {expected} requires a "
                       f"scalar or vector; payload is {nums or 'empty'}")
    if want == "vector":
        if nums in ("vector", "pair"):
            return True, ""   # a 2-vector is a vector
        if nums == "matrix":
            return False, (f"expected_result_type {expected} requires a "
                           "1-D vector; payload is a matrix")
        if nums == "pair":
            return True, ""   # a 2-vector is a vector
        return False, (f"expected_result_type {expected} requires a "
                       f"numeric vector; payload is {nums or 'empty'}")
    if want == "matrix":
        if nums == "matrix":
            return True, ""
        return False, (f"expected_result_type {expected} requires a "
                       f"matrix; payload is {nums or 'empty'}")
    if want == "pair":
        if nums == "pair":
            return True, ""
        return False, (f"expected_result_type {expected} requires a "
                       f"[low, high] pair; payload is {nums or 'empty'}")
    return True, ""


def _numeric_shape(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "empty"
    if isinstance(value, (int, float)):
        return "scalar" if math.isfinite(float(value)) else "empty"
    if isinstance(value, list):
        if not value:
            return "empty"
        if any(isinstance(e, list) for e in value):
            if all(isinstance(e, list) for e in value):
                return "matrix"
            return "empty"
        if all(isinstance(e, (int, float))
               and not isinstance(e, bool) for e in value):
            return "vector" if len(value) != 2 else "pair"
        return "empty"
    if isinstance(value, dict):
        return "object"
    return "empty"


# --------------------------------------------------------------------------
# T14R.7 / T14R.8 — deterministic display policy (question text only)
# --------------------------------------------------------------------------
POLICY_DEFAULT = "DEFAULT_SAFE_DISPLAY"
POLICY_DECIMALS = "DECIMAL_PLACES"
POLICY_SIGFIGS = "SIGNIFICANT_FIGURES"
POLICY_NEAREST_INTEGER = "NEAREST_INTEGER"
POLICY_PERCENTAGE = "PERCENTAGE"

_DECIMALS_RE = re.compile(
    r"to\s+(\d+)\s*(?:decimal\s*)?places?|"
    r"(\d+)\s*(?:decimal\s*)?places?\b|"
    r"rounded\s+to\s+(\d+)\s*(?:decimal\s*)?places?", re.I)
_SIGFIGS_RE = re.compile(
    r"(\d+)\s*(?:significant\s*(?:figures|figs|digits)|sig\s*figs?)", re.I)
_NEAREST_RE = re.compile(
    r"nearest\s+(?:whole\s+)?(?:number|integer)|to\s+the\s+nearest", re.I)
_PERCENT_RE = re.compile(r"as\s+a\s+percentage|percent(?:age)?\s+form|"
                         r"as\s+a\s+percent\b|\bpercent\b|%", re.I)


def format_policy(question: str) -> dict:
    """Deterministic display policy from the QUESTION TEXT ONLY.

    Never reads an expected answer (T14R.8: no benchmark leakage) —
    the policy is a pure function of how the user asked for the
    number: an explicitly stated decimal count, significant-figure
    count, "nearest" phrasing, percentage phrasing, or the default
    safe display (the raw value, no invented precision).
    """
    q = question or ""
    m = _DECIMALS_RE.search(q)
    if m:
        n = int(next(g for g in m.groups() if g))
        if 0 <= n <= 15:
            return {"policy": POLICY_DECIMALS, "decimals": n}
    m = _SIGFIGS_RE.search(q)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 15:
            return {"policy": POLICY_SIGFIGS, "sig_figs": n}
    if _NEAREST_RE.search(q):
        return {"policy": POLICY_NEAREST_INTEGER}
    if _PERCENT_RE.search(q):
        return {"policy": POLICY_PERCENTAGE}
    return {"policy": POLICY_DEFAULT}


def display_value(raw: object, policy: dict) -> dict:
    """Deterministic display value; never LLM-chosen precision."""
    if isinstance(raw, bool) or raw is None:
        return {"raw_value": raw, "display_value": raw,
                "rounding_rule": "NO_ROUNDING"}
    if isinstance(raw, (list, tuple)):
        # elementwise for vectors/matrices, same rule for each element
        return {
            "raw_value": raw,
            "display_value": [
                display_value(e, policy)["display_value"] for e in raw],
            "rounding_rule": policy.get("policy", POLICY_DEFAULT),
        }
    if not isinstance(raw, (int, float)) \
            or isinstance(raw, float) and not math.isfinite(raw):
        return {"raw_value": raw, "display_value": raw,
                "rounding_rule": "NO_ROUNDING"}
    raw_f = float(raw)
    name = policy.get("policy", POLICY_DEFAULT)
    if name == POLICY_DECIMALS:
        n = int(policy.get("decimals", 0))
        return {"raw_value": raw_f,
                "display_value": round(raw_f, n),
                "rounding_rule": f"ROUND_HALF_EVEN_{n}dp"}
    if name == POLICY_SIGFIGS:
        n = int(policy.get("sig_figs", 6))
        if raw_f == 0:
            disp = 0.0
        else:
            disp = float(f"%.{max(n, 1)}g" % raw_f)
        return {"raw_value": raw_f, "display_value": disp,
                "rounding_rule": f"ROUND_{n}_SIGNIFICANT_FIGURES"}
    if name == POLICY_NEAREST_INTEGER:
        # deterministic half-up on magnitude
        disp = math.copysign(math.floor(abs(raw_f) + 0.5), raw_f)
        return {"raw_value": raw_f,
                "display_value": float(disp),
                "rounding_rule": "ROUND_HALF_UP_TO_NEAREST_INTEGER"}
    if name == POLICY_PERCENTAGE:
        return {"raw_value": raw_f,
                "display_value": raw_f * 100.0,
                "rounding_rule": "PERCENTAGE_SCALE_X100_NO_EXTRA_ROUNDING"}
    return {"raw_value": raw_f, "display_value": raw_f,
            "rounding_rule": POLICY_DEFAULT + "_RAW_AS_COMPUTED"}


# --------------------------------------------------------------------------
# T14R.10 — unit preservation guard
# --------------------------------------------------------------------------
def unit_guard(result_units: str, answer: str) -> dict:
    """Deterministic unit-preservation check (T14R.10).

    The SciComp lane performs no unit conversion; an answer that
    attaches a unit token DIFFERENT from the verified result's unit
    (m/s -> m, kg -> g, dimensioned -> dimensionless) has lost or
    mutated the unit and must be rejected. Returns
    {"ok", "violation", "reason"}.
    """
    from sciencemath.scicomp.adoption import _unit_conflict
    ru = (result_units or "").strip()
    if not ru:
        return {"ok": True, "violation": False,
                "note": "no declared result units"}
    if not (answer or "").strip():
        return {"ok": True, "violation": False, "note": "empty answer"}
    if _unit_conflict(ru, answer):
        return {"ok": False, "violation": True,
                "violation_type": "UNIT_MUTATED",
                "note": f"result unit {ru!r} not preserved in answer"}
    return {"ok": True, "violation": False,
            "note": f"result unit {ru!r} preserved or omitted"}


# --------------------------------------------------------------------------
# T14R.6 — observation text carrying the contract
# --------------------------------------------------------------------------
def observe_contract(contract: dict) -> str:
    """Observation text the adopter receives: the canonical contract,
    never prose the model can re-derive from (T14R.6)."""
    if contract.get("binding") == VERIFIED:
        disp = contract.get("display") or {}
        parts = [
            f"VERIFIED_COMPUTE_RESULT "
            f"[field={contract.get('authoritative_field')}]",
            f"verified_value: {_fmt(contract.get('authoritative_value'))}",
            f"display_value: {_fmt(disp.get('display_value'))} "
            f"({disp.get('rounding_rule')})",
        ]
        if contract.get("units"):
            parts.append(f"units: {contract['units']} (preserve)")
        parts.append("Do NOT recompute this value; adopt it verbatim "
                     "as the final answer. Any number you asserted "
                     "before this result is superseded.")
        if contract.get("stale_policy") == "PREFER_VERIFIED_RESULT":
            parts.append("STALE-ANSWER RULE: if your earlier candidate "
                         "differs from the verified value, the verified "
                         "value wins.")
        parts.append(f"hash: "
                     f"{str(contract.get('source_parameter_hash'))[:12]}")
        if contract.get("shape_warning"):
            parts.append(f"NOTE: {contract['shape_warning']}")
        return " | ".join(parts)
    return (
        f"COMPUTE_RESULT_NOT_USABLE [{contract.get('binding')}] — "
        f"{contract.get('reason', '')}. Do NOT present a numeric "
        "answer as verified.")


def _fmt(value: object) -> str:
    if isinstance(value, list):
        return json_dumps(value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def json_dumps(value: object) -> str:
    import json
    return json.dumps(value)