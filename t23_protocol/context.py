"""Additive production experiment registry preserving frozen T21/T22 bytes.

The T22 evaluator freeze binds t21_protocol/context.py and contract.py by
SHA-256. Editing either would invalidate T22's root of trust; this adapter
extends their closed registries without changing any protected component.
"""
from __future__ import annotations

from pathlib import Path

from t21_protocol.context import (
    CONSTRUCTION_TOKENS as PRIOR_CONSTRUCTION,
    EVALUATION_TOKENS as PRIOR_EVALUATION,
    require_construction_authorization as prior_construction,
    require_evaluation_authorization as prior_evaluation,
)
from t21_protocol.contract import load_contract as load_prior_contract
from t21_protocol.errors import AuthorizationError

from .contract import load_t23_contract

CONSTRUCTION_TOKENS = PRIOR_CONSTRUCTION | {
    "t23": "T23_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
}
EVALUATION_TOKENS = PRIOR_EVALUATION | {
    "t23": "T23_ONE_SHOT_OFFICIAL_EVALUATION",
}


def require_construction_authorization(token: str, *, experiment: str) -> None:
    if experiment == "t23":
        if token != CONSTRUCTION_TOKENS["t23"]:
            raise AuthorizationError("T23 construction authorization rejected")
        return
    prior_construction(token, experiment=experiment)


def require_evaluation_authorization(token: str, *, experiment: str) -> None:
    if experiment == "t23":
        if token != EVALUATION_TOKENS["t23"]:
            raise AuthorizationError("T23 evaluation authorization rejected")
        return
    prior_evaluation(token, experiment=experiment)


def load_experiment_contract(path: Path, *, experiment: str):
    if experiment == "t23":
        return load_t23_contract(path)
    if experiment not in PRIOR_CONSTRUCTION:
        raise AuthorizationError(f"unknown experiment: {experiment}")
    contract = load_prior_contract(path)
    if contract.experiment != experiment:
        raise AuthorizationError("experiment/contract mismatch")
    return contract
