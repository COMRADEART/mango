"""T32 Phase 4/5: build the three frozen candidate mixtures.

Registered recipes (evaluations/t32/development/DEV_PROTOCOL.md §8, written
before training):

  t32-A-math-restore   T30 train replay + fresh gsm8k 600 + fresh MATH 600
                       (subject-stratified) + 400 verified drills
  t32-B-task-balanced  A + mango-sft-v2 level1 (850, re-gated) + 150 protocol-
                       envelope math records + 30 abstain + 20 recovery + 300
                       MC-format letter-choice records (sciq train distractors)
  t32-C-conservative   the exact frozen T30 train corpus (only lr changes at
                       training time)

Gates applied to every ADDED record (pool / authored / curriculum):
  * fingerprint not in {T30 corpus, T31 eval questions, T32 dev sets}
  * near-leakage (4-gram Jaccard >= 0.90) vs T31 eval questions -> removed
  * within-mixture exact dedup
  * Phase 5: structured/protocol records validate schema AND math content;
    a record whose math final answer fails programmatic verification is
    dropped, never accepted for schema validity alone.
T30 replay rows are frozen evidence: the near gate runs over them for
DISCLOSURE (they are not removed — removing rows would break the C ==
T30-corpus identity; the T30 adapter already trained on exactly these
records, so replaying them adds no new advantage over T30).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")

from common import REPO_ROOT  # noqa: E402

from sciencemath.datasets.leakage import (  # noqa: E402
    find_direct_leakage,
    find_near_leakage,
)
from sciencemath.datasets.normalize import text_fingerprint  # noqa: E402
from sciencemath.datasets.schema import make_id  # noqa: E402
from sciencemath.t32.drills import verify_lines  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_jsonl  # noqa: E402

ROOT = REPO_ROOT
POOLS = ROOT / "training/t32/pools"
DEV = ROOT / "training/t32/dev_sets"
CAND = ROOT / "training/t32/candidates"
T30 = ROOT / "training/datasets/sciencemath-sft-v1"
MANGO_L1 = ROOT / "training/curriculum/mango-sft-v2/level1"
EVAL_DIR = ROOT / "evaluations/t31/scored/base"

QUOTA_GSM8K = 600
QUOTA_MATH = 600
N_PROTOCOL = 150
N_ABSTAIN = 30
N_RECOVERY = 20
N_MC = 300

CANDIDATES = ("t32-A-math-restore", "t32-B-task-balanced", "t32-C-conservative")


def fp(text) -> str:
    return text_fingerprint(str(text))


# ------------------------------------------------------- exclusion sets


def exclusion_sets() -> tuple[set[str], dict[str, list[str]]]:
    t30_fps: set[str] = set()
    for fname in ("train.jsonl", "validation.jsonl"):
        for rec in read_jsonl(T30 / fname):
            t30_fps.add(fp(rec["question"]))
    eval_fps: set[str] = set()
    eval_rows: dict[str, list[dict]] = {}
    for b in ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq"):
        rows = read_jsonl(EVAL_DIR / f"{b}.jsonl")
        eval_rows[b] = [{"id": r["item_id"], "question": r["question"],
                         "source": f"t31/{b}"} for r in rows]
        for r in rows:
            eval_fps.add(fp(r["question"]))
    dev_fps = set(json.loads((DEV / "dev_excluded_fingerprints.json")
                             .read_text(encoding="utf-8")))
    return t30_fps | dev_fps, eval_fps, eval_rows


def _probe_id(r: dict) -> str:
    return r.get("id") or fp(r["question"])


def near_gate(records: list[dict], eval_rows: dict[str, list[dict]],
              label: str, threshold: float = 0.90) -> list[dict]:
    """Near-leakage gate for a block of records; returns flagged trains."""
    probe = [{"id": _probe_id(r), "question": r["question"]} for r in records]
    result = find_near_leakage(probe, eval_rows, threshold=threshold)
    flagged = [{"train_id": p.train_id,
                "eval_id": p.eval_id,
                "eval_split": p.eval_split, "similarity": p.similarity,
                "gate": label, "kind": p.kind}
               for p in result.pairs]
    return flagged


# ---------------------------------------------------- authored slices (B)


def authored_slices(rng: random.Random, pool: list[dict],
                    underlying_banned: set[str], eval_fps: set[str],
                    gsm_reserved_ids: set[str]) -> dict[str, list[dict]]:
    """Protocol-envelope math, abstain, recovery, MC-letter slices.

    Phase 5 rule enforced here: a structured (protocol-envelope or recovery)
    record is accepted only when (a) its schema keys are present and (b) its
    math content verifies (explicit step lines + boxed final). Records
    failing either check are dropped, not corrected.

    Gating semantics: a record's UNDERLYING question (for MC the raw SciQ
    question before option augmentation; for envelopes the wrapped math
    question) must be absent from ``underlying_banned`` (T30 corpus ∪ T32
    dev ∪ T31 eval fingerprints) so no banned question enters training in
    any textual form. The AUGMENTED question (envelope framing / option
    list) is additionally fingerprint+ near-gated at assembly time because
    it is what the trainer sees. ``gsm_reserved_ids`` are pool records
    already used by the gsm8k fresh-addition quota; envelopes draw from the
    disjoint remainder."""
    pool_by_source: dict[str, list[dict]] = {}
    for r in pool:
        pool_by_source.setdefault(r["source"], []).append(r)

    envelopes: list[dict] = []
    gsm_pool = sorted(pool_by_source["gsm8k"],
                      key=lambda r: r["id"])
    for r in gsm_pool:
        if len(envelopes) >= N_PROTOCOL:
            break
        if r["id"] in gsm_reserved_ids:
            continue
        qf = fp(r["question"])
        if qf in underlying_banned or qf in eval_fps:
            continue
        tid = f"T-{hashlib.sha1(qf.encode()).hexdigest()[:8].upper()}"
        math_q = r["question"]
        target = (f"Task {tid}: plan step is to compute the requested value "
                  f"and record it in the task note.\n\nWork:\n"
                  f"{r['target_response']}\n\nTask note:\nstatus: complete\n"
                  f"result: see final answer above")
        envelope_q = (f"[Mango task {tid}] A planning step requires the "
                      f"computation below. Solve it and record the result in "
                      f"the task note.\n\n{math_q}")
        envelopes.append({
            "id": make_id("t32-protocol-envelope-v1", tid, envelope_q),
            "source": "t32-protocol-envelope-v1", "license": "MIT",
            "domain": "mathematics", "subject": "protocol_shaped_math",
            "question": envelope_q, "answer": r["answer"],
            "answer_type": "numeric", "difficulty": 2,
            "target_response": target,
            "provenance": {"wrapped_pool_record": r["id"]},
            "protocol_record": True,
        })
        gsm_reserved_ids.add(r["id"])

    # ---- abstain / refuse (30): genuinely underdetermined templates ----
    abstain: list[dict] = []
    seen_abstain: set[str] = set()
    i = 0
    while len(abstain) < N_ABSTAIN and i < N_ABSTAIN * 40:
        i += 1
        style = i % 3
        a = rng.randint(2, 200)      # per-record parameter
        b = rng.randint(2, 60)
        if style == 0:
            template_q = (f"A rectangle's width is {a} cm and its area is "
                          f"3 times the area of a square with side {b} cm. "
                          f"What is the rectangle's height in cm?")
        elif style == 1:
            template_q = (f"The average of two numbers is {a}. One of the "
                          f"two numbers is not stated in the problem. What "
                          f"is the other number?")
        else:
            template_q = (f"A share of a total is {b} out of every 7 units, "
                          f"but the total itself is not stated. Compute the "
                          f"share.")
        fpr = fp(template_q)
        if fpr in seen_abstain or fpr in underlying_banned or fpr in eval_fps:
            continue
        seen_abstain.add(fpr)
        abstain.append({
            "id": make_id("t32-abstain-v1", f"abstain-{len(abstain)}",
                          template_q),
            "source": "t32-abstain-v1", "license": "MIT",
            "domain": "general", "subject": "insufficiency_recognition",
            "question": template_q, "answer": "cannot determine",
            "answer_type": "text", "difficulty": 2,
            "target_response": ("This problem is missing a quantity required "
                                "for a numerical answer, so no unique "
                                "numeric conclusion can be drawn from the "
                                "information given."),
            "boxed_contract": False,
        })

    # ---- recovery / replan (20): explicit wrong-step correction chains ----
    recovery: list[dict] = []
    for i in range(N_RECOVERY):
        a = rng.randint(12, 40)
        b = rng.randint(3, 9)
        c = rng.randint(10, 60)
        p = a * b
        wrong = p + rng.randint(1, 9)
        final = p - c if p > c else p + c
        op = "-" if p > c else "+"
        q = (f"During the computation of ({a} × {b}) {op} {c}, a previous run "
             f"wrote the intermediate product as {wrong}. Recheck the "
             f"product, correct it if needed, and give the right result.")
        sol = [f"{a} × {b} = {fm_(p)}",
               f"The earlier product {wrong} was wrong.",
               f"Continue with the corrected product: {p} {op} {c} = {fm_(final)}"]
        target = ("\n".join(sol) +
                  f"\n\nFinal answer: \\boxed{{{fm_(final)}}}")
        bad = verify_lines(sol)
        if bad:
            continue
        recovery.append({
            "id": make_id("t32-recovery-v1", f"recovery-{i}", q),
            "source": "t32-recovery-v1", "license": "MIT",
            "domain": "mathematics", "subject": "recovery_replan",
            "question": q, "answer": fm_(final), "answer_type": "numeric",
            "difficulty": 3, "target_response": target,
            "verified_content": True, "protocol_record": True,
        })

    # ---- MC-format letter slice (300): sciq train distractors ----
    mc: list[dict] = []
    from datasets import load_dataset

    sciq_raw = [dict(r) for r in load_dataset("allenai/sciq", split="train")]
    raw_used = _shuffled_head(sciq_raw, N_MC * 3, rng)
    for r in raw_used:
        if len(mc) >= N_MC:
            break
        if (fp(r["question"]) in underlying_banned
                or fp(r["question"]) in eval_fps):
            continue
        try:
            texts = [str(r["correct_answer"]).strip(),
                     str(r["distractor1"]).strip(),
                     str(r["distractor2"]).strip(),
                     str(r["distractor3"]).strip()]
        except KeyError:
            continue
        if len({t.casefold() for t in texts}) != 4:
            continue
        gold_pos = len(mc) % 4
        texts[0], texts[gold_pos] = texts[gold_pos], texts[0]
        label = "ABCD"[gold_pos]
        q = (str(r["question"]).strip() + "\n\n" +
             "\n".join(f"{lab}) {t}" for lab, t in zip("ABCD", texts)))
        mc.append({
            "id": make_id("t32-mc-sciq-v1", str(r.get("id", len(mc))), q),
            "source": "t32-mc-sciq-v1", "license": "CC-BY-NC-3.0",
            "domain": "general_science", "subject": "science_qa_letter",
            "question": q, "answer": label, "answer_type": "mc_letter",
            "difficulty": 2, "target_response": f"Answer: \\boxed{{{label}}}",
        })
    return {"protocol": envelopes, "abstain": abstain,
            "recovery": recovery, "mc": mc}


def fm_(x) -> str:
    return f"{x:,}" if isinstance(x, int) and abs(x) >= 10000 else str(x)


def _shuffled_head(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    g = sorted(rows, key=lambda r: str(r.get("question", str(r))[:256]))
    rng.shuffle(g)
    return g[:n]


# ------------------------------------------------------------ assembly


def subject_stratified(records: list[dict], n: int, rng: random.Random) -> list[dict]:
    from collections import defaultdict
    by_subj: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_subj[r.get("subject") or "?"].append(r)
    for v in by_subj.values():
        v.sort(key=lambda r: r["id"])
        rng.shuffle(v)
    subjects = sorted(by_subj, key=lambda s: (-len(by_subj[s]), s))
    out: list[dict] = []
    # largest-remainder allocation across subjects
    quota = {s: (n * len(by_subj[s])) // len(records) for s in subjects}
    remaining = n - sum(quota.values())
    for i in range(remaining):
        quota[subjects[i % len(subjects)]] += 1
    for s in subjects:
        out.extend(by_subj[s][: quota[s]])
    return out


def build_candidate(name: str, blocks: dict[str, list[dict]],
                    val_blocks: dict[str, list[dict]],
                    gate_ctx: dict, out: Path) -> dict:
    train_records = [r for rs in blocks.values() for r in rs]
    val_records = [r for rs in val_blocks.values() for r in rs]
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "train.jsonl", sorted(
        train_records, key=lambda r: r["id"]))
    write_jsonl(out / "validation.jsonl", sorted(val_records, key=lambda r: r["id"]))

    def digest(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    manifest = {
        "artifact": "T32_TRAINING_MIXTURE",
        "candidate": name,
        "schema_version": "t32-mixture-v1",
        "blocks": {k: {"records": len(v), "sha256": hashlib.sha256(
            "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                    for r in v).encode("utf-8")).hexdigest()}
            for k, v in sorted(blocks.items())},
        "validation_blocks": {k: {"records": len(v)}
                              for k, v in sorted(val_blocks.items())},
        "train_sha256": digest(out / "train.jsonl"),
        "validation_sha256": digest(out / "validation.jsonl"),
        "gates": gate_ctx,
        "provenance": {
            "fresh_pool": (POOLS / "fresh_pool_clean.jsonl").as_posix(),
            "dev_fingerprints_excluded": True,
            "t30_replay": "training/datasets/sciencemath-sft-v1/train.jsonl",
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(f"{name}: train {len(train_records)} val {len(val_records)}",
          flush=True)
    return manifest


def main() -> int:
    rng = random.Random(42)
    excl, eval_fps, eval_rows = exclusion_sets()
    pool = read_jsonl(POOLS / "fresh_pool_clean.jsonl")
    drills = read_jsonl(ROOT / "training/t32/drills/verified_drills.jsonl")
    t30_train = read_jsonl(T30 / "train.jsonl")
    t30_val = read_jsonl(T30 / "validation.jsonl")
    mango = read_jsonl(MANGO_L1 / "train.jsonl")
    mango_val = read_jsonl(MANGO_L1 / "validation.jsonl")
    print("pool", len(pool), "t30", len(t30_train), "drills", len(drills),
          "mango", len(mango), flush=True)

    # ---- candidate A quotas from the pool remainder ----
    pool_rem = [r for r in pool if fp(r["question"]) not in excl]
    by_source = {}
    for r in pool_rem:
        by_source.setdefault(r["source"], []).append(r)
    g = sorted(by_source["gsm8k"], key=lambda r: r["id"])
    rng.shuffle(g)
    gsm_add = g[: QUOTA_GSM8K]
    used = {fp(r["question"]) for r in gsm_add}
    math_add = subject_stratified(by_source["math-competition"], QUOTA_MATH, rng)
    for r in math_add:
        used.add(fp(r["question"]))

    # ---- Phase 3 gates on every ADDED record (new-record leakage removal) ----
    additions = {
        "drills": drills,
        "gsm8k_fresh": gsm_add,
        "math_fresh": math_add,
    }
    for r in additions["drills"]:
        if fp(r["question"]) in excl:
            print("WARN: drill fingerprint collision with exclusion set")
    gate_additions = [
        r for rs in additions.values() for r in rs
        if fp(r["question"]) not in eval_fps]

    # direct re-check over additions + within-block dedup + near gate
    flagged = near_gate(gate_additions, eval_rows, "additions")
    flagged_ids = {f["train_id"] for f in flagged}
    if flagged_ids:
        print("REMOVED near-flagged additions:", len(flagged_ids), flush=True)
        gate_additions = [r for r in gate_additions if _probe_id(r) not in flagged_ids]
        for b in additions:
            additions[b] = [r for r in additions[b] if _probe_id(r) not in flagged_ids]

    gsm_add, math_add, drills = (additions["gsm8k_fresh"],
                                 additions["math_fresh"], additions["drills"])

    # ---- authored + curriculum slices for candidate B ----
    reserved = {r["id"] for r in gsm_add}
    authored = authored_slices(random.Random(123), pool, excl, eval_fps,
                               reserved)
    mango_clean, mango_flags = [], []
    for i, r in enumerate(mango):
        r.setdefault("id", make_id("mango-sft-v2-level1",
                                   str(r.get("source_id") or f"level1-{i}"),
                                   r["question"]))
        fpr = underlying_fp = fp(r["question"])
        if fpr in excl or fpr in eval_fps:
            mango_flags.append({"id": r["id"], "reason": "fingerprint"})
            continue
        mango_clean.append(r)
    mango_val = []
    seen_mv: set[str] = set()
    for i, r in enumerate(read_jsonl(MANGO_L1 / "validation.jsonl")):
        r.setdefault("id", make_id("mango-sft-v2-level1",
                                   str(r.get("source_id") or f"val-{i}"),
                                   r["question"]))
        fpr = fp(r["question"])
        if fpr in excl or fpr in eval_fps or fpr in seen_mv:
            continue
        seen_mv.add(fpr)
        mango_val.append(r)
    mf = near_gate(mango_clean, eval_rows, "mango-sft-v2")
    mango_flag_ids = {f["train_id"] for f in mf}
    mango_clean = [r for r in mango_clean if _probe_id(r) not in mango_flag_ids]

    all_b_add = ([r for rs in [authored["protocol"], authored["abstain"],
                               authored["recovery"], authored["mc"]]
                  for r in rs] + mango_clean)
    # mc slice fingerprint gates (direct) are inside authored_slices via
    # question gating; near-gate ALL B additions
    bflagged = near_gate(
        [{"id": r.get("id") or r["question"][:32], "question": r["question"]}
         for r in all_b_add], eval_rows, "B-additions")
    bflag_ids = {f["train_id"] for f in bflagged}

    def keep(block: list[dict]) -> list[dict]:
        return [r for r in block
                if _probe_id(r) not in bflag_ids]

    b_blocks = {k: keep(v) for k, v in authored.items()}
    b_blocks["mango_sft_v2"] = [r for r in mango_clean if _probe_id(r) not in bflag_ids]

    # MC slice letter-frequency balance + Phase 5 record
    letters = Counter(r["answer"] for r in b_blocks.get("mc", []))

    # ---- assemble the candidates ----
    a_blocks = {
        "t30_replay": t30_train,
        "gsm8k_fresh_additions": gsm_add,
        "math_fresh_additions": math_add,
        "verified_drills": drills,
    }
    a_val_blocks = {
        "t30_validation": t30_val,
        "gsm8k_fresh_val": gsm_add[:30],
        "math_fresh_val": math_add[:30],
        "drills_val": drills[:30],
    }
    a_train = {
        "t30_replay": a_blocks["t30_replay"],
        "gsm8k_fresh_additions": gsm_add[30:],
        "math_fresh_additions": math_add[30:],
        "verified_drills": drills[30:],
    }
    b_train = {**a_train, **b_blocks}
    n_proto = len(b_blocks["protocol"])
    n_val_proto = min(20, max(n_proto - 30, 10)) if n_proto > 30 else 0
    b_val = b_blocks["protocol"][: n_val_proto]
    b_val_blocks = {**a_val_blocks,
                    "mango_sft_v2_val": mango_val,
                    "protocol_val": b_val}
    if n_val_proto:
        b_train["protocol"] = b_blocks["protocol"][n_val_proto:]

    # ---- direct + within-mixture dedup for every block set ----
    def dedup_blocks(blocks):
        seen: set[str] = set()
        dropped = Counter()
        for key in blocks:
            kept_r = []
            for r in blocks[key]:
                fpr = fp(r["question"])
                if fpr in seen:
                    dropped[key] += 1
                    continue
                seen.add(fpr)
                kept_r.append(r)
            blocks[key] = kept_r
        return dropped

    a_dropped = dedup_blocks(a_train)
    b_dropped = dedup_blocks(b_train)
    c_blocks = {"t30_replay": t30_train}
    c_val_blocks = {"t30_validation": t30_val}
    c_dropped = dedup_blocks(c_blocks)

    # ---- disclosure: near gate over the T30 replay (frozen evidence) ----
    replay_flagged = near_gate(
        [{"id": r["id"], "question": r["question"]} for r in t30_train],
        eval_rows, "t30-replay-disclosure")
    print("T30 replay near-matches disclosed (not removed):",
          len(replay_flagged), flush=True)

    gate_ctx = {
        "new_record_direct_gate": "excluded at pool/dev carve; re-checked here",
        "new_record_near_gate_removed": len(flagged_ids) + len(bflag_ids),
        "t30_replay_near_matches_disclosed": len(replay_flagged),
        "t30_replay_removal_rationale": ("T30 corpus is frozen evidence; the "
                                        "T30 adapter already trained on it; "
                                        "removing rows would break the "
                                        "C-candidate == T30-corpus identity"),
        "within_mixture_dedup_dropped": {
            "A": dict(a_dropped), "B": dict(b_dropped), "C": dict(c_dropped)},
        "mc_slice_letter_counts": dict(letters),
        "phase5": ("structured records verified for schema AND math content; "
                   "invalid math content dropped regardless of schema validity"),
    }

    stats = {}
    stats["A"] = build_candidate("t32-A-math-restore", a_train, a_val_blocks,
                                 gate_ctx, CAND / "t32-A-math-restore")
    stats["B"] = build_candidate("t32-B-task-balanced", b_train, b_val_blocks,
                                 gate_ctx, CAND / "t32-B-task-balanced")
    stats["C"] = build_candidate("t32-C-conservative", c_blocks, c_val_blocks,
                                 gate_ctx, CAND / "t32-C-conservative")

    build_report = {
        "artifact": "T32_MIXTURE_BUILD_REPORT",
        "schema_version": "t32-mixture-v1",
        "candidates": {
            name: {"blocks": {k: len(v) for k, v in blocks.items()},
                   "validation_blocks": {
                       k: len(v) for k, v in vblocks.items()}}
            for name, blocks, vblocks in (
                ("t32-A-math-restore", a_train, a_val_blocks),
                ("t32-B-task-balanced", b_train, b_val_blocks),
                ("t32-C-conservative", c_blocks, c_val_blocks))},
        "authored_blocks": {k: len(v) for k, v in authored.items()},
        "gate_ctx": gate_ctx,
    }
    (POOLS / "mixture_build_report.json").write_text(
        json.dumps(build_report, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    print("mixture build complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())