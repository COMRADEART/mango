"""License gating tests (deny-by-default must be airtight)."""
import pytest

from sciencemath.datasets.licenses import (
    filter_for_training,
    license_decision,
    load_dataset_manifest,
    training_sources,
    write_license_manifest_md,
)
from sciencemath.utils.io_utils import load_json, write_json


@pytest.fixture
def manifest_entries():
    return [
        {"name": "approved-set", "provider": "huggingface",
         "reference": "https://example.com/a", "license": "MIT",
         "license_status": "APPROVED", "license_verified": True,
         "allows_training_use": True, "redistribution_permitted": True,
         "eval_only": False, "checked_on": "2026-08-31"},
        {"name": "review-set", "provider": "kaggle",
         "reference": "https://example.com/r", "license": "Unknown",
         "license_status": "REVIEW_REQUIRED", "license_verified": False,
         "allows_training_use": False,
         "eval_only": False, "checked_on": "2026-08-31"},
        {"name": "bench", "provider": "huggingface",
         "reference": "https://example.com/b", "license": "CC-BY-SA-4.0",
         "license_status": "APPROVED", "license_verified": True,
         "allows_training_use": True, "eval_only": True},
    ]


def rec(source):
    return {"id": f"{source}-1", "source": source, "question": "q?", "answer": "a",
            "domain": "mathematics", "license": "?"}


def test_unknown_source_excluded(manifest_entries):
    decision, reason = license_decision(None)
    assert decision == "EXCLUDED" and "not present" in reason


def test_review_required_excluded(manifest_entries):
    decision, reason = license_decision(manifest_entries[1])
    assert decision == "EXCLUDED"


def test_approved_allowed(manifest_entries):
    decision, _ = license_decision(manifest_entries[0])
    assert decision == "ALLOWED"


def test_filter_for_training(manifest_entries):
    records = [rec("approved-set"), rec("review-set"), rec("un-listed")]
    ok, excluded = filter_for_training(records, manifest_entries)
    assert [r["source"] for r in ok] == ["approved-set"]
    reasons = {e["source"]: e["reason"] for e in excluded}
    assert "license not verified" in reasons["review-set"]
    assert "not present" in reasons["un-listed"]


def test_eval_only_source_not_in_training_sources(manifest_entries):
    sources = training_sources(manifest_entries)
    assert "approved-set" in sources
    assert "bench" not in sources


def test_manifest_loader_rejects_bad_status(manifest_entries, tmp_path):
    bad = [dict(manifest_entries[0], license_status="SHRUG")]
    p = tmp_path / "datasets.json"
    write_json(p, {"datasets": bad})
    with pytest.raises(ValueError):
        load_dataset_manifest(p)


def test_license_manifest_md_generation(manifest_entries, tmp_path):
    p = tmp_path / "LICENSE_MANIFEST.md"
    write_license_manifest_md(manifest_entries, p)
    text = p.read_text(encoding="utf-8")
    assert "review-set" in text and "REVIEW_REQUIRED" in text
    assert "Deny-by-default" in text or "deny-by-default" in text


def test_repo_manifest_loads():
    from tests.conftest import REPO_ROOT
    entries = load_dataset_manifest(REPO_ROOT / "data" / "manifests" / "datasets.json")
    assert entries, "datasets.json must contain at least one entry"
    for e in entries:
        assert e.get("license_status") in {"APPROVED", "REVIEW_REQUIRED", "INCOMPATIBLE"}
        # engineering rules: statuses must reflect verification
        if e.get("license_status") == "APPROVED":
            assert e.get("license_verified") is True, \
                f"{e['name']} marked APPROVED but license_verified is not true"
            assert e.get("allows_training_use") is True