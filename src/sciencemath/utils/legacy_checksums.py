"""LEGACY_CRLF_CHECKSUM_PORTABILITY_DEFECT — frozen-corpus checksum helper.

The T21R6 entry gate (canonical base f71cdb6e7855ba20d58e38b05d7286457
bc300ae) found that every file of the frozen v1 SFT corpus
(training/datasets/sciencemath-sft-v1/) is stored and checked out as pure
LF bytes, yet the historical checksums.json values were computed from the
CRLF byte representation used when the corpus was originally frozen on a
Windows checkout. sha256(LF bytes) != historical expected for all 8 files,
while sha256(LF -> CRLF canonical) == historical expected for all 8 files.
This is a checksum-verification portability defect, NOT corpus tampering:
the corpus content is byte-identical to the committed git content.

`historical_corpus_sha256` reproduces the historical byte representation
deterministically:

    1. read the file bytes,
    2. normalize CRLF -> LF,
    3. convert the normalized LF text back to CRLF,
    4. sha256 the canonical CRLF bytes.

The verifier accepts a file only when EITHER the raw sha256 OR the
historical CRLF-canonical sha256 equals the frozen expected value — never
any third hash — so any textual or byte mutation other than line endings
still fails verification. The matched semantics are reported per file so
the legacy match is always visible and auditable.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def raw_sha256(path: Path) -> str:
    """sha256 of the file's raw bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def historical_corpus_sha256(path: Path) -> str:
    """sha256 of the file's CRLF-canonical byte representation.

    Reads the raw bytes, normalizes CRLF -> LF, converts LF -> CRLF, and
    hashes the result. For pure-LF content this reproduces the byte form
    used when the frozen historical checksums were originally generated
    (LEGACY_CRLF_CHECKSUM_PORTABILITY_DEFECT). Deterministic and
    platform-independent: both an LF and a CRLF checkout of the same text
    produce the same digest.
    """
    raw = Path(path).read_bytes()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")
                          .replace(b"\n", b"\r\n")).hexdigest()


def verify_frozen_checksums(corpus_dir: Path) -> dict:
    """Verify a checksummed corpus dir under both checksum semantics.

    Each file must match its frozen checksums.json entry under the raw
    sha256 or the historical CRLF-canonical sha256. Returns the classic
    verify_corpus shape (ok, files_checked, missing, mismatched) plus a
    per-file `semantics` map ("raw" | "legacy_crlf") so a legacy match is
    never silently indistinguishable from a raw match.
    """
    from sciencemath.utils.io_utils import load_json

    checksums = load_json(Path(corpus_dir) / "checksums.json")
    missing, mismatched = [], []
    semantics: dict[str, str] = {}
    for name, expected in checksums.items():
        p = Path(corpus_dir) / name
        if not p.exists():
            missing.append(name)
            continue
        if raw_sha256(p) == expected:
            semantics[name] = "raw"
        elif historical_corpus_sha256(p) == expected:
            semantics[name] = "legacy_crlf"
        else:
            mismatched.append(name)
    return {"ok": not mismatched and not missing,
            "files_checked": len(checksums),
            "missing": missing, "mismatched": mismatched,
            "semantics": semantics}