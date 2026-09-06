"""Build one curriculum stage corpus (mango-sft-v2, T6.4-T6.9).

Assembles the training corpus for a single curriculum level:

  1. per-track allocation of the level's target examples
  2. deterministic generator records (math/quantitative) — verified by the
     T4 verifier parse gate and cross-checked against the tool layer
  3. agent-authored records for tracks without generators (science) —
     grounding-checked against the approved retrieval corpus (T6.6: a
     scientific example is accepted only if its supporting quote exists in
     the corpus; synthetic scientific facts are never accepted on the word
     of an LLM alone)
  4. replay buffer from earlier stages + frozen sciencemath-sft-v1
     (T6.9) at the level's declared fraction
  5. contamination check against the frozen eval suites (T6.2: the core
     suite stays outside training)
  6. token-mixture measurement (T6.8) with the actual Qwen tokenizer
  7. deterministic train/validation split, then freeze with checksums

Usage:
  python scripts/build_curriculum_stage.py --level 1 \
      [--authored-dir training/curriculum/authored/level1] \
      [--out-dir training/curriculum/mango-sft-v2/level1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.capabilities import (  # noqa: E402
    FAMILIES, family_of, track_spec,
)
from sciencemath.curriculum.levels import LEVELS, validate_level_def  # noqa: E402
from sciencemath.curriculum.generators import (  # noqa: E402
    generate_stage_examples, verified_records, cross_check_with_tools,
    mark_verified,
)
from sciencemath.curriculum.replay import select_replay  # noqa: E402
from sciencemath.curriculum.eval_core import contamination_check  # noqa: E402

CORPUS_VERSION = "mango-sft-v2"
V1_DIR = REPO / "training" / "datasets" / "sciencemath-sft-v1"
RAG_CORPUS = REPO / "rag" / "corpus" / "wikipedia_en.jsonl"

SCIENCE_FAMILIES = ("physics", "chemistry", "biology", "earth_space",
                    "scientific_reasoning")

# frozen v1 uses "general_science" as its domain for sciq records
DOMAIN_ALIASES = {"general_science": "sciences"}

AUTHORED_REQUIRED = ("question", "answer", "target_response",
                     "verification_state", "capability_track",
                     "curriculum_level", "difficulty", "license", "source")
AUTHORED_VERIFICATION_OK = ("PASS", "REVIEWED")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _macro_of(family: str) -> str:
    if family == "mathematics":
        return "mathematics"
    if family in SCIENCE_FAMILIES:
        return "sciences"
    if family == "cross_domain":
        return "cross_domain"
    return "general"


def allocate_tracks(level: int, n_new: int) -> dict[str, int]:
    """Even allocation across the level's tracks, remainder to the first
    tracks deterministically."""
    tracks = LEVELS[level]["tracks"]
    base, rem = divmod(n_new, len(tracks))
    return {t: base + (1 if i < rem else 0)
            for i, t in enumerate(tracks)}


def load_authored(directory: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """Load agent-authored records grouped by capability_track."""
    by_track: dict[str, list[dict]] = defaultdict(list)
    problems: list[str] = []
    if not directory.exists():
        return by_track, problems
    for path in sorted(directory.glob("*.jsonl")):
        for i, line in enumerate(path.read_text(encoding="utf-8")
                                 .splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{path.name}:{i}: bad json ({exc})")
                continue
            missing = [f for f in AUTHORED_REQUIRED if f not in rec]
            if missing and rec.get("required_capability") is not None:
                missing = [f for f in missing if f != "capability_track"]
            if missing:
                problems.append(f"{path.name}:{i}: missing {missing}")
                continue
            rec.setdefault(
                "capability_track",
                rec.get("required_capability"))
            if rec["verification_state"] not in AUTHORED_VERIFICATION_OK:
                problems.append(f"{path.name}:{i}: verification_state "
                                f"{rec['verification_state']!r} not "
                                f"{AUTHORED_VERIFICATION_OK} — excluded")
                continue
            by_track.setdefault(rec["capability_track"], []).append(rec)
    return by_track, problems


def load_rag_corpus_titles() -> dict[str, str]:
    """title -> normalized page text (all chunks concatenated), from the
    approved retrieval corpus."""
    titles: dict[str, str] = {}
    with open(RAG_CORPUS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            title = row.get("title", "")
            titles[title] = titles.get(title, "") + " " \
                + _norm(row.get("text", ""))
    return titles


def grounding_check(records: list[dict], corpus: dict[str, str]) -> tuple[
        list[dict], list[str]]:
    """T6.6: every authored science record must cite a corpus title whose
    normalized text contains the quoted supporting sentence."""
    kept, rejected = [], []
    for rec in records:
        prov = rec.get("provenance") or {}
        quote = _norm(prov.get("quote") or rec.get("supporting_quote") or "")
        title = prov.get("corpus_title") or rec.get("corpus_title") or ""
        page = corpus.get(title)
        if page is None:
            rejected.append(f"{rec['capability_track']}: title {title!r} "
                            "not in corpus")
            continue
        if not quote or quote not in page:
            rejected.append(f"{rec['capability_track']}: quote not found "
                            f"in {title!r}: {quote[:70]}...")
            continue
        kept.append(rec)
    return kept, rejected


def token_counts(records: list[dict], tokenizer) -> Counter:
    counts = Counter()
    for rec in records:
        fam = rec.get("family") or rec.get("domain") or "general"
        fam = DOMAIN_ALIASES.get(fam, fam)
        macro = _macro_of(fam if fam in FAMILIES else "general")
        ids = tokenizer(rec["question"] + rec.get("target_response", ""),
                        add_special_tokens=False)["input_ids"]
        counts[macro] += len(ids)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--authored-dir", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    level = args.level
    errors = validate_level_def(level)
    if errors:
        print("level definition errors:", errors)
        return 2
    ldef = LEVELS[level]
    out_dir = args.out_dir or (REPO / "training" / "curriculum"
                               / "mango-sft-v2" / f"level{level}")
    authored_dir = args.authored_dir or (REPO / "training" / "curriculum"
                                         / "authored" / f"level{level}")

    replay_fraction = ldef["replay_fraction"]
    target = ldef["target_examples"]
    n_replay = round(target * replay_fraction)
    n_new = target - n_replay
    allocation = allocate_tracks(level, n_new)

    # 1. generator records ------------------------------------------------
    gen_tracks = {t: n for t, n in allocation.items()
                  if track_spec(t) and t in GENERATOR_COVERAGE}
    records, gen_stats = generate_stage_examples(
        level=level, tracks=gen_tracks, seed=args.seed)
    records, vstats = verified_records(records)
    records, cstats = cross_check_with_tools(records)
    records = mark_verified(records)

    # 2. authored records -------------------------------------------------
    authored, load_problems = load_authored(authored_dir)
    authored_accepted, grounding_rejected = [], []
    rag_titles: dict[str, str] = {}
    for track, n in allocation.items():
        if track in gen_tracks or n == 0:
            continue
        pool = authored.get(track, [])
        if not pool:
            load_problems.append(f"{track}: needs {n} authored examples, "
                                 "0 available")
            continue
        if not rag_titles:
            rag_titles = load_rag_corpus_titles()
        grounded, rejected = grounding_check(pool, rag_titles)
        grounding_rejected.extend(rejected)
        taken = grounded[:n]
        if len(taken) < n:
            load_problems.append(f"{track}: grounded {len(grounded)} "
                                 f"< needed {n}")
        for rec in taken:
            rec.setdefault("family", family_of(track))
            rec.setdefault("domain", family_of(track))
            rec["required_capability"] = track
        records.extend(taken)

    # 3. replay -----------------------------------------------------------
    stage_questions = {rec["question"] for rec in records}
    v1_pool = [json.loads(l) for l in (V1_DIR / "train.jsonl")
               .read_text(encoding="utf-8").splitlines() if l.strip()]
    replay, replay_report = select_replay(
        v1_pool, fraction=replay_fraction, target_size=n_replay,
        seed=args.seed, exclude_questions=stage_questions)

    # 4. contamination against frozen eval suites (T6.2) ------------------
    reference = []
    for suite in ("evaluations/eval-core/v1/questions.jsonl",
                  "evaluations/suite/v1/questions.jsonl"):
        p = REPO / suite
        if p.exists():
            reference.extend(json.loads(l)["question"]
                             for l in p.read_text(encoding="utf-8")
                             .splitlines() if l.strip())
    flagged = contamination_check(records + replay, reference)

    # 5. token mixture (T6.8) ---------------------------------------------
    tokenizer = _load_tokenizer()
    new_counts = token_counts(records, tokenizer)
    replay_counts = token_counts(replay, tokenizer)
    all_counts = new_counts + replay_counts
    total = sum(all_counts.values()) or 1
    mixture = {m: round(c / total, 4) for m, c in all_counts.items()}
    targets = ldef["macro_token_targets"]

    # 6. split ------------------------------------------------------------
    rng = random.Random(args.seed)
    by_track: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_track[rec["required_capability"]].append(rec)
    train, val = [], []
    for track in sorted(by_track):
        recs = sorted(by_track[track],
                      key=lambda r: _norm(r["question"]))
        rng.shuffle(recs)
        k = max(1, round(len(recs) * 0.05)) if len(recs) >= 10 else 0
        val.extend(recs[:k])
        train.extend(recs[k:])
    train.extend(replay)   # replay trains only, never in validation

    # 7. freeze ------------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    _dump(train, out_dir / "train.jsonl")
    _dump(val, out_dir / "validation.jsonl")
    _dump(replay, out_dir / "replay.jsonl")
    domain_dist = {
        "corpus": f"{CORPUS_VERSION}-level{level}",
        "by_macro_new": dict(Counter(_macro_of(r.get("family") or
                                                r.get("domain") or "general")
                                     for r in records)),
        "by_track_new": dict(Counter(r["required_capability"]
                                     for r in records)),
        "by_difficulty_new": dict(Counter(str(r["difficulty"])
                                          for r in records)),
        "by_source_new": dict(Counter(r["source"] for r in records)),
        "replay_count": len(replay),
    }
    (out_dir / "domain_distribution.json").write_text(
        json.dumps(domain_dist, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (out_dir / "contamination_report.json").write_text(json.dumps({
        "checked_against": ["mango-eval-core-v1", "sciencemath-eval-suite-v1"],
        "flagged": flagged,
        "ok": not flagged,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    token_mixture = {
        "measured_tokens": dict(all_counts),
        "mixture": mixture,
        "targets": targets,
        "deltas_pp": {m: round((mixture.get(m, 0.0) - targets.get(m, 0.0))
                               * 100, 1)
                      for m in set(mixture) | set(targets)},
    }
    (out_dir / "token_mixture.json").write_text(
        json.dumps(token_mixture, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (out_dir / "replay_report.json").write_text(
        json.dumps(replay_report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    license_counts = Counter(rec.get("license", "unknown")
                             for rec in train + val)
    (out_dir / "license_manifest.json").write_text(json.dumps(
        {"by_license": dict(license_counts),
         "note": "generated records are CC0-1.0; replay inherits frozen "
                 "sciencemath-sft-v1 licenses"}, indent=2) + "\n",
        encoding="utf-8")

    manifest = {
        "corpus": CORPUS_VERSION,
        "level": level,
        "level_name": ldef["name"],
        "curriculum_version": "1.0.0",
        "seed": args.seed,
        "immutable": True,
        "frozen_before_training": True,
        "target_examples": target,
        "counts": {"generated_new": len(records), "validation": len(val),
                   "train": len(train), "replay": len(replay)},
        "generation_stats": gen_stats,
        "verification": {"parse_gate": vstats, "tool_cross_check": cstats,
                         "grounding_rejected": grounding_rejected,
                         "authored_problems": load_problems},
        "replay_fraction": replay_fraction,
        "token_mixture": mixture,
        "contamination_ok": not flagged,
        "regression_gates_ref": "configs/curriculum.yaml (pre-declared)",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    checksums = {}
    for p in sorted(out_dir.glob("*")):
        if p.is_file() and p.name != "checksums.json":
            checksums[p.name] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    (out_dir / "checksums.json").write_text(
        json.dumps(checksums, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"out_dir": str(out_dir), "counts": manifest["counts"],
                      "token_mixture": mixture, "targets": targets,
                      "contamination_ok": not flagged,
                      "deficits": load_problems}, indent=2))
    if flagged or load_problems or cstats["dropped"]:
        print("STAGE BUILD INCOMPLETE — fix deficits above", file=sys.stderr)
        return 1
    return 0


def _dump(records: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for rec in sorted(records, key=lambda r: _norm(r["question"])):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained("Qwen/Qwen3-1.7B")


GENERATOR_COVERAGE = {
    "math_arithmetic", "math_fractions", "math_ratios", "math_percentages",
    "math_linear_equations", "math_scientific_notation", "sci_measurements",
    "phys_mechanics", "phys_energy_momentum", "chem_stoichiometry",
}


if __name__ == "__main__":
    raise SystemExit(main())