"""T32 Phase 3/4 infrastructure: the fresh-pool inventory.

Builds the pool of NEW training records available to T32:

* Sources are exactly the APPROVED, training-allowed entries of
  ``data/manifests/datasets.json`` (gsm8k train / hendrycks MATH train /
  sciq train). ARC and MATH-500 are never trained sources (eval-only or
  test subsets).
* Records are normalized through the SAME pipeline the frozen T30 corpus
  build used (``scripts/build_sft_corpus.py``): per-source field mapping,
  ``normalize_example`` with the data.yaml quality limits, and
  ``build_target`` canonical targets. Pool records therefore have the
  same schema (incl. ``target_response``) and the same question
  fingerprints as corpus records.
* Every record is fingerprinted and EXCLUDED if it already appears in the
  frozen T30 corpus (sciencemath-sft-v1 train+validation) or matches a T31
  evaluation item question (exact fingerprint). Near-duplicate filtering
  against T31 eval items runs later, at mixture-selection time, through
  the same leakage module used by the T30 build.
* ARC train rows are NOT pooled (eval-only license); they may be used for
  dev measurement only.

Output: training/t32/pools/fresh_pool.jsonl + inventory manifest.
Deterministic: no sampling here, no randomness; pools are complete and hashed.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")

from common import REPO_ROOT  # noqa: E402

from sciencemath.datasets.normalize import (  # noqa: E402
    normalize_example,
    text_fingerprint,
)
from sciencemath.datasets.schema import make_id  # noqa: E402
from sciencemath.training.sft_format import build_target  # noqa: E402
from sciencemath.utils.io_utils import load_yaml, read_jsonl, write_jsonl  # noqa: E402

ROOT = REPO_ROOT
T30_CORPUS = ROOT / "training/datasets/sciencemath-sft-v1"
POOLS = ROOT / "training/t32/pools"

MATH_CONFIGS = ("algebra", "counting_and_probability", "geometry",
                "intermediate_algebra", "number_theory", "prealgebra",
                "precalculus")


def fingerprint(question: str) -> str:
    return text_fingerprint(str(question))


def _normalize_all(rows, source, domain, subject, license_id, fields, load_note,
                   quality, records, rejects):
    """Exact local copy of the T30 builder's normalize_all closure (same
    field mappings, same thresholds, same target construction)."""
    kept = 0
    for i, raw in enumerate(rows):
        rec = {
            "source": source, "license": license_id,
            "domain": domain, "subject": subject,
            "question": str(raw.get(fields.get("question", "question")) or ""),
        }
        ans_field = fields.get("answer", "answer")
        if ans_field and raw.get(ans_field):
            rec["answer"] = str(raw[ans_field])
        sol_field = fields.get("solution")
        if sol_field and raw.get(sol_field):
            if source == "sciq":
                # sciq 'support' is explanatory prose, not worked solution
                rec["explanation"] = str(raw[sol_field])
            else:
                rec["solution"] = str(raw[sol_field])
        for f in ("source_id", "difficulty", "explanation"):
            if raw.get(f) is not None:
                rec[f] = raw[f]
        if source == "math-competition":
            # MATH parquet: level 'Level 3' -> difficulty 3, type -> subject
            if raw.get("level"):
                m = re.search(r"\d", str(raw["level"]))
                rec["difficulty"] = int(m.group()) if m else None
            rec["subject"] = {"counting_&_probability": "counting_and_probability",
                              }.get(str(raw.get("type", "")).lower().replace(" ", "_"),
                                    str(raw.get("type", subject)).lower().replace(" ", "_"))
        rec.setdefault("answer_type",
                       {"gsm8k": "numeric", "math-competition": "expression",
                        "sciq": "free_text"}.get(source, "text"))
        if not rec.get("source_id"):
            rec["source_id"] = str(raw.get("id", i))
        rec["id"] = make_id(source, rec["source_id"], rec["question"])
        cleaned, issues = normalize_example(
            rec, min_question=int(quality.get("min_question_chars", 12)),
            max_question=int(quality.get("max_question_chars", 4000)),
            max_answer=int(quality.get("max_answer_chars", 2000)),
            max_solution=int(quality.get("max_solution_chars", 16000)))
        if cleaned is None:
            rejects.append({"source": source, "source_id": rec["source_id"],
                            "reason": "; ".join(issues)})
            continue
        target, reject_reason = build_target(cleaned)
        if target is None:
            rejects.append({"source": source, "source_id": rec["source_id"],
                            "reason": reject_reason})
            continue
        cleaned["target_response"] = target
        records.append(cleaned)
        kept += 1
    return {"source": source, "hf_id": load_note[0], "actual_load": load_note[1],
            "rows": len(rows), "kept_with_target": kept}


def main() -> int:
    # ---- 1. the sets that must be excluded ----
    t30_used = set()
    for fname in ("train.jsonl", "validation.jsonl"):
        for rec in read_jsonl(T30_CORPUS / fname):
            t30_used.add(fingerprint(rec["question"]))
    print("T30 corpus fingerprints (train+val):", len(t30_used), flush=True)

    t31_eval = set()
    for arm in ("base", "adapter"):
        for b in ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq"):
            for r in read_jsonl(ROOT / f"evaluations/t31/scored/{arm}/{b}.jsonl"):
                t31_eval.add(fingerprint(r["question"]))
    print("T31 evaluation fingerprints:", len(t31_eval), flush=True)

    # ---- 2. load the pools exactly as the T30 build did ----
    quality = load_yaml(ROOT / "configs" / "data.yaml")["quality"]
    records: list[dict] = []
    rejects: list[dict] = []
    load_log: list[dict] = []

    from datasets import load_dataset

    ds = load_dataset("openai/gsm8k", "main", split="train")
    load_log.append(_normalize_all(
        list(ds), "gsm8k", "mathematics", "arithmetic_word_problems", "MIT",
        {"question": "question", "answer": "answer"},
        ("openai/gsm8k", "openai/gsm8k#main [train]"), quality, records, rejects))

    # MATH parquet mirror, same per-config fields as the builder
    rows = []
    for cfg in MATH_CONFIGS:
        cfg_ds = load_dataset("EleutherAI/hendrycks_math", cfg, split="train")
        rows.extend({"problem": r["problem"], "level": r["level"],
                     "type": r["type"], "solution": r["solution"]} for r in cfg_ds)
    load_log.append(_normalize_all(
        rows, "math-competition", "mathematics", "competition_math", "MIT",
        {"question": "problem", "answer": "solution", "solution": "solution"},
        ("hendrycks/competition_math (canonical ref)",
         "EleutherAI/hendrycks_math (parquet mirror; script loader "
         "incompatible with datasets 5.x)"), quality, records, rejects))

    ds = load_dataset("allenai/sciq", split="train")
    load_log.append(_normalize_all(
        list(ds), "sciq", "general_science", "science_qa", "CC-BY-NC-3.0",
        {"question": "question", "answer": "correct_answer", "solution": "support"},
        ("allenai/sciq", "allenai/sciq [train]"), quality, records, rejects))

    for entry in load_log:
        print(entry["source"], "rows", entry["rows"], "-> kept", entry["kept_with_target"],
              flush=True)
    total_pool = len(records)

    # ---- 3. exclude ----
    fresh, seen, used_t30, eval_leak = [], set(), [], []
    eval_used_sources = Counter()
    for rec in records:
        fp = fingerprint(rec["question"])
        if fp in seen:
            rejects.append({"source": rec["source"], "source_id": rec["source_id"],
                            "reason": "within_pool_duplicate"})
            continue
        seen.add(fp)
        if fp in t30_used:
            used_t30.append(rec["source"])
            continue
        if fp in t31_eval:
            eval_leak.append(rec["source"])
            eval_used_sources[rec["source"]] += 1
            continue
        fresh.append(rec)

    counts = Counter(r["source"] for r in fresh)
    print("pool total:", total_pool, "| fresh:", len(fresh),
          "| excluded T30-used:", len(used_t30),
          "| excluded T31-eval:", len(eval_leak),
          "| within-pool dups:", sum(1 for r in rejects
                                     if r["reason"] == "within_pool_duplicate"),
          flush=True)

    POOLS.mkdir(parents=True, exist_ok=True)
    out = POOLS / "fresh_pool.jsonl"
    write_jsonl(out, fresh)

    body = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                   for r in fresh)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    manifest = {
        "artifact": "T32_FRESH_POOL",
        "schema_version": "t32-mixture-v1",
        "pipeline": ("normalize_all-equivalent of scripts/build_sft_corpus.py "
                     "(field mappings, data.yaml quality limits, build_target "
                     "canonical targets, make_id)"),
        "load_log": load_log,
        "rejects_n": len(rejects),
        "pool_total_kept": total_pool,
        "excluded": {
            "already_in_t30_corpus_fingerprints": len(used_t30),
            "by_source_t30": dict(Counter(used_t30)),
            "matches_t31_eval_question": len(eval_leak),
            "by_source_t31": dict(eval_used_sources),
            "within_pool_duplicate": sum(1 for r in rejects
                                         if r["reason"] == "within_pool_duplicate"),
        },
        "fresh": dict(counts),
        "records": out.as_posix(),
        "sha256": digest,
        "notes": [
            "Fingerprints via the same text_fingerprint used by the T30 build.",
            "ARC is not pooled (eval_only); T31 eval questions (incl. MATH-500 "
            "test membership) are excluded by fingerprint.",
            "Pools are complete inventories; candidate mixtures select "
            "deterministically from this file and the selection is recorded.",
        ],
    }
    (POOLS / "fresh_pool_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    (POOLS / "fresh_pool_rejects.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rejects),
        encoding="utf-8", newline="\n")
    print("wrote", out, digest[:12], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())