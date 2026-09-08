"""scicomp diagnostics — numerical quality reporting (T11.9, T11.12).

Every scicomp result must expose the diagnostics a scientist needs to
judge it: residuals, condition numbers, error estimates, convergence
flags, solver evaluation counts. This module builds those diagnostic
dictionaries in one canonical JSON-safe shape, and separates (T11.12):

* numerical approximation error   — solver-reported, e.g. quad's error
* model uncertainty               — NEVER filled by scicomp (stays unknown)
* scientific/evidence uncertainty — the caller's domain, not computed

Diagnostic helpers never raise for messy numerics: they sanitize
(non-finite -> omitted with a warning note) so a borderline run still
carries whatever quality signal survived.
"""
from __future__ import annotations

import numpy as np


def _safe(value: object) -> object:
    """JSON-safe a scalar; NaN/inf become None (with caller-supplied note)."""
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return v if np.isfinite(v) else None
    return value


def condition_number(matrix: np.ndarray) -> dict:
    """Condition number diagnostics for a square matrix (T11.31)."""
    try:
        cond = float(np.linalg.cond(matrix))
    except Exception:  # noqa: BLE001 — diagnostic must not fail the op
        return {"condition_number": None,
                "conditioning": "NOT_AVAILABLE"}
    return {
        "condition_number": cond,
        "conditioning": _conditioning_label(cond),
    }


def _conditioning_label(cond: float) -> str:
    if cond is None or cond != cond or cond == float("inf"):
        return "SINGULAR_OR_NOT_AVAILABLE"
    if cond > 1e12:
        return "ILL_CONDITIONED"
    if cond > 1e8:
        return "POORLY_CONDITIONED"
    return "WELL_CONDITIONED"


def residual_norm(a: np.ndarray, x: np.ndarray, b: np.ndarray) -> dict:
    """Relative residual of a solved linear system (T11.9)."""
    try:
        r = float(np.linalg.norm(a @ x - b))
        denom = float(np.linalg.norm(b)) or 1.0
        return {"residual_norm": r, "relative_residual": r / denom}
    except Exception:  # noqa: BLE001
        return {"residual_norm": None}


def integration(residual: float, error_estimate: float,
                converged: bool) -> dict:
    """Integration diagnostics: estimated error + convergence (T11.9)."""
    return {
        "estimated_error": _safe(error_estimate),
        "last_step_estimate": _safe(residual),
        "converged": bool(converged),
    }


def ode(success: bool, message: str, nfev: int, njev: int,
        njev_label: str = "njev") -> dict:
    """ODE solver diagnostics: success, termination reason, eval counts
    (T11.9, T11.29). Never returns partial solver state as success."""
    return {
        "solver_success": bool(success),
        "termination_reason": str(message),
        "nfev": int(nfev),
        njev_label: int(njev),
    }


def optimization(converged: bool, status_message: str, iterations: int,
                 objective: float, gradient_norm: float | None = None) -> dict:
    """Optimization diagnostics: convergence flag, objective, iterations
    (T11.9, T11.30)."""
    return {
        "converged": bool(converged),
        "status_message": str(status_message),
        "iterations": int(iterations),
        "objective_value": _safe(objective),
        "gradient_norm": _safe(gradient_norm) if gradient_norm is not None else None,
    }


def curve_fit(residual_norm_value: float, covariance: np.ndarray | None,
              pcov_diagonal: list[float] | None = None) -> dict:
    """Curve-fit diagnostics: residual + parameter uncertainty (T11.9)."""
    out: dict = {"residual_norm": _safe(residual_norm_value)}
    if covariance is not None:
        with np.errstate(invalid="ignore"):
            diag = np.sqrt(np.abs(np.diag(covariance)))
        out["parameter_std_errors"] = [_safe(v) for v in diag]
        out["covariance_valid"] = bool(np.all(np.isfinite(covariance)))
    else:
        out["covariance_valid"] = False
        out["parameter_std_errors"] = None
    return out


def stats(n: int, assumptions: list[str]) -> dict:
    """Statistical diagnostics: sample size + explicit assumptions
    (T11.28). Every statistical result must carry these."""
    return {
        "sample_size": int(n),
        "assumptions": list(assumptions),
    }


def note_nonfinite(warnings: list[str], where: str) -> list[str]:
    """Append a warning if callers had to omit a non-finite diagnostic."""
    warnings.append(f"non-finite diagnostic omitted in {where}")
    return warnings