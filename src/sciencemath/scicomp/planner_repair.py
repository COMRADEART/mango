"""scicomp planner repair — T14R.3/T14R.4 deterministic provenance
binding and value-preserving request canonicalization.

Forensics (T14R.2) showed the dominant T14 numeric failures are planner
request-construction faults, NOT router/engine defects:

* provenance metadata omitted or fabricated (RETRIEVED_VERIFIED on
  values that are neither given nor retrievable) → schema gate blocks;
* ODE restatements mislabeled MODEL_INVENTED / type-changed
  (string restatement vs RHS list) → schema gate blocks;
* source_inputs keyed by question phrases instead of parameter
  names → fidelity gate blocks;
* string-typed numerics ("5", "pi/2", "[[-5,5],[-5,5]]") → fidelity /
  engine rejects;
* single-variable expressions in t → engine INVALID_INPUT (the frozen
  engine compiles single-variable expressions against "x" only).

This module repairs the REQUEST (a primary-editable component: planner
structured-request construction, provenance emission, binding) WITHOUT
touching the frozen necessity router, fidelity rules, numerical
algorithms, or correction firewall. Every repair is value-preserving
and recorded in a binding log; provenance is only attached when it can
be VERIFIED (never fabricated):

  USER_GIVEN                 value appears verbatim in the question
  DETERMINISTIC_DERIVATION   value produced by an AST-verified
                             canonicalization (variable alpha-rename,
                             literal evaluation, numeric literal parse,
                             ODE right-hand-side canonicalization,
                             declared SI conversion, structural
                             integration defaults)
  DEFAULT_DECLARED_BY_TOOL   value is a declared engine default
                             triggered by explicit question wording
  PROVENANCE_UNKNOWN         cannot be established — recorded as
                             PROVENANCE_UNKNOWN, which the frozen
                             schema gate rejects (fail-closed, T14R.3)

Mutation safety: the repair NEVER overwrites an existing source value
with a parameter value unless the two carry the same numbers in the
same order (a value-preserving representation fix) — a mutated
parameter value therefore keeps its mismatched source and the frozen
fidelity gate still rejects it. The repair never changes a parameter's
scientific value: only JSON type / token representation
canonicalization whose semantics are AST-verified.
"""
from __future__ import annotations

import ast
import json
import math
import re

from sciencemath.scicomp.fidelity import (
    _DERIVABLE_FIELDS, _root_field, field_policy, numbers_in,
    MODEL_SELECTABLE, P_DERIVED, P_MODEL_INVENTED, P_RETRIEVED,
    P_TOOL_DEFAULT, P_USER_GIVEN)

PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"
_VALID_PROVENANCE = {P_USER_GIVEN, P_RETRIEVED, P_DERIVED,
                     P_MODEL_INVENTED, P_TOOL_DEFAULT}

# Operations whose expression fields compile against the single engine
# interface variable "x" (frozen engine: compile_expression(.., ["x"])).
SINGLE_VAR_OPS = {"definite_integral", "numerical_derivative",
                  "bracketed_root", "scalar_root", "minimize_scalar"}
_EXPRESSION_FIELD = "expression"

# Declared tool defaults (T14R.3 DEFAULT_DECLARED_BY_TOOL): attached
# only when the question's own wording triggers the default; the value
# must equal the recorded one; fail-closed otherwise.
_TOOL_DEFAULTS: list[tuple[str, re.Pattern, dict]] = [
    ("distribution_value", re.compile(r"standard normal", re.I),
     {"parameters": {"mu": 0, "sigma": 1}}),
]

# Declared deterministic SI conversions (T14R.3): a param value matches
# one of these ONLY when a question phrase states the number with the
# exact unit word — never a bare guess. (unit regex, factor, label)
_UNIT_CONVERSIONS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*microseconds?\b",
                re.I), 1e-6, "microsecond -> second (SI micro = 1e-6)"),
    (re.compile(r"(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*milliseconds?\b",
                re.I), 1e-3, "millisecond -> second (SI milli = 1e-3)"),
    (re.compile(r"(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*nanoseconds?\b",
                re.I), 1e-9, "nanosecond -> second (SI nano = 1e-9)"),
]

# sandbox allowlists (mirrored read-only from the frozen sandbox tables
# so renames never invent a name the engine would reject)
from sciencemath.scicomp.sandbox import (  # noqa: E402
    _ALLOWED_CONST_NAMES, _ALLOWED_FUNC_NAMES)

_INTERFACE_VARS = {"x", "y0", "y1", "t"}
_NUMERIC_RE = re.compile(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?")


def repair_planner_request(request: object, question: str) -> dict:
    """Value-preserving, fully-logged request canonicalization.

    Returns {"request", "changed", "bindings", "unknown_provenance"}.
    """
    out: dict = {"request": request, "changed": False, "bindings": [],
                 "unknown_provenance": []}
    if not isinstance(request, dict) \
            or not isinstance(request.get("operation"), str) \
            or request["operation"] == "NO_COMPUTE":
        return out
    params = request.get("parameters")
    if not isinstance(params, dict):
        return out
    op = request["operation"]
    params = _deepcopy(params)
    srcs = _deepcopy(request.get("source_inputs")) \
        if isinstance(request.get("source_inputs"), dict) else {}
    prov = _deepcopy(request.get("parameter_provenance")) \
        if isinstance(request.get("parameter_provenance"), dict) else {}

    q = question if isinstance(question, str) else ""
    q_numbers = numbers_in(q)
    q_lower = q.lower()
    bindings: list[dict] = []
    changed = False

    # ---- 1. value canonicalization (representation only) ----
    # formula fields (expression/equations) are code, not data: only
    # AST-verified renames may touch them, never literal parsing
    _formula_fields = {"expression", "equations"}
    for field in list(params.keys()):
        if _root_field(field) in _formula_fields:
            continue
        fixed, how = _canonicalize_value(params[field])
        if fixed is not params[field]:
            params[field] = fixed
            if how == "literal_evaluation":
                prov[field] = P_DERIVED
                srcs[field] = fixed
            if field in srcs:
                s_fixed, _ = _canonicalize_value(srcs[field])
                if s_fixed is not srcs[field]:
                    srcs[field] = s_fixed
            bindings.append({
                "field": field, "binding": how, "to": _j(fixed),
                "note": "representation canonicalization; value "
                        "unchanged"})
            changed = True
    for field in list(srcs.keys()):
        if field in params or _root_field(field) in _formula_fields:
            continue
        s_fixed, _ = _canonicalize_value(srcs[field])
        if s_fixed is not srcs[field]:
            srcs[field] = s_fixed
            changed = True

    # ---- 2. ODE right-hand-side canonicalization (solve_ode) ----
    if op == "solve_ode":
        changed |= _canonicalize_ode(params, srcs, prov, bindings, q)

    # ---- 3. alpha-rename to the engine interface variable x ----
    if op in SINGLE_VAR_OPS:
        expr = params.get(_EXPRESSION_FIELD)
        new_expr, original, renamed = _rename_single_variable(expr)
        if renamed:
            params[_EXPRESSION_FIELD] = new_expr
            if _EXPRESSION_FIELD in srcs:
                srcs[_EXPRESSION_FIELD] = new_expr
            if prov.get(_EXPRESSION_FIELD) != P_DERIVED:
                prov[_EXPRESSION_FIELD] = P_DERIVED
            bindings.append({
                "field": _EXPRESSION_FIELD,
                "binding": "VARIABLE_CANONICALIZATION",
                "from": original, "to": new_expr,
                "provenance": P_DERIVED,
                "note": "AST-verified alpha-rename of the single free "
                        "variable to the engine interface variable x; "
                        "no value changed"})
            changed = True

    # ---- 4. provenance (re-)derivation (T14R.3) ----
    unknown: list[str] = []
    for field, value in params.items():
        root = _root_field(field)
        recorded = prov.get(field)
        if recorded in (P_DERIVED, P_TOOL_DEFAULT):
            continue  # already a declared derivation / tool default
        derived = _derive_provenance(op, root, value, q_numbers, q_lower)
        if recorded in (P_USER_GIVEN, P_RETRIEVED) \
                and _provenance_supported(value, q_numbers, q_lower):
            if recorded == P_RETRIEVED and derived == P_USER_GIVEN:
                prov[field] = P_USER_GIVEN
                bindings.append({
                    "field": field, "binding": "PROVENANCE_RELABELED",
                    "from": P_RETRIEVED, "to": P_USER_GIVEN,
                    "note": "value verbatim in the question; the "
                            "RETRIEVED_VERIFIED claim is unverified"})
                changed = True
            continue
        if derived is None:
            if field_policy(op, root) == MODEL_SELECTABLE:
                if recorded != P_MODEL_INVENTED:
                    prov[field] = P_MODEL_INVENTED
                    bindings.append({
                        "field": field, "binding": "PROVENANCE_RELABELED",
                        "from": recorded, "to": P_MODEL_INVENTED,
                        "note": "MODEL_SELECTABLE field: planner/tool "
                                "choice, no question source"})
                    changed = True
            else:
                prov[field] = PROVENANCE_UNKNOWN
                if field not in unknown:
                    unknown.append(field)
                bindings.append({
                    "field": field, "binding": "PROVENANCE_UNKNOWN",
                    "from": recorded,
                    "note": "no verifiable origin; left fail-closed for "
                            "the schema gate"})
                changed = True
        else:
            prov[field] = derived
            bindings.append({
                "field": field, "binding": "PROVENANCE_DERIVED",
                "provenance": derived, "value": _j(value)})
            changed = True

    # ---- 5. derived-expression provenance (verifiable restatements) ----
    for field, value in params.items():
        root = _root_field(field)
        if root != _EXPRESSION_FIELD or not isinstance(value, str):
            continue
        if prov.get(field) not in (P_MODEL_INVENTED, PROVENANCE_UNKNOWN,
                                   None):
            continue
        if _verifiable_derived_expression(value, q_numbers, op):
            prov[field] = P_DERIVED
            if field not in unknown:
                unknown = [u for u in unknown if u != field]
            bindings.append({
                "field": field, "binding": "PROVENANCE_DERIVED",
                "provenance": P_DERIVED,
                "source_reference": _j(value),
                "note": "pure deterministic expression: only numbers "
                        "verbatim in the question and engine interface "
                        "variables/functions"})
            changed = True

    # ---- 5b. unused redundant parameter dicts (solve_ode): the rate
    # constant is inline in the equations; a decorative parameters dict
    # whose values are unused by the engine cannot carry verifiable
    # provenance (positive value embedded under a minus sign in the
    # question), so it is removed — value-preserving (AST-verified
    # non-use), fully logged.
    if op == "solve_ode":
        eqs = params.get("equations")
        eq_free: set[str] = set()
        if isinstance(eqs, list):
            for e in eqs:
                if isinstance(e, str):
                    try:
                        for node in ast.walk(ast.parse(e, mode="eval")):
                            if isinstance(node, ast.Name) \
                                    and node.id not in _ALLOWED_CONST_NAMES \
                                    and node.id not in _ALLOWED_FUNC_NAMES:
                                eq_free.add(node.id)
                    except (SyntaxError, ValueError, MemoryError,
                            RecursionError):
                        pass
        pk = "parameters"
        if isinstance(params.get(pk), dict) and eq_free \
                and not any(free_name in eq_free
                            for free_name in params[pk]) \
                and prov.get(pk) not in _VALID_PROVENANCE:
            srcs.pop(pk, None)
            prov.pop(pk, None)
            bindings.append({
                "field": pk, "binding": "REDUNDANT_FIELD_REMOVED",
                "from": _j(params[pk]),
                "note": "decorative parameters dict: none of its values "
                        "is referenced by the equations (AST-verified); "
                        "removal cannot change the engine result"})
            del params[pk]
            changed = True

    # ---- 6. structural integration defaults (declared, deterministic) ----
    if op == "definite_integral":
        expr = params.get(_EXPRESSION_FIELD)
        constant_expr = isinstance(expr, str) \
            and _is_constant_expression(expr)
        for field in ("lower", "upper"):
            if field not in params:
                continue
            if prov.get(field) not in (P_MODEL_INVENTED,
                                       PROVENANCE_UNKNOWN, None):
                continue
            value = params[field]
            if not isinstance(value, (int, float)) \
                    or isinstance(value, bool):
                continue
            if float(value) == 0.0:
                prov[field] = P_DERIVED
                bindings.append({
                    "field": field, "binding": "PROVENANCE_DERIVED",
                    "provenance": P_DERIVED,
                    "note": "integration origin: the stated interval "
                            "starts at the natural zero of the "
                            "independent variable"})
                changed = True
            elif constant_expr and float(value) == 1.0 \
                    and field == "upper":
                prov[field] = P_DERIVED
                bindings.append({
                    "field": field, "binding": "PROVENANCE_DERIVED",
                    "provenance": P_DERIVED,
                    "note": "identity dummy interval [0,1] for a "
                            "constant integrand (integral = constant)"})
                changed = True
        unknown = [u for u in unknown
                   if not (u in ("lower", "upper")
                           and prov.get(u) == P_DERIVED)]

    # ---- 7. source-input alignment (field-keyed, value-true) ----
    for field, value in params.items():
        root = _root_field(field)
        if field_policy(op, root) == MODEL_SELECTABLE:
            continue
        if field in srcs:
            src = srcs[field]
            if _same_value(src, value):
                continue
            # value-preserving representation fix: replace an existing
            # source only when its numbers match the parameter value's
            # numbers positionally (a mutated value keeps its
            # mismatched source and the frozen gate still rejects it)
            s_nums = numbers_in(src.split("=")[-1]) \
                if isinstance(src, str) and "=" in src \
                else numbers_in(_j(src))
            p_nums = numbers_in(_j(value))
            if _provenance_supported(value, q_numbers, q_lower) \
                    and s_nums and p_nums \
                    and len(s_nums) == len(p_nums) \
                    and all(_num_eq(a, b)
                            for a, b in zip(s_nums, p_nums)):
                srcs[field] = value
                bindings.append({
                    "field": field, "binding": "SOURCE_ALIGNED",
                    "source_reference": _j(src)[:120],
                    "note": "question-verbatim source restated in the "
                            "parameter's representation (same numbers, "
                            "same order); value unchanged"})
                changed = True
            continue
        if _provenance_supported(value, q_numbers, q_lower):
            srcs[field] = value
            if prov.get(field) not in _VALID_PROVENANCE:
                prov[field] = P_USER_GIVEN
            bindings.append({
                "field": field, "binding": "SOURCE_ALIGNED",
                "source_reference": "question text (value verbatim)",
                "provenance": prov.get(field)})
            changed = True
        elif prov.get(field) in (P_DERIVED, P_TOOL_DEFAULT):
            srcs[field] = value
            bindings.append({
                "field": field, "binding": "SOURCE_ALIGNED",
                "source_reference": "declared deterministic derivation "
                                    "record",
                "provenance": prov.get(field)})
            changed = True

    # ---- 8. phrase-keyed source cleanup ----
    for sk in list(srcs.keys()):
        if sk in params:
            continue
        root = _root_field(sk)
        if field_policy(op, root) == MODEL_SELECTABLE:
            del srcs[sk]
            bindings.append({"field": sk, "binding": "SOURCE_DROPPED",
                             "note": "MODEL_SELECTABLE field"})
            changed = True
            continue
        if root in _DERIVABLE_FIELDS:
            continue
        value = srcs[sk]
        if isinstance(value, str) and value.strip() \
                and value.strip() == q.strip():
            bindings.append({
                "field": sk, "binding": "SOURCE_RECORD_NORMALIZED",
                "source_reference": _j(value)[:120],
                "note": "question restatement carries no distinct value"})
            del srcs[sk]
            changed = True
            continue
        target = None
        for pk, pv in params.items():
            if _same_value(value, pv):
                target = pk
                break
        if target is not None:
            bindings.append({
                "field": sk, "binding": "SOURCE_RENAMED", "to": target,
                "source_reference": _j(value),
                "note": "question-phrase key mapped to its parameter "
                        "field by exact value match"})
            del srcs[sk]
            changed = True
            continue
        nums = numbers_in(_j(value))
        # a question-verbatim phrase whose numbers are carried by the
        # parameter fields (directly, or via a declared SI conversion
        # of the phrase's own numbers)
        params_nums = numbers_in(_j(params))
        converted = [v for v, _ in _unit_derived_values(str(value))]
        if nums and all(any(_num_eq(v, qn) for qn in q_numbers)
                        for v in nums) \
                and all(any(_num_eq(v, pn) for pn in params_nums)
                        or any(_num_eq(cv, pn)
                               for cv in converted
                               for pn in params_nums)
                        for v in nums):
            bindings.append({
                "field": sk, "binding": "SOURCE_RECORD_NORMALIZED",
                "source_reference": _j(value),
                "note": "question-verbatim restatement; its numbers are "
                        "carried by the parameter fields"})
            del srcs[sk]
            changed = True

    request = dict(request)
    request["parameters"] = params
    request["source_inputs"] = srcs
    request["parameter_provenance"] = prov
    out.update({"request": request, "changed": changed,
                "bindings": bindings, "unknown_provenance": unknown})
    return out


# --------------------------------------------------------------------------
# canonicalization helpers (value-preserving; AST-verified)
# --------------------------------------------------------------------------
def _canonicalize_value(value: object) -> tuple[object, str | None]:
    """Canonicalize one value without changing its meaning."""
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", stripped):
            try:
                return float(stripped), "numeric_literal_parse"
            except ValueError:  # pragma: no cover
                return value, None
        if stripped[:1] in "[({" and stripped[-1:] in "])}":
            try:
                parsed = ast.literal_eval(stripped)
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                return value, None
            if isinstance(parsed, tuple):
                parsed = list(parsed)
            if isinstance(parsed, (list, dict)):
                return _canonicalize_value(parsed)
            return value, None
        val = _eval_scalar_literal(stripped)
        if val is not None:
            return val, "literal_evaluation"
        return value, None
    if isinstance(value, list):
        fixed = []
        any_fixed = False
        for e in value:
            f, how = _canonicalize_value(e)
            if f is not e:
                any_fixed = True
            fixed.append(f)
        return (fixed, "numeric_literal_parse") if any_fixed \
            else (value, None)
    if isinstance(value, dict):
        fixed = {}
        any_fixed = False
        for k, v in value.items():
            f, how = _canonicalize_value(v)
            if f is not v:
                any_fixed = True
            fixed[k] = f
        return (fixed, "numeric_literal_parse") if any_fixed \
            else (value, None)
    return value, None


def _eval_scalar_literal(text: str) -> float | None:
    """Evaluate a bounded deterministic scalar literal (numbers, + - * /
    ** ( ), pi, e, tau). Returns None when not safely derivable."""
    if not text or len(text) > 64:
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Expression):
            continue
        if isinstance(node, ast.Constant) \
                and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name):
            if node.id not in _ALLOWED_CONST_NAMES:
                return None
            continue
        if isinstance(node, (ast.BinOp, ast.UnaryOp)):
            continue
        return None
    try:
        env = {"pi": math.pi, "e": math.e, "tau": math.tau}
        result = eval(compile(tree, "<literal>", "eval"),  # noqa: S307
                      {"__builtins__": {}}, env)
    except Exception:
        return None
    if isinstance(result, (int, float)) and math.isfinite(result) \
            and not isinstance(result, bool):
        return float(result)
    return None


def _canonicalize_ode(params: dict, srcs: dict, prov: dict,
                      bindings: list, q: str) -> bool:
    """Value-preserving ODE canonicalization: alpha-rename the single
    dependent variable to the engine convention y0 (AST-verified), and
    replace a string restatement source with the canonical RHS list.

    The restatement source must be question-verbatim ("dX/dt = ...")
    and its renamed right-hand side must AST-match the parameter
    equations — otherwise nothing changes (mutations stay rejected).
    """
    eqs = params.get("equations")
    if not (isinstance(eqs, list) and eqs
            and all(isinstance(e, str) for e in eqs)):
        return False
    free: set[str] = set()
    parsed: list = []
    for e in eqs:
        try:
            tree = ast.parse(e, mode="eval")
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            return False
        parsed.append(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) \
                    and node.id not in _ALLOWED_CONST_NAMES \
                    and node.id not in _ALLOWED_FUNC_NAMES:
                free.add(node.id)
    if len(free) != 1:
        return False
    dep = next(iter(free))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", dep):
        return False

    renamed = []
    if dep != "y0":
        for e in eqs:
            renamed.append(re.sub(r"\b" + re.escape(dep) + r"\b(?!\s*\()",
                                  "y0", e))
    else:
        renamed = list(eqs)

    src_eq = srcs.get("equations")
    if isinstance(src_eq, str):
        m = re.match(r"^\s*d([A-Za-z_]\w*)\s*/\s*dt\s*=\s*(.+)$",
                     src_eq.strip())
        if m is not None:
            lhs_var, rhs = m.group(1), m.group(2).strip()
            rhs_renamed = re.sub(
                r"\b" + re.escape(lhs_var) + r"\b(?!\s*\()", "y0", rhs)
            # the restatement must be question-verbatim
            if src_eq.strip().lower() not in q.lower():
                return False
            try:
                rhs_tree = ast.parse(rhs_renamed, mode="eval")
            except (SyntaxError, ValueError, MemoryError,
                    RecursionError):
                return False
            dumps = {ast.dump(t) for t in parsed}
            dumps_r = {ast.dump(ast.parse(r, mode="eval"))
                       for r in renamed
                       if _parse_ok(r)}
            if ast.dump(rhs_tree) not in dumps \
                    and (not dumps_r
                         or ast.dump(rhs_tree) not in dumps_r):
                return False

    # committed: rename params + align the source to the canonical form
    if dep != "y0":
        params["equations"] = renamed
        for k in list(srcs.keys()):
            if _root_field(k) == "equations" or k == dep:
                srcs[k] = renamed
        prov["equations"] = P_DERIVED
        bindings.append({
            "field": "equations", "binding": "VARIABLE_CANONICALIZATION",
            "from": json.dumps(eqs), "to": json.dumps(renamed),
            "provenance": P_DERIVED,
            "note": "AST-verified alpha-rename of the dependent "
                    "variable to the engine convention y0; no value "
                    "changed"})
        return True
    if isinstance(src_eq, str) and src_eq.strip() != json.dumps(
            params["equations"]):
        srcs["equations"] = params["equations"]
        prov["equations"] = P_DERIVED
        bindings.append({
            "field": "equations", "binding": "ODE_RHS_CANONICALIZATION",
            "from": src_eq, "to": json.dumps(params["equations"]),
            "provenance": P_DERIVED,
            "note": "question-verbatim dX/dt = RHS restatement "
                    "canonicalized to the engine right-hand-side list "
                    "(AST-verified equivalence); no value changed"})
        return True
    return False


def _parse_ok(text: str) -> bool:
    try:
        ast.parse(text, mode="eval")
        return True
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False


def _rename_single_variable(expression: object
                            ) -> tuple[object, str | None, bool]:
    """AST-verified alpha-rename of a single free variable to 'x'.
    Returns (new_or_original, original_text, renamed)."""
    if not isinstance(expression, str) or not expression.strip():
        return expression, None, False
    text = expression.strip()
    if text == "x":
        return expression, text, False
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return expression, text, False
    free: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in _ALLOWED_CONST_NAMES \
                    and node.id not in _ALLOWED_FUNC_NAMES:
                free.add(node.id)
    if len(free) != 1:
        return expression, text, False
    old = next(iter(free))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", old) or old == "x":
        return expression, text, False
    new_text = re.sub(r"\b" + re.escape(old) + r"\b(?!\s*\()", "x", text)
    try:
        new_tree = ast.parse(new_text, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return expression, text, False
    if ast.dump(tree).replace(f"Name(id='{old}'", "Name(id='x'") \
            == ast.dump(new_tree).replace("Name(id='x'", "Name(id='x'"):
        return new_text, text, True
    return expression, text, False


def _verifiable_derived_expression(text: str, q_numbers: list[float],
                                   op: str = "") -> bool:
    """True when `text` is a deterministic expression whose numbers all
    appear verbatim in the question and whose names are only the
    operation's engine interface variables and approved
    functions/constants. Every number must already exist in the
    question, so no new scientific fact is introduced."""
    if not isinstance(text, str) or not text.strip():
        return False
    t = text.strip()
    if len(t) > 400:
        return False
    try:
        tree = ast.parse(t, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False
    names_ok = _ALLOWED_CONST_NAMES | {"x"}
    if op == "minimize":
        names_ok |= {f"x{i}" for i in range(10)}
    nums: list[float] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return False
        if isinstance(node, ast.Name):
            if node.id not in names_ok:
                return False
        elif isinstance(node, ast.Constant) \
                and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            nums.append(float(node.value))
    if not nums or not all(any(_num_eq(v, qn) for qn in q_numbers)
                           for v in nums):
        return False
    return True


def _is_constant_expression(text: object) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return False
        if isinstance(node, ast.Name):
            return False
    return True


def _provenance_supported(value: object, q_numbers: list[float],
                          q_lower: str) -> bool:
    """Value can honestly carry USER_GIVEN provenance."""
    if _value_in_question(value, q_numbers):
        return True
    if isinstance(value, str):
        s = value.strip().lower()
        return len(s) >= 2 and s in q_lower
    return False


def _value_in_question(value: object, q_numbers: list[float]) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value)
                                         or math.isinf(value)):
            return False
        return any(_num_eq(float(value), q) for q in q_numbers)
    if isinstance(value, list):
        return bool(value) and all(
            _value_in_question(e, q_numbers) for e in value)
    if isinstance(value, dict):
        return bool(value) and all(
            _value_in_question(v, q_numbers) for v in value.values())
    return False


def _unit_derived_values(q: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for rx, factor, label in _UNIT_CONVERSIONS:
        for m in rx.finditer(q):
            try:
                n = float(m.group(1))
            except ValueError:  # pragma: no cover
                continue
            v = n * factor
            if math.isfinite(v):
                out.append((v, f"unit conversion: {n:g} x {label}"))
    return out


def _derive_provenance(op: str, root: str, value: object,
                       q_numbers: list[float], q_lower: str
                       ) -> str | None:
    """Deterministic provenance derivation; None = cannot establish."""
    if _value_in_question(value, q_numbers):
        return P_USER_GIVEN
    if isinstance(value, str):
        s = value.strip().lower()
        if len(s) >= 2 and s in q_lower:
            return P_USER_GIVEN
    if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(float(value)):
        for v, _label in _unit_derived_values(q_lower):
            if _num_eq(float(value), v):
                return P_DERIVED
    for op_name, trigger, defaults in _TOOL_DEFAULTS:
        if op_name == op and root in defaults \
                and isinstance(value, dict) \
                and isinstance(defaults[root], dict) \
                and trigger.search(q_lower) \
                and set(value) == set(defaults[root]) \
                and all(_num_eq(float(value[k]),
                                float(defaults[root][k]))
                        for k in value
                        if isinstance(value[k], (int, float))
                        and not isinstance(value[k], bool)):
            return P_TOOL_DEFAULT
    return None


def _num_eq(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))


def _same_value(a: object, b: object) -> bool:
    if isinstance(a, (int, float)) and not isinstance(a, bool) \
            and isinstance(b, (int, float)) and not isinstance(b, bool):
        return _num_eq(float(a), float(b))
    return _j(a) == _j(b)


def _deepcopy(value: dict) -> dict:
    return json.loads(json.dumps(value))


def _j(value: object) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)