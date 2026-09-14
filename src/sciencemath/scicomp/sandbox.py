"""scicomp sandbox — safe expression language for scientific operations.

T11.5 contract: equations and functions entered as strings are parsed by
the SAME hardened AST whitelist the T4 calculator uses
(`sciencemath.tools.safeparse`): numeric literals, named variables,
arithmetic operators, bounded exponentiation, approved elementary
functions. Attribute access, imports, comprehensions, lambdas, dunder
names, assignments, strings, subscripts and every other construct are
rejected before any evaluation happens. `eval()` on raw text is never
called.

On top of that gate this module adds the scicomp-specific rules:

* every free name must be a *declared variable* (e.g. the state variables
  of an ODE right-hand side) or an approved constant (pi, e, tau) —
  unknown names are rejected up front, not NameError at runtime;
* the validated expression is compiled once into a code object and
  evaluated against a namespace containing ONLY the declared variables,
  the whitelisted functions (math + numpy variants for array support)
  and the approved constants. `__builtins__` is stripped;
* evaluation results are guarded: non-finite outputs (NaN/inf, including
  overflow to inf) are surfaced as a domain error rather than silently
  propagating (T11.23);
* exponent bombs are bounded twice — statically by safeparse's
  MAX_STATIC_EXPONENT and at runtime by result magnitude checks.

The sandbox owns ONLY expressions. It never sees shell commands, file
paths, imports, or arbitrary Python (T11.3, T11.33).
"""
from __future__ import annotations

import ast
import math

import numpy as np

from sciencemath.scicomp.schemas import ScicompError, invalid_input
from sciencemath.tools import safeparse
from sciencemath.tools.base import ToolError

# Elementary functions exposed to sandboxed expressions. Numpy variants
# are used so ODE right-hand sides can operate elementwise on state
# vectors. math.* fallbacks would not vectorize; np ufuncs on scalars
# return numpy scalars, which _finite_output converts to float.
_FUNCTION_TABLE: dict[str, object] = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    "asinh": np.arcsinh, "acosh": np.arccosh, "atanh": np.arctanh,
    "exp": np.exp, "log": np.log, "log2": np.log2, "log10": np.log10,
    "sqrt": np.sqrt, "cbrt": np.cbrt, "abs": np.abs,
    "floor": np.floor, "ceil": np.ceil, "sign": np.sign,
}

_CONSTANT_TABLE: dict[str, float] = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
}

# Names an expression may reference: declared variables are supplied by
# the caller; constants and functions come from the tables above.
_ALLOWED_CONST_NAMES = frozenset(_CONSTANT_TABLE)
_ALLOWED_FUNC_NAMES = frozenset(_FUNCTION_TABLE)

# Bound on |value| flowing through a sandboxed evaluation: guards
# exponent bombs that survive the static exponent check (e.g. nested
# products of large floats overflowing to inf gradually).
_MAX_EVAL_MAGNITUDE = 1e100


def validate_expression(expression: str, variables: list[str]) -> str:
    """Validate an expression string and return the normalized source.

    Runs the T4 safeparse gate (LaTeX normalization, implicit
    multiplication, AST whitelist), then rejects free names that are not
    declared variables, approved constants, or approved functions.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise invalid_input("expression must be a non-empty string")
    if len(expression) > 2000:
        raise ScicompError("RESOURCE_LIMIT",
                           "expression exceeds 2000 characters")
    for var in variables:
        if not var.isidentifier() or var in _ALLOWED_FUNC_NAMES \
                or var in _ALLOWED_CONST_NAMES:
            raise invalid_input(f"invalid variable name {var!r}")
    try:
        normalized = safeparse.lenient_expression(
            safeparse.normalize_input(expression))
        tree = safeparse.validate_ast(normalized)
    except ToolError as e:
        # Deterministic mapping: the T4 gate's rejection codes become
        # scicomp INVALID_INPUT with the original message preserved.
        raise invalid_input(f"expression rejected [{e.code}]: {e.message}")
    _check_free_names(tree.body, set(variables))
    return normalized


def _check_free_names(node: ast.AST, variables: set[str]) -> None:
    """Reject any Name that is not a declared variable / constant.

    Function names are legal ONLY as the callee of a Call node (the AST
    gate already restricts which functions may be called); a bare
    reference to a function name — e.g. passing ``cos`` around — is
    rejected since there is nothing to pass it to.
    """
    called = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            called.add(sub.func.id)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            name = sub.id
            if name in variables or name in _ALLOWED_CONST_NAMES:
                continue
            if name in _ALLOWED_FUNC_NAMES:
                if name in called:
                    continue
                raise invalid_input(
                    f"function {name!r} must be called, not referenced")
            raise invalid_input(f"unknown name {name!r} in expression "
                                f"(declared variables: {sorted(variables)})")


def compile_expression(expression: str, variables: list[str]) -> "SandboxedFunction":
    """Validate an expression and compile it into a sandboxed callable.

    The returned callable takes keyword arguments matching ``variables``
    (scalars or numpy arrays) and returns a float or ndarray. Because the
    AST passed safeparse's whitelist and the namespace contains no
    builtins, no attribute access, import, or call outside the approved
    table is reachable (T11.25).
    """
    normalized = validate_expression(expression, variables)
    tree = ast.parse(normalized, mode="eval")
    code = compile(tree, "<scicomp-sandboxed>", "eval")
    return SandboxedFunction(expression, tuple(variables), code)


class SandboxedFunction:
    """A compiled, validated expression with a closed evaluation namespace."""

    def __init__(self, source: str, variables: tuple[str, ...], code):
        self.source = source
        self.variables = variables
        self._code = code

    def __call__(self, **kwargs: object) -> object:
        missing = [v for v in self.variables if v not in kwargs]
        if missing:
            raise invalid_input(
                f"missing values for variable(s): {', '.join(missing)}")
        namespace: dict[str, object] = {k: kwargs[k]
                                        for k in self.variables}
        namespace.update(_CONSTANT_TABLE)
        namespace.update(_FUNCTION_TABLE)
        # No __builtins__ key at all: even a smuggled name lookup finds
        # nothing but the tables above.
        namespace["__builtins__"] = {}
        try:
            with np.errstate(over="ignore", invalid="ignore",
                             divide="ignore"):
                # Overflow/NaN are detected and surfaced below as
                # deterministic failures, not warnings.
                value = eval(self._code, namespace)  # noqa: S307 — gated AST
        except ScicompError:
            raise
        except ZeroDivisionError:
            raise ScicompError("FAIL", "division by zero in expression")
        except OverflowError:
            raise ScicompError("FAIL", "overflow in expression evaluation")
        except (TypeError, ValueError) as e:
            raise invalid_input(f"expression evaluation failed: {e}")
        except RecursionError:
            raise ScicompError("RESOURCE_LIMIT",
                               "expression evaluation too deep")
        return _finite_output(value)


def _finite_output(value: object) -> object:
    """Guard evaluation output: reject NaN/inf and runaway magnitude."""
    if isinstance(value, np.ndarray):
        if value.size > 1_000_000:
            raise ScicompError("RESOURCE_LIMIT", "expression output too large")
        if not np.all(np.isfinite(value)):
            raise ScicompError("FAIL",
                               "expression produced non-finite values "
                               "(NaN or infinity)")
        if np.any(np.abs(value) > _MAX_EVAL_MAGNITUDE):
            raise ScicompError("FAIL",
                               "expression output exceeds magnitude bound "
                               f"{_MAX_EVAL_MAGNITUDE:.0e}")
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        v = float(value)
        if v != v or v in (float("inf"), float("-inf")):
            raise ScicompError(
                "FAIL", "expression produced non-finite value "
                        "(NaN or infinity)")
        if abs(v) > _MAX_EVAL_MAGNITUDE:
            raise ScicompError("FAIL",
                               "expression output exceeds magnitude bound "
                               f"{_MAX_EVAL_MAGNITUDE:.0e}")
        return v
    raise ScicompError("FAIL",
                       f"expression produced unsupported type "
                       f"{type(value).__name__}")