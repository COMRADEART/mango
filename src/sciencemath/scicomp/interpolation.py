"""scicomp interpolation — interpolation and bounded curve fitting
(T11.2).

* ``linear_interpolate`` — piecewise-linear interpolation over strictly
  increasing samples; outside-range queries are rejected (no silent
  extrapolation).
* ``polynomial_interpolate`` — exact polynomial through n points with a
  hard degree cap (T11.6); requesting a degree at or above the sample
  count is flagged (overfitting, T11.23).
* ``curve_fit`` — bounded-count least-squares fit of a sandboxed model
  expression; reports residual, parameter standard errors and any fit
  warnings (T11.9).
"""
from __future__ import annotations

import numpy as np
from scipy import optimize as sci_opt

from sciencemath.scicomp import diagnostics, sandbox
from sciencemath.scicomp.schemas import (Limits, finite_list,
                                         finite_number, invalid_input,
                                         resource_limit)


# --- linear interpolation -------------------------------------------------------

def linear_interpolate(inputs: dict, options: dict, limits: Limits) -> dict:
    x = finite_list(inputs.get("x"), "x", limits.max_stats_points)
    y = finite_list(inputs.get("y"), "y", limits.max_stats_points)
    if len(x) != len(y):
        raise invalid_input("'x' and 'y' must have equal length")
    if len(x) < 2:
        raise invalid_input("need at least 2 sample points")
    xv = np.asarray(x)
    if np.any(np.diff(xv) <= 0):
        raise invalid_input("'x' must be strictly increasing")
    at = finite_number(inputs.get("at"), "at")
    if at < xv[0] or at > xv[-1]:
        raise invalid_input(
            f"query {at} is outside the sample range "
            f"[{xv[0]}, {xv[-1]}]; extrapolation is not supported")
    value = float(np.interp(at, xv, np.asarray(y)))
    # Local slope as a diagnostic (where the query sits between samples).
    i = int(np.searchsorted(xv, at, side="right") - 1)
    i = min(max(i, 0), len(xv) - 2)
    slope = float((y[i + 1] - y[i]) / (x[i + 1] - x[i]))
    return {
        "result": {"value": value, "at": at},
        "diagnostics": {"local_slope": slope,
                        "segment": [float(x[i]), float(x[i + 1])],
                        "method": "piecewise-linear"},
        "provenance": {"engine": "numpy", "method": "interp"},
    }


# --- polynomial interpolation ------------------------------------------------------

def polynomial_interpolate(inputs: dict, options: dict, limits: Limits) -> dict:
    x = finite_list(inputs.get("x"), "x", limits.max_polynomial_degree + 1)
    y = finite_list(inputs.get("y"), "y", limits.max_polynomial_degree + 1)
    if len(x) != len(y):
        raise invalid_input("'x' and 'y' must have equal length")
    if len(x) < 2:
        raise invalid_input("need at least 2 sample points")
    if len(x) > limits.max_polynomial_degree + 1:
        raise resource_limit(
            f"polynomial interpolation supports at most "
            f"{limits.max_polynomial_degree + 1} points")
    xv = np.asarray(x)
    if np.any(np.diff(xv) <= 0):
        raise invalid_input("'x' must be strictly increasing")
    at = finite_number(inputs.get("at"), "at")
    if at < xv[0] or at > xv[-1]:
        raise invalid_input(
            f"query {at} is outside the sample range "
            f"[{xv[0]}, {xv[-1]}]; extrapolation is not supported")
    coeffs = np.polyfit(xv, np.asarray(y), deg=len(x) - 1)
    value = float(np.polyval(coeffs, at))
    warnings, status = [], "PASS"
    if len(x) == limits.max_polynomial_degree + 1:
        warnings.append(
            f"degree {len(x) - 1} polynomial is at the cap; high-degree "
            "interpolation can oscillate (Runge phenomenon) — treat with "
            "caution")
        status = "NUMERICAL_WARNING"
    return {
        "result": {"value": value, "at": at, "degree": len(x) - 1,
                   "coefficients": [float(c) for c in coeffs]},
        "diagnostics": {"method": "exact-polynomial",
                        "points": len(x)},
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "numpy", "method": "polyfit-polyval"},
    }


# --- curve fitting -------------------------------------------------------------------

def curve_fit(inputs: dict, options: dict, limits: Limits) -> dict:
    """Fit a sandboxed model y = f(x; p0, p1, ...) to (x, y) samples."""
    model = inputs.get("model")
    if not isinstance(model, str):
        raise invalid_input("'model' must be a model expression string")
    x = finite_list(inputs.get("x"), "x", limits.max_fit_points)
    y = finite_list(inputs.get("y"), "y", limits.max_fit_points)
    if len(x) != len(y):
        raise invalid_input("'x' and 'y' must have equal length")
    if len(x) < 2:
        raise invalid_input("need at least 2 data points")
    xv = np.asarray(x)
    yv = np.asarray(y)
    param_names_raw = inputs.get("parameters")
    if not isinstance(param_names_raw, list) or not param_names_raw:
        raise invalid_input("'parameters' must be a list of parameter "
                            "names")
    p_names = []
    for p in param_names_raw:
        if not isinstance(p, str) or not p.isidentifier() or p == "x":
            raise invalid_input(f"invalid parameter name {p!r} "
                                "(x is reserved)")
        p_names.append(p)
    if len(p_names) > limits.max_fit_params:
        raise resource_limit(
            f"parameter count {len(p_names)} exceeds "
            f"{limits.max_fit_params}")
    if len(x) <= len(p_names):
        # Overfitting guard (T11.23): more parameters than data points.
        raise invalid_input(
            f"{len(p_names)} parameters for {len(x)} data points: the fit "
            "is underdetermined (overfitting)")

    model_fn = sandbox.compile_expression(model, ["x", *p_names])
    initial = inputs.get("initial_guess") or [1.0] * len(p_names)
    p0_list = finite_list(initial, "initial_guess", limits.max_fit_params)
    if len(p0_list) != len(p_names):
        raise invalid_input(
            f"'initial_guess' must have {len(p_names)} entries")

    def residual(p_values, xv, yv):
        kwargs = {name: float(p_values[i])
                  for i, name in enumerate(p_names)}
        predicted = model_fn(x=xv, **kwargs)
        return np.asarray(predicted, dtype=float) - yv

    try:
        popt, pcov = sci_opt.curve_fit(
            lambda x_data, *p: np.asarray(
                model_fn(x=x_data, **{n: v for n, v in
                                      zip(p_names, p)}), dtype=float),
            xv, yv, p0=np.asarray(p0_list), maxfev=10_000)
    except (RuntimeError, ValueError, TypeError,
            sci_opt.OptimizeWarning) as e:
        raise invalid_input(f"curve fit failed: {e}")
    if not np.all(np.isfinite(pcov)):
        raise invalid_input(
            "covariance could not be estimated (fit is degenerate or "
            "parameters are not identifiable)")
    fitted = np.asarray(model_fn(x=xv, **{n: v for n, v in
                                          zip(p_names, popt)}),
                        dtype=float)
    resid = float(np.sqrt(np.mean((fitted - yv) ** 2)))
    return {
        "result": {"parameters": {n: float(v)
                                  for n, v in zip(p_names, popt)},
                   "rmse": resid},
        "diagnostics": diagnostics.curve_fit(resid, pcov),
        "provenance": {"engine": "scipy", "method": "curve_fit"},
    }