"""scicomp executor — bounded, deterministic dispatch (T11.6, T11.7, T11.8).

The executor is the ONLY entry point into the laboratory. It:

1. structurally validates the request (T11.4) — unknown operations,
   malformed payloads, oversized requests never reach a handler;
2. looks up the operation in the approved registry (T11.3) — there is no
   way to execute anything else;
3. runs the handler on CPU inside a wall-clock timeout (T11.6, T11.7);
4. converts every failure mode into a structured envelope — INVALID_INPUT,
   RESOURCE_LIMIT, FAIL, UNKNOWN — so a rejected call is a *result*,
   never a crash and never a silently collapsed warning (T11.8);
5. guarantees JSON-safe, size-capped outputs (T11.6 output row/byte caps).

Timing/provenance metadata (T11.15, T11.39) is recorded in the envelope:
operation latency is measured, GPU is never touched (CPU-only policy).
"""
from __future__ import annotations

import json
import time

from sciencemath.scicomp.registry import build_registry
from sciencemath.scicomp.schemas import (Limits, ScicompError,
                                         STATUS_INVALID_INPUT,
                                         STATUS_NUMERICAL_WARNING,
                                         STATUS_PASS,
                                         STATUS_RESOURCE_LIMIT, make_envelope,
                                         validate_request)
from sciencemath.scicomp.schemas import STATUS_FAIL, STATUS_UNKNOWN
from sciencemath.tools.base import ToolError, ensure_json_safe, \
    run_with_timeout

_DEFAULT_LIMITS = Limits()
_registry = build_registry()


def limits() -> Limits:
    """The active resource caps."""
    return _DEFAULT_LIMITS


def operations() -> list[str]:
    """Registered operation names."""
    return sorted(_registry)


def registry_sha256() -> str:
    from sciencemath.scicomp import registry
    return registry.registry_hash(_registry)


def execute(payload: object,
            limits_config: Limits | None = None) -> dict:
    """Execute one structured compute request; returns the envelope.

    Never raises: every path returns a well-formed envelope with a
    status. CPU-only; wall-clock bounded; output size capped.
    """
    active = limits_config or _DEFAULT_LIMITS
    start = time.perf_counter()
    try:
        request = validate_request(payload, active)
        op = _registry.get(request.operation)
        if op is None:
            raise ScicompError(
                STATUS_INVALID_INPUT,
                f"unknown operation {request.operation!r}; approved "
                f"operations: {', '.join(sorted(_registry))}")
        # Wall-clock bound in a worker thread (T11.6). The handler itself
        # enforces its finer per-op caps; this is the hard outer bound.
        outcome = run_with_timeout(
            lambda: op.handler(request.inputs, request.options, active),
            timeout_s=active.wall_clock_s,
            description=f"scicomp:{op.name}")
        envelope = _coerce_envelope(op.name, outcome)
    except ScicompError as e:
        envelope = make_envelope(
            operation=_op_name_safe(payload),
            status=e.code if e.code in ("FAIL", "UNKNOWN",
                                        "INVALID_INPUT",
                                        "RESOURCE_LIMIT") else STATUS_FAIL,
            result=None,
            diagnostics=getattr(e, "diagnostics", {}),
            warnings=[e.message],
        )
    except ToolError as e:
        envelope = make_envelope(
            operation=_op_name_safe(payload),
            status=("RESOURCE_LIMIT" if e.code == "TIMEOUT"
                    else STATUS_INVALID_INPUT),
            result=None,
            warnings=[f"{e.code}: {e.message}"],
        )
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    envelope = _finalize(envelope, elapsed_ms, active)
    return envelope


def _op_name_safe(payload: object) -> str:
    """Best-effort operation name for error envelopes."""
    if isinstance(payload, dict) and isinstance(payload.get("operation"),
                                                str):
        return payload["operation"]
    return "<malformed-request>"


def _coerce_envelope(operation: str, outcome: object) -> dict:
    """Normalize a handler outcome into an envelope shape."""
    if not isinstance(outcome, dict) or "result" not in outcome:
        return make_envelope(
            operation, STATUS_FAIL, None,
            warnings=["operation returned a malformed internal result"])
    status = outcome.get("status", "PASS")
    envelope = make_envelope(
        operation=operation,
        status=status if isinstance(status, str) else "FAIL",
        result=outcome.get("result"),
        diagnostics=outcome.get("diagnostics") or {},
        warnings=outcome.get("warnings") or [],
        provenance=outcome.get("provenance") or {},
        cross_check=outcome.get("cross_check"),
    )
    return envelope


def _has_nonfinite(value: object) -> bool:
    """True when the payload contains a NaN/±inf float anywhere."""
    if isinstance(value, float):
        return value != value or value in (float("inf"), float("-inf"))
    if isinstance(value, dict):
        return any(_has_nonfinite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_nonfinite(v) for v in value)
    return False


def _sanitize(value: object) -> object:
    """Map non-finite floats to None so the payload is JSON-safe."""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


def _finalize(envelope: dict, elapsed_ms: float, active: Limits) -> dict:
    """JSON-safety, size cap, and timing/provenance finalization.

    Never raises: a payload carrying non-finite floats is downgraded
    deterministically instead of crashing the caller (executor contract:
    every path returns a well-formed envelope).
    """
    # JSON-safety guard (mirrors the T4 tool contract), but fail-closed:
    # NaN/inf are sanitized to null and a PASS with a non-finite RESULT
    # is downgraded to NUMERICAL_WARNING (never silently collapsed to a
    # clean pass); diagnostics keep their shape with nulls for inf/nan.
    raw_result = envelope.get("result")
    result_tainted = _has_nonfinite(raw_result)
    envelope["result"] = ensure_json_safe(_sanitize(raw_result))
    envelope["diagnostics"] = ensure_json_safe(
        _sanitize(envelope.get("diagnostics")))
    if result_tainted and envelope.get("status") == STATUS_PASS:
        envelope["status"] = STATUS_NUMERICAL_WARNING
        envelope.setdefault("warnings", []).append(
            "result contained non-finite values (NaN/inf); they were "
            "suppressed to null and the status downgraded")
    # Serialized size cap (T11.6).
    encoded = json.dumps(envelope, allow_nan=False,
                         default=lambda o: f"<unserializable:{type(o).__name__}>")
    if len(encoded) > active.max_output_bytes:
        trimmed = make_envelope(
            envelope["operation"], "RESOURCE_LIMIT", None,
            warnings=[f"result exceeded {active.max_output_bytes} bytes "
                      "and was not returned"])
        envelope = trimmed
        encoded = json.dumps(envelope, allow_nan=False)
    envelope["runtime"] = {
        "device": "cpu",
        "latency_ms": round(elapsed_ms, 3),
        "wall_clock_cap_s": active.wall_clock_s,
    }
    return envelope