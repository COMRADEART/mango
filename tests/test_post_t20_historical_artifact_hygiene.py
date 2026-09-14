"""Post-T20 historical-artifact hygiene — immutability pin.

Historical evaluation artifacts are immutable records: later milestones may
read/hash/compare them, but must never silently rewrite them. A T20
protection run refreshed the ``recorded_at`` timestamp of the T15R
mutation-safety probe in place; this test pins the canonical historical
hash so any future in-place mutation fails CI instead of passing silently.

Canonical values verified mechanically against git history during the
post-T20 historical-artifact cleanup (branch
``post-t20-historical-artifact-hygiene``, base main ``642abe1``):
pre-T20 blob ``fba2437f78633884bd31965d78a4250bd1ca893c``, mutated T20 blob
``494382747b7b068fb2f23de8b4e72f690bde5755``.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HISTORICAL = ROOT / "evaluations/t15r/mutation_safety_probe.json"
CANONICAL_BLOB_SHA = "fba2437f78633884bd31965d78a4250bd1ca893c"
CANONICAL_RECORDED_AT = "2026-09-13T16:24:50.907825+00:00"
CANONICAL_MILESTONE = "T15R mutation-safety probe (T14R2 logic, current tree)"


def _git_blob_sha(path: Path) -> str:
    """Git blob SHA of a file's working-tree content (line-ending agnostic
    the same way git itself is: content is hashed as-is via hash-object)."""
    out = subprocess.run(
        ["git", "hash-object", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_t15r_probe_file_exists() -> None:
    assert HISTORICAL.is_file()


def test_t15r_probe_blob_sha_is_canonical() -> None:
    assert _git_blob_sha(HISTORICAL) == CANONICAL_BLOB_SHA


def test_t15r_probe_recorded_at_is_canonical() -> None:
    doc = json.loads(HISTORICAL.read_text(encoding="utf-8"))
    assert doc["recorded_at"] == CANONICAL_RECORDED_AT
    assert doc["milestone"] == CANONICAL_MILESTONE
    assert doc["passed"] is True


def test_t15r_probe_content_digest_matches_canonical_blob() -> None:
    """The canonical blob SHA, recomputed from content (sha1 of
    'blob <len>\\0' + bytes) with repository-normalized line endings
    (CRLF -> LF, matching core.autocrlf checkout filters)."""
    data = HISTORICAL.read_bytes().replace(b"\r\n", b"\n")
    header = f"blob {len(data)}\0".encode("ascii")
    assert hashlib.sha1(header + data).hexdigest() == CANONICAL_BLOB_SHA


def test_t20_probe_artifact_remains_local_and_valid() -> None:
    """The T20-local probe artifact (the proper result of the T20 protection
    run) must still exist alongside the untouched historical one."""
    t20 = ROOT / "evaluations/t20/mutation_safety_probe.json"
    assert t20.is_file()
    doc = json.loads(t20.read_text(encoding="utf-8"))
    assert doc["passed"] is True
    assert doc["recorded_at"] != CANONICAL_RECORDED_AT  # T20-local timestamp