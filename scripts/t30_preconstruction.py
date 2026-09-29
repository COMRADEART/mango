"""T30 successor preconstruction driver (T30 authorization §12–§49).

Fail-closed stage order:

  A   T29 predecessor-status record (§1/§6/§11/§12; adjudication cc60c49)
  B   base artifacts (design / storage / qualifications / protection /
      real-exposure / T28 + T29 public root-cause reproducers)
  S   successor evidence (§18–§25/§32): actual T28 journal positive control,
      frozen-lifecycle T28 stand-in schema equivalence, journal negative
      controls, T27 metadata-only positive control, T29 abandonment
      commitment / oracle requirement / readiness
  C   T30 boundaries (exclusion policy ladder, authenticated public
      historical index, T27 marker contract, predecessor-oracle rehearsal)
  D   REAL official environment (candidate executions = 0)
  E   readiness evidence -> preconstruction contract -> readiness gate
  F   provisional freeze at the canonical path
  G   publication leak scan + test gate
  H   construction suites bound to the live canonical freeze
  I   OFFICIAL freeze regenerated after every artifact was staged
  J   fail-closed doctor, verdict, report

Private predecessor locations are supplied ONLY through the environment
(T30_T27_STORE, T30_T28_STORE, T30_T29_PACKAGE); no private path is written
into any staged artifact.  ABSOLUTE STOP (§49): no T30 real blind rows, no
real gold, no real predecessor oracle invocation, no T30 construction ledger,
no official evaluation.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT_DEFAULT = Path(__file__).resolve().parents[1]

T29_ADJUDICATION_COMMIT = "cc60c49"
T29_PREDECESSOR_STATUS_RECORD = {
    "schema_version": "t30-t29-predecessor-status-v1",
    "artifact": "T30_T29_PREDECESSOR_STATUS",
    "classification": "PUBLIC_SAFE",
    "t29_terminal": ("T29_REAL_PACKAGE_AUTHORED_BUT_CONSTRUCTION_PERMANENTLY_"
                     "INELIGIBLE_DUE_TO_FROZEN_T28_ACCESS_JOURNAL_SCHEMA_DEFECT"),
    "t29_refusal": ("T29_REAL_CONSTRUCTION_REFUSED_FROZEN_T28_ORACLE_REJECTS_"
                    "OFFICIAL_T28_ACCESS_JOURNAL"),
    "root_cause": "FROZEN_T28_ACCESS_JOURNAL_SCHEMA_COMPATIBILITY_DEFECT",
    "construction_one_shot": "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
    "construction_one_shot_physical_state": "UNSPENT",
    "real_construction_eligibility": "PERMANENTLY_INELIGIBLE",
    "capability_verdict": "NOT_MEASURED",
    "sealed_holdout": False,
    "t29_construction_ledger": "ABSENT", "t29_construction_marker": "ABSENT",
    "t29_real_oracle_invocations": {"t27": 0, "t28": 0},
    "t29_construct_real_invocations": 0,
    "t29_preconstruction_freeze_sha256":
        "85d4f923249a9af41f796177df3ab6c0200a958b146e02b58a8c029cdda45158",
    "t29_preconstruction_tip": "0e74648f58c59d8a05f425282942ae1009dfe58d",
    "t29_adjudication_path":
        "evaluations/t29/T29_REAL_CONSTRUCTION_ELIGIBILITY_ADJUDICATION.json",
    "t29_token_reuse_forbidden":
        "T29_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
    "t29_protocol_repair_forbidden": True,
    "t29_package_reuse_forbidden": True,
    "candidate_unchanged": {
        "candidate_commit": "11d76c6392ec1f3d08840cfca641618ca61d9247",
        "candidate_tree": "1b1a0296232d1b89f94d95902dbce515f59bb266",
        "runtime_root":
            "c55da12937ed4bce5df0f0ad3692a85c0ae323278a5bacd5610fdf87f258a44d",
        "candidate_runtime_changes": 0,
    },
    "historical_rewrite_of_predecessor": False,
}


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n", encoding="utf-8")


def _read_staged(root: Path, name: str) -> dict:
    return json.loads(
        (root / "evaluations" / "t30" / name).read_text(encoding="utf-8"))


def _staged(root: Path, name: str) -> bool:
    """True when the staged artifact exists with a passing status."""
    path = root / "evaluations" / "t30" / name
    if not path.is_file():
        return False
    try:
        status = json.loads(path.read_text(encoding="utf-8")).get("status")
    except (ValueError, OSError):
        return False
    return status in ("PASS", "REPRODUCED", "REPRODUCED_AND_REMEDIATED")


# ---------------------------------------------------------------------------
# Stage A: T29 predecessor-status record (§12)
# ---------------------------------------------------------------------------


def _stage_t29_predecessor_status(root: Path) -> dict:
    from t30_protocol.freeze import T29_PREDECESSOR_STATUS_PATH
    path = root / T29_PREDECESSOR_STATUS_PATH
    adjudication = json.loads(
        (root / T29_PREDECESSOR_STATUS_RECORD["t29_adjudication_path"])
        .read_text(encoding="utf-8"))
    record = {**T29_PREDECESSOR_STATUS_RECORD,
              "t29_adjudication_root": adjudication["adjudication_root"]}
    if adjudication.get("terminal") != record["t29_terminal"]:
        raise RuntimeError("T29 adjudication terminal mismatch")
    _write(path, record)
    return record


# ---------------------------------------------------------------------------
# Stage S: successor evidence (§18–§25, §32)
# ---------------------------------------------------------------------------


def _private_location(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must name the private location "
                           "(environment only; never staged)")
    path = Path(value)
    if not path.exists():
        raise RuntimeError(f"{name} does not exist")
    return path


def _stage_successor_evidence(root: Path) -> dict:
    from t27_protocol.store import T27PrivateStore
    from t27_protocol.t28_private_oracle import (
        authenticate_official_t27_store_for_t28,
        validate_t27_store_authentication_evidence)
    from t30_protocol.abandonment import (abandonment_oracle_requirement,
                                          official_abandonment_readiness,
                                          t29_abandonment_commitment)
    from t30_protocol.oracle import build_t28_journal_evidence

    out = root / "evaluations" / "t30"
    journal = build_t28_journal_evidence(root, _private_location("T30_T28_STORE"))
    t27_store = T27PrivateStore(_private_location("T30_T27_STORE"),
                                repository_root=root)
    t27 = authenticate_official_t27_store_for_t28(root, t27_store, expected=None)
    validate_t27_store_authentication_evidence(t27, real=True)
    t27_document = {
        "schema_version": "t30-t27-metadata-authentication-v1",
        "artifact": "T30_T27_METADATA_AUTHENTICATION",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if t27.get("t27_store_authenticated") is True
        and t27.get("t27_official_commitments_exact") is True else "FAIL",
        **{key: value for key, value in sorted(t27.items())
           if key.startswith("t27_") and isinstance(value, (bool, int, str))
           and not key.endswith("_path")},
        "t27_oracle_executed": False,
    }
    documents = {
        "t28_journal_compatibility.json": journal["official"],
        "t28_journal_schema_equivalence.json": journal["equivalence"],
        "t28_journal_negative_controls.json": journal["negative_controls"],
        "t27_metadata_authentication.json": t27_document,
        "t29_abandonment_commitment.json": t29_abandonment_commitment(root),
        "t29_abandonment_oracle_requirement.json":
            abandonment_oracle_requirement(),
        "t29_abandonment_readiness.json": official_abandonment_readiness(
            root, _private_location("T30_T29_PACKAGE")),
    }
    for name, document in documents.items():
        _write(out / name, document)
    failed = [name for name, document in documents.items()
              if document.get("status", "PASS") != "PASS"
              and document.get("SCHEMA_EQUIVALENT") is not True]
    if failed or t27_document.get("t27_private_rows_read", 1) != 0:
        raise RuntimeError("T30 successor evidence not green: " + str(failed))
    return documents


# ---------------------------------------------------------------------------
# Stage B: base artifacts (§5–§7, §41)
# ---------------------------------------------------------------------------


def _stage_base_artifacts(root: Path) -> dict:
    from t30_protocol.contract import (authority_graph, design,
                                       execution_contract, metric_registry,
                                       nonvacuity_policy, production_graph,
                                       storage_policy)
    from t30_protocol.protection import run_protection
    from t30_protocol.qualification import qualification_exclusion_commitment

    from t30_protocol.freeze import build_candidate_identity

    out = root / "evaluations" / "t30"
    out.mkdir(parents=True, exist_ok=True)
    documents = {
        "candidate_identity.json":
            build_candidate_identity(root),
        "terminal_contract.json": execution_contract(),
        "prospective_design.json": design(),
        "metric_registry.json": metric_registry(),
        "nonvacuity_policy.json": nonvacuity_policy(),
        "authority_graph.json": authority_graph(),
        "production_graph.json": production_graph(),
        "private_storage_policy.json": storage_policy(),
        "qualification_exclusions.json": qualification_exclusion_commitment(),
        "real_exposure.json": {
            "t30_real_blind_rows": 0, "t30_real_gold": 0,
            "t30_construction_attempts": 0, "t30_evaluation_attempts": 0,
            "t27_private_rows_opened": 0, "t27_candidate_reruns": 0,
        },
        # §41/§45: the T27 historical failure anchor replaced by the driver
        # (the stand-in staged by stage_official_documents is superseded);
        # identity keys are bound live, never copied from a placeholder.
        "T27_HISTORICAL_FAILURE_ANCHOR.json": _historical_anchor(root),
    }
    for name, document in documents.items():
        _write(out / name, document)
    # Structural reproducer/witness + T28 public root-cause reproducer: run
    # the fail-closed reproducers fresh on every driver pass (they are the
    # §52 T28-DEFECT-REPRODUCER section's live evidence; never mutated).
    _reproduce_t28_defect(root)
    # Official historical anchors (T27/T28), producer-serialized, staged
    # write-if-absent exactly as stage_official_documents would.
    from t30_protocol.evaluation import (_canonical_bytes,
                                         _official_anchor_document)
    for predecessor in ("t27", "t28"):
        target = out / f"historical_anchor_{predecessor}.json"
        if not target.is_file():
            target.write_bytes(_canonical_bytes(
                _official_anchor_document(root, predecessor)))
    if not _staged(root, "qualification_report.json"):
        from t30_protocol.qualification import run_qualification
        _write(out / "qualification_report.json", run_qualification())
    documents["qualification_report.json"] = _read_staged(
        root, "qualification_report.json")
    if not _staged(root, "diagnostics_report.json"):
        from t30_protocol.qualification import (
            run_completion_gate_matrix, run_terminal_matrix,
            run_verification_matrix)
        _write(root / "evaluations" / "t30" / "diagnostics_report.json", {
            "terminal_matrix": run_terminal_matrix(),
            "verification_matrix": run_verification_matrix(),
            "completion_gate": run_completion_gate_matrix(),
        })
    documents["diagnostics_report.json"] = _read_staged(
        root, "diagnostics_report.json")
    if not _staged(root, "protection_report.json"):
        _write(root / "evaluations" / "t30" / "protection_report.json",
               run_protection(root))
    documents["protection_report.json"] = _read_staged(
        root, "protection_report.json")
    return documents


def _historical_anchor(root: Path) -> dict:
    """§41/§45: the T27 historical failure anchor, bound live to the frozen
    T27 official evaluation eligibility adjudication (commit 16314c5…) —
    construction SEALED/1, official evaluation UNSPENT_BUT_PERMANENTLY_
    INELIGIBLE (attempt 0), permanent T27 ineligibility, zero rows opened."""
    from t30_protocol.contract import (
        T27_CONSTRUCTION_ATTEMPT, T27_CONSTRUCTION_STATE,
        T27_OFFICIAL_EVALUATION_ATTEMPT, T27_OFFICIAL_EVALUATION_ELIGIBILITY,
        T27_OFFICIAL_EVALUATION_STATE, T27_PREDECESSOR_VERDICT)
    from t30_protocol.freeze import T27_ADJUDICATION_COMMIT

    adjudication = json.loads(
        (root / "evaluations/t27/"
         "T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json")
        .read_text(encoding="utf-8"))
    return {
        "schema_version": "t30-t27-historical-failure-anchor-v1",
        "artifact": "T27_HISTORICAL_FAILURE_ANCHOR",
        "classification": "PUBLIC_SAFE",
        "construction_state": T27_CONSTRUCTION_STATE,
        "attempt": T27_CONSTRUCTION_ATTEMPT,
        "official_evaluation_state": adjudication.get(
            "evaluation_one_shot_terminal"),
        "evaluation_attempt": adjudication.get("evaluation_invocation_count"),
        "eligibility": adjudication.get(
            "official_evaluation_eligibility_state"),
        "verdict": T27_PREDECESSOR_VERDICT,
        "adjudication_commit": T27_ADJUDICATION_COMMIT,
        "public_construction_commit": adjudication.get(
            "public_construction", {}).get("commit"),
        "machine_only_blind_hashing_boundary":
            "T27 sealed artifacts are hashed as raw bytes only for any "
            "metadata authentication; rows parsed = 0, rows exposed = 0, "
            "content returned = 0",
        "t27_one_shot_reuse":
            "FORBIDDEN_PRESERVE_UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "raw_rows_included": False,
        "private_artifact_contents_included": False,
        "frozen_official_evaluation_state": T27_OFFICIAL_EVALUATION_STATE,
        "frozen_official_evaluation_attempt": T27_OFFICIAL_EVALUATION_ATTEMPT,
        "frozen_official_evaluation_eligibility":
            T27_OFFICIAL_EVALUATION_ELIGIBILITY,
        "t28_token_binding": (
            "T28_ONE_SHOT_OFFICIAL_EVALUATION is superseded by "
            "UNSPENT_BUT_PERMANENTLY_INELIGIBLE and is never reused"),
    }


def _run_protection(root: Path) -> dict:
    from t30_protocol.protection import run_protection
    return run_protection(root)


def _reproduce_t28_defect(root: Path) -> None:
    """§52 T28-DEFECT-REPRODUCER: idempotent re-run of the sealed reproducer."""
    from t30_protocol.defect_reproducer import run_t28_preflight_defect_reproducer
    out = root / "evaluations" / "t30"
    if not _staged(root, "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json"):
        _write(out / "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json",
               run_t28_preflight_defect_reproducer(root))
    from t30_protocol.defect_reproducer import run_t29_journal_defect_reproducer
    if not _staged(root, "T29_PUBLIC_ROOT_CAUSE_REPRODUCTION.json"):
        _write(out / "T29_PUBLIC_ROOT_CAUSE_REPRODUCTION.json",
               run_t29_journal_defect_reproducer(root))


# ---------------------------------------------------------------------------
# Stage C: T30 boundaries (§8–§12, §28, §29)
# ---------------------------------------------------------------------------


def _stage_t30_boundaries(root: Path) -> dict:
    from t30_protocol.construction import (
        official_marker_contract_report, run_real_mode_oracle_validation_rehearsal)
    from t30_protocol.exclusion import (
        authenticated_construction_policy,
        build_authenticated_public_historical_index,
        construction_ready_policy, generated_public_dimension_policy,
        historical_exclusion_policy_v4, policy as exclusion_policy,
        public_index_report, public_index_supersession,
        t27_public_qualification_exclusion_precedent,
    )
    from t30_protocol.store import storage_policy_successor

    out = root / "evaluations" / "t30"
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
        "real_mode_oracle_evidence.json":
            run_real_mode_oracle_validation_rehearsal(root),
    }
    for name, document in documents.items():
        _write(out / name, document)
    return documents


# ---------------------------------------------------------------------------
# Stage D: REAL official environment (§26/§27) — see drive_environment
# ---------------------------------------------------------------------------


def _stage_environment(root: Path) -> dict:
    """Idempotent REAL staging; skips the model load when fully staged."""
    out = root / "evaluations" / "t30"
    if ((out / "official_environment_identity.json").is_file()
            and (out / "official_general_context.json").is_file()
            and _staged(root, "production_stack_environment_preflight.json")):
        return _read_staged(root, "official_environment_identity.json")
    import os
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from t30_protocol.official_environment import (
        MODEL_PINS, build_official_evaluation_environment,
        stage_environment_identity)
    from t30_protocol.scorer import ZERO_DENOMINATOR_POLICY
    from t30_protocol.evaluation import run_model_hydration_preflight

    real = stage_environment_identity(root)
    rehearsal = stage_environment_identity(root, rehearsal_only=True)
    identity_document = {
        "schema_version": "t30-official-environment-identity-v1",
        "artifact": "T30_OFFICIAL_ENVIRONMENT_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t30",
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
        "schema_version": "t30-production-stack-environment-preflight-v1",
        "artifact": "T30_PRODUCTION_STACK_ENVIRONMENT_PREFLIGHT",
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
        "model_stack_loadable": True,
        "stack_attestation": stack,
        "environment_root": environment.environment_root,
        "general_context_identity_root":
            environment.general_context_document["identity_root"],
        "live_provider_identity_root":
            environment.provider_identity["identity_root"],
        "binding": environment.binding(),
        "zero_denominator_policy": ZERO_DENOMINATOR_POLICY,
        "t27_private_rows_read": 0, "t28_private_material_parsed": False,
        "real_blind_rows": 0, "hydration_tested_pre_ledger": True,
        "hydration_preflight": run_model_hydration_preflight(root, mode="REAL"),
    }
    _write(out / "production_stack_environment_preflight.json", stack_document)
    return identity_document


# ---------------------------------------------------------------------------
# Stage R: recovery-reachability remediation evidence (pre-exposure)
# ---------------------------------------------------------------------------


RECOVERY_REMEDIATION_STATIC = (
    "T30_REAL_CONSTRUCTION_REFUSAL_RECOVERY_REACHABILITY.json",
    "T30_OLD_STACK_RECOVERY_REACHABILITY_REPRODUCER.json",
    "preconstruction_freeze_superseded_pre_exposure.json",
    "T30_RECOVERY_REACHABILITY_REMEDIATION_LIFECYCLE.json",
)


def _stage_recovery_remediation(root: Path) -> dict:
    """Recovery-control policy, adapter identity, REAL-stack nonvacuity
    reachability gate and recovery-control negative controls.  Runs after
    the environment identity is staged (the reachability gate drives the
    frozen official factory) and before any freeze/rehearsal consumes it.
    Disposable synthetic material only; no real row, gold or control."""
    from t30_protocol.reachability import (
        run_real_stack_nonvacuity_reachability,
        run_recovery_control_negative_controls)
    from t30_protocol.recovery_control import (adapter_identity_report,
                                               recovery_control_policy)

    out = root / "evaluations" / "t30"
    for name in RECOVERY_REMEDIATION_STATIC:
        if not (out / name).is_file():
            raise RuntimeError(f"T30 remediation record absent: {name}")
    documents = {
        "recovery_control_policy.json": recovery_control_policy(),
        "adapter_identity.json": adapter_identity_report(root),
        "nonvacuity_reachability_gate.json":
            run_real_stack_nonvacuity_reachability(root),
        "recovery_control_negative_controls.json":
            run_recovery_control_negative_controls(root),
    }
    expected = {"recovery_control_policy.json": ("classification", "PUBLIC_SAFE"),
                "adapter_identity.json": ("status", "PASS"),
                "nonvacuity_reachability_gate.json": ("status", "GATE_GREEN"),
                "recovery_control_negative_controls.json": ("status", "PASS")}
    for name, document in documents.items():
        _write(out / name, document)
        key, value = expected[name]
        if document.get(key) != value:
            raise RuntimeError(f"T30 recovery remediation evidence not green: "
                               f"{name}: " + json.dumps(
                                   {k: document.get(k) for k in (
                                       "status", "failed_checks",
                                       "failed_controls")}, sort_keys=True))
    return documents


# ---------------------------------------------------------------------------
# Stage E: provisional freeze + readiness evidence + contract + readiness gate
# ---------------------------------------------------------------------------


def _stage_provisional_freeze(root: Path) -> dict:
    """Stage the provisional freeze at the canonical path (an EXCLUDED
    self-referent): the canonical loader consumed by the real entrypoint
    requires it.  Recomputed deterministically at Stage I."""
    from t30_protocol.freeze import build_freeze, T30_PRECONSTRUCTION_FREEZE_PATH
    freeze_path = root / T30_PRECONSTRUCTION_FREEZE_PATH
    freeze = build_freeze(root)
    if not freeze_path.is_file() or json.loads(
            freeze_path.read_text(encoding="utf-8")) != freeze:
        freeze_path.parent.mkdir(parents=True, exist_ok=True)
        freeze_path.write_text(
            json.dumps(freeze, sort_keys=True, indent=2, ensure_ascii=False)
            + "\n", encoding="utf-8")
        return {"staged": True}
    return {"staged": False}


def _stage_readiness(root: Path) -> dict:
    from t30_protocol.evaluation import (
        run_evaluation_readiness_gate, run_preconstruction_contract_audit,
        stage_readiness_evidence)

    result_evidence = stage_readiness_evidence(root)
    staged_paths = sorted(result_evidence.get("staged_paths", []))
    contract = run_preconstruction_contract_audit(root)
    _write(root / "evaluations" / "t30" / "preconstruction_contract.json",
           contract)
    if contract.get("status") != "PASS":
        raise RuntimeError("T30 preconstruction contract audit: "
                           + str(contract.get("status")))
    gate = run_evaluation_readiness_gate(root)
    _write(root / "evaluations" / "t30" / "evaluation_readiness_gate.json", gate)
    return {"evidence": staged_paths, "contract": contract, "gate": gate}


# ---------------------------------------------------------------------------
# Stage G: publication leak scan + applicability-aware test gate (§46)
# ---------------------------------------------------------------------------


def _test_gate(root: Path) -> dict:
    files = sorted(
        path.as_posix()
        for path in (root / "tests").glob("test_t30*.py"))
    if not files:
        raise RuntimeError(
            "no tests/test_t30*.py test files staged for the §46 gate")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t30-test-gate-") as tmp:
        temp = Path(tmp)
        junit = temp / "junit.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *files, "-q",
             "-p", "no:cacheprovider", "--disable-warnings",
             f"--basetemp={temp / 'basetemp'}", f"--junitxml={junit}"],
            cwd=root, capture_output=True, text=True, timeout=2400,
            env={**os.environ.copy(), "PYTHONIOENCODING": "utf-8",
                 "PYTHONPATH": os.pathsep.join(
                     [str(root / "src"), str(root)])})
        if not junit.is_file():
            return {"schema_version": "t30-test-gate-v1",
                    "artifact": "T30_APPLICABILITY_AWARE_TEST_GATE",
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
            "schema_version": "t30-test-gate-v1",
            "artifact": "T30_APPLICABILITY_AWARE_TEST_GATE",
            "classification": "PUBLIC_SAFE",
            "status": "PASS" if (result.returncode == 0
                                 and failures == errors == skipped == 0
                                 ) else "FAIL",
            "tests": tests,
            "passed": tests - failures - errors - skipped,
            "live_failures": failures, "unknown_failures": errors,
            "unexplained_skips": skipped, "xfails": 0, "deselections": 0,
            "test_files": files,
            "historical_frozen_identity_tests":
                "INAPPLICABLE_TO_AUTHORIZED_SUCCESSOR_BYTE_CHANGES",
        }


def _stage_leak_and_gate(root: Path) -> dict:
    from t30_protocol.construction import run_publication_leak_gate

    out = root / "evaluations" / "t30"
    leak = run_publication_leak_gate(root, fetch=False)
    _write(out / "public_leak_scan.json", leak)
    gate = _test_gate(root)
    _write(out / "test_gate_report.json", gate)
    if gate.get("status") != "PASS":
        raise RuntimeError("T30 §46 test gate not green: "
                           + json.dumps({k: gate[k] for k in (
                               "status", "tests", "live_failures",
                               "unknown_failures", "unexplained_skips",
                               "xfails", "deselections")}, sort_keys=True))
    if leak.get("status") != "PASS":
        raise RuntimeError("T30 publication leak gate not green: "
                           + str(leak)[:400])
    return {"leak": leak, "gate": gate}


# ---------------------------------------------------------------------------
# Stage H: construction suites (§43–§46) — bound to the live canonical freeze
# ---------------------------------------------------------------------------


def _stage_construction_suites(root: Path, freeze: dict) -> dict:
    from t30_protocol.construction import (
        run_construction_failure_rehearsal, run_construction_rehearsals,
        run_freeze_path_negative_controls, run_generated_public_policy_controls,
        run_negative_controls, run_t27_marker_layout_negative_controls,
    )

    out = root / "evaluations" / "t30"
    documents = {
        "construction_rehearsal_report.json":
            run_construction_rehearsals(root, freeze),
        "construction_failure_rehearsal.json":
            run_construction_failure_rehearsal(root, freeze),
        "construction_negative_controls.json":
            run_negative_controls(root, freeze),
        "generated_public_policy_controls.json":
            run_generated_public_policy_controls(root),
        "t27_marker_layout_negative_controls.json":
            run_t27_marker_layout_negative_controls(root),
        "freeze_path_negative_controls.json":
            run_freeze_path_negative_controls(root),
    }
    for name, document in documents.items():
        _write(out / name, document)
        if name in ("generated_public_policy_controls.json",
                    "t27_marker_layout_negative_controls.json"):
            # Bare controls maps (control name -> control verdict); every
            # control verdict must be a PASS with refused=True.
            if not document or any(
                    not isinstance(item, dict)
                    or item.get("status") != "PASS"
                    or item.get("refused") is not True
                    for item in document.values()):
                raise RuntimeError(f"T30 construction suite failed: {name}: "
                                   + json.dumps(document, sort_keys=True)[:400])
        elif document.get("status") != "PASS":
            raise RuntimeError(
                f"T30 construction suite failed: {name}: "
                + str(document.get("refusal") or document.get("summary"))[:300])
    return documents


# ---------------------------------------------------------------------------
# Stage I: canonical freeze (§47/§48) — regenerated LAST, with zero real flags
# ---------------------------------------------------------------------------


def _stage_freeze(root: Path) -> dict:
    from t30_protocol.freeze import build_freeze, verify_freeze

    out = root / "evaluations" / "t30"
    frozen = build_freeze(root)
    _write(out / "preconstruction_freeze.json", frozen)
    verified = verify_freeze(root, frozen)
    if verified["status"] != "PASS":
        raise ValueError(f"preconstruction freeze failed: {verified}")
    flags_ok = (
        frozen.get("real_construction_authorized") is False
        and frozen.get("real_evaluation_authorized") is False
        and frozen.get("real_blind_rows") == 0
        and frozen.get("real_gold_rows") == 0
        and frozen.get("real_construction_attempts") == 0
        and frozen.get("real_evaluation_attempts") == 0)
    if not flags_ok:
        raise ValueError("T30 §48 freeze flags violated: "
                         + json.dumps({key: frozen.get(key) for key in (
                             "real_construction_authorized",
                             "real_evaluation_authorized", "real_blind_rows",
                             "real_gold_rows", "real_construction_attempts",
                             "real_evaluation_attempts")}, sort_keys=True))
    return frozen


# ---------------------------------------------------------------------------
# Stage J: fail-closed doctor (§45) + §53 verdict + §52 report
# ---------------------------------------------------------------------------


def _final_verdict(root: Path, frozen: dict, doctor: dict) -> dict:
    passed = (
        doctor.get("status") == "PASS"
        and frozen.get("real_construction_authorized") is False
        and frozen.get("real_evaluation_authorized") is False
        and frozen.get("real_blind_rows") == 0
        and frozen.get("real_gold_rows") == 0)
    return {
        "schema_version": "t30-preconstruction-verdict-v1",
        "artifact": "T30_PRECONSTRUCTION_VERDICT",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if passed else "FAIL",
        "verdict": ("T30_PRECONSTRUCTION_PASS" if passed
                    else "T30_PRECONSTRUCTION_FAIL"),
        "construction_authorized": False,
        "evaluation_authorized": False,
        "absolute_stop": True,
        "next_state": "T30_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
        "t27_token_binding": "T27_ONE_SHOT_OFFICIAL_EVALUATION "
                             "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t28_token_binding": "T28_ONE_SHOT_OFFICIAL_EVALUATION "
                             "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t29_terminal": T29_PREDECESSOR_STATUS_RECORD["t29_terminal"],
        "t29_token_binding": "T29_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION "
                             "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t30_construction_one_shot": "UNSPENT",
        "t30_evaluation_one_shot": "NOT_YET_AUTHORIZED",
        "remediation_verdict": (
            "T30_PRE_EXPOSURE_RECOVERY_REACHABILITY_REMEDIATION_PASS" if passed
            else "T30_PRE_EXPOSURE_RECOVERY_REACHABILITY_REMEDIATION_FAIL"),
        "superseded_freeze_sha256":
            "96e3ee5e12ffa8b7e5c3e6dd01dfe19ecfc4bd5ead1cb740a66f46080fb616ce",
        "prior_construction_authorization": "WITHDRAWN_NOT_USABLE",
        "rehearsal_freeze_note":
            "construction/evaluation rehearsals bound the provisional "
            "freeze root; the canonical preconstruction freeze was "
            "recomputed after every artifact was staged and is the only "
            "root a real construction authorization consumes",
    }


def _preconstruction_report(root: Path, frozen: dict, doctor: dict,
                            verdict: dict) -> dict:
    """§52 machine-readable report; RETURNED (printed) at the end of the
    pass, never staged (the freeze identity it embeds must not become a
    freeze component — self-reference non-convergence)."""
    from t30_protocol.contract import (CRITICAL_COUNTERS,
                                       T27_PREDECESSOR_VERDICT,
                                       T28_PREDECESSOR_VERDICT)
    out = root / "evaluations" / "t30"

    def _read(name: str) -> dict:
        return json.loads((out / name).read_text(encoding="utf-8"))

    contract = _read("preconstruction_contract.json")
    gate = _read("evaluation_readiness_gate.json")
    exposure = _read("real_exposure.json")
    identity = _read("official_environment_identity.json")
    stack = _read("production_stack_environment_preflight.json")
    test_gate = _read("test_gate_report.json")
    leak = _read("public_leak_scan.json")
    rehearsal = _read("evaluation_wrapper_rehearsal_evidence.json")
    return {
        "schema_version": "t30-preconstruction-report-v1",
        "artifact": "T30_PRECONSTRUCTION_REPORT",
        "classification": "PUBLIC_SAFE",
        "verdict": verdict["verdict"],
        "remediation_verdict": verdict["remediation_verdict"],
        "RECOVERY_REMEDIATION": {
            "reachability_gate": {key: _read(
                "nonvacuity_reachability_gate.json").get(key) for key in (
                "status", "recovery_proof", "designations",
                "replan_triggers_observed", "safe_terminals_observed",
                "adapter_stack", "reachability_root")},
            "recovery_negative_controls": {key: _read(
                "recovery_control_negative_controls.json").get(key)
                for key in ("status", "control_count", "PASS", "FAIL")},
            "adapter_identity": {key: _read("adapter_identity.json").get(key)
                                 for key in ("status", "identity_exact",
                                             "actual_adapter_builder",
                                             "historical_defect",
                                             "adapter_identity_root")},
            "recovery_control_policy_root": _read(
                "recovery_control_policy.json").get("policy_root"),
            "wrapper_rehearsal_runs": [
                {key: run.get(key) for key in (
                    "variant", "status", "score_pass", "recovery_success_rate",
                    "recovery_pass_32_of_32", "recovery_injections_exact",
                    "ordering_binding_precedes_control_read",
                    "ordering_control_before_blind_inputs",
                    "ordering_strictly_increasing", "state_sequence",
                    "semantic_signature")}
                for run in rehearsal.get("runs", [])],
            "wrapper_semantic_equivalence": rehearsal.get(
                "semantic_equivalence"),
        },
        # --- §52 required sections ---
        "START_STATE": {
            "predecessor": T27_PREDECESSOR_VERDICT,
            "t27_terminal":
                "SEALED / UNSPENT_BUT_PERMANENTLY_INELIGIBLE (attempt 0)",
            "t28_terminal": T28_PREDECESSOR_VERDICT,
            "t28_terminal":
                "SEALED / UNSPENT_BUT_PERMANENTLY_INELIGIBLE (attempt 0)",
            "branch": "t30-preconstruction",
            "base_commit": T29_ADJUDICATION_COMMIT,
            "t29_terminal": T29_PREDECESSOR_STATUS_RECORD["t29_terminal"],
        },
        "CANDIDATE": {
            "candidate_commit": "11d76c6392ec1f3d08840cfca641618ca61d9247",
            "candidate_tree": "1b1a0296232d1b89f94d95902dbce515f59bb266",
            "runtime_root":
                "c55da12937ed4bce5df0f0ad3692a85c0ae323278a5bacd5610fdf87f258a44d",
            "candidate_runtime_changes": 0,
        },
        "T27_T28_STATUS": {
            "t27": ["SEALED", "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
                    "PERMANENTLY_NOT_AUTHORIZED_FOR_T27", "NOT_MEASURED"],
            "t28": ["SEALED", "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
                    "PERMANENTLY_INELIGIBLE", "NOT_MEASURED"],
        },
        "T28_DEFECT_REPRODUCER": {
            "artifact": "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json",
            "status": (json.loads(
                (out / "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json")
                .read_text(encoding="utf-8")).get("status")),
        },
        "T30_HISTORICAL_ANCHOR_SCHEMA": {
            "t27_anchor": "t30-t27-historical-failure-anchor-v1",
            "dual_oracle": "t30-dual-overlap-oracle-v2",
        },
        "PRODUCER_CONSUMER_ROUNDTRIP": {
            "t27_official_anchor_live": _read("historical_anchor_t27.json")[
                "construction_state"],
            "t28_official_anchor_live": _read("historical_anchor_t28.json")[
                "construction_state"],
            "roundtrip_exact": _read(
                "historical_anchor_controls_evidence.json")[
                "roundtrip_exact"],
        },
        "CONSTRUCTION_INFRASTRUCTURE": {
            "wrapper_rehearsal": _read("real_entrypoint_rehearsal.json")[
                "status"],
            "rehearsals": _read("construction_rehearsal_report.json")[
                "status"],
            "failure_rehearsal": _read(
                "construction_failure_rehearsal.json")["status"],
            "negative_controls": _read("construction_negative_controls.json")[
                "status"],
        },
        "CONSTRUCTION_REAL_WRAPPER_REHEARSAL": {
            "artifact": "real_entrypoint_rehearsal.json",
            "entrypoint": "t30_protocol.construction:construct_real",
            "status": _read("real_entrypoint_rehearsal.json")["status"],
        },
        "EVALUATION_INFRASTRUCTURE": {
            "official_entrypoint": "t30_protocol.evaluation:evaluate_official",
            "closed_signature": ["root", "private_store_root", "token"],
            "ledger_first": True,
        },
        "OFFICIAL_EVALUATE_OFFICIAL_WRAPPER_REHEARSALS": {
            "status": rehearsal["status"],
            "wrapper_invocations_on_disposable_standins":
                rehearsal.get("wrapper_invocations_on_disposable_standins"),
            "official_real_evaluator_invocations":
                rehearsal.get("official_real_evaluator_invocations"),
        },
        "ORDERING_PROOF": {
            "evaluation_ledger_precedes":
                _read("production_graph.json")["evaluation_ledger_precedes"],
            "rehearsal_ordering_strictly_increasing": all(
                run.get("ordering_strictly_increasing") is True
                for run in rehearsal.get("runs", [])),
        },
        "PRE_LEDGER_FAILURE_CONTROLS": {
            "preledger_refusals": _read(
                "evaluation_preledger_refusals_evidence.json")["status"],
            "wrapper_refusals": _read(
                "wrapper_refusal_controls_evidence.json")["status"],
        },
        "POST_LEDGER_FAILURE_CONTROLS": {
            "failure_rehearsal": _read(
                "evaluation_failure_rehearsal_evidence.json")["status"],
        },
        "OFFICIAL_ENVIRONMENT": {
            "environment_root": identity["environment_root"],
            "rehearsal_environment_root":
                identity["rehearsal_environment_root"],
            "live_provider_identity_root":
                identity["live_provider_identity_root"],
            "model_stack": {
                "base_model_id": stack["model_identity_evidence"][
                    "base_model_id"],
                "base_revision": stack["model_identity_evidence"][
                    "base_revision"],
                "adapter_sha256": stack["model_identity_evidence"][
                    "adapter_sha256"],
                "adapter_bytes": stack["model_identity_evidence"][
                    "adapter_bytes"],
                "candidate_executions": stack["candidate_executions"],
            },
        },
        "T27_SEALED_ORACLE": {
            "predecessor": "t27", "mode": "REAL_REHEARSAL",
            "store_authenticated": _read("real_mode_oracle_evidence.json")[
                "t27_store_authenticated"],
        },
        "T28_SEALED_ORACLE": {
            "predecessor": "t28", "mode": "REAL_REHEARSAL",
            "store_authenticated": _read("real_mode_oracle_evidence.json")[
                "t28_store_authenticated"],
        },
        "PUBLIC_HISTORICAL_INDEX": {
            "authenticated": True,
            "index_report_staged": "public_historical_index_report.json",
        },
        "QUALIFICATION": _read("qualification_report.json").get("status"),
        "METRICS": _read("metric_registry.json")["metrics"],
        "CRITICAL_COUNTERS": list(CRITICAL_COUNTERS),
        "CONTRACT": {
            "leaf_count": contract["leaf_count"], "PASS": contract["PASS"],
            "FAIL": contract["FAIL"], "UNVERIFIABLE": contract["UNVERIFIABLE"],
        },
        "CONSTRUCTION_GATE": {
            "gate_ids": 56, "real_attempts": 0, "consumed": False,
            "one_shot": "UNSPENT",
        },
        "EVALUATION_READINESS_GATE": gate,
        "DOCTOR": {"status": doctor.get("status"),
                   "checks_red": [k for k, v in doctor.get("checks",
                                                           {}).items()
                                  if v is not True]},
        "FREEZE": {key: frozen.get(key) for key in (
            "freeze_sha256", "freeze_root", "component_root",
            "component_count", "real_construction_authorized",
            "real_evaluation_authorized", "real_blind_rows", "real_gold_rows",
            "real_construction_attempts", "real_evaluation_attempts")},
        "REAL_EXPOSURE": exposure,
        "TEST_GATE": test_gate,
        "LEAK_SCAN": {"status": leak["status"],
                      "blind_blob_count": leak.get("blind_blob_count")},
        "ENVIRONMENT": {"environment_root": identity["environment_root"]},
        "ABSOLUTE_STOP": verdict["absolute_stop"],
        "NEXT_STATE": verdict["next_state"],
    }


def _verify(root: Path) -> int:
    """§50 verification mode: read-only re-verification of pushed bytes.

    Runs inside a fresh remote clone: verifies the canonical freeze through
    the shared loader, re-runs the fail-closed doctor from the pushed
    protocol bytes, and emits a machine JSON summary.  Writes only the
    doctor report (freeze-EXCLUDED), never any other artifact.
    """
    from t30_protocol.freeze import load_preconstruction_freeze
    from t30_protocol.doctor import run_doctor

    root = Path(root).resolve()
    frozen = load_preconstruction_freeze(root)
    doctor = run_doctor(root)
    (root / "evaluations" / "t30").mkdir(parents=True, exist_ok=True)
    _write(root / "evaluations" / "t30" / "protocol_doctor_report.json",
           doctor)
    verdict = json.loads(
        (root / "evaluations" / "t30" / "T30_PRECONSTRUCTION_VERDICT.json")
        .read_text(encoding="utf-8"))
    print(json.dumps(
        {"doctor": doctor.get("status"),
         "doctor_check_count": doctor.get("check_count"),
         "verdict": verdict.get("verdict"),
         "freeze_sha256": frozen.get("freeze_sha256"),
         "component_count": frozen.get("component_count"),
         "component_root": frozen.get("component_root"),
         "freeze_root": frozen.get("freeze_root"),
         "candidate_commit": frozen.get("candidate_commit"),
         "candidate_runtime_changes":
             frozen.get("candidate_runtime_changes")},
        indent=2, sort_keys=True))
    ok = (doctor.get("status") == "PASS"
          and verdict.get("verdict") == "T30_PRECONSTRUCTION_PASS"
          and verdict.get("absolute_stop") is True
          and frozen.get("real_construction_authorized") is False
          and frozen.get("real_evaluation_authorized") is False
          and frozen.get("real_blind_rows") == 0
          and frozen.get("real_gold_rows") == 0
          and frozen.get("real_construction_attempts") == 0
          and frozen.get("real_evaluation_attempts") == 0
          and frozen.get("component_count")
          == len(frozen.get("components", [])))
    return 0 if ok else 1


#: §45 semantic fields compared for rehearsals whose disposable stand-ins
#: carry wall-clock journal timestamps (roots legitimately differ per run).
_REAL_MODE_SEMANTIC_KEYS = (
    "status", "predecessors", "t27_store_authenticated", "t27_commitments_exact",
    "t28_store_authenticated", "t28_commitments_exact",
    "t29_abandoned_package_authenticated", "t29_abandoned_commitment_exact",
    "t29_abandoned_row_files_opened", "real_mode_not_synthetic",
    "prospective_root_exact", "t27_fingerprint_index_origin",
    "t28_fingerprint_index_origin", "overall_prohibited_overlap",
    "outside_boundary_private_rows_exposed", "candidate_executions")
_EVALUATION_WRAPPER_SEMANTIC_KEYS = (
    "status", "semantic_equivalence",
    "wrapper_invocations_on_disposable_standins",
    "official_real_evaluator_invocations", "real_evaluation_attempts",
    "real_blind_rows", "runs")


def _verify_full(root: Path) -> int:
    """§45: from exact remote bytes, recompute every successor surface and
    compare with the pushed artifacts; semantic_drift counts mismatches.
    Writes only freeze-EXCLUDED files (doctor report)."""
    from t30_protocol.construction import (run_publication_leak_gate,
                                           run_real_entrypoint_rehearsal,
                                           run_real_mode_oracle_validation_rehearsal)
    from t30_protocol.doctor import run_doctor
    from t30_protocol.evaluation import (run_evaluation_readiness_gate,
                                         run_evaluation_rehearsals,
                                         run_preconstruction_contract_audit)
    from t30_protocol.freeze import load_preconstruction_freeze

    root = Path(root).resolve()
    out = root / "evaluations" / "t30"
    staged = lambda name: json.loads((out / name).read_text(encoding="utf-8"))  # noqa: E731
    items: dict[str, dict] = {}

    def compare(name: str, recomputed, pushed, keys=None) -> None:
        if keys is not None:
            recomputed = {key: recomputed.get(key) for key in keys}
            pushed = {key: pushed.get(key) for key in keys}
        items[name] = {"match": recomputed == pushed,
                       "compared_keys": list(keys) if keys else "ALL"}

    frozen = load_preconstruction_freeze(root)
    items["freeze_loader"] = {"match": frozen.get("freeze_sha256") == staged(
        "preconstruction_freeze.json").get("freeze_sha256")}
    # Successor evidence recomputed against the actual stores (env only).
    from t27_protocol.store import T27PrivateStore
    from t27_protocol.t28_private_oracle import authenticate_official_t27_store_for_t28
    from t30_protocol.abandonment import (abandonment_oracle_requirement,
                                          official_abandonment_readiness,
                                          t29_abandonment_commitment)
    from t30_protocol.oracle import build_t28_journal_evidence
    journal = build_t28_journal_evidence(root, _private_location("T30_T28_STORE"))
    compare("t28_journal_compatibility", journal["official"],
            staged("t28_journal_compatibility.json"))
    compare("t28_journal_schema_equivalence", journal["equivalence"],
            staged("t28_journal_schema_equivalence.json"))
    compare("t28_journal_negative_controls", journal["negative_controls"],
            staged("t28_journal_negative_controls.json"))
    t27 = authenticate_official_t27_store_for_t28(
        root, T27PrivateStore(_private_location("T30_T27_STORE"),
                              repository_root=root), expected=None)
    pushed_t27 = staged("t27_metadata_authentication.json")
    compare("t27_metadata_authentication",
            {key: t27.get(key) for key in pushed_t27 if key.startswith("t27_")
             and key != "t27_oracle_executed"},
            {key: value for key, value in pushed_t27.items()
             if key.startswith("t27_") and key != "t27_oracle_executed"})
    compare("t29_abandonment_commitment", t29_abandonment_commitment(root),
            staged("t29_abandonment_commitment.json"))
    compare("t29_abandonment_oracle_requirement",
            abandonment_oracle_requirement(),
            staged("t29_abandonment_oracle_requirement.json"))
    compare("t29_abandonment_readiness", official_abandonment_readiness(
        root, _private_location("T30_T29_PACKAGE")),
        staged("t29_abandonment_readiness.json"))
    # Rehearsals, contract, gates.
    compare("real_mode_oracle_rehearsal",
            run_real_mode_oracle_validation_rehearsal(root),
            staged("real_mode_oracle_evidence.json"), _REAL_MODE_SEMANTIC_KEYS)
    compare("construction_wrapper_rehearsal", run_real_entrypoint_rehearsal(root),
            staged("real_entrypoint_rehearsal.json"))
    compare("evaluation_wrapper_rehearsals", run_evaluation_rehearsals(root),
            staged("evaluation_wrapper_rehearsal_evidence.json"),
            _EVALUATION_WRAPPER_SEMANTIC_KEYS)
    # Recovery-reachability remediation surfaces (fresh-clone reproduction).
    from t30_protocol.reachability import (
        run_real_stack_nonvacuity_reachability,
        run_recovery_control_negative_controls)
    from t30_protocol.recovery_control import (adapter_identity_report,
                                               recovery_control_policy)
    compare("recovery_control_policy", recovery_control_policy(),
            staged("recovery_control_policy.json"))
    compare("adapter_implementation_identity", adapter_identity_report(root),
            staged("adapter_identity.json"))
    compare("real_stack_nonvacuity_reachability",
            run_real_stack_nonvacuity_reachability(root),
            staged("nonvacuity_reachability_gate.json"))
    compare("recovery_control_negative_controls",
            run_recovery_control_negative_controls(root),
            staged("recovery_control_negative_controls.json"))
    compare("preconstruction_contract", run_preconstruction_contract_audit(root),
            staged("preconstruction_contract.json"))
    compare("evaluation_readiness_gate", run_evaluation_readiness_gate(root),
            staged("evaluation_readiness_gate.json"))
    leak = run_publication_leak_gate(root, fetch=True)
    items["leak_scan"] = {"match": leak.get("status") == "PASS"
                          and leak.get("blind_blob_count") == 0}
    tests = _test_gate(root)
    items["test_gate"] = {"match": tests.get("status") == "PASS"
                          and tests.get("tests") == staged(
                              "test_gate_report.json").get("tests")}
    doctor = run_doctor(root)
    _write(out / "protocol_doctor_report.json", doctor)
    items["doctor"] = {"match": doctor.get("status") == "PASS"}
    drift = sorted(name for name, item in items.items() if not item["match"])
    print(json.dumps({"semantic_drift": len(drift), "drifted": drift,
                      "items": items,
                      "freeze_sha256": frozen.get("freeze_sha256"),
                      "doctor": doctor.get("status"),
                      "doctor_check_count": doctor.get("check_count"),
                      "test_gate_tests": tests.get("tests"),
                      "leak_scan_root": leak.get("scan_root")},
                     indent=2, sort_keys=True))
    return 0 if not drift else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify-full", action="store_true",
                        help="§45 full semantic reproduction (fresh clone)")
    parser.add_argument("--verify", action="store_true",
                        help="§50 read-only verification mode used inside a "
                             "fresh remote clone (no staging, no suites)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.verify_full:
        return _verify_full(root)
    if args.verify:
        return _verify(root)
    (root / "evaluations" / "t30").mkdir(parents=True, exist_ok=True)
    _stage_t29_predecessor_status(root)
    # Idempotent official-document bootstrap (write-if-absent; the staged
    # real environment root is carried forward, never replaced).
    from t30_protocol.evaluation import stage_official_documents
    stage_official_documents(root)
    _stage_base_artifacts(root)
    _stage_successor_evidence(root)
    _stage_t30_boundaries(root)
    identity = _stage_environment(root)
    _stage_recovery_remediation(root)
    _stage_provisional_freeze(root)
    _stage_readiness(root)
    _stage_leak_and_gate(root)
    from t30_protocol.freeze import build_freeze
    provisional = build_freeze(root)
    _stage_construction_suites(root, provisional)
    frozen = _stage_freeze(root)
    from t30_protocol.doctor import run_doctor
    doctor = run_doctor(root)
    _write(root / "evaluations" / "t30" / "protocol_doctor_report.json", doctor)
    verdict = _final_verdict(root, frozen, doctor)
    _write(root / "evaluations" / "t30" / "T30_PRECONSTRUCTION_VERDICT.json",
           verdict)
    report = _preconstruction_report(root, frozen, doctor, verdict)
    print(json.dumps({"doctor": doctor.get("status"),
                      "verdict": verdict.get("verdict"),
                      "freeze_sha256": frozen.get("freeze_sha256"),
                      "report": report}, indent=2, sort_keys=True))

if __name__ == "__main__":
    raise SystemExit(main())
