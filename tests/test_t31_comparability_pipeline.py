"""T31 tests for the two pipeline helpers that feed GATE 1.

Both decide a clause of "the T30 record is unmodified", and both have a
fail-open shape if written carelessly: a git check that returns ``True`` when
git could not be run, or a record reader that returns a default when the file
is missing. The tests pin the fail-closed behaviour — ``None`` means "not
evaluated", which the gate turns into NOT_EVALUATED and the overall decision
into PARTIAL, never into a PASS nobody checked.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from sciencemath.comparability import pipeline as P


def _git_init(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True,
                   capture_output=True)


def test_the_t30_tree_check_is_clean_for_an_untouched_repository(tmp_path):
    _git_init(tmp_path)
    assert P._t30_tree_clean(tmp_path) is True


def test_the_t30_tree_check_reports_a_tree_with_changes(tmp_path):
    """An untracked file under the protected path shows as dirty, so a staged
    artifact left in the tree cannot read as an unmodified record."""
    _git_init(tmp_path)
    protected = tmp_path / "evaluations" / "t30"
    protected.mkdir(parents=True)
    (protected / "sneaked.json").write_text("{}", encoding="utf-8")
    assert P._t30_tree_clean(tmp_path) is False


def test_the_t30_tree_check_is_unevaluated_outside_a_repository(tmp_path):
    """Not a repository means the check did not run, which is ``None``, not a
    clean tree.

    The directory must be outside *any* repository: pytest's ``tmp_path`` sits
    under the repo, and git walks up to find one, so a nested temp dir would
    report a perfectly clean tree and the test would pass for the wrong
    reason."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="t31-no-repo-") as outside:
        assert P._t30_tree_clean(__import__("pathlib").Path(outside)) is None


def test_the_recorded_freeze_is_read_from_the_promotion_record(tmp_path):
    from sciencemath.comparability.identity import T30_PROMOTION_RECORD

    path = tmp_path / T30_PROMOTION_RECORD
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(
        {"freeze_identity": {"freeze_sha256": "abc123", "modified": False}}),
        encoding="utf-8")
    assert P._t30_recorded_freeze(tmp_path) == "abc123"


def test_a_missing_record_yields_no_freeze_rather_than_a_default(tmp_path):
    assert P._t30_recorded_freeze(tmp_path) is None


def test_the_shipped_record_declares_the_pinned_freeze_root():
    """The value in ``identity`` and the value in the record must agree; if the
    record were edited, this is the test that would fail first."""
    from pathlib import Path

    from sciencemath.comparability.identity import (
        T30_FROZEN_FREEZE_SHA256, T30_PROMOTION_RECORD,
    )

    record = Path(T30_PROMOTION_RECORD)
    if not record.exists():
        pytest.skip("T30 promotion record not present in this checkout")
    declared = json.loads(record.read_text(encoding="utf-8"))
    assert (declared["freeze_identity"]["freeze_sha256"]
            == T30_FROZEN_FREEZE_SHA256)
    assert declared["freeze_identity"]["modified"] is False
