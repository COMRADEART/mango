"""LEGACY_CRLF_CHECKSUM_PORTABILITY_DEFECT — focused verifier tests.

The T21R6 entry gate proved the frozen v1 corpus checksums were generated
from CRLF byte representations while the checkout is pure LF. These tests
pin the platform-independent repair:

  * an LF checkout passes,
  * a CRLF checkout passes,
  * an actual textual mutation fails,
  * a byte mutation other than line endings fails,
  * a missing file fails,

and that the real frozen corpus verifies with the legacy semantics
recorded explicitly (never silently).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sciencemath.utils.legacy_checksums import (
    historical_corpus_sha256,
    raw_sha256,
    verify_frozen_checksums,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "training" / "datasets" / "sciencemath-sft-v1"

TEXT = "alpha line\nbeta line\ngamma line\n"


def _expected_for(text: str) -> str:
    """The historical CRLF-canonical checksum of a text."""
    return hashlib.sha256(
        text.encode("utf-8").replace(b"\n", b"\r\n")).hexdigest()


def _corpus(tmp_path: Path, content: bytes, expected_overrides=None):
    (tmp_path / "train.jsonl").write_bytes(content)
    expected = expected_overrides if expected_overrides is not None \
        else _expected_for(TEXT)
    (tmp_path / "checksums.json").write_text(
        json.dumps({"train.jsonl": expected}), encoding="utf-8")


def test_lf_checkout_passes(tmp_path):
    _corpus(tmp_path, TEXT.encode("utf-8"))          # LF bytes on disk
    res = verify_frozen_checksums(tmp_path)
    assert res["ok"], res
    assert res["semantics"]["train.jsonl"] == "legacy_crlf"


def test_crlf_checkout_passes(tmp_path):
    _corpus(tmp_path, TEXT.replace("\n", "\r\n").encode("utf-8"))
    res = verify_frozen_checksums(tmp_path)
    # round trip CRLF -> LF -> CRLF is identity for pure-CRLF content, so
    # BOTH semantics match; raw is tried first
    assert res["ok"], res
    assert res["semantics"]["train.jsonl"] in ("raw", "legacy_crlf")


def test_raw_semantics_still_accepted(tmp_path):
    expected = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    _corpus(tmp_path, TEXT.encode("utf-8"), expected_overrides=expected)
    res = verify_frozen_checksums(tmp_path)
    assert res["ok"], res
    assert res["semantics"]["train.jsonl"] == "raw"


def test_textual_mutation_fails(tmp_path):
    expected = _expected_for(TEXT)
    _corpus(tmp_path, TEXT.replace("gamma", "delta").encode("utf-8"),
            expected_overrides=expected)
    res = verify_frozen_checksums(tmp_path)
    assert res["ok"] is False and res["mismatched"] == ["train.jsonl"]


def test_byte_mutation_other_than_eol_fails(tmp_path):
    expected = _expected_for(TEXT)
    # flip one content byte ("beta" -> "beto"): not a line-ending change
    _corpus(tmp_path, TEXT.replace("beta", "beto").encode("utf-8"),
            expected_overrides=expected)
    assert verify_frozen_checksums(tmp_path)["ok"] is False
    # append a stray byte: also fails both semantics
    _corpus(tmp_path, TEXT.encode("utf-8") + b"\x00",
            expected_overrides=expected)
    assert verify_frozen_checksums(tmp_path)["ok"] is False


def test_missing_file_fails(tmp_path):
    (tmp_path / "checksums.json").write_text(
        json.dumps({"train.jsonl": "0" * 64}), encoding="utf-8")
    res = verify_frozen_checksums(tmp_path)
    assert res["ok"] is False and res["missing"] == ["train.jsonl"]


def test_no_arbitrary_alternate_hash_accepted(tmp_path):
    _corpus(tmp_path, TEXT.encode("utf-8"),
            expected_overrides="e" * 64)
    assert verify_frozen_checksums(tmp_path)["ok"] is False


@pytest.mark.skipif(not CORPUS_DIR.exists(), reason="frozen corpus absent")
def test_real_frozen_corpus_verifies_with_legacy_semantics_recorded():
    res = verify_frozen_checksums(CORPUS_DIR)
    assert res["ok"], res
    assert res["files_checked"] == 8
    # every file matched under the historical CRLF-canonical semantics,
    # never by accident under a third hash
    assert all(v == "legacy_crlf"
               for v in res["semantics"].values()), res["semantics"]


@pytest.mark.skipif(not CORPUS_DIR.exists(), reason="frozen corpus absent")
def test_historical_helper_matches_expected_values():
    checksums = json.loads(
        (CORPUS_DIR / "checksums.json").read_text(encoding="utf-8"))
    for name, expected in checksums.items():
        assert historical_corpus_sha256(CORPUS_DIR / name) == expected, name


def test_helpers_are_deterministic_and_distinct(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(TEXT.encode("utf-8"))
    assert historical_corpus_sha256(p) == historical_corpus_sha256(p)
    # the two semantics genuinely differ for LF content
    assert raw_sha256(p) != historical_corpus_sha256(p)
    # ...and agree for CRLF content
    p.write_bytes(TEXT.replace("\n", "\r\n").encode("utf-8"))
    assert raw_sha256(p) == historical_corpus_sha256(p)