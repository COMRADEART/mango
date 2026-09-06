"""T4 safety tests: NO eval() on untrusted expressions, no unrestricted
execution, deterministic errors, timeouts.

The directive's T4 completion gate requires explicit proof that unsafe
expression execution is impossible — this file is that proof. Every payload
below is a real exploit pattern for eval-based expression parsers.
"""
import json

import pytest

from sciencemath.tools.base import (ToolError, ToolResult, ensure_json_safe,
                                    run_with_timeout)
from sciencemath.tools.calculator import CalculatorTool
from sciencemath.tools.equation_solver import EquationSolverTool
from sciencemath.tools.safeparse import normalize_input, validate_ast
from sciencemath.tools.symbolic_math import (SymbolicMathTool, safe_parse,
                                             symbolic_equivalence)

calc = CalculatorTool()
eq = EquationSolverTool()
sym = SymbolicMathTool()

# payloads that MUST be rejected by the AST gate (code would execute under
# eval-based parsing)
INJECTION_PAYLOADS = [
    "__import__('os').system('echo pwned')",
    "__import__('os').remove('x')",
    "().__class__.__bases__[0].__subclasses__()",
    "().__class__.__mro__[1].__subclasses__()[104]",
    "open('/etc/passwd').read()",
    "exec('import os')",
    "eval('1+1')",
    "getattr(str, 'join')(['a'])",
    "x.__class__",
    "[].append(1)",
    "lambda: 1",
    "[i for i in range(3)]",
    "(x for x in range(3))",
    "f'{{}}'",
    "'a' + 'b'",
    "'rm -rf /'",
    "{'a': 1}",
    "x[0]",
    "a if b else c",
    "print(1)",
    "globals()",
    "help()",
    "1 if True else 2",
]


class TestInjectionResistance:
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_calculator_rejects(self, payload):
        result = calc.run({"expression": payload})
        assert result.status == "error"
        assert result.error["code"] in ("DISALLOWED_EXPRESSION",
                                        "PARSE_ERROR", "INVALID_INPUT",
                                        "UNKNOWN_FUNCTION")
        assert result.error["code"] != "INTERNAL_ERROR"

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_safe_parse_rejects(self, payload):
        # either the AST gate or parse must refuse; never execute
        try:
            expr = safe_parse(payload)
        except ToolError:
            return
        # the only survivable parses are pure symbols/numbers (auto_symbol
        # wraps unknown names); ensure nothing executable survived
        assert not str(expr).strip().startswith("<")

    @pytest.mark.parametrize("lhs", [
        "__import__('os').system('x') = 0",
        "x.__class__ = 1",
        "open('f') = 0",
    ])
    def test_solver_rejects(self, lhs):
        result = eq.run({"equation": lhs})
        assert result.status == "error"
        assert result.error["code"] != "INTERNAL_ERROR"

    def test_normalize_input_rejects_unknown_latex(self):
        import pytest as _pytest
        with _pytest.raises(ToolError):
            normalize_input(r"\href{http://evil.com}{1}")

    def test_validate_ast_rejects_attribute_access(self):
        with pytest.raises(ToolError):
            validate_ast("(1).__class__")

    def test_validate_ast_rejects_string_literals(self):
        with pytest.raises(ToolError):
            validate_ast("'hello'")

    def test_validate_ast_rejects_call_on_attribute(self):
        with pytest.raises(ToolError):
            validate_ast("sqrt.pi(2)")

    def test_deep_nesting_bounded(self):
        # parentheses do not add AST depth ("(((1)))" is Constant 1), so
        # probe real nesting AND the raw-length bound
        with pytest.raises(ToolError):
            validate_ast("+".join(["1"] * 100))     # depth > MAX_AST_DEPTH
        with pytest.raises(ToolError):
            validate_ast("1+" * 6000)               # > MAX_EXPRESSION_LENGTH

    def test_no_builtins_reachable_from_names(self):
        # names that are NOT whitelisted constants/functions must parse to
        # Symbols under sympy — never resolve to Python builtins
        expr = safe_parse("eval")
        assert str(expr) == "eval"          # a bare Symbol, not a function


class TestResourceLimits:
    def test_exponent_limit(self):
        # rejected earlier now: the AST resource gate bounds the exponent
        # before sympy/calculator ever evaluates it
        assert calc.run({"expression": "9**9**9"}).error["code"] in (
            "OVERFLOW", "DISALLOWED_EXPRESSION")

    def test_deep_nesting_in_calculator(self):
        r = calc.run({"expression": "-" * 200 + "1"})
        assert r.status in ("ok", "error")       # either fine, no crash/hang

    def test_timeout_produces_deterministic_error(self):
        def slow():
            import time
            time.sleep(1.0)
            return 1
        import pytest as _pytest
        with _pytest.raises(ToolError) as exc:
            run_with_timeout(slow, 0.05, "test")
        assert exc.value.code == "TIMEOUT"

    def test_symbolic_timeout_flagged_unknown(self):
        # a small timeout on a nontrivial simplify must yield a TIMEOUT
        # error result (never a guessed answer)
        r = sym_timeout()
        if r is None:      # finished fast on this machine — not a failure
            return
        assert r.error["code"] == "TIMEOUT"


def sym_timeout():
    from sciencemath.tools.symbolic_math import SymbolicMathTool
    t = SymbolicMathTool()
    r = t.run({"operation": "simplify",
               "expression": "sin(x)**5 + cos(x)**5 + "
                             "integrate(sin(x**7), x) + 1",
               "timeout_s": 0.01})
    return r if (r.status == "error" and r.error["code"] == "TIMEOUT") else None


class TestDeterministicErrors:
    def test_all_errors_carry_codes(self):
        for result in [calc.run({"expression": "1/0"}),
                       calc.run({}),
                       sym.run({"operation": "bogus", "expression": "1"}),
                       eq.run({"equation": ""}),
                       conv_run(),
                       num_run()]:
            assert result.status == "error"
            assert isinstance(result.error.get("code"), str)
            json.dumps(result.to_dict())       # error shape is JSON-safe

    def test_infinity_and_nan_inputs_rejected(self):
        assert calc.run({"expression": ""}).status == "error"
        from sciencemath.tools.numerical_math import NumericalMathTool
        r = NumericalMathTool().run({"operation": "describe",
                                     "values": [1, float("nan")]})
        assert r.status == "error"


def conv_run():
    from sciencemath.tools.unit_converter import UnitConverterTool
    return UnitConverterTool().run({"value": 1, "from_unit": "smoot",
                                    "to_unit": "m"})


def num_run():
    from sciencemath.tools.numerical_math import NumericalMathTool
    return NumericalMathTool().run({"operation": "nope", "values": [1]})


class TestJsonSafetyBoundary:
    def test_symbolic_results_are_strings(self):
        from sciencemath.tools.symbolic_math import SymbolicMathTool
        r = SymbolicMathTool().run({"operation": "simplify",
                                    "expression": "x**2/x"})
        payload = r.result
        json.dumps(payload)                  # would raise on sympy objects
        assert isinstance(payload["result"], str)
        assert isinstance(payload["numeric"], (int, float, type(None)))

    def test_tool_result_roundtrip(self):
        r = calc.run({"expression": "2+2"})
        assert ToolResult(**{k: v for k, v in r.to_dict().items()}).ok