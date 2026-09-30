"""T32 Phase 9: ONE final locked evaluation of the selected candidate.

The frozen T31 model-only methodology, applied exactly once to the T32 arm:
full frozen benchmark membership (load_benchmark), the frozen prompt policy,
the frozen per-benchmark budgets from the frozen config, greedy decoding,
and the frozen scorer. The base and T30 columns reuse the FROZEN T31 scored
rows for the same item ids (same prompts, membership, and scorer — stated
in the report); no row of the frozen evidence is rewritten.

Writes under evaluations/t32/final/:
  t32/<benchmark>.jsonl   fresh T32-arm scored rows
  T32_FINAL_SCORES.json   per-benchmark accuracies for the three arms
                          (T32 fresh; base/T30 joined from frozen rows)

Run AFTER Phase 8 selection. Never change anything because of the result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, "src")

ROOT = Path(".")
T31 = ROOT / "evaluations" / "t31"
FINAL = ROOT / "evaluations" / "t32" / "final"
BENCHMARKS_ALL = ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq")

# frozen per-benchmark generation budgets (t31_frozen_config decoding_primary)
PRIMARY_BUDGETS = {"gsm8k": 512, "math500": 1024, "arc_easy": 32,
                   "arc_challenge": 32, "sciq": 32}
BATCH = 8


def frozen_budgets() -> dict[str, int]:
    cfg = json.loads((T31 / "config/t31_frozen_config.json").read_text(
        encoding="utf-8"))
    budgets = dict((cfg.get("decoding_primary") or {}).get(
        "max_new_tokens") or {})
    # every frozen budget must equal the recorded primary budget
    for b in BENCHMARKS_ALL:
        if budgets.get(b) != PRIMARY_BUDGETS[b]:
            raise SystemExit(
                f"frozen decoding_primary budget for {b} = "
                f"{budgets.get(b)}, expected {PRIMARY_BUDGETS[b]}")
    return budgets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter-dir", required=True,
                    help="selected candidate adapter directory (Phase 8)")
    ap.add_argument("--arm-name", required=True,
                    help="label for the fresh arm (e.g. t32-A)")
    args = ap.parse_args()

    from sciencemath.comparability.contract import BENCHMARKS
    from sciencemath.comparability.loaders import load_benchmark
    from sciencemath.comparability.prompts import prompt_text, render_chat
    from sciencemath.comparability.runner import (
        ArmRuntime,
        generate_batch,
        release_arm,
    )
    from sciencemath.comparability.scoring import score_row
    from sciencemath.t32.dev_eval import load_candidate

    budgets = frozen_budgets()
    adapter_dir = Path(args.adapter_dir)
    if not (adapter_dir / "adapter_model.safetensors").is_file():
        raise SystemExit(f"no adapter_model.safetensors in {adapter_dir}")

    # load the T32 arm EXACTLY the way dev_eval attached its candidates
    tok, model, identity = load_candidate(adapter_dir)
    runtime = ArmRuntime(arm=args.arm_name, model=model, tokenizer=tok)
    runtime.identity = identity
    print(json.dumps(identity, indent=1), flush=True)

    arm_dir = FINAL / args.arm_name
    arm_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for b in BENCHMARKS_ALL:
        kind = BENCHMARKS[b]["kind"]
        items = load_benchmark(b)
        raws = []
        for start in range(0, len(items), BATCH):
            chunk = items[start:start + BATCH]
            texts = [prompt_text(it, kind) for it in chunk]
            chats = [render_chat(tok, t, enable_thinking=False)
                     for t in texts]
            gens, finish, _, out_toks, _ = generate_batch(
                runtime, chats, max_new_tokens=budgets[b])
            for it, gen, fin, tok_n, text in zip(chunk, gens, finish,
                                                 out_toks, texts):
                scored = score_row({"arm": args.arm_name, "benchmark": b,
                                    "raw_generation": gen,
                                    "finish_reason": fin}, it)
                raws.append({
                    "item_id": it.item_id, "benchmark": it.benchmark,
                    "model_id": identity["base_repo_id"],
                    "model_revision": identity["base_revision"],
                    "adapter_label": args.arm_name,
                    "adapter_sha256": identity["weights_sha256"],
                    "prompt_sha256": hashlib.sha256(
                        text.encode("utf-8")).hexdigest(),
                    "max_new_tokens": budgets[b],
                    "raw_generation": gen, "finish_reason": fin,
                    "output_tokens": tok_n,
                    "content_valid": scored["content_valid"],
                    "extracted_answer": scored.get("extracted_answer")})
            if (start // BATCH) % 20 == 0:
                print(f"[{time.time() - t0:7.1f}s] {b}: "
                      f"{start + len(chunk)}/{len(items)}", flush=True)
        path = arm_dir / f"{b}.jsonl"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in raws:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n = len(raws)
        corr = sum(1 for r in raws if r["content_valid"] is True)
        print(f"[{time.time() - t0:7.1f}s] {b}: DONE n={n} "
              f"acc={corr / n:.4f} sha={hashlib.sha256(path.read_bytes()).hexdigest()[:16]}",
              flush=True)

    release_arm(runtime)
    print("T32 arm generation complete; run sciencemath.t32.paired for "
          "the three-arm join", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())