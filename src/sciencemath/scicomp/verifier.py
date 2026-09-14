"""scicomp verifier — analytical vs numerical cross-checks (T11.10).

When both an analytical and a numerical route exist for a quantity, the
executor runs both where cheap and reports AGREE / DISAGREE /
NOT_AVAILABLE. Numerical agreement is a consistency signal, never formal
proof — the cross_check verdict is advisory and always separate from the
result payload.

Tolerances: a cross-check uses the operation's declared numerical
tolerance, not one global epsilon.
"""
from __future__ import annotations

import numpy as np
import sympy
from sympy.parsing.sympy_parser import standard_transformations

from sciencemath.scicomp.sandbox import SandboxedFunction

AGREE = "AGREE"
DISAGREE = "DISAGREE"
NOT_AVAILABLE = "NOT_AVAILABLE"


def compare(numerical: float, analytical: float, rtol: float,
            atol: float) -> str:
    """Compare two quantities within declared tolerances."""
    if numerical is None or analytical is None:
        return NOT_AVAILABLE
    if any(v != v or abs(v) == float("inf") for v in (numerical,
                                                      analytical)):
        return NOT_AVAILABLE
    return AGREE if abs(numerical - analytical) <= atol + rtol * abs(
        analytical) else DISAGREE


def cross_check(verdict: str, numerical: float | None,
                analytical: float | None, method: str) -> dict:
    """Build the envelope's cross_check block (T11.10, T11.15)."""
    return {
        "verdict": verdict,
        "numerical_value": numerical,
        "analytical_value": analytical,
        "analytical_method": method,
        "note": "numerical agreement is a consistency signal, "
                "not a formal proof",
    }


def symbolic_definite_integral(expression: SandboxedFunction, variable: str,
                               lower: float, upper: float) -> float | None:
    """Attempt a cheap symbolic antiderivative evaluation for the
    integrand. Returns the analytic value, or None when the integrand has
    no closed form found within bounded effort (never raises)."""
    try:
        sym_var = sympy.Symbol(variable, positive=True)
        parsed = sympy.parse_expr(
            expression.source, local_dict={variable: sym_var},
            transformations=standard_transformations,
        )
        primitive = sympy.integrate(parsed, sym_var)
        if not isinstance(primitive, sympy.Expr):
            return None
        f_lower = float(primitive.subs(sym_var, lower).evalf(15))
        f_upper = float(primitive.subs(sym_var, upper).evalf(15))
        value = f_upper - f_lower
        if value != value or abs(value) == float("inf"):
            return None
        return value
    except Exception:  # noqa: BLE001 — cross-check is best-effort
        return None


def linear_residual_check(a: np.ndarray, x: np.ndarray,
                          b: np.ndarray, rtol: float,
                          atol: float) -> dict:
    """Analytical verification for a solved linear system: A·x == b
    within tolerance. Direct substitution, no solver involved."""
    try:
        recon = a @ x
        ok = bool(np.allclose(recon, b, rtol=rtol, atol=atol))
        return cross_check(AGREE if ok else DISAGREE, None, None,
                           "A·x substitution (residual check)")
    except Exception:  # noqa: BLE001
        return cross_check(NOT_AVAILABLE, None, None, "A·x substitution")