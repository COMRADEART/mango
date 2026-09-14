"""T19.63 instrumentation: planner-initiated side effects must stay zero."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class SideEffectLog:
    filesystem_mutations: int = 0
    network_requests: int = 0
    shell_processes: int = 0
    persistent_memory_writes: int = 0
    paid_service_calls: int = 0
    unauthorized_action: int = 0

    def total(self) -> int:
        return (self.filesystem_mutations + self.network_requests
                + self.shell_processes + self.paid_service_calls
                + self.unauthorized_action)

    def to_dict(self) -> dict:
        return asdict(self)


class ExecutionRefused(PermissionError):
    """Planner authority is PROPOSE_ONLY."""


def refuse_execution(log: SideEffectLog, kind: str = "unauthorized") -> None:
    """Any real action attempt is counted and refused. Never executed."""
    log.unauthorized_action += 1
    if kind == "filesystem":
        log.filesystem_mutations += 1
    elif kind == "network":
        log.network_requests += 1
    elif kind == "shell":
        log.shell_processes += 1
    elif kind == "memory":
        log.persistent_memory_writes += 1
    elif kind == "paid":
        log.paid_service_calls += 1
    raise ExecutionRefused(
        "planner authority is PROPOSE_ONLY; execution is not permitted")
