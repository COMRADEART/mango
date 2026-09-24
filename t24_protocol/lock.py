"""T24 preconstruction lock over code/design/contracts, never blind rows."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .author import fingerprint_root, load_spec

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "evaluations" / "t24" / "author_lock.json"
BINDINGS = {
    "author_implementation": "t24_protocol/author.py",
    "author_specification": "evaluations/t24/author_specification.json",
    "experiment_registry": "t24_protocol/context.py",
    "construction_implementation": "t24_protocol/construction.py",
    "construction_freeze_builder": "t24_protocol/freeze.py",
    "contract_validator_and_leaf_enumerator": "t24_protocol/contract.py",
    "construction_ledger_schema": "t24_protocol/ledgers.py",
    "construction_gate": "t24_protocol/gates.py",
    "construction_uniqueness_checker": "t24_protocol/exclusions.py",
    "t23_exposed_sealed_anchor": "t24_protocol/anchor_t23.py",
    "construction_manifest_and_seal": "t24_protocol/manifest.py",
    "holdout_seal_implementation": "t24_protocol/seal.py",
    "private_artifact_store": "t24_protocol/store.py",
    "private_workspace_manager": "t24_protocol/workspace.py",
    "git_blind_blob_scanner": "t24_protocol/leakscan.py",
    "live_web_firewall": "t24_protocol/firewall.py",
    "publication_policy": "t24_protocol/policy.py",
    "artifact_classification": "t24_protocol/classification.py",
    "evaluation_implementation": "t24_protocol/evaluation.py",
    "evaluation_graph_validator": "t24_protocol/graph.py",
    "doctor_implementation": "t24_protocol/doctor.py",
    "shadow_lifecycle_orchestrator": "t24_protocol/shadow.py",
    "production_provider": "t24_protocol/provider.py",
    "frozen_t23_production_provider": "t23_protocol/provider.py",
    "production_provider_config": "evaluations/t24/production_provider_config.json",
    "production_scorer": "t24_protocol/scorer.py",
    "frozen_t23_scorer": "t23_protocol/scorer.py",
    "candidate_identity": "evaluations/t24/candidate_identity.json",
    "route_registry": "evaluations/t23/route_registry.json",
    "capability_registry": "evaluations/t24/capability_registry.json",
    "router_contract": "evaluations/t23/executive_router_contract.json",
    "router_metric_semantics_and_floors": "evaluations/t24/production_router_metric_registry.json",
    "preregistered_router_floors": "evaluations/t24/router_metric_registry.json",
    "t22_protected_metrics": "evaluations/t22/official_metric_registry.json",
    "t22_protected_semantics": "evaluations/t22/official_metric_semantics.json",
    "t22_protected_implementations": "evaluations/t22/metric_implementation_registry.json",
    "t22_runtime_freeze": "evaluations/t22/runtime_freeze.json",
    "t23_exposed_sealed_anchor_artifact": "evaluations/t24/t23_exposed_sealed_anchor.json",
    "construction_exclusion_sources": "evaluations/t24/t24_exclusion_sources.json",
    "t22_hash_only_exclusion_anchor": "evaluations/t23/t22_exclusion_anchor.json",
    "t22_prior_exclusion": "evaluations/t22/prior_exclusion.json",
    "t22_remediation_exclusion": "evaluations/t22/remediation_exclusion.json",
    "live_web_source_firewall_registry": "evaluations/t24/live_web_source_firewall_registry.json",
    "publication_policy_artifact": "evaluations/t24/t24_publication_policy.json",
    "artifact_classification_artifact": "evaluations/t24/t24_artifact_classification.json",
    "private_store_config_artifact": "evaluations/t24/t24_private_store_config.json",
    "blind_private_ignore_policy": ".gitignore",
    "construction_contract": "evaluations/t24/t24_master_contract.json",
    "evaluation_graph": "evaluations/t24/production_evaluation_graph.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_lock() -> dict[str, Any]:
    spec = load_spec()
    candidate = json.loads((ROOT / BINDINGS["candidate_identity"]).read_text(encoding="utf-8"))["t24_candidate"]
    return {
        "schema_version": "t24-author-lock-v1",
        "artifact": "T24_PRODUCTION_AUTHOR_LOCK",
        "experiment": "t24",
        "construction_authorized": False,
        "author_fingerprint_root": fingerprint_root(spec),
        "taxonomy_spec_root": hashlib.sha256(json.dumps(
            {"taxonomy": spec["taxonomy"], "material_model": spec["material_model"]},
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "construction_mode": "PRECONSTRUCTION_ONLY",
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "unchanged_from_t23_candidate": True,
        "bindings": {key: {"path": relative, "sha256": _sha(ROOT / relative)}
                     for key, relative in sorted(BINDINGS.items())},
        "missing_bindings": 0,
    }


def _successor_classifiable(actual: dict[str, Any],
                            expected: dict[str, Any]) -> list[str] | None:
    """Drifted binding paths when, and only when, the lock diff is byte-drift
    inside "bindings" and every other field recomputes exactly."""
    if set(actual) != set(expected) or set(actual.get("bindings", {})) != set(expected["bindings"]):
        return None
    for key, value in expected.items():
        if key == "bindings":
            continue
        if actual.get(key) != value:
            return None
    drifted = []
    for name, binding in expected["bindings"].items():
        stored = actual["bindings"][name]
        if stored.get("path") != binding["path"]:
            return None
        if stored.get("sha256") != binding["sha256"]:
            drifted.append(binding["path"])
    return sorted(drifted) or None


def verify_lock(path: Path = LOCK) -> dict[str, Any]:
    """The stored T24 author lock must recompute exactly.

    In the authorized T25 successor tree the lock's byte bindings are
    historical: the only permitted recomputation differences are sha256
    values of bindings whose file bytes the authorized T25 remediation
    changed, and every such byte must be bound exactly by the T25 successor
    freeze (fail closed otherwise).
    """
    from .successor import successor_binding

    actual = json.loads(path.read_text(encoding="utf-8"))
    expected = expected_lock()
    if actual != expected:
        drifted_paths = _successor_classifiable(actual, expected)
        if drifted_paths is None:
            raise ValueError("T24 author lock or production binding drift")
        successor = successor_binding(ROOT, drifted_paths)
        if successor is None:
            raise ValueError("T24 author lock or production binding drift")
        return {"status": "PASS", "binding_count": len(BINDINGS),
                "missing_bindings": 0,
                "author_fingerprint_root": actual["author_fingerprint_root"],
                "candidate_commit": actual["candidate_commit"],
                "candidate_tree": actual["candidate_tree"],
                "taxonomy_spec_root": actual["taxonomy_spec_root"],
                "successor_interpretation": successor}
    return {"status": "PASS", "binding_count": len(BINDINGS),
            "missing_bindings": 0, "author_fingerprint_root": actual["author_fingerprint_root"],
            "candidate_commit": actual["candidate_commit"],
            "candidate_tree": actual["candidate_tree"],
            "taxonomy_spec_root": actual["taxonomy_spec_root"]}