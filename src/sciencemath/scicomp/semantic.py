"""scicomp semantic fidelity — bounded canonicalizer and transformation
classes for fidelity comparison ONLY (T13.2–T13.9).

T12-DEF-2 root cause: the T12 classifier used runtime type equality as
semantic equality.  A faithful structured restatement — the planner
re-expressing the question's literal text as the schema-native value the
frozen engine requires (matrix literal string → numeric matrix, ODE
prose → the solve_ode input schema) — was rejected as TYPE_CHANGED.

T13 policy (fail-closed is unchanged):

1. The fidelity layer judges SCIENTIFIC MEANING of source→parameter
   transformations.  The frozen engine remains the schema/TYPE
   authority: a structured parameter whose types the engine rejects
   (numeric strings where JSON numbers are required) can never silently
   execute, because the engine fail-closes on them (schemas.finite_number
   rejects strings) — T13 does not change that.
2. Canonical parsing of SOURCE-side literals (numeric strings, matrix
   literals, unit values) is permitted ONLY for fields the frozen engine
   validates as numeric (``NUMERIC_SCHEMA_ROLES``, derived from the
   engine's own validation code) — T13.2's "only if schema explicitly
   allows canonical parsing".
3. A numeric STRING on the STRUCTURED side of a numeric-declared field
   is a schema-type violation and is rejected (TYPE_SEMANTICS_CHANGED):
   the engine schema distinguishes JSON numbers from strings, so no
   canonicalization may launder it.
4. null / zero / empty container / missing are NEVER interchangeable
   (T13.7); vector length and matrix shape mismatches reject before any
   engine execution (T13.8); containers preserve length, order and
   element-wise semantics with duplicates intact (T13.6).
5. Empty containers classify deterministically and never crash
   (T12-DEF-1 repair; T13.15).

Nothing here mutates execution inputs: canonical forms exist only for
comparison.  All classification is deterministic and bounded (no
recursion beyond the input's own nesting, no evaluation of expressions).
"""
from __future__ import annotations

import json
import re

# --------------------------------------------------------------------------
# T13.2 transformation classes
# --------------------------------------------------------------------------
EXACT = "EXACT"
REPRESENTATION_EQUIVALENT = "REPRESENTATION_EQUIVALENT"
UNIT_EQUIVALENT = "UNIT_EQUIVALENT"          # == legacy UNIT_NORMALIZATION
STRUCTURE_EQUIVALENT = "STRUCTURE_EQUIVALENT"
VALUE_CHANGED = "VALUE_CHANGED"
TYPE_SEMANTICS_CHANGED = "TYPE_SEMANTICS_CHANGED"
INFORMATION_ADDED = "INFORMATION_ADDED"
INFORMATION_REMOVED = "INFORMATION_REMOVED"
INVALID_NORMALIZATION = "INVALID_NORMALIZATION"

APPROVED_T13_CLASSES = {EXACT, REPRESENTATION_EQUIVALENT, UNIT_EQUIVALENT,
                        STRUCTURE_EQUIVALENT}

# --------------------------------------------------------------------------
# T13.4 schema roles — declared from the FROZEN engine's own validation
# (schemas.finite_number / finite_list / finite_matrix and each solver's
# input handling).  Only fields listed here may have their SOURCE side
# canonically parsed from literal text; anything undeclared stays
# fail-closed (string vs type mismatch => reject).
# --------------------------------------------------------------------------
ROLE_NUMBER = "NUMBER"
ROLE_NUMBER_LIST = "NUMBER_LIST"
ROLE_NUMBER_MATRIX = "NUMBER_MATRIX"
ROLE_NUMBER_MAP = "NUMBER_MAP"       # dict of named numbers (ODE parameters)
ROLE_EXPRESSION = "EXPRESSION"       # string expression, never numeric-parsed

_NUMERIC_SCHEMA_ROLES: dict[str, dict[str, str]] = {
    # linear algebra (linear_algebra.py: _as_array over matrix/a/b/vector)
    "determinant": {"matrix": ROLE_NUMBER_MATRIX},
    "matrix_inverse": {"matrix": ROLE_NUMBER_MATRIX},
    "matrix_rank": {"matrix": ROLE_NUMBER_MATRIX},
    "eigen_decompose": {"matrix": ROLE_NUMBER_MATRIX},
    "matrix_multiply": {"a": ROLE_NUMBER_MATRIX, "b": ROLE_NUMBER_MATRIX},
    "solve_linear_system": {"matrix": ROLE_NUMBER_MATRIX,
                            "a": ROLE_NUMBER_MATRIX, "b": ROLE_NUMBER_LIST,
                            "b_vector": ROLE_NUMBER_LIST},
    "vector_or_matrix_norm": {"vector": ROLE_NUMBER_LIST,
                              "matrix": ROLE_NUMBER_MATRIX},
    # calculus / roots (calculus.py, roots.py — numeric bounds and grids)
    "definite_integral": {"bound_low": ROLE_NUMBER, "bound_high": ROLE_NUMBER,
                          "x": ROLE_NUMBER_LIST, "t": ROLE_NUMBER_LIST,
                          "x_eval": ROLE_NUMBER_LIST},
    "numerical_derivative": {"x0": ROLE_NUMBER},
    "bracketed_root": {"bound_low": ROLE_NUMBER, "bound_high": ROLE_NUMBER},
    "scalar_root": {"x0": ROLE_NUMBER, "bound_low": ROLE_NUMBER,
                    "bound_high": ROLE_NUMBER},
    "system_root": {"x0": ROLE_NUMBER_LIST},
    # ODE (ode.py: finite_number(initial_state[i]), t_start, t_end,
    # parameters values)
    "solve_ode": {"initial_state": ROLE_NUMBER_LIST,
                  "t_start": ROLE_NUMBER, "t_end": ROLE_NUMBER,
                  "parameters": ROLE_NUMBER_MAP,
                  "t_eval": ROLE_NUMBER_LIST},
    # optimization (optimization.py: finite_number per bound element)
    "minimize_scalar": {"bound_low": ROLE_NUMBER, "bound_high": ROLE_NUMBER,
                        "x0": ROLE_NUMBER},
    "minimize": {"bounds": ROLE_NUMBER_MATRIX,
                 "initial_guess": ROLE_NUMBER_LIST},
    "parameter_sweep": {"base_value": ROLE_NUMBER},
    # statistics (statistics.py — numeric samples)
    "describe": {"values": ROLE_NUMBER_LIST},
    "confidence_interval_mean": {"values": ROLE_NUMBER_LIST},
    "correlation": {"x": ROLE_NUMBER_LIST, "y": ROLE_NUMBER_LIST},
    "hypothesis_test": {"sample_a": ROLE_NUMBER_LIST,
                        "sample_b": ROLE_NUMBER_LIST},
    "linear_regression": {"x": ROLE_NUMBER_LIST, "y": ROLE_NUMBER_LIST},
    "curve_fit": {"x": ROLE_NUMBER_LIST, "y": ROLE_NUMBER_LIST},
    # interpolation (interpolation.py)
    "linear_interpolate": {"x": ROLE_NUMBER_LIST, "y": ROLE_NUMBER_LIST,
                           "x_query": ROLE_NUMBER},
    "polynomial_interpolate": {"x": ROLE_NUMBER_LIST, "y": ROLE_NUMBER_LIST,
                               "x_query": ROLE_NUMBER},
}


def schema_role(operation: str, field: str) -> str | None:
    return _NUMERIC_SCHEMA_ROLES.get(operation, {}).get(field)


def _element_role(role: str | None) -> str | None:
    if role == ROLE_NUMBER_LIST:
        return ROLE_NUMBER
    if role == ROLE_NUMBER_MATRIX:
        return ROLE_NUMBER_LIST
    if role == ROLE_NUMBER_MAP:
        return ROLE_NUMBER
    return None


# --------------------------------------------------------------------------
# strict literal parsers (comparison-only)
# --------------------------------------------------------------------------
_STRICT_NUM_RE = re.compile(
    r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\s*$")
_FRACTION_RE = re.compile(
    r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)\s*/\s*(?:\d+\.?\d*|\.\d+)\s*$")


def parse_numeric_literal(text: str) -> float | None:
    """Strict numeric literal ("3.5", "2", "-1.2e3", simple "7/5").

    Returns None for anything else (no surrounding text, no units, no
    expressions — those are other classes, not number parses).
    """
    if not isinstance(text, str):
        return None
    if _STRICT_NUM_RE.match(text):
        try:
            return float(text)
        except ValueError:  # pragma: no cover
            return None
    if _FRACTION_RE.match(text):
        try:
            num, den = text.split("/")
            return float(num.strip()) / float(den.strip())
        except (ValueError, ZeroDivisionError):
            return None
    return None


_MATRIX_LINE_RE = re.compile(
    r"^\s*\[(.*)\]\s*$", re.S)


def parse_matrix_literal(text: str) -> list[list[float]] | None:
    """Strict matrix literal "[a b; c d]" / "[[a,b],[c,d]]" / "[a, b; c, d]"
    → rectangular nested float lists, or None if not exactly that shape.
    """
    if not isinstance(text, str):
        return None
    # nested-bracket form: strict JSON of numbers only
    stripped = text.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, list) and data:
            parsed = []
            width = None
            for row in data:
                if not isinstance(row, list) or not row:
                    return None
                vals = []
                for cell in row:
                    if isinstance(cell, bool) or \
                            not isinstance(cell, (int, float)):
                        return None
                    vals.append(float(cell))
                width = width or len(vals)
                if len(vals) != width:
                    return None
                parsed.append(vals)
            return parsed
        return None
    m = _MATRIX_LINE_RE.match(text)
    if not m:
        return None
    body = m.group(1).strip()
    if not body:
        return None
    rows = [r.strip() for r in body.split(";") if r.strip()]
    parsed: list[list[float]] = []
    width: int | None = None
    for row in rows:
        cells = [c for c in re.split(r"[\s,]+", row) if c]
        values: list[float] = []
        for cell in cells:
            v = parse_numeric_literal(cell)
            if v is None:
                return None
            values.append(v)
        if not values:
            return None
        if width is None:
            width = len(values)
        elif len(values) != width:
            return None
        parsed.append(values)
    return parsed or None


# --------------------------------------------------------------------------
# canonical comparison (T13.4/T13.5/T13.6/T13.7/T13.8)
# --------------------------------------------------------------------------
def cross_kind_classify(source: object, compute: object,
                        role: str | None) -> dict:
    """Classify a source→compute transformation whose runtime types differ.

    Only faithful representation changes may pass, and only on fields
    whose schema role permits canonical source-side parsing.  Never
    approves: value changes, scalar↔vector, shape/length changes,
    null↔zero/empty, numeric strings on the structured side.
    """
    src_num = _as_number(source, role)
    # structured side is NEVER numeric-string-parsed: the frozen engine
    # schema distinguishes JSON numbers from strings (T13.2 rule 3)
    comp_num = _as_number(compute, None)

    # number vs number (any representation): exact, bounded comparison.
    # 1e-12 relative is the T12-approved canonical-formatting bound —
    # input fidelity, NOT solver answer tolerance (T13.5).
    if src_num is not None and comp_num is not None:
        from sciencemath.scicomp.fidelity import _num_eq
        if _num_eq(src_num, comp_num):
            return _approved(REPRESENTATION_EQUIVALENT,
                             detail={"source_repr": repr(source),
                                     "compute_repr": repr(compute)})
        return _rejected(VALUE_CHANGED,
                         reason="NUMERIC_VALUE_CHANGED",
                         detail={"source": source, "compute": compute})

    # structured side must not be a numeric string in a numeric field
    # (T13.2 rule 3): the frozen engine schema distinguishes numbers
    # from strings, and no canonicalization may launder that.
    if isinstance(compute, str) and role in (ROLE_NUMBER, ROLE_NUMBER_LIST,
                                             ROLE_NUMBER_MATRIX,
                                             ROLE_NUMBER_MAP):
        if parse_numeric_literal(compute) is not None:
            return _rejected(TYPE_SEMANTICS_CHANGED,
                             reason="SCHEMA_TYPE_STRING_FOR_NUMBER",
                             detail={"field_role": role,
                                     "compute": compute})

    # matrix / vector literal source → structured list (role numeric)
    if isinstance(source, str) and isinstance(compute, (list, tuple)):
        lit = parse_matrix_literal(source)
        if lit is not None and role in (ROLE_NUMBER_MATRIX, ROLE_NUMBER_LIST):
            return _compare_sequences(lit, list(compute), role)
        return _rejected(TYPE_SEMANTICS_CHANGED, reason="TYPE_CHANGED")

    if isinstance(source, (list, tuple)) and isinstance(compute, str):
        lit = parse_matrix_literal(compute)
        if lit is not None and role in (ROLE_NUMBER_MATRIX, ROLE_NUMBER_LIST):
            return _compare_sequences(list(source), lit, role)
        return _rejected(TYPE_SEMANTICS_CHANGED, reason="TYPE_CHANGED")

    # scalar vs container is never equivalent (T13.3) — unless the
    # schema explicitly declares singleton-list equivalence (none does)
    if isinstance(source, (list, tuple)) or isinstance(compute, (list, tuple)):
        return _rejected(TYPE_SEMANTICS_CHANGED,
                         reason="SCALAR_CONTAINER_CHANGED")

    # null semantics (T13.7): null is not zero, not empty
    if source is None or compute is None:
        return _rejected(VALUE_CHANGED, reason="NULL_SEMANTICS_CHANGED",
                         detail={"source": source, "compute": compute})

    return _rejected(INVALID_NORMALIZATION,
                     reason="UNCLASSIFIED_TRANSFORMATION")


def _as_number(value: object, role: str | None) -> float | None:
    """Number for comparison: runtime numbers always; source-side strings
    only on numeric-declared fields (T13.2 canonical-parse rule)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and role == ROLE_NUMBER:
        return parse_numeric_literal(value)
    return None


def _compare_sequences(src: list, comp: list,
                       element_role: str | None) -> dict:
    """Shared list comparison: length, order, recursive element-wise
    semantics (T13.6/T13.8).  Roles drive the recursion depth
    (NUMBER_MATRIX → rows → numbers)."""
    if len(src) != len(comp):
        return _rejected(TYPE_SEMANTICS_CHANGED, reason="LENGTH_CHANGED",
                         detail={"source_len": len(src),
                                 "compute_len": len(comp)})
    from sciencemath.scicomp.fidelity import _num_eq
    for s, c in zip(src, comp):
        if isinstance(s, (list, tuple)) and isinstance(c, (list, tuple)):
            sub = _compare_sequences(list(s), list(c),
                                     _element_role(element_role))
            if not sub["semantic_equivalence_verified"]:
                return sub
            continue
        sn = _as_number(s, element_role)
        cn = _as_number(c, None)
        leaf_role = (ROLE_NUMBER
                     if element_role in (ROLE_NUMBER, ROLE_NUMBER_LIST)
                     else element_role)
        if cn is None and isinstance(c, str) \
                and leaf_role == ROLE_NUMBER \
                and parse_numeric_literal(c) is not None:
            # structured side numeric string in a numeric-declared field:
            # schema-type violation, never canonicalized away (T13.2)
            return _rejected(TYPE_SEMANTICS_CHANGED,
                             reason="SCHEMA_TYPE_STRING_FOR_NUMBER")
        if sn is None or cn is None or not _num_eq(sn, cn):
            return _rejected(VALUE_CHANGED, reason="ELEMENT_VALUE_CHANGED")
    return _approved(STRUCTURE_EQUIVALENT)


def _approved(cls: str, detail: dict | None = None) -> dict:
    out = {"class": cls, "semantic_equivalence_verified": True,
           "t13_class": cls}
    if detail:
        out["field_detail"] = detail
    return out


def _rejected(t13_cls: str, reason: str, detail: dict | None = None) -> dict:
    from sciencemath.scicomp.fidelity import DISALLOWED
    out = {"class": DISALLOWED, "semantic_equivalence_verified": False,
           "t13_class": t13_cls, "reason": reason}
    if detail:
        out["field_detail"] = detail
    return out


# --------------------------------------------------------------------------
# T13 structured-restatement resolvers (deterministic, per-operation)
#
# A resolver maps a coherent set of question-literal source keys onto the
# schema-native parameter fields of ONE operation family.  It engages
# only when the mapping is complete and every mapped value verifies
# equivalent; any leftover or mismatch fails closed.
# --------------------------------------------------------------------------
_ODE_LHS_RE = re.compile(
    r"^\s*d\s*([A-Za-z]\w*)\s*/\s*d\s*([A-Za-z]\w*)\s*=\s*(.+?)\s*$")
_ODE_IC_RE = re.compile(
    r"^([A-Za-z]\w*)\s*\(\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*\)$")
_EXPR_DEF_RE = re.compile(
    r"^\s*[A-Za-z]\w*\s*\(\s*[A-Za-z]\w*\s*\)\s*=\s*(.+?)\s*$")
_RANGE_RE = re.compile(
    r"^\s*(?:in|on)?\s*[\[\(]\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
    r"\s*,\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*[\]\)]\s*$")


class Restatement:
    """Coverage map produced by a resolver (T13 semantic layer)."""

    def __init__(self) -> None:
        self.param_verdicts: dict[str, dict] = {}   # param key -> verdict
        self.src_consumed: dict[str, str] = {}      # src key -> param key
        self.src_keys_for_param: dict[str, list[str]] = {}

    def cover(self, param_key: str, src_keys: list[str], verdict: dict,
              srcs: dict) -> None:
        self.param_verdicts[param_key] = verdict
        for sk in src_keys:
            self.src_consumed[sk] = param_key
        self.src_keys_for_param[param_key] = src_keys
        # verify the SOURCE side carries the numbers it claims
        # (anti-hallucination runs on the source values downstream)
        for sk in src_keys:
            if sk in srcs:
                verdict.setdefault("source_values", {})[sk] = srcs[sk]


def resolve_ode_restatement(srcs: dict, params: dict,
                            classify) -> Restatement | None:
    """solve_ode question-notation → schema restatement.

    Recognized faithful mapping (all deterministic):
      "dy/dt = RHS"            → equations: [RHS with state var renamed y0]
      "<var>(<t0>)": value     → initial_state[i] (var name match), t0 → t_start
      t / T / time: value      → t_end
      <name>: value            → parameters.<name>

    Coverage is reported under the TOP-LEVEL parameter keys the
    fail-closed loop iterates ("equations", "initial_state", "t_start",
    "t_end", "parameters"); a value-level mismatch is covered as a
    REJECTED verdict (precise failure label), while structural
    incoherence (cannot even parse the restatement shape) returns None
    so the T12 fail-closed behavior applies unchanged.
    """
    """solve_ode question-notation → schema restatement.

    Recognized faithful mapping (all deterministic):
      "dy/dt = RHS"            → equations: [RHS with state var renamed y0]
      "<var>(<t0>)": value     → initial_state[i] (var name match), t0 → t_start
      t / T / time: value      → t_end
      <name>: value            → parameters.<name>
    """
    comp_eq = params.get("equations")
    if not isinstance(comp_eq, list) or not comp_eq:
        return None
    if not all(isinstance(e, str) for e in comp_eq):
        return None

    src_eq = srcs.get("equations")
    rest = Restatement()

    # --- equations ---
    if isinstance(src_eq, str):
        m = _ODE_LHS_RE.match(src_eq)
        if not m:
            return None
        dep, _indep, rhs = m.group(1), m.group(2), m.group(3)
        renamed = re.sub(rf"\b{re.escape(dep)}\b", dep + "0", rhs)
        candidates = [renamed, rhs]
        if len(comp_eq) != 1:
            return None
        eq_verdict = _match_string_candidates(comp_eq[0], candidates)
        if eq_verdict is None:
            return None
        rest.cover("equations", ["equations"], eq_verdict, srcs)
        state_bases = [_state_base(e) for e in comp_eq]
        if any(b is None for b in state_bases):
            return None
    elif isinstance(src_eq, list) and len(src_eq) == len(comp_eq) \
            and all(isinstance(e, str) for e in src_eq):
        state_bases = []
        subs = []
        for s, c in zip(src_eq, comp_eq):
            m = _ODE_LHS_RE.match(s)
            if not m:
                # already RHS-form: direct string comparison
                verdict = classify(s, c)
                if not verdict["semantic_equivalence_verified"]:
                    return None
                subs.append(verdict)
                base = _state_base(c)
                if base is None:
                    return None
                state_bases.append(base)
                continue
            dep, _indep, rhs = m.group(1), m.group(2), m.group(3)
            renamed = re.sub(rf"\b{re.escape(dep)}\b", dep + "0", rhs)
            verdict = _match_string_candidates(c, [renamed, rhs])
            if verdict is None:
                return None
            subs.append(verdict)
            base = _state_base(c)
            if base is None:
                return None
            state_bases.append(base)
        eq_verdict = subs[0]
        for extra in subs[1:]:
            if extra["semantic_equivalence_verified"] is False:
                return None
        rest.cover("equations", ["equations"], eq_verdict, srcs)
    else:
        return None

    # --- initial conditions ---
    ics: dict[str, tuple[float, object, str]] = {}
    for k in srcs:
        if k == "equations":
            continue
        m = _ODE_IC_RE.match(k)
        if m:
            val = srcs[k]
            num = val if isinstance(val, (int, float)) \
                and not isinstance(val, bool) \
                else parse_numeric_literal(val) if isinstance(val, str) \
                else None
            if num is None:
                return None
            ics[m.group(1)] = (float(m.group(2)), val, k)

    init_state = params.get("initial_state")
    if not isinstance(init_state, list) or len(init_state) != len(comp_eq):
        return None
    if len(ics) != len(comp_eq):
        return None
    t0_values = set()
    ic_keys: list[str] = []
    ic_verdicts: list[dict] = []
    for i, base in enumerate(state_bases):
        if base not in ics:
            return None
        t0, raw, orig_key = ics[base]
        t0_values.add(t0)
        ic_keys.append(orig_key)
        ic_verdicts.append(classify(raw, init_state[i], ROLE_NUMBER))
    if len(t0_values) != 1:
        return None
    t0 = t0_values.pop()
    merged_ic = _merge_verdicts(ic_verdicts)
    rest.cover("initial_state", ic_keys, merged_ic, srcs)

    # --- t_start: implied by the initial condition's time ---
    t_start = params.get("t_start")
    if t_start is not None:
        rest.cover("t_start", [], classify(t0, t_start, ROLE_NUMBER), srcs)

    # --- t_end from t / T / time / t_final ---
    t_end = params.get("t_end")
    src_t = next((k for k in ("t", "T", "time", "t_final")
                  if k in srcs and k not in rest.src_consumed), None)
    if t_end is not None and src_t is not None:
        rest.cover("t_end", [src_t],
                   classify(srcs[src_t], t_end, ROLE_NUMBER), srcs)

    # --- parameters: named scalars absorbed into the parameters map ---
    comp_params = params.get("parameters")
    if comp_params is not None:
        if not isinstance(comp_params, dict):
            return None
        names = sorted(comp_params)
        sub_verdicts = []
        for name in names:
            if name in ("t", "T", "time"):
                return None  # reserved independent variable
            if name in srcs and name not in rest.src_consumed:
                sub_verdicts.append(
                    classify(srcs[name], comp_params[name], ROLE_NUMBER))
            else:
                # no question source for this declared parameter value
                sub_verdicts.append(_rejected(
                    INFORMATION_ADDED, reason="NO_SOURCE_FOR_PARAMETER"))
        rest.cover("parameters", [n for n in names if n in srcs],
                   _merge_verdicts(sub_verdicts), srcs)

    return rest


def _merge_verdicts(verdicts: list[dict]) -> dict:
    """Aggregate element verdicts: approved only if every element is;
    otherwise propagate the first rejection (precise label)."""
    bad = next((v for v in verdicts
                if not v["semantic_equivalence_verified"]), None)
    if bad is not None:
        return bad
    classes = {v.get("t13_class", REPRESENTATION_EQUIVALENT)
               for v in verdicts}
    cls = classes.pop() if len(classes) == 1 else STRUCTURE_EQUIVALENT
    return _approved(cls)


def resolve_scalar_bounds_restatement(srcs: dict, params: dict,
                                      classify) -> Restatement | None:
    """minimize_scalar restatement: "f(x) = body" → expression body,
    "in [-10, 10]" (from a domain key) → bound_low/bound_high."""
    rest = Restatement()

    # --- expression: strip a leading "f(x) =" definition prefix ---
    src_expr = srcs.get("expression")
    comp_expr = params.get("expression")
    if isinstance(src_expr, str) and isinstance(comp_expr, str):
        m = _EXPR_DEF_RE.match(src_expr)
        if m:
            body = m.group(1)
            verdict = classify(body, comp_expr)
            if not verdict["semantic_equivalence_verified"]:
                return None
            rest.cover("expression", ["expression"], verdict, srcs)

    # --- bounds from a domain/range key ("x": "in [-10, 10]") ---
    need_low = "bound_low" in params and "bound_low" not in srcs
    need_high = "bound_high" in params and "bound_high" not in srcs
    if need_low != need_high:
        return None
    if need_low:
        src_key = next((k for k in ("x", "domain", "interval", "range")
                        if k in srcs and k not in rest.src_consumed), None)
        if src_key is None:
            return None
        raw = srcs[src_key]
        m = _RANGE_RE.match(raw) if isinstance(raw, str) else None
        if not m:
            return None
        lo, hi = float(m.group(1)), float(m.group(2))
        v_lo = classify(lo, params["bound_low"], ROLE_NUMBER)
        v_hi = classify(hi, params["bound_high"], ROLE_NUMBER)
        if not (v_lo["semantic_equivalence_verified"]
                and v_hi["semantic_equivalence_verified"]):
            return None
        rest.cover("bound_low", [src_key], v_lo, srcs)
        rest.cover("bound_high", [src_key], v_hi, srcs)

    return rest if rest.param_verdicts else None


def _match_string_candidates(compute: str, candidates: list[str]) -> dict | None:
    from sciencemath.scicomp.fidelity import classify_transformation
    for cand in candidates:
        verdict = classify_transformation(cand, compute)
        if verdict["semantic_equivalence_verified"]:
            return verdict
    return None


def _state_base(equation_rhs: str) -> str | None:
    """State-variable base name from a schema RHS ("−2*y0" → "y")."""
    m = re.search(r"\b([A-Za-z]\w*?)0\b", equation_rhs)
    return m.group(1) if m else None


RESTATEMENT_RESOLVERS: dict[str, object] = {
    "solve_ode": resolve_ode_restatement,
    "minimize_scalar": resolve_scalar_bounds_restatement,
}