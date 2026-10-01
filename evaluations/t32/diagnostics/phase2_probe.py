"""T32 Phase 2 GPU probe: is the adapter's math failure a policy or a depth problem?

Read-only w.r.t. T31 evidence; writes only under evaluations/t32/diagnostics/.
This is a DIAGNOSTIC probe under clearly non-frozen prompts/budgets. It is not
the T31 methodology and never feeds the frozen comparison. Conditions:

  control_frozen   exact frozen user prompt, frozen max_new_tokens (gsm8k 512 / math500 1024)
  budget_1024      same frozen prompt, 1024-token budget (separates budget from policy on gsm8k)
  derive_explicit  same user prompt + an explicit ``show every calculation`` instruction
                   appended, 1024-token budget (separates verbosity policy from capability)

RESUMABLE: completed (item, condition) rows are appended to
probe_verbosity_rows.jsonl as each chunk finishes (flush per chunk), and a
rerun skips pairs already present, so an interrupted run loses at most one
chunk. Deterministic sampling and greedy decoding make resumed runs
identical by construction.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, "src")

from sciencemath.comparability import config as C
from sciencemath.comparability.contract import BENCHMARKS
from sciencemath.comparability.loaders import load_benchmark
from sciencemath.comparability.prompts import prompt_text, render_chat
from sciencemath.comparability.runner import generate_batch, load_arm, release_arm
from sciencemath.comparability.scoring import score_row

ROOT = Path(".")
T31 = ROOT / "evaluations/t31"
OUTDIR = ROOT / "evaluations/t32/diagnostics"

DERIVE_SUFFIX = ("\n\nSolve this step by step: write out every calculation "
                 "explicitly, one line at a time, before giving the final answer.")
CONDITIONS: tuple[str, ...] = ("control_frozen", "budget_1024", "derive_explicit")
FROZEN_BUDGET = {"gsm8k": 512, "math500": 1024}
SAMPLE_N = {"gsm8k": 60, "math500": 20}
ROWS_PATH = OUTDIR / "probe_verbosity_rows.jsonl"


def _load_done() -> tuple[set[tuple[str, str]], list[dict[str, Any]]]:
    done, rows = set(), []
    if ROWS_PATH.exists():
        with open(ROWS_PATH, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                rows.append(r)
                done.add((r["item_id"], r["condition"]))
    return done, rows


def _append_rows(items: list[dict[str, Any]], done_set: set,
                 all_rows: list[dict[str, Any]]) -> None:
    """Append and flush this chunk's rows immediately (kill-safe)."""
    new = [r for r in items if (r["item_id"], r["condition"]) not in done_set]
    if not new:
        return
    with open(ROWS_PATH, "a", encoding="utf-8", newline="\n") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in new:
        done_set.add((r["item_id"], r["condition"]))
        all_rows.append(r)


def main() -> int:
    t0 = time.time()

    def stamp(msg: str) -> None:
        print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)

    cfg = C.load_frozen(T31 / "config/t31_frozen_config.json")
    if cfg["config_sha256"] != ("2f86db2e577807ed8021a4b647f3fa2243762"
                                "e327d6e3c22c76184520e842eff"):
        raise SystemExit("frozen config hash does not match the recorded digest")
    del cfg

    scored: dict[tuple[str, str], dict[str, Any]] = {}
    for arm_name in ("base", "adapter"):
        for b in ("gsm8k", "math500"):
            with open(T31 / f"scored/{arm_name}/{b}.jsonl", encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    scored[(arm_name, r["item_id"])] = r

    done_set, all_rows = _load_done()
    stamp(f"resume check: {len(done_set)} (item, condition) rows already done")

    stamp("loading adapter arm (frozen T31 path)")
    runtime = load_arm("adapter")
    stamp("adapter arm loaded")

    out_items: list[dict[str, Any]] = list(all_rows)
    for b in ("gsm8k", "math500"):
        kind = BENCHMARKS[b]["kind"]
        items_all = {it.item_id: it for it in load_benchmark(b)}
        wrong_ids = sorted(
            iid for (a_name, iid), r in scored.items()
            if a_name == "adapter" and r["benchmark"] == b
            and r["content_valid"] is False
            and scored.get(("base", iid)).get("content_valid") is True)
        sampled = wrong_ids[: SAMPLE_N[b]]
        stamp(f"{b}: adapter-wrong/base-right available={len(wrong_ids)} sampled={len(sampled)}")

        budget = {"control_frozen": FROZEN_BUDGET[b], "budget_1024": 1024,
                  "derive_explicit": 1024}
        for start in range(0, len(sampled), 8):
            chunk = sampled[start:start + 8]
            todo = {c: [iid for iid in chunk if (iid, c) not in done_set]
                    for c in CONDITIONS}
            for c in CONDITIONS:
                if not todo[c]:
                    continue
                if c == "derive_explicit":
                    texts = [prompt_text(items_all[iid], kind) + DERIVE_SUFFIX
                             for iid in todo[c]]
                else:
                    texts = [prompt_text(items_all[iid], kind)
                             for iid in todo[c]]
                chats = [render_chat(runtime.tokenizer, t, enable_thinking=False)
                         for t in texts]
                gens, finish, _, out_toks, _ = generate_batch(
                    runtime, chats, max_new_tokens=budget[c])
                fresh = []
                for idx, iid in enumerate(todo[c]):
                    item = items_all[iid]
                    raw_row = {"arm": "adapter", "benchmark": b,
                               "raw_generation": gens[idx],
                               "finish_reason": finish[idx]}
                    scored_row = score_row(raw_row, item)
                    ok = bool(scored_row["content_valid"])
                    fresh.append({
                        "item_id": iid, "benchmark": b, "gold": item.gold,
                        "condition": c,
                        "correct": ok, "finish": finish[idx],
                        "output_tokens": out_toks[idx],
                        "extracted_answer": scored_row.get("extracted_answer"),
                        "generation": gens[idx]})
                _append_rows(fresh, done_set, out_items)
                done_n = sum(1 for r in out_items
                             if r["benchmark"] == b and r["condition"] == c)
                stamp(f"  {b} {c}: +{len(fresh)} (total done={done_n})")
            stamp(f"  {b}: {start + len(chunk)}/{len(sampled)}")
    release_arm(runtime)
    stamp("released")

    agg: dict[str, dict[str, dict[str, Any]]] = {}
    for c in CONDITIONS:
        agg[c] = {}
        for b in ("gsm8k", "math500"):
            cur = [r for r in out_items if r["condition"] == c
                   and r["benchmark"] == b]
            n = len(cur)
            agg[c][b] = {
                "n": n, "correct": sum(r["correct"] for r in cur),
                "accuracy": (sum(r["correct"] for r in cur) / n) if n else None,
                "truncated": sum(r["finish"] != "stop" for r in cur)}

    pair_rows: list[dict[str, Any]] = []
    for iid in sorted({r["item_id"] for r in out_items}):
        conds = {r["condition"]: r for r in out_items if r["item_id"] == iid}
        if set(conds) != set(CONDITIONS):
            stamp(f"warning: incomplete item {iid} ({sorted(conds)}) — excluded from pair table")
            continue
        pair_rows.append({
            "item_id": iid, "benchmark": next(iter(conds.values()))["benchmark"],
            "gold": next(iter(conds.values()))["gold"],
            "control_frozen": conds["control_frozen"]["correct"],
            "budget_1024": conds["budget_1024"]["correct"],
            "derive_explicit": conds["derive_explicit"]["correct"],
            "tokens": {c: conds[c]["output_tokens"] for c in CONDITIONS},
            "derive_extracted": conds["derive_explicit"]["extracted_answer"],
            "derive_generation": conds["derive_explicit"]["generation"]})

    result = {
        "schema_version": "t32-diagnostic-v1",
        "artifact": "T32_PHASE2_VERBOSITY_PROBE",
        "purpose": ("Separate verbosity policy from capability on the "
                    "adapter-wrong/base-right math subset of the frozen T31 evidence."),
        "sampling": ("Adapter-wrong & base-right items from the frozen T31 scored rows; "
                     "deterministic head of the item_id sort; gsm8k 60, math500 20; "
                     "batch 8, greedy, shared tokenizer and chat template; "
                     "kill-safe incremental writes; resumed runs skip completed pairs"),
        "conditions": CONDITIONS,
        "derive_prompt_suffix": DERIVE_SUFFIX,
        "results": agg,
        "n_pair_complete_items": len(pair_rows),
        "verdict_rule": ("derive_explicit materially above control => capability present "
                         "under a different verbosity policy (style-policy failure, "
                         "addressable by mixture); derive_explicit near control => "
                         "capability damage (conservative-adaptation candidates matter)"),
    }
    with open(OUTDIR / "probe_verbosity_summary.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(agg, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())