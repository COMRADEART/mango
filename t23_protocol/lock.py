"""T23 preconstruction lock over code/design/contracts, never blind rows."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .author import fingerprint_root, load_spec

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "evaluations" / "t23" / "author_lock.json"
BINDINGS = {
    "author_implementation": "t23_protocol/author.py",
    "author_specification": "evaluations/t23/author_specification.json",
    "experiment_registry": "t23_protocol/context.py",
    "construction_implementation": "t23_protocol/construction.py",
    "evaluation_implementation": "t23_protocol/evaluation.py",
    "evaluation_graph_validator": "t23_protocol/graph.py",
    "doctor_implementation": "t23_protocol/doctor.py",
    "production_provider": "t23_protocol/provider.py",
    "production_provider_config": "evaluations/t23/production_provider_config.json",
    "production_scorer": "t23_protocol/scorer.py",
    "candidate_identity": "evaluations/t23/candidate_identity.json",
    "route_registry": "evaluations/t23/route_registry.json",
    "capability_registry": "evaluations/t23/capability_registry.json",
    "router_contract": "evaluations/t23/executive_router_contract.json",
    "router_metric_semantics_and_floors": "evaluations/t23/production_router_metric_registry.json",
    "preregistered_router_floors": "evaluations/t23/router_metric_registry.json",
    "t22_protected_metrics": "evaluations/t22/official_metric_registry.json",
    "t22_protected_semantics": "evaluations/t22/official_metric_semantics.json",
    "t22_protected_implementations": "evaluations/t22/metric_implementation_registry.json",
    "t22_runtime_freeze": "evaluations/t22/runtime_freeze.json",
    "historical_exclusion": "evaluations/t23/historical_exclusion.json",
    "privacy_policy": "evaluations/t23/private_blind_policy.json",
    "blind_private_ignore_policy": ".gitignore",
    "construction_contract": "evaluations/t23/t23_master_contract.json",
    "evaluation_graph": "evaluations/t23/production_evaluation_graph.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_lock() -> dict[str, Any]:
    spec = load_spec()
    candidate = json.loads((ROOT / BINDINGS["candidate_identity"]).read_text(encoding="utf-8"))["t23_candidate"]
    return {
        "schema_version": "t23-author-lock-v1",
        "artifact": "T23_PRODUCTION_AUTHOR_LOCK",
        "experiment": "t23",
        "construction_authorized": False,
        "author_fingerprint_root": fingerprint_root(spec),
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "bindings": {key: {"path": relative, "sha256": _sha(ROOT / relative)}
                     for key, relative in sorted(BINDINGS.items())},
        "missing_bindings": 0,
    }


def verify_lock(path: Path = LOCK) -> dict[str, Any]:
    actual = json.loads(path.read_text(encoding="utf-8"))
    expected = expected_lock()
    if actual != expected:
        raise ValueError("T23 author lock or production binding drift")
    return {"status": "PASS", "binding_count": len(BINDINGS),
            "missing_bindings": 0, "author_fingerprint_root": actual["author_fingerprint_root"]}
