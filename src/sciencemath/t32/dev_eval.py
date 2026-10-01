"""T32 Phase 7 development evaluation runner (protocol: DEV_PROTOCOL.md).

Runs one model arm over the five dev slices using:
  * the FROZEN T31 prompt policy (prompts.prompt_text / render_chat),
  * the FROZEN per-benchmark budgets (512 / 1024 / 32), greedy, batch 8,
  * the FROZEN scorer (comparability.scoring.score_row),

with the adapters attached from a directory (candidate) or through the
frozen harness path (base / adapter anchors). This module does not modify
any frozen comparability code; it composes the frozen primitives.

Usage:
  PYTHONPATH=src python -m sciencemath.t32.dev_eval --arm base
  PYTHONPATH=src python -m sciencemath.t32.dev_eval --arm adapter
  PYTHONPATH=src python -m sciencemath.t32.dev_eval \
      --arm-dir training/adapters/t32-A-math-restore --label t32-A
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

from sciencemath.comparability.loaders import EvalItem

ROOT = Path(".")
OUT = ROOT / "evaluations" / "t32" / "development"
DEV = ROOT / "training" / "t32" / "dev_sets"

SLICES: dict[str, dict[str, Any]] = {
    "dev_gsm8k": {"benchmark": "gsm8k", "budget": 512},
    "dev_math": {"benchmark": "math500", "budget": 1024},
    "dev_sciq": {"benchmark": "sciq", "budget": 32},
    "dev_arc_easy": {"benchmark": "arc_easy", "budget": 32},
    "dev_arc_challenge": {"benchmark": "arc_challenge", "budget": 32},
}
BATCH = 8


def load_candidate(adapter_dir: Path):
    """Attach a T32 candidate adapter to the FROZEN base revision.

    Same base bytes, same shared tokenizer, same attach mechanism as the
    frozen harness's adapter path; the difference is only the adapter source
    (the freshly saved candidate directory instead of the pinned T30 hub
    snapshot — candidates are new bytes by definition)."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from sciencemath.comparability.contract import ARM_BASE
    from sciencemath.comparability.identity import MODEL_IDENTITIES
    from sciencemath.comparability.runner import _load_pretrained

    base = MODEL_IDENTITIES[ARM_BASE]
    tok = AutoTokenizer.from_pretrained(base["repo_id"],
                                        revision=base["revision"])
    tok.padding_side = "left"
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = _load_pretrained(AutoModelForCausalLM, base["repo_id"],
                             base["revision"], dtype=torch.bfloat16)
    model.to("cuda:0")
    model.eval()
    model = PeftModel.from_pretrained(model, str(adapter_dir.resolve()),
                                      is_trainable=False)
    model.eval()
    weights = adapter_dir / "adapter_model.safetensors"
    identity = {"base_repo_id": base["repo_id"],
                "base_revision": base["revision"],
                "adapter_dir": adapter_dir.resolve().as_posix(),
                "weights_sha256": hashlib.sha256(
                    weights.read_bytes()).hexdigest()}
    return tok, model, identity


def measure(runtime: Any, slices: list[str]) -> dict[str, Any]:
    from sciencemath.comparability.contract import BENCHMARKS
    from sciencemath.comparability.prompts import prompt_text, render_chat
    from sciencemath.comparability.runner import generate_batch, release_arm
    from sciencemath.comparability.scoring import score_row

    arm_dir = OUT / runtime.arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    rec: dict[str, dict[str, Any]] = {}
    t0 = time.time()

    for s in slices:
        cfg = SLICES[s]
        kind = BENCHMARKS[cfg["benchmark"]]["kind"]
        rows = [json.loads(line) for line in
                (DEV / f"{s}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        # kill-safe resume: skip (dev_id) pairs already on disk
        slice_path = arm_dir / f"{s}.jsonl"
        done: set[str] = set()
        raws: list[dict[str, Any]] = []
        if slice_path.exists():
            for line in slice_path.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                done.add(r["dev_id"])
                raws.append(r)
        pending = [r for r in rows if r["item_id"] not in done]
        expected = {r["item_id"] for r in rows}
        if len(done) != len(raws) or not done <= expected:
            raise ValueError(f"Invalid persisted development IDs in {slice_path}")
        if not pending and raws:
            print(f"[{time.time() - t0:6.1f}s] {s}: all {len(raws)} rows "
                  f"already on disk; skipping", flush=True)
        for start in range(0, len(pending), BATCH):
            chunk = pending[start:start + BATCH]
            # EvalItems first so the frozen prompt/score paths apply verbatim
            items = []
            for r in chunk:
                fields = {f: r.get(f) for f in EvalItem.__dataclass_fields__}
                fields["meta"] = {"provenance": r["provenance"]}
                items.append(EvalItem(**fields))
            texts = [prompt_text(it, kind) for it in items]
            chats = [render_chat(runtime.tokenizer, t, enable_thinking=False)
                     for t in texts]
            gens, finish, _, out_toks, _ = generate_batch(
                runtime, chats, max_new_tokens=cfg["budget"])
            fresh = []
            for r, it, gen, fin, tok_n in zip(chunk, items, gens, finish,
                                              out_toks):
                scored = score_row({"arm": runtime.arm,
                                    "benchmark": cfg["benchmark"],
                                    "raw_generation": gen,
                                    "finish_reason": fin}, it)
                fresh.append({"dev_id": r["item_id"],
                              "benchmark": cfg["benchmark"],
                              "raw_generation": gen, "finish_reason": fin,
                              "output_tokens": tok_n,
                              "gold": r["gold"],
                              "content_valid": scored["content_valid"],
                              "extracted_answer":
                              scored.get("extracted_answer")})
            # append + flush immediately (kill loses at most one batch)
            with open(slice_path, "a", encoding="utf-8", newline="\n") as f:
                for r in fresh:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            raws.extend(fresh)
            print(f"[{time.time() - t0:6.1f}s] {s}: "
                  f"{len(raws)}/{len(rows)}", flush=True)
        # recompute fully from disk so resumed slices count everything
        disk_rows = [json.loads(line) for line in
                     slice_path.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
        n = len(disk_rows)
        if {r["dev_id"] for r in disk_rows} != expected or n != len(expected):
            raise ValueError(f"Incomplete development slice {s}")
        correct = sum(1 for r in disk_rows if r["content_valid"] is True)
        trunc = sum(1 for r in disk_rows if r["finish_reason"] != "stop")
        rec[s] = {"n": n, "correct": correct,
                  "accuracy": round(correct / n, 4) if n else None,
                  "truncated": trunc,
                  "truncation_rate": trunc / n if n else None,
                  "extraction_failure_rate": sum(r.get("extracted_answer") is None for r in disk_rows) / n if n else None,
                  "mean_output_tokens": sum(r["output_tokens"] for r in disk_rows) / n if n else None}
        import statistics
        rec[s]["median_output_tokens"] = statistics.median(r["output_tokens"] for r in disk_rows) if n else None
        print(f"[{time.time() - t0:6.1f}s] {s}: {rec[s]}", flush=True)

    metrics: dict[str, Any] = {"arm": runtime.arm,
                               "identity": runtime.identity,
                               "slices": rec,
                               "wall_s": round(time.time() - t0, 1)}
    if all(s in rec for s in SLICES):
        metrics["acc_gsm8k_dev"] = rec["dev_gsm8k"]["accuracy"]
        metrics["acc_math_dev"] = rec["dev_math"]["accuracy"]
        metrics["acc_sciq_dev"] = rec["dev_sciq"]["accuracy"]
        ea, ca = rec["dev_arc_easy"], rec["dev_arc_challenge"]
        metrics["acc_mc_dev"] = round(
            (ea["n"] * ea["accuracy"] + ca["n"] * ca["accuracy"])
            / (ea["n"] + ca["n"]), 4)
        metrics["math_dev_mean"] = round(
            (rec["dev_gsm8k"]["accuracy"]
             + rec["dev_math"]["accuracy"]) / 2, 4)
    path = OUT / f"{runtime.arm}_metrics.json"
    path.write_text(json.dumps(metrics, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    release_arm(runtime)
    print(f"[{time.time() - t0:6.1f}s] released; metrics -> {path}",
          flush=True)
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("base", "adapter"),
                    help="frozen harness arms (anchors)")
    ap.add_argument("--arm-dir", help="candidate adapter directory")
    ap.add_argument("--label")
    ap.add_argument("--slices", default=",".join(SLICES))
    args = ap.parse_args()
    if args.arm_dir and args.arm:
        ap.error("--arm and --arm-dir are mutually exclusive")

    slices = [s.strip() for s in args.slices.split(",") if s.strip()]
    unknown = [s for s in slices if s not in SLICES]
    if unknown:
        ap.error(f"unknown slices {unknown}")
    if not (args.arm or args.arm_dir):
        ap.error("one of --arm / --arm-dir is required")

    from sciencemath.comparability import runner as _runner
    from sciencemath.comparability.runner import load_arm

    if args.arm:
        runtime = load_arm(args.arm)
        runtime.arm = {"base": "base", "adapter": "t30-anchor"}[args.arm]
        runtime.identity = {"arm": args.arm}
    else:
        tok, model, identity = load_candidate(Path(args.arm_dir))
        runtime = _runner.ArmRuntime(
            arm=args.label or Path(args.arm_dir).name,
            model=model, tokenizer=tok)
        runtime.identity = identity

    OUT.mkdir(parents=True, exist_ok=True)
    metrics = measure(runtime, slices)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
