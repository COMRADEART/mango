"""Normalize raw fetched records (any source) into the canonical JSONL schema,
writing data/processed/<name>.jsonl plus a rejection list.

Input: one or more JSONL files of raw dicts, each containing at least the
fields needed to fill the canonical schema (loader adapters in
src/sciencemath/datasets/source_profiles.py map raw fields when needed).

Usage:
  python scripts/normalize_dataset.py --input data/raw/gsm8k.jsonl \
      --name gsm8k --source gsm8k --license MIT [--keep-rejected]
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, load_configs, setup_logging  # noqa: E402

from sciencemath.datasets.normalize import normalize_example  # noqa: E402
from sciencemath.datasets.schema import make_id  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_jsonl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", nargs="+", required=True, help="raw JSONL file(s)")
    ap.add_argument("--name", required=True, help="output stem, e.g. gsm8k")
    ap.add_argument("--source", required=True, help="dataset name as in datasets.json")
    ap.add_argument("--license", required=True, help="license identifier to stamp")
    ap.add_argument("--domain", default=None, help="default domain if records lack one")
    ap.add_argument("--subject", default=None)
    ap.add_argument("--question-field", default="question")
    ap.add_argument("--answer-field", default="answer")
    ap.add_argument("--solution-field", default="solution")
    ap.add_argument("--keep-rejected", action="store_true")
    args = ap.parse_args()

    log = setup_logging("normalize_dataset")
    cfg = load_configs().get("data", {})
    quality = (cfg or {}).get("quality", {})

    records = []
    for path in args.input:
        records.extend(read_jsonl(path))
    log.info("loaded %d raw records", len(records))

    kept, rejected = [], []
    for i, raw in enumerate(records):
        rec = {
            "source": args.source,
            "license": args.license,
            "question": raw.get(args.question_field) or "",
            "answer": raw.get(args.answer_field) or "",
        }
        if raw.get(args.solution_field):
            rec["solution"] = raw[args.solution_field]

        # passthrough of optional canonical fields when present in the raw data
        for f in ("domain", "subject", "difficulty", "explanation",
                  "source_id", "answer_type"):
            if raw.get(f) is not None:
                rec[f] = raw[f]
        # CLI flags are defaults-without-override: a record's own value wins
        for flag_field, cli_value in (("domain", args.domain),
                                      ("subject", args.subject)):
            if cli_value:
                rec.setdefault(flag_field, cli_value)
        rec["domain"] = rec.get("domain")
        rec.setdefault("subject", "")
        if not rec.get("domain"):
            rejected.append({"line": i, "reason": "domain: missing (pass --domain)"})
            continue
        if not rec.get("source_id"):
            rec["source_id"] = str(raw.get("id", i))
        rec["id"] = make_id(args.source, rec["source_id"], str(rec["question"]))

        cleaned, issues = normalize_example(
            rec,
            min_question=int(quality.get("min_question_chars", 12)),
            max_question=int(quality.get("max_question_chars", 4000)),
            max_answer=int(quality.get("max_answer_chars", 2000)),
            max_solution=int(quality.get("max_solution_chars", 16000)))
        if cleaned is None:
            rejected.append({"line": i, "id": rec["id"], "reason": "; ".join(issues)})
        else:
            kept.append(cleaned)

    out_dir = DATA_DIR / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.name}.jsonl"
    write_jsonl(out_path, kept)
    log.info("wrote %d normalized -> %s", len(kept), out_path)

    rej_path = out_dir / f"{args.name}.rejected.jsonl"
    if rejected:
        write_jsonl(rej_path, rejected)
        log.info("wrote %d rejected -> %s", len(rejected), rej_path)

    by_reason = Counter(r["reason"].split(";")[0] for r in rejected)
    print(f"normalized={len(kept)} rejected={len(rejected)} reasons={dict(by_reason)}")
    if rejected and not args.keep_rejected:
        print("note: rejections are detailed in", rej_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())