"""Disposable negative controls for the repaired T23 construction protocol."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import pytest

from sciencemath.knowledge.corpus import load_corpus
from t21_protocol.errors import LedgerError
from t23_protocol.author import author_cases, shadow_labels
from t23_protocol.blindness import audit_blindness, synthetic_provenance
from t23_protocol.construction import run_construction_audits, run_shadow_construction
from t23_protocol.construction_gate import run_construction_gate
from t23_protocol.construction_ledger import (T23ConstructionLedger,
                                               construction_state, verify_ledger)
from t23_protocol.contract import load_t23_contract
from t23_protocol.exclusions import audit_exclusions, load_exclusion_sources
from t23_protocol.lock import verify_lock
from t23_protocol.lifecycle import verify_lifecycle
from t23_protocol.manifest import verify_seal

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t23"


@pytest.fixture(scope="module")
def shadow():
    with TemporaryDirectory(prefix="t23-negative-shadow-") as directory:
        root = Path(directory)
        result = run_shadow_construction(ROOT, root)
        assert result["terminal_state"] == "SEALED"
        yield root


@pytest.mark.parametrize("field", [
    "candidate_commit", "candidate_tree", "preconstruction_freeze_sha256",
    "freeze_root", "author_lock_sha256",
])
def test_frozen_identity_drift_refused(shadow: Path, tmp_path: Path, field: str) -> None:
    ledger = json.loads((shadow / "evaluations/t23/construction_run_ledger.json").read_text())
    ledger["bindings"][field] = "0" * 64
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(LedgerError):
        verify_ledger(path)


def test_duplicate_ledger_and_second_attempt_refused(shadow: Path) -> None:
    path = shadow / "evaluations/t23/construction_run_ledger.json"
    bindings = verify_ledger(path)["bindings"]
    with pytest.raises(LedgerError):
        T23ConstructionLedger.create_exclusive(path, bindings)
    with pytest.raises(ValueError, match="empty"):
        run_shadow_construction(ROOT, shadow)


def test_missing_historical_source_and_unknown_dimension_refused() -> None:
    registry = json.loads((OUT / "construction_exclusion_sources.json").read_text())
    absent = deepcopy(registry)
    absent["sources"]["historical"]["path"] = "evaluations/t23/absent-anchor.json"
    with pytest.raises(ValueError, match="missing"):
        load_exclusion_sources(ROOT, absent)
    unknown = deepcopy(registry)
    unknown["sources"]["historical"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        load_exclusion_sources(ROOT, unknown)


@pytest.mark.parametrize("mutation", ["qualification_collision", "duplicate_case_id",
                                      "duplicate_semantic_fingerprint"])
def test_exclusion_collision_controls(mutation: str) -> None:
    inputs, gold = author_cases(shadow_labels(), namespace="t23-shadow",
                                attachment_path="documents/shadow.txt")
    registry = json.loads((OUT / "construction_exclusion_sources.json").read_text())
    if mutation == "qualification_collision":
        qualification = json.loads((OUT / "nonblind_qualification_inputs.jsonl").open(encoding="utf-8").readline())
        inputs[0]["candidate_input"]["query"] = qualification["query"]
    elif mutation == "duplicate_case_id":
        inputs[1]["case_id"] = inputs[0]["case_id"]
        gold[1]["case_id"] = gold[0]["case_id"]
    else:
        inputs[1]["candidate_input"] = deepcopy(inputs[0]["candidate_input"])
    report = audit_exclusions(ROOT, registry, inputs, gold, load_corpus(ROOT / "rag/gk_corpus"))
    assert report["status"] == "FAIL" and report["violations"] > 0


def test_blindness_candidate_output_and_evaluation_contamination(tmp_path: Path) -> None:
    inputs, gold = author_cases(shadow_labels(), namespace="t23-shadow",
                                attachment_path="documents/shadow.txt")
    provenance = synthetic_provenance()
    provenance["candidate_outputs_read"] = 1
    report = audit_blindness(tmp_path, inputs, gold, provenance, real=False)
    assert report["candidate_leakage"] == 1 and report["status"] == "FAIL"
    provenance = synthetic_provenance()
    future = tmp_path / "evaluations/t23/raw_results.jsonl"
    future.parent.mkdir(parents=True)
    future.write_text("", encoding="utf-8")
    report = audit_blindness(tmp_path, inputs, gold, provenance, real=False)
    assert report["future_evaluation_leakage"] == 1 and report["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["wrong_family_count", "wrong_total_rows", "missing_family"])
def test_gate_design_controls(shadow: Path, tmp_path: Path, mutation: str) -> None:
    material = tmp_path / "material"
    shutil.copytree(shadow, material)
    out = material / "evaluations/t23"
    (out / "holdout_manifest.json").unlink()
    (out / "HOLDOUT_FROZEN").unlink()
    ledger_path = out / "construction_run_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["events"].pop()
    ledger["state"] = "AUDITED"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    design = load_t23_contract(OUT / "t23_master_contract.json").get("construction_design")
    family_path = material / next(iter(design["suite_mapping"].values()))
    if mutation == "wrong_family_count":
        family_path.write_text("\n".join(family_path.read_text(encoding="utf-8").splitlines()[:-1]) + "\n",
                               encoding="utf-8")
    elif mutation == "wrong_total_rows":
        inputs_path = out / "suites/inputs.jsonl"
        inputs_path.write_text("\n".join(inputs_path.read_text(encoding="utf-8").splitlines()[:-1]) + "\n",
                               encoding="utf-8")
    else:
        family_path.unlink()
    with pytest.raises(ValueError):
        run_construction_gate(ROOT, material, real=False, namespace="t23-shadow")


def test_manifest_missing_artifact_and_seal_root_mismatch(shadow: Path, tmp_path: Path) -> None:
    material = tmp_path / "material"
    shutil.copytree(shadow, material)
    suite = material / "evaluations/t23/suites/families/ambiguous_route.jsonl"
    suite.unlink()
    with pytest.raises(ValueError):
        verify_seal(ROOT, material)
    shutil.copy2(shadow / "evaluations/t23/suites/families/ambiguous_route.jsonl", suite)
    marker_path = material / "evaluations/t23/HOLDOUT_FROZEN"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["freeze_root"] = "0" * 64
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        verify_seal(ROOT, material)


def test_unknown_construction_state_and_author_lock_refused(shadow: Path, tmp_path: Path) -> None:
    ledger = json.loads((shadow / "evaluations/t23/construction_run_ledger.json").read_text())
    ledger["state"] = "UNKNOWN"
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(LedgerError):
        verify_ledger(path)
    lock = json.loads((OUT / "author_lock.json").read_text())
    lock["candidate_commit"] = "0" * 40
    lock_path = tmp_path / "author_lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_lock(lock_path)


def test_unknown_lifecycle_state_refused(tmp_path: Path) -> None:
    registry = json.loads((OUT / "experiment_lifecycle_registry.json").read_text())
    registry["experiments"]["t23"]["state"] = "UNKNOWN"
    path = tmp_path / "evaluations/t23/experiment_lifecycle_registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(registry), encoding="utf-8")
    report = verify_lifecycle(tmp_path, "t23")
    assert report["status"] == "FAIL" and report["state"] == "UNKNOWN"


def test_static_audit_wrong_total_and_missing_family() -> None:
    inputs, gold = author_cases(shadow_labels(), namespace="t23-shadow",
                                attachment_path="documents/shadow.txt")
    spec = json.loads((OUT / "author_specification.json").read_text())
    corpus = load_corpus(ROOT / "rag/gk_corpus")
    with pytest.raises(ValueError):
        run_construction_audits(inputs[:-1], gold[:-1], corpus, spec)
    missing = [row for row in gold if row["family"] != "ambiguous_route"]
    with pytest.raises(ValueError):
        run_construction_audits(inputs[:len(missing)], missing, corpus, spec)
