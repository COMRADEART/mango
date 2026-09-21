"""Typed authorization and workspace provenance for protocol phase APIs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import AuthorizationError, ProvenanceError

CONSTRUCTION_TOKEN = "T21R15_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
EVALUATION_TOKEN = "T21R15_ONE_SHOT_OFFICIAL_EVALUATION"
CONSTRUCTION_TOKENS = {
    "t21r15": CONSTRUCTION_TOKEN,
    "t21r16": "T21R16_REAL_BLIND_CONSTRUCTION_AUTHORIZED",
    "t21r17": "T21R17_REAL_BLIND_CONSTRUCTION_AUTHORIZED",
}
EVALUATION_TOKENS = {
    "t21r15": EVALUATION_TOKEN,
    "t21r16": "T21R16_ONE_SHOT_OFFICIAL_EVALUATION",
    "t21r17": "T21R17_ONE_SHOT_OFFICIAL_EVALUATION",
}


class WorkspaceMode(str, Enum):
    SYNTHETIC_DISPOSABLE = "SYNTHETIC_DISPOSABLE"
    REAL_EXPERIMENT = "REAL_EXPERIMENT"


class MaterialMode(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    REAL_BLIND = "REAL_BLIND"
    REAL_DRY_RUN = "REAL_DRY_RUN"


@dataclass(frozen=True)
class ConstructionAuthorization:
    token: str

    def validate(self, expected: str = CONSTRUCTION_TOKEN) -> None:
        if self.token != expected:
            raise AuthorizationError("construction authorization rejected")


@dataclass(frozen=True)
class EvaluationAuthorization:
    token: str

    def validate(self, expected: str = EVALUATION_TOKEN) -> None:
        if self.token != expected:
            raise AuthorizationError("evaluation authorization rejected")


@dataclass(frozen=True)
class ExecutionContext:
    workspace_mode: WorkspaceMode
    qualification_rehearsal: bool = False

    def validate(self) -> None:
        if self.qualification_rehearsal and self.workspace_mode != WorkspaceMode.REAL_EXPERIMENT:
            raise ProvenanceError("real-mode rehearsal requires REAL_EXPERIMENT workspace mode")


def require_construction_authorization(
    value: ConstructionAuthorization | str, *, experiment: str = "t21r15"
) -> ConstructionAuthorization:
    if isinstance(value, EvaluationAuthorization):
        raise AuthorizationError("evaluation authorization cannot authorize construction")
    expected = CONSTRUCTION_TOKENS.get(experiment)
    if expected is None:
        raise AuthorizationError(f"no construction token registered for experiment: {experiment}")
    authorization = value if isinstance(value, ConstructionAuthorization) else ConstructionAuthorization(str(value))
    authorization.validate(expected)
    return authorization


def require_evaluation_authorization(
    value: EvaluationAuthorization | str, *, experiment: str = "t21r15"
) -> EvaluationAuthorization:
    if isinstance(value, ConstructionAuthorization):
        raise AuthorizationError("construction authorization cannot authorize evaluation")
    expected = EVALUATION_TOKENS.get(experiment)
    if expected is None:
        raise AuthorizationError(f"no evaluation token registered for experiment: {experiment}")
    authorization = value if isinstance(value, EvaluationAuthorization) else EvaluationAuthorization(str(value))
    authorization.validate(expected)
    return authorization
