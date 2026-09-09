"""T8S.16 - reproducibility metadata gate tests (hermetic)."""
import pytest

from sciencemath.evaluation.repro import (
    REQUIRED_REPRO_FIELDS,
    ReproducibilityError,
    assert_reproducible,
    canonical_hash,
    enrich_manifest,
    generation_config_hash,
    validate_reproducibility_metadata,
)


def _full_meta() -> dict:
    return {f: "value-" + f for f in REQUIRED_REPRO_FIELDS}


def test_validate_ok_when_complete():
    assert validate_reproducibility_metadata(_full_meta()) == []


def test_validate_lists_all_missing_fields():
    assert validate_reproducibility_metadata({}) == list(REQUIRED_REPRO_FIELDS)


@pytest.mark.parametrize("field", ["model_id", "model_revision",
                                   "local_config_hash", "code_git_commit"])
def test_validate_detects_empty_and_unresolved(field):
    meta = _full_meta()
    meta[field] = ""
    assert field in validate_reproducibility_metadata(meta)
    meta[field] = "unresolved (connection error)"
    assert field in validate_reproducibility_metadata(meta)


def test_revisions_optional_when_not_required():
    meta = _full_meta()
    meta.pop("model_revision")
    meta.pop("tokenizer_revision")
    assert validate_reproducibility_metadata(
        meta, require_revision=False) == []
    assert validate_reproducibility_metadata(meta) == [
        "model_revision", "tokenizer_revision"]


def test_assert_raises_loudly():
    with pytest.raises(ReproducibilityError):
        assert_reproducible({"model_id": "m"})
    assert_reproducible(_full_meta())  # must not raise


def test_generation_hash_is_canonical_and_stable():
    h1 = generation_config_hash({"seed": 42, "do_sample": False})
    h2 = generation_config_hash({"do_sample": False, "seed": 42})
    assert h1 == h2
    assert len(h1) == 64
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_enrich_fails_loudly_when_revision_unresolvable(monkeypatch, tmp_path):
    from sciencemath.evaluation import repro
    monkeypatch.setattr(repro, "resolve_revision", lambda mid: None)
    monkeypatch.setattr(repro, "local_config_hash", lambda mid: None)
    with pytest.raises(ReproducibilityError):
        repro.enrich_manifest({}, model_id="fake/model", generation={},
                              repo=tmp_path)


def test_enrich_fills_and_never_overwrites(monkeypatch, tmp_path):
    from sciencemath.evaluation import repro
    monkeypatch.setattr(repro, "resolve_revision", lambda mid: "rev-abc")
    monkeypatch.setattr(repro, "local_config_hash", lambda mid: "cfg-hash")
    monkeypatch.setattr(repro, "code_git_commit", lambda repo=None: "commit-1")
    m = repro.enrich_manifest(
        {"model_id": "override/model", "model_revision": "pinned-rev"},
        model_id="fake/model", generation={"seed": 1}, repo=tmp_path)
    assert m["model_id"] == "override/model"      # existing value kept
    assert m["model_revision"] == "pinned-rev"    # never overwritten
    assert m["tokenizer_revision"] == "rev-abc"
    assert m["local_config_hash"] == "cfg-hash"
    assert m["generation_config_hash"] == generation_config_hash({"seed": 1})
    assert m["code_git_commit"] == "commit-1"
    assert validate_reproducibility_metadata(m) == []
