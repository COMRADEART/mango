"""scicomp invocation — the model-facing tool boundary (T11.14, T11.33).

Mango-4B-System-v1 generates structured compute requests; this module is
the ONLY way they reach the laboratory. It composes, in order:

1. deterministic routing eligibility (T11.13 router) — recorded, never
   enforced against the model (the model may legitimately compute
   something the router missed; the mismatch is measured, not blocked);
2. structural + semantic schema validation (T11.4);
3. bounded CPU execution through ``executor.execute`` (T11.6);
4. trust labeling of the outcome for the answer layer (T11.17/T11.18).

The model NEVER authors code (T11.33): a request whose payload contains
anything but the structured schema is rejected at step 2 and becomes a
deterministic rejection result the model sees as an observation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sciencemath.scicomp import router as scicomp_router
from sciencemath.scicomp.executor import execute
from sciencemath.scicomp.schemas import STATUS_PASS
from sciencemath.scicomp.trust import adoption_allowed, Provenance


@dataclass
class InvocationResult:
    """One model-initiated compute invocation, fully auditable (T11.15)."""

    request: dict
    envelope: dict
    route_recommendation: dict
    adopted: bool
    latency_ms: float
    prevalidation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "request": self.request,
            "envelope": self.envelope,
            "route_recommendation": self.route_recommendation,
            "adopted": self.adopted,
            "latency_ms": self.latency_ms,
            "prevalidation": self.prevalidation,
        }


def prevalidate(payload: object) -> dict:
    """Cheap structural gate BEFORE execution (mirrors the T4
    prevalidation pattern): shape only, no execution."""
    checks = {"is_object": False, "has_operation": False,
              "has_inputs": False, "no_code_keys": False}
    if isinstance(payload, dict):
        checks["is_object"] = True
        checks["has_operation"] = isinstance(payload.get("operation"), str)
        checks["has_inputs"] = isinstance(payload.get("inputs", {}), dict)
        # T11.33 guard: the model must not smuggle code to execute.
        forbidden = {"code", "script", "python", "source", "exec",
                     "command", "shell", "path"}
        present = set()
        for section in (payload, payload.get("inputs", {}),
                        payload.get("options", {})):
            if isinstance(section, dict):
                present |= set(section) & forbidden
        checks["no_code_keys"] = not present
    return {"ok": all(checks.values()), "checks": checks}


def invoke(payload: object, question: str = "") -> InvocationResult:
    """Execute one model-generated compute request (T11.14 flow).

    ``question`` is the problem text the request arose from — used only
    for the router's eligibility recommendation, never for execution.
    """
    start = time.perf_counter()
    route_rec = scicomp_router.route(question)
    pre = prevalidate(payload)
    envelope = execute(payload)
    latency = (time.perf_counter() - start) * 1000.0
    return InvocationResult(
        request=payload if isinstance(payload, dict) else {},
        envelope=envelope,
        route_recommendation=route_rec,
        adopted=envelope.get("status") == STATUS_PASS
        and adoption_allowed(envelope),
        latency_ms=round(latency, 3),
        prevalidation=pre,
    )


def observation_text(result: InvocationResult) -> str:
    """Compact observation for the executive's step context.

    Distinguishes computed results from retrieved facts and never
    presents a non-verified number as certainty (T11.17, T11.18).
    """
    env = result.envelope
    status = env.get("status")
    if status != STATUS_PASS:
        reason = "; ".join(env.get("warnings", [])[:2]) or status
        return f"COMPUTE {env.get('operation')}: {status} — {reason}"
    label = Provenance.DETERMINISTIC_COMPUTATION.value
    parts = [f"COMPUTED [{label}] via {env.get('operation')}",
             f"result: {env.get('result')}"]
    diag = env.get("diagnostics") or {}
    if diag:
        shown = {k: diag[k] for k in list(diag)[:4]}
        parts.append(f"diagnostics: {shown}")
    for w in env.get("warnings", [])[:2]:
        parts.append(f"warning: {w}")
    return " | ".join(parts)