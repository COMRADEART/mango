"""symbolic_math — SymPy-backed symbolic operations behind the safety gate.

Every input expression passes through safeparse.normalize_input ->
lenient_expression -> validate_ast BEFORE sympy.parsing.parse_expr sees it.
parse_expr alone executes via eval (a documented injection surface: the
sympy global namespace includes __builtins__), so the AST whitelist gate is
what makes this safe: only whitelisted arithmetic and function calls can
ever reach parse_expr.

All operations run under a wall-clock timeout (SymPy can hang on hard
integrals). Every timeout degrades to a deterministic UNKNOWN-style error
result, never to a guessed answer.
"""
from __future__ import annotations

import hashlib
import random

import sympy
from sympy import (Abs, E, Max, Min, Symbol, binomial, ceiling, cos, exp,
                   factorial, floor, gamma, gcd, lcm, log, pi, sign, sin,
                   sqrt, tan)

from sympy.parsing.sympy_parser import standard_transformations

from sciencemath.tools.base import Tool, ToolError, ToolResult, \
    run_with_timeout
from sciencemath.tools.safeparse import (lenient_expression,
                                         normalize_input, validate_ast)

DEFAULT_TIMEOUT_S = 10.0

# Restricted namespace for parse_expr: ONLY these names resolve (plus the
# auto-created Symbols); __builtins__ never matters because validate_ast has
# already excluded every non-whitelisted name/call from the string.
_SAFE_GLOBALS: dict = {
    # constructors emitted by standard_transformations themselves — the
    # transformed code the evaluator runs is exactly the string validate_ast
    # approved plus Symbol()/Integer() wrappers, so these are the only extra
    # names parse_expr can reach
    "Symbol": Symbol, "Integer": sympy.Integer, "Float": sympy.Float,
    "Rational": sympy.Rational,
    # NOTE: bare "e" is Euler's number here, not a free symbol (documented
    # trade-off: scientific answers use e as the constant, not a variable)
    "pi": pi, "tau": 2 * pi, "e": E, "E": E,
    "sqrt": sqrt, "cbrt": sympy.cbrt, "exp": exp,
    "log": log, "log2": lambda x: log(x, 2), "log10": lambda x: log(x, 10),
    "sin": sin, "cos": cos, "tan": tan,
    "asin": sympy.asin, "acos": sympy.acos, "atan": sympy.atan,
    "sinh": sympy.sinh, "cosh": sympy.cosh, "tanh": sympy.tanh,
    "asinh": sympy.asinh, "acosh": sympy.acosh, "atanh": sympy.atanh,
    "floor": floor, "ceil": ceiling, "sign": sign,
    "factorial": factorial, "gcd": gcd, "lcm": lcm,
    "min": Min, "max": Max, "binomial": binomial, "gamma": gamma,
    "abs": Abs,
}


def safe_parse(expression: str, *, lenient: bool = True,
               timeout_s: float = DEFAULT_TIMEOUT_S) -> sympy.Expr:
    """Parse an untrusted expression string into a sympy expression.

    Safety chain: normalize -> (lenient) -> AST whitelist -> parse_expr with
    the restricted namespace above. Raises ToolError(PARSE_ERROR /
    DISALLOWED_EXPRESSION / TIMEOUT).
    """
    expr = normalize_input(expression)
    if lenient and expr:
        try:
            expr = lenient_expression(expr)
        except ToolError:
            pass                                  # fall back to strict parse
    validate_ast(expr, allow_calls=True)
    try:
        parsed = run_with_timeout(
            lambda: sympy.parsing.sympy_parser.parse_expr(
                expr, local_dict={}, global_dict=dict(_SAFE_GLOBALS),
                transformations=standard_transformations),
            timeout_s, "sympy parse")
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ToolError("PARSE_ERROR", f"cannot parse expression: {e}")
    if parsed is None:
        raise ToolError("PARSE_ERROR", "empty expression")
    return parsed


def numeric_value(expr: sympy.Expr, tol: float = 1e-9) -> float | None:
    """Best-effort float value of a sympy expression, None if symbolic."""
    try:
        val = float(expr.evalf(15))
    except (TypeError, ValueError):  # pragma: no cover
        return None
    if val != val or val in (float("inf"), float("-inf")):
        return None
    return val


def symbolic_equivalence(a: sympy.Expr, b: sympy.Expr,
                         timeout_s: float = DEFAULT_TIMEOUT_S,
                         sample_tol: float = 1e-8) -> str:
    """Decide equivalence of two sympy expressions: PASS / FAIL / UNKNOWN.

    Method (in order, stopping at the first decisive answer):
      1. structural: a == b (sympy auto-simplification may already match)
      2. exact: simplify(a - b) == 0 under a timeout
      3. numeric: evaluate both at 7 deterministic sample points derived
         from a hash of the two expressions (distinct value per free
         symbol); every valid pair must agree to sample_tol * max(1, |b|).
         Poles (failed evaluations) are skipped; at least 3 valid pairs
         with NO complex-valued samples are required for PASS — complex
         results mean branch-sensitive functions, where numeric agreement
         on the real points is not decisive, so those degrade to UNKNOWN.
         Never forces an uncertain case.
    """
    if a == b:
        return "PASS"
    try:
        diff = run_with_timeout(lambda: sympy.simplify(a - b),
                                timeout_s, "simplify")
        if diff == 0:
            return "PASS"
    except ToolError as e:
        if e.code == "TIMEOUT":
            return "UNKNOWN"
        raise
    except Exception:  # noqa: BLE001 — simplify can fail oddly; fall through
        pass

    symbols = sorted(a.free_symbols | b.free_symbols, key=lambda s: s.name)
    if not symbols:
        try:
            fa, fb = float(a.evalf(15)), float(b.evalf(15))
        except (TypeError, ValueError):
            return "UNKNOWN"
        if fa != fa or fb != fb:
            return "UNKNOWN"
        # constant comparison tolerance matches the verifier's documented
        # numeric tolerance (1e-6 relative): 6 significant digits must agree
        return "PASS" if abs(fa - fb) <= 1e-6 * max(1.0, abs(fb)) + 1e-9 \
            else "FAIL"

    # Sample points are derived per call from a hash of BOTH expressions
    # (deterministic, but not a fixed public list): an adversary cannot
    # precompute a nullifier polynomial that vanishes on all sample points
    # without knowing the hash-derived points for this exact pair.
    seed = int.from_bytes(
        hashlib.sha256((sympy.sstr(a) + "|" + sympy.sstr(b))
                       .encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    sample_points = []
    for i in range(7):  # mix of signs: poles/domain limits get fewer hiding spots
        u = rng.uniform(0.05, 4.7)
        sample_points.append(u if i % 2 == 0 else -u)

    valid = 0
    saw_complex = False
    for point in sample_points:
        # Distinct value per free symbol — evaluating all symbols at the
        # same value would grade "x" equivalent to "y" and "2*a*t" to
        # "2*b*t" (any difference invisible when a == b numerically).
        subs = {s: sympy.Float(point + i * 0.3717)
                for i, s in enumerate(symbols)}
        try:
            fa = float((a).subs(subs).evalf(15))
            fb = float((b).subs(subs).evalf(15))
        except ZeroDivisionError:
            continue  # pole — legitimately uninformative sample
        except (TypeError, ValueError):
            # Complex result (branch cut / negative sqrt / log): the
            # numeric-only method is NOT decisive for branch-sensitive
            # functions — agreement on the real points where both sides
            # happen to be real proves nothing (e.g. log(x**2) vs 2*log(x)).
            saw_complex = True
            continue
        if fa != fa or fb != fb or \
                fa in (float("inf"), float("-inf")) or \
                fb in (float("inf"), float("-inf")):
            continue
        valid += 1
        if abs(fa - fb) > sample_tol * max(1.0, abs(fb)):
            return "FAIL"
    if valid >= 3 and not saw_complex:
        return "PASS"
    return "UNKNOWN"


def expression_to_string(expr: sympy.Expr) -> str:
    """Deterministic JSON-safe string form of a sympy expression."""
    return sympy.sstr(expr)


def _limit_value(v, name: str) -> sympy.Expr:
    """Integral bound: a JSON number, or a constant expression string
    ("pi", "-1", "oo"). float(str) crashed on "pi" (INTERNAL_ERROR)."""
    if isinstance(v, bool):
        raise ToolError("INVALID_INPUT", f"{name} must be a number")
    if isinstance(v, (int, float)):
        return sympy.Rational(v) if isinstance(v, int) else sympy.Float(v)
    if isinstance(v, str):
        return safe_parse(v.strip(), lenient=False)
    raise ToolError("INVALID_INPUT", f"{name} must be a number")


def _infer_var(arguments: dict, expr: sympy.Expr, tool_name: str) -> str:
    """Resolve the differentiation/integration variable.

    Explicit 'var' wins. When omitted, a single free symbol is inferred —
    the benchmark model omitted 'var' in 10/34 tool calls (all deterministic
    INVALID_INPUT rejections). Multi-symbol expressions still require an
    explicit 'var' (ambiguous otherwise)."""
    var = arguments.get("var")
    if isinstance(var, str) and var.strip():
        return var.strip()
    syms = sorted(expr.free_symbols, key=lambda s: s.name)
    if len(syms) == 1:
        return syms[0].name
    raise ToolError("INVALID_INPUT",
                    "missing 'var' (expression has "
                    f"{len(syms)} free symbols — pass 'var' explicitly)")


class SymbolicMathTool(Tool):
    name = "symbolic_math"
    description = (
        "Symbolic mathematics via SymPy. operations: simplify, expand, "
        "factor, derivative ([var], order — var inferred when the "
        "expression has exactly one free symbol), integral ([var], [a, b] "
        "for definite), evaluate (numeric, digits). Input is an algebraic "
        "expression in Python-style syntax. NO arbitrary Python execution."
    )
    input_schema = {"type": "object",
                    "required": ["operation", "expression"],
                    "properties": {
                        "operation": {"type": "string", "enum": [
                            "simplify", "expand", "factor", "derivative",
                            "integral", "evaluate"]},
                        "expression": {"type": "string"},
                        "var": {"type": "string"},
                        "order": {"type": "integer"},
                        "lower": {"type": "number"},
                        "upper": {"type": "number"},
                        "digits": {"type": "integer"}}}
    output_schema = {"type": "object",
                     "properties": {"operation": {"type": "string"},
                                    "result": {"type": "string"},
                                    "latex": {"type": "string"},
                                    "numeric": {"type": ["number", "null"]}}}

    def _checked_run(self, arguments: dict) -> ToolResult:
        operation = self._require_str(arguments, "operation")
        raw = self._require_str(arguments, "expression")
        timeout = float(arguments.get("timeout_s", DEFAULT_TIMEOUT_S))
        expr = safe_parse(raw, timeout_s=timeout)
        if isinstance(expr, bool) or not isinstance(expr, sympy.Basic):
            expr = sympy.sympify(expr)

        if operation == "simplify":
            out = run_with_timeout(lambda: sympy.simplify(expr),
                                   timeout, "simplify")
        elif operation == "expand":
            out = run_with_timeout(lambda: sympy.expand(expr),
                                   timeout, "expand")
        elif operation == "factor":
            out = run_with_timeout(lambda: sympy.factor(expr),
                                   timeout, "factor")
        elif operation == "derivative":
            var = _infer_var(arguments, expr, self.name)
            order = int(arguments.get("order", 1))
            if order < 1 or order > 10:
                raise ToolError("INVALID_INPUT", "order must be 1..10")
            sym = Symbol(var)
            if sym not in expr.free_symbols:
                raise ToolError("INVALID_INPUT",
                                f"variable {var!r} not in expression")
            out = run_with_timeout(
                lambda: sympy.diff(expr, sym, order), timeout, "derivative")
        elif operation == "integral":
            var = _infer_var(arguments, expr, self.name)
            sym = Symbol(var)
            if "lower" in arguments and "upper" in arguments:
                lo, hi = _limit_value(arguments["lower"], "lower"), \
                    _limit_value(arguments["upper"], "upper")
                out = run_with_timeout(
                    lambda: sympy.integrate(expr, (sym, lo, hi)),
                    timeout, "integral")
                numeric = numeric_value(out)
            else:
                out = run_with_timeout(lambda: sympy.integrate(expr, sym),
                                       timeout, "integral")
                numeric = None
        elif operation == "evaluate":
            digits = int(arguments.get("digits", 12))
            if not 1 <= digits <= 50:
                raise ToolError("INVALID_INPUT", "digits must be 1..50")
            out = expr.evalf(digits)
            numeric = numeric_value(out)
        else:
            raise ToolError("INVALID_INPUT",
                            f"unknown operation {operation!r}")

        numeric = numeric if operation in ("integral", "evaluate") \
            else numeric_value(out)
        return ToolResult(tool=self.name, status="ok",
                          result={"operation": operation,
                                  "result": expression_to_string(out),
                                  "latex": sympy.latex(out),
                                  "numeric": numeric})