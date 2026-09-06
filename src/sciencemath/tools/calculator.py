"""calculator — safe arithmetic evaluation of untrusted expressions.

Parses the expression with the safeparse AST whitelist, then evaluates the
AST directly (no eval, no exec). Guards against resource exhaustion:
integer powers with |exponent| > 10_000 are rejected, float overflow is
caught, and result magnitude is capped. Accepts LaTeX-ish input via
normalize_input (e.g. \\\\frac{3}{4}, \\\\sqrt{2}, 2^{10}).
"""
from __future__ import annotations

import ast
import math

from sciencemath.tools.base import Tool, ToolError, ToolResult, \
    run_with_timeout
from sciencemath.tools.safeparse import normalize_input, validate_ast

MAX_ABS_EXPONENT = 10_000
MAX_ABS_RESULT = 1e100
MAX_FACTORIAL_N = 10_000        # float conversion overflows far below this


class CalculatorTool(Tool):
    name = "calculator"
    description = (
        "Evaluate a pure arithmetic expression exactly. Input is a "
        "Python-style math expression (also accepts common LaTeX: \\frac, "
        "\\sqrt, ^, \\cdot). Functions: sqrt cbrt abs exp log log2 log10 "
        "sin cos tan asin acos atan sinh cosh tanh floor ceil round sign "
        "factorial gcd lcm min max. Constants: pi, e, tau. "
        "NO variables, NO eval, NO arbitrary Python."
    )
    input_schema = {"type": "object",
                    "required": ["expression"],
                    "properties": {"expression": {"type": "string"}}}
    output_schema = {"type": "object",
                     "properties": {"expression": {"type": "string"},
                                    "value": {"type": "number"},
                                    "exact": {"type": ["boolean", "null"]}}}

    def _checked_run(self, arguments: dict) -> ToolResult:
        raw = self._require_str(arguments, "expression")
        expr = normalize_input(raw)
        try:
            tree = validate_ast(expr, allow_calls=True)
        except ToolError:
            # second chance: token-based implicit multiplication (2x -> 2*x)
            from sciencemath.tools.safeparse import lenient_expression
            expr2 = lenient_expression(expr)
            tree = validate_ast(expr2, allow_calls=True)
            expr = expr2
        visitor = _EvalVisitor()
        # Wall-clock bound: pure-Python big-int arithmetic (e.g. deep
        # factorial trees) can otherwise run unbounded.
        value = run_with_timeout(lambda: visitor.eval(tree.body),
                                 self.default_timeout_s, "calculator")
        exact = visitor.exact
        if isinstance(value, int) and abs(value) > MAX_ABS_RESULT:
            raise ToolError("OVERFLOW",
                            f"integer result exceeds {MAX_ABS_RESULT:g}")
        return ToolResult(tool=self.name, status="ok",
                          result={"expression": expr, "value": value,
                                  "exact": exact})


class CalculatorTool(Tool):
    name = "calculator"
    description = (
        "Evaluate a pure arithmetic expression exactly. Input is a "
        "Python-style math expression (also accepts common LaTeX: \\frac, "
        "\\sqrt, ^, \\cdot). Functions: sqrt cbrt abs exp log log2 log10 "
        "sin cos tan asin acos atan sinh cosh tanh floor ceil round sign "
        "factorial gcd lcm min max. Constants: pi, e, tau. "
        "NO variables, NO eval, NO arbitrary Python."
    )
    input_schema = {"type": "object",
                    "required": ["expression"],
                    "properties": {"expression": {"type": "string"}}}
    output_schema = {"type": "object",
                     "properties": {"expression": {"type": "string"},
                                    "value": {"type": "number"},
                                    "exact": {"type": ["boolean", "null"]}}}

    def _checked_run(self, arguments: dict) -> ToolResult:
        raw = self._require_str(arguments, "expression")
        expr = normalize_input(raw)
        try:
            tree = validate_ast(expr, allow_calls=True)
        except ToolError:
            # second chance: token-based implicit multiplication (2x -> 2*x)
            from sciencemath.tools.safeparse import lenient_expression
            expr2 = lenient_expression(expr)
            tree = validate_ast(expr2, allow_calls=True)
            expr = expr2
        visitor = _EvalVisitor()
        value = visitor.eval(tree.body)
        exact = visitor.exact
        return ToolResult(tool=self.name, status="ok",
                          result={"expression": expr, "value": value,
                                  "exact": exact})


class _EvalVisitor:
    """AST walker producing a numeric value. exact=True iff the result came
    from pure integer arithmetic (no float rounding involved)."""

    def __init__(self) -> None:
        self.exact = True

    def eval(self, node: ast.AST):  # noqa: ANN202 — int|float tuple
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            consts = {"pi": math.pi, "e": math.e, "tau": math.tau}
            if node.id in consts:
                self.exact = False
                return consts[node.id]
            raise ToolError("INVALID_INPUT",
                            f"calculator does not accept variables ({node.id})")
        if isinstance(node, ast.UnaryOp):
            v = self.eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return v
            raise ToolError("INVALID_INPUT", "unary operator not supported")
        if isinstance(node, ast.BinOp):
            left, right = self.eval(node.left), self.eval(node.right)
            both_int = isinstance(left, int) and isinstance(right, int)
            if isinstance(node.op, ast.Add):
                out = left + right
            elif isinstance(node.op, ast.Sub):
                out = left - right
            elif isinstance(node.op, ast.Mult):
                out = left * right
            elif isinstance(node.op, ast.Div):
                self.exact = False
                if right == 0:
                    raise ToolError("DIVISION_BY_ZERO", "division by zero")
                out = left / right
            elif isinstance(node.op, ast.FloorDiv):
                if right == 0:
                    raise ToolError("DIVISION_BY_ZERO", "division by zero")
                out = left // right
            elif isinstance(node.op, ast.Mod):
                if right == 0:
                    raise ToolError("DIVISION_BY_ZERO", "modulo by zero")
                out = left % right
            elif isinstance(node.op, ast.Pow):
                out = self._pow(left, right)
            else:  # pragma: no cover — validate_ast prevents this
                raise ToolError("INVALID_INPUT", "operator not supported")
            if both_int and isinstance(out, int):
                pass                      # pure integer arithmetic stays exact
            else:
                self.exact = False
            if isinstance(out, int) and abs(out) > 10 ** 400:
                raise ToolError("OVERFLOW", "integer result too large")
            if isinstance(out, float) and (
                    out != out or abs(out) > 1e300):
                raise ToolError("OVERFLOW", f"numeric result out of range")
            return out
        if isinstance(node, ast.Call):
            return self._call(node)
        raise ToolError("INVALID_INPUT",
                        f"unsupported construct {type(node).__name__}")

    @staticmethod
    def _pow(left, right):
        if isinstance(right, int) and abs(right) > MAX_ABS_EXPONENT:
            raise ToolError("OVERFLOW",
                            f"exponent {right} exceeds limit "
                            f"{MAX_ABS_EXPONENT}")
        if isinstance(left, int) and isinstance(right, int) and right >= 0:
            if right * max(1, abs(left)).bit_length() > 4000:
                raise ToolError("OVERFLOW", "power result too large")
            return left ** right
        try:
            out = left ** right
        except (OverflowError, ZeroDivisionError) as e:
            raise ToolError("OVERFLOW", f"power failed: {e}")
        if isinstance(out, complex):
            raise ToolError("INVALID_INPUT",
                            "complex results not supported")
        return out

    def _call(self, node: ast.Call) -> float:
        if not isinstance(node.func, ast.Name):  # pragma: no cover
            raise ToolError("INVALID_INPUT", "invalid call target")
        name = node.func.id
        args = [self.eval(a) for a in node.args]
        self.exact = False
        funcs = {
            "sqrt": lambda x: math.sqrt(x),
            "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
            "abs": abs,
            "exp": math.exp,
            "log": lambda x, *b: math.log(x, *b),
            "log2": math.log2,
            "log10": math.log10,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan,
            "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
            "floor": lambda x: float(math.floor(x)),
            "ceil": lambda x: float(math.ceil(x)),
            "round": lambda x, *n: float(round(x, *n)),
            "sign": lambda x: float((x > 0) - (x < 0)),
            "factorial": lambda n: float(math.factorial(n))
            if n >= 0 else _bad("negative factorial")
            if n <= MAX_FACTORIAL_N else _bad("factorial argument too large"),
            "gcd": math.gcd, "lcm": math.lcm,
            "min": lambda *a: min(_flat(a)),
            "max": lambda *a: max(_flat(a)),
        }
        fn = funcs.get(name)
        if fn is None:
            raise ToolError("UNKNOWN_FUNCTION",
                            f"function {name!r} not available in calculator")
        try:
            out = fn(*args)
        except (ValueError, OverflowError, ZeroDivisionError) as e:
            raise ToolError("DOMAIN_ERROR", f"{name}: {e}")
        except TypeError as e:
            raise ToolError("INVALID_INPUT",
                            f"{name}: invalid argument type ({e})")
        if isinstance(out, float) and (out != out or abs(out) == float("inf")):
            raise ToolError("DOMAIN_ERROR", f"{name} produced non-finite value")
        return out


def _flat(args):
    out = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(a)
        else:
            out.append(a)
    return out


def _bad(msg: str):
    raise ToolError("DOMAIN_ERROR", msg)