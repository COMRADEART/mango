"""Mechanical seal-protocol controls for the T21R8 blind holdout.

Every control runs against a synthetic fixture tree (temp directories).
NO real T21R8 blind row is constructed, no blind world is generated, and
no production-runtime function is executed: the seal script is exercised
only at the boundaries where it must refuse (existing seal artifacts,
frozen-identity drift, missing/failed data-only audits, annotation
violations, gate failures, wrong physical holdout shape) or where it must
write exactly holdout_manifest.json + HOLDOUT_FROZEN and nothing else.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r8_construction_audit as construction_audit  # noqa: E402
import t21r8_freeze_holdout as seal  # noqa: E402


REPO_OUT = ROOT / "evaluations" / "t21r8"
CONTRACT = json.loads(
    (REPO_OUT / "holdout_construction_contract.json").read_text(
        encoding="utf-8"))
SUITES = [(name, rule["suite_id"], rule["minimum"])
          for name, rule in CONTRACT["suite_target_minimums"].items()]
FIXTURE_HEAD = "f" * 40
FIXTURE_TREE = "a" * 40

IE_CONFIGS = [
    "missing_start_entity", "missing_hop1", "missing_hop2",
    "wrong_bridge_identity", "near_name_start_entity",
    "near_name_bridge_entity", "wrong_relation",
    "same_entity_wrong_attribute", "partial_path_only",
    "unrelated_conflict", "relevant_unresolved_conflict",
]
MILESTONES = ["T21", "T21R", "T21R2", "T21R3", "T21R4", "T21R5", "T21R6",
              "T21R7"]
DIMENSIONS = [
    "case_ids", "entity_identities", "source_ids", "chunk_ids",
    "exact_queries", "exact_answers", "exact_source_text", "verbatim_attacks",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _passing_metrics(contract: dict) -> dict:
    """A metrics document that satisfies every construction requirement of
    ``contract`` (same shape the frozen gate accepts)."""
    return {
        "annotation_violations": 0,
        "total_rows": sum(rule["minimum"]
                          for rule in contract["suite_target_minimums"]
                          .values()),
        "suite_rows": {
            name: rule["minimum"]
            for name, rule in contract["suite_target_minimums"].items()
        },
        "stresses": {
            "multihop_rows": 800,
            "multihop_chain_families": 14,
            "multihop_largest_family_count": 80,
            "multihop_largest_chain_family_share": 0.10,
            "multihop_surface_mismatch_rows": 500,
            "crossdomain_rows": 700,
            "crossdomain_two_source_two_domain_rows": 700,
            "domain_pair_families": 6,
            "largest_domain_pair_count": 140,
            "largest_domain_pair_share": 0.20,
            "multisource_path_rows": 1200,
            "partial_path_ie_rows": 320,
            "ie_configurations": {name: 10 for name in IE_CONFIGS},
            "relation_surface_sensitive_rows": 900,
            "canonical_relations": [f"RELATION_{index:02d}"
                                    for index in range(18)],
            "relation_surface_mismatch_rows": 500,
            "source_injection_safe_fact_rows": 300,
            "safe_fact_with_directive_rows": 180,
            "query_injection_or_spoof_rows": 300,
        },
        "independence": {
            milestone: {dimension: 0 for dimension in DIMENSIONS}
            for milestone in MILESTONES
        },
    }


# Runtime-directory stubs: every composite group must resolve (directories
# exist so the recursive hash walks them) with tiny placeholder files.
_SRC_STUBS = (
    "src/sciencemath/knowledge/__init__.py",
    "src/sciencemath/knowledge/injection.py",
    "src/sciencemath/knowledge/provenance_spoof.py",
    "src/sciencemath/executive/skills.py",
    "src/sciencemath/executive/executive_router.py",
    "src/sciencemath/executive/correction.py",
    "src/sciencemath/executive/verify.py",
    "src/sciencemath/executive/repair.py",
    "src/sciencemath/executive/replan.py",
    "src/sciencemath/executive/state.py",
    "src/sciencemath/rag/__init__.py",
    "src/sciencemath/web/__init__.py",
    "src/sciencemath/document/__init__.py",
    "src/sciencemath/memory/__init__.py",
    "src/sciencemath/planning/__init__.py",
    "src/sciencemath/orchestration/__init__.py",
    "src/sciencemath/scicomp/__init__.py",
    "src/sciencemath/code/__init__.py",
    "tests/test_historical_artifact_write_guard.py",
)


def _build_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    out = root / "evaluations" / "t21r8"
    out.mkdir(parents=True)
    scripts = root / "scripts"
    scripts.mkdir()
    shutil.copy(
        ROOT / "scripts" / "t21r4_freeze_runtime.py",
        scripts / "t21r4_freeze_runtime.py",
    )
    for rel in _SRC_STUBS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixture stub {rel}\n", encoding="utf-8")
    (root / "scripts" / "t15r_mutation_probe.py").write_text(
        "# fixture probe\n", encoding="utf-8")
    for name in ("t21r8_run_eval.py", "t21r8_official_eval.py",
                 "t21r8_freeze_holdout.py", *seal.BUILDER_SCRIPTS):
        (scripts / name).write_text(f"fixture {name}\n", encoding="utf-8")
    for name in ("scoring_semantics.json", "validation_contract.json",
                 "holdout_construction_contract.json"):
        shutil.copy(REPO_OUT / name, out / name)
    _write_json(out / "evaluator_qualification.json",
                {"qualification_passed": True})
    corpus = root / "rag" / "gk_holdout_t21r8"
    corpus.mkdir(parents=True)
    (corpus / "world.jsonl").write_text(
        '{"entity_id": "fx-1"}\n{"entity_id": "fx-2"}\n',
        encoding="utf-8")
    (corpus / "sources.jsonl").write_text(
        '{"source_id": "fx-src-1"}\n', encoding="utf-8")
    (corpus / "chunks.jsonl").write_text(
        '{"chunk_id": "fx-chunk-1", "text": "fixture"}\n', encoding="utf-8")
    _write_json(corpus / "corpus_manifest.json", {"corpus": "fixture"})
    for _short, suite_id, count in SUITES:
        suite_dir = out / "suites" / suite_id
        suite_dir.mkdir(parents=True)
        rows = "\n".join(
            json.dumps({"case_id": f"fx-{suite_id}-{index:04d}"})
            for index in range(count)) + "\n"
        (suite_dir / "holdout.jsonl").write_text(rows, encoding="utf-8")
    return root


def _write_freezes(root: Path) -> None:
    """Synthetic runtime + evaluator freezes whose recorded identities are
    exactly the fixture files (same trust shape as the real freezes)."""
    out = root / "evaluations" / "t21r8"
    runtime_freeze = {
        "recorded_at": "2026-01-01T00:00:00+00:00",
        "git_head": FIXTURE_HEAD,
        "git_tree_sha": FIXTURE_TREE,
        "runtime_composites": seal._composites(root),
        "validation_contract_sha256": _sha(out / "validation_contract.json"),
        "holdout_construction_contract_sha256": _sha(
            out / "holdout_construction_contract.json"),
        "scoring_semantics_file_sha256": _sha(
            out / "scoring_semantics.json"),
    }
    _write_json(out / "runtime_freeze.json", runtime_freeze)
    _write_json(out / "evaluator_freeze.json", {
        "recorded_at": "2026-01-01T00:00:00+00:00",
        "frozen_hashes": {
            "evaluator_source_sha256": _sha(
                root / "scripts" / "t21r8_run_eval.py"),
            "official_runner_sha256": _sha(
                root / "scripts" / "t21r8_official_eval.py"),
            "validation_contract_sha256":
                runtime_freeze["validation_contract_sha256"],
            "construction_contract_sha256":
                runtime_freeze["holdout_construction_contract_sha256"],
            "qualification_artifact_sha256": _sha(
                out / "evaluator_qualification.json"),
            "runtime_freeze_sha256": _sha(out / "runtime_freeze.json"),
            "builder_audit_scripts_sha256": {
                script: _sha(root / "scripts" / script)
                for script in seal.BUILDER_SCRIPTS
            },
        },
    })


def _anchor_fixture_roots(root: Path, monkeypatch) -> None:
    """Make the synthetic freeze/helper bytes the preregistered test roots."""
    out = root / "evaluations" / "t21r8"
    monkeypatch.setattr(
        seal, "EXPECTED_RUNTIME_FREEZE_SHA256",
        _sha(out / "runtime_freeze.json"))
    monkeypatch.setattr(
        seal, "EXPECTED_EVALUATOR_FREEZE_SHA256",
        _sha(out / "evaluator_freeze.json"))
    monkeypatch.setattr(
        seal, "EXPECTED_RUNTIME_HASH_HELPER_SHA256",
        _sha(root / "scripts" / "t21r4_freeze_runtime.py"))


def _record_fixture_world_identity(root: Path, monkeypatch) -> dict:
    """Add and root-anchor preserved-world metadata for the fixture."""
    path = root / "evaluations" / "t21r8" / "evaluator_freeze.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    corpus = root / "rag" / "gk_holdout_t21r8"
    document["construction_infrastructure_amendment"] = {
        "preserved_world_sha256": {
            name: _sha(corpus / name) for name in seal.CORPUS_FILES
        },
    }
    _write_json(path, document)
    _anchor_fixture_roots(root, monkeypatch)
    return document


def _write_audits(root: Path, metrics: dict, static_status: str = "PASS",
                  static_executions: int = 0, uniqueness_verdict: str =
                  "UNIQUE", uniqueness_executions: int = 0,
                  blindness_status: str = "PASS", blindness_exposures: int =
                  0) -> None:
    out = root / "evaluations" / "t21r8"
    _write_json(out / "static_gold_audit.json", {
        "status": static_status,
        "runtime_execution_count": static_executions,
        "construction_contract": {
            "metrics": metrics,
            "checks": [],
            "requirements_evaluated": 0,
            "requirements_passed": 0,
            "status": "PASS",
        },
    })
    _write_json(out / "holdout_uniqueness.json", {
        "verdict": uniqueness_verdict,
        "runtime_execution_count": uniqueness_executions,
    })
    _write_json(out / "blindness_audit.json", {
        "status": blindness_status,
        "official_runtime_exposures_before_freeze": blindness_exposures,
    })


def _prepare(tmp_path: Path, monkeypatch, metrics: dict | None = None,
             violations: list | None = None) -> Path:
    """Full happy-path fixture: freezes, audits, corpus, suites, and a
    monkeypatched construction remeasurement (no runtime code executes)."""
    root = _build_root(tmp_path)
    _write_freezes(root)
    _anchor_fixture_roots(root, monkeypatch)
    if metrics is None:
        metrics = _passing_metrics(
            json.loads((root / "evaluations" / "t21r8"
                        / "holdout_construction_contract.json")
                       .read_text(encoding="utf-8")))
    _write_audits(root, metrics)
    monkeypatch.setattr(
        construction_audit, "measure_candidate",
        lambda root: {"metrics": metrics,
                      "annotation_violation_details": violations or []})
    return root


# ---------------------------------------------------------------------------
# Root-of-trust anchors (controls A-G).
# ---------------------------------------------------------------------------


def test_root_anchor_exact_frozen_artifacts_and_helper_pass() -> None:
    # Control A: the three audited repository roots and all deeper frozen
    # identities pass together.
    out = ROOT / "evaluations" / "t21r8"
    assert _sha(out / "runtime_freeze.json") == (
        seal.EXPECTED_RUNTIME_FREEZE_SHA256)
    assert _sha(out / "evaluator_freeze.json") == (
        seal.EXPECTED_EVALUATOR_FREEZE_SHA256)
    assert _sha(ROOT / "scripts" / "t21r4_freeze_runtime.py") == (
        seal.EXPECTED_RUNTIME_HASH_HELPER_SHA256)
    runtime_freeze, evaluator_freeze = seal.verify_frozen_identity(ROOT)
    assert len(runtime_freeze["runtime_composites"]) == 14
    assert "frozen_hashes" in evaluator_freeze


def test_root_anchor_evaluator_source_alias_matches_frozen_hash() -> None:
    # Compatibility control: the frozen runner's top-level lookup and the
    # canonical nested evaluator identity must authorize the same bytes.
    path = ROOT / "evaluations" / "t21r8" / "evaluator_freeze.json"
    evaluator_freeze = json.loads(path.read_text(encoding="utf-8"))
    assert evaluator_freeze["evaluator_source_sha256"] == (
        evaluator_freeze["frozen_hashes"]["evaluator_source_sha256"])
    assert evaluator_freeze["evaluator_source_sha256"] == _sha(
        ROOT / "scripts" / "t21r8_run_eval.py")


def test_root_anchor_refuses_modified_evaluator_freeze_bytes(
    tmp_path, monkeypatch,
) -> None:
    # Control B: even semantically inert byte drift is refused.
    root = _prepare(tmp_path, monkeypatch)
    path = root / "evaluations" / "t21r8" / "evaluator_freeze.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(SystemExit, match="evaluator_freeze.json SHA-256"):
        seal.verify_frozen_identity(root)


def test_root_anchor_refuses_self_consistent_evaluator_rewrite(
    tmp_path, monkeypatch,
) -> None:
    # Control C: changing the evaluator and its hash inside the evaluator
    # freeze cannot establish a new root.
    root = _prepare(tmp_path, monkeypatch)
    evaluator = root / "scripts" / "t21r8_run_eval.py"
    evaluator.write_text("correspondingly modified evaluator\n",
                         encoding="utf-8")
    path = root / "evaluations" / "t21r8" / "evaluator_freeze.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["frozen_hashes"]["evaluator_source_sha256"] = _sha(evaluator)
    _write_json(path, document)
    with pytest.raises(SystemExit, match="evaluator_freeze.json SHA-256"):
        seal.verify_frozen_identity(root)


def test_root_anchor_refuses_modified_runtime_freeze_bytes(
    tmp_path, monkeypatch,
) -> None:
    # Control D.
    root = _prepare(tmp_path, monkeypatch)
    path = root / "evaluations" / "t21r8" / "runtime_freeze.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(SystemExit, match="runtime_freeze.json SHA-256"):
        seal.verify_frozen_identity(root)


def test_root_anchor_refuses_coordinated_freeze_rewrite(
    tmp_path, monkeypatch,
) -> None:
    # Control E: updating the runtime freeze and its evaluator-freeze pointer
    # changes both pinned roots and is still refused.
    root = _prepare(tmp_path, monkeypatch)
    out = root / "evaluations" / "t21r8"
    runtime_path = out / "runtime_freeze.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["tampered"] = True
    _write_json(runtime_path, runtime)
    evaluator_path = out / "evaluator_freeze.json"
    evaluator = json.loads(evaluator_path.read_text(encoding="utf-8"))
    evaluator["frozen_hashes"]["runtime_freeze_sha256"] = _sha(runtime_path)
    _write_json(evaluator_path, evaluator)
    assert _sha(runtime_path) != seal.EXPECTED_RUNTIME_FREEZE_SHA256
    assert _sha(evaluator_path) != seal.EXPECTED_EVALUATOR_FREEZE_SHA256
    with pytest.raises(SystemExit, match="runtime_freeze.json SHA-256"):
        seal.verify_frozen_identity(root)


def test_root_anchor_refuses_modified_runtime_hash_helper(
    tmp_path, monkeypatch,
) -> None:
    # Control F.
    root = _prepare(tmp_path, monkeypatch)
    helper = root / "scripts" / "t21r4_freeze_runtime.py"
    helper.write_bytes(helper.read_bytes() + b"\n# modified\n")
    with pytest.raises(SystemExit, match="t21r4_freeze_runtime.py SHA-256"):
        seal.verify_frozen_identity(root)


def test_root_anchor_rejects_helper_before_weakened_composites_are_used(
    tmp_path, monkeypatch,
) -> None:
    # Control G: a modified helper cannot omit a group and exploit the
    # composite loop's dependence on the helper-defined group set.
    root = _prepare(tmp_path, monkeypatch)
    helper = root / "scripts" / "t21r4_freeze_runtime.py"
    helper.write_text(
        "RUNTIME_GROUPS = {}  # maliciously omitted all runtime groups\n",
        encoding="utf-8")
    composites_used = False

    def _weakened_composites(_root: Path) -> dict:
        nonlocal composites_used
        composites_used = True
        return {}

    monkeypatch.setattr(seal, "_composites", _weakened_composites)
    with pytest.raises(SystemExit, match="t21r4_freeze_runtime.py SHA-256"):
        seal.verify_frozen_identity(root)
    assert composites_used is False


# ---------------------------------------------------------------------------
# Adjudicated preserved-world enforcement.
# ---------------------------------------------------------------------------


def test_matching_preserved_world_hashes_are_allowed(
    tmp_path, monkeypatch,
) -> None:
    root = _prepare(tmp_path, monkeypatch)
    evaluator_freeze = _record_fixture_world_identity(root, monkeypatch)
    seal.verify_preserved_world_identity(root, evaluator_freeze)


@pytest.mark.parametrize("name", seal.CORPUS_FILES)
def test_changed_preserved_world_file_refuses_seal(
    tmp_path, monkeypatch, name: str,
) -> None:
    root = _prepare(tmp_path, monkeypatch)
    evaluator_freeze = _record_fixture_world_identity(root, monkeypatch)
    path = root / "rag" / "gk_holdout_t21r8" / name
    path.write_bytes(path.read_bytes() + b"\nchanged\n")
    with pytest.raises(SystemExit, match="FROZEN_IDENTITY_VIOLATION"):
        seal.verify_preserved_world_identity(root, evaluator_freeze)


# ---------------------------------------------------------------------------
# Entry refusals (controls 1-3).
# ---------------------------------------------------------------------------


def test_refuses_existing_holdout_manifest(tmp_path, monkeypatch) -> None:
    # Control 1: the holdout seals exactly once.
    root = _prepare(tmp_path, monkeypatch)
    manifest = root / "evaluations" / "t21r8" / "holdout_manifest.json"
    manifest.write_text("premature\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="FREEZE_ORDER_VIOLATION"):
        seal.main(root)


def test_refuses_existing_holdout_marker(tmp_path, monkeypatch) -> None:
    # Control 2: HOLDOUT_FROZEN already present refuses.
    root = _prepare(tmp_path, monkeypatch)
    (root / "evaluations" / "t21r8" / "HOLDOUT_FROZEN").write_text(
        "premature\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="FREEZE_ORDER_VIOLATION"):
        seal.main(root)


@pytest.mark.parametrize("artifact", seal.EXPOSURE_ARTIFACTS)
def test_refuses_existing_exposure_artifact(
    tmp_path, monkeypatch, artifact: str,
) -> None:
    # Control 3: a begun one-shot exposure precedes any seal.
    root = _prepare(tmp_path, monkeypatch)
    (root / "evaluations" / "t21r8" / artifact).write_text(
        "exposure began\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exposure artifact"):
        seal.main(root)


# ---------------------------------------------------------------------------
# Frozen-identity enforcement (controls 4-10).
# ---------------------------------------------------------------------------


def test_refuses_missing_runtime_freeze(tmp_path, monkeypatch) -> None:
    # Control 4.
    root = _prepare(tmp_path, monkeypatch)
    (root / "evaluations" / "t21r8" / "runtime_freeze.json").unlink()
    with pytest.raises(SystemExit, match="FROZEN_IDENTITY_VIOLATION"):
        seal.main(root)


def test_refuses_missing_evaluator_freeze(tmp_path, monkeypatch) -> None:
    # Control 5.
    root = _prepare(tmp_path, monkeypatch)
    (root / "evaluations" / "t21r8" / "evaluator_freeze.json").unlink()
    with pytest.raises(SystemExit, match="FROZEN_IDENTITY_VIOLATION"):
        seal.main(root)


def test_refuses_runtime_composite_drift(tmp_path, monkeypatch) -> None:
    # Control 6: one drifted runtime group refuses the seal.
    root = _prepare(tmp_path, monkeypatch)
    out = root / "evaluations" / "t21r8"
    freeze = json.loads((out / "runtime_freeze.json").read_text(
        encoding="utf-8"))
    freeze["runtime_composites"]["security_layer"] = "0" * 64
    _write_json(out / "runtime_freeze.json", freeze)
    evaluator_path = out / "evaluator_freeze.json"
    evaluator = json.loads(evaluator_path.read_text(encoding="utf-8"))
    evaluator["frozen_hashes"]["runtime_freeze_sha256"] = _sha(
        out / "runtime_freeze.json")
    _write_json(evaluator_path, evaluator)
    _anchor_fixture_roots(root, monkeypatch)
    with pytest.raises(SystemExit, match="security_layer drifted"):
        seal.main(root)


def test_refuses_evaluator_source_drift(tmp_path, monkeypatch) -> None:
    # Control 7.
    root = _prepare(tmp_path, monkeypatch)
    (root / "scripts" / "t21r8_run_eval.py").write_text(
        "drifted\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="evaluator freeze"):
        seal.main(root)


def test_refuses_official_runner_drift(tmp_path, monkeypatch) -> None:
    # Control 8.
    root = _prepare(tmp_path, monkeypatch)
    (root / "scripts" / "t21r8_official_eval.py").write_text(
        "drifted\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="official-runner freeze"):
        seal.main(root)


@pytest.mark.parametrize("script", seal.BUILDER_SCRIPTS)
def test_refuses_builder_script_drift(tmp_path, monkeypatch,
                                      script: str) -> None:
    # Control 9: any of the seven builder/audit scripts drifting refuses.
    root = _prepare(tmp_path, monkeypatch)
    (root / "scripts" / script).write_text("drifted\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="builder/audit script"):
        seal.main(root)


@pytest.mark.parametrize("artifact", [
    "validation_contract.json",
    "holdout_construction_contract.json",
    "evaluator_qualification.json",
    "scoring_semantics.json",
    "runtime_freeze.json",
])
def test_refuses_frozen_artifact_drift(tmp_path, monkeypatch,
                                       artifact: str) -> None:
    # Control 10: any frozen contract/semantics/qualification/freeze
    # artifact drifting from its recorded identity refuses the seal.
    root = _prepare(tmp_path, monkeypatch)
    path = root / "evaluations" / "t21r8" / artifact
    if artifact.endswith(".json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        document["tampered"] = True
        _write_json(path, document)
    else:
        path.write_text("drifted\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="FROZEN_IDENTITY_VIOLATION"):
        seal.main(root)


# ---------------------------------------------------------------------------
# Data-only audit gates (controls 11-12).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("audit", [
    "static_gold_audit.json", "holdout_uniqueness.json",
    "blindness_audit.json",
])
def test_requires_all_three_data_only_audits(
    tmp_path, monkeypatch, audit: str,
) -> None:
    # Control 11: all three audits must exist before sealing.
    root = _prepare(tmp_path, monkeypatch)
    (root / "evaluations" / "t21r8" / audit).unlink()
    with pytest.raises(SystemExit, match="required audit missing"):
        seal.main(root)


@pytest.mark.parametrize("field,value", [
    ("static_status", "FAIL"),
    ("static_executions", 2),
    ("uniqueness_verdict", "OVERLAP_DETECTED"),
    ("uniqueness_executions", 3),
    ("blindness_status", "FAIL"),
    ("blindness_exposures", 1),
])
def test_refuses_non_passing_data_only_audits(
    tmp_path, monkeypatch, field: str, value,
) -> None:
    # Control 12: PASS / UNIQUE / PASS at zero recorded runtime activity.
    root = _build_root(tmp_path)
    _write_freezes(root)
    _anchor_fixture_roots(root, monkeypatch)
    metrics = _passing_metrics(
        json.loads((root / "evaluations" / "t21r8"
                    / "holdout_construction_contract.json")
                   .read_text(encoding="utf-8")))
    _write_audits(root, metrics, **{field: value})
    monkeypatch.setattr(
        construction_audit, "measure_candidate",
        lambda root: {"metrics": metrics,
                      "annotation_violation_details": []})
    with pytest.raises(SystemExit, match="SEAL_ENTRY_BLOCKED"):
        seal.main(root)


# ---------------------------------------------------------------------------
# Corpus + construction remeasurement (controls 13-16).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus_file", seal.CORPUS_FILES)
def test_refuses_missing_corpus_file(tmp_path, monkeypatch,
                                     corpus_file: str) -> None:
    # Control 13: all four corpus files must exist and parse.
    root = _prepare(tmp_path, monkeypatch)
    (root / "rag" / "gk_holdout_t21r8" / corpus_file).unlink()
    with pytest.raises(SystemExit, match="corpus file missing"):
        seal.main(root)


def test_refuses_recomputed_annotation_violations(
    tmp_path, monkeypatch,
) -> None:
    # Control 14: the remeasured construction audit must find zero
    # annotation violations.
    root = _prepare(tmp_path, monkeypatch, violations=[
        {"case_id": "fx-1", "violation": "declared path_required_sources "
                                        "differ from gold path edge "
                                        "sources"}])
    with pytest.raises(SystemExit, match="annotation violations"):
        seal.main(root)
    assert not (root / "evaluations" / "t21r8"
                / "holdout_manifest.json").exists()


def test_refuses_construction_gate_failure(tmp_path, monkeypatch) -> None:
    # Control 15: every construction requirement must pass on remeasurement.
    contract = copy.deepcopy(CONTRACT)
    contract["suite_target_minimums"]["multihop"]["minimum"] = 800
    metrics = _passing_metrics(contract)
    metrics["stresses"]["multihop_chain_families"] = 10  # below minimum 12
    root = _prepare(tmp_path, monkeypatch, metrics=metrics)
    with pytest.raises(SystemExit, match="construction gate failed"):
        seal.main(root)


def test_refuses_recomputed_metrics_mismatch(tmp_path, monkeypatch) -> None:
    # Control 16: recomputed metrics must exactly equal the metrics
    # embedded in static_gold_audit.json.
    metrics = _passing_metrics(CONTRACT)
    embedded = copy.deepcopy(metrics)
    embedded["stresses"]["multihop_chain_families"] = 13  # differs, passes
    root = _build_root(tmp_path)
    _write_freezes(root)
    _anchor_fixture_roots(root, monkeypatch)
    _write_audits(root, embedded)
    monkeypatch.setattr(
        construction_audit, "measure_candidate",
        lambda root: {"metrics": metrics,
                      "annotation_violation_details": []})
    with pytest.raises(SystemExit, match="metrics differ"):
        seal.main(root)


# ---------------------------------------------------------------------------
# Exact physical holdout shape (controls 17-20).
# ---------------------------------------------------------------------------


def test_refuses_contract_minimums_differing_from_exact_shape(
    tmp_path, monkeypatch,
) -> None:
    # Control 17: the contract's suite minimums must equal the
    # preregistered exact shape (4800 = 600+550+800+700+450+800+250+650).
    root = _build_root(tmp_path)
    out = root / "evaluations" / "t21r8"
    contract = copy.deepcopy(CONTRACT)
    contract["suite_target_minimums"]["retrieval"]["minimum"] = 650
    contract["suite_target_minimums"]["singlehop"]["minimum"] = 500
    _write_json(out / "holdout_construction_contract.json", contract)
    _write_freezes(root)
    _anchor_fixture_roots(root, monkeypatch)
    metrics = _passing_metrics(contract)
    _write_audits(root, metrics)
    monkeypatch.setattr(
        construction_audit, "measure_candidate",
        lambda root: {"metrics": metrics,
                      "annotation_violation_details": []})
    with pytest.raises(SystemExit, match="exact holdout shape"):
        seal.main(root)


def test_refuses_wrong_suite_directory_set(tmp_path, monkeypatch) -> None:
    # Control 18: exactly the eight expected suite IDs may exist.
    root = _prepare(tmp_path, monkeypatch)
    extra = (root / "evaluations" / "t21r8" / "suites" / "fx-extra-suite")
    extra.mkdir()
    (extra / "holdout.jsonl").write_text('{"case_id": "fx-e-0"}\n',
                                         encoding="utf-8")
    with pytest.raises(SystemExit, match="suite directories"):
        seal.main(root)


def test_refuses_wrong_suite_row_count(tmp_path, monkeypatch) -> None:
    # Control 19: each suite must hold exactly its preregistered count
    # (NOT merely the minimum).
    root = _prepare(tmp_path, monkeypatch)
    short, suite_id, count = next(s for s in SUITES if s[0] == "singlehop")
    assert count == 550
    path = (root / "evaluations" / "t21r8" / "suites" / suite_id
            / "holdout.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly 550 are required"):
        seal.main(root)


def test_refuses_missing_suite_file(tmp_path, monkeypatch) -> None:
    # Control 20.
    root = _prepare(tmp_path, monkeypatch)
    _short, suite_id, _count = SUITES[0]
    (root / "evaluations" / "t21r8" / "suites" / suite_id
     / "holdout.jsonl").unlink()
    with pytest.raises(SystemExit, match="suite file missing"):
        seal.main(root)


# ---------------------------------------------------------------------------
# The seal itself (controls 21-22).
# ---------------------------------------------------------------------------


def test_seal_writes_manifest_and_marker_last(tmp_path, monkeypatch) -> None:
    # Control 21: the happy path writes exactly holdout_manifest.json and
    # HOLDOUT_FROZEN — and nothing else — with the marker anchoring the
    # exact manifest bytes.
    root = _prepare(tmp_path, monkeypatch)
    out = root / "evaluations" / "t21r8"
    assert seal.main(root) == 0

    manifest = json.loads(
        (out / "holdout_manifest.json").read_text(encoding="utf-8"))
    marker = json.loads((out / "HOLDOUT_FROZEN").read_text(encoding="utf-8"))
    assert manifest["holdout_total"] == 4800
    assert manifest["runtime_execution_count_before_freeze"] == 0
    assert manifest["one_shot_rule"] == seal.ONE_SHOT_RULE
    assert manifest["official_command"] == "python scripts/t21r8_official_eval.py"
    assert marker["HOLDOUT_FROZEN"] is True
    assert marker["holdout_manifest_sha256"] == _sha(
        out / "holdout_manifest.json")
    assert marker["holdout_total"] == 4800
    assert marker["runtime_freeze_sha256"] == manifest["freeze_inputs"][
        "runtime_freeze"]["sha256"]

    freeze_inputs = manifest["freeze_inputs"]
    for name in ("runtime_freeze", "evaluator_freeze",
                 "runtime_hash_helper", "validation_contract",
                 "construction_contract", "scoring_semantics",
                 "evaluator_qualification", "official_runner", "evaluator",
                 "static_gold_audit", "holdout_uniqueness",
                 "blindness_audit", "seal_script",
                 *(f"builder_{script}" for script in seal.BUILDER_SCRIPTS)):
        entry = freeze_inputs[name]
        assert entry["sha256"] == _sha(root / entry["path"]), name
    helper = freeze_inputs["runtime_hash_helper"]
    assert helper["path"] == "scripts/t21r4_freeze_runtime.py"
    assert helper["sha256"] == seal.EXPECTED_RUNTIME_HASH_HELPER_SHA256
    assert len(freeze_inputs) == 13 + len(seal.BUILDER_SCRIPTS)

    assert set(manifest["corpus"]) == set(seal.CORPUS_FILES)
    for name, entry in manifest["corpus"].items():
        assert entry["sha256"] == _sha(root / entry["path"])

    expected_suite_ids = {suite_id for _short, suite_id, _count in SUITES}
    assert set(manifest["suites"]) == expected_suite_ids
    for short, suite_id, count in SUITES:
        record = manifest["suites"][suite_id]
        assert record["short_name"] == short
        assert record["suite_id"] == suite_id
        assert record["exact_rows"] == count
        assert record["rows"] == count
        assert record["sha256"] == _sha(root / record["path"])

    # The seal constructs NOTHING beyond the two freeze artifacts.
    for artifact in seal.EXPOSURE_ARTIFACTS:
        assert not (out / artifact).exists()
    # The seal does not modify any frozen file.
    freeze = json.loads((out / "runtime_freeze.json").read_text(
        encoding="utf-8"))
    assert seal._composites(root) == freeze["runtime_composites"]

    # The seal script is data-only: no evaluator/runtime import and no
    # production-runtime call anywhere in its source.
    source = (ROOT / "scripts" / "t21r8_freeze_holdout.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            assert not name.startswith(("t21r8_run_eval",
                                        "t21r8_official_eval",
                                        "sciencemath")), name
    forbidden_calls = ("answer_knowledge", "run_answer_row",
                       "run_retrieval_row", "load_corpus", "retrieve",
                       "detect_conflicts", "classify_injection",
                       "resolve_citations", "parse_relation_path")
    for call in forbidden_calls:
        assert f"{call}(" not in source, call


def test_marker_write_failure_leaves_seal_incomplete(
    tmp_path, monkeypatch,
) -> None:
    # Control 22: manifest written + marker failure = T21R8_HOLDOUT_SEAL_
    # INCOMPLETE; no silent rerun, marker stays absent.
    root = _prepare(tmp_path, monkeypatch)
    out = root / "evaluations" / "t21r8"

    def _fail(out_dir: Path, marker: dict) -> None:
        raise OSError("simulated marker write failure")

    monkeypatch.setattr(seal, "_write_marker", _fail)
    with pytest.raises(SystemExit, match="T21R8_HOLDOUT_SEAL_INCOMPLETE"):
        seal.main(root)
    assert (out / "holdout_manifest.json").exists()
    assert not (out / "HOLDOUT_FROZEN").exists()
