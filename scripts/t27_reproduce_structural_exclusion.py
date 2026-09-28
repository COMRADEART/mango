#!/usr/bin/env python3
"""Fresh-checkout reproduction for T27 structural exclusion remediation.

Never touches the physical official T26 store: the real-store metadata
authentication stays on the authorized local machine and only its pushed
aggregate evidence artifact is cross-checked here for self-consistency.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for value in (ROOT, ROOT / "src"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from t26_protocol.t27_private_oracle import (  # noqa: E402
    official_marker_binding,
    validate_t26_store_authentication_evidence)
from t27_protocol.construction import (  # noqa: E402
    CONSTRUCTION_GATE_IDS, CONTRACT_LEAF_IDS, official_marker_contract_report,
    run_construction_failure_rehearsal, run_construction_rehearsals,
    run_negative_controls, run_publication_leak_gate,
    run_real_mode_oracle_validation_rehearsal)
from t27_protocol.contract import authority_graph, production_graph  # noqa: E402
from t27_protocol.doctor import run_doctor  # noqa: E402
from t27_protocol.evaluation import (  # noqa: E402
    run_evaluation_failure_rehearsal, run_evaluation_rehearsals,
    runner_identity)
from t27_protocol.exclusion import (  # noqa: E402
    SUPERSEDED_INDEX_ROOT, authenticated_construction_policy,
    build_authenticated_public_historical_index, generated_public_dimension_policy,
    historical_exclusion_policy_v4, public_index_report, public_index_supersession,
    t26_public_qualification_exclusion_precedent)
from t27_protocol.freeze import (PRESERVED_V1_FREEZE_SHA256,  # noqa: E402
                                 PRESERVED_V2_FREEZE_SHA256,
                                 PRESERVED_V3_FREEZE_SHA256,
                                 PRESERVED_V4_FREEZE_SHA256, runtime_identity,
                                 verify_freeze_v5)
from t27_protocol.protection import run_protection  # noqa: E402


def read(out: Path, name: str) -> dict:
    return json.loads((out / name).read_text(encoding="utf-8"))


def reproduce(root: Path) -> dict:
    root = root.resolve()
    out = root / "evaluations" / "t27"
    freeze_v2 = read(out, "preconstruction_freeze_v2.json")
    mapping, runtime_root = runtime_identity(root)
    candidate = read(out, "candidate_identity.json")
    index = build_authenticated_public_historical_index(root)
    construction = run_construction_rehearsals(root, freeze_v2)
    evaluation = run_evaluation_rehearsals(root)
    failures = {
        "construction": run_construction_failure_rehearsal(root, freeze_v2),
        "evaluation": run_evaluation_failure_rehearsal(root),
    }
    preflight = read(out, "official_t26_store_preflight.json")
    marker_contract = official_marker_contract_report(root)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()
    remote = subprocess.run(
        ["git", "rev-parse", "origin/t27-preconstruction"], cwd=root,
        capture_output=True, text=True, check=True).stdout.strip()
    checks = {
        "candidate_identity": candidate["runtime_component_sha256"] == mapping
                              and candidate["runtime_root"] == runtime_root,
        "public_history_authentication": public_index_report(index) == read(
            out, "public_historical_index_report.json"),
        "generated_public_dimension_policy": (
            generated_public_dimension_policy() == read(
                out, "generated_public_exclusion_dimension_policy.json")),
        "historical_policy_v4": historical_exclusion_policy_v4() == read(
            out, "historical_exclusion_policy_v4.json"),
        "supersession": public_index_supersession(index) == read(
            out, "public_index_supersession.json"),
        "t26_exclusion_precedent": (
            t26_public_qualification_exclusion_precedent() == read(
                out, "t26_public_qualification_exclusion_precedent.json")),
        "legacy_public_history_policy": authenticated_construction_policy() == read(
            out, "historical_exclusion_policy_v3.json"),
        "old_root_superseded": (
            index["public_historical_index_root"] != SUPERSEDED_INDEX_ROOT
            and read(out, "public_index_supersession.json")[
                "superseded_root"] == SUPERSEDED_INDEX_ROOT),
        "unsatisfiability_reproducer": (
            read(out, "structural_unsatisfiability_reproducer.json")["status"]
            == "REPRODUCED"
            and read(out, "structural_unsatisfiability_reproducer.json")[
                "old_semantics_minimum_overlap"] == 33),
        "satisfiability_witness": (
            read(out, "structural_satisfiability_witness.json")["status"]
            == "PASS"
            and read(out, "structural_satisfiability_witness.json")[
                "overall_prohibited_overlap"] == 0),
        "t26_oracle_authentication":
            run_real_mode_oracle_validation_rehearsal(root) == read(
                out, "real_mode_oracle_rehearsal.json"),
        "official_marker_contract": marker_contract == read(
            out, "official_t26_marker_contract.json"),
        "official_marker_binding_pinned": (
            official_marker_binding()["marker_path_exact"] is True
            and official_marker_binding()["marker_schema_exact"] is True),
        "real_store_preflight_self_consistent": (
            validate_t26_store_authentication_evidence(preflight, real=True)
            .get("status") == "PASS"
            and preflight.get("official_commitment_scope") == "OFFICIAL_T26"
            and preflight.get("t26_official_marker_path") ==
            "evaluation/one_shot_spent.json"
            and preflight.get("t26_private_rows_read") == 0
            and preflight.get("t27_fingerprint_derivation_invoked") is False),
        "construction_rehearsals": construction == read(
            out, "construction_rehearsal_report.json"),
        "evaluation_rehearsals": evaluation == read(
            out, "evaluation_rehearsal_report.json"),
        "construction_failure_rehearsal": failures["construction"] == read(
            out, "failure_rehearsal_report.json")["construction"],
        "evaluation_failure_rehearsal": failures["evaluation"] == read(
            out, "failure_rehearsal_report.json")["evaluation"],
        "negative_controls": run_negative_controls(root, freeze_v2) == read(
            out, "construction_negative_controls.json"),
        "contract_leaf_count": len(CONTRACT_LEAF_IDS) == 60,
        "gate_check_count": len(CONSTRUCTION_GATE_IDS) == 52,
        "doctor": run_doctor(root)["status"] == "PASS",
        "production_graph": production_graph() == read(out, "production_graph.json"),
        "authority_graph": authority_graph() == read(out, "authority_graph.json"),
        "official_runner": runner_identity(root) == read(
            out, "official_runner_identity.json"),
        "protections": run_protection(root) == read(out, "protection_report.json"),
        "test_gate": read(out, "test_gate_report_v5.json")["status"] == "PASS",
        "freeze": verify_freeze_v5(
            root, read(out, "preconstruction_freeze_v5.json"))["status"] == "PASS",
        "prior_freezes_preserved": (
            read(out, "preconstruction_freeze.json")["freeze_sha256"] ==
            PRESERVED_V1_FREEZE_SHA256
            and read(out, "preconstruction_freeze_v2.json")["freeze_sha256"] ==
            PRESERVED_V2_FREEZE_SHA256
            and read(out, "preconstruction_freeze_v3.json")["freeze_sha256"] ==
            PRESERVED_V3_FREEZE_SHA256
            and read(out, "preconstruction_freeze_v4.json")["freeze_sha256"] ==
            PRESERVED_V4_FREEZE_SHA256),
        "verdict_pass": read(
            out, "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_VERDICT.json"
        )["verdict"] == "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_PASS",
        "github_local_equals_remote": head == remote,
        "public_leak_scan": run_publication_leak_gate(root)["status"] == "PASS",
    }
    return {
        "schema_version": "t27-fresh-remote-reproduction-v5",
        "artifact": "T27_FRESH_REMOTE_REPRODUCTION_V5",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "semantic_drift": sum(not value for value in checks.values()),
        "local_head": head,
        "remote_head": remote,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
        "t26_private_rows_exposed_outside_sealed_oracle": 0,
        "t26_candidate_reruns": 0,
        "t26_private_store_local_only": True,
        "construction_one_shot": "UNSPENT",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = reproduce(args.root)
    if args.write:
        path = (args.root.resolve() / "evaluations/t27" /
                "fresh_remote_reproduction_v5.json")
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())