"""scicomp linear_algebra — bounded dense linear algebra operations.

Operations (T11.2): matrix multiply, determinant, inverse
(well-conditioned only), linear-system solve, eigenvalues/eigenvectors,
norms, rank, least squares. All run on CPU through numpy/scipy with
dimension caps (T11.6) and conditioning diagnostics (T11.9, T11.31).

Conditioning policy (T11.31): systems are SOLVED, never inverted; the
inverse operation refuses matrices above the ill-conditioning threshold
instead of returning garbage that looks authoritative; every solve
reports condition number and residual.
"""
from __future__ import annotations

import numpy as np
import scipy.linalg as sla

from sciencemath.scicomp import diagnostics
from sciencemath.scicomp.schemas import (Limits, ScicompError, invalid_input,
                                         numerical_failure, resource_limit)

ILL_CONDITIONED_THRESHOLD = 1e12


def _as_array(matrix: list[list[float]], name: str) -> np.ndarray:
    return np.asarray(matrix, dtype=float)


def _complex_pairs(values: np.ndarray) -> list[list[float]]:
    """JSON-safe complex eigenvalues as [re, im] pairs."""
    return [[float(np.real(v)), float(np.imag(v))] for v in values]


# --- matrix multiplication -------------------------------------------------

def matmul(inputs: dict, options: dict, limits: Limits) -> dict:
    a = _as_array(inputs.get("a") or [], "a")
    b = _as_array(inputs.get("b") or [], "b")
    if a.ndim != 2 or b.ndim != 2:
        raise invalid_input("'a' and 'b' must be 2-D matrices")
    if a.shape[1] != b.shape[0]:
        raise invalid_input(
            f"dimension mismatch: a is {a.shape}, b is {b.shape} "
            f"({a.shape[1]} != {b.shape[0]})")
    if max(a.size, b.size) > limits.max_matrix_elements:
        raise resource_limit("matrix exceeds element cap")
    if max(a.shape) > limits.max_matrix_side or max(b.shape) > limits.max_matrix_side:
        raise resource_limit("matrix exceeds side cap")
    product = a @ b
    return {
        "result": {"matrix": product.tolist()},
        "diagnostics": {"shape": list(product.shape)},
        "provenance": {"engine": "numpy", "method": "matmul"},
    }


# --- determinant -----------------------------------------------------------

def determinant(inputs: dict, options: dict, limits: Limits) -> dict:
    m = _as_array(inputs.get("matrix") or [], "matrix")
    if m.ndim != 2 or m.shape[0] != m.shape[1]:
        raise invalid_input("'matrix' must be square")
    if m.shape[0] > limits.max_matrix_side:
        raise resource_limit("matrix exceeds side cap")
    det = float(np.linalg.det(m))
    diag = diagnostics.condition_number(m)
    warnings = []
    status = "PASS"
    if diag["condition_number"] is not None and \
            diag["condition_number"] > ILL_CONDITIONED_THRESHOLD:
        warnings.append("matrix is ill-conditioned; determinant may be "
                        "unreliable")
        status = "NUMERICAL_WARNING"
    return {
        "result": {"determinant": det},
        "diagnostics": diag,
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "numpy", "method": "lu-det"},
    }


# --- inverse (well-conditioned only, T11.31) --------------------------------

def inverse(inputs: dict, options: dict, limits: Limits) -> dict:
    m = _as_array(inputs.get("matrix") or [], "matrix")
    if m.ndim != 2 or m.shape[0] != m.shape[1]:
        raise invalid_input("'matrix' must be square")
    if m.shape[0] > limits.max_matrix_side:
        raise resource_limit("matrix exceeds side cap")
    diag = diagnostics.condition_number(m)
    cond = diag["condition_number"]
    if cond is None or cond == float("inf") \
            or float(np.linalg.det(m)) == 0.0:
        raise numerical_failure("matrix is singular; no inverse exists")
    if cond > ILL_CONDITIONED_THRESHOLD:
        # Fail closed: an inverse of an ill-conditioned matrix looks
        # authoritative while being numerically meaningless (T11.31).
        raise ScicompError(
            "FAIL", f"matrix is ill-conditioned (condition number "
                    f"{cond:.3e} > {ILL_CONDITIONED_THRESHOLD:.0e}); "
                    "refusing to invert — solve a linear system instead")
    try:
        inv = np.linalg.inv(m)
    except np.linalg.LinAlgError as e:
        raise numerical_failure(f"inversion failed: {e}")
    # Verify: M·M⁻¹ ≈ I
    identity_err = float(np.max(np.abs(m @ inv - np.eye(m.shape[0]))))
    warnings, status = [], "PASS"
    if identity_err > 1e-8 * max(1.0, cond):
        warnings.append(f"inverse verification error {identity_err:.3e}")
        status = "NUMERICAL_WARNING"
    return {
        "result": {"inverse": inv.tolist()},
        "diagnostics": {**diag, "verification_error": identity_err},
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "numpy", "method": "inv"},
    }


# --- linear system solve -----------------------------------------------------

def solve_linear_system(inputs: dict, options: dict, limits: Limits) -> dict:
    a = _as_array(inputs.get("matrix") or [], "matrix")
    b = np.asarray(inputs.get("b") or [], dtype=float)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise invalid_input("'matrix' must be square")
    if a.shape[0] > limits.max_matrix_side:
        raise resource_limit("matrix exceeds side cap")
    if b.ndim != 1 or b.shape[0] != a.shape[0]:
        raise invalid_input(
            f"'b' must be a vector of length {a.shape[0]}")
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise invalid_input("matrix and b must be finite")
    diag_cond = diagnostics.condition_number(a)
    cond = diag_cond["condition_number"]
    if cond is not None and cond == float("inf"):
        raise numerical_failure("matrix is singular; system has no unique "
                                "solution")
    try:
        x = np.linalg.solve(a, b)
    except np.linalg.LinAlgError as e:
        raise numerical_failure(f"solve failed: {e}")
    resid = diagnostics.residual_norm(a, x, b)
    warnings, status = [], "PASS"
    if cond is not None and cond > ILL_CONDITIONED_THRESHOLD:
        warnings.append(
            f"matrix is ill-conditioned (condition number {cond:.3e}); "
            "solution may be inaccurate")
        status = "NUMERICAL_WARNING"
    elif resid["relative_residual"] is not None and \
            resid["relative_residual"] > 1e-6:
        warnings.append("residual above 1e-6; solution may be inaccurate")
        status = "NUMERICAL_WARNING"
    cross = _verify_by_substitution(a, x, b, options)
    return {
        "result": {"solution": x.tolist()},
        "diagnostics": {**diag_cond, **resid},
        "warnings": warnings,
        "status": status,
        "cross_check": cross,
        "provenance": {"engine": "numpy", "method": "lu-solve"},
    }


def _verify_by_substitution(a: np.ndarray, x: np.ndarray, b: np.ndarray,
                            options: dict) -> dict:
    from sciencemath.scicomp import verifier
    rtol = options.get("rtol", 1e-6)
    atol = options.get("atol", 1e-9)
    return verifier.linear_residual_check(a, x, b, rtol, atol)


# --- eigenvalues / eigenvectors ----------------------------------------------

def eigen(inputs: dict, options: dict, limits: Limits) -> dict:
    m = _as_array(inputs.get("matrix") or [], "matrix")
    if m.ndim != 2 or m.shape[0] != m.shape[1]:
        raise invalid_input("'matrix' must be square")
    if m.shape[0] > limits.max_matrix_side:
        raise resource_limit("matrix exceeds side cap")
    want_vectors = bool(inputs.get("eigenvectors", True))
    try:
        if want_vectors:
            values, vectors = np.linalg.eig(m)
        else:
            values = np.linalg.eigvals(m)
            vectors = None
    except np.linalg.LinAlgError as e:
        raise numerical_failure(f"eigen decomposition failed: {e}")
    result: dict = {"eigenvalues": _complex_pairs(values)}
    if vectors is not None:
        result["eigenvectors"] = [_complex_pairs(vectors[:, i])
                                  for i in range(vectors.shape[1])]
    diag = diagnostics.condition_number(m)
    warnings = []
    status = "PASS"
    if any(abs(v[1]) > 1e-12 for v in result["eigenvalues"]):
        warnings.append("matrix has complex eigenvalues; returned as "
                        "[real, imaginary] pairs")
    return {
        "result": result,
        "diagnostics": diag,
        "warnings": warnings,
        "status": status,
        "provenance": {"engine": "numpy", "method": "eig"},
    }


# --- norms -------------------------------------------------------------------

def norm(inputs: dict, options: dict, limits: Limits) -> dict:
    kind = inputs.get("norm", "l2")
    if kind not in ("l1", "l2", "lINF", "frobenius"):
        raise invalid_input("'norm' must be one of l1, l2, lINF, frobenius")
    vec = inputs.get("vector")
    mat = inputs.get("matrix")
    if (vec is None) == (mat is None):
        raise invalid_input("provide exactly one of 'vector' or 'matrix'")
    if vec is not None:
        v = np.asarray(vec, dtype=float)
        if v.ndim != 1 or v.size > limits.max_vector_dim:
            raise invalid_input(
                f"'vector' must be 1-D with at most {limits.max_vector_dim} "
                "entries")
        order = {"l1": 1, "l2": 2, "lINF": np.inf}[kind]
        value = float(np.linalg.norm(v, ord=order))
        target = "vector"
    else:
        m = _as_array(mat, "matrix")
        if m.ndim != 2 or max(m.shape) > limits.max_matrix_side:
            raise invalid_input("'matrix' must be 2-D within side cap")
        if kind == "frobenius":
            value = float(np.linalg.norm(m, ord="fro"))
        else:
            order = {"l1": 1, "l2": 2, "lINF": np.inf}[kind]
            value = float(np.linalg.norm(m, ord=order))
        target = "matrix"
    return {
        "result": {"norm": value, "norm_kind": kind, "target": target},
        "provenance": {"engine": "numpy", "method": "norm"},
    }


# --- rank ----------------------------------------------------------------------

def rank(inputs: dict, options: dict, limits: Limits) -> dict:
    m = _as_array(inputs.get("matrix") or [], "matrix")
    if m.ndim != 2 or max(m.shape) > limits.max_matrix_side:
        raise invalid_input("'matrix' must be 2-D within side cap")
    tol = options.get("rtol", 1e-10)
    r = int(np.linalg.matrix_rank(m, tol=tol))
    return {
        "result": {"rank": r, "shape": list(m.shape)},
        "diagnostics": diagnostics.condition_number(m),
        "provenance": {"engine": "numpy", "method": "svd-rank"},
    }


# --- least squares ---------------------------------------------------------------

def least_squares(inputs: dict, options: dict, limits: Limits) -> dict:
    a = _as_array(inputs.get("matrix") or [], "matrix")
    b = np.asarray(inputs.get("b") or [], dtype=float)
    if a.ndim != 2 or max(a.shape) > limits.max_matrix_side:
        raise invalid_input("'matrix' must be 2-D within side cap")
    if b.ndim != 1 or b.shape[0] != a.shape[0]:
        raise invalid_input(f"'b' must be a vector of length {a.shape[0]}")
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise invalid_input("matrix and b must be finite")
    x, residuals, rank_value, singular_values = np.linalg.lstsq(
        a, b, rcond=options.get("rtol", None))
    predicted = a @ x
    resid_norm = float(np.linalg.norm(b - predicted))
    warnings = []
    if rank_value < min(a.shape):
        warnings.append(
            f"matrix rank {rank_value} < {min(a.shape)}: solution is not "
            "unique (minimum-norm solution returned)")
    elif len(singular_values) and float(singular_values[-1]) <= 0.0:
        warnings.append("singular matrix: least-squares solution may be "
                        "unstable")
    return {
        "result": {"solution": x.tolist(),
                   "residual_norm": resid_norm,
                   "rank": int(rank_value)},
        "diagnostics": {"residual_norm": resid_norm,
                        "rank": int(rank_value)},
        "warnings": warnings,
        "status": "NUMERICAL_WARNING" if warnings else "PASS",
        "provenance": {"engine": "numpy", "method": "lstsq"},
    }