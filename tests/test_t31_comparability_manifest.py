"""T31 tests for the evidence pack: manifest, hashes, and the pack's layout.

The brief asks for hashes over the config, prompts, scorers, raw results,
scored results and the report, and states what they are for: they
"authenticate the run", and must not be "described as proof of model
capability". So the tests here check that a hash changes when the bytes change,
that an empty manifest is refused, and that a missing or altered file is
reported rather than tolerated.

The layout test pins the base-directory convention. ``rows.raw_path`` already
appends ``evaluations/t31``, so a manifest helper that appended it again would
write the pack one level too deep — and it would do so silently, because
nothing else reads that path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sciencemath.comparability import manifest as M
from sciencemath.comparability.rows import EVIDENCE_ROOT, raw_path


def pack(base):
    """Create a small evidence tree under ``base``."""
    root = M.evidence_root(base)
    (root / "raw" / "base").mkdir(parents=True, exist_ok=True)
    (root / "raw" / "base" / "gsm8k.jsonl").write_text('{"a": 1}\n',
                                                       encoding="utf-8")
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "r.md").write_text("# report\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------
def test_the_pack_lives_where_the_row_paths_do(tmp_path):
    """One convention, shared with ``rows.raw_path``, or the two disagree."""
    assert M.evidence_root(tmp_path) == tmp_path / EVIDENCE_ROOT
    # config/<name>, raw/<arm>/<benchmark>.jsonl: both hang off the same root.
    assert M.config_path(tmp_path).parent.parent == M.evidence_root(tmp_path)
    assert (raw_path(tmp_path, "base", "gsm8k").parent.parent.parent
            == M.evidence_root(tmp_path))


# ---------------------------------------------------------------------------
# collecting and writing
# ---------------------------------------------------------------------------
def test_collect_hashes_every_file_by_relative_path(tmp_path):
    pack(tmp_path)
    recorded = M.collect(tmp_path)
    assert set(recorded) == {"raw/base/gsm8k.jsonl", "reports/r.md"}
    assert all(len(digest) == 64 for digest in recorded.values())


def test_a_changed_byte_changes_the_hash(tmp_path):
    root = pack(tmp_path)
    before = M.collect(tmp_path)
    (root / "raw" / "base" / "gsm8k.jsonl").write_text('{"a": 2}\n',
                                                       encoding="utf-8")
    assert M.collect(tmp_path) != before


def test_write_sums_is_sorted_and_covers_the_pack(tmp_path):
    pack(tmp_path)
    destination = M.write_sums(tmp_path)
    lines = destination.read_text(encoding="utf-8").splitlines()
    assert lines == sorted(lines)
    assert any(line.endswith("raw/base/gsm8k.jsonl") for line in lines)


def test_the_manifest_does_not_list_itself(tmp_path):
    """A file cannot contain its own hash: writing the line changes it."""
    pack(tmp_path)
    M.write_sums(tmp_path)
    assert "SHA256SUMS" not in M.collect(tmp_path)


def test_an_empty_pack_is_refused_rather_than_manifested(tmp_path):
    """A manifest over no files authenticates nothing and reads complete."""
    with pytest.raises(M.ManifestError, match="empty"):
        M.write_sums(tmp_path)


def test_the_manifest_can_be_verified(tmp_path):
    pack(tmp_path)
    M.write_sums(tmp_path)
    ok, problems = M.verify_sums(tmp_path)
    assert ok and not problems


def test_a_file_changed_after_the_manifest_is_caught(tmp_path):
    root = pack(tmp_path)
    M.write_sums(tmp_path)
    (root / "reports" / "r.md").write_text("# tampered\n", encoding="utf-8")
    ok, problems = M.verify_sums(tmp_path)
    assert not ok
    assert any("reports/r.md" in problem for problem in problems)


def test_a_file_added_after_the_manifest_is_caught(tmp_path):
    """Otherwise a pack could grow after verification and still verify."""
    root = pack(tmp_path)
    M.write_sums(tmp_path)
    (root / "analysed.json").write_text("{}\n", encoding="utf-8")
    ok, problems = M.verify_sums(tmp_path)
    assert not ok
    assert any("analysed.json" in problem for problem in problems)


def test_a_removed_file_is_reported_as_absent(tmp_path):
    root = pack(tmp_path)
    M.write_sums(tmp_path)
    (root / "reports" / "r.md").unlink()
    ok, problems = M.verify_sums(tmp_path)
    assert not ok
    assert any("absent" in problem for problem in problems)


def test_verifying_without_a_manifest_is_an_error_not_a_pass(tmp_path):
    pack(tmp_path)
    with pytest.raises(M.ManifestError, match="SHA256SUMS"):
        M.verify_sums(tmp_path)


def test_the_manifest_line_endings_are_lf(tmp_path):
    """Written with the default newline translation, ``sha256sum -c`` on a
    POSIX reader folds the trailing CR into every filename and reports the
    whole pack missing."""
    pack(tmp_path)
    M.write_sums(tmp_path)
    raw = (M.evidence_root(tmp_path) / M.SUMS_NAME).read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")


# ---------------------------------------------------------------------------
# the source snapshot
# ---------------------------------------------------------------------------
def test_the_measurement_source_is_snapshotted_into_the_pack(tmp_path):
    """The brief asks the pack to contain the prompt templates, the answer
    extractors and the scorers: they are copied in, not merely hashed."""
    pack(tmp_path)
    M.snapshot_sources(tmp_path)
    written = M.collect(tmp_path)
    for module in ("prompts.py", "extractors.py", "scorers.py"):
        assert f"{M.SOURCE_DIR}/{module}" in written


def test_the_snapshot_is_a_byte_exact_copy(tmp_path):
    import sciencemath.comparability as package

    pack(tmp_path)
    M.snapshot_sources(tmp_path)
    copied = M.source_dir(tmp_path) / "prompts.py"
    original = Path(package.__file__).parent / "prompts.py"
    assert copied.read_bytes() == original.read_bytes()


def test_snapshot_returns_the_hashes_it_wrote(tmp_path):
    pack(tmp_path)
    written = M.snapshot_sources(tmp_path)
    assert written
    for name, digest in written.items():
        assert len(digest) == 64
        assert (M.evidence_root(tmp_path) / name).is_file()


def test_a_snapshotted_source_file_is_covered_by_the_manifest(tmp_path):
    pack(tmp_path)
    M.snapshot_sources(tmp_path)
    M.write_sums(tmp_path)
    ok, problems = M.verify_sums(tmp_path)
    assert ok and not problems


def test_an_altered_source_snapshot_fails_verification(tmp_path):
    """Editing the copied extractor after the manifest is written must show,
    or the pack could present a scorer it did not score with."""
    pack(tmp_path)
    M.snapshot_sources(tmp_path)
    M.write_sums(tmp_path)
    (M.source_dir(tmp_path) / "extractors.py").write_text("# tampered\n",
                                                          encoding="utf-8")
    ok, problems = M.verify_sums(tmp_path)
    assert not ok
    assert any("extractors.py" in problem for problem in problems)


# ---------------------------------------------------------------------------
# text hashing and the chat template
# ---------------------------------------------------------------------------
def test_hashing_text_is_stable_and_utf8():
    assert M.sha256_text("abc") == M.sha256_text("abc")
    assert M.sha256_text("é") != M.sha256_text("e")


def test_a_tokenizer_without_a_template_is_refused():
    """The prompts cannot be pinned without it, so a configuration frozen
    anyway would not record what the model was asked."""
    class Bare:
        chat_template = None

    with pytest.raises(M.ManifestError, match="chat_template"):
        M.chat_template_sha256(Bare())


def test_a_changed_template_changes_the_hash():
    class Template:
        def __init__(self, text):
            self.chat_template = text

    assert (M.chat_template_sha256(Template("{{ x }}"))
            != M.chat_template_sha256(Template("{{ x }}{{ y }}")))


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------
def test_artifacts_carry_the_repo_schema_envelope(tmp_path):
    import json

    path = M.write_artifact(tmp_path / "x.json", "T31_THING", {"value": 1})
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["artifact"] == "T31_THING"
    assert document["schema_version"] == "t31-comparability-v1"
    assert document["value"] == 1


def test_jsonl_writing_replaces_rather_than_appends(tmp_path):
    """An append would let a rerun double the handoff dataset."""
    path = tmp_path / "rows.jsonl"
    M.write_lines(path, ["a", "b"])
    M.write_lines(path, ["c"])
    assert path.read_text(encoding="utf-8") == "c\n"


def test_the_dependency_record_names_the_versions():
    record = M.dependency_record()
    for name in ("torch", "transformers", "peft"):
        assert name in record and record[name]
