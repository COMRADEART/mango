"""Produce the dataset validation report (counts, duplicates, rejections,
licensing exclusions, split distribution, contamination status) from the
pipeline artifacts in data/.

Reads (whatever exists):
  data/manifests/datasets.json
  data/processed/*.duplicates.jsonl, *.rejected.jsonl
  data/train/*.jsonl, data/validation/*.jsonl, data/test/*.jsonl

Writes data/processed/dataset_validation.{json,md}.

Usage: python scripts/validate_dataset.py [--train-splits data/train/*.jsonl ...]
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, load_configs, setup_logging  # noqa: E402

from sciencemath.datasets.licenses import load_dataset_manifest  # noqa: E402
from sciencemath.datasets.report import build_validation_report, save_report  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, load_json  # noqa: E402


def _first(patterns):
    for p in patterns:
        m = sorted(DATA_DIR.glob(p))
        if m:
            return m[0]
    return None


def main() -> int:
    from sciencemath.datasets.leakage import check_splits

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train-splits", nargs="*", default=None,
                    help="split JSONLs; defaults to newest in data/train|validation|test")
    args = ap.parse_args()

    log = setup_logging("validate_dataset")
    log.info("building validation report")

    train_p = _first(["train/*.jsonl"])
    val_p = _first(["validation/*.jsonl"])
    test_p = _first(["test/*.jsonl"])

    splits: dict[str, list[dict]] = {}
    for name, p in (("train", train_p), ("validation", val_p), ("test", test_p)):
        if p is not None:
            splits[name] = read_jsonl(p)
            log.info("loaded %s: %d examples (%s)", name, len(splits[name]), p)

    duplicates = []
    for p in sorted((DATA_DIR / "processed").glob("*.duplicates.jsonl")):
        duplicates.extend(read_jsonl(p))
    rejected = Counter()
    for p in sorted((DATA_DIR / "processed").glob("*.rejected.jsonl")):
        for r in read_jsonl(p):
            rejected[r.get("reason", "unknown").split(";")[0]] += 1

    manifest_path = DATA_DIR / "manifests" / "datasets.json"
    manifest = load_dataset_manifest(manifest_path) if manifest_path.exists() else []
    excluded = [e for e in manifest if e.get("license_status") != "APPROVED"]

    try:
        leakage_report = check_splits(splits) if splits.get("train") else {}
        leakage_report["near_count"] = len(leakage_report.get("near_leakage", []))
        leakage_report["direct_count"] = len(leakage_report.get("direct_leakage", []))
    except Exception as exc:            # leakage failure => report, don't hide
        leakage_report = {"passed": False, "error": str(exc)}

    all_records = sum(splits.values(), []) if splits else []
    report = build_validation_report(
        records=all_records,
        rejected=rejected,
        duplicates=duplicates,
        licensing_exclusions=[
            {"source": e.get("name", "?"),
             "reason": e.get("license_status", "REVIEW_REQUIRED")}
            for e in excluded],
        split_summary=None,
        leakage_report=leakage_report,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": "configs/data.yaml",
        })

    # split distribution from the split summary artifact if present
    ssum = DATA_DIR / "manifests" / "splits_summary.json"
    if ssum.exists():
        report["splits"] = load_json(ssum).get("summary", {})

    json_path, md_path = save_report(report, DATA_DIR / "processed")
    log.info("wrote %s and %s", json_path, md_path)
    print(f"total={report['total_examples']} "
          f"by_domain={report['by_domain']} "
          f"duplicates={report['duplicate_count']} "
          f"rejected={report['rejected_count']} "
          f"leakage_passed={leakage_report.get('passed', 'n/a')}")
    print("STATUS:", "PASS" if leakage_report.get("passed") else "PARTIAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())