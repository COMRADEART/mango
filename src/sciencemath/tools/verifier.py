"""verifier — deterministic final-answer verification (PASS/FAIL/UNKNOWN).

The verifier NEVER forces an uncertain case: every parse failure, timeout,
or insufficient-evidence path returns UNKNOWN. The false-PASS rate is a
critical T4 metric and is held near zero by construction:

* a verdict of PASS requires a decisive check — exact symbolic equality,
  numeric equality within tolerance, all-sample-points agreement (>= 3
  valid points), or a unit-aware magnitude match;
* wrong numeric answers, incompatible units, and sampled disagreements
  return FAIL;
* anything else (unparseable answers, simplify timeouts, poles in every
  sample) returns UNKNOWN.

`verify_model_output` is the T4.3 pipeline entry: it reads the raw model
output, extracts the answer, verifies against the reference, and returns a
record — the raw output is never rewritten in place (predictions keep the
original text; the verification record references it).
"""
from __future__ import annotations

import re

import sympy

from sciencemath.evaluation.extraction import extract_answer, \
    normalize_symbolic, signals_uncertainty
from sciencemath.tools.base import ToolError, run_with_timeout
from sciencemath.tools.equation_solver import EquationSolverTool
from sciencemath.tools.symbolic_math import (DEFAULT_TIMEOUT_S, safe_parse,
                                             symbolic_equivalence)
from sciencemath.tools.unit_converter import (_UNIT_TOKEN_RE, _lookup_unit,
                                              _normalize_unit_token,
                                              is_temperature_unit,
                                              parse_quantity, parse_unit)

NUMERIC_REL_TOL = 1e-6
NUMERIC_ABS_TOL = 1e-9
MIN_SAMPLE_POINTS = 3

VERDICTS = ("PASS", "FAIL", "UNKNOWN")


class AnswerObject:
    """Typed parse of an answer string. kind is one of:
    number | quantity | percent | expression | solution_set | letter |
    text | unparsed."""

    __slots__ = ("kind", "value", "unit", "expr", "elements", "text",
                 "parse_error")

    def __init__(self, kind: str, *, value: float | None = None,
                 unit: str | None = None, expr=None, elements=None,
                 text: str | None = None, parse_error: str | None = None):
        self.kind = kind
        self.value = value
        self.unit = unit
        self.expr = expr
        self.elements = elements or []
        self.text = text
        self.parse_error = parse_error


def _strip_wrappers(s: str) -> str:
    s = (s or "").strip()
    # unwrap \boxed{...} (non-nested) and $ wrappers
    s = re.sub(r"\\boxed\{([^{}]*)\}", r"\1", s)
    return s.strip("$").strip()


def parse_answer(text: str, *, lenient: bool = True) -> AnswerObject:
    """Classify an answer string for verification (never guesses)."""
    s = _strip_wrappers(text)
    if s == "":
        return AnswerObject("unparsed", text=text)

    # percent
    if s.endswith("%"):
        inner = s[:-1].strip()
        num = _try_number(inner)
        if num is not None:
            return AnswerObject("percent", value=num / 100.0, text=s,
                                unit="%", expr=_expr_of(inner))

    # plain number (incl. 3/4 fractions and 1,000-style commas) — must run
    # BEFORE parse_quantity, else "3/4" reads as quantity 3 with unit "/4"
    num = _try_number(s)
    if num is not None:
        return AnswerObject("number", value=num, text=s, expr=_expr_of(s))

    # quantity with a unit: "5 km", "98.6 degF", "3.2e4 kg/m^3"
    quantity = parse_quantity(s)
    if quantity is not None:
        value, unit = quantity
        if _is_known_unit(unit):
            return AnswerObject("quantity", value=value, unit=unit, text=s)

    # solution set / list: {2, 3} | 2, 3 | x = 2 or x = 3
    as_set = _try_solution_set(s)
    if as_set is not None:
        return AnswerObject("solution_set", elements=as_set, text=s)

    # single equation: lhs = rhs (validate_ast cannot parse assignments,
    # so equations are split and wrapped in sympy.Eq)
    if "=" in s and s.count("=") == 1:
        left_s, right_s = s.split("=", 1)
        try:
            eq = sympy.Eq(safe_parse(left_s, lenient=True),
                          safe_parse(right_s, lenient=True))
            return AnswerObject("expression", expr=eq, text=s)
        except (ToolError, Exception):  # noqa: BLE001 — fall through
            pass

    # symbolic expression (variables allowed)
    try:
        expr = safe_parse(s, lenient=True)
        return AnswerObject("expression", expr=expr, text=s)
    except ToolError as e:
        return AnswerObject("unparsed", text=s, parse_error=e.message)
    except Exception as e:  # noqa: BLE001
        return AnswerObject("unparsed", text=s, parse_error=str(e))


def _expr_of(s: str):
    """Best-effort sympy form of a numeric string (None when it fails)."""
    try:
        return safe_parse(s, lenient=True)
    except Exception:  # noqa: BLE001
        return None


def _try_number(s: str) -> float | None:
    """Parse a string as a pure number (incl. fractions like 3/4)."""
    t = s.strip()
    # thousand-separated numbers ("12,345,678"): strip ALL comma groups —
    # the old single-comma-only rule let "12,345,678" fall through to the
    # solution-set parser and be read as the list [12, 345, 678]
    if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+(\.\d+)?", t):
        t = t.replace(",", "")
    s = t
    if re.fullmatch(r"[-+]?\d+(\.\d*)?([eE][-+]?\d+)?|\.\d+([eE][-+]?\d+)?",
                    s):
        try:
            return float(s)
        except ValueError:
            return None
    if re.fullmatch(r"[-+]?\d+/\d+", s):
        try:
            num, den = s.split("/")
            return float(num) / float(den)
        except ZeroDivisionError:
            return None
    return None


def _is_known_unit(unit: str) -> bool:
    """True iff the string has at least one unit-name token and every name
    token resolves in the registry (bare operators like '/' never count)."""
    s = re.sub(r"\bper\b", "/", unit)
    tokens = _UNIT_TOKEN_RE.findall(s)
    if not tokens:
        return False
    from sciencemath.tools.unit_converter import _POWER_TOKEN_RE
    has_name = False
    for tok in tokens:
        if tok in ("*", "/") or _POWER_TOKEN_RE.fullmatch(tok):
            continue
        has_name = True
        from sciencemath.tools.unit_converter import _split_unit_token
        name, _ = _split_unit_token(tok)
        try:
            _lookup_unit(name)
        except ToolError:
            return False
    return has_name


_SET_SPLIT_RE = re.compile(r"[;,]")


def _try_solution_set(s: str) -> list[str] | None:
    """Parse '{2, 3}', '2, 3', 'x=2, x=-3', '2 or 3' into element strings.

    Returns None when the string is not set-like (single plain answers must
    not be misread as 1-element sets is fine, but prose must stay text)."""
    t = s.strip()
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1]
    else:
        # 'x = 2 or x = 3' / 'x = 2, x = 3' / bare '2, 3'
        if _SET_SPLIT_RE.search(t) or re.search(r"\bor\b", t, re.IGNORECASE):
            inner = t
        else:
            return None
    parts = [p.strip() for p in re.split(r"[;,]|\bor\b", inner,
                                         flags=re.IGNORECASE) if p.strip()]
    if not parts or len(parts) > 12:
        return None
    # every part must parse as a number or symbolic expression
    for p in parts:
        if _try_number(p) is None:
            stripped = re.sub(r"^[a-zA-Z]\s*=\s*", "", p)
            if _try_number(stripped) is None:
                try:
                    safe_parse(stripped, lenient=True)
                except ToolError:
                    return None
    return [re.sub(r"^[a-zA-Z]\s*=\s*", "", p).strip() for p in parts]


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_answer(extracted: str | None, expected: str,
                  answer_type: str = "exact_answer",
                  choices: list[str] | None = None,
                  timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """Verify an extracted answer against the expected answer.

    Returns {"verdict": PASS|FAIL|UNKNOWN, "method": str, "detail": str}.
    Deterministic. Never raises."""
    if extracted is None or str(extracted).strip() == "":
        return {"verdict": "UNKNOWN", "method": "no_answer",
                "detail": "no extractable answer"}
    try:
        return _verify(extracted, expected, answer_type, choices, timeout_s)
    except ToolError as e:
        if e.code == "TIMEOUT":
            return {"verdict": "UNKNOWN", "method": "timeout",
                    "detail": e.message}
        return {"verdict": "UNKNOWN", "method": "error", "detail": e.message}
    except Exception as e:  # noqa: BLE001 — verifier must never crash scoring
        return {"verdict": "UNKNOWN", "method": "error",
                "detail": f"{type(e).__name__}: {e}"}


def _verify(extracted: str, expected: str, answer_type: str,
            choices: list[str] | None, timeout_s: float) -> dict:
    if answer_type == "multiple_choice":
        return _verify_mcq(extracted, expected, choices)
    if answer_type in ("uncertainty", "short_text"):
        return _verify_text(extracted, expected)

    got = parse_answer(extracted)
    gold = parse_answer(expected)

    # gold not machine-parseable: deterministic normalized string equality
    if gold.kind == "unparsed":
        return _verify_string_fallback(extracted, expected)
    # model answer not machine-parseable while the reference is: we cannot
    # interpret what the model answered -> UNKNOWN. String equality against
    # a number is meaningless, and calling it FAIL would grade the
    # extraction heuristic as definitively wrong rather than the model.
    if got.kind == "unparsed":
        return {"verdict": "UNKNOWN", "method": "no_answer_extracted",
                "detail": f"cannot parse model answer {extracted!r}; "
                          f"reference {expected!r} is parseable"}

    # ---- solution sets ----------------------------------------------------
    if gold.kind == "solution_set" or got.kind == "solution_set":
        if gold.kind == "solution_set" and got.kind == "solution_set":
            return _verify_sets(got.elements, gold.elements, timeout_s)
        if gold.kind == "solution_set":
            return _verify_set_membership(got, gold.elements, timeout_s,
                                          got_side=True)
        return _verify_set_membership(gold, got.elements, timeout_s,
                                      got_side=False)

    # ---- quantities and numbers --------------------------------------------
    if got.kind == "quantity" and gold.kind == "quantity":
        return _verify_quantities(got, gold)
    if got.kind == "quantity" and gold.kind in ("number", "percent"):
        # model attached a unit, reference is bare: compare magnitudes,
        # flagged (unit semantics unverifiable against a bare reference)
        return _verify_numeric(got, gold, note="model_unit_unverified")
    if gold.kind == "quantity" and got.kind == "percent":
        # "50%" vs "0.5 m": a percent has no meaning without its base;
        # dropping the unit graded this PASS. Not decidable -> UNKNOWN.
        return {"verdict": "UNKNOWN", "method": "quantity",
                "detail": f"percent answer vs unit-bearing reference "
                          f"{gold.value} {gold.unit}: percent base undefined"}
    if gold.kind == "quantity" and got.kind == "number":
        return _verify_gold_quantity_bare_number(got, gold)
    if got.kind in ("number", "percent") and gold.kind in ("number",
                                                           "percent"):
        return _verify_numeric(got, gold)

    # ---- numeric vs symbolic constant (e.g. "2.718" vs "e") ----------------
    if {got.kind, gold.kind} <= {"number", "percent", "expression"}:
        return _verify_symbolic(got, gold, timeout_s)

    return _fallback_mixed(got, gold)


def _verify_mcq(extracted: str, expected: str,
                choices: list[str] | None) -> dict:
    from sciencemath.evaluation.extraction import extract_mcq
    got = extract_mcq(extracted, choices)
    exp = (expected or "").strip().upper()
    exp_letter = exp[0] if exp and exp[0] in "ABCDE" else None
    if got is None and not exp_letter:
        # both sides are choice VALUES (e.g. \boxed{3} vs reference '3'
        # for a numeric-choice MCQ): deterministic string comparison
        ok = ((extracted or "").strip().lower()
              == (expected or "").strip().lower()
              and (extracted or "").strip() != "")
        return {"verdict": "PASS" if ok else "FAIL", "method": "mcq_value",
                "detail": f"extracted {extracted!r} vs reference value "
                          f"{expected!r}"}
    if got is None:
        return {"verdict": "UNKNOWN", "method": "mcq_parse",
                "detail": f"cannot parse choice from {extracted!r}"}
    if not exp_letter:
        # MCQ whose reference is a choice VALUE (e.g. '3') rather than a
        # letter: deterministic string comparison of the extracted choice
        ok = (got or "").strip().lower() == (expected or "").strip().lower()
        return {"verdict": "PASS" if ok else "FAIL", "method": "mcq_value",
                "detail": f"extracted {got!r} vs reference value "
                          f"{expected!r}"}
    ok = got.upper() == exp_letter
    return {"verdict": "PASS" if ok else "FAIL", "method": "mcq_letter",
            "detail": f"extracted {got.upper()} vs expected {exp_letter}"}


def _verify_text(extracted: str, expected: str) -> dict:
    got_uncertain = signals_uncertainty(extracted)
    gold_uncertain = signals_uncertainty(expected)
    if gold_uncertain:
        ok = got_uncertain
    else:
        ok = normalize_symbolic(extracted) == normalize_symbolic(expected)
        if not ok:
            # deterministic short-text equality (case/punctuation-tolerant)
            a = re.sub(r"[^a-z0-9]", "", extracted.lower())
            b = re.sub(r"[^a-z0-9]", "", expected.lower())
            ok = a == b and a != ""
    return {"verdict": "PASS" if ok else "FAIL", "method": "text_match",
            "detail": ""}


def _verify_string_fallback(extracted: str, expected: str) -> dict:
    ok = normalize_symbolic(extracted) == normalize_symbolic(expected)
    return {"verdict": "PASS" if ok else "FAIL",
            "method": "normalized_string",
            "detail": "reference not machine-parseable; string comparison"}


def _fallback_mixed(got: AnswerObject, gold: AnswerObject) -> dict:
    return {"verdict": "UNKNOWN",
            "method": "type_mismatch",
            "detail": f"model answered {got.kind}, reference is "
                      f"{gold.kind}; not comparable"}


def _numbers_equal(a: float, b: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= NUMERIC_REL_TOL * max(1.0, abs(b)) + NUMERIC_ABS_TOL


def _verify_numeric(got: AnswerObject, gold: AnswerObject,
                    note: str | None = None) -> dict:
    gv, ev = got.value, gold.value
    # percent normalization: both stored as fraction already (25% -> 0.25)
    if _numbers_equal(ev, gv):
        return {"verdict": "PASS", "method": "numeric",
                "detail": note or ""}
    return {"verdict": "FAIL", "method": "numeric",
            "detail": f"expected {ev}, got {gv}"
                      + (f" ({note})" if note else "")}


_TEMPERATURE_DIMS = (0, 0, 0, 0, 1, 0, 0)


def _verify_gold_quantity_bare_number(got: AnswerObject,
                                      gold: AnswerObject) -> dict:
    """Bare model number vs unit-bearing reference.

    The bare number carries no unit, so it is accepted EITHER at the raw
    magnitude (answer given in the reference's unit) OR against the
    reference converted to SI base units ("3000" vs "3 km"). Unit-blind
    comparison graded the SI case FAIL. Only when BOTH interpretations
    fail is the answer FAIL."""
    if _numbers_equal(got.value, gold.value):
        return {"verdict": "PASS", "method": "quantity",
                "detail": f"bare number matches {gold.value} {gold.unit} "
                          f"(reference unit)"}
    from sciencemath.tools.unit_converter import (UnitConverterTool,
                                                  _format_si, _lookup_unit)
    try:
        _, dims = _lookup_unit(gold.unit)
    except ToolError:
        dims = None
    if dims is None or dims == _TEMPERATURE_DIMS:
        # temperature is affine (not factor-comparable); unknown registry
        # unit cannot be normalized — either way not decisive
        return {"verdict": "UNKNOWN", "method": "quantity",
                "detail": f"cannot normalize bare number against "
                          f"reference unit {gold.unit!r}"}
    res = UnitConverterTool().run({"value": gold.value,
                                   "from_unit": gold.unit,
                                   "to_unit": _format_si(dims)})
    if not res.ok:
        return {"verdict": "UNKNOWN", "method": "quantity",
                "detail": f"cannot convert reference unit {gold.unit!r} "
                          f"to SI"}
    si = res.result["converted_value"]
    if _numbers_equal(got.value, si):
        return {"verdict": "PASS", "method": "quantity_si_normalized",
                "detail": f"{gold.value} {gold.unit} = {si} (SI)"}
    return {"verdict": "FAIL", "method": "quantity",
            "detail": f"expected {gold.value} {gold.unit} (SI: {si}), "
                      f"got {got.value}"}


def _verify_quantities(got: AnswerObject, gold: AnswerObject) -> dict:
    got_unit, gold_unit = got.unit or "", gold.unit or ""
    if _normalize_unit_token(got_unit) == _normalize_unit_token(gold_unit):
        ok = _numbers_equal(got.value, gold.value)
        return {"verdict": "PASS" if ok else "FAIL", "method": "quantity",
                "detail": f"same unit {gold_unit}"}
    # compatible units: convert gold into the model's unit
    from sciencemath.tools.unit_converter import UnitConverterTool
    res = UnitConverterTool().run({"value": gold.value,
                                   "from_unit": gold_unit,
                                   "to_unit": got_unit})
    if not res.ok:
        err = res.error or {}
        if err.get("code") == "INCOMPATIBLE_UNITS":
            return {"verdict": "FAIL", "method": "quantity",
                    "detail": f"incompatible units: {gold_unit} vs "
                              f"{got_unit}"}
        return {"verdict": "UNKNOWN", "method": "quantity",
                "detail": str(err.get("message", "unit conversion failed"))}
    converted = res.result["converted_value"]
    ok = _numbers_equal(got.value, converted)
    return {"verdict": "PASS" if ok else "FAIL", "method": "quantity_converted",
            "detail": f"gold {gold.value} {gold_unit} = {converted} {got_unit}"}


def _verify_symbolic(got: AnswerObject, gold: AnswerObject,
                     timeout_s: float) -> dict:
    if got.expr is None or gold.expr is None:
        return {"verdict": "UNKNOWN", "method": "symbolic_parse",
                "detail": f"parse errors: got={got.parse_error!r} "
                          f"gold={gold.parse_error!r}"}
    got_eq = isinstance(got.expr, sympy.Equality)
    gold_eq = isinstance(gold.expr, sympy.Equality)
    if got_eq and gold_eq:
        ok = _equations_equivalent(got.expr, gold.expr, timeout_s)
        if ok is None:
            return {"verdict": "UNKNOWN", "method": "equation",
                    "detail": "could not decide equation equivalence"}
        return {"verdict": "PASS" if ok else "FAIL", "method": "equation",
                "detail": ""}
    if got_eq or gold_eq:
        # "x = 4" vs bare reference "4": the equation is right exactly when
        # its solution set is {4} (multiple solutions -> incomplete -> FAIL)
        eq = got.expr if got_eq else gold.expr
        value = gold.expr if got_eq else got.expr
        return _equation_vs_value(eq, value, timeout_s)
    verdict = symbolic_equivalence(got.expr, gold.expr, timeout_s)
    return {"verdict": verdict, "method": "symbolic_equivalence",
            "detail": ""}


def _equations_equivalent(a, b, timeout_s: float) -> bool | None:
    """Compare two equations/expressions as solution sets."""
    import sympy as sp

    def solution_set(expr):
        rel = expr if isinstance(expr, sp.Equality) else sp.Eq(expr, 0)
        syms = sorted(rel.free_symbols, key=lambda s: s.name)
        if not syms:
            return None
        try:
            sols = sp.solve(rel, syms, dict=True)
        except Exception:  # noqa: BLE001
            return None
        # keep the sympy objects: a string round-trip mangled solutions
        # starting with "(" (strip("{}()") eats the parens of a tuple str)
        return {tuple(sol.get(s2) for s2 in syms) for sol in sols}

    set_a, set_b = solution_set(a), solution_set(b)
    if set_a is None or set_b is None:
        return None
    # An EMPTY solution set is not evidence of equality: solve() returning
    # [] for both sides graded "1/x = 0" equivalent to "sqrt(x) = -1".
    # Undecidable -> None (UNKNOWN).
    if not set_a or not set_b:
        return None
    if len(set_a) != len(set_b):
        return False
    # match each element of A to a distinct element of B
    remaining = list(set_b)
    for sol in sorted(set_a, key=lambda t: sp.sstr(t)):
        matched = False
        for cand in list(remaining):
            if len(sol) != len(cand) or not sol:
                continue
            if all(symbolic_equivalence(x, y, timeout_s) == "PASS"
                   for x, y in zip(sol, cand)):
                remaining.remove(cand)
                matched = True
                break
        if not matched:
            return False
    return not remaining


def _equation_vs_value(eq, value, timeout_s: float) -> dict:
    """One side is an equation, the other a bare value.

    "x = 4" vs "4" passes exactly when the equation's solution set is
    {4}. Multiple solutions against a single reference value is an
    incomplete answer -> FAIL (never a false PASS)."""
    import sympy as sp

    syms = sorted(eq.free_symbols, key=lambda s: s.name)
    if not syms:
        return {"verdict": "UNKNOWN", "method": "equation",
                "detail": "equation has no variable to solve for"}
    if len(syms) > 1:
        return {"verdict": "UNKNOWN", "method": "equation",
                "detail": f"multi-variable equation ({len(syms)} symbols) "
                          f"vs single value is underdetermined"}
    try:
        sols = run_with_timeout(lambda: sp.solve(eq, syms, dict=True),
                                timeout_s, "solve equation")
    except ToolError as e:
        return {"verdict": "UNKNOWN", "method": "equation",
                "detail": f"solve failed: {e.message}"}
    except Exception:  # noqa: BLE001
        return {"verdict": "UNKNOWN", "method": "equation",
                "detail": "equation could not be solved"}
    if len(sols) != 1:
        return {"verdict": "FAIL", "method": "equation",
                "detail": f"{len(sols)} solutions vs single reference value"}
    verdict = symbolic_equivalence(sols[0][syms[0]], value, timeout_s)
    if verdict == "UNKNOWN":
        return {"verdict": "UNKNOWN", "method": "equation",
                "detail": "solution equivalence undecided"}
    return {"verdict": verdict, "method": "equation", "detail": ""}


def _verify_sets(got: list[str], gold: list[str],
                 timeout_s: float) -> dict:
    """Element-wise set comparison; order-independent, multiplicity-strict."""
    if len(got) != len(gold):
        return {"verdict": "FAIL", "method": "solution_set",
                "detail": f"{len(got)} solutions vs {len(gold)} expected"}
    remaining = list(gold)
    for elem in got:
        matched = False
        for cand in list(remaining):
            verdict = _element_verdict(elem, cand, timeout_s)
            if verdict == "PASS":
                remaining.remove(cand)
                matched = True
                break
            if verdict == "UNKNOWN":
                return {"verdict": "UNKNOWN", "method": "solution_set",
                        "detail": f"cannot decide {elem!r} vs {cand!r}"}
        if not matched:
            return {"verdict": "FAIL", "method": "solution_set",
                    "detail": f"{elem!r} not among expected solutions"}
    return {"verdict": "PASS", "method": "solution_set", "detail": ""}


def _verify_set_membership(single: AnswerObject, elements: list[str],
                           timeout_s: float, got_side: bool = True) -> dict:
    """One side answered a single value, the other a solution set.

    A single value matching an element of a multi-element set is
    definitively INCOMPLETE -> FAIL (never UNKNOWN: we know it is wrong).
    A single value matching the only element -> PASS."""
    matches = 0
    for elem in elements:
        # the AnswerObject is always `single`; the string is `elem`. The
        # old got_side branch swapped them and crashed on .kind -> UNKNOWN
        verdict = _single_vs_element(single, elem, timeout_s)
        if verdict == "PASS":
            matches += 1
        elif verdict == "UNKNOWN":
            return {"verdict": "UNKNOWN", "method": "solution_set",
                    "detail": "cannot decide single answer vs a set element"}
    if matches == 0:
        return {"verdict": "FAIL", "method": "solution_set",
                "detail": "single answer matches no expected solution"}
    if len(elements) > 1:
        return {"verdict": "FAIL", "method": "solution_set",
                "detail": f"incomplete: 1 value vs {len(elements)} solutions"}
    return {"verdict": "PASS", "method": "solution_set", "detail": ""}


def _single_vs_element(single: AnswerObject, elem: str,
                       timeout_s: float) -> str:
    """Compare one typed answer against one set element (PASS/FAIL/UNKNOWN)."""
    num = _try_number(elem)
    if single.kind in ("number", "percent") and num is not None:
        return "PASS" if _numbers_equal(single.value, num) else "FAIL"
    if single.kind == "quantity":
        return "UNKNOWN"          # bare element vs unit-carrying answer
    if single.kind == "expression" and single.expr is not None:
        try:
            ee = safe_parse(elem, lenient=True)
        except ToolError:
            return "UNKNOWN"
        return symbolic_equivalence(single.expr, ee, timeout_s)
    return "UNKNOWN"


def _element_verdict(a: str, b: str, timeout_s: float) -> str:
    na, nb = _try_number(a), _try_number(b)
    if na is not None and nb is not None:
        return "PASS" if _numbers_equal(na, nb) else "FAIL"
    try:
        ea, eb = safe_parse(a, lenient=True), safe_parse(b, lenient=True)
    except ToolError:
        return "UNKNOWN"
    return symbolic_equivalence(ea, eb, timeout_s)


# ---------------------------------------------------------------------------
# T4.3 pipeline: verify a raw model output (original text is preserved)
# ---------------------------------------------------------------------------

def verify_model_output(raw_output: str, expected: str,
                        answer_type: str = "exact_answer",
                        choices: list[str] | None = None,
                        timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """Full verification record for one model answer.

    The RAW model output is treated as immutable: it is echoed into the
    record (never modified, never rewritten in place) and the verification
    is computed separately from it.
    """
    extracted = extract_answer(raw_output or "", answer_type, choices)
    if answer_type == "multiple_choice" and extracted is None:
        # MCQ with a non-letter boxed answer (e.g. \boxed{3} for a numeric
        # choice): the general extractor still finds the value
        extracted = extract_answer(raw_output or "", "numeric", None)
    verification = verify_answer(extracted, expected, answer_type, choices,
                                 timeout_s)
    return {
        "raw_output_preserved": raw_output or "",
        "extracted_answer": extracted,
        "expected_answer": expected,
        "answer_type": answer_type,
        "verdict": verification["verdict"],
        "method": verification["method"],
        "detail": verification["detail"],
    }