#!/usr/bin/env python3
"""Build and reproduce only public-safe T26 preconstruction artifacts.

This entrypoint has no command for real blind construction or evaluation.
Those one-shot phases are guarded separately by exact future tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from t21_protocol.util import sha256_json  # noqa: E402
from t26_protocol.contract import (authority_graph, design, execution_contract,  # noqa: E402
                                   live_web_firewall_registry, metric_registry,
                                   production_graph, storage_policy)
from t26_protocol.doctor import run_doctor  # noqa: E402
from t26_protocol.exclusion import (build_historical_exclusion_document)  # noqa: E402,F401
from t26_protocol.freeze import build_freeze, verify_freeze  # noqa: E402
from t26_protocol.native_smoke import native_case, run_native_smoke  # noqa: E402
from t26_protocol.protection import run_protection  # noqa: E402
from t26_protocol.qualification import (build_public_cases,  # noqa: E402
                                        exclusion_fingerprints,
                                        run_qualification)
from t26_protocol.rehearsal import run_rehearsals  # noqa: E402
from t26_protocol.test_gate import run_test_gate  # noqa: E402

OUT = ROOT / "evaluations" / "t26"
T25_PROMOTION = "8940d96aacb08d8acf110e5f3e45e9ce84f03577"


def _write(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True,
                                    ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8", newline="\n")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def _candidate_identity() -> dict:
    candidate = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD^")
    if parent != T25_PROMOTION:
        raise ValueError("T26 runtime candidate must directly descend from T25 promotion")
    tree = _git("rev-parse", "HEAD^{tree}")
    prior = json.loads((ROOT / "evaluations/t25/candidate_identity.json")
                       .read_text(encoding="utf-8"))["t25_candidate"]
    changed = _git("diff", "--name-only", T25_PROMOTION, candidate).splitlines()
    expected_changed = ["src/sciencemath/integrated/__init__.py",
                        "src/sciencemath/integrated/runner.py"]
    if changed != expected_changed:
        raise ValueError(f"T26 runtime candidate changed unexpected files: {changed}")
    mapping = dict(prior["runtime_component_sha256"])
    for relative in expected_changed:
        path = ROOT / relative
        content = path.read_bytes()
        committed = subprocess.run(["git", "show", f"{candidate}:{relative}"],
                                   cwd=ROOT, capture_output=True, check=True).stdout
        if content != committed:
            raise ValueError(f"candidate runtime working-tree drift: {relative}")
        mapping[relative] = hashlib.sha256(content).hexdigest()
    return {"schema_version": "t26-candidate-identity-v1",
            "artifact": "T26_CANDIDATE_IDENTITY",
            "candidate_commit": candidate, "candidate_tree": tree,
            "parent_candidate": prior["candidate_commit"],
            "promotion_base": T25_PROMOTION,
            "changed_from_t25": True,
            "changed_runtime_files": expected_changed,
            "runtime_component_count": len(mapping),
            "runtime_component_sha256": dict(sorted(mapping.items())),
            "runtime_root": sha256_json(mapping),
            "public_safe_justification": "Bounded internal multi-capability runner with explicit plan, T25 router dispatch validation, handoff provenance, independent verification, retry/replan budgets, checkpoint resume and fail-closed completion. No T25 private evidence was used."}


def build_static() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    identity_path = OUT / "candidate_identity.json"
    if identity_path.exists():
        # Section 4: the candidate is frozen across this remediation. Verify
        # the committed identity instead of re-deriving it from HEAD.
        candidate = json.loads(identity_path.read_text(encoding="utf-8"))
        if (candidate["candidate_commit"] != "6cb029c0f4edb4116c7f9a1f187cdc4671077a1f"
                or candidate["candidate_tree"] != "6199df3a4537e5af480098a4bd009c357ecc2910"
                or candidate["runtime_root"] !=
                "28f83990f5382400bac72cb34448ad5854c875d74655f1a571703f50d9cb453c"):
            raise ValueError("frozen T26 candidate identity drifted")
        mapping = dict(candidate["runtime_component_sha256"])
        for relative, expected in mapping.items():
            content = (ROOT / relative).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"candidate runtime working-tree drift: {relative}")
    else:
        candidate = _candidate_identity()
        _write(identity_path, candidate)
    artifacts = {
        "prospective_design.json": design(),
        "t26_execution_contract.json": execution_contract(),
        "metric_registry.json": metric_registry(),
        "authority_graph.json": authority_graph(),
        "production_graph.json": production_graph(),
        "private_storage_policy.json": storage_policy(),
    }
    for filename, document in artifacts.items():
        _write(OUT / filename, document)
    cases, gold, _ = build_public_cases()
    _jsonl(OUT / "qualification" / "inputs.jsonl", cases)
    _jsonl(OUT / "qualification" / "gold.jsonl", gold)
    exclusions = exclusion_fingerprints(cases + [native_case()[0]])
    _write(OUT / "qualification_exclusions.json", exclusions)
    _write(OUT / "live_web_firewall_registry.json", live_web_firewall_registry(ROOT))
    qualification = run_qualification()
    _write(OUT / "qualification_report.json", qualification)
    native = run_native_smoke(ROOT, exclusions)
    _write(OUT / "native_smoke_report.json", native)
    rehearsals = run_rehearsals()
    _write(OUT / "rehearsal_report.json", rehearsals)
    return {"candidate_commit": candidate["candidate_commit"],
            "candidate_tree": candidate["candidate_tree"],
            "runtime_root": candidate["runtime_root"],
            "qualification": qualification["status"],
            "native_smoke": native["status"],
            "rehearsals": rehearsals["status"]}


def build_protection() -> dict:
    result = run_protection(ROOT)
    _write(OUT / "protection_report.json", result)
    return {"status": result["status"],
            "t19": result["t19"]["tests"],
            "t20": result["t20"]["tests"],
            "t22": result["t22"],
            "t25_router": result["t25_router"],
            "t25_dispatch": result["t25_dispatch"]["status"]}


def build_test_gate() -> dict:
    result = run_test_gate(ROOT)
    _write(OUT / "test_gate_report.json", result)
    return result


OLD_FREEZE_V1 = {
    "record": "T26_PRECONSTRUCTION_FREEZE_V1_SUPERSEDED_PRE_EXPOSURE",
    "freeze_sha256": "ff09bed6caf8b7c9760bf57b7f2954374a22610797e785c35e54b78daa033ac6",
    "component_count": 235,
    "component_root": "1f879681a7c138b7d0974e8489284aef010dcbfc8bcc90247c5a7181bf526381",
    "freeze_root": "55047a78eb3b4ecefa5453225446e091ed214ffe1ca5fe864a24878732ec8c3b",
    "blind_material_under_it": "none",
    "preserved_in_git_history": True,
}

OLD_FREEZE_V2 = {
    "record": "T26_PRECONSTRUCTION_FREEZE_V2_SUPERSEDED_PRE_EXPOSURE",
    "reason": "ZERO_FIXTURE_CONTRACT_OPTIONALITY_WIRING_DEFECT",
    "freeze_sha256": "98ae5124de494e99fb1398633f19131e1e5af976cbeb672249c57c83d3d9ae35",
    "component_count": 243,
    "component_root": "015a45720ffcd70867006a84af9a2908386bfc1988a2db7d1ea1b410fcefb430",
    "freeze_root": "20191c43dbdf6d567f54fc51af241dcc37e51ab3a8c2bf1e88c81c448623936e",
    "blind_material_under_it": "none",
    "real_construction_attempts": 0,
    "preserved_in_git_history": True,
}


def build_construction_infrastructure() -> dict:
    """Rebuild every construction-infrastructure public artifact (sections 7-32)."""
    from t26_protocol.construction import (protocol_hashes,
                                           run_negative_gate_controls)
    from t26_protocol.qualification import construction_rehearsal_fingerprints

    _write(OUT / "qualification_exclusions.json", exclusion_fingerprints(
        build_public_cases()[0] + [native_case()[0]]))
    _write(OUT / "rehearsal_exclusion_fingerprints.json",
           construction_rehearsal_fingerprints())
    _write(OUT / "historical_exclusions.json",
           build_historical_exclusion_document(ROOT))
    _write(OUT / "protocol_identity_hashes.json", protocol_hashes(ROOT))
    negative = run_negative_gate_controls(ROOT)
    _write(OUT / "negative_gate_controls.json", negative)
    return {"status": "PASS" if negative["status"] == "PASS" else "FAIL",
            "negative_controls": negative["control_count"]}


def run_failure_rehearsal() -> dict:
    """Inject a failure after ledger creation (section 32); prove FAILED semantics."""
    import tempfile

    from t26_protocol.construction import (ConstructionLedgerError,
                                           _synthetic_oracle_result,
                                           construct_real,
                                           synthetic_author_provenance,
                                           synthetic_private_bundle)
    from t26_protocol.lifecycle import T26PrivateStore

    with tempfile.TemporaryDirectory(prefix="t26-failure-rehearsal-") as tmp:
        store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
        cases, gold, fixtures = synthetic_private_bundle(3)
        oracle = _synthetic_oracle_result(ROOT, cases, gold, fixtures)
        provenance = synthetic_author_provenance(cases, gold, fixtures)
        token = "T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
        raised = False
        try:
            construct_real(ROOT, store, token=token, cases=cases, gold=gold,
                           fixtures=fixtures, oracle_result=oracle,
                           provenance=provenance,
                           inject_failure_after_ledger=True)
        except RuntimeError:
            raised = True
        ledger_doc = store.read("construction/ledger.json")
        events = [event["event_type"] for event in ledger_doc["events"]]
        second_refused = False
        try:
            construct_real(ROOT, store, token=token, cases=cases, gold=gold,
                           fixtures=fixtures, oracle_result=oracle,
                           provenance=provenance)
        except (ConstructionLedgerError, RuntimeError, ValueError):
            second_refused = True
        failure_event = ledger_doc["events"][-1]
        ok = (raised and ledger_doc["state"] == "FAILED"
              and ledger_doc["attempt"] == 1
              and events.count("LEDGER_CREATED") == 1
              and failure_event["event_type"] == "FAILED"
              and set(failure_event["payload"]) == {"failure_phase",
                                                    "failure_class",
                                                    "evidence_hash"}
              and second_refused)
        return {"status": "PASS" if ok else "FAIL",
                "ledger_final_state": ledger_doc["state"],
                "attempt_count": ledger_doc["attempt"],
                "retry_count": 0, "second_construction_refused": second_refused,
                "failure_event": failure_event["payload"],
                "evidence_preserved": True}


def build_construction_rehearsals(*, persist: bool = True) -> dict:
    """Fixture-bearing x2, zero-fixture, and failure lifecycle rehearsals."""
    import tempfile

    from t26_protocol.construction import (_synthetic_oracle_result, construct_real,
                                           ledger_semantic_digest,
                                           run_zero_fixture_contract_controls,
                                           synthetic_author_provenance,
                                           synthetic_private_bundle)
    from t26_protocol.lifecycle import T26PrivateStore

    runs = []
    run_specs = ((1, "FIXTURE_BEARING", 2),
                 (2, "FIXTURE_BEARING", 2),
                 (3, "ZERO_FIXTURE", 4))
    for index, fixture_mode, variant in run_specs:
        with tempfile.TemporaryDirectory(
                prefix=f"t26-construction-rehearsal-{index}-") as tmp:
            store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
            # Variants 0/1 are permanently registered as disposable rehearsal
            # fingerprints. Fixture-bearing runs use variant 2; the zero-
            # fixture policy rehearsal uses fresh variant 4.
            cases, gold, authored_fixtures = synthetic_private_bundle(variant)
            fixtures = authored_fixtures if fixture_mode == "FIXTURE_BEARING" else []
            oracle = _synthetic_oracle_result(ROOT, cases, gold, fixtures)
            provenance = synthetic_author_provenance(cases, gold, fixtures)
            result = construct_real(ROOT, store,
                                    token="T26_REAL_BLIND_HOLDOUT_"
                                          "CONSTRUCTION_AUTHORIZATION",
                                    cases=cases, gold=gold, fixtures=fixtures,
                                    oracle_result=oracle,
                                    provenance=provenance)
            runs.append({
                "run": index, "fixture_mode": fixture_mode,
                "fixture_count": len(fixtures), "status": result["status"],
                "case_count": result["case_count"],
                "ledger_state": result["ledger"]["state"],
                "ledger_attempt": result["ledger"]["attempt"],
                "ledger_event_count": result["ledger"]["event_count"],
                "execution_checkout_commit":
                    result["ledger"]["bindings"]["execution_checkout_commit"],
                "execution_checkout_tree":
                    result["ledger"]["bindings"]["execution_checkout_tree"],
                "ledger_semantic_digest": ledger_semantic_digest(result["ledger"]),
                "audit_root": result["audit"]["audit_root"],
                "gate_root": result["gate"]["gate_root"],
                "gate_check_count": result["gate"]["check_count"],
                "contract_leaf_total": result["contract_leaf_audit"]["total_leaves"],
                "contract_leaf_pass_count":
                    result["contract_leaf_audit"]["pass_count"],
                "contract_leaf_fail_count":
                    result["contract_leaf_audit"]["fail_count"],
                "manifest_roots": result["manifest_roots"],
                "seal_state": result["seal"]["state"],
                "store_verify": result["store_verification"]["status"],
                "receipt_state": result["receipt"]["state"],
                "commitment_semantic": {
                    key: value for key, value in result["commitment"].items()
                    if key not in {"construction_ledger_sha256",
                                   "construction_ledger_root",
                                   "private_manifest_sha256", "seal_sha256",
                                   "commitment_root"}},
                "commitment_root": result["commitment"]["commitment_root"],
                "publication_leak_gate": result["publication_leak_gate"]["status"],
                "blind_blob_count": result["publication_leak_gate"]["blind_blob_count"]})
    fixture_runs = [run for run in runs
                    if run["fixture_mode"] == "FIXTURE_BEARING"]
    zero_fixture_run = next(run for run in runs
                            if run["fixture_mode"] == "ZERO_FIXTURE")
    failure = run_failure_rehearsal()
    zero_fixture_controls = run_zero_fixture_contract_controls(ROOT)
    semantic_diffs = {
        "ledger_semantic_diff": int(fixture_runs[0]["ledger_semantic_digest"] !=
                                    fixture_runs[1]["ledger_semantic_digest"]),
        "audit_root_diff": int(fixture_runs[0]["audit_root"] !=
                               fixture_runs[1]["audit_root"]),
        "gate_root_diff": int(fixture_runs[0]["gate_root"] !=
                              fixture_runs[1]["gate_root"]),
        "manifest_semantic_root_diff": int(
            fixture_runs[0]["manifest_roots"]["construction_semantic_root"] !=
            fixture_runs[1]["manifest_roots"]["construction_semantic_root"]),
        "seal_semantic_diff": int(fixture_runs[0]["seal_state"] !=
                                  fixture_runs[1]["seal_state"]),
        "receipt_semantic_diff": int(fixture_runs[0]["commitment_semantic"] !=
                                     fixture_runs[1]["commitment_semantic"]),
    }
    volatile_classification = {
        "construction_ledger_sha256": "VOLATILE_TIMESTAMP_BEARING",
        "construction_ledger_root": "VOLATILE_TIMESTAMP_BEARING",
        "seal_sha256": "VOLATILE_TIMESTAMP_BEARING",
        "commitment_root": "VOLATILE_TIMESTAMP_BEARING",
        "ledger_event_timestamps": "VOLATILE_TIMESTAMP_BEARING",
        "execution_checkout_commit": "VOLATILE_PUBLICATION_COMMIT_BOUND",
        "execution_checkout_tree": "VOLATILE_PUBLICATION_COMMIT_BOUND",
        "freeze_sha256": "VOLATILE_PUBLICATION_COMMIT_BOUND",
        "ledger_semantic_digest": "VOLATILE_PUBLICATION_COMMIT_BOUND",
        "construction_gate_root": "VOLATILE_PUBLICATION_COMMIT_BOUND",
        "private_manifest_sha256": "VOLATILE_TIMESTAMP_AND_PUBLICATION_COMMIT_BOUND",
        "construction_semantic_root": "VOLATILE_PUBLICATION_COMMIT_BOUND",
    }
    passed = (all(run["status"] == "SEALED" for run in runs)
              and all(run["gate_check_count"] == 24 for run in runs)
              and all(run["contract_leaf_total"] == 62 and
                      run["contract_leaf_pass_count"] == 62 and
                      run["contract_leaf_fail_count"] == 0 for run in runs)
              and all(run["store_verify"] == "PASS" and
                      run["publication_leak_gate"] == "PASS" for run in runs)
              and zero_fixture_run["fixture_count"] == 0
              and not any(semantic_diffs.values())
              and zero_fixture_controls["status"] == "PASS"
              and failure["status"] == "PASS")
    report = {"schema_version": "t26-construction-lifecycle-rehearsals-v2",
              "artifact": "T26_CONSTRUCTION_LIFECYCLE_REHEARSALS",
              "status": "PASS" if passed else "FAIL",
              "run_count": len(runs), "runs": runs,
              "fixture_bearing_lifecycle": {
                  "status": "PASS" if all(run["status"] == "SEALED"
                                            for run in fixture_runs) else "FAIL",
                  "run_count": len(fixture_runs)},
              "zero_fixture_lifecycle": {
                  "status": "PASS" if zero_fixture_run["status"] == "SEALED"
                            else "FAIL",
                  "run": zero_fixture_run["run"],
                  "fixture_count": zero_fixture_run["fixture_count"],
                  "ledger_state": zero_fixture_run["ledger_state"],
                  "ledger_event_count": zero_fixture_run["ledger_event_count"],
                  "contract_leaf_total": zero_fixture_run["contract_leaf_total"],
                  "contract_leaf_pass_count":
                      zero_fixture_run["contract_leaf_pass_count"],
                  "gate_check_count": zero_fixture_run["gate_check_count"],
                  "store_verify": zero_fixture_run["store_verify"],
                  "publication_leak_gate":
                      zero_fixture_run["publication_leak_gate"]},
              "zero_fixture_contract_controls": zero_fixture_controls,
              "failure_rehearsal": failure,
              "semantic_diffs": semantic_diffs,
              "volatile_classified_fields": volatile_classification,
              "real_blind_rows": 0, "real_construction_attempts": 0,
              "material": "DISPOSABLE_SYNTHETIC_PRIVATE"}
    if persist:
        _write(OUT / "construction_rehearsal_report.json", report)
    return report


def _construction_rehearsal_reproduction_view(value: dict) -> dict:
    """Remove only timestamp- or publication-commit-bound rehearsal fields.

    A report cannot commit a rehearsal that names the report's own eventual
    Git commit: publishing the report necessarily creates a new commit.  The
    listed derived roots therefore change once between the authoring checkout
    and the exact published checkout.  Their internal validity is enforced by
    the construction gate, store verification, and the zero-diff comparison
    between both runs; fresh reproduction compares the remaining semantics.
    """
    normalized = json.loads(json.dumps(value))
    for run in normalized.get("runs", []):
        for field in ("commitment_root", "execution_checkout_commit",
                      "execution_checkout_tree", "gate_root",
                      "ledger_semantic_digest"):
            run.pop(field, None)
        run.get("manifest_roots", {}).pop("construction_semantic_root", None)
        commitment = run.get("commitment_semantic", {})
        commitment.pop("construction_gate_root", None)
        commitment.pop("construction_ledger_root", None)
        commitment.pop("private_manifest_sha256", None)
        commitment.pop("freeze_sha256", None)
    return normalized


# T26_SCRIPT_PART_4


def finalize() -> dict:
    freeze_path = OUT / "preconstruction_freeze.json"
    # This command is also the public requalification path after an
    # infrastructure-only remediation.  Prior freezes remain immutable in Git
    # history; the current public artifact is replaced only with a newly
    # recomputed, still-non-authorizing freeze.
    frozen = build_freeze(ROOT)
    _write(freeze_path, frozen)
    doctor = run_doctor(ROOT)
    _write(OUT / "protocol_doctor_report.json", doctor)
    status = "PASS" if doctor["status"] == "PASS" else "FAIL"
    verdict = {
        "schema_version": "t26-preconstruction-verdict-v3",
        "artifact": "T26_PRECONSTRUCTION_VERDICT",
        "status": status,
        "verdict": "T26_INTEGRATED_INTERNAL_EXECUTION_PRECONSTRUCTION_PASS"
        if status == "PASS" else
        "T26_INTEGRATED_INTERNAL_EXECUTION_PRECONSTRUCTION_FAIL",
        "doctor_check_count": doctor["check_count"],
        "freeze_sha256": frozen["freeze_sha256"],
        "component_count": frozen["component_count"],
        "component_root": frozen["component_root"],
        "freeze_root": frozen["freeze_root"],
        "superseded_freeze_v1": OLD_FREEZE_V1,
        "superseded_freeze_v2": OLD_FREEZE_V2,
        "real_blind_rows": 0,
        "real_construction_attempts": 0,
        "real_evaluation_attempts": 0,
        "real_construction_ledger": "absent",
        "real_evaluation_ledger": "absent",
        "t25_private_rows_accessed": 0,
        "real_blind_construction_authorized": False,
        "external_action_authority": False,
    }
    _write(OUT / "T26_PRECONSTRUCTION_VERDICT.json", verdict)
    return verdict


def reproduce() -> dict:
    expected = {
        filename: json.loads((OUT / filename).read_text(encoding="utf-8"))
        for filename in ("qualification_report.json", "native_smoke_report.json",
                         "rehearsal_report.json",
                         "protection_report.json", "test_gate_report.json",
                         "construction_rehearsal_report.json",
                         "negative_gate_controls.json",
                         "historical_exclusions.json")}
    from t26_protocol.construction import (run_negative_gate_controls,
                                           protocol_hashes)
    actual = {"qualification_report.json": run_qualification(),
              "native_smoke_report.json": run_native_smoke(
                  ROOT, json.loads((OUT / "qualification_exclusions.json").read_text(encoding="utf-8"))),
              "rehearsal_report.json": run_rehearsals(),
              "protection_report.json": run_protection(ROOT),
              "test_gate_report.json": run_test_gate(ROOT),
              "construction_rehearsal_report.json":
                  build_construction_rehearsals(persist=False),
              "negative_gate_controls.json": run_negative_gate_controls(ROOT),
              "historical_exclusions.json": build_historical_exclusion_document(ROOT)}
    # The committed reports are JSON; a live rehearsal may hold tuple-valued
    # semantic trace entries that serialize as the same JSON arrays. Compare
    # the public artifact representation, not Python container identity.
    canonical = lambda value: json.dumps(value, sort_keys=True,
                                         separators=(",", ":"),
                                         ensure_ascii=False)
    drift = [name for name in expected if
             canonical(_construction_rehearsal_reproduction_view(expected[name])
                       if name == "construction_rehearsal_report.json"
                       else expected[name]) !=
             canonical(_construction_rehearsal_reproduction_view(actual[name])
                       if name == "construction_rehearsal_report.json"
                       else actual[name])]
    frozen = json.loads((OUT / "preconstruction_freeze.json").read_text(encoding="utf-8"))
    freeze_report = verify_freeze(ROOT, frozen)
    doctor = run_doctor(ROOT)
    identity_drift = []
    committed_hashes = json.loads(
        (OUT / "protocol_identity_hashes.json").read_text(encoding="utf-8"))
    if committed_hashes != protocol_hashes(ROOT):
        identity_drift.append("protocol_identity_hashes.json")
    candidate = json.loads(
        (OUT / "candidate_identity.json").read_text(encoding="utf-8"))
    if (candidate["candidate_commit"] != "6cb029c0f4edb4116c7f9a1f187cdc4671077a1f"
            or candidate["candidate_tree"] != "6199df3a4537e5af480098a4bd009c357ecc2910"
            or candidate["runtime_root"] !=
            "28f83990f5382400bac72cb34448ad5854c875d74655f1a571703f50d9cb453c"):
        identity_drift.append("candidate_identity.json")
    passed = (not drift and not identity_drift and
              freeze_report["status"] == doctor["status"] == "PASS")
    return {"schema_version": "t26-fresh-worktree-reproduction-v2",
            "artifact": "T26_FRESH_WORKTREE_REPRODUCTION",
            "status": "PASS" if passed else "FAIL",
            "drifted_artifacts": drift,
            "identity_drift": identity_drift,
            "freeze": freeze_report,
            "doctor_status": doctor["status"],
            "doctor_check_count": doctor["check_count"],
            "qualification_status": actual["qualification_report.json"]["status"],
            "native_smoke_status": actual["native_smoke_report.json"]["status"],
            "rehearsal_status": actual["rehearsal_report.json"]["status"],
            "construction_rehearsal_status":
                actual["construction_rehearsal_report.json"]["status"],
            "negative_controls_status":
                actual["negative_gate_controls.json"]["status"],
            "historical_exclusion_status":
                actual["historical_exclusions.json"].get("status", "PASS"),
            "protection_status": actual["protection_report.json"]["status"],
            "test_gate_status": actual["test_gate_report.json"]["status"],
            "candidate_commit": candidate["candidate_commit"],
            "public_blind_blob_count": doctor["checks"]["GIT_LEAK_SCAN"]["public_blind_blob_count"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("static", "protection", "tests",
                                          "infrastructure", "rehearsals",
                                          "finalize", "reproduce"))
    args = parser.parse_args()
    result = {"static": build_static, "protection": build_protection,
              "tests": build_test_gate,
              "infrastructure": build_construction_infrastructure,
              "rehearsals": build_construction_rehearsals,
              "finalize": finalize, "reproduce": reproduce}[args.phase]()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
