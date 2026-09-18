"""Preflight-before-exposure and one-shot consumption controls for the
T21R8 official evaluation wrapper.

Every control runs against a synthetic fixture tree (temp directories with
synthetic freeze artifacts, synthetic suite files, and an injected stub
corpus).  No real T21R8 holdout row is ever executed and no real R8 blind
material is constructed: the wrapper is exercised at the boundary where
preflight failures must leave ``official_runtime_exposures`` at 0 and a
post-exposure crash must consume the one-shot holdout.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import t21r4_freeze_runtime as freeze_runtime  # noqa: E402
import t21r8_official_eval as oe  # noqa: E402
import t21r8_run_eval as evaluator  # noqa: E402


EVALUATOR_SHA = hashlib.sha256(oe.EVALUATOR_PATH.read_bytes()).hexdigest()


class _StubSource:
    topic_tags = ["geography"]


class _StubCorpus:
    """Injected corpus stand-in: only domain validation touches it."""

    sources = [_StubSource()]
    manifest = {"manifest_checksum": "fixture-stub"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _write_suite(paths: oe.Paths, suite: str, rows: list[dict]) -> None:
    directory = paths.suites_dir / suite
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "holdout.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _synthetic_row(suite: str, index: int = 1) -> dict:
    return {
        "case_id": f"fx-{suite}-{index:04d}",
        "mode": "retrieval",
        "category": "fixture",
        "request": {"query": f"query {suite} {index}"},
        "gold": {},
    }


def _runtime_composites() -> dict:
    return {name: freeze_runtime.sha_group(spec)
            for name, spec in freeze_runtime.RUNTIME_GROUPS.items()}


def _build_fixture(tmp_path: Path, monkeypatch) -> oe.Paths:
    """Build a synthetic candidate tree whose preflight PASSES."""
    paths = oe.build_paths(tmp_path)
    paths.out_dir.mkdir(parents=True)

    suites = {}
    for suite in evaluator.SUITES:
        _write_suite(paths, suite, [_synthetic_row(suite)])
        suites[suite] = {
            "sha256": _sha(paths.suites_dir / suite / "holdout.jsonl")}
    probe = paths.root / "probe.txt"
    probe.write_text("freeze probe\n", encoding="utf-8")
    corpus_dir = paths.corpus_dir
    corpus_dir.mkdir(parents=True)
    for name in ("sources.jsonl", "chunks.jsonl"):
        (corpus_dir / name).write_text("{}\n", encoding="utf-8")
    _write_json(paths.manifest_path, {
        "freeze_inputs": {
            "probe": {"path": "probe.txt", "sha256": _sha(probe)},
        },
        "corpus": {
            name: {"path": f"rag/gk_holdout_t21r8/{name}",
                   "sha256": _sha(corpus_dir / name)}
            for name in ("sources.jsonl", "chunks.jsonl")
        },
        "suites": suites,
    })
    # The marker cryptographically anchors the EXACT manifest bytes: the
    # manifest is only a trusted root of truth through this identity.
    _write_json(paths.marker_path, {
        "frozen_at": "2026-01-01T00:00:00+00:00",
        "holdout_manifest_sha256": _sha(paths.manifest_path),
    })
    _write_json(paths.qualification_path, {
        "qualification_passed": True,
        "all_metric_paths_exercised": True,
        "all_cases_pass": True,
        "uncaught_exceptions": 0,
        "evaluator_source_sha256": EVALUATOR_SHA,
    })
    _write_json(paths.evaluator_freeze_path, {
        "evaluator_source_sha256": EVALUATOR_SHA,
        "scoring_semantics": evaluator.SCORING_SEMANTICS,
        "scoring_semantics_sha256": evaluator.scoring_semantics_sha256(),
    })
    _write_json(paths.runtime_freeze_path, {
        "runtime_composites": _runtime_composites(),
    })
    _write_json(paths.contract_path, {
        "scoring_semantics": evaluator.SCORING_SEMANTICS,
        "scoring_semantics_sha256": evaluator.scoring_semantics_sha256(),
    })
    monkeypatch.setattr(oe, "load_corpus", lambda corpus_dir: _StubCorpus())
    return paths


def _assert_no_exposure_artifacts(paths: oe.Paths) -> None:
    for name in oe.EXPOSURE_ARTIFACTS:
        assert not getattr(paths, name).exists(), name


def test_preflight_passes_and_writes_no_exposure_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    manifest, corpus = oe._preflight(paths)
    assert set(manifest["suites"]) == set(evaluator.SUITES)
    assert isinstance(corpus, _StubCorpus)
    _assert_no_exposure_artifacts(paths)


def test_missing_frozen_holdout_refuses_before_any_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    paths.marker_path.unlink()
    with pytest.raises(SystemExit, match="HOLDOUT_FROZEN"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_manifest_hash_mismatch_refuses_before_any_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    (paths.root / "probe.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="T21R8_FREEZE_VIOLATION"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


# ---------------------------------------------------------------------------
# Manifest-marker binding: HOLDOUT_FROZEN must anchor the exact manifest
# bytes, or a modified suite/corpus file plus an updated hash inside the
# manifest could become a new accepted root of truth.
# ---------------------------------------------------------------------------


def test_marker_anchors_the_exact_manifest_bytes_on_a_valid_tree(
    tmp_path: Path, monkeypatch,
) -> None:
    # A: valid marker SHA + valid manifest -> preflight succeeds and no
    # exposure artifact exists.
    paths = _build_fixture(tmp_path, monkeypatch)
    marker = json.loads(
        paths.marker_path.read_text(encoding="utf-8"))
    assert marker["holdout_manifest_sha256"] == _sha(paths.manifest_path)
    manifest, corpus = oe._preflight(paths)
    assert set(manifest["suites"]) == set(evaluator.SUITES)
    assert isinstance(corpus, _StubCorpus)
    _assert_no_exposure_artifacts(paths)


def test_manifest_bytes_changed_after_marker_refuses(
    tmp_path: Path, monkeypatch,
) -> None:
    # B: change holdout_manifest.json bytes after marker creation -> refuse,
    # no exposure artifacts.
    paths = _build_fixture(tmp_path, monkeypatch)
    manifest = json.loads(
        paths.manifest_path.read_text(encoding="utf-8"))
    manifest["tampered"] = "post-marker edit"
    _write_json(paths.manifest_path, manifest)
    with pytest.raises(SystemExit, match="T21R8_FREEZE_VIOLATION"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_marker_sha_change_alone_refuses(
    tmp_path: Path, monkeypatch,
) -> None:
    # C: change the marker's holdout_manifest_sha256 only -> refuse, no
    # exposure artifacts (the manifest itself is untouched).
    paths = _build_fixture(tmp_path, monkeypatch)
    _write_json(paths.marker_path, {
        "frozen_at": "2026-01-01T00:00:00+00:00",
        "holdout_manifest_sha256": "a" * 64,
    })
    with pytest.raises(SystemExit, match="T21R8_FREEZE_VIOLATION"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_suite_change_with_manifest_hash_update_still_refuses(
    tmp_path: Path, monkeypatch,
) -> None:
    # D (mandatory): change a suite AND update that suite's hash inside the
    # manifest WITHOUT updating HOLDOUT_FROZEN -> preflight still refuses,
    # because the manifest identity changed.  Updating a hash inside the
    # manifest can never mint a new accepted root of truth.
    paths = _build_fixture(tmp_path, monkeypatch)
    suite = evaluator.SUITES[0]
    _write_suite(paths, suite, [_synthetic_row(suite), _synthetic_row(suite, 2)])
    manifest = json.loads(
        paths.manifest_path.read_text(encoding="utf-8"))
    manifest["suites"][suite]["sha256"] = _sha(
        paths.suites_dir / suite / "holdout.jsonl")
    _write_json(paths.manifest_path, manifest)
    marker = json.loads(
        paths.marker_path.read_text(encoding="utf-8"))
    assert marker["holdout_manifest_sha256"] != _sha(paths.manifest_path)
    with pytest.raises(SystemExit, match="T21R8_FREEZE_VIOLATION"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_unparseable_marker_refuses(tmp_path: Path, monkeypatch) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    paths.marker_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="does not parse"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_marker_without_manifest_sha_refuses(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    _write_json(paths.marker_path, {"frozen_at": "2026-01-01T00:00:00+00:00"})
    with pytest.raises(SystemExit, match="lacks"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_evaluator_hash_mismatch_refuses_before_any_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    freeze = json.loads(
        paths.evaluator_freeze_path.read_text(encoding="utf-8"))
    freeze["evaluator_source_sha256"] = "0" * 64
    _write_json(paths.evaluator_freeze_path, freeze)
    with pytest.raises(SystemExit, match="evaluator freeze"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_runtime_composite_mismatch_refuses_before_any_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    freeze = json.loads(paths.runtime_freeze_path.read_text(encoding="utf-8"))
    freeze["runtime_composites"]["knowledge_runtime"] = "0" * 64
    _write_json(paths.runtime_freeze_path, freeze)
    with pytest.raises(SystemExit, match="runtime group knowledge_runtime"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_qualification_failure_refuses_before_any_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)
    qualification = json.loads(
        paths.qualification_path.read_text(encoding="utf-8"))
    qualification["qualification_passed"] = False
    _write_json(paths.qualification_path, qualification)
    with pytest.raises(SystemExit, match="qualification is not PASS"):
        oe.main(paths)
    _assert_no_exposure_artifacts(paths)


def test_crash_after_exposure_consumes_the_one_shot_holdout(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)

    def _boom(row, corpus):
        # The ledger MUST already exist when the first runtime row executes.
        assert paths.ledger_path.exists(), \
            "exposure ledger must be written before the first runtime row"
        assert paths.ledger_path.read_text(encoding="utf-8").count(
            '"official_runtime_exposures": 1') == 1
        raise RuntimeError("simulated runtime failure after exposure")

    monkeypatch.setattr(evaluator, "run_retrieval_row", _boom)
    with pytest.raises(RuntimeError, match="simulated runtime failure"):
        oe.main(paths)

    ledger = json.loads(paths.ledger_path.read_text(encoding="utf-8"))
    assert ledger["official_runtime_exposures"] == 1
    assert ledger["phase"] == "completed"
    assert ledger["exit_code"] == 1
    assert "simulated runtime failure" in ledger["error"]
    assert paths.raw_path.exists()

    with pytest.raises(SystemExit, match="T21R8_ONE_SHOT_CONSUMED"):
        oe.main(paths)


def test_crash_before_any_scored_row_still_consumes_and_forbids_rerun(
    tmp_path: Path, monkeypatch,
) -> None:
    paths = _build_fixture(tmp_path, monkeypatch)

    def _boom(row, corpus):
        raise RuntimeError("simulated crash before any row is scored")

    monkeypatch.setattr(evaluator, "run_retrieval_row", _boom)
    with pytest.raises(RuntimeError):
        oe.main(paths)
    ledger = json.loads(paths.ledger_path.read_text(encoding="utf-8"))
    assert ledger["official_runtime_exposures"] == 1
    with pytest.raises(SystemExit, match="T21R8_ONE_SHOT_CONSUMED"):
        oe.main(paths)