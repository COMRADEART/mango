"""Generate train/validation/test splits with contamination checks, honoring
the license manifest (deny-by-default) and eval-only sources.

Reads data/processed/<name>.dedup.jsonl file(s), stamps split= on each
record, writes data/train/*.jsonl, data/validation/*.jsonl, data/test/*.jsonl
and data/manifests/splits_summary.json. Fails (exit code 3) on direct
leakage, exit code 4 when every record is license-excluded.

Usage:
  python scripts/build_splits.py --input data/processed/gsm8k.dedup.jsonl \
      data/processed/sciq.dedup.jsonl
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, REPO_ROOT, load_configs, setup_logging  # noqa: E402

from sciencemath.datasets.licenses import (  # noqa: E402
    filter_for_training,
    is_eval_only_source,
    load_dataset_manifest,
    training_sources,
)
from sciencemath.datasets.splits import build_and_check, LeakageError  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_jsonl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", nargs="+", required=True,
                    help="deduplicated processed JSONL files")
    ap.add_argument("--output-stem", default="sciencemath-corpus")
    ap.add_argument("--test-fraction", type=float, default=None)
    ap.add_argument("--validation-fraction", type=float, default=None)
    ap.add_argument("--no-fail-on-leakage", action="store_true",
                    help="report leakage without refusing (NOT recommended)")
    args = ap.parse_args()

    log = setup_logging("build_splits")
    cfg = load_configs().get("data", {})
    split_cfg = (cfg or {}).get("split", {})

    manifest_path = DATA_DIR / "manifests" / "datasets.json"
    manifest = load_dataset_manifest(manifest_path)
    allowed = training_sources(manifest)
    log.info("license manifest loaded: %d entries, %d approved for training: %s",
             len(manifest), len(allowed), sorted(allowed))

    records = []
    for p in args.input:
        records.extend(read_jsonl(p))

    ok, excluded = filter_for_training(records, manifest)
    log.info("license filter: %d allowed for training, %d excluded by license",
             len(ok), len(excluded))
    if excluded:
        print("license-excluded examples:", len(excluded),
              "sources:", sorted({e["source"] for e in excluded}))
        for e in excluded[:5]:
            print("  ", e["source"], "-", e["reason"])
    if not ok:
        print("ERROR: no records are licensed for training. "
              "Approve datasets in data/manifests/datasets.json after "
              "verifying their license text.")
        return 4

    eval_only = {s for s in {r.get("source", "?") for r in ok}
                 if is_eval_only_source(s, manifest)}
    holdout = set(split_cfg.get("holdout_sources", []) or [])

    try:
        splits, summary, leakage = build_and_check(
            ok,
            seed=int(split_cfg.get("seed", 42)),
            test_fraction=float(args.test_fraction
                                if args.test_fraction is not None
                                else split_cfg.get("test_fraction", 0.10)),
            validation_fraction=float(args.validation_fraction
                                      if args.validation_fraction is not None
                                      else split_cfg.get("validation_fraction", 0.05)),
            group_by=split_cfg.get("group_by", "normalized_question"),
            eval_only_sources=eval_only,
            holdout_sources=holdout,
            near_threshold=float((cfg.get("leakage", {}) or {}).get("near_threshold", 0.90)),
            fail_on_direct=bool((cfg.get("leakage", {}) or {}).get("fail_on_direct", True))
            and not args.no_fail_on_leakage)
    except LeakageError as exc:
        log.error("split generation REFUSED: %s", exc)
        print(f"STATUS: FAILED - {exc}")
        return 3

    # stamp split onto records and write split files
    for split, recs in splits.items():
        for r in recs:
            r["split"] = split
        out_path = DATA_DIR / split / f"{args.output_stem}.jsonl"
        write_jsonl(out_path, recs)
        log.info("wrote %d -> %s", len(recs), out_path)

    from sciencemath.utils.io_utils import write_json
    import json

    summary_out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "leakage": {
            "passed": leakage.get("passed"),
            "direct": leakage.get("direct_leakage"),
            "near": leakage.get("near_leakage")[:50],
            "near_count": len(leakage.get("near_leakage", [])),
            "source_overlap": leakage.get("source_overlap"),
            "eval_only_violations": leakage.get("eval_only_source_violations"),
        },
        "license_exclusions": [
            {k: e[k] for k in ("id", "source", "reason")} for e in excluded[:500]],
        "inputs": [str(p) for p in args.input],
    }
    write_json(DATA_DIR / "manifests" / "splits_summary.json", summary_out)

    print(json.dumps(summary["counts"], indent=2))
    print(f"leakage_passed={summary['leakage_passed']}")
    print("STATUS: PASS" if summary["leakage_passed"] else "STATUS: FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())