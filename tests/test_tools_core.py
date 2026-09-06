"""T4 tool-layer core tests: calculator, symbolic, solver, units, numerics.

All tools are exercised through their run() interface so the tests check
the exact JSON-safe contract downstream code depends on.
"""
import json

import pytest

from sciencemath.tools.base import ToolError, ToolResult, ensure_json_safe
from sciencemath.tools.calculator import CalculatorTool
from sciencemath.tools.equation_solver import EquationSolverTool
from sciencemath.tools.numerical_math import NumericalMathTool
from sciencemath.tools.symbolic_math import (SymbolicMathTool, safe_parse,
                                             symbolic_equivalence)
from sciencemath.tools.unit_converter import (UnitConverterTool,
                                              parse_quantity, parse_unit)

calc = CalculatorTool()
sym = SymbolicMathTool()
eq = EquationSolverTool()
conv = UnitConverterTool()
num = NumericalMathTool()


def ok(result):
    assert result.status == "ok", f"expected ok, got {result.error}"
    return result.result


def err(result):
    assert result.status == "error", f"expected error, got {result.result}"
    return result.error["code"]


# ---------------------------------------------------------------- calculator
class TestCalculator:
    def test_basic_arithmetic(self):
        assert ok(calc.run({"expression": "2 + 3 * 4"}))["value"] == 14
        assert ok(calc.run({"expression": "(2 + 3) * 4"}))["value"] == 20
        assert ok(calc.run({"expression": "2**10"}))["value"] == 1024

    def test_integer_results_reported_exact(self):
        assert ok(calc.run({"expression": "6*7"}))["exact"] is True
        assert ok(calc.run({"expression": "6/7"}))["exact"] is False

    def test_latex_input(self):
        assert ok(calc.run({"expression": r"\frac{3}{4} + \sqrt{16}"}))[
            "value"] == 4.75
        assert ok(calc.run({"expression": r"2^{10}"}))["value"] == 1024

    def test_implicit_multiplication(self):
        assert ok(calc.run({"expression": "3(4+2)"}))["value"] == 18

    def test_functions(self):
        assert ok(calc.run({"expression": "sqrt(144)"}))["value"] == 12.0
        assert ok(calc.run({"expression": "abs(-5) + min(2, 3, 1)"}))[
            "value"] == 6.0
        assert ok(calc.run({"expression": "factorial(5)"}))["value"] == 120.0

    def test_variables_rejected(self):
        assert err(calc.run({"expression": "x + 1"})) in (
            "INVALID_INPUT", "PARSE_ERROR", "DISALLOWED_EXPRESSION")

    def test_division_by_zero(self):
        assert err(calc.run({"expression": "1/0"})) == "DIVISION_BY_ZERO"

    def test_exponent_limit(self):
        # the AST resource gate now rejects the exponent at parse time;
        # either the parse-time or eval-time rejection is acceptable
        assert err(calc.run({"expression": "10**10**10"})) in (
            "OVERFLOW", "DISALLOWED_EXPRESSION")

    def test_huge_integer_rejected(self):
        assert err(calc.run({"expression": "123456789**99"})) in ("OVERFLOW",
                                                                  "INVALID_INPUT")

    def test_unknown_function(self):
        assert err(calc.run({"expression": "system('rm -rf /')"})) == \
            "DISALLOWED_EXPRESSION"

    def test_domain_error(self):
        assert err(calc.run({"expression": "sqrt(-1)"})) == "DOMAIN_ERROR"
        assert err(calc.run({"expression": "log(0)"})) == "DOMAIN_ERROR"

    def test_result_is_json_safe(self):
        json.dumps(calc.run({"expression": "sqrt(2)"}).to_dict())


# ------------------------------------------------------------------ symbolic
class TestSymbolic:
    def test_simplify(self):
        r = ok(sym.run({"operation": "simplify",
                        "expression": "(x**2 - 1)/(x - 1)"}))
        assert r["result"] == "x + 1"

    def test_derivative(self):
        r = ok(sym.run({"operation": "derivative",
                        "expression": "x**3", "var": "x"}))
        assert r["result"] == "3*x**2"

    def test_definite_integral(self):
        r = ok(sym.run({"operation": "integral", "expression": "x**2",
                        "var": "x", "lower": 0, "upper": 3}))
        assert r["numeric"] == 9.0

    def test_indefinite_integral(self):
        r = ok(sym.run({"operation": "integral", "expression": "2*x",
                        "var": "x"}))
        assert r["result"] == "x**2"

    def test_evaluate(self):
        r = ok(sym.run({"operation": "evaluate",
                        "expression": "sqrt(2)*pi", "digits": 8}))
        assert abs(r["numeric"] - 4.442882938) < 1e-6

    def test_variable_not_in_expression(self):
        assert err(sym.run({"operation": "derivative", "expression": "x**2",
                            "var": "y"})) == "INVALID_INPUT"

    def test_unknown_operation(self):
        assert err(sym.run({"operation": "factorial_tree",
                            "expression": "x"})) == "INVALID_INPUT"

    def test_equivalence_pass_fail(self):
        a = safe_parse("(x+1)*(x-1)")
        assert symbolic_equivalence(a, safe_parse("x**2 - 1")) == "PASS"
        assert symbolic_equivalence(a, safe_parse("x**2 + 1")) == "FAIL"

    def test_safe_parse_latex(self):
        assert str(safe_parse(r"\frac{3}{4}")) == "3/4"
        assert str(safe_parse("2x + 1")) == "2*x + 1"

    def test_safe_parse_rejects_injection(self):
        with pytest.raises(ToolError):
            safe_parse("__import__('os').system('x')")


# ------------------------------------------------------------------- solver
class TestEquationSolver:
    def test_linear(self):
        r = ok(eq.run({"equation": "2*x + 3 = 11"}))
        assert r["solutions"] == [{"x": "4"}]

    def test_quadratic(self):
        r = ok(eq.run({"equation": "x**2 - 5*x + 6 = 0"}))
        assert r["solution_count"] == 2
        assert {s["x"] for s in r["solutions"]} == {"2", "3"}

    def test_system(self):
        r = ok(eq.run({"equation": "2*x + y = 5; x - y = 1"}))
        assert r["solutions"] == [{"x": "2", "y": "1"}]

    def test_complex_solutions_dropped_by_default(self):
        r = ok(eq.run({"equation": "x**2 + 1 = 0"}))
        assert r["solution_count"] == 0

    def test_complex_allowed(self):
        r = ok(eq.run({"equation": "x**2 + 1 = 0", "allow_complex": True}))
        assert r["solution_count"] == 2

    def test_missing_variable(self):
        assert err(eq.run({"equation": "x + 1 = 2",
                           "variables": ["y"]})) == "INVALID_INPUT"

    def test_no_equation_form(self):
        # "x + 1" alone means x + 1 = 0
        r = ok(eq.run({"equation": "x + 1"}))
        assert r["solutions"] == [{"x": "-1"}]


# --------------------------------------------------------------------- units
class TestUnitConverter:
    def test_length(self):
        r = ok(conv.run({"value": 5, "from_unit": "km", "to_unit": "mi"}))
        assert abs(r["converted_value"] - 3.106856) < 1e-5

    def test_mass(self):
        assert ok(conv.run({"value": 2, "from_unit": "kg",
                            "to_unit": "g"}))["converted_value"] == 2000.0

    def test_temperature_affine(self):
        assert ok(conv.run({"value": 25, "from_unit": "degC",
                            "to_unit": "degF"}))["converted_value"] == 77.0
        assert ok(conv.run({"value": 0, "from_unit": "degC",
                            "to_unit": "K"}))["si_value"] == 273.15

    def test_temperature_to_non_temperature_rejected(self):
        assert err(conv.run({"value": 25, "from_unit": "degC",
                             "to_unit": "m"})) == "INCOMPATIBLE_UNITS"

    def test_compound_units(self):
        r = ok(conv.run({"value": 90, "from_unit": "km/h", "to_unit": "m/s"}))
        assert r["converted_value"] == 25.0
        r = ok(conv.run({"value": 1, "from_unit": "g/cm^3",
                         "to_unit": "kg/m^3"}))
        assert r["converted_value"] == 1000.0

    def test_negative_power_syntax(self):
        r = ok(conv.run({"value": 1, "from_unit": "m*s^-2",
                         "to_unit": "m/s^2"}))
        assert r["converted_value"] == 1.0

    def test_incompatible_units(self):
        assert err(conv.run({"value": 1, "from_unit": "km",
                             "to_unit": "kg"})) == "INCOMPATIBLE_UNITS"

    def test_unknown_unit_is_error_not_guess(self):
        assert err(conv.run({"value": 1, "from_unit": "smoot",
                             "to_unit": "m"})) == "UNKNOWN_UNIT"

    def test_convert_to_si_by_default(self):
        r = ok(conv.run({"value": 1, "from_unit": "g/cm^3"}))
        assert r["si_value"] == 1000.0 and r["si_unit"] == "kg/m^3"

    def test_parse_quantity(self):
        assert parse_quantity("3.2e4 kg/m^3") == (32000.0, "kg/m^3")
        assert parse_quantity("25%") == (25.0, "%")
        assert parse_quantity("98.6 degF") == (98.6, "degF")
        assert parse_quantity("no quantity here") is None

    def test_plurals_and_phrases(self):
        assert ok(conv.run({"value": 3, "from_unit": "kilometers",
                            "to_unit": "meters"}))["converted_value"] == 3000.0


# ------------------------------------------------------------- numerical math
class TestNumericalMath:
    def test_describe(self):
        r = ok(num.run({"operation": "describe",
                        "values": [2, 4, 6, 8]}))
        assert r["mean"] == 5.0 and r["median"] == 5.0
        assert r["min"] == 2.0 and r["max"] == 8.0
        assert abs(r["variance_population"] - 5.0) < 1e-12

    def test_percentile(self):
        r = ok(num.run({"operation": "percentile", "values": [1, 2, 3, 4],
                        "q": 50}))
        assert r["value"] == 2.5

    def test_combinatorics(self):
        assert ok(num.run({"operation": "ncr", "n": 5, "k": 2}))["value"] == 10.0
        assert ok(num.run({"operation": "npr", "n": 5, "k": 2}))["value"] == 20.0

    def test_determinant(self):
        r = ok(num.run({"operation": "determinant",
                        "matrix": [[1, 2], [3, 4]]}))
        assert r["determinant"] == -2.0

    def test_inverse(self):
        r = ok(num.run({"operation": "inverse",
                        "matrix": [[4, 7], [2, 6]]}))
        inv = r["inverse"]
        # [[4,7],[2,6]]^-1 = 1/10 * [[6,-7],[-2,4]]
        flat = [v for row in inv for v in row]
        assert flat == pytest.approx([0.6, -0.7, -0.2, 0.4])

    def test_singular_matrix(self):
        assert err(num.run({"operation": "inverse",
                            "matrix": [[1, 2], [2, 4]]})) == "SINGULAR_MATRIX"

    def test_transpose(self):
        r = ok(num.run({"operation": "transpose", "matrix": [[1, 2], [3, 4]]}))
        assert r["transpose"] == [[1, 3], [2, 4]]

    def test_matrix_must_be_square(self):
        assert err(num.run({"operation": "determinant",
                            "matrix": [[1, 2, 3], [4, 5, 6]]})) == \
            "INVALID_INPUT"


# ------------------------------------------------------------- base contract
class TestBaseContract:
    def test_registry_unknown_tool(self):
        from sciencemath.tools.base import ToolRegistry
        reg = ToolRegistry([calc])
        r = reg.invoke("no_such_tool", {})
        assert err(r) == "UNKNOWN_TOOL"

    def test_registry_manifest(self):
        from sciencemath.tools.router import build_default_registry
        manifest = build_default_registry().manifest()
        assert {m["name"] for m in manifest} == {
            "calculator", "symbolic_math", "equation_solver",
            "unit_converter", "numerical_math"}
        for m in manifest:
            assert m["input_schema"] and m["output_schema"]

    def test_ensure_json_safe_rejects(self):
        import sympy
        with pytest.raises(ToolError):
            ensure_json_safe(sympy.Integer(1))
        with pytest.raises(ToolError):
            ensure_json_safe(float("nan"))
        with pytest.raises(ToolError):
            ensure_json_safe(float("inf"))
        with pytest.raises(ToolError):
            ensure_json_safe({"k": {1, 2}})
        assert ensure_json_safe({"a": [1, 2.5, None, "x"]}) == \
            {"a": [1, 2.5, None, "x"]}

    def test_missing_argument(self):
        assert err(calc.run({})) == "INVALID_INPUT"

    def test_tools_never_raise(self):
        for tool, args in [(calc, {"expression": "((("}),
                           (sym, {"operation": "simplify",
                                  "expression": "((("}),
                           (eq, {"equation": "= ="}),
                           (conv, {"value": 1, "from_unit": ""}),
                           (num, {"operation": "describe", "values": []})]:
            r = tool.run(arguments=args)
            assert r.status == "error"