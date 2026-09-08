"""scicomp calculus — numerical differentiation and definite integration.

Operations (T11.2): numerical derivative, definite integral, cumulative
integral over sampled points. All integrands/expressions go through the
sandboxed expression language; integration runs scipy.quad on CPU with
error estimates (T11.9), divergence and discontinuity detection
(T11.23), and an analytical cross-check where a cheap closed form exists
(T11.10). Unit semantics are declared explicitly (T11.11): integrating
velocity over time yields distance — the caller must declare the
integration variable's unit and the integrand's unit so the output unit
can be composed and checked.
"""
from __future__ import annotations

import numpy as np
from scipy import integrate as sci_integrate

from sciencemath.scicomp import diagnostics, sandbox
from sciencemath.scicomp.schemas import (Limits, ScicompError, finite_list,
                                         finite_number, invalid_input,
                                         resource_limit)
from sciencemath.tools.unit_converter import parse_unit

MAX_QUAD_SUBDIVISIONS = 200


# --- numerical derivative -----------------------------------------------------

def derivative(inputs: dict, options: dict, limits: Limits) -> dict:
    expr = sandbox.compile_expression(inputs.get("expression") or "",
                                      ["x"])
    at = finite_number(inputs.get("at"), "at")
    order = inputs.get("order", 1)
    if order not in (1, 2):
        raise invalid_input("'order' must be 1 or 2")
    step = options.get("step", None)
    step = finite_number(step, "step") if step is not None else 1e-5
    if step <= 0 or step > 1.0:
        raise invalid_input("'step' must be in (0, 1]")

    # Central differences with two step sizes -> Richardson-style error
    # estimate (T11.9).
    if order == 1:
        def d(h: float) -> float:
            return float((expr(x=at + h) - expr(x=at - h)) / (2 * h))
        value = d(step)
        finer = d(step / 2)
    else:
        def d2(h: float) -> float:
            return float((expr(x=at + h) - 2 * expr(x=at)
                          + expr(x=at - h)) / h ** 2)
        value = d2(step)
        finer = d2(step / 2)
    error_estimate = abs(finer - value)  # |d(h) - d(h/2)| bounds the error
    warnings, status = [], "PASS"
    if error_estimate > 1e-3 * max(1.0, abs(value)):
        warnings.append(
            f"derivative estimate unstable (step-halving delta "
            f"{error_estimate:.3e}); result may be inaccurate near a "
            "discontinuity or noise-dominated region")
        status = "NUMERICAL_WARNING"
    return {
        "result": {"derivative": float(finer), "at": at, "order": order},
        "diagnostics": {"estimated_error": error_estimate,
                        "step_used": step / 2},
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "central-difference", "method":
                       f"central-diff-order-{order}"},
    }


# --- definite integral -----------------------------------------------------------

def definite_integral(inputs: dict, options: dict, limits: Limits) -> dict:
    expr = sandbox.compile_expression(inputs.get("expression") or "",
                                      ["x"])
    lower = finite_number(inputs.get("lower"), "lower")
    upper = finite_number(inputs.get("upper"), "upper")
    if abs(upper - lower) > limits.max_ode_span:
        raise resource_limit(
            f"integration span {abs(upper - lower)} exceeds "
            f"{limits.max_ode_span}")
    rtol = options.get("rtol", 1e-8)
    atol = options.get("atol", 1e-12)

    # full_output=1 suppresses IntegrationWarning and returns a diagnostics
    # dict as the third element (T11.9): divergence and subdivision signals
    # come from here instead of exception text.
    result = sci_integrate.quad(
        lambda x: float(expr(x=x)), lower, upper,
        limit=MAX_QUAD_SUBDIVISIONS, epsabs=atol, epsrel=rtol,
        full_output=1)
    value, error = float(result[0]), float(result[1])
    info = result[2] if len(result) > 2 else {}
    message = str(info.get("message", ""))

    warnings, status = [], "PASS"
    if "divergent" in message.lower():
        raise ScicompError(
            "FAIL", f"integral is divergent or badly behaved: {message}")
    if message:
        warnings.append(f"integration warning: {message}")
        status = "NUMERICAL_WARNING"
    if error > max(atol, rtol * abs(value) if value else atol):
        warnings.append(
            f"estimated integration error {error:.3e} exceeds tolerance")
        status = "NUMERICAL_WARNING"

    # Analytical cross-check where cheap (T11.10): symbolic antiderivative.
    from sciencemath.scicomp import verifier
    analytic = verifier.symbolic_definite_integral(expr, "x", lower, upper)
    verdict = verifier.compare(float(value), analytic, rtol, 1e-6) \
        if analytic is not None else verifier.NOT_AVAILABLE
    cross = verifier.cross_check(verdict, float(value), analytic,
                                 "sympy antiderivative") \
        if analytic is not None else verifier.cross_check(
            verifier.NOT_AVAILABLE, float(value), None, "no closed form")

    # Unit semantics (T11.11): declared integrand unit × variable unit.
    unit_info = _compose_units(inputs)

    return {
        "result": {"integral": float(value), "lower": lower, "upper": upper},
        "diagnostics": {**diagnostics.integration(error, error, True),
                        **unit_info},
        "warnings": warnings,
        "status": status,
        "cross_check": cross,
        "provenance": {"engine": "scipy", "method": "quad"},
    }


def _compose_units(inputs: dict) -> dict:
    """Dimensional composition for integration (T11.11).

    If the caller declares integrand units U_f and integration-variable
    units U_x, the result unit is U_f * U_x. A declared expected unit is
    checked against the composition; an obvious mismatch is rejected.
    """
    integrand_unit = inputs.get("integrand_unit")
    variable_unit = inputs.get("variable_unit")
    expected_unit = inputs.get("expected_unit")
    if integrand_unit is None and variable_unit is None \
            and expected_unit is None:
        return {}
    if integrand_unit is None or variable_unit is None:
        raise invalid_input(
            "declare both 'integrand_unit' and 'variable_unit' (or neither)")
    try:
        f_factor, f_dims, _ = parse_unit(integrand_unit)
        x_factor, x_dims, _ = parse_unit(variable_unit)
        out_dims = tuple(a + b for a, b in zip(f_dims, x_dims))
        out_factor = f_factor * x_factor
    except Exception as e:  # noqa: BLE001 — T4 parse errors map to input
        raise invalid_input(f"unit parse failed: {e}")
    out: dict = {
        "result_unit": _dims_label(out_dims),
        "unit_composition": f"{integrand_unit} * {variable_unit}",
        "unit_dimensionless": all(d == 0 for d in out_dims),
    }
    if expected_unit is not None:
        try:
            e_factor, e_dims, _ = parse_unit(expected_unit)
        except Exception as e:  # noqa: BLE001
            raise invalid_input(f"unit parse failed: {e}")
        if e_dims != out_dims:
            raise invalid_input(
                f"dimension mismatch: integrating {integrand_unit} over "
                f"{variable_unit} yields {_dims_label(out_dims)}, not "
                f"{expected_unit}")
        out["declared_unit_matches"] = True
    return out


# dimension vector order from sciencemath.tools.unit_converter
_DIM_BASE = ["m", "kg", "s", "A", "K", "mol", "cd"]


def _dims_label(dims: tuple) -> str:
    parts = [f"{base}^{d}" if d != 1 else base
             for base, d in zip(_DIM_BASE, dims) if d]
    return " * ".join(parts) if parts else "dimensionless"


# --- cumulative integral ------------------------------------------------------------

def cumulative_integral(inputs: dict, options: dict, limits: Limits) -> dict:
    """Cumulative integral over explicitly sampled points (T11.2 'where
    justified'): trapezoidal running integral of y(x) samples."""
    x = finite_list(inputs.get("x"), "x", limits.max_stats_points)
    y = finite_list(inputs.get("y"), "y", limits.max_stats_points)
    if len(x) != len(y):
        raise invalid_input("'x' and 'y' must have equal length")
    if len(x) < 2:
        raise invalid_input("need at least 2 sample points")
    xv = np.asarray(x)
    if np.any(np.diff(xv) <= 0):
        raise invalid_input("'x' must be strictly increasing")
    cum = sci_integrate.cumulative_trapezoid(
        np.asarray(y), xv, initial=0.0)
    if cum.shape[0] > limits.max_output_rows:
        raise resource_limit("output exceeds row cap")
    return {
        "result": {"cumulative": cum.tolist(), "x": xv.tolist()},
        "diagnostics": {"method": "cumulative_trapezoid",
                        "points": len(x)},
        "provenance": {"engine": "scipy", "method":
                       "cumulative_trapezoid"},
    }