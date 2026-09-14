"""scicomp roots — bracketed and scalar root finding (T11.2).

* ``bracketed_root`` — expression + explicit bracket; Brent's method.
  A sign change must exist on the bracket, otherwise the request is
  rejected (no silent extrapolation).
* ``scalar_root`` — Newton's method with an optional bracket; when the
  iteration fails to converge the result is UNKNOWN, never a number
  presented as a root (T11.23 non-bracketed case).
* ``system_root`` — small square nonlinear systems (bounded dimension,
  bounded iterations); convergence status is always reported.

Every result carries the residual |f(root)| so diagnostics can judge it.
"""
from __future__ import annotations

import numpy as np
from scipy import optimize as sci_opt

from sciencemath.scicomp import sandbox
from sciencemath.scicomp.schemas import (Limits, finite_number,
                                         invalid_input, resource_limit,
                                         unknown_result)

MAX_SYSTEM_DIM = 8


def _make_f(expr: sandbox.SandboxedFunction):
    return lambda x: float(expr(x=x))


# --- bracketed root ---------------------------------------------------------

def bracketed_root(inputs: dict, options: dict, limits: Limits) -> dict:
    expr = sandbox.compile_expression(inputs.get("expression") or "",
                                      ["x"])
    lo = finite_number(inputs.get("bracket_low"), "bracket_low")
    hi = finite_number(inputs.get("bracket_high"), "bracket_high")
    if not lo < hi:
        raise invalid_input("'bracket_low' must be < 'bracket_high'")
    f = _make_f(expr)
    f_lo, f_hi = f(lo), f(hi)
    if f_lo == 0.0:
        return _root_result(float(lo), 0.0, "bracket endpoint is a root",
                            "brentq")
    if f_hi == 0.0:
        return _root_result(float(hi), 0.0, "bracket endpoint is a root",
                            "brentq")
    if f_lo * f_hi > 0:
        raise invalid_input(
            f"bracket [{lo}, {hi}] has no sign change (f(lo)={f_lo:.6g}, "
            f"f(hi)={f_hi:.6g}); cannot bracket a root")
    rtol = options.get("rtol", 1e-10)
    root, report = sci_opt.brentq(f, lo, hi, rtol=rtol, maxiter=200,
                                  full_output=True)
    if not report.converged:
        raise unknown_result("bracketed root search did not converge")
    return _root_result(float(root), abs(f(root)), "converged", "brentq")


# --- scalar root (optionally bracketed) ----------------------------------------

def scalar_root(inputs: dict, options: dict, limits: Limits) -> dict:
    expr = sandbox.compile_expression(inputs.get("expression") or "",
                                      ["x"])
    start = finite_number(inputs.get("initial_guess"), "initial_guess")
    f = _make_f(expr)
    lo = inputs.get("bracket_low")
    hi = inputs.get("bracket_high")
    method_args: dict = {}
    method = "newton"
    if lo is not None and hi is not None:
        lo_v = finite_number(lo, "bracket_low")
        hi_v = finite_number(hi, "bracket_high")
        if not lo_v < hi_v:
            raise invalid_input("'bracket_low' must be < 'bracket_high'")
        method_args = {"fprime": None}
        # Secant/newton with a bracket: scipy.secant would ignore it; use
        # brentq semantics but report as bracketed fallback.
        try:
            root, report = sci_opt.brentq(f, lo_v, hi_v, maxiter=200,
                                          full_output=True)
        except ValueError:
            raise invalid_input(
                f"bracket [{lo_v}, {hi_v}] has no sign change; cannot "
                "bracket a root")
        if not report.converged:
            raise unknown_result("bracketed root search did not converge")
        return _root_result(float(root), abs(f(root)), "converged",
                            "brentq")
    try:
        root = sci_opt.newton(f, start, tol=1e-10, maxiter=200,
                              **method_args)
    except (RuntimeError, sci_opt.ResetOptimization) as e:
        raise unknown_result(
            f"root iteration did not converge from initial guess "
            f"{start}: {e}")
    return _root_result(float(root), abs(f(root)),
                        "converged (unbracketed iteration; root is "
                        "candidate only)", method)


# --- nonlinear system -----------------------------------------------------------

def system_root(inputs: dict, options: dict, limits: Limits) -> dict:
    """Solve f(x) = 0 for a small square system of expressions.

    inputs: expressions = list of strings in variables x0..x(n-1),
    initial_guess = list of floats. Dimension capped at MAX_SYSTEM_DIM.
    """
    expressions = inputs.get("expressions")
    if not isinstance(expressions, list) or not expressions:
        raise invalid_input("'expressions' must be a non-empty list")
    n = len(expressions)
    if n > MAX_SYSTEM_DIM:
        raise resource_limit(
            f"system dimension {n} exceeds {MAX_SYSTEM_DIM}")
    var_names = [f"x{i}" for i in range(n)]
    funcs = [sandbox.compile_expression(e, var_names)
             for e in expressions]
    guess = inputs.get("initial_guess")
    if not isinstance(guess, list) or len(guess) != n:
        raise invalid_input(
            f"'initial_guess' must be a list of {n} numbers")
    x0 = np.asarray([finite_number(v, f"initial_guess[{i}]")
                     for i, v in enumerate(guess)])

    def system(vec: np.ndarray) -> np.ndarray:
        kwargs = {name: float(vec[i]) for i, name in enumerate(var_names)}
        return np.asarray([float(f(**kwargs)) for f in funcs])

    f0 = system(x0)
    if not np.all(np.isfinite(f0)):
        raise invalid_input("system is non-finite at the initial guess")
    sol = sci_opt.root(system, x0, method="hybr",
                       options={"maxfev": 5000})
    residual = float(np.max(np.abs(system(sol.x))))
    if not sol.success:
        raise unknown_result(
            f"system root search failed: {sol.message}")
    warnings = []
    status = "PASS"
    if residual > 1e-6:
        warnings.append(f"residual {residual:.3e} above 1e-6; root is "
                        "approximate")
        status = "NUMERICAL_WARNING"
    return {
        "result": {"root": sol.x.tolist()},
        "diagnostics": {"residual_norm": residual,
                        "converged": bool(sol.success),
                        "nfev": int(getattr(sol, "nfev", -1))},
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "scipy", "method": "root-hybr"},
    }


def _root_result(root: float, residual: float, message: str,
                 method: str) -> dict:
    warnings = []
    status = "PASS"
    if residual > 1e-6:
        warnings.append(f"residual {residual:.3e} above 1e-6")
        status = "NUMERICAL_WARNING"
    if "candidate only" in message:
        warnings.append(message)
        status = "NUMERICAL_WARNING"
    return {
        "result": {"root": root},
        "diagnostics": {"residual_norm": residual,
                        "convergence": message},
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "scipy", "method": method},
    }