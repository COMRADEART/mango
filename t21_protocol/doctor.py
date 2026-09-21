"""Single fail-closed qualification command for the T21 protocol kernel."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from .adjudication import generate_applicability, validate_adjudication
from .artifact_graph import load_artifact_graph, phase_ownership_report, validate_artifact_graph
from .audits import validate_executed_audit
from .construction import run_construction
from .context import (
    CONSTRUCTION_TOKEN,
    EVALUATION_TOKEN,
    ConstructionAuthorization,
    EvaluationAuthorization,
    WorkspaceMode,
    require_construction_authorization,
    require_evaluation_authorization,
)
from .contract import load_contract, validate_master_contract
from .exclusion import validate_historical_policy, validate_remediation_policy
from .freeze import verify_freeze
from .import_audit import dynamic_import_write_audit, static_import_write_audit
from .ledger import ConstructionLedger, EvaluationLedger
from .pipeline import run_real_mode_dry_rehearsal, run_synthetic_construction_twice, run_synthetic_twice
from .providers import SyntheticCandidateProvider, SyntheticMaterialProvider, validate_candidate_provider, validate_material_provider
from .qualification import validate_qualification_lock
from .seal import HOLDOUT_FROZEN_FIELDS, validate_holdout_frozen, validate_holdout_frozen_schema
from .state_machine import ProtocolStateMachine
from .taxonomy import canonical_labels, coverage_report, load_taxonomy
from .util import read_json, sha256_json, write_json
from .write_guard import diff_snapshots, tracked_tree

VERDICT_PASS = "T21_PROTOCOL_DOCTOR_PASS"
VERDICT_FAIL = "T21_PROTOCOL_DOCTOR_FAIL"
NEGATIVE_CONTROLS = {
    "missing seal input": "PRECONSTRUCTION",
    "unbound required seal artifact": "PRECONSTRUCTION",
    "incomplete HOLDOUT_FROZEN": "PRECONSTRUCTION",
    "missing construction-ledger implementation": "PRECONSTRUCTION",
    "second ledger creation": "PRECONSTRUCTION",
    "author fingerprint-root mismatch": "CONSTRUCTION_STARTED",
    "test writing historical committed file": "PRECONSTRUCTION",
    "import-time repository write": "PRECONSTRUCTION",
    "official validator requiring seal too early": "PRECONSTRUCTION",
    "unknown evaluator taxonomy label": "PRECONSTRUCTION",
    "contract/gate mismatch": "PRECONSTRUCTION",
    "contract/consumer schema mismatch": "PRECONSTRUCTION",
    "missing cross-module callable": "PRECONSTRUCTION",
    "raw exclusion value": "PRECONSTRUCTION",
    "missing historical exclusion dimension": "PRECONSTRUCTION",
    "historical author collision": "PRECONSTRUCTION",
    "missing exact-design context": "PRECONSTRUCTION",
    "construction authorization used for evaluation": "PRECONSTRUCTION",
    "evaluation authorization used for construction": "PRECONSTRUCTION",
    "construction chaining into evaluation": "PRECONSTRUCTION",
    "construction writing evaluation artifact": "PRECONSTRUCTION",
    "evaluation mutating sealed construction artifact": "PRECONSTRUCTION",
    "synthetic provider in real workspace": "PRECONSTRUCTION",
    "stub candidate in real workspace": "PRECONSTRUCTION",
    "placeholder audit in real workspace": "PRECONSTRUCTION",
    "synthetic material sealed in real workspace": "CONSTRUCTION_STARTED",
}


def _ledger_integration() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="t21-ledger-integration-") as directory:
        root = Path(directory)
        results: dict[str, bool] = {}
        construction_path = root / "construction.json"
        construction = ConstructionLedger.create_exclusive(construction_path, "t21r15")
        try:
            ConstructionLedger.create_exclusive(construction_path, "t21r15")
        except Exception:
            results["second_create_refused"] = True
        construction.complete()
        results["started_to_complete"] = construction.state == "COMPLETE"
        try:
            ConstructionLedger.create_exclusive(construction_path, "t21r15")
        except Exception:
            results["restart_after_complete_refused"] = True
        evaluation_path = root / "evaluation.json"
        evaluation = EvaluationLedger.create_exclusive(evaluation_path, "t21r15")
        evaluation.fail()
        results["started_to_failed"] = evaluation.state == "FAILED"
        try:
            EvaluationLedger.create_exclusive(evaluation_path, "t21r15")
        except Exception:
            results["restart_after_failed_refused"] = True
        return {"status": "PASS" if len(results) == 5 and all(results.values()) else "FAIL", **results}


def _marker_schema_check(path: Path) -> dict[str, Any]:
    sample = {
        "schema_version": "t21-holdout-frozen-v1",
        "experiment": "t21r15",
        "construction_status": "COMPLETE",
        "holdout_manifest_sha256": "a" * 64,
        "freeze_root_sha256": "b" * 64,
        "candidate_commit": "c" * 40,
        "candidate_tree": "d" * 40,
        "runtime_root": "e" * 64,
        "evaluator_root": "f" * 64,
        "floor_hash": "0" * 64,
        "construction_attempts": 1,
        "corpus_materializations": 1,
        "suite_materializations": 1,
        "candidate_rows_executed": 0,
        "runtime_rows_executed": 0,
        "official_evaluator_invocations": 0,
        "workspace_mode": "REAL_EXPERIMENT",
        "material_mode": "REAL_BLIND",
    }
    result = validate_holdout_frozen(sample)
    schema = validate_holdout_frozen_schema(read_json(path))
    return {**result, "schema_status": schema["status"], "fields": len(HOLDOUT_FROZEN_FIELDS)}


def _negative_control_registry(path: Path) -> dict[str, Any]:
    document = read_json(path)
    entries = document.get("controls", [])
    observed = {entry.get("failure_class"): entry.get("latest_legal_phase") for entry in entries}
    missing = sorted(set(NEGATIVE_CONTROLS) - set(observed))
    mismatched = sorted(name for name, phase in NEGATIVE_CONTROLS.items() if observed.get(name) != phase)
    return {
        "status": "PASS" if not missing and not mismatched else "FAIL",
        "controls": len(entries),
        "missing": missing,
        "phase_mismatches": mismatched,
    }


def _real_paths(root: Path, contract: Any) -> dict[str, Any]:
    paths = [root / relative for relative in contract.get("real_r15_paths")]
    present = [path.relative_to(root).as_posix() for path in paths if path.exists()]
    return {"status": "PASS" if not present else "FAIL", "present": present, "checked": len(paths)}


def _phase_api_check() -> dict[str, Any]:
    from .evaluate import run_evaluation

    results = {
        "production_construction_callable": callable(run_construction),
        "production_evaluation_callable": callable(run_evaluation),
    }
    return {"status": "PASS" if all(results.values()) else "FAIL", **results}


def _phase_separation(root: Path, graph: dict[str, Any], construction_rehearsal: dict[str, Any]) -> dict[str, Any]:
    source = (root / "t21_protocol" / "construction.py").read_text(encoding="utf-8")
    forbidden = ("run_evaluation", "EvaluationLedger", "evaluate_rows", "score(")
    static_edges = sum(source.count(token) for token in forbidden)
    run_1 = construction_rehearsal.get("run_1", {}).get("construction", {})
    run_2 = construction_rehearsal.get("run_2", {}).get("construction", {})
    dynamic_evaluation_executions = sum(
        int(report.get("official_evaluation_executions", -1)) for report in (run_1, run_2)
    )
    ownership = phase_ownership_report(graph)
    passed = static_edges == 0 and dynamic_evaluation_executions == 0 and ownership["status"] == "PASS"
    return {
        "status": "PASS" if passed else "FAIL",
        "construction_to_evaluation_call_edges": static_edges,
        "dynamic_official_evaluation_executions": dynamic_evaluation_executions,
        **{key: value for key, value in ownership.items() if key != "status"},
    }


def _provider_separation() -> dict[str, Any]:
    results: dict[str, bool] = {}
    synthetic_material = SyntheticMaterialProvider()
    synthetic_candidate = SyntheticCandidateProvider()
    try:
        validate_material_provider(synthetic_material, WorkspaceMode.REAL_EXPERIMENT)
    except Exception:
        results["synthetic_provider_rejected_in_real"] = True
    try:
        validate_candidate_provider(synthetic_candidate, WorkspaceMode.REAL_EXPERIMENT)
    except Exception:
        results["stub_candidate_rejected_in_real"] = True
    try:
        validate_executed_audit(
            {"artifact": "NEGATIVE_CONTROL", "status": "PASS", "audit_mode": "EXECUTED", "placeholder": True},
            WorkspaceMode.REAL_EXPERIMENT,
        )
    except Exception:
        results["placeholder_audit_rejected_in_real"] = True
    try:
        require_construction_authorization(EvaluationAuthorization(EVALUATION_TOKEN))
    except Exception:
        results["evaluation_token_rejected_by_construction"] = True
    try:
        require_evaluation_authorization(ConstructionAuthorization(CONSTRUCTION_TOKEN))
    except Exception:
        results["construction_token_rejected_by_evaluation"] = True
    return {"status": "PASS" if len(results) == 5 and all(results.values()) else "FAIL", **results}


def run_doctor(root: Path, experiment: str = "t21r15") -> dict[str, Any]:
    before = tracked_tree(root)
    out = root / "evaluations" / experiment
    contract = load_contract(out / "t21_master_contract.json")
    graph = load_artifact_graph(out / "artifact_graph.json")
    taxonomy = load_taxonomy(out / "domain_taxonomy_contract.json")
    canonical = canonical_labels(taxonomy)
    author_labels = set(contract.get("author.vocabulary"))
    taxonomy_report = coverage_report(
        taxonomy,
        {
            "author": author_labels,
            "suite_builder": canonical,
            "gold_validator": canonical,
            "evaluator": canonical,
            "scorer": canonical,
            "domain_macro_aggregator": canonical,
        },
    )
    adjudication = read_json(out / "test_failure_adjudication.json")
    applicability = generate_applicability(adjudication)
    committed_applicability = read_json(out / "current_test_applicability.json")
    checks: dict[str, Any] = {
        "master_contract": validate_master_contract(contract.document, raise_on_error=False),
        "artifact_graph": validate_artifact_graph(graph, raise_on_error=False),
        "state_machine": ProtocolStateMachine.from_contract(contract).validate(),
        "ledgers": _ledger_integration(),
        "holdout_frozen_schema": _marker_schema_check(root / contract.get("artifacts.holdout_frozen_schema")),
        "taxonomy": taxonomy_report,
        "historical_exclusion": validate_historical_policy(read_json(out / "historical_exclusion.json"), root),
        "remediation_exclusion": validate_remediation_policy(read_json(out / "remediation_exclusion.json")),
        "runtime_freeze": verify_freeze(root, out / "runtime_freeze.json", artifact="T21R15_RUNTIME_FREEZE"),
        "evaluator_freeze": verify_freeze(root, out / "evaluator_freeze.json", artifact="T21R15_EVALUATOR_FREEZE"),
        "qualification_lock": validate_qualification_lock(root, contract, read_json(out / "qualification_lock.json")),
        "adjudication": validate_adjudication(adjudication),
        "applicability": {
            "status": "PASS" if committed_applicability.get("deselect_nodeids") == applicability["deselect_nodeids"] else "FAIL",
            "registered_failures": applicability["registered_failures"],
        },
        "negative_controls": _negative_control_registry(out / "negative_controls.json"),
        "real_paths": _real_paths(root, contract),
        "production_phase_apis": _phase_api_check(),
        "provider_separation": _provider_separation(),
    }
    module_paths = sorted((root / "t21_protocol").glob("*.py"))
    helper_names = ("t21r_fixtures", "t21r12_fixtures", "t21r13_fixtures", "t21r14_fixtures")
    helper_paths = [root / "scripts" / f"{name}.py" for name in helper_names]
    test_paths = sorted((root / "tests").glob("test_t21*.py"))
    checks["static_import_audit"] = static_import_write_audit([*module_paths, *helper_paths, *test_paths])
    checks["dynamic_import_audit"] = dynamic_import_write_audit(
        root,
        [f"t21_protocol.{path.stem}" for path in module_paths if path.stem not in {"__init__", "doctor"}]
        + list(helper_names),
    )
    construction_rehearsal = run_synthetic_construction_twice(root, contract, graph)
    checks["synthetic_construction_only"] = construction_rehearsal
    checks["phase_separation"] = _phase_separation(root, graph, construction_rehearsal)
    checks["real_mode_dry_rehearsal"] = run_real_mode_dry_rehearsal(root, contract, graph)
    checks["synthetic_full_protocol"] = run_synthetic_twice(root, contract, graph)
    cleanliness_path = out / "test_cleanliness.json"
    checks["test_cleanliness"] = read_json(cleanliness_path) if cleanliness_path.is_file() else {"status": "FAIL", "reason": "missing test cleanliness evidence"}
    r14 = read_json(root / "evaluations" / "t21r14" / "T21R14_CLOSURE.json")
    checks["r14_disposition"] = {
        "status": "PASS" if r14.get("status") == "CLOSED / PRECONSTRUCTION_PROTOCOL_INTEGRATION_FAILURE" and r14.get("construction_attempts") == 0 and r14.get("one_shot_consumed") is False else "FAIL"
    }
    after = tracked_tree(root)
    drift = diff_snapshots(before, after)
    checks["doctor_cleanliness"] = {
        "status": "PASS" if not any(drift.values()) else "FAIL",
        "tracked_tree_before": sha256_json(before),
        "tracked_tree_after": sha256_json(after),
        "tracked_drift": sum(len(value) for value in drift.values()),
    }
    passed = all(check.get("status") in {"PASS", "VERIFIED"} for check in checks.values())
    return {
        "schema_version": "t21-protocol-doctor-report-v1",
        "artifact": "T21_PROTOCOL_DOCTOR_REPORT",
        "experiment": experiment,
        "checks": checks,
        "status": "PASS" if passed else "FAIL",
        "verdict": VERDICT_PASS if passed else VERDICT_FAIL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="t21r15")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--write-report", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = run_doctor(arguments.root.resolve(), arguments.experiment)
    except Exception as exc:
        report = {
            "schema_version": "t21-protocol-doctor-report-v1",
            "artifact": "T21_PROTOCOL_DOCTOR_REPORT",
            "experiment": arguments.experiment,
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "verdict": VERDICT_FAIL,
        }
    if arguments.write_report:
        write_json(arguments.root / "evaluations" / arguments.experiment / "protocol_doctor_report.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "verdict"}, indent=2, sort_keys=True))
    print(report["verdict"])
    return 0 if report["verdict"] == VERDICT_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
