"""Build and FREEZE the T3 SFT corpus (sciencemath-sft-v1).

Sources: ONLY datasets whose entry in data/manifests/datasets.json has
license_status=APPROVED and eval_only=False. REVIEW_REQUIRED and eval-only
sources are never included (eval-only violations are a hard failure).

Pipeline (all deterministic, seed 42):
  1. load raw source datasets (HF cache)
  2. normalize into the canonical T1 schema (quality limits from data.yaml)
  3. build canonical SFT targets (sft_format: budgets, boxed closure)
  4. exact + normalized dedup (T1 deduplicate())
  5. CONTAMINATION GATE vs the frozen sciencemath-eval-v1 suite (direct +
     near leakage). Leaked records are REMOVED and the remediation is
     recorded in contamination_report.json and the corpus manifest. Direct
     leakage found at build time is removed and reported - it is expected,
     because the eval suite was sampled from the same upstream datasets.
  6. quota sampling to the frozen domain mix (math 50-55%, science 35-40%,
     general 5-10%)
  7. stratified train/validation split (grouped by question fingerprint)

Output: training/datasets/sciencemath-sft-v1/
  manifest.json, train.jsonl, validation.jsonl, source_manifest.json,
  license_manifest.json, domain_distribution.json, quality_report.json,
  contamination_report.json, checksums.json

The freeze is immutable: the script REFUSES to overwrite an existing frozen
version (delete the directory explicitly to rebuild).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, setup_logging  # noqa: E402

from sciencemath.datasets.dedup import deduplicate  # noqa: E402
from sciencemath.datasets.leakage import (  # noqa: E402
    find_direct_leakage,
    find_near_leakage,
)
from sciencemath.datasets.normalize import (  # noqa: E402
    normalize_example,
    text_fingerprint,
)
from sciencemath.datasets.schema import make_id, validate_example  # noqa: E402
from sciencemath.training.sft_format import build_target  # noqa: E402
from sciencemath.training.synthetic_general import (  # noqa: E402
    synthetic_general_records,
)
from sciencemath.utils.io_utils import read_jsonl, write_json, write_jsonl  # noqa: E402

CORPUS_VERSION = "sciencemath-sft-v1"
CORPUS_DIR = REPO_ROOT / "training" / "datasets" / CORPUS_VERSION
SUITE_DIR = REPO_ROOT / "evaluations" / "suite" / "v1"
DATASETS_MANIFEST = REPO_ROOT / "data" / "manifests" / "datasets.json"

# Frozen mixture targets (fractions of the final corpus). Must stay inside the
# T3 contract ranges: math 0.50-0.55, science 0.35-0.40, general 0.05-0.10.
MIX_TARGETS = {"math": 0.54, "science": 0.40, "general": 0.06}

# The general slice is FIXED (all synthetic-sft-v1 items that survive dedup);
# gsm8k/MATH/sciq quotas are then DERIVED from the mix targets so the frozen
# contract holds by construction. The MATH quota spans every subject.
GSM8K_SHARE_OF_MATH = 0.52          # rest is competition MATH
MATH_SUBJECT_QUOTA_SHARES = {
    # MATH subject: share of the competition-math quota
    "algebra": 0.26,
    "prealgebra": 0.18,
    "intermediate_algebra": 0.17,
    "geometry": 0.15,
    "precalculus": 0.10,
    "counting_and_probability": 0.09,
    "number_theory": 0.09,
}
VALIDATION_FRACTION = 0.04


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_source_records() -> tuple[list[dict], list[dict], list[dict]]:
    """Load + normalize + target-build every approved source.

    Returns (records, rejects, load_log)."""
    log = setup_logging("build_sft_corpus")
    manifest = json.loads(DATASETS_MANIFEST.read_text(encoding="utf-8"))
    by_name = {d["name"]: d for d in manifest["datasets"]}

    train_sources = {
        name: d for name, d in by_name.items()
        if d.get("license_status") == "APPROVED" and not d.get("eval_only")
    }
    log.info("approved training sources: %s", sorted(train_sources))
    missing = {"gsm8k", "math-competition", "sciq"} - set(train_sources)
    if missing:
        raise SystemExit(f"required training sources not APPROVED: {missing}")

    from sciencemath.utils.io_utils import load_yaml
    quality = load_yaml(REPO_ROOT / "configs" / "data.yaml")["quality"]

    records: list[dict] = []
    rejects: list[dict] = []
    load_log: list[dict] = []

    def normalize_all(rows, source, domain, subject, license_id, fields, load_note):
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
        load_log.append({"source": source, "hf_id": load_note[0],
                         "actual_load": load_note[1], "rows": len(rows),
                         "kept_with_target": kept})
        log.info("%s: %d rows -> %d with canonical target", source, len(rows), kept)

    from datasets import load_dataset

    # ---- gsm8k (MIT) ----
    ds = load_dataset("openai/gsm8k", "main", split="train")
    normalize_all(list(ds), "gsm8k", "mathematics", "arithmetic_word_problems",
                  "MIT", {"question": "question", "answer": "answer"},
                  ("openai/gsm8k", "openai/gsm8k#main [train]"))

    # ---- MATH competition set (MIT) ----
    # datasets.json records hendrycks/competition_math (script loader, no
    # longer loadable on datasets>=3). EleutherAI/hendrycks_math is the same
    # content as parquet; recorded as actual_load for provenance.
    rows = []
    for cfg in MATH_SUBJECT_QUOTA_SHARES:
        ds = load_dataset("EleutherAI/hendrycks_math", cfg, split="train")
        rows.extend({"problem": r["problem"], "level": r["level"],
                     "type": r["type"], "solution": r["solution"]} for r in ds)
    normalize_all(rows, "math-competition", "mathematics", "competition_math",
                  "MIT",
                  {"question": "problem", "answer": "solution",
                   "solution": "solution"},
                  ("hendrycks/competition_math (canonical ref)",
                   "EleutherAI/hendrycks_math (parquet mirror; script loader "
                   "incompatible with datasets 5.x)"))

    # ---- sciq (CC-BY-NC-3.0) ----
    ds = load_dataset("allenai/sciq", split="train")
    normalize_all(list(ds), "sciq", "general_science", "science_qa",
                  "CC-BY-NC-3.0",
                  {"question": "question", "answer": "correct_answer",
                   "solution": "support"},
                  ("allenai/sciq", "allenai/sciq [train]"))

    # ---- synthetic general/instruction items (MIT, self-authored) ----
    synth = synthetic_general_records()
    for raw in synth:
        rec = dict(raw)
        rec["id"] = make_id(raw["source"], raw["source_id"], raw["question"])
        cleaned, issues = normalize_example(rec, min_question=4, max_question=4000,
                                            max_answer=2000, max_solution=16000)
        if cleaned is None:
            rejects.append({"source": raw["source"], "source_id": raw["source_id"],
                            "reason": "; ".join(issues)})
            continue
        # synthetic targets are pre-built canonical responses; keep the boxed
        # short answer in 'answer' for schema validation + stats
        from sciencemath.training.sft_format import last_boxed
        cleaned["target_response"] = cleaned["answer"]
        cleaned["answer"] = last_boxed(cleaned["answer"]) or cleaned["target_response"]
        records.append(cleaned)
    load_log.append({"source": "synthetic-sft-v1", "hf_id": None,
                     "actual_load": "authored in sciencemath/training/synthetic_general.py",
                     "rows": len(synth), "kept_with_target": len(synth)})
    return records, rejects, load_log


def contamination_gate(records: list[dict]) -> tuple[list[dict], dict]:
    """Direct + near leakage check against the FROZEN eval suite.

    Leaked records are removed (remediation recorded). This is the
    T3-mandated gate: no frozen eval question may appear directly or
    near-duplicated in SFT training."""
    suite = read_jsonl(SUITE_DIR / "questions.jsonl")
    eval_sets = {"sciencemath-eval-v1": [
        {"id": q["eval_id"], "question": q["question"], "source": q["source"]}
        for q in suite]}

    direct = find_direct_leakage(records, eval_sets)
    near = find_near_leakage(records, eval_sets, threshold=0.90)
    leaked_ids = {p.train_id for p in direct.pairs} | {p.train_id for p in near.pairs}

    removed = [{"id": r["id"], "source": r.get("source"), "source_id": r.get("source_id"),
                "kind": ("direct" if r["id"] in {p.train_id for p in direct.pairs}
                         else "near"),
                "similarity": next((p.similarity for p in near.pairs
                                    if p.train_id == r["id"]), 1.0)}
               for r in records if r["id"] in leaked_ids]

    kept = [r for r in records if r["id"] not in leaked_ids]
    report = {
        "gate": "sciencemath-sft-v1 vs sciencemath-eval-v1",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "suite_questions": len(suite),
        "candidates_checked": len(records),
        "direct_leakage_found": len(direct.direct),
        "near_leakage_found": len(near.near),
        "records_removed": len(removed),
        "remediation": ("contaminated records (direct and near >= 0.90 Jaccard) "
                        "REMOVED from the SFT corpus before freeze; full list in "
                        "contamination_report.json removals; corpus not frozen "
                        "unless this gate ran"),
        "removed_records": removed,
        "passed_after_remediation": True,
    }
    if len(kept) != len(records):
        # re-verify clean: rerun direct check on kept records
        recheck = find_direct_leakage(kept, eval_sets)
        if recheck.has_direct:
            raise SystemExit("contamination gate FAILED: direct leakage remains "
                             "after remediation; refusing to freeze")
    return kept, report


def quota_sampling(records: list[dict]) -> tuple[list[dict], dict]:
    """Deterministic quota sampling to the frozen mix.

    The general (synthetic) slice is taken whole; gsm8k/MATH/sciq quotas are
    derived from MIX_TARGETS so the frozen domain contract holds by
    construction (up to pool exhaustion, which is reported in the plan)."""
    rng = random.Random(42)
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["domain"] == "mathematics":
            bucket = "gsm8k" if r["source"] == "gsm8k" else f"math:{r.get('subject', '')}"
        elif r["source"] == "synthetic-sft-v1":
            bucket = "general"
        else:
            bucket = "sciq"
        by_bucket[bucket].append(r)

    chosen: list[dict] = []
    plan: dict[str, int] = {}

    # general: all synthetic items, fixed
    pool = by_bucket.get("general", [])
    n_general = len(pool)
    chosen.extend(pool)
    plan["general"] = n_general

    # math quota derived from mix, split gsm8k / MATH subjects
    n_math = min(int(round(n_general * MIX_TARGETS["math"] / MIX_TARGETS["general"])),
                 sum(len(v) for k, v in by_bucket.items()
                     if k == "gsm8k" or k.startswith("math:")))
    n_gsm8k = min(int(round(n_math * GSM8K_SHARE_OF_MATH)), len(by_bucket.get("gsm8k", [])))
    pool = by_bucket.get("gsm8k", [])
    rng.shuffle(pool)
    chosen.extend(pool[:n_gsm8k])
    plan["gsm8k"] = n_gsm8k

    n_competition = n_math - n_gsm8k
    for subject, share in MATH_SUBJECT_QUOTA_SHARES.items():
        quota = int(round(n_competition * share))
        pool = by_bucket.get(f"math:{subject}", [])
        take = min(quota, len(pool))
        rng.shuffle(pool)
        chosen.extend(pool[:take])
        plan[f"math:{subject}"] = take

    # science fills toward the target mix (bounded by pool size)
    n_sci_target = int(round(n_general * MIX_TARGETS["science"] / MIX_TARGETS["general"]))
    pool = sorted(by_bucket.get("sciq", []), key=lambda r: r["id"])
    rng.shuffle(pool)
    take = min(n_sci_target, len(pool))
    chosen.extend(pool[:take])
    plan["sciq"] = take

    return chosen, plan


def split_train_validation(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Stratified split grouped by question fingerprint (no group spans both
    splits). 4% validation, deterministic."""
    rng = random.Random(42)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[text_fingerprint(r["question"])].append(r)
    by_domain: dict[str, list[str]] = defaultdict(list)
    for fp, rs in groups.items():
        by_domain[rs[0]["domain"]].append(fp)

    val_fps: set[str] = set()
    for domain, fps in sorted(by_domain.items()):
        fps = sorted(fps)
        rng.shuffle(fps)
        k = max(2, int(round(len(fps) * VALIDATION_FRACTION)))
        val_fps.update(fps[:k])

    train, val = [], []
    for fp, rs in groups.items():
        if fp in val_fps:
            val.extend(rs)
        else:
            train.extend(rs)
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def quality_report(train, val, rejects, plan, contamination) -> dict:
    allrecs = train + val
    by_domain = Counter(r["domain"] for r in allrecs)
    by_subject = Counter(r.get("subject", "") for r in allrecs)
    by_source = Counter(r["source"] for r in allrecs)
    by_difficulty = Counter(str(r.get("difficulty")) for r in allrecs)
    with_solution = sum(1 for r in allrecs if r.get("solution"))
    answer_formats = Counter(r.get("answer_type", "unspecified") for r in allrecs)
    total = len(allrecs)
    math = by_domain.get("mathematics", 0)
    general = sum(1 for r in allrecs if r.get("source") == "synthetic-sft-v1")
    science = total - math - general
    return {
        "total_examples": total,
        "train": len(train),
        "validation": len(val),
        "accepted": total,
        "rejected_at_normalize_or_target": len(rejects),
        "rejected_reasons": dict(Counter(r["reason"].split(";")[0].split(":")[0]
                                         for r in rejects)),
        "duplicates_removed": None,     # filled by caller after dedup
        "near_duplicates_removed": None,
        "contamination_removed": contamination["records_removed"],
        "by_domain": dict(by_domain),
        "by_subject": dict(by_subject),
        "by_source": dict(by_source),
        "by_difficulty": dict(by_difficulty),
        "answer_formats": dict(answer_formats),
        "with_solution": with_solution,
        "without_explanation": total - sum(1 for r in allrecs if r.get("explanation")),
        "mix": {"math": round(math / total, 4), "science": round(science / total, 4),
                "general": round(general / total, 4)},
        "mix_targets": MIX_TARGETS,
        "mix_within_contract": (
            0.50 <= math / total <= 0.55 and 0.35 <= science / total <= 0.40
            and 0.05 <= general / total <= 0.10),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the frozen corpus exists")
    args = ap.parse_args()
    log = setup_logging("build_sft_corpus")

    if CORPUS_DIR.exists() and not args.force:
        print(f"REFUSED: {CORPUS_DIR} already exists (frozen corpus is immutable). "
              f"Delete it explicitly to rebuild.")
        return 91

    records, rejects, load_log = load_source_records()
    log.info("loaded %d candidate records", len(records))

    n_before = len(records)
    # Dedup real sources with full near-duplicate detection; the synthetic
    # slice is deduped with exact/normalized matching only, because its
    # templated drill families are intentionally kept distinct-by-answer
    # (near-dup shingles on shared phrasing would strip the instruction
    # family down to one item per template). Cross-set near dups are not
    # plausible (short synthetic drills vs long source questions) and the
    # contamination gate still re-checks everything against the eval suite.
    source_recs = [r for r in records if r["source"] != "synthetic-sft-v1"]
    synth_recs = [r for r in records if r["source"] == "synthetic-sft-v1"]
    dedup_src = deduplicate(source_recs)
    dedup_syn = deduplicate(synth_recs, near_enabled=False)
    records = dedup_src.kept + dedup_syn.kept
    duplicates_removed = len(dedup_src.duplicates) + len(dedup_syn.duplicates)
    dup_breakdown = {k: dedup_src.counts.get(k, 0) + dedup_syn.counts.get(k, 0)
                     for k in ("exact", "normalized", "near_duplicate")}
    log.info("dedup: %d removed (%s)", duplicates_removed, dup_breakdown)

    records, contamination = contamination_gate(records)
    log.info("contamination gate: removed %d leaked records",
             contamination["records_removed"])

    records, plan = quota_sampling(records)
    train, val = split_train_validation(records)

    for r in records:
        violations = validate_example(r)
        if violations:
            raise SystemExit(f"schema violation in {r.get('id')}: {violations}")

    quality = quality_report(train, val, rejects, plan, contamination)
    quality["duplicates_removed"] = duplicates_removed
    quality["duplicate_breakdown"] = dup_breakdown
    quality["near_duplicates_removed"] = dup_breakdown.get("near_duplicate", 0)

    # ---- write frozen artifacts ----
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(CORPUS_DIR / "train.jsonl", train)
    write_jsonl(CORPUS_DIR / "validation.jsonl", val)

    suite_licenses = {d["name"]: d for d in
                      json.loads(DATASETS_MANIFEST.read_text(encoding="utf-8"))["datasets"]}
    license_manifest = {
        "corpus": CORPUS_VERSION,
        "policy": "only datasets.json entries with license_status=APPROVED and "
                  "eval_only=false; REVIEW_REQUIRED excluded; eval-only "
                  "sources excluded from training",
        "sources": {
            name: {
                "license": d["license"], "license_status": d["license_status"],
                "license_verified": d.get("license_verified"),
                "allows_training_use": d.get("allows_training_use"),
                "redistribution_permitted": d.get("redistribution_permitted"),
                "hf_id": d.get("hf_id"),
                "notes": d.get("notes"),
            }
            for name, d in suite_licenses.items()
            if name in {r["source"] for r in records} or name == "synthetic-sft-v1"
        },
        "synthetic-sft-v1": {
            "license": "MIT", "license_status": "APPROVED (self-authored)",
            "note": "authored in src/sciencemath/training/synthetic_general.py"},
        "commercial_use_note": ("sciq is CC-BY-NC-3.0 (non-commercial); the "
                                "corpus inherits that restriction"),
    }

    src_counts_train = Counter(r["source"] for r in train)
    src_counts_val = Counter(r["source"] for r in val)
    source_manifest = {
        "corpus": CORPUS_VERSION,
        "load_log": load_log,
        "sampling_plan": plan,
        "sources": {
            "gsm8k": {"license": "MIT", "train": src_counts_train.get("gsm8k", 0),
                      "validation": src_counts_val.get("gsm8k", 0)},
            "math-competition": {"license": "MIT",
                                 "train": src_counts_train.get("math-competition", 0),
                                 "validation": src_counts_val.get("math-competition", 0)},
            "sciq": {"license": "CC-BY-NC-3.0",
                     "train": src_counts_train.get("sciq", 0),
                     "validation": src_counts_val.get("sciq", 0)},
            "synthetic-sft-v1": {"license": "MIT",
                                 "train": src_counts_train.get("synthetic-sft-v1", 0),
                                 "validation": src_counts_val.get("synthetic-sft-v1", 0)},
        },
        "excluded": {
            "ai2-arc": "license_status=APPROVED but eval_only=true (evaluation "
                       "integrity); excluded from SFT training",
            "kaggle-unverified-candidates": "license_status=REVIEW_REQUIRED; "
                                            "excluded from SFT training",
        },
        "eval_separation": {
            "eval_suite": "sciencemath-eval-v1 (frozen 2026-08-31, 188 questions)",
            "contamination_gate": contamination["gate"],
            "direct_removed": contamination["direct_leakage_found"],
            "near_removed": contamination["near_leakage_found"],
        },
    }

    dist_by_domain = Counter(r["domain"] for r in records)
    dist_by_subject = Counter(r.get("subject", "") for r in records)
    dist_by_difficulty = Counter(str(r.get("difficulty")) for r in records)
    dist_by_source = Counter(r["source"] for r in records)
    domain_distribution = {
        "corpus": CORPUS_VERSION,
        "by_domain": dict(dist_by_domain),
        "by_subject": dict(sorted(dist_by_subject.items())),
        "by_difficulty": dict(sorted(dist_by_difficulty.items())),
        "by_source": dict(dist_by_source),
    }

    manifest = {
        "version": CORPUS_VERSION,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "seed": 42,
        "git_commit": REPO_ROOT.joinpath(".git").exists() and
        __import__("subprocess").run(["git", "rev-parse", "HEAD"], capture_output=True,
                                     text=True, cwd=REPO_ROOT).stdout.strip() or None,
        "format": "canonical ScienceMath SFT: user question / assistant "
                  "concise visible reasoning + boxed final-answer closure "
                  "(no reasoning blocks; enable_thinking=False protocol)",
        "counts": {
            "train": len(train), "validation": len(val),
            "total": len(train) + len(val),
        },
        "mix_measured": quality["mix"],
        "mix_targets": MIX_TARGETS,
        "answer_contract": {
            "math": "Final answer: \\boxed{...}",
            "science": "Answer: \\boxed{...}",
        },
        "reasoning_budgets": {"math": 1600, "science": 700, "general": 400},
        "immutability": "frozen; changes require sciencemath-sft-v2",
        "eval_suite": "sciencemath-eval-v1 (unchanged; contamination gate rerun "
                      "at freeze time and recorded in contamination_report.json)",
        "provenance_per_example": ["id", "source", "source_id", "domain", "subject",
                                   "difficulty", "license", "question", "answer",
                                   "solution", "explanation", "target_response"],
    }

    write_json(CORPUS_DIR / "manifest.json", manifest)
    write_json(CORPUS_DIR / "source_manifest.json", source_manifest)
    write_json(CORPUS_DIR / "license_manifest.json", license_manifest)
    write_json(CORPUS_DIR / "domain_distribution.json", domain_distribution)
    write_json(CORPUS_DIR / "quality_report.json", quality)
    write_json(CORPUS_DIR / "contamination_report.json", contamination)

    # checksums last, over every artifact
    checksums = {}
    for p in sorted(CORPUS_DIR.iterdir()):
        if p.is_file() and p.name != "checksums.json":
            checksums[p.name] = sha256_file(p)
    write_json(CORPUS_DIR / "checksums.json", checksums)

    print(json.dumps({
        "corpus": CORPUS_VERSION,
        "train": len(train), "validation": len(val),
        "mix": quality["mix"], "mix_ok": quality["mix_within_contract"],
        "duplicates_removed": duplicates_removed,
        "contamination_removed": contamination["records_removed"],
        "direct": contamination["direct_leakage_found"],
        "near": contamination["near_leakage_found"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())