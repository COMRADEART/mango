"""Build and FREEZE the T2 evaluation suite (sciencemath-eval-v1).

Sources: only T1-license-verified datasets. Sampling is seeded and
deterministic (no use of Python's hash()). Before freezing, ALL current
training data is checked for contamination against the candidate eval
questions (T1 direct + near leakage detection); direct leakage FAILS the
milestone gate, is reported to leakage_check.json, and the suite is NOT
frozen.

Categories with no license-verified evaluation source are recorded as
INSUFFICIENT_VERIFIED_EVAL_DATA rather than fabricated. Fully synthetic items
are used ONLY for instruction_following and uncertainty_calibration, and are
marked "synthetic": true, source "synthetic-v1".

Output: evaluations/suite/v1/{manifest.json, questions.jsonl, checksum.json,
category_manifest.json, source_manifest.json, leakage_check.json}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, setup_logging  # noqa: E402

from sciencemath.datasets.leakage import (  # noqa: E402
    find_direct_leakage,
    find_near_leakage,
)
from sciencemath.datasets.normalize import text_fingerprint  # noqa: E402
from sciencemath.utils.io_utils import (  # noqa: E402
    read_jsonl,
    write_json,
    write_jsonl,
)

SUITE_VERSION = "sciencemath-eval-v1"
SUITE_DIR = REPO_ROOT / "evaluations" / "suite" / "v1"

# Fixed per-source sample sizes: small enough for 6 GB VRAM runtime, large
# enough for per-category signal. Recorded in manifest.json.
SAMPLE_PLAN = {
    "gsm8k": 40,
    "ai2-arc": 30,
    "sciq": 30,
}
MATH_PER_SUBJECT = 10
MATH_MAX_TOTAL = 70

MATH_SUBJECT_TO_CATEGORY = {
    "algebra": "algebra",
    "intermediate_algebra": "algebra",
    "prealgebra": "algebra",
    "number_theory": "algebra",
    "geometry": "geometry",
    "precalculus": "trigonometry_precalculus",
    "counting_and_probability": "probability_statistics",
}
MATH_CONFIGS = ["algebra", "counting_and_probability", "geometry",
                "intermediate_algebra", "number_theory", "prealgebra",
                "precalculus"]

SYNTHETIC_INSTRUCTION = [
    {"question": "Reply with the single word: blue", "expected_answer": "blue"},
    {"question": "Reply with the single word: 17", "expected_answer": "17"},
    {"question": "How many sides does a hexagon have? Reply with the number as a word only.", "expected_answer": "six"},
    {"question": "Reply with the single word: hydrogen", "expected_answer": "hydrogen"},
    {"question": "What is the chemical symbol for sodium? Reply with the two-letter symbol only.", "expected_answer": "Na"},
    {"question": "How many days are in a leap year? Reply with the number only.", "expected_answer": "366"},
    {"question": "What is the SI unit of force? Reply with the unit name only.", "expected_answer": "newton"},
    {"question": "Reply with the single word: mitochondrion", "expected_answer": "mitochondrion"},
    {"question": "State the freezing point of water in degrees Celsius as a bare number.", "expected_answer": "0"},
    {"question": "How many continents are there? Reply with the number only.", "expected_answer": "7"},
]

SYNTHETIC_CALIBRATION = [
    {"question": "What was the exact temperature in Berlin, Germany on 18 March 1876?",
     "expected_answer": "__UNKNOWN__"},
    {"question": "How many ants are alive on Earth right now?", "expected_answer": "__UNKNOWN__"},
    {"question": "What color shoes did Isaac Newton wear on the day he formulated calculus?",
     "expected_answer": "__UNKNOWN__"},
    {"question": "What is the exact mass, in kilograms, of the first human to observe Saturn through a telescope?",
     "expected_answer": "__UNKNOWN__"},
    {"question": "Which specific atom will undergo radioactive decay next somewhere in the universe?",
     "expected_answer": "__UNKNOWN__"},
    {"question": "What exact food did the inventor of the first electric battery eat for breakfast on the day he invented it?",
     "expected_answer": "__UNKNOWN__"},
    {"question": "What is my personal favorite scientific equation?",
     "expected_answer": "__UNKNOWN__"},
    {"question": "On what exact date will the next magnitude-9 earthquake strike the Pacific Ring of Fire?",
     "expected_answer": "__UNKNOWN__"},
]

# Categories a frozen suite honestly cannot fill from verified sources. Recorded
# as INSUFFICIENT_VERIFIED_EVAL_DATA, never with fabricated questions.
EMPTY_CATEGORY_NOTES = {
    "calculus": "no license-verified calculus evaluation source available; the "
                "MATH precalculus subject is the closest verified content and is "
                "kept under trigonometry_precalculus",
    "physics": "no verified subject-labeled physics evaluation source ingested",
    "chemistry": "no verified subject-labeled chemistry evaluation source ingested",
    "biology": "no verified subject-labeled biology evaluation source ingested",
    "astronomy_earth_science": "no verified astronomy/earth-science evaluation source ingested",
    "interdisciplinary": "no verified interdisciplinary evaluation source ingested",
}
ALL_CATEGORIES = ["arithmetic", "algebra", "geometry",
                  "trigonometry_precalculus", "calculus",
                  "probability_statistics", "physics", "chemistry", "biology",
                  "astronomy_earth_science", "general_science",
                  "interdisciplinary", "instruction_following",
                  "uncertainty_calibration"]


def _last_boxed_text(text: str) -> str | None:
    idx = text.rfind("\\boxed{")
    if idx == -1:
        return None
    start = idx + len("\\boxed")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i].strip()
    return None


def _stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def load_sources() -> tuple[list[dict], list[dict]]:
    """Load raw candidate questions. Returns (questions, load_log)."""
    from datasets import load_dataset

    questions: list[dict] = []
    log: list[dict] = []
    base = {"synthetic": False, "source_split": "test"}

    # ---- gsm8k (MIT, verified 2026-08-31) ----
    try:
        ds = load_dataset("openai/gsm8k", "main")["test"]
        for row in ds:
            m = re.search(r"####\s*(.+)", row["answer"])
            if not m:
                continue
            questions.append({**base, "source": "gsm8k", "license": "MIT",
                              "source_id": row.get("unique_id", ""),
                              "category": "arithmetic", "answer_type": "numeric",
                              "question": row["question"],
                              "expected_answer": m.group(1).strip()})
        log.append({"source": "gsm8k", "status": "OK", "rows": len(ds)})
    except Exception as exc:
        log.append({"source": "gsm8k", "status": f"FAILED: {type(exc).__name__}: {exc}"})

    # ---- MATH competition (MIT) ----
    # Primary: EleutherAI/hendrycks_math parquet mirror, per-subject configs.
    # Fallback: hendrycks/competition_math (needs trust_remote_code).
    math_q, math_log = _load_math(load_dataset)
    questions.extend(math_q)
    log.append(math_log)

    # ---- ai2-arc (CC-BY-SA-4.0, eval_only, verified) ----
    try:
        ds = load_dataset("allenai/ai2_arc", "ARC-Challenge")["test"]
        for row in ds:
            labels = row["choices"]["label"]
            texts = row["choices"]["text"]
            if not labels or row["answerKey"] not in labels:
                continue
            questions.append({**base, "source": "ai2-arc", "license": "CC-BY-SA-4.0",
                              "source_id": row["id"], "category": "general_science",
                              "answer_type": "multiple_choice",
                              "question": row["question"],
                              "choices": [texts[labels.index(l)] for l in labels],
                              "expected_answer": row["answerKey"]})
        log.append({"source": "ai2-arc", "status": "OK", "rows": len(ds)})
    except Exception as exc:
        log.append({"source": "ai2-arc", "status": f"FAILED: {type(exc).__name__}: {exc}"})

    # ---- sciq (CC-BY-NC-3.0, verified; non-commercial license recorded) ----
    try:
        ds = load_dataset("allenai/sciq")["test"]
        for i, row in enumerate(ds):
            answer = row["correct_answer"]
            choices = [row["distractor1"], row["distractor2"],
                       row["distractor3"], answer]
            # deterministic shuffle: NO hash() (randomized per process)
            choices = [c for c in choices if c]
            rng = random.Random(_stable_seed(str(answer)))
            rng.shuffle(choices)
            letter = chr(65 + choices.index(answer))
            questions.append({**base, "source": "sciq", "license": "CC-BY-NC-3.0",
                              "source_id": f"sciq-test-{i}",
                              "category": "general_science",
                              "answer_type": "multiple_choice",
                              "question": row["question"], "choices": choices,
                              "expected_answer": letter})
        log.append({"source": "sciq", "status": "OK", "rows": len(ds),
                    "note": "CC-BY-NC-3.0 - evaluated only; excluded from any "
                            "commercial use via data/manifests/datasets.json"})
    except Exception as exc:
        log.append({"source": "sciq", "status": f"FAILED: {type(exc).__name__}: {exc}"})

    # ---- synthetic (isolated, marked) ----
    for i, item in enumerate(SYNTHETIC_INSTRUCTION):
        questions.append({"source": "synthetic-v1", "source_id": f"synth-instr-{i}",
                          "source_split": "synthetic", "license": "MIT",
                          "synthetic": True, "category": "instruction_following",
                          "answer_type": "text", "question": item["question"],
                          "expected_answer": item["expected_answer"]})
    for i, item in enumerate(SYNTHETIC_CALIBRATION):
        questions.append({"source": "synthetic-v1", "source_id": f"synth-calib-{i}",
                          "source_split": "synthetic", "license": "MIT",
                          "synthetic": True, "category": "uncertainty_calibration",
                          "answer_type": "text", "question": item["question"],
                          "expected_answer": item["expected_answer"]})
    return questions, log


def _load_math(load_dataset) -> tuple[list[dict], dict]:
    q: list[dict] = []
    loader_name: str | None = None
    try:
        for subj in MATH_CONFIGS:
            ds = load_dataset("EleutherAI/hendrycks_math", subj)["test"]
            for i, row in enumerate(ds):
                answer = _last_boxed_text(row["solution"])
                if not answer:
                    continue
                q.append({"source": "math-competition",
                          "source_id": f"math-{subj}-{i}", "source_split": "test",
                          "license": "MIT", "synthetic": False,
                          "subject_raw": subj,
                          "category": MATH_SUBJECT_TO_CATEGORY[subj],
                          "answer_type": "numeric", "question": row["problem"],
                          "expected_answer": answer})
        loader_name = "EleutherAI/hendrycks_math (parquet mirror, per-subject configs)"
    except Exception as exc1:
        try:
            ds = load_dataset("hendrycks/competition_math",
                              trust_remote_code=True)["test"]
            for i, row in enumerate(ds):
                answer = _last_boxed_text(row["solution"])
                if not answer:
                    continue
                subject = str(row.get("type") or row.get("subject") or "").lower().replace(" ", "_")
                cat = MATH_SUBJECT_TO_CATEGORY.get(subject)
                if cat is None:
                    continue
                q.append({"source": "math-competition",
                          "source_id": f"math-{i}", "source_split": "test",
                          "license": "MIT", "synthetic": False,
                          "subject_raw": subject, "category": cat,
                          "answer_type": "numeric", "question": row["problem"],
                          "expected_answer": answer})
            loader_name = "hendrycks/competition_math (script)"
        except Exception as exc2:
            return q, {"source": "math-competition",
                       "status": f"FAILED: {type(exc1).__name__} / {type(exc2).__name__}"}
    return q, {"source": "math-competition", "status": "OK",
               "loader": loader_name, "rows": len(q)}


def sample_questions(questions: list[dict], seed: int = 42) -> list[dict]:
    """Deterministic sampling honoring SAMPLE_PLAN and MATH subject coverage."""
    rng = random.Random(seed)
    picked: list[dict] = []

    gsm = [q for q in questions if q["source"] == "gsm8k"]
    picked += rng.sample(gsm, min(SAMPLE_PLAN["gsm8k"], len(gsm)))

    math = [q for q in questions if q["source"] == "math-competition"]
    by_subject: dict[str, list[dict]] = {}
    for q in math:
        by_subject.setdefault(q["subject_raw"], []).append(q)
    math_pick: list[dict] = []
    for subj in sorted(by_subject):
        math_pick += rng.sample(by_subject[subj],
                                min(MATH_PER_SUBJECT, len(by_subject[subj])))
    if len(math_pick) > MATH_MAX_TOTAL:
        math_pick = rng.sample(math_pick, MATH_MAX_TOTAL)
    picked += math_pick

    for src in ("ai2-arc", "sciq"):
        pool = [q for q in questions if q["source"] == src]
        picked += rng.sample(pool, min(SAMPLE_PLAN[src], len(pool)))

    picked += [q for q in questions if q["source"] == "synthetic-v1"]
    return picked


def assign_ids(questions: list[dict]) -> list[dict]:
    for q in questions:
        payload = f"{q['source']}|{q['source_id']}|{q['question']}"
        q["eval_id"] = "ev1-" + hashlib.sha1(
            payload.encode("utf-8")).hexdigest()[:12]
    questions.sort(key=lambda q: q["eval_id"])
    return questions


def leakage_gate(picked: list[dict]) -> dict:
    """T2 ENTRY GATE: contamination of candidate eval questions against ALL
    current training data (direct = hard fail, near = reported)."""
    train: list[dict] = []
    for split in ("train", "validation"):
        for p in sorted((REPO_ROOT / "data" / split).glob("*.jsonl")):
            train.extend(read_jsonl(p))

    eval_sets = {"suite-v1": picked}
    if not train:
        result = {"passed": True,
                  "note": "no training data ingested yet (data/train and "
                          "data/validation empty); leakage check trivially "
                          "passes and MUST be re-run for any future suite "
                          "version or any new training ingestion",
                  "direct_leakage": [], "near_leakage": [],
                  "source_overlap": {}, "train_records_checked": 0}
        return result

    direct = find_direct_leakage(train, eval_sets)
    near = find_near_leakage(train, eval_sets, threshold=0.90)
    sources_train = sorted({r.get("source", "?") for r in train})
    result = {"passed": not direct.has_direct,
              "direct_leakage": [p.to_dict() for p in direct.direct],
              "near_leakage": [(p.to_dict()) for p in near.near],
              "near_threshold": 0.90,
              "train_records_checked": len(train),
              "train_sources": sources_train}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true",
                        help="overwrite an already-frozen suite (normal "
                             "workflow rejects this; frozen suites are "
                             "immutable and corrections need a new version)")
    args = parser.parse_args()

    log = setup_logging("build_eval_suite")

    ckpt = SUITE_DIR / "checksum.json"
    if ckpt.exists() and not args.rebuild:
        existing = json.loads(ckpt.read_text(encoding="utf-8"))
        print(f"REFUSED: {SUITE_VERSION} already frozen at "
              f"{existing.get('frozen_at')}. Frozen suites are immutable; "
              f"corrections require a new suite version (sciencemath-eval-v2). "
              f"Pass --rebuild only to deliberately re-create v1 during "
              f"development.")
        return 7

    questions, load_log = load_sources()
    log.info("load_log: %s", load_log)

    # dedup on normalized question text across sources
    seen: set[str] = set()
    unique: list[dict] = []
    for q in questions:
        fp = text_fingerprint(q["question"])
        if fp and fp in seen:
            continue
        seen.add(fp)
        unique.append(q)

    picked = sample_questions(unique, seed=42)
    assign_ids(picked)

    gate = leakage_gate(picked)
    if not gate["passed"]:
        SUITE_DIR.mkdir(parents=True, exist_ok=True)
        write_json(SUITE_DIR / "leakage_check.json", gate)
        print("T2 ENTRY GATE FAILED: direct train/eval leakage detected. "
              f"Details: {SUITE_DIR / 'leakage_check.json'}")
        return 6

    SUITE_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(SUITE_DIR / "questions.jsonl", picked)
    write_json(SUITE_DIR / "leakage_check.json", gate)

    counts = Counter(q["category"] for q in picked)
    synthetic_cats = {q["category"] for q in picked if q.get("synthetic")}
    category_manifest: dict = {}
    for cat in ALL_CATEGORIES:
        n = counts.get(cat, 0)
        entry: dict = {"count": n, "synthetic": cat in synthetic_cats}
        if n == 0:
            entry["status"] = "INSUFFICIENT_VERIFIED_EVAL_DATA"
            entry["note"] = EMPTY_CATEGORY_NOTES.get(cat,
                            "no verified evaluation source for this category")
        category_manifest[cat] = entry
    write_json(SUITE_DIR / "category_manifest.json", category_manifest)

    src_counts = Counter(q["source"] for q in picked)
    write_json(SUITE_DIR / "source_manifest.json", {
        "sample_sizes": {**SAMPLE_PLAN, "math-competition": {
            "per_subject": MATH_PER_SUBJECT, "max_total": MATH_MAX_TOTAL}},
        "counts": dict(src_counts),
        "synthetic_isolation": {
            "allowed_categories": ["instruction_following",
                                   "uncertainty_calibration"],
            "policy": "synthetic items carry synthetic=true and "
                      "source=synthetic-v1 and are used only for the two "
                      "categories no verified benchmark covers",
        },
        "load_log": load_log,
        "license_verification": "data/manifests/datasets.json + "
                                "data/licenses/LICENSE_MANIFEST.md "
                                "(verified 2026-08-31)",
        "eval_only_sources": ["ai2-arc"],
    })

    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "version": SUITE_VERSION,
        "frozen_at": now,
        "seed": 42,
        "n_questions": len(picked),
        "categories": {c: e["count"] for c, e in category_manifest.items()},
        "sources": dict(src_counts),
        "leakage_gate": "PASS" if gate["passed"] else "FAIL",
        "scoring": "deterministic only (exact_choice_match, numeric_exact_match "
                   "with tolerance, normalized_text_match, uncertainty signal "
                   "detection); no LLM judging",
        "immutability": "frozen; corrections require sciencemath-eval-v2",
    }
    write_json(SUITE_DIR / "manifest.json", manifest)

    # checksum.json last: hashes every other file in the frozen directory
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(SUITE_DIR.iterdir()) if p.is_file()}
    write_json(SUITE_DIR / "checksum.json", {
        "suite_version": SUITE_VERSION,
        "frozen_at": now,
        "files": files,
        "immutable": True,
        "verify": "recompute sha256 of each listed file; any mismatch means "
                  "the suite was tampered with and no baseline is valid",
    })

    print(f"FROZEN {SUITE_VERSION}: {len(picked)} questions, "
          f"categories={dict(counts)}, leakage_gate=PASS")
    print(f"  suite dir: {SUITE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())