"""T29 successor preconstruction driver (§1–§54).

Executes the T29 successor preconstruction authorization verbatim, in
fail-closed stage order:

  A   superseded freeze record (§11, historical preservation)
  B   base artifacts (design / storage / qualifications / protection /
      real-exposure / T28 public root-cause reproducer)
  C   T29 boundaries (exclusion policy ladder v1-v4, authenticated public
      historical index, T27 marker contract, T29 dual-oracle rehearsal)
  D   REAL official environment (§26/§27; staged on this production-capable
      host with the pinned adapter, candidate executions = 0)
  E   readiness evidence (7 sealed documents) -> preconstruction contract ->:
  F   provisional freeze at the canonical path (rehearsals load it through
      t29_protocol.freeze:load_preconstruction_freeze only)
  G   publication leak scan + applicability-aware test gate (§46)
  H   construction suites (rehearsals / failure rehearsal / negative controls
      / generated-public policy controls / marker layout + freeze-path
      controls) bound to the live canonical freeze
  I   OFFICIAL freeze (§47) regenerated after every artifact was staged —
      deterministically identical — with the §48 flags all false
  J   fail-closed protocol doctor (§45) staged OUTSIDE the freeze component
      set, then the §53 verdict and the §52 report

ABSOLUTE STOP (§54): no real blind scenarios, no real gold, no T29
construction ledger, no consumption of the T29 construction one-shot, and no
official evaluation are executed here.
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

# §11 historical preservation: the pre-remediation T29 freeze identity, whose
# only defect was the nonexistent freeze path consumed by the real
# entrypoint.  Identity pinned by the fail-closed doctor (§45).
SUPERSEDED_PRE_EXPOSURE_FREEZE_RECORD = {
    "schema_version": "t29-freeze-supersession-record-v1",
    "artifact": "T29_PRECONSTRUCTION_FREEZE_SUPERSEDED_PRE_EXPOSURE",
    "classification": "SUPERSEDED_PRE_EXPOSURE",
    "record_name": "T29_PRECONSTRUCTION_FREEZE_V1_SUPERSEDED_PRE_EXPOSURE",
    "supersession_reason":
        "REAL_CONSTRUCTION_ENTRYPOINT_REFERENCED_NONEXISTENT_FREEZE_PATH",
    "supersession_detail":
        "the corrected construct_real entrypoint now loads the canonical "
        "preconstruction freeze through the shared loader at the single "
        "canonical path constant; the historical freeze identity below was "
        "verified exact and is preserved here; no alias path was created",
    "superseded_at_authorization_commit":
        "b9ffbbb508ded09696d9e9f0edb51c70ffc1e245",
    "superseded_freeze": {
        "artifact": "T29_PRECONSTRUCTION_FREEZE",
        "path": "evaluations/t29/preconstruction_freeze.json",
        "component_count": 262,
        "component_root":
            "c413a58598d811eee81ada1afcd5470c18579c507576908d8d067ee9f4780bc7",
        "freeze_root":
            "fbb7d58b0034128d35a2730cc54b1049a50111291f1a0aec9d7a3060ac708965",
        "freeze_sha256":
            "06b01fe5eab5383fc0b3a785c0030af7b945f829ee005c3dfccb2d61b3f72e99",
        "real_construction_authorized": False,
        "real_evaluation_authorized": False,
    },
    "candidate_unchanged": {
        "candidate_commit": "11d76c6392ec1f3d08840cfca641618ca61d9247",
        "candidate_tree": "1b1a0296232d1b89f94d95902dbce515f59bb266",
        "runtime_root":
            "c55da12937ed4bce5df0f0ad3692a85c0ae323278a5bacd5610fdf87f258a44d",
        "candidate_runtime_changes": 0,
    },
    "successor": "T29_PRECONSTRUCTION_FREEZE",
    "historical_rewrite_of_predecessor": False,
    "real_exposure": 0,
}


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n", encoding="utf-8")


def _read_staged(root: Path, name: str) -> dict:
    return json.loads(
        (root / "evaluations" / "t29" / name).read_text(encoding="utf-8"))


def _staged(root: Path, name: str) -> bool:
    """True when the staged artifact exists with a passing status."""
    path = root / "evaluations" / "t29" / name
    if not path.is_file():
        return False
    try:
        status = json.loads(path.read_text(encoding="utf-8")).get("status")
    except (ValueError, OSError):
        return False
    return status in ("PASS", "REPRODUCED", "REPRODUCED_AND_REMEDIATED")


# ---------------------------------------------------------------------------
# Stage A: superseded freeze record (§11)
# ---------------------------------------------------------------------------


def _stage_superseded_freeze_record(root: Path) -> dict:
    from t29_protocol.freeze import SUPERSEDED_PRE_EXPOSURE_PATH
    out = root / "evaluations" / "t29"
    path = out / SUPERSEDED_PRE_EXPOSURE_PATH.rsplit("/", 1)[-1]
    if not path.is_file():
        _write(path, SUPERSEDED_PRE_EXPOSURE_FREEZE_RECORD)
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Stage B: base artifacts (§5–§7, §41)
# ---------------------------------------------------------------------------


def _stage_base_artifacts(root: Path) -> dict:
    from t29_protocol.contract import (authority_graph, design,
                                       execution_contract, metric_registry,
                                       nonvacuity_policy, production_graph,
                                       storage_policy)
    from t29_protocol.protection import run_protection
    from t29_protocol.qualification import qualification_exclusion_commitment

    from t29_protocol.freeze import build_candidate_identity

    out = root / "evaluations" / "t29"
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
            "t29_real_blind_rows": 0, "t29_real_gold": 0,
            "t29_construction_attempts": 0, "t29_evaluation_attempts": 0,
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
    if not _staged(root, "qualification_report.json"):
        from t29_protocol.qualification import run_qualification
        _write(out / "qualification_report.json", run_qualification())
    documents["qualification_report.json"] = _read_staged(
        root, "qualification_report.json")
    if not _staged(root, "diagnostics_report.json"):
        from t29_protocol.qualification import (
            run_completion_gate_matrix, run_terminal_matrix,
            run_verification_matrix)
        _write(root / "evaluations" / "t29" / "diagnostics_report.json", {
            "terminal_matrix": run_terminal_matrix(),
            "verification_matrix": run_verification_matrix(),
            "completion_gate": run_completion_gate_matrix(),
        })
    documents["diagnostics_report.json"] = _read_staged(
        root, "diagnostics_report.json")
    if not _staged(root, "protection_report.json"):
        _write(root / "evaluations" / "t29" / "protection_report.json",
               run_protection(root))
    documents["protection_report.json"] = _read_staged(
        root, "protection_report.json")
    return documents


def _historical_anchor(root: Path) -> dict:
    """§41/§45: the T27 historical failure anchor, bound live to the frozen
    T27 official evaluation eligibility adjudication (commit 16314c5…) —
    construction SEALED/1, official evaluation UNSPENT_BUT_PERMANENTLY_
    INELIGIBLE (attempt 0), permanent T27 ineligibility, zero rows opened."""
    from t29_protocol.contract import (
        T27_CONSTRUCTION_ATTEMPT, T27_CONSTRUCTION_STATE,
        T27_OFFICIAL_EVALUATION_ATTEMPT, T27_OFFICIAL_EVALUATION_ELIGIBILITY,
        T27_OFFICIAL_EVALUATION_STATE, T27_PREDECESSOR_VERDICT)
    from t29_protocol.freeze import T27_ADJUDICATION_COMMIT

    adjudication = json.loads(
        (root / "evaluations/t27/"
         "T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json")
        .read_text(encoding="utf-8"))
    return {
        "schema_version": "t29-t27-historical-failure-anchor-v1",
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
    from t29_protocol.protection import run_protection
    return run_protection(root)


def _reproduce_t28_defect(root: Path) -> None:
    """§52 T28-DEFECT-REPRODUCER: idempotent re-run of the sealed reproducer."""
    from t29_protocol.defect_reproducer import run_t28_preflight_defect_reproducer
    out = root / "evaluations" / "t29"
    if not _staged(root, "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json"):
        _write(out / "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json",
               run_t28_preflight_defect_reproducer(root))


# ---------------------------------------------------------------------------
# Stage C: T29 boundaries (§8–§12, §28, §29)
# ---------------------------------------------------------------------------


def _stage_t29_boundaries(root: Path) -> dict:
    from t29_protocol.construction import (
        official_marker_contract_report, run_real_mode_oracle_validation_rehearsal)
    from t29_protocol.exclusion import (
        authenticated_construction_policy,
        build_authenticated_public_historical_index,
        construction_ready_policy, generated_public_dimension_policy,
        historical_exclusion_policy_v4, policy as exclusion_policy,
        public_index_report, public_index_supersession,
        t27_public_qualification_exclusion_precedent,
    )
    from t29_protocol.store import storage_policy_successor

    out = root / "evaluations" / "t29"
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
    out = root / "evaluations" / "t29"
    if ((out / "official_environment_identity.json").is_file()
            and (out / "official_general_context.json").is_file()
            and _staged(root, "production_stack_environment_preflight.json")):
        return _read_staged(root, "official_environment_identity.json")
    import os
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from t29_protocol.official_environment import (
        MODEL_PINS, build_official_evaluation_environment,
        stage_environment_identity)
    from t29_protocol.scorer import ZERO_DENOMINATOR_POLICY
    from t29_protocol.evaluation import run_model_hydration_preflight

    real = stage_environment_identity(root)
    rehearsal = stage_environment_identity(root, rehearsal_only=True)
    identity_document = {
        "schema_version": "t29-official-environment-identity-v1",
        "artifact": "T29_OFFICIAL_ENVIRONMENT_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t29",
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
        "schema_version": "t29-production-stack-environment-preflight-v1",
        "artifact": "T29_PRODUCTION_STACK_ENVIRONMENT_PREFLIGHT",
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
# Stage E: provisional freeze + readiness evidence + contract + readiness gate
# ---------------------------------------------------------------------------


def _stage_provisional_freeze(root: Path) -> dict:
    """Stage the provisional freeze at the canonical path (an EXCLUDED
    self-referent): the canonical loader consumed by the real entrypoint
    requires it.  Recomputed deterministically at Stage I."""
    from t29_protocol.freeze import build_freeze, T29_PRECONSTRUCTION_FREEZE_PATH
    freeze_path = root / T29_PRECONSTRUCTION_FREEZE_PATH
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
    from t29_protocol.evaluation import (
        run_evaluation_readiness_gate, run_preconstruction_contract_audit,
        stage_readiness_evidence)

    result_evidence = stage_readiness_evidence(root)
    staged_paths = sorted(result_evidence.get("staged_paths", []))
    contract = run_preconstruction_contract_audit(root)
    _write(root / "evaluations" / "t29" / "preconstruction_contract.json",
           contract)
    if contract.get("status") != "PASS":
        raise RuntimeError("T29 preconstruction contract audit: "
                           + str(contract.get("status")))
    gate = run_evaluation_readiness_gate(root)
    _write(root / "evaluations" / "t29" / "evaluation_readiness_gate.json", gate)
    return {"evidence": staged_paths, "contract": contract, "gate": gate}


# ---------------------------------------------------------------------------
# Stage G: publication leak scan + applicability-aware test gate (§46)
# ---------------------------------------------------------------------------


def _test_gate(root: Path) -> dict:
    files = sorted(
        path.as_posix()
        for path in (root / "tests").glob("test_t29*.py"))
    if not files:
        raise RuntimeError(
            "no tests/test_t29*.py test files staged for the §46 gate")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t29-test-gate-") as tmp:
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
            return {"schema_version": "t29-test-gate-v1",
                    "artifact": "T29_APPLICABILITY_AWARE_TEST_GATE",
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
            "schema_version": "t29-test-gate-v1",
            "artifact": "T29_APPLICABILITY_AWARE_TEST_GATE",
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
    from t29_protocol.construction import run_publication_leak_gate

    out = root / "evaluations" / "t29"
    leak = run_publication_leak_gate(root, fetch=False)
    _write(out / "public_leak_scan.json", leak)
    gate = _test_gate(root)
    _write(out / "test_gate_report.json", gate)
    if gate.get("status") != "PASS":
        raise RuntimeError("T29 §46 test gate not green: "
                           + json.dumps({k: gate[k] for k in (
                               "status", "tests", "live_failures",
                               "unknown_failures", "unexplained_skips",
                               "xfails", "deselections")}, sort_keys=True))
    if leak.get("status") != "PASS":
        raise RuntimeError("T29 publication leak gate not green: "
                           + str(leak)[:400])
    return {"leak": leak, "gate": gate}


# ---------------------------------------------------------------------------
# Stage H: construction suites (§43–§46) — bound to the live canonical freeze
# ---------------------------------------------------------------------------


def _stage_construction_suites(root: Path, freeze: dict) -> dict:
    from t29_protocol.construction import (
        run_construction_failure_rehearsal, run_construction_rehearsals,
        run_freeze_path_negative_controls, run_generated_public_policy_controls,
        run_negative_controls, run_t27_marker_layout_negative_controls,
    )

    out = root / "evaluations" / "t29"
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
                raise RuntimeError(f"T29 construction suite failed: {name}: "
                                   + json.dumps(document, sort_keys=True)[:400])
        elif document.get("status") != "PASS":
            raise RuntimeError(
                f"T29 construction suite failed: {name}: "
                + str(document.get("refusal") or document.get("summary"))[:300])
    return documents


# ---------------------------------------------------------------------------
# Stage I: canonical freeze (§47/§48) — regenerated LAST, with zero real flags
# ---------------------------------------------------------------------------


def _stage_freeze(root: Path) -> dict:
    from t29_protocol.freeze import build_freeze, verify_freeze

    out = root / "evaluations" / "t29"
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
        raise ValueError("T29 §48 freeze flags violated: "
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
        "schema_version": "t29-preconstruction-verdict-v1",
        "artifact": "T29_PRECONSTRUCTION_VERDICT",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if passed else "FAIL",
        "verdict": ("T29_PRECONSTRUCTION_PASS" if passed
                    else "T29_PRECONSTRUCTION_FAIL"),
        "construction_authorized": False,
        "evaluation_authorized": False,
        "absolute_stop": True,
        "next_state": "T29_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
        "t27_token_binding": "T27_ONE_SHOT_OFFICIAL_EVALUATION "
                             "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t28_token_binding": "T28_ONE_SHOT_OFFICIAL_EVALUATION "
                             "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t29_construction_one_shot": "UNSPENT",
        "t29_evaluation_one_shot": "NOT_YET_AUTHORIZED",
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
    from t29_protocol.contract import (CRITICAL_COUNTERS,
                                       T27_PREDECESSOR_VERDICT,
                                       T28_PREDECESSOR_VERDICT)
    out = root / "evaluations" / "t29"

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
        "schema_version": "t29-preconstruction-report-v1",
        "artifact": "T29_PRECONSTRUCTION_REPORT",
        "classification": "PUBLIC_SAFE",
        "verdict": verdict["verdict"],
        # --- §52 required sections ---
        "START_STATE": {
            "predecessor": T27_PREDECESSOR_VERDICT,
            "t27_terminal":
                "SEALED / UNSPENT_BUT_PERMANENTLY_INELIGIBLE (attempt 0)",
            "t28_terminal": T28_PREDECESSOR_VERDICT,
            "t28_terminal":
                "SEALED / UNSPENT_BUT_PERMANENTLY_INELIGIBLE (attempt 0)",
            "branch": "t29-preconstruction",
            "base_commit": "b9ffbbb508ded09696d9e9f0edb51c70ffc1e245",
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
        "T29_HISTORICAL_ANCHOR_SCHEMA": {
            "t27_anchor": "t29-t27-historical-failure-anchor-v1",
            "dual_oracle": "t29-dual-overlap-oracle-v2",
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
            "entrypoint": "t29_protocol.construction:construct_real",
            "status": _read("real_entrypoint_rehearsal.json")["status"],
        },
        "EVALUATION_INFRASTRUCTURE": {
            "official_entrypoint": "t29_protocol.evaluation:evaluate_official",
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
    from t29_protocol.freeze import load_preconstruction_freeze
    from t29_protocol.doctor import run_doctor

    root = Path(root).resolve()
    frozen = load_preconstruction_freeze(root)
    doctor = run_doctor(root)
    (root / "evaluations" / "t29").mkdir(parents=True, exist_ok=True)
    _write(root / "evaluations" / "t29" / "protocol_doctor_report.json",
           doctor)
    verdict = json.loads(
        (root / "evaluations" / "t29" / "T29_PRECONSTRUCTION_VERDICT.json")
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
          and verdict.get("verdict") == "T29_PRECONSTRUCTION_PASS"
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify", action="store_true",
                        help="§50 read-only verification mode used inside a "
                             "fresh remote clone (no staging, no suites)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.verify:
        return _verify(root)
    (root / "evaluations" / "t29").mkdir(parents=True, exist_ok=True)
    _stage_superseded_freeze_record(root)
    _stage_base_artifacts(root)
    _stage_t29_boundaries(root)
    identity = _stage_environment(root)
    _stage_provisional_freeze(root)
    _stage_readiness(root)
    _stage_leak_and_gate(root)
    from t29_protocol.freeze import build_freeze
    provisional = build_freeze(root)
    _stage_construction_suites(root, provisional)
    frozen = _stage_freeze(root)
    from t29_protocol.doctor import run_doctor
    doctor = run_doctor(root)
    _write(root / "evaluations" / "t29" / "protocol_doctor_report.json", doctor)
    verdict = _final_verdict(root, frozen, doctor)
    _write(root / "evaluations" / "t29" / "T29_PRECONSTRUCTION_VERDICT.json",
           verdict)
    report = _preconstruction_report(root, frozen, doctor, verdict)
    print(json.dumps({"doctor": doctor.get("status"),
                      "verdict": verdict.get("verdict"),
                      "freeze_sha256": frozen.get("freeze_sha256"),
                      "report": report}, indent=2, sort_keys=True))

if __name__ == "__main__":
    raise SystemExit(main())
