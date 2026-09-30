"""T32 Phase 7 infrastructure: carve the development sets FIRST.

Deterministic (seed 42), built from the contamination-gated fresh pool +
raw ARC/SciQ train splits. Every dev question fingerprint is recorded and
is EXCLUDED from every T32 training mixture (dev/train separation), on top
of the T30/T31 exclusions already applied to the pool.

Dev items mirror the frozen T31 benchmark construction exactly (same
benchmark tags drive the frozen scorer paths; same option ordering salt for
SciQ; canonical A-D labels for ARC), but the records are distinct from T31
evaluation membership (verified by fingerprint + the two leakage gates).
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")

from common import REPO_ROOT  # noqa: E402

from sciencemath.comparability.loaders import (  # noqa: E402
    _OPTION_LABELS,
    OPTION_ORDER_SALT,
)
from sciencemath.datasets.leakage import (  # noqa: E402
    find_direct_leakage as _fdl,
)
from sciencemath.datasets.leakage import find_near_leakage  # noqa: E402
from sciencemath.datasets.normalize import text_fingerprint  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_jsonl  # noqa: E402

ROOT = REPO_ROOT
POOLS = ROOT / "training/t32/pools"
DEV = ROOT / "training/t32/dev_sets"

N_GSM8K = 200
N_MATH = 200
N_SCIQ = 150
N_ARC_EASY = 120
N_ARC_CHALLENGE = 80

# benchmark tag used by the dev items -> drives the FROZEN scorer kind.
# dev_gsm8k items carry benchmark "gsm8k" (numeric kind), dev_math items
# "math500" (boxed math kind), etc. The tag is a scoring-path selector, not a
# membership claim: the manifest records the true provenance of each record.
DEVS = (
    ("dev_gsm8k", "gsm8k", N_GSM8K),
    ("dev_math", "math500", N_MATH),
    ("dev_sciq", "sciq", N_SCIQ),
    ("dev_arc_easy", "arc_easy", N_ARC_EASY),
    ("dev_arc_challenge", "arc_challenge", N_ARC_CHALLENGE),
)


def fp(text: str) -> str:
    return text_fingerprint(str(text))


def math_gold(record: dict) -> str | None:
    ans = str(record.get("answer") or "")
    # MATH train rows: boxed inside the solution/answer text
    i = ans.rfind("\\boxed{")
    if i != -1:
        depth, start = 0, i + len("\\boxed")
        for j in range(start, len(ans)):
            depth += {("{"): 1, ("}"): -1}.get(ans[j], 0)
            if depth == 0:
                return ans[start + 1:j].strip()
    return None


def main() -> int:
    rng = random.Random(42)
    pool = read_jsonl(POOLS / "fresh_pool_clean.jsonl")

    t31_eval: set[str] = set()
    for arm in ("base", "adapter"):
        for b in ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq"):
            for r in read_jsonl(ROOT / f"evaluations/t31/scored/{arm}/{b}.jsonl"):
                t31_eval.add(fp(r["question"]))
    t30_used: set[str] = set()
    for fname in ("train.jsonl", "validation.jsonl"):
        for rec in read_jsonl(ROOT / f"training/datasets/sciencemath-sft-v1/{fname}"):
            t30_used.add(fp(rec["question"]))

    # ---- 1. dev from the clean pool (already T30/T31-excluded) ----
    by_source: dict[str, list[dict]] = defaultdict(list)
    for rec in pool:
        by_source[rec["source"]].append(rec)

    picked: dict[str, list[dict]] = {}
    # gsm8k: shuffled head of 200
    g = sorted(by_source["gsm8k"], key=lambda r: r["id"])
    rng.shuffle(g)
    picked["dev_gsm8k"] = g[:N_GSM8K]
    # MATH: subject-stratified proportional carve of 200
    m = sorted(by_source["math-competition"], key=lambda r: r["id"])
    rng.shuffle(m)
    subj_counts = Counter(r["subject"] for r in m)
    quotas: dict[str, int] = {}
    remaining = N_MATH
    subjects = sorted(subj_counts, key=lambda s: (-subj_counts[s], s))
    for i, s in enumerate(subjects):
        take = round(N_MATH * subj_counts[s] / len(m)) if i < len(subjects) - 1 else remaining
        take = min(take, remaining)
        quotas[s] = take
        remaining -= take
    dev_math: list[dict] = []
    for s in subjects:
        if not quotas.get(s):
            continue
        pool_s = [r for r in m if r["subject"] == s and r["id"] not in
                  {x["id"] for x in dev_math}]
        dev_math.extend(pool_s[: quotas[s]])
    picked["dev_math"] = dev_math
    # sciq free-pool records unused (sciq dev comes from raw train below so
    # the frozen MC option construction (distractors) can be mirrored).

    used_ids = {r["id"] for rs in picked.values() for r in rs}

    # ---- 2. raw sciq train with distractors; gate vs T31/T30 ----
    from datasets import load_dataset

    rows = [dict(r) for r in load_dataset("allenai/sciq", split="train")]
    t31_sciq_rows = read_jsonl(ROOT / "evaluations/t31/scored/base/sciq.jsonl")
    # direct: fingerprint matches (same gate the pool build used)
    t31_sciq_fp = {fp(r["question"]) for r in t31_sciq_rows}
    # near: the 0.90 Jaccard gate, train ids = the probe ids below
    probe = [{"id": f"sciq-train-{i}", "question": r["question"]}
             for i, r in enumerate(rows)]
    near = find_near_leakage(probe, {"t31_sciq": t31_sciq_rows}, threshold=0.90)
    near_ids = {p.train_id for p in near.pairs}
    sciq_direct_drop = sciq_near_drop = 0
    clean_rows, seen = [], set()
    for i, r in enumerate(rows):
        f = fp(r["question"])
        if f in t31_eval or f in t31_sciq_fp or f in t30_used:
            sciq_direct_drop += 1
            continue
        if f"sciq-train-{i}" in near_ids:
            sciq_near_drop += 1
            continue
        if f in seen:
            continue
        seen.add(f)
        clean_rows.append(r)
    print(f"sciq train: {len(rows)} raw -> {len(clean_rows)} clean "
          f"(direct {sciq_direct_drop}, near {sciq_near_drop})", flush=True)
    g = sorted(clean_rows, key=lambda r: str(r["question"]))
    rng.shuffle(g)
    picked["dev_sciq"] = g[:N_SCIQ]

    # ---- 3. ARC train (measurement-only source): gate vs T31 ARC eval ----
    for dev_name, cfg, bench, n in (
            ("dev_arc_easy", "ARC-Easy", "arc_easy", N_ARC_EASY),
            ("dev_arc_challenge", "ARC-Challenge", "arc_challenge",
             N_ARC_CHALLENGE)):
        ds = load_dataset("allenai/ai2_arc", cfg, split="train")
        rows = [dict(r) for r in ds]
        t31_arc = read_jsonl(
            ROOT / f"evaluations/t31/scored/base/{bench}.jsonl")
        t31_arc_items = [{"id": x["item_id"], "question": x["question"]}
                         for x in t31_arc]
        probe = [{"id": f"arc-train-{i}", "question": r["question"]}
                 for i, r in enumerate(rows)]
        direct = _fdl(probe, {"t31": t31_arc_items})
        direct_ids = {p.train_id for p in direct.pairs}
        near = find_near_leakage(probe, {"t31": t31_arc_items}, threshold=0.90)
        near_ids = {p.train_id for p in near.pairs}
        keep = []
        seen = set()
        for i, r in enumerate(rows):
            tag = f"arc-train-{i}"
            f = fp(r["question"])
            if tag in direct_ids or tag in near_ids or f in t31_eval or f in seen:
                continue
            if not str(r.get("answerKey") or "").strip():
                continue
            seen.add(f)
            keep.append(r)
        print(f"{cfg} train: {len(rows)} raw -> {len(keep)} gated", flush=True)
        # ARC's own id is the anchor for provenance only (ids stay t32dev-*)
        g = sorted(keep, key=lambda r: str(r["id"]))
        rng.shuffle(g)
        picked[dev_name] = g[:n]

    # ---- 4. render dev items in the frozen item form ----
    DEV.mkdir(parents=True, exist_ok=True)
    all_dev_fps: set[str] = set()
    manifest_files = {}
    for dev_name, bench, _n in DEVS:
        items = []
        for r in picked[dev_name]:
            if dev_name == "dev_gsm8k":
                q = str(r["question"]).strip()
                ans = str(r["answer"])
                gold = ans.rpartition("####")[2].strip().replace(",", "")
                items.append({"item_id": f"t32dev-{bench}-" + hashlib.sha1(
                    fp(q).encode()).hexdigest()[:16], "benchmark": bench,
                    "split": "t32dev", "native_id": None, "question": q,
                    "choices": [], "gold": gold, "gold_label": None,
                    "subject": r.get("subject"), "level": r.get("level"),
                    "provenance": {"source": r["source"], "source_id": r["source_id"],
                                   "pool_record_id": r["id"]}})
            elif dev_name == "dev_math":
                q = str(r["question"]).strip()
                gold = math_gold(r)
                if gold is None:
                    continue
                items.append({"item_id": f"t32dev-{bench}-" + hashlib.sha1(
                    fp(q).encode()).hexdigest()[:16], "benchmark": bench,
                    "split": "t32dev", "native_id": None, "question": q,
                    "choices": [], "gold": gold, "gold_label": None,
                    "subject": r.get("subject"), "level": r.get("difficulty"),
                    "provenance": {"source": r["source"], "source_id": r["source_id"],
                                   "pool_record_id": r["id"]}})
            elif dev_name == "dev_sciq":
                q = str(r["question"]).strip()
                item_id = "t32dev-sciq-" + hashlib.sha1(fp(q).encode()).hexdigest()[:16]
                raw_opts = [str(r["correct_answer"]).strip(),
                            str(r["distractor1"]).strip(),
                            str(r["distractor2"]).strip(),
                            str(r["distractor3"]).strip()]
                order = sorted(range(4), key=lambda i: hashlib.sha256(
                    f"{OPTION_ORDER_SALT}|{item_id}|{i}".encode()).hexdigest())
                choices = [(_OPTION_LABELS[pos], raw_opts[src])
                           for pos, src in enumerate(order)]
                gold_label = _OPTION_LABELS[order.index(0)]
                items.append({"item_id": item_id, "benchmark": bench,
                              "split": "t32dev", "native_id": None,
                              "question": q, "choices": choices,
                              "gold": gold_label, "gold_label": gold_label,
                              "subject": None, "level": None,
                              "provenance": {"source": "allenai/sciq train",
                                             "id": r.get("id"),
                                             "correct_answer_text": raw_opts[0]}})
            else:
                labels = [str(x).strip() for x in r["choices"]["label"]]
                texts = [str(x).strip() for x in r["choices"]["text"]]
                depth = min(len(labels), len(texts))
                q = str(r["question"]).strip()
                if len(set(labels)) != depth or not 2 <= depth <= 5:
                    continue
                gold_pos = next(
                    (i for i in range(depth) if labels[i] == str(r["answerKey"]).strip()),
                    None)
                if gold_pos is None:
                    continue
                gold_label = _OPTION_LABELS[gold_pos]
                choices = [(_OPTION_LABELS[i], texts[i]) for i in range(depth)]
                items.append({"item_id": f"t32dev-{bench}-" + hashlib.sha1(
                    (str(r.get("id")) or fp(q)).encode()).hexdigest()[:16],
                    "benchmark": bench,
                    "split": "t32dev", "native_id": r.get("id"),
                    "question": q, "choices": choices,
                    "gold": gold_label, "gold_label": gold_label,
                    "subject": None, "level": None,
                    "provenance": {"source": "allenai/ai2_arc train",
                                   "id": r.get("id"),
                                   "answerKey_original": str(r["answerKey"]).strip()}})
            all_dev_fps.add(fp(items[-1]["question"]))
        out = DEV / f"{dev_name}.jsonl"
        write_jsonl(out, items)
        manifest_files[dev_name] = {
            "path": out.as_posix(), "n": len(items),
            "benchmark_tag": bench,
            "sha256": hashlib.sha256(
                (out.read_bytes())).hexdigest()}
        print(dev_name, len(items), flush=True)

    # ---- 5. manifest + dev exclusion fingerprints ----
    fp_file = DEV / "dev_excluded_fingerprints.json"
    fp_file.write_text(json.dumps(sorted(all_dev_fps)), encoding="utf-8",
                       newline="\n")
    manifest = {
        "artifact": "T32_DEV_SETS",
        "schema_version": "t32-mixture-v1",
        "carve_order": "dev sets carved FIRST; every dev question fingerprint is "
                       "excluded from every T32 training mixture",
        "seed": 42,
        "sources": {
            "dev_gsm8k": "fresh gsm8k train records from the T32 clean pool",
            "dev_math": "fresh MATH train records from the T32 clean pool "
                        "(subject-stratified)",
            "dev_sciq": "raw sciq train rows (distractors required for the "
                        "frozen MC option construction), fingerprint-gated "
                        "vs T31 eval and the T30 corpus",
            "dev_arc_easy": "ai2_arc ARC-Easy TRAIN rows (eval_only license: "
                            "measurement only, never training), "
                            "fingerprint-gated vs T31 arc_easy eval",
            "dev_arc_challenge": "ai2_arc ARC-Challenge TRAIN rows (same terms)",
        },
        "benchmark_tags": ("dev items reuse the frozen benchmark tags (gsm8k/"
                           "math500/arc_easy/arc_challenge/sciq) so the frozen "
                           "scorer paths apply; tags are scoring-path selectors, "
                           "not T31 membership claims"),
        "files": manifest_files,
        "excluded_fingerprints_file": fp_file.as_posix(),
        "excluded_fingerprints_n": len(all_dev_fps),
    }
    (DEV / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("dev fingerprints excluded from mixtures:", len(all_dev_fps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())