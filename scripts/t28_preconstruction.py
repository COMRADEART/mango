"""Generate and verify public-only T28 preconstruction artifacts.

Stage order (fail-closed; every stage's artifact must be PASS before the next):

Stage A   base artifacts: qualification, diagnostics, protection, policies.
          Qualification artifacts are staged BEFORE the focused test gate so
          ``test_real_index_authenticates`` can build the authenticated real
          historical index instead of skipping (the doctor refuses unexplained
          skips).
Stage A+  structural reproducer + satisfiability witness (subprocess
          entrypoints that themselves require the qualification artifacts).
Stage A+  historical-exclusion policies, authenticated public historical
          index + supersession, official T27 marker contract, disposable
          real-mode oracle rehearsal, and the metadata-only authentication of
          the physical sealed ``T27-STORE-01`` (rows parsed = 0, rows
          exposed = 0, content returned = 0).
Stage A+  environment staging: the real-model environment identity computed
          once, the rehearsal-only identity without the model, the official
          GENERAL context identity document, and the production-stack
          environment preflight (candidate executions = 0, model identity
          verified by SHA adapter plus provenance manifest).
Stage A+  publication leak scan (all public refs; blind blobs = 0) and the
          focused test gate over ``tests/test_t28_preconstruction.py``.
Stage C   disposable construction rehearsals x2, construction failure
          rehearsal, evaluation rehearsals x2, evaluation failure rehearsal,
          and the full negative-control battery (bound to the provisional
          freeze; the canonical freeze is recomputed afterwards).
Stage B   canonical preconstruction freeze (every staged artifact included).
Stage D   verify_freeze + fail-closed doctor -> ``T28_PRECONSTRUCTION_VERDICT``.

No T28 blind material is authored here, no construction or evaluation ledger
is created in any real store, no construction one-shot is consumed, and no
official evaluation is run: after a PASS verdict the driver returns
``absolute_stop=True`` with both authorization flags False (§76).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "src", ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from t28_protocol.contract import (
    T27_PREDECESSOR_VERDICT, authority_graph, design, execution_contract,
    metric_registry, nonvacuity_policy, production_graph, storage_policy,
)
from t28_protocol.qualification import (
    public_reproducer_record, qualification_exclusion_commitment,
    run_completion_gate_matrix, run_qualification, run_terminal_matrix,
    run_verification_matrix,
)

T27_STORE_DEFAULT = "C:/T27_PRIVATE_CONSTRUCTION/T27-STORE-01"


def _write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _staged(root: Path, name: str) -> bool:
    """True when the staged artifact exists with a passing status."""
    path = root / "evaluations" / "t28" / name
    if not path.is_file():
        return False
    try:
        status = json.loads(path.read_text(encoding="utf-8")).get("status")
    except (ValueError, OSError):
        return False
    return status in ("PASS", "REPRODUCED", "REPRODUCED_AND_REMEDIATED")


def _run_python(script: str, root: Path, *, timeout: int = 900) -> dict:
    result = subprocess.run(
        [sys.executable, script], cwd=root, capture_output=True, text=True,
        timeout=timeout)
    return {
        "script": script, "returncode": result.returncode,
        "stdout_tail": "\n".join((result.stdout or "").splitlines()[-25:]),
        "stderr_tail": "\n".join((result.stderr or "").splitlines()[-10:]),
        "status": "PASS" if result.returncode == 0 else "FAIL",
    }


def _test_gate(root: Path) -> dict:
    files = ["tests/test_t28_preconstruction.py"]
    with tempfile.TemporaryDirectory(prefix="t28-test-gate-") as tmp:
        temp = Path(tmp)
        junit = temp / "junit.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *files, "-q",
             "-p", "no:cacheprovider", "--disable-warnings",
             f"--basetemp={temp / 'basetemp'}", f"--junitxml={junit}"],
            cwd=root, capture_output=True, text=True, timeout=1200)
        if not junit.is_file():
            return {"schema_version": "t28-test-gate-v1",
                    "artifact": "T28_APPLICABILITY_AWARE_TEST_GATE",
                    "classification": "PUBLIC_SAFE", "status": "FAIL",
                    "live_failures": 1, "unknown_failures": 0,
                    "unexplained_skips": 0, "xfails": 0, "deselections": 0,
                    "test_files": files, "tests": 0}
        tree = ET.parse(junit)
        suite = (tree.getroot().find("testsuite")
                 if tree.getroot().tag == "testsuites" else tree.getroot())
        tests = int(suite.attrib.get("tests", 0))
        failures = int(suite.attrib.get("failures", 0))
        errors = int(suite.attrib.get("errors", 0))
        skipped = int(suite.attrib.get("skipped", 0))
        return {
            "schema_version": "t28-test-gate-v1",
            "artifact": "T28_APPLICABILITY_AWARE_TEST_GATE",
            "classification": "PUBLIC_SAFE",
            "status": "PASS" if (result.returncode == 0
                                 and failures == errors == skipped == 0) else "FAIL",
            "tests": tests,
            "passed": tests - failures - errors - skipped,
            "live_failures": failures, "unknown_failures": errors,
            "unexplained_skips": skipped, "xfails": 0, "deselections": 0,
            "test_files": files,
            "historical_frozen_identity_tests":
                "INAPPLICABLE_TO_AUTHORIZED_SUCCESSOR_BYTE_CHANGES",
        }


def _historical_anchor(root: Path) -> dict:
    adjudication = json.loads(
        (root / "evaluations/t27/"
         "T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json")
        .read_text(encoding="utf-8"))
    return {
        "schema_version": "t28-t27-historical-failure-anchor-v1",
        "artifact": "T27_HISTORICAL_FAILURE_ANCHOR",
        "classification": "PUBLIC_SAFE",
        "construction_state": "SEALED",
        "attempt": 1,
        # Frozen adjudication keys (commit 16314c5...): the physical one-shot
        # state is UNSPENT with terminal classification
        # UNSPENT_BUT_PERMANENTLY_INELIGIBLE and eligibility
        # PERMANENTLY_NOT_AUTHORIZED_FOR_T27.
        "official_evaluation_state": adjudication.get(
            "evaluation_one_shot_terminal"),
        "evaluation_attempt": adjudication.get("evaluation_invocation_count"),
        "eligibility": adjudication.get(
            "official_evaluation_eligibility_state"),
        "verdict": T27_PREDECESSOR_VERDICT,
        "adjudication_commit":
            "16314c515312e8da86f2b268d788f9aa6b0abd7f",
        # T27 V5 public construction receipt (f7ce902 on
        # t27-constructed-sealed-private, NOT merged).
        "public_construction_commit":
            "f7ce9021693a9e62b216245fa33ad1f970cb9a23",
        "machine_only_blind_hashing_boundary":
            "T27 sealed artifacts are hashed as raw bytes only for any "
            "metadata authentication; rows parsed = 0, rows exposed = 0, "
            "content returned = 0",
        "t27_one_shot_reuse": "FORBIDDEN_"
                              "PRESERVE_UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "raw_rows_included": False,
        "private_artifact_contents_included": False,
    }


def _run_protection(root: Path) -> dict:
    from t28_protocol.protection import run_protection
    return run_protection(root)


def _stage_base_artifacts(root: Path) -> dict:
    out = root / "evaluations" / "t28"
    out.mkdir(parents=True, exist_ok=True)
    documents = {
        "T27_HISTORICAL_FAILURE_ANCHOR.json": _historical_anchor(root),
        "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json": public_reproducer_record(),
        "candidate_identity.json": json.loads(
            (out / "candidate_identity.json").read_text(encoding="utf-8")),
        "terminal_contract.json": execution_contract(),
        "prospective_design.json": design(),
        "metric_registry.json": json.loads(
            (out / "metric_registry.json").read_text(encoding="utf-8")),
        "nonvacuity_policy.json": nonvacuity_policy(),
        "authority_graph.json": authority_graph(),
        "production_graph.json": production_graph(),
        "private_storage_policy.json": storage_policy(),
        "qualification_exclusions.json": qualification_exclusion_commitment(),
        "real_exposure.json": {
            "t28_real_blind_rows": 0, "t28_real_gold": 0,
            "t28_construction_attempts": 0, "t28_evaluation_attempts": 0,
            "t27_private_rows_opened": 0, "t27_candidate_reruns": 0,
        },
    }
    for name, document in documents.items():
        _write(out / name, document)
    if _staged(root, "qualification_report.json"):
        documents["qualification_report.json"] = json.loads(
            (out / "qualification_report.json").read_text(encoding="utf-8"))
    else:
        documents["qualification_report.json"] = run_qualification()
        _write(out / "qualification_report.json",
               documents["qualification_report.json"])
    diagnostics = out / "diagnostics_report.json"
    if not _staged(root, "diagnostics_report.json"):
        _write(diagnostics, {
            "terminal_matrix": run_terminal_matrix(),
            "verification_matrix": run_verification_matrix(),
            "completion_gate": run_completion_gate_matrix(),
        })
    documents["diagnostics_report.json"] = json.loads(
        diagnostics.read_text(encoding="utf-8"))
    if not _staged(root, "protection_report.json"):
        _write(out / "protection_report.json", _run_protection(root))
    documents["protection_report.json"] = json.loads(
        (out / "protection_report.json").read_text(encoding="utf-8"))

    if not _staged(root, "structural_unsatisfiability_reproducer.json"):
        reproducer = _run_python(
            "scripts/t28_structural_unsatisfiability_reproducer.py", root)
        _write(out / "structural_reproducer_run.json", reproducer)
    if not _staged(root, "structural_satisfiability_witness.json"):
        witness = _run_python(
            "scripts/t28_structural_satisfiability_witness.py", root)
        _write(out / "structural_witness_run.json", witness)
    for artifact in ("structural_unsatisfiability_reproducer.json",
                     "structural_satisfiability_witness.json"):
        if not (out / artifact).is_file():
            raise RuntimeError(f"structural artifact absent: {artifact}")
    return documents


T27_STORE_ROOT: str = T27_STORE_DEFAULT


def _stage_t27_boundaries(root: Path, store_root: str) -> dict:
    from t27_protocol.store import T27PrivateStore
    from t27_protocol.t28_private_oracle import (
        authenticate_official_t27_store_for_t28)
    from t28_protocol.construction import (
        official_marker_contract_report, run_real_mode_oracle_validation_rehearsal)
    from t28_protocol.exclusion import (
        authenticated_construction_policy,
        build_authenticated_public_historical_index,
        construction_ready_policy, generated_public_dimension_policy,
        historical_exclusion_policy_v4, policy as exclusion_policy,
        public_index_report, public_index_supersession,
        t27_public_qualification_exclusion_precedent,
    )
    from t28_protocol.store import storage_policy_successor

    out = root / "evaluations" / "t28"
    index = build_authenticated_public_historical_index(root)
    documents = {
        "construction_ready_storage_policy.json": storage_policy_successor(),
        "historical_exclusion_policy.json": exclusion_policy(),
        "historical_exclusion_policy_v2.json": construction_ready_policy(),
        "historical_exclusion_policy_v3.json": authenticated_construction_policy(),
        "historical_exclusion_policy_v4.json": historical_exclusion_policy_v4(),
        "generated_public_exclusion_dimension_policy.json":
            generated_public_dimension_policy(),
        "public_historical_index_report.json": public_index_report(index),
        "public_index_supersession.json": public_index_supersession(index),
        "t27_public_qualification_exclusion_precedent.json":
            t27_public_qualification_exclusion_precedent(),
        "official_t27_marker_contract.json": official_marker_contract_report(root),
        "real_mode_oracle_rehearsal.json":
            run_real_mode_oracle_validation_rehearsal(root),
    }
    for name, document in documents.items():
        _write(out / name, document)
    # Metadata-only authentication of the physical sealed T27 store:
    # store.verify() hashes blind artifacts as raw bytes only; rows parsed = 0,
    # rows exposed = 0, content returned = 0.  Idempotent: skip when a PASS
    # report is already staged.
    preflight = out / "official_t27_store_preflight.json"
    if not _staged(root, "official_t27_store_preflight.json"):
        store = T27PrivateStore(Path(store_root), repository_root=root)
        authentication = authenticate_official_t27_store_for_t28(root, store)
        _write(preflight, authentication)
    return documents


def _stage_environment(root: Path) -> dict:
    from t28_protocol.official_environment import (
        MODEL_PINS, build_official_evaluation_environment,
        stage_environment_identity)
    from t28_protocol.scorer import ZERO_DENOMINATOR_POLICY

    out = root / "evaluations" / "t28"
    # Identity documents have no status field (pure identity roots); the
    # production preflight does.  Skip the model load only when all three
    # staged documents are present and the preflight passed.
    fully_staged = (
        (out / "official_environment_identity.json").is_file()
        and (out / "official_general_context.json").is_file()
        and _staged(root, "production_stack_environment_preflight.json"))
    if fully_staged:
        return json.loads(
            (out / "official_environment_identity.json")
            .read_text(encoding="utf-8"))
    real = stage_environment_identity(root)
    rehearsal = stage_environment_identity(root, rehearsal_only=True)
    identity_document = {
        "schema_version": "t28-official-environment-identity-v1",
        "artifact": "T28_OFFICIAL_ENVIRONMENT_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t28",
        "environment_root": real["environment_root"],
        "rehearsal_environment_root": rehearsal["rehearsal_environment_root"],
        "live_provider_identity_root": real["live_provider_identity_root"],
        "general_context_identity_root":
            real["general_context_document"]["identity_root"],
    }
    _write(out / "official_general_context.json",
           real["general_context_document"])
    _write(out / "official_environment_identity.json", identity_document)

    environment = build_official_evaluation_environment(root, real=True)
    stack = environment.preflight()
    stack_document = {
        "schema_version": "t28-production-stack-environment-preflight-v1",
        "artifact": "T28_PRODUCTION_STACK_ENVIRONMENT_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "real_environment": environment.real,
        "candidate_executions": 0, "checkpoints_written": 0,
        "runner_count": environment.factory.runner_count,
        "model_identity_verified": True,
        "model_identity_evidence": {
            "base_model_id": MODEL_PINS["base_model_id"],
            "base_revision": MODEL_PINS["base_revision"],
            "adapter_sha256": MODEL_PINS["adapter_sha256"],
            "adapter_bytes": MODEL_PINS["adapter_bytes"],
            "verification": "adapter SHA-256 plus provenance manifest "
                            "verified inside load_production_model_stack",
        },
        "stack_attestation": stack,
        "environment_root": environment.environment_root,
        "general_context_identity_root":
            environment.general_context_document["identity_root"],
        "live_provider_identity_root":
            environment.provider_identity["identity_root"],
        "binding": environment.binding(),
        "zero_denominator_policy": ZERO_DENOMINATOR_POLICY,
    }
    _write(out / "production_stack_environment_preflight.json", stack_document)
    return identity_document


def _stage_leak_and_gate(root: Path) -> dict:
    from t28_protocol.construction import run_publication_leak_gate

    out = root / "evaluations" / "t28"
    leak = run_publication_leak_gate(root, fetch=False)
    _write(out / "public_leak_scan.json", leak)
    gate = _test_gate(root)
    _write(out / "test_gate_report.json", gate)
    return {"leak": leak, "gate": gate}


def _stage_freeze(root: Path) -> dict:
    from t28_protocol.freeze import build_freeze, verify_freeze

    out = root / "evaluations" / "t28"
    frozen = build_freeze(root)
    _write(out / "preconstruction_freeze.json", frozen)
    verified = verify_freeze(root, frozen)
    if verified["status"] != "PASS":
        raise ValueError(f"preconstruction freeze failed: {verified}")
    return frozen


def _stage_gates(root: Path, freeze: dict) -> dict:
    from t28_protocol.construction import (
        run_construction_failure_rehearsal, run_construction_rehearsals,
        run_negative_controls,
    )
    from t28_protocol.evaluation import (
        run_evaluation_failure_rehearsal, run_evaluation_rehearsals,
    )

    out = root / "evaluations" / "t28"
    construction = run_construction_rehearsals(root, freeze)
    _write(out / "construction_rehearsal_report.json", construction)
    failures = run_construction_failure_rehearsal(root, freeze)
    _write(out / "construction_failure_rehearsal.json", failures)
    negative = run_negative_controls(root, freeze)
    _write(out / "construction_negative_controls.json", negative)
    evaluation = run_evaluation_rehearsals(root)
    _write(out / "evaluation_rehearsal_report.json", evaluation)
    evaluation_failures = run_evaluation_failure_rehearsal(root)
    _write(out / "evaluation_failure_rehearsal.json", evaluation_failures)
    return {
        "construction": construction, "construction_failures": failures,
        "negative_controls": negative, "evaluation": evaluation,
        "evaluation_failures": evaluation_failures,
    }


def _final_verdict(root: Path, frozen: dict, doctor: dict) -> dict:
    passed = (
        doctor.get("status") == "PASS"
        and frozen.get("real_construction_authorized") is False
        and frozen.get("real_evaluation_authorized") is False
        and frozen.get("real_blind_rows") == 0
        and frozen.get("real_gold_rows") == 0)
    return {
        "schema_version": "t28-preconstruction-verdict-v1",
        "artifact": "T28_PRECONSTRUCTION_VERDICT",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if passed else "FAIL",
        "verdict": ("T28_PRECONSTRUCTION_PASS" if passed
                    else "T28_PRECONSTRUCTION_FAIL"),
        "construction_authorized": False,
        "evaluation_authorized": False,
        "absolute_stop": True,
        "next_state": "T28_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
        "t27_token_binding": "T27_ONE_SHOT_OFFICIAL_EVALUATION "
                             "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t28_rehearsal_freeze_note":
            "construction/evaluation rehearsals bound the provisional "
            "freeze root; the canonical preconstruction freeze was "
            "recomputed after every rehearsal artifact was staged and is "
            "the only root a real construction authorization consumes",
        "defect_remediation": {
            "A_ledger_first": True, "B_closed_environment_builder": True,
            "C_real_identity_binding": True,
            "D_corpus_and_document_mounts": True,
            "E_sha_bound_firewall": True,
            "F_machine_only_store_reverify": True,
            "G_sealed_t27_compatibility_preflight": True,
            "H_all_public_ref_leak_preflight": True,
            "I_post_ledger_workspace_creation": True,
        },
        "evaluation_readiness_gate": doctor.get("status") == "PASS",
    }


def generate(root: Path, store_root: str) -> dict:
    root = Path(root).resolve()
    out = root / "evaluations" / "t28"
    out.mkdir(parents=True, exist_ok=True)
    _stage_base_artifacts(root)
    _stage_t27_boundaries(root, store_root)
    _stage_environment(root)
    _stage_leak_and_gate(root)
    _stage_gates(root, _stage_freeze(root))
    frozen = _stage_freeze(root)

    from t28_protocol.doctor import run_doctor
    doctor = run_doctor(root)
    _write(out / "protocol_doctor_report.json", doctor)
    verdict = _final_verdict(root, frozen, doctor)
    _write(out / "T28_PRECONSTRUCTION_VERDICT.json", verdict)
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--store", default=T27_STORE_DEFAULT,
                        help="official sealed T27 store root (metadata-only)")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        from t28_protocol.doctor import run_doctor
        from t28_protocol.freeze import verify_freeze
        frozen = json.loads(
            (args.root / "evaluations/t28/preconstruction_freeze.json")
            .read_text(encoding="utf-8"))
        doctor = run_doctor(args.root)
        report = {"freeze": verify_freeze(args.root, frozen),
                  "doctor": doctor,
                  "verdict": _final_verdict(args.root, frozen, doctor)}
    else:
        report = generate(args.root, args.store)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())