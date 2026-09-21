"""Import-safe shared fixtures/helpers for the T21R16 preconstruction experiment.

All functions are pure (no filesystem writes); the only permitted side effect
is importing committed artifacts read-only. The dynamic import audit runs this
module and requires zero repository writes at import time."""
from __future__ import annotations

import json
from pathlib import Path

EXPERIMENT = "t21r16"
OUT = Path("evaluations") / EXPERIMENT
R15_OUT = Path("evaluations") / "t21r15"

#: R15 closure facts this preconstruction must preserve verbatim.
R15_CONSTRUCTION_HEAD = "86099f03461dde34b90424c990d1e0d756202b40"
R15_MANIFEST_SHA256 = "4514bedb096d095db5f35f415e4148a8a472628df2413d00ef838c87bd205a4d"
R15_HOLDOUT_FROZEN_SHA256 = "9c2aadd365a1f553db694390c6d2b03fe9b4ae21b4c9806b7e60e6e6f8f8ccfc"
R15_SEAL_ROOT = "34782693ef413aced065b09840b1372f7e4d218ecdf25938b8d03894f6c65aff"
R15_CLOSURE_STATUS = "CLOSED / SEALED_HOLDOUT_RUNTIME_CONTRACT_INCOMPATIBILITY"
R15_CLOSURE_REASON = "SEALED_CORPUS_NOT_LOADABLE_BY_FROZEN_CANDIDATE_RUNTIME"
R15_HISTORICAL_MILESTONE = "T21R15_SEALED_UNEVALUABLE"

#: Unchanged candidate and floors (from the R15 contract; carried into R16).
CANDIDATE_COMMIT = "d4b1902c9b93cae4931a348e460ce2da3e776c6f"
CANDIDATE_TREE = "dc3ca7f14375e3e71356b166a2e78a24ac3f668b"
RUNTIME_ROOT = "7bba4d0d2e381d741727e5f8d2d6a50cd82df8c054f2ec18610999a818ce1b80"
FLOOR_HASH = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"

#: R15's evaluated-suite material (for registry fingerprint derivation only).
R15_SEALED_SUITES = {
    "adversarial": 650,
    "citation_claim": 450,
    "conflict_abstention": 800,
    "crossdomain": 700,
    "multihop": 800,
    "retrieval": 600,
    "singlehop": 550,
    "temporal": 250,
}
R15_SUITE_TOTAL = sum(R15_SEALED_SUITES.values())


def load_json(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8-sig"))


def contract_path(root: Path) -> Path:
    return root / OUT / "t21_master_contract.json"


def contract_present(root: Path) -> bool:
    return contract_path(root).is_file()