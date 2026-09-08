"""scicomp registry — the approved operation catalogue (T11.1, T11.2).

The registry is the complete, closed list of scientific operations the
laboratory can execute. Anything not registered cannot be invoked —
there is no generic "run this code" escape hatch (T11.3, T11.33). The
registry exposes a stable manifest (for prompts and audits) and a
content hash so the exact executor surface can be pinned in audit
records (T11.42).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from sciencemath.scicomp import calculus, interpolation, linear_algebra, \
    ode, optimization, parameter_sweep, roots, statistics
from sciencemath.scicomp.schemas import Limits

# Route categories (T11.13) — deterministic routing targets.
CAT_LINEAR_ALGEBRA = "LINEAR_ALGEBRA"
CAT_INTEGRATION = "NUMERICAL_INTEGRATION"
CAT_DERIVATIVE = "DERIVATIVE"
CAT_ROOT_FINDING = "ROOT_FINDING"
CAT_ODE = "ODE"
CAT_OPTIMIZATION = "OPTIMIZATION"
CAT_STATISTICS = "STATISTICS"
CAT_INTERPOLATION = "INTERPOLATION"
CAT_PARAMETER_SWEEP = "PARAMETER_SWEEP"


@dataclass(frozen=True)
class Operation:
    """One approved scientific operation."""

    name: str
    category: str
    description: str
    handler: Callable[[dict, dict, Limits], dict]


def build_registry() -> dict[str, Operation]:
    """The approved operation set. Adding an operation is a code change
    with tests, never runtime state."""
    ops = [
        # linear algebra (T11.2)
        Operation("matrix_multiply", CAT_LINEAR_ALGEBRA,
                  "multiply two matrices", linear_algebra.matmul),
        Operation("determinant", CAT_LINEAR_ALGEBRA,
                  "determinant of a square matrix", linear_algebra.determinant),
        Operation("matrix_inverse", CAT_LINEAR_ALGEBRA,
                  "inverse of a WELL-CONDITIONED square matrix",
                  linear_algebra.inverse),
        Operation("solve_linear_system", CAT_LINEAR_ALGEBRA,
                  "solve A·x = b for a square system",
                  linear_algebra.solve_linear_system),
        Operation("eigen_decompose", CAT_LINEAR_ALGEBRA,
                  "eigenvalues (and optionally eigenvectors) of a square "
                  "matrix", linear_algebra.eigen),
        Operation("vector_or_matrix_norm", CAT_LINEAR_ALGEBRA,
                  "l1/l2/lINF norm of a vector or matrix (or Frobenius)",
                  linear_algebra.norm),
        Operation("matrix_rank", CAT_LINEAR_ALGEBRA,
                  "numerical rank of a matrix", linear_algebra.rank),
        Operation("least_squares", CAT_LINEAR_ALGEBRA,
                  "minimum-norm least-squares solution of an overdetermined "
                  "system", linear_algebra.least_squares),
        # calculus (T11.2)
        Operation("numerical_derivative", CAT_DERIVATIVE,
                  "first or second derivative of an expression at a point",
                  calculus.derivative),
        Operation("definite_integral", CAT_INTEGRATION,
                  "definite integral of an expression over an interval",
                  calculus.definite_integral),
        Operation("cumulative_integral", CAT_INTEGRATION,
                  "cumulative trapezoidal integral over sampled points",
                  calculus.cumulative_integral),
        # roots (T11.2)
        Operation("bracketed_root", CAT_ROOT_FINDING,
                  "root of an expression inside a sign-changing bracket",
                  roots.bracketed_root),
        Operation("scalar_root", CAT_ROOT_FINDING,
                  "scalar root by iteration, optionally bracketed",
                  roots.scalar_root),
        Operation("system_root", CAT_ROOT_FINDING,
                  "root of a small square nonlinear system",
                  roots.system_root),
        # ODE (T11.2, T11.29)
        Operation("solve_ode", CAT_ODE,
                  "initial-value problem on a bounded interval with "
                  "explicit initial conditions and diagnostics",
                  ode.solve_ode),
        # optimization (T11.2, T11.30)
        Operation("minimize_scalar", CAT_OPTIMIZATION,
                  "bounded scalar minimization", optimization.minimize_scalar),
        Operation("minimize", CAT_OPTIMIZATION,
                  "bounded multivariate minimization (local)",
                  optimization.minimize),
        # statistics (T11.2, T11.28)
        Operation("describe", CAT_STATISTICS,
                  "descriptive statistics of a sample", statistics.describe),
        Operation("confidence_interval_mean", CAT_STATISTICS,
                  "confidence interval for a mean, assumptions stated",
                  statistics.confidence_interval_mean),
        Operation("correlation", CAT_STATISTICS,
                  "pearson or spearman correlation with assumptions",
                  statistics.correlation),
        Operation("linear_regression", CAT_STATISTICS,
                  "simple least-squares regression with diagnostics",
                  statistics.linear_regression),
        Operation("hypothesis_test", CAT_STATISTICS,
                  "t-tests with explicitly declared assumptions",
                  statistics.hypothesis_test),
        Operation("distribution_value", CAT_STATISTICS,
                  "pdf/cdf/pmf/logpdf of a parameterized distribution",
                  statistics.distribution_value),
        # interpolation / fitting (T11.2)
        Operation("linear_interpolate", CAT_INTERPOLATION,
                  "piecewise-linear interpolation within the sample range",
                  interpolation.linear_interpolate),
        Operation("polynomial_interpolate", CAT_INTERPOLATION,
                  "exact polynomial interpolation with degree cap",
                  interpolation.polynomial_interpolate),
        Operation("curve_fit", CAT_INTERPOLATION,
                  "bounded-parameter least-squares curve fit",
                  interpolation.curve_fit),
        # parameter sweeps (T11.2, T11.27)
        Operation("parameter_sweep", CAT_PARAMETER_SWEEP,
                  "bounded Cartesian sweep of an expression over parameter "
                  "grids", parameter_sweep.sweep),
    ]
    return {op.name: op for op in ops}


def manifest(registry: dict[str, Operation]) -> list[dict]:
    """Stable, sorted manifest of the approved operations."""
    return [
        {"name": op.name, "category": op.category,
         "description": op.description}
        for op in sorted(registry.values(), key=lambda o: o.name)
    ]


def registry_hash(registry: dict[str, Operation]) -> str:
    """Content hash of the operation catalogue (T11.42 audit pin)."""
    payload = json.dumps(manifest(registry), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()