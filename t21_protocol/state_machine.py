"""Explicit T21 protocol phases and command transition enforcement."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import StateTransitionError


class Phase(str, Enum):
    PRECONSTRUCTION = "PRECONSTRUCTION"
    QUALIFIED = "QUALIFIED"
    CONSTRUCTION_STARTED = "CONSTRUCTION_STARTED"
    CONSTRUCTED = "CONSTRUCTED"
    SEALED = "SEALED"
    EVALUATION_STARTED = "EVALUATION_STARTED"
    EVALUATION_COMPLETE = "EVALUATION_COMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CommandSpec:
    name: str
    required_state: Phase
    next_state: Phase
    writable_paths: tuple[str, ...]


class ProtocolStateMachine:
    def __init__(self, commands: dict[str, CommandSpec]):
        self.commands = dict(commands)

    @classmethod
    def from_contract(cls, contract: Any) -> "ProtocolStateMachine":
        raw = contract.get("state_machine.commands")
        commands: dict[str, CommandSpec] = {}
        for name, spec in raw.items():
            commands[name] = CommandSpec(
                name=name,
                required_state=Phase(spec["required_state"]),
                next_state=Phase(spec["next_state"]),
                writable_paths=tuple(spec["writable_paths"]),
            )
        machine = cls(commands)
        machine.validate()
        return machine

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        expected = {
            (Phase.PRECONSTRUCTION, Phase.QUALIFIED),
            (Phase.QUALIFIED, Phase.CONSTRUCTION_STARTED),
            (Phase.CONSTRUCTION_STARTED, Phase.CONSTRUCTED),
            (Phase.CONSTRUCTED, Phase.SEALED),
            (Phase.SEALED, Phase.EVALUATION_STARTED),
            (Phase.EVALUATION_STARTED, Phase.EVALUATION_COMPLETE),
        }
        actual = {(spec.required_state, spec.next_state) for spec in self.commands.values()}
        missing = expected - actual
        if missing:
            errors.append(f"missing lifecycle transitions: {sorted((a.value, b.value) for a, b in missing)}")
        for spec in self.commands.values():
            if spec.required_state in {Phase.FAILED, Phase.EVALUATION_COMPLETE}:
                errors.append(f"terminal phase used as command source: {spec.name}")
            if not spec.writable_paths:
                errors.append(f"command has no declared writable paths: {spec.name}")
        if errors:
            raise StateTransitionError("; ".join(errors))
        return {"status": "PASS", "commands": len(self.commands), "missing_transitions": 0}

    def transition(self, command: str, current: Phase | str) -> Phase:
        if command not in self.commands:
            raise StateTransitionError(f"unknown protocol command: {command}")
        current_phase = Phase(current)
        spec = self.commands[command]
        if current_phase != spec.required_state:
            raise StateTransitionError(
                f"{command} requires {spec.required_state.value}, got {current_phase.value}"
            )
        return spec.next_state

    def writable_paths(self, command: str) -> tuple[str, ...]:
        if command not in self.commands:
            raise StateTransitionError(f"unknown protocol command: {command}")
        return self.commands[command].writable_paths
