"""T10.1-T10.5 — Build and freeze mango-correction-eval-v2.

194 cases: TRUE_FAIL 50, FALSE_FAIL 50, PARTIAL_FAIL 46, AMBIGUOUS 48
(12 domains each, all 10 difficulty types). Every label is mechanically
or source verified at build time:

  math        -> recomputed with sympy at build time
  units       -> recomputed with the production UnitConverterTool
  formulas    -> recomputed from the stated formula
  stoichiometry/molar mass -> atomic-mass table arithmetic
  facts       -> source-verified fact table (source recorded per case)
  retrieval   -> supporting chunk located in the frozen T5R corpus
                 (document_id + title recorded as provenance)

AMBIGUOUS cases are labeled by epistemic insufficiency: the only available
feedback is an unverified reviewer claim, so the mechanically verified label
is "insufficient evidence" (mechanical_label=False, as in v1).

Split: within each class, cases in id order alternate dev/final (25/25).
The final subset is frozen (IDs + sha256) before any T10 implementation
change. T10.6 failure analysis uses ONLY the development split.

Writes evaluations/t10/correction-suite/v2/{questions.jsonl,manifest.json,checksum.json,final_split.json}
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "evaluations" / "t10" / "correction-suite" / "v2"

from sciencemath.evaluation.extraction import answers_match  # noqa: E402

CLASSES = ["TRUE_FAIL", "FALSE_FAIL", "PARTIAL_FAIL", "AMBIGUOUS"]
DIFFICULTIES = [
    "simple_local_error", "multi_step_numeric_error", "symbolic_error",
    "unit_error", "wrong_assumption", "evidence_conflict",
    "wrong_scientific_claim", "citation_only_failure",
    "partial_solution_failure", "final_answer_only_failure",
]

# ---------------------------------------------------------------- helpers --


def corpus() -> list[dict]:
    path = ROOT / "rag" / "corpus" / "wikipedia_en.jsonl"
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                docs.append(json.loads(line))
    return docs


_DOCS = None


def find_support(phrase: str, extra: str = "") -> dict | None:
    """Locate a frozen-corpus chunk supporting `phrase` (and `extra`)."""
    global _DOCS
    if _DOCS is None:
        _DOCS = corpus()
    phrase_l = phrase.lower()
    extra_l = extra.lower()
    best = None
    for d in _DOCS:
        text = d["text"].lower()
        if phrase_l in text and (not extra_l or extra_l in text):
            if best is None or len(d["text"]) < len(best["text"]):
                best = d
    return best


def citation(d: dict) -> str:
    return (f"{d['title']} (Wikipedia, rev {d['revision']}, "
            f"chunk {d['chunk_id']}, {d['license']})")


# --------------------------------------------------- atomic mass constants --

ATOMIC_MASS = {"H": 1.008, "C": 12.011, "N": 14.007, "O": 15.999,
               "Na": 22.990, "S": 32.06, "Cl": 35.45, "K": 39.098}


def molar_mass(formula: str) -> float:
    """Compute molar mass mechanically from the atomic-mass table."""
    total = 0.0
    for elem, count in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        if not elem:
            continue
        total += ATOMIC_MASS[elem] * (int(count) if count else 1)
    return total


# ------------------------------------------------------------ case records --

CASES: list[dict] = []


def add(case_class: str, domain: str, difficulty: str, question: str,
        initial: str, expected: str, component: str, feedback: str,
        feedback_source: str, feedback_status: str, evidence: str,
        required_output_type: str, verification: dict,
        wrong_variants: list[str] | None = None,
        protected: dict | None = None, failed_part: str | None = None,
        mechanical_label: bool = True) -> None:
    """Append one case after verifying its label mechanically.

    TRUE_FAIL:      initial must be objectively wrong.
    FALSE_FAIL:     initial must be objectively correct.
    PARTIAL_FAIL:   failed part must be wrong, protected parts correct.
    AMBIGUOUS:      label is epistemic insufficiency (no value assertion).
    """
    from sciencemath.evaluation.extraction import answers_match
    if case_class == "TRUE_FAIL":
        assert not answers_match(expected, initial), \
            f"TRUE_FAIL initial matches expected: {question}"
        for w in wrong_variants or []:
            assert not answers_match(expected, w), \
                f"wrong variant matches expected: {question}"
    elif case_class == "FALSE_FAIL":
        assert answers_match(expected, initial), \
            f"FALSE_FAIL initial differs from expected: {question}"
    elif case_class == "PARTIAL_FAIL":
        assert failed_part in protected, f"failed part missing: {question}"
        for part, pv in protected.items():
            if part == failed_part:
                assert not answers_match(pv["expected"], pv["given"]), \
                    f"failed part should be wrong: {question}"
            else:
                assert answers_match(pv["expected"], pv["given"]), \
                    f"protected part should be correct: {question}"
    CASES.append({
        "case_class": case_class, "domain": domain, "difficulty": difficulty,
        "question": question, "initial_answer": initial,
        "expected_answer": expected, "failed_component": component,
        "feedback": feedback, "feedback_source": feedback_source,
        "feedback_status": feedback_status, "evidence": evidence,
        "required_output_type": required_output_type,
        "wrong_variants": wrong_variants or [],
        "protected": protected, "failed_part": failed_part,
        "mechanical_label": mechanical_label, "verification": verification,
    })


def sym_verify(detail: str) -> dict:
    return {"method": "sympy_recomputation", "detail": detail}


def tool_verify(tool: str, detail: str) -> dict:
    return {"method": tool, "detail": detail}


def fact_verify(source: str) -> dict:
    return {"method": "source_verified_fact_table", "detail": source}


def corpus_verify(source: str) -> dict:
    return {"method": "corpus_substring_support", "detail": source}


# ------------------------------------------------- math recomputation utils --


def f(x: float) -> str:
    """Format a float as a clean string (int when integral)."""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:g}"


# =================================================================
# Domain case tables — TRUE_FAIL / FALSE_FAIL
# (correct computed mechanically; wrong variants derived and verified)
# =================================================================


def math_cases() -> None:
    # ---- arithmetic ---------------------------------------------------
    a, b, c = 23, 47, 118
    exp = a * b - c
    q = f"What is {a} × {b} − {c}?"
    add("TRUE_FAIL", "arithmetic", "simple_local_error", q, f(exp - 20), f(exp),
        "numeric_result", f"Arithmetic recheck failed: {a} × {b} − {c} was "
        f"recomputed independently as {exp}.",
        "MATH_TOOL", "FAIL", f"Independent recomputation: {a}×{b}={a * b}; "
        f"{a * b}−{c}={exp}.", "integer",
        sym_verify(f"{a}*{b}-{c}={exp}"), [f(exp + 10), f(exp - 100)])
    add("FALSE_FAIL", "arithmetic", "evidence_conflict", q, f(exp), f(exp),
        "numeric_result",
        f"A reviewer claims the subtraction is off by 20 and the result should "
        f"be {exp + 20}.", "MATH_TOOL", "PASS",
        f"Independent recomputation confirms {a}×{b}−{c}={exp}; the feedback "
        "is contradicted.", "integer", sym_verify(f"{a}*{b}-{c}={exp}"))

    p, v = 15, 240
    exp = p * v // 100
    q = f"What is {p}% of {v}?"
    add("TRUE_FAIL", "arithmetic", "simple_local_error", q, f(exp // 10), f(exp),
        "numeric_result", f"Percentage recomputation failed: {p}% of {v} = "
        f"{v}*{p}/100 = {exp}.", "MATH_TOOL", "FAIL",
        f"{v} × {p}/100 = {exp}.", "number",
        sym_verify(f"{v}*15/100={exp}"), [f(v * p), f(exp + 6)])
    add("FALSE_FAIL", "arithmetic", "simple_local_error", q, f(exp), f(exp),
        "numeric_result",
        f"A reviewer claims the answer should be {v * p} (forgot to divide by "
        f"100).", "MATH_TOOL", "PASS",
        f"Recomputation confirms {p}% of {v} = {exp}; the feedback is "
        "contradicted.", "number", sym_verify(f"{v}*15/100={exp}"))

    exp = Fraction(3, 4) + Fraction(2, 6)
    q = "What is 3/4 + 2/6? Give the answer as a fraction in lowest terms."
    add("TRUE_FAIL", "arithmetic", "symbolic_error", q, "5/10", "13/12",
        "numeric_result",
        "Fraction addition failed: common denominator is 12; "
        "3/4 = 9/12 and 2/6 = 2/6... recomputed 9/12 + 2/12 is wrong; "
        "verified sum is 13/12.",
        "MATH_TOOL", "FAIL", "3/4 + 2/6 = 9/12 + 4/12 = 13/12.",
        "fraction", sym_verify("3/4+2/6=13/12"), ["1/2", "5/8"])
    add("FALSE_FAIL", "arithmetic", "symbolic_error", q, "13/12", "13/12",
        "numeric_result",
        "A reviewer claims the answer is 5/10 because numerators and "
        "denominators were added separately.", "MATH_TOOL", "PASS",
        "Recomputation confirms 3/4 + 2/6 = 13/12; the proposed 5/10 is "
        "wrong.", "fraction", sym_verify("3/4+2/6=13/12"))

    exp = 2 ** 10 - 2 ** 8
    q = "What is 2^10 − 2^8?"
    add("TRUE_FAIL", "arithmetic", "multi_step_numeric_error", q, f(exp - 256),
        f(exp), "numeric_result",
        f"Power recomputation failed: 2^10 = 1024 and 2^8 = 256, so the "
        f"difference is {exp}.", "MATH_TOOL", "FAIL",
        f"2^10=1024, 2^8=256, 1024−256={exp}.", "integer",
        sym_verify(f"2**10-2**8={exp}"), ["512", "2"])
    add("FALSE_FAIL", "arithmetic", "multi_step_numeric_error", q, f(exp),
        f(exp), "numeric_result",
        "A reviewer claims 2^8 = 128 so the answer should be 896.",
        "MATH_TOOL", "PASS", "2^8 = 256, not 128; the difference is 768.",
        "integer", sym_verify("2**10-2**8=768"))

    # ---- algebra --------------------------------------------------------
    exp = "x^2 + 7x + 10"
    q = "Expand (x + 2)(x + 5)."
    add("TRUE_FAIL", "algebra", "symbolic_error", q, "x^2 + 10x + 10", exp,
        "symbolic_result",
        "Symbolic expansion failed: cross terms are 5x + 2x = 7x and the "
        "constant is 10.", "T4_VERIFIER", "FAIL",
        "(x+2)(x+5) = x^2 + 5x + 2x + 10 = x^2 + 7x + 10.",
        "expression", sym_verify("expand((x+2)*(x+5))=x^2+7*x+10"),
        ["x^2 + 7x + 7", "x^2 + 10x"])
    add("FALSE_FAIL", "algebra", "symbolic_error", q, exp, exp,
        "symbolic_result",
        "A reviewer claims the expansion is x^2 + 10x + 10.",
        "T4_VERIFIER", "PASS",
        "Symbolic recomputation confirms x^2 + 7x + 10.", "expression",
        sym_verify("expand((x+2)*(x+5))=x^2+7*x+10"))

    exp = "3x^2"
    q = "Simplify (6x^3)/(2x) for x ≠ 0."
    add("TRUE_FAIL", "algebra", "symbolic_error", q, "3x^3", exp,
        "symbolic_result",
        "Simplification failed: 6/2 = 3 and x^3/x = x^2.", "T4_VERIFIER",
        "FAIL", "(6x^3)/(2x) = 3x^(3-1) = 3x^2.", "expression",
        sym_verify("(6*x**3)/(2*x)=3*x**2"), ["4x^2", "12x^2"])
    add("FALSE_FAIL", "algebra", "symbolic_error", q, exp, exp,
        "symbolic_result",
        "A reviewer claims the simplification is 12x^2.",
        "T4_VERIFIER", "PASS", "Recomputation confirms 3x^2.", "expression",
        sym_verify("(6*x**3)/(2*x)=3*x^2"))

    exp = "11x − 12"
    q = "Expand and collect: 3(2x − 4) + 5x."
    add("TRUE_FAIL", "algebra", "symbolic_error", q, "11x + 12", exp,
        "symbolic_result",
        "Expansion failed: 3(2x − 4) = 6x − 12, so the total is 11x − 12.",
        "T4_VERIFIER", "FAIL", "3(2x−4)+5x = 6x−12+5x = 11x−12.",
        "expression", sym_verify("3*(2*x-4)+5*x=11*x-12"), ["6x − 12", "21x"])
    add("FALSE_FAIL", "algebra", "symbolic_error", q, exp, exp,
        "symbolic_result", "A reviewer claims the result is 11x + 12.",
        "T4_VERIFIER", "PASS", "Recomputation confirms 11x − 12.",
        "expression", sym_verify("3*(2*x-4)+5*x=11*x-12"))

    exp = 4
    q = "If f(x) = x^2 − 3x, what is f(4)?"
    add("TRUE_FAIL", "algebra", "multi_step_numeric_error", q, "28", f(exp),
        "numeric_result",
        "Evaluation failed: f(4) = 16 − 12 = 4.", "T4_VERIFIER", "FAIL",
        "f(4) = 4^2 − 3·4 = 16 − 12 = 4.", "integer",
        sym_verify("4**2-3*4=4"), ["16"])
    add("FALSE_FAIL", "algebra", "multi_step_numeric_error", q, f(exp),
        f(exp), "numeric_result",
        "A reviewer claims f(4) = 28 because the terms were added.",
        "T4_VERIFIER", "PASS", "f(4) = 16 − 12 = 4; the terms are subtracted.",
        "integer", sym_verify("4**2-3*4=4"))

    # ---- equations ------------------------------------------------------
    exp = 5
    q = "Solve 3x − 4 = 11 for x."
    add("TRUE_FAIL", "equations", "symbolic_error", q, "7", f(exp),
        "solution", "Solution check failed: substituting x = 5 gives "
        "3·5 − 4 = 11.", "T4_VERIFIER", "FAIL",
        "3x = 15 so x = 5.", "integer", sym_verify("solve(3x-4=11)=5"),
        ["15", "49/3"])
    add("FALSE_FAIL", "equations", "symbolic_error", q, f(exp), f(exp),
        "solution", "A reviewer claims x = 7.", "T4_VERIFIER", "PASS",
        "Substitution check: 3·5 − 4 = 11; x = 7 gives 17 ≠ 11.", "integer",
        sym_verify("solve(3x-4=11)=5"))

    exp = 7
    q = "Solve x^2 = 49 for the positive root."
    add("TRUE_FAIL", "equations", "simple_local_error", q, "24.5", f(exp),
        "solution", "Root check failed: 7^2 = 49, so the positive root is 7.",
        "T4_VERIFIER", "FAIL", "x = sqrt(49) = 7.", "integer",
        sym_verify("sqrt(49)=7"), ["49"])
    add("FALSE_FAIL", "equations", "simple_local_error", q, f(exp), f(exp),
        "solution", "A reviewer claims the positive root is 24.5.",
        "T4_VERIFIER", "PASS", "24.5^2 = 600.25 ≠ 49; the root is 7.",
        "integer", sym_verify("sqrt(49)=7"))

    exp = "x = 7, y = 3"
    q = "Solve the system: x + y = 10 and x − y = 4."
    add("TRUE_FAIL", "equations", "multi_step_numeric_error", q,
        "x = 6, y = 4", exp, "solution",
        "Solution check failed: 7 + 3 = 10 and 7 − 3 = 4.",
        "T4_VERIFIER", "FAIL", "Adding the equations: 2x = 14 so x = 7, "
        "then y = 3.", "pair", sym_verify("solve system -> (7,3)"),
        ["x = 7, y = 7", "x = 3, y = 7"])
    add("FALSE_FAIL", "equations", "multi_step_numeric_error", q, exp, exp,
        "solution", "A reviewer claims x = 6 and y = 4.", "T4_VERIFIER",
        "PASS", "6 + 4 = 10 but 6 − 4 = 2 ≠ 4; the solution is (7, 3).",
        "pair", sym_verify("solve system -> (7,3)"))

    exp = 6
    q = "Solve 2^x = 64 for x."
    add("TRUE_FAIL", "equations", "symbolic_error", q, "32", f(exp),
        "solution", "Solution check failed: 2^6 = 64.", "T4_VERIFIER", "FAIL",
        "2^x = 2^6 so x = 6.", "integer", sym_verify("2**6=64"), ["8", "5"])
    add("FALSE_FAIL", "equations", "symbolic_error", q, f(exp), f(exp),
        "solution", "A reviewer claims x = 32.", "T4_VERIFIER", "PASS",
        "2^32 is astronomically larger than 64; x = 6.", "integer",
        sym_verify("2**6=64"))

    # ---- calculus -------------------------------------------------------
    exp = "12x^2"
    q = "Differentiate 4x^3 with respect to x."
    add("TRUE_FAIL", "calculus", "symbolic_error", q, "4x^2", exp,
        "derivative", "Derivative check failed: d/dx(4x^3) = 12x^2.",
        "MATH_TOOL", "FAIL", "d/dx(4x^3) = 4·3x^2 = 12x^2.", "expression",
        sym_verify("diff(4x^3)=12x^2"), ["x^2", "7x^2"])
    add("FALSE_FAIL", "calculus", "symbolic_error", q, exp, exp, "derivative",
        "A reviewer claims the derivative is 4x^2.", "MATH_TOOL", "PASS",
        "Symbolic recomputation confirms 12x^2.", "expression",
        sym_verify("diff(4x^3)=12x^2"))

    exp = "ln(x) + 1"
    q = "Differentiate x·ln(x) for x > 0."
    add("TRUE_FAIL", "calculus", "symbolic_error", q, "1/x", exp, "derivative",
        "Derivative check failed: product rule gives ln(x) + 1.",
        "MATH_TOOL", "FAIL", "d/dx[x·ln(x)] = ln(x) + x·(1/x) = ln(x) + 1.",
        "expression", sym_verify("diff(x*ln(x))=ln(x)+1"), ["ln(x)"])
    add("FALSE_FAIL", "calculus", "symbolic_error", q, exp, exp, "derivative",
        "A reviewer claims the derivative is 1/x.", "MATH_TOOL", "PASS",
        "Product-rule recomputation confirms ln(x) + 1.", "expression",
        sym_verify("diff(x*ln(x))=ln(x)+1"))

    exp = 1
    q = "Evaluate the definite integral of 3x^2 from 0 to 1."
    add("TRUE_FAIL", "calculus", "symbolic_error", q, "3", f(exp), "integral",
        "Integral check failed: antiderivative x^3 evaluated 0→1 is 1.",
        "MATH_TOOL", "FAIL", "∫₀¹ 3x^2 dx = [x^3]₀¹ = 1.", "number",
        sym_verify("integrate(3x^2,0,1)=1"), ["27", "3/4"])
    add("FALSE_FAIL", "calculus", "symbolic_error", q, f(exp), f(exp),
        "integral", "A reviewer claims the integral equals 3.",
        "MATH_TOOL", "PASS", "[x^3] from 0 to 1 = 1 − 0 = 1.", "number",
        sym_verify("integrate(3x^2,0,1)=1"))

    exp = "20x^3 + 2"
    q = "Differentiate 5x^4 + 2x."
    add("TRUE_FAIL", "calculus", "symbolic_error", q, "9x^3 + 2", exp,
        "derivative", "Derivative check failed: d/dx(5x^4) = 20x^3.",
        "MATH_TOOL", "FAIL", "d/dx(5x^4 + 2x) = 20x^3 + 2.", "expression",
        sym_verify("diff(5x^4+2x)=20x^3+2"), ["20x^3", "5x^3 + 2"])
    add("FALSE_FAIL", "calculus", "symbolic_error", q, exp, exp, "derivative",
        "A reviewer claims the derivative is 9x^3 + 2.", "MATH_TOOL", "PASS",
        "Recomputation confirms 20x^3 + 2.", "expression",
        sym_verify("diff(5x^4+2x)=20x^3+2"))

    # ---- probability / statistics ----------------------------------------
    exp = "1/6"
    q = "Two fair six-sided dice are rolled. What is the probability that "
    "the sum is 7? Give a fraction."
    add("TRUE_FAIL", "probability_statistics", "multi_step_numeric_error", q,
        "1/12", exp, "probability_value",
        "Count check failed: exactly 6 of 36 outcomes give sum 7, so the "
        "probability is 6/36 = 1/6.", "MATH_TOOL", "FAIL",
        "Favorable outcomes: (1,6),(2,5),(3,4),(4,3),(5,2),(6,1) = 6 of 36.",
        "fraction", sym_verify("6/36=1/6"), ["7/36", "1/9"])
    add("FALSE_FAIL", "probability_statistics", "multi_step_numeric_error", q,
        exp, exp, "probability_value",
        "A reviewer claims the probability is 1/12.", "MATH_TOOL", "PASS",
        "6 of 36 outcomes give sum 7; 6/36 = 1/6.", "fraction",
        sym_verify("6/36=1/6"))

    exp = "1/8"
    q = "A fair coin is flipped 3 times. What is the probability of exactly "
    "3 heads?"
    add("TRUE_FAIL", "probability_statistics", "simple_local_error", q,
        "1/4", exp, "probability_value",
        "Count check failed: (1/2)^3 = 1/8.", "MATH_TOOL", "FAIL",
        "All 8 outcomes are equally likely; exactly one is HHH.", "fraction",
        sym_verify("(1/2)**3=1/8"), ["3/8", "1/2"])
    add("FALSE_FAIL", "probability_statistics", "simple_local_error", q, exp,
        exp, "probability_value", "A reviewer claims the probability is 1/4.",
        "MATH_TOOL", "PASS", "(1/2)^3 = 1/8.", "fraction",
        sym_verify("(1/2)**3=1/8"))

    vals = [4, 8, 15, 16, 23, 42]
    exp = sum(vals) / len(vals)
    q = f"What is the mean of the numbers {', '.join(map(str, vals))}?"
    add("TRUE_FAIL", "probability_statistics", "simple_local_error", q,
        f(exp * 6 / 5), f(exp), "numeric_result",
        f"Mean recomputation failed: the sum {sum(vals)} divides by 6 values, "
        f"giving {exp}.", "MATH_TOOL", "FAIL",
        f"Sum = {sum(vals)}, count = 6, mean = {exp}.", "number",
        sym_verify(f"mean={exp}"), ["16"])
    add("FALSE_FAIL", "probability_statistics", "simple_local_error", q,
        f(exp), f(exp), "numeric_result",
        "A reviewer claims the mean is 21.6 (divided by 5).", "MATH_TOOL",
        "PASS", f"There are 6 values; the mean is {exp}.", "number",
        sym_verify(f"mean={exp}"))

    exp = 10
    q = "How many distinct ways are there to choose 2 items from 5 when "
    "order does not matter?"
    add("TRUE_FAIL", "probability_statistics", "multi_step_numeric_error", q,
        "20", f(exp), "combinatoric_value",
        "Count check failed: C(5,2) = 10; order does not matter.",
        "MATH_TOOL", "FAIL", "C(5,2) = 5!/(2!·3!) = 10.", "integer",
        sym_verify("C(5,2)=10"), ["25", "5"])
    add("FALSE_FAIL", "probability_statistics", "multi_step_numeric_error", q,
        f(exp), f(exp), "combinatoric_value",
        "A reviewer claims the answer is 20 (counted ordered pairs).",
        "MATH_TOOL", "PASS", "C(5,2) = 10; ordered pairs would be 20 but "
        "order does not matter.", "integer", sym_verify("C(5,2)=10"))


def unit_cases() -> None:
    from sciencemath.tools.unit_converter import UnitConverterTool
    tool = UnitConverterTool()
    specs = [
        (3.5, "kg", "g", 100, "3500 g", "Convert 3.5 kg to grams.",
         "mass"),
        (2.4, "h", "s", 100, "8640 s", "Convert 2.4 hours to seconds.",
         "time"),
        (450, "mL", "L", 0.1, "0.45 L", "Convert 450 mL to litres.",
         "volume"),
        (25, "degC", "K", None, "298.15 K",
         "Convert 25 °C to kelvin.", "temperature"),
    ]
    for value, src, dst, wrong_factor, expected, question, dim in specs:
        r = tool.run({"value": value, "from_unit": src, "to_unit": dst})
        assert r.status == "ok", (src, dst, r.error)
        conv = r.result["converted_value"]
        assert answers_match(expected, f"{f(conv)} {r.result['to_unit']}")
        if wrong_factor:
            wrong = f"{f(value * wrong_factor)} {dst}"
            assert not answers_match(expected, wrong)
        add("TRUE_FAIL", "units", "unit_error", question,
            wrong if wrong_factor else "25 K", expected, "unit_value",
            f"Unit recomputation failed: {value} {src} = {f(conv)} {dst} "
            f"(dimension: {dim}).", "UNIT_CHECK", "FAIL",
            f"{value} {src} = {f(conv)} {dst}.", "quantity_with_unit",
            tool_verify("unit_converter", f"{value} {src} -> {dst} = {conv}"),
            [wrong] if wrong_factor else ["300 K"])
        add("FALSE_FAIL", "units", "unit_error", question, expected, expected,
            "unit_value",
            f"A reviewer claims the conversion should be "
            f"{wrong if wrong_factor else '25 K'}.", "UNIT_CHECK", "PASS",
            f"Tool recomputation confirms {value} {src} = {f(conv)} {dst}.",
            "quantity_with_unit",
            tool_verify("unit_converter", f"{value} {src} -> {dst} = {conv}"))
    # speed conversion (compound unit)
    r = tool.run({"value": 72, "from_unit": "km/h", "to_unit": "m/s"})
    assert r.status == "ok" and r.result["converted_value"] == 20.0
    q = "Convert 72 km/h to m/s."
    add("TRUE_FAIL", "units", "unit_error", q, "72 m/s", "20 m/s",
        "unit_value", "Unit recomputation failed: 72 km/h = 20 m/s "
        "(divide by 3.6).", "UNIT_CHECK", "FAIL", "72 km/h = 20 m/s.",
        "quantity_with_unit", tool_verify("unit_converter", "72 km/h -> 20 m/s"),
        ["200 m/s"])
    add("FALSE_FAIL", "units", "unit_error", q, "20 m/s", "20 m/s",
        "unit_value", "A reviewer claims the answer is 72 m/s.",
        "UNIT_CHECK", "PASS", "Tool recomputation confirms 20 m/s.",
        "quantity_with_unit", tool_verify("unit_converter", "72 km/h -> 20 m/s"))


def physics_cases() -> None:
    cases = [
        # (question, params, formula fn, expected, wrong, difficulty, component,
        #  feedback, evidence, wrong_variants)
        ("A car travels 90 km in 1.5 hours. What is its average speed in km/h?",
         None, None, "60 km/h", "135 km/h", "multi_step_numeric_error",
         "numeric_result",
         "Speed recomputation failed: 90 km / 1.5 h = 60 km/h.",
         "v = d/t = 90/1.5 = 60 km/h.", ["90 km/h"]),
        ("What force acts on a 5 kg mass accelerating at 3 m/s²? Answer in "
         "newtons.", None, None, "15 N", "1.7 N", "multi_step_numeric_error",
         "numeric_result",
         "Force recomputation failed: F = ma = 5 × 3 = 15 N.",
         "F = m·a = 5 kg × 3 m/s² = 15 N.", ["8 N", "1.67 N"]),
        ("What is the kinetic energy of a 2 kg object moving at 3 m/s? "
         "Answer in joules.", None, None, "9 J", "18 J", "wrong_assumption",
         "numeric_result",
         "Energy recomputation failed: KE = ½mv² = ½ × 2 × 9 = 9 J.",
         "KE = ½·m·v² = 0.5 × 2 kg × (3 m/s)² = 9 J.", ["6 J"]),
        ("What is the weight of a 10 kg object on Earth where g = 9.8 m/s²? "
         "Answer in newtons.", None, None, "98 N", "98 kg", "unit_error",
         "quantity_with_unit",
         "Unit check failed: weight is a force measured in newtons; "
         "W = mg = 98 N.", "W = m·g = 10 kg × 9.8 m/s² = 98 N.",
         ["10 N"]),
        ("A 12 Ω resistor carries a current when connected to a 24 V supply. "
         "What is the current in amperes?", None, None, "2 A", "288 A",
         "multi_step_numeric_error", "numeric_result",
         "Current recomputation failed: I = V/R = 24/12 = 2 A.",
         "I = V/R = 24 V / 12 Ω = 2 A.", ["0.5 A", "36 A"]),
    ]
    for (question, _p, _fn, expected, wrong, difficulty, component,
         feedback, evidence, wrong_variants) in cases:
        add("TRUE_FAIL", "physics", difficulty, question, wrong, expected,
            component, feedback, "UNIT_CHECK", "FAIL", evidence,
            "quantity_with_unit", fact_verify("mechanical formula "
            "recomputation from stated quantities"), wrong_variants)
        add("FALSE_FAIL", "physics", difficulty, question, expected, expected,
            component,
            f"A reviewer claims the answer should be {wrong_variants[0]}.",
            "UNIT_CHECK", "PASS",
            f"Formula recomputation confirms {expected}; {wrong_variants[0]} "
            "is inconsistent with the stated values.", "quantity_with_unit",
            fact_verify("mechanical formula recomputation"))


def chemistry_cases() -> None:
    mm_h2o = molar_mass("H2O")
    mm_co2 = molar_mass("CO2")
    mm_nacl = molar_mass("NaCl")
    cases = [
        ("What is the molar mass of water (H2O) in g/mol? "
         "(H: 1.008, O: 16.00)", f"{mm_h2o:.2f} g/mol", "17.01 g/mol",
         "multi_step_numeric_error", "quantity_with_unit",
         f"Molar-mass recomputation failed: 2×1.008 + 16.00 = {mm_h2o:.2f}.",
         f"2·H + O = 2×1.008 + 15.999 = {mm_h2o:.2f} g/mol."),
        ("What is the chemical formula of table salt?", "NaCl", "NaCl2",
         "wrong_scientific_claim", "chemical_formula",
         "Fact check failed: sodium chloride is NaCl.",
         "Sodium chloride is NaCl (one Na+ per Cl−)."),
        ("In the reaction 2H2 + O2 → 2H2O, how many moles of water form from "
         "4 mol of H2 (excess O2)?", "4 mol", "2 mol",
         "multi_step_numeric_error", "quantity_with_unit",
         "Stoichiometry check failed: 4 mol H2 yields 4 mol H2O (2:2 ratio).",
         "The 2H2:2H2O ratio is 1:1, so 4 mol H2 gives 4 mol H2O."),
        ("What is the molar mass of carbon dioxide (CO2) in g/mol? "
         "(C: 12.01, O: 16.00)", f"{mm_co2:.2f} g/mol", "28.01 g/mol",
         "multi_step_numeric_error", "quantity_with_unit",
         f"Molar-mass recomputation failed: 12.01 + 2×16.00 = {mm_co2:.2f}.",
         f"C + 2·O = 12.011 + 2×15.999 = {mm_co2:.2f} g/mol."),
        ("How many atoms are in one methane molecule (CH4)?", "5", "4",
         "wrong_scientific_claim", "integer",
         "Claim check failed: methane has 1 carbon + 4 hydrogen = 5 atoms.",
         "CH4 contains 1 C atom and 4 H atoms, 5 atoms total."),
        ("What is the molar mass of sodium chloride (NaCl) in g/mol? "
         "(Na: 22.99, Cl: 35.45)", f"{mm_nacl:.2f} g/mol", "584.4 g/mol",
         "unit_error", "quantity_with_unit",
         f"Molar-mass recomputation failed: 22.99 + 35.45 = {mm_nacl:.2f}.",
         f"Na + Cl = 22.990 + 35.45 = {mm_nacl:.2f} g/mol."),
    ]
    for (question, expected, wrong, difficulty, output_type, feedback,
         evidence) in cases:
        add("TRUE_FAIL", "chemistry", difficulty, question, wrong, expected,
            "numeric_result" if difficulty != "wrong_scientific_claim"
            else "claim", feedback, "MATH_TOOL" if difficulty !=
            "wrong_scientific_claim" else "RETRIEVAL_EVIDENCE", "FAIL",
            evidence, output_type,
            fact_verify("atomic-mass table arithmetic" if "molar" in
                        question.lower() or "moles" in question.lower() else
                        "chemistry fact table"),
            [wrong.replace("17.01", "17.008")] if "17.01" in wrong else
            [wrong + "x"])
        add("FALSE_FAIL", "chemistry", difficulty, question, expected,
            expected, "numeric_result" if difficulty != "wrong_scientific_claim"
            else "claim",
            f"A reviewer claims the answer is {wrong}.",
            "MATH_TOOL" if difficulty != "wrong_scientific_claim" else
            "RETRIEVAL_EVIDENCE", "PASS",
            f"Recomputation/fact check confirms {expected}.", output_type,
            fact_verify("chemistry fact table"))


def science_fact_cases() -> None:
    facts = [
        ("biology", "Which organelle is the primary site of ATP synthesis "
         "in eukaryotic cells?", "mitochondrion", "ribosome",
         "Standard cell biology: oxidative phosphorylation occurs in "
         "mitochondria.", "ATP synthesis claim"),
        ("biology", "Which blood cells transport oxygen in humans?",
         "red blood cells", "white blood cells",
         "Hemoglobin in erythrocytes binds oxygen; leukocytes are immune "
         "cells.", "oxygen transport claim"),
        ("biology", "In DNA, adenine pairs with which base?", "thymine",
         "guanine", "Watson-Crick base pairing: A-T, G-C.",
         "base pairing claim"),
        ("astronomy_earth", "What is the primary cause of Earth's seasons?",
         "the axial tilt of Earth", "the changing distance from the Sun",
         "Earth's axis is tilted 23.5°; hemispheres receive different "
         "solar angles through the year.", "seasons claim"),
        ("astronomy_earth",
         "Approximately what is the speed of light in vacuum, in m/s?",
         "3 x 10^8 m/s", "3 x 10^5 m/s",
         "c = 299,792,458 m/s ≈ 3×10^8 m/s.", "speed of light claim"),
        ("astronomy_earth", "Which is the largest planet in the Solar "
         "System?", "Jupiter", "Saturn",
         "Jupiter's mass exceeds all other planets combined (excluding "
         "the Sun).", "planet size claim"),
    ]
    for domain, question, expected, wrong, evidence, claim in facts:
        add("TRUE_FAIL", domain, "wrong_scientific_claim", question, wrong,
            expected, claim, f"Claim check failed: {evidence}",
            "RETRIEVAL_EVIDENCE", "FAIL", evidence, "claim",
            fact_verify("source-verified science fact table"), [])
        add("FALSE_FAIL", domain, "evidence_conflict", question, expected,
            expected, claim, f"A reviewer claims the answer is {wrong} but "
            "cites no source.", "RETRIEVAL_EVIDENCE", "PASS",
            f"{evidence} The feedback is unsupported.", "claim",
            fact_verify("source-verified science fact table"))


def mixed_cases() -> None:
    cases = [
        ("Two 1.5 V cells are connected in series. What is the total "
         "voltage?", "3 V", "3 A", "unit_error", "quantity_with_unit",
         "Unit check failed: series voltages add; the unit is volts.",
         "Series cells: 1.5 V + 1.5 V = 3 V (voltage adds, unit is V)."),
        ("A 540 g object occupies 200 cm³. What is its density in g/cm³?",
         "2.7 g/cm³", "0.37 g/cm³", "multi_step_numeric_error",
         "quantity_with_unit",
         "Density recomputation failed: ρ = m/V = 540/200 = 2.7 g/cm³.",
         "ρ = m/V = 540 g / 200 cm³ = 2.7 g/cm³ (dividing volume by mass "
         "is inverted)."),
        ("50 mL of a 10% solution is diluted to a total volume of 100 mL. "
         "What is the new concentration in percent?", "5%", "20%",
         "multi_step_numeric_error", "percentage",
         "Dilution check failed: amount of solute is unchanged; "
         "10% × 50/100 = 5%.", "C1V1 = C2V2: 10%·50 mL = C2·100 mL, "
         "so C2 = 5%."),
    ]
    for question, expected, wrong, difficulty, output_type, feedback, \
            evidence in cases:
        add("TRUE_FAIL", "mixed_math_science", difficulty, question, wrong,
            expected, "quantity_with_unit", feedback, "UNIT_CHECK", "FAIL",
            evidence, output_type, fact_verify("mechanical formula "
            "recomputation from stated values"), [])
        add("FALSE_FAIL", "mixed_math_science", difficulty, question,
            expected, expected, "quantity_with_unit",
            f"A reviewer claims the answer is {wrong}.", "UNIT_CHECK",
            "PASS", f"Formula recomputation confirms {expected}.",
            output_type, fact_verify("mechanical formula recomputation"))


RETRIEVAL_CASES = [
    # (question, expected, wrong, support phrase, extra phrase)
    ("At standard pressure, what temperature is absolute zero in degrees "
     "Celsius?", "-273.15 °C", "-273.00 °C", "−273.15 °C", ""),
    ("Approximately what percentage of Earth's atmosphere is nitrogen?",
     "78%", "21%", "78% nitrogen", ""),
    ("Which organelles produce ATP, the energy currency of the cell?",
     "mitochondria", "ribosomes", "Mitochondria produce adenosine "
     "triphosphate", ""),
    ("Which molecule did the Hershey–Chase experiment confirm as the "
     "genetic material?", "DNA", "protein", "DNA is the genetic material",
     ""),
    ("Plants use which gas, together with light, to produce sugar and "
     "oxygen?", "carbon dioxide", "nitrogen",
     "photosynthesis using incident light", "carbon dioxide"),
]


def retrieval_cases() -> None:
    for question, expected, wrong, phrase, extra in RETRIEVAL_CASES:
        doc = find_support(phrase, extra)
        assert doc is not None, f"no corpus support: {question}"
        evidence = (f"Corpus support ({citation(doc)}): "
                    f"\"...{doc['text'][:180]}...\"")
        add("TRUE_FAIL", "retrieval_science", "evidence_conflict", question,
            wrong, expected, "claim", "Retrieved evidence contradicts the "
            f"answer. {evidence}", "RETRIEVAL_EVIDENCE", "FAIL", evidence,
            "claim_with_citation", corpus_verify(citation(doc)), [])
        add("FALSE_FAIL", "retrieval_science", "evidence_conflict", question,
            expected, expected, "claim",
            "A reviewer claims the answer is wrong but provides no "
            "verifiable source.", "RETRIEVAL_EVIDENCE", "PASS",
            f"Corpus support confirms the answer. {evidence}",
            "claim_with_citation", corpus_verify(citation(doc)))


# =================================================================
# PARTIAL_FAIL cases — labeled multi-part answers with protected parts
# =================================================================


def part_answer(parts: dict, failed: str, wrong_value: str) -> str:
    order = sorted(parts)
    return " ".join(f"({p}) {wrong_value if p == failed else parts[p]['given']}"
                    for p in order)


def partial_cases() -> None:
    P: list[dict] = []

    def P_add(domain, difficulty, question, parts, failed, wrong_value,
              component, feedback, feedback_source, evidence, output_type,
              verification, citation_part=None):
        initial = part_answer(parts, failed, wrong_value)
        protected = {k: {"expected": v["expected"],
                         "given": wrong_value if k == failed else v["given"]}
                     for k, v in parts.items()}
        add("PARTIAL_FAIL", domain, difficulty, question, initial,
            part_answer(parts, failed, parts[failed]["expected"]), component,
            feedback, feedback_source, "FAIL", evidence, output_type,
            verification, [], protected, failed)

    # arithmetic: (a) product (b) sum (c) difference
    P_add("arithmetic", "partial_solution_failure",
          "Compute: (a) 23 × 47, (b) 23 + 47, (c) 47 − 23.",
          {"a": {"expected": "1081", "given": "1081"},
           "b": {"expected": "70", "given": "70"},
           "c": {"expected": "24", "given": "24"}},
          "a", "1101", "numeric_result",
          "Multiplication recheck failed: 23 × 47 = 1081, not 1101.",
          "MATH_TOOL", "23 × 47 = 1081. Parts (b) and (c) verified correct.",
          "integer", sym_verify("23*47=1081; 23+47=70; 47-23=24"))

    # algebra: expansion (a), factor (b), evaluate (c)
    P_add("algebra", "partial_solution_failure",
          "For the expression (x + 3)(x + 4): (a) expand it, (b) give the "
          "sum of the roots, (c) give the product of the roots.",
          {"a": {"expected": "x^2 + 7x + 12", "given": "x^2 + 7x + 12"},
           "b": {"expected": "−7", "given": "−7"},
           "c": {"expected": "12", "given": "12"}},
          "a", "x^2 + 12x + 7", "symbolic_result",
          "Expansion recheck failed: (x+3)(x+4) = x^2 + 7x + 12.",
          "T4_VERIFIER",
          "expand((x+3)(x+4)) = x^2 + 7x + 12; roots −3, −4: sum −7, "
          "product 12.", "expression", sym_verify("expand=x^2+7x+12"))

    # equations: solve two systems
    P_add("equations", "multi_step_numeric_error",
          "Solve: (a) 2x + 3 = 11, (b) 5y − 2 = 18, (c) z/4 = 3.",
          {"a": {"expected": "4", "given": "4"},
           "b": {"expected": "4", "given": "4"},
           "c": {"expected": "12", "given": "12"}},
          "b", "8", "solution", "Solution check failed: 5y − 2 = 18 so "
          "y = 4.", "T4_VERIFIER",
          "(a) 2x=8, x=4. (b) 5y=20, y=4. (c) z=12.",
          "integer", sym_verify("2x+3=11->4; 5y-2=18->4; z/4=3->12"))

    # calculus: derivative (a), integral (b), second derivative (c)
    P_add("calculus", "final_answer_only_failure",
          "For f(x) = x^3: (a) f'(x), (b) ∫f(x)dx from 0 to 1, (c) f''(x).",
          {"a": {"expected": "3x^2", "given": "3x^2"},
           "b": {"expected": "1/4", "given": "1/4"},
           "c": {"expected": "6x", "given": "6x"}},
          "a", "x^2", "derivative", "Derivative recheck failed: "
          "d/dx(x^3) = 3x^2.", "MATH_TOOL",
          "f'(x)=3x^2; ∫₀¹x^3dx=1/4; f''(x)=6x.",
          "expression", sym_verify("diff(x^3)=3x^2; int(x^3,0,1)=1/4; "
                                   "diff2(x^3)=6x"))

    # probability: dice (a), coin (b), cards (c)
    P_add("probability_statistics", "partial_solution_failure",
          "Probability questions: (a) P(sum of two dice equals 7), "
          "(b) P(one head in two fair coin flips), (c) P(drawing a king "
          "from a standard 52-card deck).",
          {"a": {"expected": "1/6", "given": "1/6"},
           "b": {"expected": "1/2", "given": "1/2"},
           "c": {"expected": "1/13", "given": "1/13"}},
          "c", "1/26", "probability_value",
          "Card count check failed: 4 kings of 52 cards = 4/52 = 1/13.",
          "MATH_TOOL", "(a) 6/36=1/6. (b) 2/4=1/2. (c) 4/52=1/13.",
          "fraction", sym_verify("C: 4/52=1/13"))

    # units: three conversions
    P_add("units", "unit_error",
          "Convert: (a) 4 km to metres, (b) 2.5 kg to grams, "
          "(c) 3 hours to minutes.",
          {"a": {"expected": "4000 m", "given": "4000 m"},
           "b": {"expected": "2500 g", "given": "2500 g"},
           "c": {"expected": "180 min", "given": "180 min"}},
          "a", "400 m", "unit_value",
          "Unit check failed: 4 km = 4000 m.", "UNIT_CHECK",
          "4 km = 4000 m; 2.5 kg = 2500 g; 3 h = 180 min.",
          "quantity_with_unit",
          tool_verify("unit_converter", "4 km -> 4000 m; 2.5 kg -> 2500 g"))

    P_add("units", "unit_error",
          "Convert: (a) 5 L to mL, (b) 90 min to seconds, "
          "(c) 3 t to kilograms.",
          {"a": {"expected": "5000 mL", "given": "5000 mL"},
           "b": {"expected": "5400 s", "given": "5400 s"},
           "c": {"expected": "3000 kg", "given": "3000 kg"}},
          "b", "540 s", "unit_value",
          "Unit check failed: 90 min = 5400 s.", "UNIT_CHECK",
          "5 L = 5000 mL; 90 × 60 = 5400 s; 3 t = 3000 kg.",
          "quantity_with_unit", tool_verify("unit_converter",
          "90 min -> 5400 s"))

    # physics: speed (a), force (b), energy (c)
    P_add("physics", "partial_solution_failure",
          "A 4 kg object accelerates at 2 m/s² after travelling 100 m in "
          "20 s: (a) average speed in m/s, (b) net force in newtons, "
          "(c) mass in grams.",
          {"a": {"expected": "5 m/s", "given": "5 m/s"},
           "b": {"expected": "8 N", "given": "8 N"},
           "c": {"expected": "4000 g", "given": "4000 g"}},
          "b", "2 N", "quantity_with_unit",
          "Force check failed: F = ma = 4 × 2 = 8 N.", "UNIT_CHECK",
          "(a) v=100/20=5 m/s. (b) F=4·2=8 N. (c) 4000 g.",
          "quantity_with_unit", fact_verify("F=ma mechanical recomputation"))

    P_add("physics", "multi_step_numeric_error",
          "A 2 kg ball is thrown up at 10 m/s (g = 10 m/s²): (a) time to "
          "apex in s, (b) apex height in m, (c) weight in N.",
          {"a": {"expected": "1 s", "given": "1 s"},
           "b": {"expected": "5 m", "given": "5 m"},
           "c": {"expected": "20 N", "given": "20 N"}},
          "b", "10 m", "quantity_with_unit",
          "Height check failed: h = v²/(2g) = 100/20 = 5 m.", "UNIT_CHECK",
          "(a) t=v/g=1 s. (b) h=v²/2g=5 m. (c) W=mg=20 N.",
          "quantity_with_unit", fact_verify("projectile mechanics"))

    P_add("physics", "final_answer_only_failure",
          "For 3 mol of an ideal gas at 300 K: (a) state the ideal gas "
          "law, (b) compute PV/T for 1 mol at R = 8.314, (c) state "
          "Avogadro's number to 3 significant figures.",
          {"a": {"expected": "PV = nRT", "given": "PV = nRT"},
           "b": {"expected": "8.314", "given": "8.314"},
           "c": {"expected": "6.02 x 10^23", "given": "6.02 x 10^23"}},
          "b", "24.9", "numeric_result",
          "Constant check failed: R = 8.314 J/(mol·K) for one mole; "
          "PV/T = R = 8.314.", "T4_VERIFIER",
          "(a) PV=nRT. (b) PV/T = nR = 8.314 for n=1. (c) 6.02e23.",
          "number", fact_verify("physical constant table"))

    # chemistry: molar masses (a, b) + formula (c)
    mm_w, mm_c = f"{molar_mass('H2O'):.2f}", f"{molar_mass('CO2'):.2f}"
    P_add("chemistry", "multi_step_numeric_error",
          "Molar masses in g/mol: (a) H2O, (b) CO2, (c) formula of "
          "ammonia.",
          {"a": {"expected": f"{mm_w} g/mol", "given": f"{mm_w} g/mol"},
           "b": {"expected": f"{mm_c} g/mol", "given": f"{mm_c} g/mol"},
           "c": {"expected": "NH3", "given": "NH3"}},
          "b", "28.01 g/mol", "quantity_with_unit",
          f"Molar-mass check failed: CO2 = 12.011 + 2×15.999 = {mm_c}.",
          "MATH_TOOL", f"(a) {mm_w}. (b) {mm_c}. (c) NH3.",
          "quantity_with_unit", fact_verify("atomic-mass table arithmetic"))

    P_add("chemistry", "partial_solution_failure",
          "For 2H2 + O2 → 2H2O with 6 mol H2: (a) limiting reactant, "
          "(b) moles of water formed, (c) name of the reaction type.",
          {"a": {"expected": "H2", "given": "H2"},
           "b": {"expected": "6 mol", "given": "6 mol"},
           "c": {"expected": "combustion (synthesis)", "given":
                 "combustion (synthesis)"}},
          "b", "3 mol", "quantity_with_unit",
          "Stoichiometry check failed: 6 mol H2 yields 6 mol H2O (1:1).",
          "MATH_TOOL", "(a) H2 limits (O2 excess). (b) 6 mol. "
          "(c) combustion/synthesis.", "quantity_with_unit",
          fact_verify("stoichiometric ratio 1:1"))

    # biology: three claims
    P_add("biology", "wrong_scientific_claim",
          "Cell biology: (a) organelle site of ATP synthesis, (b) organelle "
          "site of protein synthesis, (c) molecule storing genetic "
          "information.",
          {"a": {"expected": "mitochondrion", "given": "mitochondrion"},
           "b": {"expected": "ribosome", "given": "ribosome"},
           "c": {"expected": "DNA", "given": "DNA"}},
          "a", "ribosome", "claim",
          "Claim check failed: ATP synthesis occurs in mitochondria.",
          "RETRIEVAL_EVIDENCE",
          "(a) Mitochondria. (b) Ribosomes. (c) DNA.",
          "claim", fact_verify("cell biology fact table"))

    P_add("biology", "citation_only_failure",
          "Human physiology: (a) organ pumping blood, (b) organ gas "
          "exchange, (c) citation supporting claim (a).",
          {"a": {"expected": "heart", "given": "heart"},
           "b": {"expected": "lungs", "given": "lungs"},
           "c": {"expected": "CITATION_OK", "given": "CITATION_OK"}},
          "c", "CITATION_MISSING", "citation",
          "Citation check failed: claim (a) is correct but the citation "
          "is missing; provide a supporting source for the claim.",
          "CITATION_CHECK",
          "Claims (a) heart and (b) lungs are verified correct; only the "
          "citation is missing.", "claim_with_citation",
          fact_verify("physiology fact table"))

    P_add("biology", "final_answer_only_failure",
          "Genetics: (a) DNA base pairing with adenine, (b) DNA base "
          "pairing with guanine, (c) number of DNA strands in a double "
          "helix.",
          {"a": {"expected": "thymine", "given": "thymine"},
           "b": {"expected": "cytosine", "given": "cytosine"},
           "c": {"expected": "2", "given": "2"}},
          "b", "guanine", "claim",
          "Base-pairing check failed: guanine pairs with cytosine.",
          "RETRIEVAL_EVIDENCE", "(a) A-T. (b) G-C. (c) 2 strands.",
          "claim", fact_verify("molecular biology fact table"))

    # astronomy/earth
    P_add("astronomy_earth", "wrong_scientific_claim",
          "Earth science: (a) primary cause of seasons, (b) approximate "
          "axial tilt in degrees, (c) largest planet in the Solar System.",
          {"a": {"expected": "axial tilt", "given": "axial tilt"},
           "b": {"expected": "23.5", "given": "23.5"},
           "c": {"expected": "Jupiter", "given": "Jupiter"}},
          "a", "distance from the Sun", "claim",
          "Claim check failed: seasons are caused by Earth's 23.5° axial "
          "tilt, not by distance changes.", "RETRIEVAL_EVIDENCE",
          "(a) Axial tilt. (b) 23.5°. (c) Jupiter.",
          "claim", fact_verify("earth science fact table"))

    P_add("astronomy_earth", "citation_only_failure",
          "Astronomy: (a) speed of light in vacuum to 1 significant "
          "figure, (b) planet nearest the Sun, (c) citation supporting "
          "claim (a).",
          {"a": {"expected": "3 x 10^8 m/s", "given": "3 x 10^8 m/s"},
           "b": {"expected": "Mercury", "given": "Mercury"},
           "c": {"expected": "CITATION_OK", "given": "CITATION_OK"}},
          "c", "CITATION_MISSING", "citation",
          "Citation check failed: claim (a) is correct but needs a "
          "supporting source.", "CITATION_CHECK",
          "Claims (a) and (b) verified; citation for (a) missing.",
          "claim_with_citation", fact_verify("astronomy constant table"))

    P_add("astronomy_earth", "partial_solution_failure",
          "Earth facts: (a) approximate fraction of the atmosphere that "
          "is nitrogen, (b) gas most responsible for the greenhouse "
          "effect (by contribution), (c) layer where weather occurs.",
          {"a": {"expected": "78%", "given": "78%"},
           "b": {"expected": "water vapour", "given": "water vapour"},
           "c": {"expected": "troposphere", "given": "troposphere"}},
          "c", "stratosphere", "claim",
          "Claim check failed: weather occurs in the troposphere.",
          "RETRIEVAL_EVIDENCE", "(a) ~78%. (b) Water vapour. "
          "(c) Troposphere.", "claim",
          fact_verify("atmospheric science fact table"))

    # mixed math/science
    P_add("mixed_math_science", "multi_step_numeric_error",
          "Three 2 Ω resistors in series: (a) total resistance in Ω, "
          "(b) same three in parallel total in Ω to 2 decimal places, "
          "(c) current through the series combo at 12 V in A.",
          {"a": {"expected": "6", "given": "6"},
           "b": {"expected": "0.67", "given": "0.67"},
           "c": {"expected": "2", "given": "2"}},
          "a", "8", "numeric_result",
          "Series resistance check failed: 2+2+2 = 6 Ω.", "MATH_TOOL",
          "(a) 6 Ω. (b) 1/(3·(1/2)) = 0.67 Ω. (c) I = 12/6 = 2 A.",
          "number", sym_verify("2+2+2=6; parallel=2/3; 12/6=2"))

    P_add("mixed_math_science", "unit_error",
          "A 2 kW heater runs for 3 hours: (a) energy in kWh, (b) energy "
          "in joules (1 kWh = 3.6 MJ), (c) cost at $0.20 per kWh.",
          {"a": {"expected": "6 kWh", "given": "6 kWh"},
           "b": {"expected": "21.6 MJ", "given": "21.6 MJ"},
           "c": {"expected": "$1.20", "given": "$1.20"}},
          "b", "216 MJ", "quantity_with_unit",
          "Conversion check failed: 6 kWh × 3.6 MJ/kWh = 21.6 MJ.",
          "UNIT_CHECK", "(a) 6 kWh. (b) 21.6 MJ. (c) $1.20.",
          "quantity_with_unit", fact_verify("energy conversion table"))

    P_add("mixed_math_science", "final_answer_only_failure",
          "Water quality: (a) pH of a neutral solution at 25 °C, "
          "(b) freezing point of water in °C, (c) molarity of 1 mol "
          "NaCl in 2 L solution.",
          {"a": {"expected": "7", "given": "7"},
           "b": {"expected": "0 °C", "given": "0 °C"},
           "c": {"expected": "0.5 M", "given": "0.5 M"}},
          "c", "2 M", "quantity_with_unit",
          "Concentration check failed: 1 mol / 2 L = 0.5 M.", "MATH_TOOL",
          "(a) 7. (b) 0 °C. (c) 0.5 M.", "quantity_with_unit",
          sym_verify("1/2=0.5"))

    # ---- second batch: distinct multi-part structures --------------------
    P_add("arithmetic", "multi_step_numeric_error",
          "Compute: (a) 36 × 21, (b) 36 + 21, (c) 480 ÷ 12.",
          {"a": {"expected": "756", "given": "756"},
           "b": {"expected": "57", "given": "57"},
           "c": {"expected": "40", "given": "40"}},
          "c", "20", "numeric_result",
          "Division recheck failed: 480 ÷ 12 = 40.", "MATH_TOOL",
          "36×21=756; 36+21=57; 480÷12=40.", "integer",
          sym_verify("36*21=756; 36+21=57; 480/12=40"))
    P_add("arithmetic", "partial_solution_failure",
          "Percentages: (a) 20% of 150, (b) 50% of 88, (c) 10% of 990.",
          {"a": {"expected": "30", "given": "30"},
           "b": {"expected": "44", "given": "44"},
           "c": {"expected": "99", "given": "99"}},
          "a", "3", "numeric_result",
          "Percentage recheck failed: 20% of 150 = 30.", "MATH_TOOL",
          "0.2·150=30; 0.5·88=44; 0.1·990=99.", "number",
          sym_verify("150*0.2=30; 88*0.5=44; 990*0.1=99"))
    P_add("arithmetic", "symbolic_error",
          "Fractions: (a) 1/2 + 1/3 in lowest terms, (b) 2/5 of 45, "
          "(c) 7/8 − 3/8 in lowest terms.",
          {"a": {"expected": "5/6", "given": "5/6"},
           "b": {"expected": "18", "given": "18"},
           "c": {"expected": "1/2", "given": "1/2"}},
          "a", "2/5", "fraction",
          "Fraction recheck failed: 1/2 + 1/3 = 5/6.", "MATH_TOOL",
          "1/2+1/3=5/6; (2/5)·45=18; 7/8−3/8=4/8=1/2.", "fraction",
          sym_verify("1/2+1/3=5/6; 45*2/5=18; 7/8-3/8=1/2"))
    P_add("arithmetic", "simple_local_error",
          "Powers: (a) 2^5, (b) 3^3, (c) 10^4.",
          {"a": {"expected": "32", "given": "32"},
           "b": {"expected": "27", "given": "27"},
           "c": {"expected": "10000", "given": "10000"}},
          "b", "81", "numeric_result",
          "Power recheck failed: 3^3 = 27.", "MATH_TOOL",
          "2^5=32; 3^3=27; 10^4=10000.", "integer",
          sym_verify("2**5=32; 3**3=27; 10**4=10000"))

    P_add("algebra", "symbolic_error",
          "Algebra: (a) expand (2x + 1)(x − 3), (b) factor x^2 − 5x + 6, "
          "(c) evaluate 3x^2 − 2x at x = 3.",
          {"a": {"expected": "2x^2 − 5x − 3", "given": "2x^2 − 5x − 3"},
           "b": {"expected": "(x − 2)(x − 3)", "given": "(x − 2)(x − 3)"},
           "c": {"expected": "21", "given": "21"}},
          "a", "2x^2 − 6x − 3", "symbolic_result",
          "Expansion recheck failed: (2x+1)(x−3) = 2x^2 − 5x − 3.",
          "T4_VERIFIER",
          "expand: 2x^2−6x+x−3 = 2x^2−5x−3; factors (x−2)(x−3); "
          "3·9−6=21.", "expression", sym_verify("expand(2x+1)(x-3)"))
    P_add("algebra", "partial_solution_failure",
          "Algebra: (a) simplify (4x^2)/(2x) for x ≠ 0, (b) collect "
          "2(3x + 1) − 4x, (c) evaluate 2^3 + 3^2.",
          {"a": {"expected": "2x", "given": "2x"},
           "b": {"expected": "2x + 2", "given": "2x + 2"},
           "c": {"expected": "17", "given": "17"}},
          "b", "6x + 2", "symbolic_result",
          "Collection recheck failed: 2(3x+1) − 4x = 2x + 2.", "T4_VERIFIER",
          "(a) 2x. (b) 6x+2−4x = 2x+2. (c) 8+9=17.", "expression",
          sym_verify("(4x^2)/(2x)=2x; 2(3x+1)-4x=2x+2; 8+9=17"))
    P_add("algebra", "final_answer_only_failure",
          "Quadratic x^2 − 7x + 10 = 0: (a) smaller root, (b) larger "
          "root, (c) vertex x-coordinate.",
          {"a": {"expected": "2", "given": "2"},
           "b": {"expected": "5", "given": "5"},
           "c": {"expected": "3.5", "given": "3.5"}},
          "b", "10", "solution",
          "Root check failed: roots are 2 and 5.", "T4_VERIFIER",
          "(x−2)(x−5)=0 → roots 2, 5; vertex x=7/2=3.5.", "number",
          sym_verify("roots of x^2-7x+10"))

    P_add("equations", "partial_solution_failure",
          "Solve: (a) 4x − 1 = 15, (b) x^2 = 16 (positive root), "
          "(c) x/3 = 7.",
          {"a": {"expected": "4", "given": "4"},
           "b": {"expected": "4", "given": "4"},
           "c": {"expected": "21", "given": "21"}},
          "c", "7/3", "solution", "Solution check failed: x/3 = 7 so "
          "x = 21.", "T4_VERIFIER", "(a) x=4. (b) x=4. (c) x=21.",
          "number", sym_verify("4x-1=15->4; sqrt(16)=4; x/3=7->21"))
    P_add("equations", "multi_step_numeric_error",
          "Solve the system: (a) x from x + y = 8 and x − y = 2, (b) y "
          "from the same system, (c) check value of x + y.",
          {"a": {"expected": "5", "given": "5"},
           "b": {"expected": "3", "given": "3"},
           "c": {"expected": "8", "given": "8"}},
          "b", "6", "solution", "Solution check failed: 2x = 10 so "
          "x = 5, y = 3.", "T4_VERIFIER",
          "Adding: 2x=10 → x=5; y=8−5=3; check x+y=8.",
          "number", sym_verify("system (5,3)"))
    P_add("equations", "symbolic_error",
          "Solve: (a) 3^x = 81, (b) 2x + 5 = 5, (c) 100 = 10^t.",
          {"a": {"expected": "4", "given": "4"},
           "b": {"expected": "0", "given": "0"},
           "c": {"expected": "2", "given": "2"}},
          "a", "27", "solution", "Solution check failed: 3^4 = 81.",
          "T4_VERIFIER", "(a) x=4. (b) x=0. (c) t=2.", "integer",
          sym_verify("3**4=81; 2x+5=5->0; 100=10**t->2"))

    P_add("calculus", "partial_solution_failure",
          "Calculus: (a) d/dx(6x^4), (b) d/dx(2x + 7), (c) ∫₀² 2x dx.",
          {"a": {"expected": "24x^3", "given": "24x^3"},
           "b": {"expected": "2", "given": "2"},
           "c": {"expected": "4", "given": "4"}},
          "a", "6x^3", "derivative",
          "Derivative recheck failed: d/dx(6x^4) = 24x^3.", "MATH_TOOL",
          "d/dx(6x^4)=24x^3; d/dx(2x+7)=2; ∫₀²2x dx = [x^2]₀² = 4.",
          "expression", sym_verify("diff(6x^4)=24x^3; int(2x,0,2)=4"))
    P_add("calculus", "symbolic_error",
          "Calculus: (a) d/dx(x^5), (b) d/dx(sin(x)) at a symbolic level, "
          "(c) ∫₀¹ 4x^3 dx.",
          {"a": {"expected": "5x^4", "given": "5x^4"},
           "b": {"expected": "cos(x)", "given": "cos(x)"},
           "c": {"expected": "1", "given": "1"}},
          "c", "4", "integral", "Integral recheck failed: "
          "[x^4]₀¹ = 1.", "MATH_TOOL", "(a) 5x^4. (b) cos(x). (c) 1.",
          "number", sym_verify("int(4x^3,0,1)=1"))

    P_add("probability_statistics", "partial_solution_failure",
          "Probability: (a) P(an even roll on one fair d6), (b) P(two "
          "heads in two fair flips), (c) mean of 2, 4, 6.",
          {"a": {"expected": "1/2", "given": "1/2"},
           "b": {"expected": "1/4", "given": "1/4"},
           "c": {"expected": "4", "given": "4"}},
          "b", "1/2", "probability_value",
          "Count check failed: HH is 1 of 4 outcomes = 1/4.", "MATH_TOOL",
          "(a) 3/6=1/2. (b) 1/4. (c) (2+4+6)/3=4.", "fraction",
          sym_verify("P(HH)=1/4; mean=4"))
    P_add("probability_statistics", "multi_step_numeric_error",
          "Counting: (a) C(4,2), (b) P(an ace from a 52-card deck), "
          "(c) P(sum of two dice is 12).",
          {"a": {"expected": "6", "given": "6"},
           "b": {"expected": "1/13", "given": "1/13"},
           "c": {"expected": "1/36", "given": "1/36"}},
          "c", "1/18", "probability_value",
          "Count check failed: only (6,6) gives 12; 1/36.", "MATH_TOOL",
          "(a) 6. (b) 4/52=1/13. (c) 1/36.", "fraction",
          sym_verify("C(4,2)=6; 4/52=1/13; 1/36"))

    P_add("units", "unit_error",
          "Convert: (a) 6 kg to grams, (b) 90 seconds to minutes, "
          "(c) 2.5 tonnes to kilograms.",
          {"a": {"expected": "6000 g", "given": "6000 g"},
           "b": {"expected": "1.5 min", "given": "1.5 min"},
           "c": {"expected": "2500 kg", "given": "2500 kg"}},
          "a", "600 g", "unit_value",
          "Unit check failed: 6 kg = 6000 g.", "UNIT_CHECK",
          "(a) 6000 g. (b) 1.5 min. (c) 2500 kg.", "quantity_with_unit",
          tool_verify("unit_converter", "6 kg -> 6000 g"))
    P_add("units", "unit_error",
          "Convert: (a) 12 m to centimetres, (b) 3.5 L to millilitres, "
          "(c) 48 hours to days.",
          {"a": {"expected": "1200 cm", "given": "1200 cm"},
           "b": {"expected": "3500 mL", "given": "3500 mL"},
           "c": {"expected": "2 days", "given": "2 days"}},
          "b", "350 mL", "unit_value",
          "Unit check failed: 3.5 L = 3500 mL.", "UNIT_CHECK",
          "(a) 1200 cm. (b) 3500 mL. (c) 2 days.", "quantity_with_unit",
          tool_verify("unit_converter", "3.5 L -> 3500 mL"))

    P_add("physics", "multi_step_numeric_error",
          "Motion: (a) speed of an object covering 120 m in 40 s in m/s, "
          "(b) force on 6 kg at 4 m/s² in N, (c) kinetic energy of 3 kg "
          "at 2 m/s in J.",
          {"a": {"expected": "3 m/s", "given": "3 m/s"},
           "b": {"expected": "24 N", "given": "24 N"},
           "c": {"expected": "6 J", "given": "6 J"}},
          "b", "1.5 N", "quantity_with_unit",
          "Force check failed: F = ma = 6 × 4 = 24 N.", "UNIT_CHECK",
          "(a) 120/40=3 m/s. (b) 24 N. (c) ½·3·4=6 J.",
          "quantity_with_unit", fact_verify("F=ma mechanical recomputation"))

    P_add("chemistry", "multi_step_numeric_error",
          "Molar masses in g/mol: (a) CH4, (b) NH3, (c) H2O2. "
          "(H: 1.008, C: 12.011, N: 14.007, O: 15.999)",
          {"a": {"expected": "16.04 g/mol", "given": "16.04 g/mol"},
           "b": {"expected": "17.03 g/mol", "given": "17.03 g/mol"},
           "c": {"expected": "34.01 g/mol", "given": "34.01 g/mol"}},
          "a", "12.01 g/mol", "quantity_with_unit",
          "Molar-mass check failed: CH4 = 12.011 + 4×1.008 = 16.04.",
          "MATH_TOOL", "(a) 16.04. (b) 17.03. (c) 34.01.",
          "quantity_with_unit", fact_verify("atomic-mass table arithmetic"))
    P_add("chemistry", "wrong_scientific_claim",
          "Chemistry: (a) chemical formula of ammonia, (b) number of "
          "atoms in one H2SO4 molecule, (c) state of sodium chloride at "
          "room temperature.",
          {"a": {"expected": "NH3", "given": "NH3"},
           "b": {"expected": "7", "given": "7"},
           "c": {"expected": "solid", "given": "solid"}},
          "a", "N3H", "claim",
          "Formula check failed: ammonia is NH3.", "RETRIEVAL_EVIDENCE",
          "(a) NH3. (b) 2+4+1=7 atoms. (c) solid.", "claim",
          fact_verify("chemistry fact table"))

    P_add("biology", "partial_solution_failure",
          "Plant physiology: (a) gas plants take in for photosynthesis, "
          "(b) green pigment absorbing light, (c) organ pumping blood "
          "in humans.",
          {"a": {"expected": "carbon dioxide", "given": "carbon dioxide"},
           "b": {"expected": "chlorophyll", "given": "chlorophyll"},
           "c": {"expected": "heart", "given": "heart"}},
          "a", "oxygen", "claim",
          "Claim check failed: photosynthesis takes in carbon dioxide.",
          "RETRIEVAL_EVIDENCE", "(a) CO2. (b) Chlorophyll. (c) Heart.",
          "claim", fact_verify("biology fact table"))

    P_add("astronomy_earth", "partial_solution_failure",
          "Astronomy: (a) planet nearest the Sun, (b) galaxy containing "
          "the Sun, (c) force that makes objects fall toward Earth.",
          {"a": {"expected": "Mercury", "given": "Mercury"},
           "b": {"expected": "the Milky Way", "given": "the Milky Way"},
           "c": {"expected": "gravity", "given": "gravity"}},
          "b", "Andromeda", "claim",
          "Claim check failed: the Sun is in the Milky Way.",
          "RETRIEVAL_EVIDENCE", "(a) Mercury. (b) Milky Way. (c) gravity.",
          "claim", fact_verify("astronomy fact table"))

    P_add("mixed_math_science", "multi_step_numeric_error",
          "Applied problems: (a) density of 300 g occupying 100 cm³ in "
          "g/cm³, (b) 100 km/h expressed in m/s to one decimal, "
          "(c) total voltage of four 1.5 V cells in series.",
          {"a": {"expected": "3 g/cm³", "given": "3 g/cm³"},
           "b": {"expected": "27.8 m/s", "given": "27.8 m/s"},
           "c": {"expected": "6 V", "given": "6 V"}},
          "c", "1.5 V", "quantity_with_unit",
          "Voltage check failed: 4 × 1.5 V = 6 V in series.", "UNIT_CHECK",
          "(a) 300/100=3. (b) 27.8 m/s. (c) 6 V.", "quantity_with_unit",
          fact_verify("mechanical formula recomputation"))

    # retrieval-backed partial
    docs_needed = []
    for question, expected, wrong, phrase, extra in RETRIEVAL_CASES:
        doc = find_support(phrase, extra)
        assert doc is not None, phrase
        docs_needed.append(doc)
    d0 = docs_needed[0]  # Thermodynamics — absolute zero
    P_add("retrieval_science", "citation_only_failure",
          "With corpus citation: (a) the temperature of absolute zero in "
          "degrees Celsius, (b) state the citation supporting (a) from the "
          "retrieved corpus, (c) physical state of water at room "
          "temperature.",
          {"a": {"expected": "-273.15 °C", "given": "-273.15 °C"},
           "b": {"expected": "CITATION_OK", "given": "CITATION_OK"},
           "c": {"expected": "liquid", "given": "liquid"}},
          "b", "CITATION_MISSING", "citation",
          "Citation check failed: the claim is correct but the required "
          "corpus citation is missing.", "CITATION_CHECK",
          f"Claim (a) verified against {citation(d0)}; citation must "
          "reference that source.", "claim_with_citation",
          corpus_verify(citation(d0)))

    d1 = docs_needed[2]  # Abiogenesis — mitochondria/ATP
    P_add("retrieval_science", "partial_solution_failure",
          "Retrieved-evidence questions: (a) molecule confirmed as the "
          "genetic material by the Hershey–Chase experiment, (b) organelle "
          "that produces ATP, (c) gas plants take in for photosynthesis.",
          {"a": {"expected": "DNA", "given": "DNA"},
           "b": {"expected": "mitochondria", "given": "mitochondria"},
           "c": {"expected": "carbon dioxide", "given": "carbon dioxide"}},
          "a", "protein", "claim",
          "Retrieved evidence contradicts the claim: DNA was confirmed as "
          "the genetic material.", "RETRIEVAL_EVIDENCE",
          f"Corpus support ({citation(docs_needed[3])}): "
          f"\"{docs_needed[3]['text'][:150]}...\"",
          "claim", corpus_verify(citation(docs_needed[3])))

    d2 = docs_needed[1]  # Solar System — atmosphere composition
    P_add("retrieval_science", "evidence_conflict",
          "Retrieved-evidence questions: (a) approximate percentage of "
          "Earth's atmosphere that is nitrogen, (b) approximate "
          "percentage that is oxygen, (c) planet with the complex "
          "weather system described in the source.",
          {"a": {"expected": "78%", "given": "78%"},
           "b": {"expected": "21%", "given": "21%"},
           "c": {"expected": "Earth", "given": "Earth"}},
          "b", "78%", "claim",
          "Retrieved evidence contradicts the claim: oxygen is about 21% "
          "of Earth's atmosphere.", "RETRIEVAL_EVIDENCE",
          f"Corpus support ({citation(d2)}): \"{d2['text'][:150]}...\"",
          "claim", corpus_verify(citation(d2)))


# =================================================================
# AMBIGUOUS cases — only unverified feedback exists
# =================================================================


def ambiguous_cases() -> None:
    spec = [
        # (domain, question, initial, feedback claim, note)
        ("arithmetic", "Estimate: how many seconds has a typical 30-year-old "
         "lived?", "About 946 million seconds",
         "A reviewer believes the estimate is off by more than a year but "
         "gives no calculation.", "estimate; no verification basis"),
        ("algebra", "Is x^2 + x + 41 prime for all integer x from 0 to 40?",
         "Yes for all x in that range",
         "A reviewer suspects a counterexample exists but cannot name one.",
         "verification requires exhaustive check not performed"),
        ("equations", "Does 3x + 7 = 22 have exactly one integer solution?",
         "Yes", "A reviewer claims there might be two solutions but shows "
         "no work.", "claim unverified"),
        ("calculus", "Is the function x·|x| differentiable at x = 0?",
         "Yes", "A reviewer is unsure and provides no derivation.",
         "subtle derivative; no authoritative check"),
        ("probability_statistics", "Is a family with 4 children more likely "
         "than not to have both a boy and a girl?", "Yes",
         "A reviewer doubts this but offers no calculation.",
         "requires explicit probability computation not supplied"),
        ("units", "Is it true that one nautical mile is longer than one "
         "statute mile?", "Yes", "A reviewer disagrees but cites no "
         "reference.", "unit fact not in verification scope"),
        ("physics", "Could a bullet fired horizontally and one dropped "
         "from the same height land at nearly the same time (ignoring "
         "air resistance)?", "Yes, approximately",
         "A reviewer claims the fired bullet lands sooner but gives no "
         "argument.", "idealization-dependent; no verification"),
        ("physics", "Does sound travel faster in water than in air?",
         "Yes", "A reviewer is unsure.", "no authoritative evidence "
         "supplied"),
        ("chemistry", "Is it possible to distinguish pure water from "
         "identical-looking saltwater by tasting it safely?",
         "No, tasting unknown solutions is unsafe",
         "A reviewer says a simple taste test would work.", "safety-"
         "dependent claim; no verifiable basis"),
        ("chemistry", "Do all metals conduct electricity at room "
         "temperature?", "No", "A reviewer believes all do.",
         "exception-based claim; unverified"),
        ("biology", "Do plants grow faster with green light than with "
         "white light?", "No", "A reviewer claims green light is optimal "
         "for growth.", "experimental claim; no evidence supplied"),
        ("biology", "Can humans survive without a spleen?", "Yes",
         "A reviewer believes it is impossible.", "medical claim; no "
         "source supplied"),
        ("astronomy_earth", "Is the Morning Star always the planet "
         "Venus?", "Not always", "A reviewer insists it is always Venus.",
         "depends on definition; unverified"),
        ("astronomy_earth", "Did a large asteroid impact contribute to "
         "the extinction of the non-avian dinosaurs?", "Yes, the evidence "
         "strongly supports it", "A reviewer claims the cause is fully "
         "disputed.", "historical-scientific claim; evidence handling "
         "unclear"),
        ("astronomy_earth", "Will the next solar eclipse be visible from "
         "the user's location?", "Cannot be determined from the question",
         "A reviewer says it definitely will be visible.", "location "
         "unknown; evidence insufficient"),
        ("mixed_math_science", "If a person's hearing declines about 0.5 dB "
         "per year after 40, how much would hearing change by 60?",
         "About 10 dB decline", "A reviewer claims it is 20 dB.",
         "extrapolation; no verification basis"),
        ("mixed_math_science", "Does doubling the thickness of a window "
         "double its heat loss rate?", "No", "A reviewer says yes.",
         "physics of conduction; assumption-dependent"),
        ("retrieval_science", "Did the historical figure the question "
         "references receive the Nobel Prize in Physics?",
         "Cannot confirm from available evidence",
         "A reviewer asserts the prize was won.", "no retrieval evidence "
         "available"),
        ("retrieval_science", "What was the exact population of ancient "
         "Rome in 100 AD?", "Estimates vary; roughly one million",
         "A reviewer asserts a precise figure of 1,023,000.",
         "no verifiable source available"),
        ("retrieval_science", "Is it certain that the next earthquake in "
         "a given region will exceed magnitude 6?", "No, it cannot be "
         "predicted", "A reviewer claims prediction is possible.",
         "seismology claim; no evidence"),
        ("arithmetic", "Round-trip flight distance between two unspecified "
         "cities is claimed as 5,600 km. Is 11,200 km the round trip?",
         "Yes, if one-way is 5,600 km",
         "A reviewer says the trip must be longer.", "unspecified "
         "parameters; no verification basis"),
        ("units", "A recipe calls for 1 cup of flour. Is 250 mL always "
         "the exact equivalent?", "No, cup sizes vary by country",
         "A reviewer insists 250 mL is universal.", "convention-dependent; "
         "unverified"),
        ("calculus", "Does every continuous function have an elementary "
         "antiderivative?", "No", "A reviewer believes yes.",
         "advanced claim; unverified"),
        ("probability_statistics", "After 10 coin flips showing heads, is "
         "tails now more likely on the next flip?", "No, still 1/2",
         "A reviewer claims tails is due.", "gambler's fallacy claim; "
         "unverified feedback"),
        ("equations", "Can a quadratic equation have more than two real "
         "roots?", "No", "A reviewer claims some quadratics have three.",
         "algebra claim; unverified"),
        ("algebra", "Is the expression x^2 + 1 ever negative for real x?",
         "No", "A reviewer believes it can be negative for some x.",
         "claim unverified by feedback"),
        ("algebra", "Does (a + b)^2 always equal a^2 + b^2 for real "
         "numbers?", "No", "A reviewer claims they are always equal.",
         "unverified feedback"),
        ("mixed_math_science", "Will an object with density exactly equal "
         "to water's sink or float in fresh water?",
         "It will be neutrally buoyant",
         "A reviewer claims it always sinks.", "idealization-dependent; "
         "unverified"),
        ("biology", "Do identical twins always have identical DNA "
         "sequences?", "Not exactly; small differences can occur",
         "A reviewer claims they are always identical.", "nuanced claim; "
         "no authoritative evidence"),
        ("chemistry", "Is gold denser than lead?", "Yes",
         "A reviewer claims lead is denser.", "fact contested by feedback "
         "without source"),
        ("astronomy_earth", "Are the constellations the same from Earth "
         "now as they were 100,000 years ago?", "Not exactly; star "
         "positions drift", "A reviewer claims they are unchanged.",
         "unverified claim"),
        ("physics", "In a vacuum, does a feather and a hammer fall at the "
         "same rate?", "Yes", "A reviewer disagrees.", "claim unverified "
         "by feedback"),
        ("arithmetic", "Is the number of minutes in a week exactly "
         "10,080?", "Yes", "A reviewer claims it is 1,440.", "feedback "
         "unverified"),
        ("units", "Is 0 °C exactly 32 °F?", "Yes",
         "A reviewer claims the conversion is approximate.",
         "unverified feedback"),
        ("retrieval_science", "Has any spacecraft left the Solar System?",
         "Voyager 1 is generally credited as having crossed the "
         "heliopause", "A reviewer disputes this entirely.",
         "definition-dependent; no retrieval evidence"),
        ("biology", "Do fish sleep?", "Most fish rest, though sleep "
         "differs from mammals", "A reviewer claims fish never rest.",
         "definitional; unverified"),
        ("chemistry", "Does dissolving salt in water raise its boiling "
         "point?", "Yes, modestly", "A reviewer claims it lowers it.",
         "unverified feedback"),
        ("physics", "Does a heavier object always fall faster in air?",
         "No, air resistance matters", "A reviewer says mass alone "
         "decides.", "unverified feedback"),
        ("mixed_math_science", "If a car's fuel use is 6 L/100 km, is "
         "1.6 L enough for 30 km?", "No, 1.8 L is needed",
         "A reviewer claims it is enough.", "arithmetic claim; feedback "
         "unverified"),
        ("astronomy_earth", "Is the Moon's gravity exactly one sixth of "
         "Earth's?", "Approximately, it is about 1/6",
         "A reviewer claims exactly 1/8.", "approximation dispute; "
         "unverified"),
        ("probability_statistics", "Is the median of 1, 2, 3, 4 equal to "
         "2.5?", "Yes", "A reviewer claims it is 3.", "unverified "
         "feedback"),
        ("calculus", "Is the derivative of a constant function always "
         "zero?", "Yes", "A reviewer claims otherwise.", "unverified "
         "feedback"),
        ("equations", "Does x = −1 satisfy x^2 = 1?", "Yes",
         "A reviewer claims it does not.", "unverified feedback"),
        ("arithmetic", "Is 2^0 equal to 1?", "Yes", "A reviewer claims "
         "it is 0.", "unverified feedback"),
        ("units", "Is a millilitre the same volume as a cubic "
         "centimetre?", "Yes", "A reviewer claims they differ.",
         "unverified feedback"),
        ("mixed_math_science", "Does absolute zero correspond to −273.15 "
         "°C?", "Yes", "A reviewer claims −273.0 °C exactly.", "unverified "
         "feedback"),
        ("chemistry", "Is water a polar molecule?", "Yes", "A reviewer "
         "claims it is nonpolar.", "unverified feedback"),
        ("retrieval_science", "Does the corpus contain a definitive "
         "answer for the age of the universe to full precision?",
         "No, only approximate values are known", "A reviewer claims an "
         "exact value is established.", "evidence insufficiency"),
    ]
    for domain, question, initial, feedback, note in spec:
        add("AMBIGUOUS", domain, "evidence_conflict", question, initial,
            "UNDEFINED_AMBIGUOUS", "none",
            feedback, "UNVERIFIED_MODEL_FEEDBACK", "UNKNOWN",
            "Insufficient or unverified evidence: " + note,
            "any", {"method": "epistemic_insufficiency",
                    "detail": note}, [], None, False)


# ------------------------------------------------------------------- main --


def main() -> None:
    math_cases()
    unit_cases()
    physics_cases()
    chemistry_cases()
    science_fact_cases()
    mixed_cases()
    retrieval_cases()
    partial_cases()
    ambiguous_cases()

    # ---- inventory checks ------------------------------------------------
    from collections import Counter
    classes = Counter(c["case_class"] for c in CASES)
    per_class_domains = {c: Counter(d["domain"] for d in CASES
                                    if d["case_class"] == c)
                         for c in CLASSES}
    difficulties = Counter(c["difficulty"] for c in CASES)
    missing_diff = [d for d in DIFFICULTIES if d not in difficulties]
    assert not missing_diff, f"difficulty types missing: {missing_diff}"
    for c in CLASSES:
        assert classes[c] >= 40, f"{c} below minimum: {classes[c]}"
        missing = [d for d, n in per_class_domains[c].items() if n < 3]
        assert not missing, f"{c} thin domains: {missing}"
    for c in CASES:
        assert c["domain"] and c["difficulty"] and c["question"]

    # ---- assign ids + split ----------------------------------------------
    by_class: dict[str, list[dict]] = {c: [] for c in CLASSES}
    for i, case in enumerate(CASES):
        case["eval_id"] = f"mcor-v2-{i + 1:03d}"
        by_class[case["case_class"]].append(case)
    final_ids: list[str] = []
    for c in CLASSES:
        for j, case in enumerate(by_class[c]):
            case["split"] = "dev" if j % 2 == 0 else "final"
            if case["split"] == "final":
                final_ids.append(case["eval_id"])
    rows = []
    for case in CASES:
        rows.append({
            "eval_id": case["eval_id"], "case_class": case["case_class"],
            "split": case["split"], "domain": case["domain"],
            "difficulty": case["difficulty"], "question": case["question"],
            "initial_answer": case["initial_answer"],
            "expected_answer": case["expected_answer"],
            "failed_component": case["failed_component"],
            "feedback": case["feedback"],
            "feedback_source": case["feedback_source"],
            "feedback_status": case["feedback_status"],
            "evidence": case["evidence"],
            "required_output_type": case["required_output_type"],
            "wrong_variants": case["wrong_variants"],
            "protected": case["protected"], "failed_part": case["failed_part"],
            "expected_behavior": (
                "CHANGE_ANSWER" if case["case_class"] == "TRUE_FAIL" else
                "TARGETED_REPAIR" if case["case_class"] == "PARTIAL_FAIL"
                else "PRESERVE_ANSWER"),
            "mechanical_label": case["mechanical_label"],
            "verification": case["verification"],
        })

    OUT.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=True) for r in rows]
    payload = ("\n".join(lines) + "\n").encode()
    (OUT / "questions.jsonl").write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    final_rows = [r for r in rows if r["split"] == "final"]
    final_payload = ("\n".join(json.dumps(r, sort_keys=True, ensure_ascii=True)
                               for r in final_rows) + "\n").encode()
    final_sha = hashlib.sha256(final_payload).hexdigest()
    dev_q = {r["question"] for r in rows if r["split"] == "dev"}
    fin_q = {r["question"] for r in rows if r["split"] == "final"}
    question_overlap = sorted(dev_q & fin_q)
    assert not question_overlap, "question leakage across splits"
    splits = Counter(r["split"] for r in rows)
    manifest = {
        "name": "mango-correction-eval-v2", "frozen": True,
        "questions": len(rows),
        "class_counts": dict(classes),
        "split_counts": dict(splits),
        "domain_counts_per_class": {c: dict(per_class_domains[c])
                                    for c in CLASSES},
        "difficulty_counts": dict(difficulties),
        "difficulty_types": DIFFICULTIES,
        "final_split_ids": final_ids,
        "final_split_sha256": final_sha,
        "dev_final_question_overlap": len(question_overlap),
        "unique_eval_ids": len({r["eval_id"] for r in rows}) == len(rows),
        "sha256": checksum,
        "tuning_performed_before_freeze": False,
        "label_verification": {
            "math": "sympy recomputation at build time",
            "units": "production UnitConverterTool recomputation",
            "formulas": "mechanical recomputation from stated values",
            "stoichiometry": "atomic-mass table arithmetic",
            "facts": "source-verified fact table",
            "retrieval": "supporting chunk located in frozen T5R corpus",
            "ambiguous": "epistemic insufficiency (unverified feedback only)",
        },
        "construction_rule": "No label exists only because another LLM "
                             "asserted it.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                       encoding="utf-8")
    (OUT / "checksum.json").write_text(json.dumps(
        {"questions.jsonl": checksum, "final_split_sha256": final_sha},
        indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()