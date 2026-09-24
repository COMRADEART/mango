"""T25 preconstruction lock over code/design/contracts, never blind rows."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .author import fingerprint_root, load_spec

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "evaluations" / "t25" / "author_lock.json"
BINDINGS = {
    "author_implementation": "t25_protocol/author.py",
    "author_specification": "evaluations/t25/author_specification.json",
    "experiment_registry": "t25_protocol/context.py",
    "construction_implementation": "t25_protocol/construction.py",
    "construction_freeze_builder": "t25_protocol/freeze.py",
    "contract_validator_and_leaf_enumerator": "t25_protocol/contract.py",
    "construction_ledger_schema": "t25_protocol/ledgers.py",
    "construction_gate": "t25_protocol/gates.py",
    "construction_uniqueness_checker": "t25_protocol/exclusions.py",
    "t23_exposed_sealed_anchor": "t24_protocol/anchor_t23.py",
    "t24_sealed_evaluated_anchor": "t25_protocol/anchor_t24.py",
    "t24_successor_applicability": "t24_protocol/successor.py",
    "construction_manifest_and_seal": "t25_protocol/manifest.py",
    "holdout_seal_implementation": "t25_protocol/seal.py",
    "private_artifact_store": "t25_protocol/store.py",
    "private_workspace_manager": "t25_protocol/workspace.py",
    "git_blind_blob_scanner": "t25_protocol/leakscan.py",
    "live_web_firewall": "t25_protocol/firewall.py",
    "publication_policy": "t25_protocol/policy.py",
    "artifact_classification": "t25_protocol/classification.py",
    "evaluation_implementation": "t25_protocol/evaluation.py",
    "evaluation_graph_validator": "t25_protocol/graph.py",
    "doctor_implementation": "t25_protocol/doctor.py",
    "shadow_lifecycle_orchestrator": "t25_protocol/shadow.py",
    "production_provider": "t25_protocol/provider.py",
    "frozen_t23_production_provider": "t23_protocol/provider.py",
    "production_provider_config": "evaluations/t25/production_provider_config.json",
    "production_scorer": "t25_protocol/scorer.py",
    "frozen_t23_scorer": "t23_protocol/scorer.py",
    "candidate_identity": "evaluations/t25/candidate_identity.json",
    "route_registry": "evaluations/t23/route_registry.json",
    "capability_registry": "evaluations/t25/capability_registry.json",
    "router_contract": "evaluations/t23/executive_router_contract.json",
    "router_metric_semantics_and_floors": "evaluations/t25/production_router_metric_registry.json",
    "preregistered_router_floors": "evaluations/t25/router_metric_registry.json",
    "t22_protected_metrics": "evaluations/t22/official_metric_registry.json",
    "t22_protected_semantics": "evaluations/t22/official_metric_semantics.json",
    "t22_protected_implementations": "evaluations/t22/metric_implementation_registry.json",
    "t22_runtime_freeze": "evaluations/t22/runtime_freeze.json",
    "t23_exposed_sealed_anchor_artifact": "evaluations/t25/t23_exposed_sealed_anchor.json",
    "t24_sealed_evaluated_anchor_artifact": "evaluations/t25/t24_sealed_evaluated_anchor.json",
    "construction_exclusion_sources": "evaluations/t25/t25_exclusion_sources.json",
    "t22_hash_only_exclusion_anchor": "evaluations/t23/t22_exclusion_anchor.json",
    "t22_prior_exclusion": "evaluations/t22/prior_exclusion.json",
    "t22_remediation_exclusion": "evaluations/t22/remediation_exclusion.json",
    "live_web_source_firewall_registry": "evaluations/t25/live_web_source_firewall_registry.json",
    "publication_policy_artifact": "evaluations/t25/t25_publication_policy.json",
    "artifact_classification_artifact": "evaluations/t25/t25_artifact_classification.json",
    "private_store_config_artifact": "evaluations/t25/t25_private_store_config.json",
    "blind_private_ignore_policy": ".gitignore",
    "construction_contract": "evaluations/t25/t25_master_contract.json",
    "evaluation_graph": "evaluations/t25/production_evaluation_graph.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_lock() -> dict[str, Any]:
    spec = load_spec()
    candidate = json.loads((ROOT / BINDINGS["candidate_identity"]).read_text(encoding="utf-8"))["t25_candidate"]
    return {
        "schema_version": "t25-author-lock-v1",
        "artifact": "T25_PRODUCTION_AUTHOR_LOCK",
        "experiment": "t25",
        "construction_authorized": False,
        "author_fingerprint_root": fingerprint_root(spec),
        "taxonomy_spec_root": hashlib.sha256(json.dumps(
            {"taxonomy": spec["taxonomy"], "material_model": spec["material_model"]},
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "construction_mode": "PRECONSTRUCTION_ONLY",
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "unchanged_from_t23_candidate": False,
        "unchanged_from_t24_candidate": False,
        "bindings": {key: {"path": relative, "sha256": _sha(ROOT / relative)}
                     for key, relative in sorted(BINDINGS.items())},
        "missing_bindings": 0,
    }


def verify_lock(path: Path = LOCK) -> dict[str, Any]:
    actual = json.loads(path.read_text(encoding="utf-8"))
    expected = expected_lock()
    if actual != expected:
        raise ValueError("T25 author lock or production binding drift")
    return {"status": "PASS", "binding_count": len(BINDINGS),
            "missing_bindings": 0, "author_fingerprint_root": actual["author_fingerprint_root"],
            "candidate_commit": actual["candidate_commit"],
            "candidate_tree": actual["candidate_tree"],
            "taxonomy_spec_root": actual["taxonomy_spec_root"]}