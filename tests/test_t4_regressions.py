"""Regression tests for the 30 confirmed T4 adversarial-review defects.

Each test names the defect it pins (R#). Evidence: t4_review_confirmed.txt.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from sciencemath.tools.base import ToolError, run_with_timeout
from sciencemath.tools.base import ToolResult
from sciencemath.tools.calculator import CalculatorTool
from sciencemath.tools.equation_solver import EquationSolverTool
from sciencemath.tools.numerical_math import NumericalMathTool
from sciencemath.tools.router import ToolCallLogger
from sciencemath.tools.safeparse import lenient_expression, normalize_input, \
    validate_ast
from sciencemath.tools.symbolic_math import safe_parse
from sciencemath.tools.symbolic_math import SymbolicMathTool
from sciencemath.tools.unit_converter import UnitConverterTool
from sciencemath.tools.verifier import verify_answer
from sciencemath.evaluation.extraction import extract_mcq

calc = CalculatorTool()
sym = SymbolicMathTool()
eqs = EquationSolverTool()
nm = NumericalMathTool()
uc = UnitConverterTool()


def ok(res):
    assert res.status == "ok", res.to_dict()
    return res.result


def err(res):
    assert res.status == "error", res.to_dict()
    return res.error["code"]


# --- R1: run_with_timeout must bound WALL CLOCK ----------------------------

def test_timeout_bounds_wall_clock():
    t0 = time.perf_counter()
    with pytest.raises(ToolError) as ei:
        run_with_timeout(lambda: time.sleep(5), 0.5, "sleepy")
    assert ei.value.code == "TIMEOUT"
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, f"timeout took {elapsed:.2f}s — worker was joined"


def test_timeout_success_path_still_returns():
    assert run_with_timeout(lambda: 42, 5.0, "fast") == 42


# --- R2/R3/R4: symbolic sample-point false-PASS cluster ---------------------

def test_nullifier_polynomial_no_longer_passes():
    # nullifier over the OLD fixed sample points must not pass now that
    # points are hash-derived per pair
    old_points = [0.1237, 1.7183, 2.3456, -1.4142, 3.7321]
    nullifier = "*".join(f"(x - {p})" for p in old_points)
    res = verify_answer(f"x**2 + 1 + {nullifier}", "x**2 + 1")
    assert res["verdict"] != "PASS"


def test_all_symbols_same_value_defect():
    assert verify_answer("x", "y")["verdict"] == "FAIL"
    assert verify_answer("2*a*t", "2*b*t")["verdict"] == "FAIL"
    assert verify_answer("0", "x**2 - y**2")["verdict"] == "FAIL"


def test_branch_sensitive_functions_not_decided_by_real_samples():
    # log(x**2) vs 2*log(x): equal on positive reals only — numeric
    # agreement there is NOT decisive
    assert verify_answer("log(x**2)", "2*log(x)")["verdict"] != "PASS"
    assert verify_answer("sqrt(x**2)", "x")["verdict"] != "PASS"
    # sanity: genuinely equivalent expressions still pass
    assert verify_answer("log(x**2)", "log(x**2)")["verdict"] == "PASS"
    assert verify_answer("2*x + 3*x", "5*x")["verdict"] == "PASS"


# --- R5: safeparse resource caps --------------------------------------------

def test_factorial_bomb_rejected_at_parse():
    t0 = time.perf_counter()
    assert err(sym.run({"operation": "simplify",
                        "expression": "factorial(10**9)"})) == \
        "DISALLOWED_EXPRESSION"
    assert time.perf_counter() - t0 < 5.0
    assert err(sym.run({"operation": "simplify",
                        "expression": "2**(10**8)"})) == "DISALLOWED_EXPRESSION"


def test_thousand_digit_literal_rejected():
    assert err(calc.run({"expression": "9" * 4000})) == "DISALLOWED_EXPRESSION"
    # big-but-sane results still work
    assert ok(calc.run({"expression": "2**64"}))["value"] == 2 ** 64


def test_factorial_argument_cap():
    assert err(calc.run({"expression": "factorial(2000000)"})) == \
        "DISALLOWED_EXPRESSION"


# --- R6: newline ambiguity and ^o regex -------------------------------------

def test_newline_inside_expression_is_parse_error():
    assert err(calc.run({"expression": "2\n3"})) == "PARSE_ERROR"
    assert ok(calc.run({"expression": "2\n"}))["value"] == 2.0


def test_degree_regex_does_not_eat_identifiers():
    assert normalize_input("45^o + 2^omega") == "45 + 2**omega"
    assert normalize_input("45^{\\circ}") == "45"
    x = safe_parse("2^omega")
    assert str(x.free_symbols.pop()) == "omega"


# --- R7: verifier unit-aware gold paths --------------------------------------

def test_gold_quantity_vs_bare_number_si_interpretation():
    assert verify_answer("3000", "3 km")["verdict"] == "PASS"
    assert verify_answer("1500", "1.5 km")["verdict"] == "PASS"
    assert verify_answer("5", "5 km")["verdict"] == "PASS"   # raw magnitude
    assert verify_answer("5000", "5 km")["verdict"] == "PASS"  # SI meters
    assert verify_answer("30", "3 km")["verdict"] == "FAIL"
    assert verify_answer("7", "3 km")["verdict"] == "FAIL"


def test_percent_vs_quantity_unknown():
    assert verify_answer("50%", "0.5 m")["verdict"] == "UNKNOWN"


def test_temperature_bare_number():
    # matching raw magnitude = "answer given in the reference's unit" (PASS);
    # mismatched bare number vs affine unit is undecidable, never FAIL
    assert verify_answer("25", "25 degC")["verdict"] == "PASS"
    assert verify_answer("45", "25 degC")["verdict"] == "UNKNOWN"


def test_pressure_dims_fixed():
    # Pa and N/m^2 must now be compatible (kg*m^-1*s^-2)
    assert ok(uc.run({"value": 1, "from_unit": "Pa",
                      "to_unit": "N/m2"}))["converted_value"] == \
        pytest.approx(1.0)


def test_bare_digit_exponents():
    # 'm2' used to be read as 'm' — 10 m2 vs 10 m graded PASS
    assert verify_answer("10 m2", "10 m")["verdict"] == "FAIL"
    assert verify_answer("10 m2", "10 m^2")["verdict"] == "PASS"
    assert ok(uc.run({"value": 1, "from_unit": "kg/m3",
                      "to_unit": "g/cm3"}))["converted_value"] == \
        pytest.approx(0.001)


# --- R8: solution-set and membership fixes -----------------------------------

def test_membership_argument_swap_fixed():
    assert verify_answer("42", "{42}")["verdict"] == "PASS"
    assert verify_answer("2", "{2, 3}")["verdict"] == "FAIL"
    assert verify_answer("5", "{2, 3}")["verdict"] == "FAIL"


def test_multicomma_number_not_a_set():
    assert verify_answer("12,345,678", "12345678")["verdict"] == "PASS"
    assert verify_answer("1,234.5", "1234.5")["verdict"] == "PASS"
    # genuine sets still work
    assert verify_answer("2, 3", "2, 3")["verdict"] == "PASS"


def test_empty_solution_sets_not_equivalent():
    assert verify_answer("1/x = 0", "sqrt(x) = -1")["verdict"] == "UNKNOWN"


def test_identical_equation_with_radical_solutions_passes():
    # string round-trip used to mangle "(" leading solutions -> FAIL
    assert verify_answer("x**2 + x - 1 = 0", "x**2 + x - 1 = 0")[
        "verdict"] == "PASS"


# --- R9: equation solver real-root / list-form / '==' fixes ------------------

def test_cubic_real_roots_not_dropped():
    # x**3 - 3*x - 1 has THREE real roots returned as is_real-None forms;
    # the old code treated is_real None as non-real and returned 0
    res = ok(eqs.run({"equation": "x**3 - 3*x - 1 = 0"}))
    assert res["solution_count"] == 3
    # genuinely complex roots are still dropped
    res2 = ok(eqs.run({"equation": "x**3 - 1 = 0"}))
    assert res2["solution_count"] == 1


def test_quintic_scalar_solve():
    res = ok(eqs.run({"equation": "x**5 - x - 1 = 0"}))
    assert res["solution_count"] == 1      # RootOf form, is_real -> real


def test_double_equals_accepted():
    res = ok(eqs.run({"equation": "2*x == 8"}))
    assert res["solution_count"] == 1
    assert res["numeric_solutions"][0]["x"] == pytest.approx(4.0)


# --- R10: calculator/numerical INTERNAL_ERROR cluster ------------------------

def test_calculator_type_error_is_invalid_input():
    assert err(calc.run({"expression": "factorial(5.0)"})) == "INVALID_INPUT"
    assert err(calc.run({"expression": "gcd(1.5, 2)"})) == "INVALID_INPUT"


def test_numerical_factorial_overflow_is_overflow():
    assert err(nm.run({"operation": "factorial", "n": 200})) == "OVERFLOW"


def test_inverse_size_cap():
    big10 = [[1.0 if i == j else 0.5 for j in range(10)] for i in range(10)]
    assert err(nm.run({"operation": "inverse", "matrix": big10})) == \
        "INVALID_INPUT"
    ok8 = [[1.0 if i == j else 0.1 for j in range(8)] for i in range(8)]
    res = ok(nm.run({"operation": "inverse", "matrix": ok8}))
    assert len(res["inverse"]) == 8


def test_integral_symbolic_bounds():
    # integral of sin over [pi, 2*pi] is -2; the old float(str) crashed on
    # the symbolic bound "pi" (INTERNAL_ERROR)
    res = ok(sym.run({"operation": "integral", "expression": "sin(x)",
                      "var": "x", "lower": "pi", "upper": "2*pi"}))
    assert res["numeric"] == pytest.approx(-2.0, abs=1e-9)


def test_var_inferred_for_single_symbol():
    # benchmark evidence: the model omitted 'var' in 10/34 tool calls
    res = ok(sym.run({"operation": "derivative", "expression": "x**3"}))
    assert res["result"] == "3*x**2"
    res = ok(sym.run({"operation": "integral", "expression": "3*x**2"}))
    assert res["result"] == "x**3"
    # multi-symbol expressions still require explicit var
    assert err(sym.run({"operation": "derivative",
                        "expression": "a*x**2"})) == "INVALID_INPUT"
    # explicit var still wins
    res = ok(sym.run({"operation": "derivative", "expression": "x*y",
                      "var": "y"}))
    assert res["result"] == "x"


# --- R11: extract_mcq trailing-word anchor -----------------------------------

def test_mcq_letter_not_taken_from_trailing_word():
    assert extract_mcq("B. mitochondria", None) is None
    assert extract_mcq("The answer is C) mitochondria", None) is None
    assert extract_mcq("B", None) == "B"
    assert extract_mcq("answer: A", None) == "A"


# --- R12: ToolCallLogger concurrency and serializability ---------------------

def test_logger_threaded_writes_are_complete(tmp_path):
    logger = ToolCallLogger(tmp_path / "calls.jsonl")
    def worker(tid):
        for i in range(50):
            logger.log({"event": "tool_call", "thread": tid, "i": i,
                        "arguments": {"expression": f"{tid}+{i}"}})
    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = [json.loads(line) for line in
             open(logger.path, encoding="utf-8")]
    assert len(lines) == 400
    assert all("ts" in line for line in lines)


def test_logger_unserializable_arguments(tmp_path):
    logger = ToolCallLogger(tmp_path / "calls.jsonl")
    logger.log({"event": "tool_call", "arguments": {"x": object()}})
    assert len(open(logger.path, encoding="utf-8").readlines()) == 1


# --- R13: verify_answer membership/perturbation hard cases -------------------

def test_no_false_pass_on_wrong_numbers():
    assert verify_answer("2", "3")["verdict"] == "FAIL"
    assert verify_answer("-1.4142", "1.4142")["verdict"] == "FAIL"