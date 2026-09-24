"""T25 frozen token registry; exact-match authorization, no aliases or suffixing."""
from __future__ import annotations

from t23_protocol.context import CONSTRUCTION_TOKENS as PRIOR_CONSTRUCTION
from t23_protocol.context import EVALUATION_TOKENS as PRIOR_EVALUATION

EXPERIMENT = "t25"

CONSTRUCTION_TOKENS = dict(PRIOR_CONSTRUCTION)
CONSTRUCTION_TOKENS[EXPERIMENT] = "T25_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
EVALUATION_TOKENS = dict(PRIOR_EVALUATION)
EVALUATION_TOKENS[EXPERIMENT] = "T25_ONE_SHOT_OFFICIAL_EVALUATION"


def _require(tokens: dict[str, str], experiment: str, authorization: str,
             kind: str) -> dict[str, str]:
    if experiment != EXPERIMENT:
        raise ValueError(f"T25 {kind} registry only authorizes experiment {EXPERIMENT!r}, "
                         f"got {experiment!r}")
    expected = tokens.get(experiment)
    if expected is None or authorization != expected:
        raise ValueError(f"invalid or aliased T25 {kind} authorization token")
    return {"experiment": experiment, "kind": kind, "token_exact_match": True}


def require_construction_authorization(authorization: str, *, experiment: str = EXPERIMENT) -> dict[str, str]:
    return _require(CONSTRUCTION_TOKENS, experiment, authorization, "construction")


def require_evaluation_authorization(authorization: str, *, experiment: str = EXPERIMENT) -> dict[str, str]:
    return _require(EVALUATION_TOKENS, experiment, authorization, "evaluation")