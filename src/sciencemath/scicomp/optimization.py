"""scicomp optimization — bounded scalar and multivariate minimization
(T11.2, T11.30).

Every optimization result must carry its convergence status. A run that
did not converge is UNKNOWN, never a "proven optimum". Even a converged
result is explicitly labeled a LOCAL optimum unless the operation and the
objective guarantee otherwise — global optimality is NOT ESTABLISHED by
this laboratory (T11.30).
"""
from __future__ import annotations

import numpy as np
from scipy import optimize as sci_opt

from sciencemath.scicomp import sandbox
from sciencemath.scicomp.schemas import (Limits, finite_number, finite_list,
                                         invalid_input, resource_limit,
                                         unknown_result)

MAX_VARS = 8


# --- scalar minimization -----------------------------------------------------

def minimize_scalar(inputs: dict, options: dict, limits: Limits) -> dict:
    expr = sandbox.compile_expression(inputs.get("expression") or "",
                                      ["x"])
    lo = finite_number(inputs.get("bound_low"), "bound_low")
    hi = finite_number(inputs.get("bound_high"), "bound_high")
    if not lo < hi:
        raise invalid_input("'bound_low' must be < 'bound_high'")
    f = lambda x: float(expr(x=x))  # noqa: E731
    result = sci_opt.minimize_scalar(
        f, bounds=(lo, hi), method="bounded",
        options={"maxiter": min(500, limits.max_optimization_iterations)})
    if not result.success:
        raise unknown_result(
            f"scalar minimization did not converge: {result.message}")
    return {
        "result": {
            "optimum_x": float(result.x),
            "optimum_value": float(result.fun),
            "optimum_kind": "LOCAL (bounded search); global optimum NOT "
                            "ESTABLISHED",
        },
        "diagnostics": {
            "converged": True,
            "status_message": str(result.message),
            "iterations": int(result.nit),
            "objective_value": float(result.fun),
            "nfev": int(result.nfev),
        },
        "provenance": {"engine": "scipy", "method": "minimize_scalar-bounded"},
    }


# --- bounded multivariate minimization ------------------------------------------

def minimize(inputs: dict, options: dict, limits: Limits) -> dict:
    expressions = inputs.get("expression") or inputs.get("objective")
    if not isinstance(expressions, str):
        raise invalid_input("'expression' must be an objective expression "
                            "string")
    bounds_raw = inputs.get("bounds")
    if not isinstance(bounds_raw, list):
        raise invalid_input("'bounds' must be a list of [low, high] pairs")
    n = len(bounds_raw)
    if n == 0:
        raise invalid_input("'bounds' must not be empty")
    if n > MAX_VARS:
        raise resource_limit(f"variable count {n} exceeds {MAX_VARS}")
    var_names = [f"x{i}" for i in range(n)]
    f_expr = sandbox.compile_expression(expressions, var_names)
    bounds = []
    for i, pair in enumerate(bounds_raw):
        if not isinstance(pair, list) or len(pair) != 2:
            raise invalid_input(
                f"bounds[{i}] must be a [low, high] pair")
        lo = finite_number(pair[0], f"bounds[{i}][0]")
        hi = finite_number(pair[1], f"bounds[{i}][1]")
        if not lo < hi:
            raise invalid_input(
                f"bounds[{i}]: low must be < high")
        bounds.append((lo, hi))
    x0_raw = inputs.get("initial_guess")
    if x0_raw is None:
        x0 = np.array([lo + (hi - lo) / 2 for lo, hi in bounds])
    else:
        x0_list = finite_list(x0_raw, "initial_guess", MAX_VARS)
        if len(x0_list) != n:
            raise invalid_input(
                f"'initial_guess' must have {n} entries")
        x0 = np.asarray(x0_list)
        # Clip into bounds: L-BFGS-B requires x0 within bounds.
        x0 = np.asarray([min(max(v, lo), hi)
                         for v, (lo, hi) in zip(x0_list, bounds)])

    def objective(vec: np.ndarray) -> float:
        kwargs = {name: float(vec[i]) for i, name in enumerate(var_names)}
        return float(f_expr(**kwargs))

    result = sci_opt.minimize(
        objective, x0, method="L-BFGS-B", bounds=bounds,
        options={"maxiter": limits.max_optimization_iterations})
    if not result.success:
        raise unknown_result(
            f"minimization did not converge: {result.message}")
    # Gradient norm where the method exposes it (L-BFGS-B provides jac).
    grad_norm = None
    if result.get("jac") is not None:
        grad_norm = float(np.linalg.norm(result.jac))
    return {
        "result": {
            "optimum_x": result.x.tolist(),
            "optimum_value": float(result.fun),
            "optimum_kind": "LOCAL optimum; global optimum NOT ESTABLISHED",
        },
        "diagnostics": {
            "converged": True,
            "status_message": str(result.message),
            "iterations": int(result.nit),
            "objective_value": float(result.fun),
            "gradient_norm": grad_norm,
            "nfev": int(result.nfev),
        },
        "provenance": {"engine": "scipy", "method": "L-BFGS-B"},
    }