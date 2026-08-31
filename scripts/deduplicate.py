"""Deduplicate a processed JSONL (exact + normalized + near-duplicate).

Reads data/processed/<name>.jsonl, writes data/processed/<name>.dedup.jsonl
and a duplicates report.

Usage:
  python scripts/deduplicate.py --name gsm8k
  python scripts/deduplicate.py --name gsm8k --no-near
"""
from __future__ import annotations

import argparse

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, load_configs, setup_logging  # noqa: E402

from sciencemath.datasets.dedup import deduplicate  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_jsonl, write_json  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--no-near", action="store_true")
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()

    log = setup_logging("deduplicate")
    dcfg = (load_configs().get("data", {}) or {}).get("dedup", {})
    near_cfg = (dcfg or {}).get("near_duplicate", {})

    in_path = DATA_DIR / "processed" / f"{args.name}.jsonl"
    records = read_jsonl(in_path)
    log.info("loaded %d records from %s", len(records), in_path)

    result = deduplicate(
        records,
        ngram_size=int(near_cfg.get("ngram_size", 4)),
        near_threshold=float(args.threshold or near_cfg.get("threshold", 0.85)),
        near_enabled=(not args.no_near) and bool(near_cfg.get("enabled", True)),
        max_scan_pairs=int(near_cfg.get("max_scan_pairs", 2_000_000)))

    out_path = DATA_DIR / "processed" / f"{args.name}.dedup.jsonl"
    write_jsonl(out_path, result.kept)
    dup_path = DATA_DIR / "processed" / f"{args.name}.duplicates.jsonl"
    if result.duplicates:
        write_jsonl(dup_path, result.duplicates)

    print(f"kept={result.n_kept} removed={len(result.duplicates)} "
          f"by_reason={result.counts}")
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())