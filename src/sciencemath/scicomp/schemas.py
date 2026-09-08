"""scicomp schemas — statuses, errors, resource caps, request validation.

T11 contract for the Scientific Computing Laboratory:

* Every compute request is a structured object::

      {"operation": <registered op name>,
       "inputs":    <op-specific payload>,
       "options":   <op-specific options, all bounded>}

  validated BEFORE execution (T11.4). Malformed or excessive requests are
  rejected with INVALID_INPUT / RESOURCE_LIMIT — never executed partially.

* Every result is a structured envelope (T11.8)::

      {"status": PASS | FAIL | UNKNOWN | INVALID_INPUT | RESOURCE_LIMIT
                 | NUMERICAL_WARNING,
       "operation": ..., "result": ..., "diagnostics": ...,
       "warnings": [...], "provenance": {...}}

  Warnings are never collapsed into PASS silently (T11.8).

* Every operation has explicit hard caps (T11.6). Exceeding a cap fails
  closed with RESOURCE_LIMIT.

This module owns the envelope shape, the error type, the resource limits,
and structural (op-independent) request validation. Op-specific input
validation lives with each operation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Statuses (T11.8)
# ---------------------------------------------------------------------------

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_INVALID_INPUT = "INVALID_INPUT"
STATUS_RESOURCE_LIMIT = "RESOURCE_LIMIT"
STATUS_NUMERICAL_WARNING = "NUMERICAL_WARNING"

ALL_STATUSES = (STATUS_PASS, STATUS_FAIL, STATUS_UNKNOWN,
                STATUS_INVALID_INPUT, STATUS_RESOURCE_LIMIT,
                STATUS_NUMERICAL_WARNING)

# Statuses that mean "no trustworthy number came out of this call".
UNTRUSTED_STATUSES = (STATUS_FAIL, STATUS_UNKNOWN, STATUS_INVALID_INPUT,
                      STATUS_RESOURCE_LIMIT, STATUS_NUMERICAL_WARNING)


class ScicompError(Exception):
    """Deterministic scicomp failure with a stable machine-readable code.

    Codes map 1:1 onto envelope statuses: raising ScicompError with code
    INVALID_INPUT produces a status-INVALID_INPUT envelope. The executor
    converts every ScicompError into a result — a rejected call is a
    *result*, not a crash.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def invalid_input(message: str) -> ScicompError:
    return ScicompError("INVALID_INPUT", message)


def resource_limit(message: str) -> ScicompError:
    return ScicompError("RESOURCE_LIMIT", message)


def numerical_failure(message: str) -> ScicompError:
    return ScicompError("FAIL", message)


def unknown_result(message: str) -> ScicompError:
    return ScicompError("UNKNOWN", message)


# ---------------------------------------------------------------------------
# Resource limits (T11.6) — hard caps, fail closed
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Limits:
    """Hard caps applied to every scicomp call (T11.6, T11.7)."""

    wall_clock_s: float = 10.0            # per-operation timeout (CPU)
    max_matrix_side: int = 128            # square matrix dimension cap
    max_matrix_elements: int = 128 * 128  # total elements cap
    max_vector_dim: int = 4096            # vector length cap
    max_ode_state_dim: int = 16           # ODE state dimension cap
    max_ode_span: float = 1e4             # |t_end - t_start| cap
    max_ode_evals: int = 200_000          # solver RHS evaluation budget
    max_sweep_combinations: int = 10_000  # total Cartesian combinations cap
    max_sweep_values_per_dim: int = 64    # values per sweep dimension cap
    max_sweep_dims: int = 4               # sweep dimension count cap
    max_optimization_iterations: int = 500
    max_fit_params: int = 8               # curve-fit parameter count cap
    max_fit_points: int = 2000            # curve-fit data point cap
    max_output_rows: int = 1000           # serialized output rows cap
    max_output_bytes: int = 1_000_000     # serialized output bytes cap
    max_expression_length: int = 2000     # expression string cap
    max_polynomial_degree: int = 10       # interpolation degree cap
    max_stats_points: int = 10_000        # sample size cap

    def clamp_options(self, options: dict) -> dict:
        """Reject (never silently relax) user options that exceed caps."""
        if not isinstance(options, dict):
            raise invalid_input("'options' must be an object")
        out = dict(options)
        if "rtol" in out:
            rtol = _finite_float(out["rtol"], "rtol")
            if rtol < 1e-15 or rtol > 1e-2:
                raise invalid_input("'rtol' must be in [1e-15, 1e-2]")
        if "atol" in out:
            atol = _finite_float(out["atol"], "atol")
            if atol < 1e-300 or atol > 1e-2:
                raise invalid_input("'atol' must be in [1e-300, 1e-2]")
        if "max_steps" in out and (
                isinstance(out["max_steps"], bool)
                or not isinstance(out["max_steps"], int)
                or out["max_steps"] < 1
                or out["max_steps"] > 1_000_000):
            raise invalid_input("'max_steps' must be an integer in [1, 1e6]")
        return out


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_input(f"'{name}' must be a number")
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        raise invalid_input(f"'{name}' must be finite")
    return v


# ---------------------------------------------------------------------------
# Result envelope (T11.8)
# ---------------------------------------------------------------------------

def make_envelope(operation: str, status: str, result: object,
                  diagnostics: dict | None = None,
                  warnings: list[str] | None = None,
                  provenance: dict | None = None,
                  cross_check: dict | None = None) -> dict:
    """Build the canonical result envelope. All fields JSON-safe."""
    if status not in ALL_STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return {
        "status": status,
        "operation": operation,
        "result": result,
        "diagnostics": diagnostics or {},
        "warnings": list(warnings or []),
        "provenance": provenance or {},
        "cross_check": cross_check,       # T11.10: AGREE/DISAGREE/NOT_AVAILABLE
    }


# ---------------------------------------------------------------------------
# Structural request validation (T11.4)
# ---------------------------------------------------------------------------

@dataclass
class ComputeRequest:
    """A validated, op-independent compute request."""

    operation: str
    inputs: dict
    options: dict
    raw: dict = field(default_factory=dict, repr=False)


def validate_request(payload: object, limits: Limits) -> ComputeRequest:
    """Validate the structural shape of a compute request.

    Rejects unknown operations, non-object payloads, oversized serialized
    requests, and options exceeding hard caps. Op-specific input validation
    is the operation's own responsibility.
    """
    if not isinstance(payload, dict):
        raise invalid_input("compute request must be a JSON object")
    try:
        encoded = json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise invalid_input(f"compute request is not JSON-safe: {e}")
    if len(encoded) > limits.max_output_bytes:
        raise resource_limit(
            f"compute request exceeds {limits.max_output_bytes} bytes")
    operation = payload.get("operation")
    if not isinstance(operation, str) or not operation.strip():
        raise invalid_input("'operation' must be a non-empty string")
    inputs = payload.get("inputs", {})
    options = payload.get("options", {})
    if not isinstance(inputs, dict):
        raise invalid_input("'inputs' must be an object")
    options = limits.clamp_options(options)
    return ComputeRequest(operation=operation, inputs=inputs,
                          options=options, raw=payload)


# ---------------------------------------------------------------------------
# Shared numeric input helpers (NaN/Inf guard — T11.23)
# ---------------------------------------------------------------------------

_MISSING = object()


def finite_number(value: object, name: str,
                  default: object = _MISSING) -> float:
    """Require a finite JSON number; reject bool, NaN, Inf, strings."""
    if value is _MISSING:
        raise invalid_input(f"missing required number '{name}'")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_input(f"'{name}' must be a number")
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        raise invalid_input(f"'{name}' must be finite")
    return v


def finite_list(value: object, name: str, max_len: int,
                default: object = _MISSING) -> list[float]:
    """Require a list of finite JSON numbers, bounded in length.

    Optional lists pass ``default=None``: a missing or null value then
    yields ``[]``. Required lists (default sentinel) reject missing values.
    """
    if value is _MISSING:
        if default is _MISSING:
            raise invalid_input(f"missing required list '{name}'")
        value = default
    if value is None and default is None:
        return []
    if not isinstance(value, list):
        raise invalid_input(f"'{name}' must be a list of numbers")
    if len(value) > max_len:
        raise resource_limit(
            f"'{name}' has {len(value)} entries (max {max_len})")
    out = []
    for i, v in enumerate(value):
        try:
            out.append(finite_number(v, f"{name}[{i}]"))
        except ScicompError as e:
            raise invalid_input(f"{name}[{i}]: {e.message}")
    return out


def finite_matrix(value: object, name: str, limits: Limits,
                  square: bool = True) -> list[list[float]]:
    """Require a bounded, rectangular (optionally square) numeric matrix."""
    if not isinstance(value, list) or not value or not all(
            isinstance(row, list) for row in value):
        raise invalid_input(f"'{name}' must be a list of lists")
    n_rows = len(value)
    if n_rows > limits.max_matrix_side:
        raise resource_limit(
            f"'{name}' has {n_rows} rows (max {limits.max_matrix_side})")
    widths = {len(row) for row in value}
    if 0 in widths or len(widths) != 1:
        raise invalid_input(f"'{name}' rows must be non-empty and equal length")
    if square and widths != {n_rows}:
        raise invalid_input(f"'{name}' must be square")
    n_cols = widths.pop()
    if n_cols > limits.max_matrix_side:
        raise resource_limit(
            f"'{name}' has {n_cols} columns (max {limits.max_matrix_side})")
    if n_rows * n_cols > limits.max_matrix_elements:
        raise resource_limit(
            f"'{name}' has {n_rows * n_cols} elements "
            f"(max {limits.max_matrix_elements})")
    try:
        return [[finite_number(v, f"{name}[{i}][{j}]")
                 for j, v in enumerate(row)] for i, row in enumerate(value)]
    except ScicompError as e:
        raise invalid_input(e.message)