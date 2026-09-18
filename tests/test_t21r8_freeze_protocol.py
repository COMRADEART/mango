"""Mechanical freeze-protocol controls for T21R8.

Every control runs against a synthetic fixture tree (temp directories).
NO real T21R8 holdout row is constructed and no blind world is generated:
the freeze scripts are exercised only at the boundary where they must
refuse (blind material present, stale/failed precheck, registry drift,
T15R drift, ordering violations) or record the identity of the files the
fixture provides.
"""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import t21r8_freeze_evaluator as freeze_evaluator  # noqa: E402
import t21r8_freeze_runtime as freeze_runtime  # noqa: E402


REPO_OUT = ROOT / "evaluations" / "t21r8"

FIXTURE_HEAD = "f" * 40
FIXTURE_TREE = "a" * 40
# The stub probe's git hash-object value: identical to the module constant
# in the happy path, so test 7 can drift the constant alone.
FIXTURE_PROBE_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _fake_git(args: list[str], root: Path) -> str:
    """Git stub: fixture HEAD/tree, the real T15R blob, full lineage log."""
    if args[:2] == ["rev-parse", "HEAD^{tree}"]:
        return FIXTURE_TREE
    if args[:2] == ["rev-parse", "HEAD"]:
        return FIXTURE_HEAD
    if args[0] == "hash-object":
        return FIXTURE_PROBE_BLOB
    if args[0] == "log":
        return "\n".join(freeze_runtime.LINEAGE.values())
    raise AssertionError(f"unexpected git call: {args}")


def _build_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    out = root / "evaluations" / "t21r8"
    out.mkdir(parents=True)
    scripts = root / "scripts"
    scripts.mkdir()
    (root / "evaluations" / "t15r").mkdir(parents=True)
    for name in ("scoring_semantics.json", "validation_contract.json",
                 "holdout_construction_contract.json"):
        shutil.copy(REPO_OUT / name, out / name)
    (root / "evaluations" / "t15r" / "mutation_safety_probe.json").write_text(
        "probe\n", encoding="utf-8")
    for script in ("t21r8_run_eval.py", "t21r8_official_eval.py",
                   *freeze_evaluator.BUILDER_SCRIPTS):
        (scripts / script).write_text(f"fixture {script}\n",
                                      encoding="utf-8")
    qualification = json.loads(
        (REPO_OUT / "evaluator_qualification.json").read_text(
            encoding="utf-8"))
    qualification["evaluator_source_sha256"] = _sha(
        root / "scripts" / "t21r8_run_eval.py")
    _write_json(out / "evaluator_qualification.json", qualification)
    return root


def _registry_stub(root: Path) -> dict:
    return {
        "availability": "EXPERIMENTAL",
        "registry_sha256": "b" * 64,
        "skills_py_sha256_lf": "c" * 64,
        "counts": {"EXPERIMENTAL": 26},
    }


def _write_precheck(root: Path, head: str, **overrides) -> None:
    document = {
        "status": "PASS",
        "command": "python -m pytest",
        "tested_head": head,
        "tested_branch": "t21r8-knowledge-rag-multisource-closure",
        "collected": 2914,
        "passed": 2912,
        "skipped": 2,
        "failed": 0,
        "errors": 0,
        "exit_code": 0,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "states": {
            "KNOWLEDGE_RAG": "EXPERIMENTAL",
            "Executive_Router": "EXPERIMENTAL",
            "T21": "OPEN",
            "T22": "BLOCKED",
        },
        "blind_artifacts_absent": True,
    }
    document.update(overrides)
    _write_json(root / "evaluations" / "t21r8" / "freeze_precheck.json",
                document)


def _run_runtime_freeze(root: Path, monkeypatch) -> dict:
    monkeypatch.setattr(freeze_runtime, "_registry_record", _registry_stub)
    assert freeze_runtime.main(root, git_fn=_fake_git) == 0
    return json.loads(
        (root / "evaluations" / "t21r8" / "runtime_freeze.json")
        .read_text(encoding="utf-8"))


def _write_runtime_freeze(root: Path) -> None:
    _write_json(root / "evaluations" / "t21r8" / "runtime_freeze.json", {
        "recorded_at": "2026-01-01T00:00:00+00:00",
        "git_head": FIXTURE_HEAD,
        "git_tree_sha": FIXTURE_TREE,
        "runtime_composites": {name: "0" * 64 for name in
                               freeze_runtime.RUNTIME_GROUPS},
    })


def _run_evaluator_freeze(root: Path, monkeypatch) -> dict:
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    assert freeze_evaluator.main(root) == 0
    return json.loads(
        (root / "evaluations" / "t21r8" / "evaluator_freeze.json")
        .read_text(encoding="utf-8"))


def _qualification(root: Path) -> dict:
    return json.loads(
        (root / "evaluations" / "t21r8" / "evaluator_qualification.json")
        .read_text(encoding="utf-8"))


def _write_qualification(root: Path, document: dict) -> None:
    _write_json(
        root / "evaluations" / "t21r8" / "evaluator_qualification.json",
        document)


# ---------------------------------------------------------------------------
# Runtime freeze refusals (controls 1-7).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blind_rel", freeze_runtime.BLIND_MATERIAL)
def test_runtime_freeze_refuses_blind_material(
    tmp_path: Path, monkeypatch, blind_rel: str,
) -> None:
    # Controls 1-4: corpus, HOLDOUT_FROZEN, holdout manifest, exposure
    # artifacts — none may exist when the runtime freezes.
    root = _build_root(tmp_path)
    _write_precheck(root, FIXTURE_HEAD)
    path = root / blind_rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("premature blind material\n", encoding="utf-8")
    monkeypatch.setattr(freeze_runtime, "_registry_record", _registry_stub)
    with pytest.raises(SystemExit, match="blind material"):
        freeze_runtime.main(root, git_fn=_fake_git)
    assert not (root / "evaluations" / "t21r8" / "runtime_freeze.json") \
        .exists()


def test_runtime_freeze_refuses_failed_or_stale_precheck(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 5: missing / failed / failing / stale-head precheck.
    root = _build_root(tmp_path)
    monkeypatch.setattr(freeze_runtime, "_registry_record", _registry_stub)
    with pytest.raises(SystemExit, match="freeze_precheck.json is missing"):
        freeze_runtime.main(root, git_fn=_fake_git)
    _write_precheck(root, FIXTURE_HEAD, status="FAIL")
    with pytest.raises(SystemExit, match="not PASS"):
        freeze_runtime.main(root, git_fn=_fake_git)
    _write_precheck(root, FIXTURE_HEAD, failed=1)
    with pytest.raises(SystemExit, match="not clean"):
        freeze_runtime.main(root, git_fn=_fake_git)
    _write_precheck(root, FIXTURE_HEAD, errors=2)
    with pytest.raises(SystemExit, match="not clean"):
        freeze_runtime.main(root, git_fn=_fake_git)
    _write_precheck(root, "e" * 40)  # stale: tested_head != current HEAD
    with pytest.raises(SystemExit, match="tested_head"):
        freeze_runtime.main(root, git_fn=_fake_git)
    assert not (root / "evaluations" / "t21r8" / "runtime_freeze.json") \
        .exists()


def test_runtime_freeze_requires_knowledge_rag_experimental(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 6: the live registry must still say EXPERIMENTAL.
    root = _build_root(tmp_path)
    _write_precheck(root, FIXTURE_HEAD)

    def _promoted(root: Path) -> dict:
        record = _registry_stub(root)
        record["availability"] = "ACTIVE"
        return record

    monkeypatch.setattr(freeze_runtime, "_registry_record", _promoted)
    with pytest.raises(SystemExit, match="EXPERIMENTAL"):
        freeze_runtime.main(root, git_fn=_fake_git)


def test_runtime_freeze_checks_t15r_canonical_blob(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 7: a drifted T15R probe blob refuses the freeze.
    root = _build_root(tmp_path)
    _write_precheck(root, FIXTURE_HEAD)
    monkeypatch.setattr(freeze_runtime, "_registry_record", _registry_stub)
    monkeypatch.setattr(freeze_runtime, "T15R_BLOB", "d" * 64)
    with pytest.raises(SystemExit, match="T15R canonical blob drifted"):
        freeze_runtime.main(root, git_fn=_fake_git)


def test_runtime_freeze_records_full_identity(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _build_root(tmp_path)
    _write_precheck(root, FIXTURE_HEAD)
    document = _run_runtime_freeze(root, monkeypatch)
    assert document["git_head"] == FIXTURE_HEAD
    assert document["git_tree_sha"] == FIXTURE_TREE
    assert set(document["runtime_composites"]) == \
        set(freeze_runtime.RUNTIME_GROUPS)
    assert len(document["runtime_composites"]) == 14
    assert document["knowledge_rag_registry"]["availability"] == \
        "EXPERIMENTAL"
    assert document["executive_router_status"] == "EXPERIMENTAL (unchanged)"
    assert document["t15r_canonical_blob"] == freeze_runtime.T15R_BLOB
    assert document["freeze_precheck_sha256"] == _sha(
        root / "evaluations" / "t21r8" / "freeze_precheck.json")
    for field in ("validation_contract_sha256",
                  "holdout_construction_contract_sha256",
                  "scoring_semantics_file_sha256",
                  "official_runner_sha256"):
        assert document[field]
    assert set(document["lineage"].values()) == \
        set(freeze_runtime.LINEAGE.values())


# ---------------------------------------------------------------------------
# Evaluator freeze (controls 8-13).
# ---------------------------------------------------------------------------


def test_evaluator_freeze_refuses_without_runtime_freeze(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 8: runtime_freeze.json must exist and validate first.
    root = _build_root(tmp_path)
    _write_precheck(root, FIXTURE_HEAD)
    _run_runtime_freeze(root, monkeypatch)
    (root / "evaluations" / "t21r8" / "runtime_freeze.json").unlink()
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    with pytest.raises(SystemExit, match="runtime must freeze"):
        freeze_evaluator.main(root)
    assert not (root / "evaluations" / "t21r8" / "evaluator_freeze.json") \
        .exists()


def test_evaluator_freeze_rejects_evaluator_source_mismatch(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 9: qualification source hash != scripts/t21r8_run_eval.py.
    root = _build_root(tmp_path)
    _write_runtime_freeze(root)
    qualification = _qualification(root)
    qualification["evaluator_source_sha256"] = "0" * 64
    _write_qualification(root, qualification)
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    with pytest.raises(SystemExit, match="qualification source hash differs"):
        freeze_evaluator.main(root)


def test_evaluator_freeze_rejects_scoring_semantics_mismatch(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 10: qualification semantics hash != evaluator canonical hash.
    root = _build_root(tmp_path)
    _write_runtime_freeze(root)
    qualification = _qualification(root)
    qualification["scoring_semantics_sha256"] = "0" * 64
    _write_qualification(root, qualification)
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    with pytest.raises(SystemExit, match="scoring-semantics identity"):
        freeze_evaluator.main(root)


def test_evaluator_freeze_rejects_qualification_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 11: any failed qualification gate refuses the freeze.
    root = _build_root(tmp_path)
    _write_runtime_freeze(root)
    for field in ("qualification_passed", "all_cases_pass",
                  "all_metric_paths_exercised"):
        qualification = _qualification(root)
        qualification[field] = False
        _write_qualification(root, qualification)
        monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                            lambda root: None)
        with pytest.raises(SystemExit, match="qualification gate"):
            freeze_evaluator.main(root)
    qualification = _qualification(root)
    qualification["uncaught_exceptions"] = 3
    _write_qualification(root, qualification)
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    with pytest.raises(SystemExit, match="qualification gate"):
        freeze_evaluator.main(root)


def test_evaluator_freeze_requires_exactly_32_floors(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 12: a 31-floor contract refuses the freeze.
    root = _build_root(tmp_path)
    _write_runtime_freeze(root)
    contract_path = root / "evaluations" / "t21r8" / "validation_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    group = next(iter(contract["floors"]))
    first_floor = next(iter(contract["floors"][group]))
    del contract["floors"][group][first_floor]
    _write_json(contract_path, contract)
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    with pytest.raises(SystemExit, match="exactly 32 floors"):
        freeze_evaluator.main(root)


def test_evaluator_freeze_records_builder_runner_and_schema_hashes(
    tmp_path: Path, monkeypatch,
) -> None:
    # Control 13: the freeze records the evaluator, official runner, ALL
    # seven builder/audit scripts, the raw schemas, and the contract hashes.
    root = _build_root(tmp_path)
    _write_runtime_freeze(root)
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    document = _run_evaluator_freeze(root, monkeypatch)
    frozen = document["frozen_hashes"]
    assert frozen["evaluator_path"] == "scripts/t21r8_run_eval.py"
    assert frozen["evaluator_source_sha256"] == _sha(
        root / "scripts" / "t21r8_run_eval.py")
    assert frozen["official_runner_path"] == "scripts/t21r8_official_eval.py"
    assert frozen["official_runner_sha256"] == _sha(
        root / "scripts" / "t21r8_official_eval.py")
    assert frozen["official_command"] == \
        "python scripts/t21r8_official_eval.py"
    recorded = frozen["builder_audit_scripts_sha256"]
    assert set(recorded) == set(freeze_evaluator.BUILDER_SCRIPTS)
    assert len(recorded) == 7
    for script, sha in recorded.items():
        assert sha == _sha(root / "scripts" / script)
    assert frozen["runtime_freeze_sha256"] == _sha(
        root / "evaluations" / "t21r8" / "runtime_freeze.json")
    assert frozen["qualification_artifact_sha256"] == _sha(
        root / "evaluations" / "t21r8" / "evaluator_qualification.json")
    assert document["runtime_freeze_recorded_at"] == \
        "2026-01-01T00:00:00+00:00"
    schema = document["raw_results_schema"]
    assert set(schema) == {"raw_answer_fields", "raw_retrieval_fields"}
    assert frozen["floors_sha256"]
    assert frozen["suite_minimums_sha256"]
    assert frozen["zero_tolerance_note_sha256"]
    assert frozen["raw_results_schema_sha256"]
    assert document["ordering"] == freeze_evaluator.ORDERING
    assert document["ordering"].startswith("runtime freeze < evaluator "
                                           "freeze")


# ---------------------------------------------------------------------------
# Control 14: the freeze scripts construct NO holdout data whatsoever.
# ---------------------------------------------------------------------------


def test_freeze_scripts_construct_no_holdout(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _build_root(tmp_path)
    _write_precheck(root, FIXTURE_HEAD)
    _run_runtime_freeze(root, monkeypatch)
    monkeypatch.setattr(freeze_evaluator, "refuse_blind_material",
                        lambda root: None)
    _run_evaluator_freeze(root, monkeypatch)

    assert not (root / "rag" / "gk_holdout_t21r8").exists()
    assert not (root / "evaluations" / "t21r8" / "suites").exists()
    assert not (root / "evaluations" / "t21r8" / "HOLDOUT_FROZEN").exists()
    assert not (root / "evaluations" / "t21r8" / "holdout_manifest.json") \
        .exists()
    assert not (root / "evaluations" / "t21r8"
                / "evaluation_run_ledger.json").exists()
    assert not (root / "evaluations" / "t21r8" / "raw_results.jsonl").exists()
    assert not (root / "evaluations" / "t21r8" / "holdout_results.json") \
        .exists()
    for script in freeze_evaluator.BUILDER_SCRIPTS:
        # The freeze runs must not have touched any builder script.
        content = (root / "scripts" / script).read_bytes()
        assert content.replace(b"\r\n", b"\n") == \
            f"fixture {script}\n".encode("utf-8")

    # Neither freeze script may import a blind-world builder module.
    forbidden_imports = ("t21r8_world", "t21r8_build_suites")
    for source_path in ("scripts/t21r8_freeze_runtime.py",
                        "scripts/t21r8_freeze_evaluator.py"):
        tree = ast.parse(
            (ROOT / source_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            for name in names:
                assert not name.startswith(forbidden_imports), \
                    f"{source_path} imports {name}"