"""Typed authorization and workspace provenance for protocol phase APIs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import AuthorizationError, ProvenanceError

CONSTRUCTION_TOKEN = "T21R15_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
EVALUATION_TOKEN = "T21R15_ONE_SHOT_OFFICIAL_EVALUATION"


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

    def validate(self) -> None:
        if self.token != CONSTRUCTION_TOKEN:
            raise AuthorizationError("construction authorization rejected")


@dataclass(frozen=True)
class EvaluationAuthorization:
    token: str

    def validate(self) -> None:
        if self.token != EVALUATION_TOKEN:
            raise AuthorizationError("evaluation authorization rejected")


@dataclass(frozen=True)
class ExecutionContext:
    workspace_mode: WorkspaceMode
    qualification_rehearsal: bool = False

    def validate(self) -> None:
        if self.qualification_rehearsal and self.workspace_mode != WorkspaceMode.REAL_EXPERIMENT:
            raise ProvenanceError("real-mode rehearsal requires REAL_EXPERIMENT workspace mode")


def require_construction_authorization(value: ConstructionAuthorization | str) -> ConstructionAuthorization:
    if isinstance(value, EvaluationAuthorization):
        raise AuthorizationError("evaluation authorization cannot authorize construction")
    authorization = value if isinstance(value, ConstructionAuthorization) else ConstructionAuthorization(str(value))
    authorization.validate()
    return authorization


def require_evaluation_authorization(value: EvaluationAuthorization | str) -> EvaluationAuthorization:
    if isinstance(value, ConstructionAuthorization):
        raise AuthorizationError("construction authorization cannot authorize evaluation")
    authorization = value if isinstance(value, EvaluationAuthorization) else EvaluationAuthorization(str(value))
    authorization.validate()
    return authorization
