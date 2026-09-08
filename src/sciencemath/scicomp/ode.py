"""scicomp ode — bounded initial-value-problem integration (T11.2, T11.29).

One operation: ``solve_ode`` — an explicit initial-value problem

    dy/dt = f(t, y0, y1, ..., y_{n-1}; parameters)

expressed as sandboxed right-hand-side expressions in variables ``t``,
the state variables ``y0..y{n-1}`` and caller-declared parameter names.

Safety contract (T11.29):
* explicit initial conditions, finite time interval, finite parameter
  values, and a state-dimension cap are all REQUIRED, not defaulted;
* the solver's success flag, termination reason, RHS evaluation count
  and step count are always reported;
* a solver that stalls, exceeds its evaluation budget, or produces a
  non-finite state returns UNKNOWN / RESOURCE_LIMIT / FAIL — partial
  final state is never presented as a successful solution.
"""
from __future__ import annotations

import numpy as np
from scipy import integrate as sci_integrate

from sciencemath.scicomp import sandbox
from sciencemath.scicomp.schemas import (Limits, ScicompError, finite_number,
                                         invalid_input, resource_limit)

MAX_STATE_DIM = 16
MAX_PARAMS = 16


class _ODEFailure(ScicompError):
    """ScicompError carrying solver diagnostics into the envelope."""

    def __init__(self, code: str, message: str, diagnostics: dict):
        super().__init__(code, message)
        self.diagnostics = diagnostics


def solve_ode(inputs: dict, options: dict, limits: Limits) -> dict:
    expressions = inputs.get("equations")
    if not isinstance(expressions, list) or not expressions:
        raise invalid_input("'equations' must be a non-empty list of "
                            "right-hand-side expressions")
    n = len(expressions)
    if n > limits.max_ode_state_dim:
        raise resource_limit(
            f"state dimension {n} exceeds {limits.max_ode_state_dim}")
    initial_state = inputs.get("initial_state")
    if not isinstance(initial_state, list) or len(initial_state) != n:
        raise invalid_input(
            f"'initial_state' must be a list of {n} numbers")
    y0 = np.asarray([finite_number(v, f"initial_state[{i}]")
                     for i, v in enumerate(initial_state)])
    t_start = finite_number(inputs.get("t_start"), "t_start")
    t_end = finite_number(inputs.get("t_end"), "t_end")
    if t_start == t_end:
        raise invalid_input("'t_start' and 't_end' must differ")
    if abs(t_end - t_start) > limits.max_ode_span:
        raise resource_limit(
            f"time span {abs(t_end - t_start)} exceeds "
            f"{limits.max_ode_span}")

    # Parameters: caller-declared names, finite values only. Names t and
    # y0.. are reserved for the independent/state variables.
    params = inputs.get("parameters") or {}
    if not isinstance(params, dict):
        raise invalid_input("'parameters' must be an object")
    if len(params) > MAX_PARAMS:
        raise resource_limit(
            f"parameter count {len(params)} exceeds {MAX_PARAMS}")
    param_values = {}
    for k, v in params.items():
        if not isinstance(k, str) or not k.isidentifier() or k == "t" \
                or (k.startswith("y") and k[1:].isdigit()):
            raise invalid_input(
                f"invalid parameter name {k!r} "
                f"(reserved: t, y0..y{n - 1})")
        param_values[k] = finite_number(v, f"parameters.{k}")

    var_names = ["t", *[f"y{i}" for i in range(n)], *param_values.keys()]
    rhs_funcs = [sandbox.compile_expression(e, var_names)
                 for e in expressions]

    def rhs(t: float, state: np.ndarray) -> np.ndarray:
        kwargs = {"t": float(t),
                  **{f"y{i}": float(state[i]) for i in range(n)},
                  **param_values}
        return np.asarray([float(f(**kwargs)) for f in rhs_funcs])

    rtol = options.get("rtol", 1e-6)
    atol = options.get("atol", 1e-9)
    nfev_cap = limits.max_ode_evals
    eval_counter = {"n": 0}

    def counting_rhs(t: float, state: np.ndarray) -> np.ndarray:
        eval_counter["n"] += 1
        if eval_counter["n"] > nfev_cap:
            raise _BudgetExceeded()
        return rhs(t, state)

    try:
        sol = sci_integrate.solve_ivp(
            counting_rhs, (t_start, t_end), y0, method="RK45",
            rtol=rtol, atol=atol, max_step=abs(t_end - t_start))
    except _BudgetExceeded:
        raise _ODEFailure(
            "RESOURCE_LIMIT",
            f"ODE right-hand-side evaluation budget of {nfev_cap} "
            "exceeded before reaching the final time", {
                "solver_success": False,
                "termination_reason": "EVALUATION_BUDGET_EXCEEDED",
                "nfev": eval_counter["n"],
            })

    diagnostics_out = {
        "solver_success": bool(sol.success),
        "termination_reason": str(sol.message),
        "nfev": eval_counter["n"],
        "nsteps": int(sol.t.shape[0]),
        "njev": int(getattr(sol, "njev", 0)),
    }

    if not sol.success:
        # Fail closed: the partial trajectory is NOT returned as a result.
        raise _ODEFailure("UNKNOWN",
                          f"ODE solver did not reach the final time: "
                          f"{sol.message}",
                          diagnostics_out)
    final = sol.y[:, -1]
    if not np.all(np.isfinite(final)):
        raise _ODEFailure("FAIL",
                          "ODE state became non-finite during integration",
                          diagnostics_out)

    warnings = []
    status = "PASS"
    if eval_counter["n"] >= nfev_cap * 0.9:
        warnings.append("solver used >= 90% of the evaluation budget")
        status = "NUMERICAL_WARNING"
    return {
        "result": {
            "final_state": [float(v) for v in final],
            "final_time": float(sol.t[-1]),
            "t_samples": [float(v) for v in sol.t[:limits.max_output_rows]],
            "y_samples": [
                [float(v) for v in sol.y[i, :limits.max_output_rows]]
                for i in range(n)],
        },
        "diagnostics": diagnostics_out,
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "scipy", "method": "solve_ivp-RK45",
                       "state_dim": n},
    }


class _BudgetExceeded(Exception):
    """Internal: RHS evaluation budget exhausted."""