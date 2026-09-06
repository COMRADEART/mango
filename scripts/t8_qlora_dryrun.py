"""T8.19 — QLoRA training-feasibility dry run for a migration candidate.

16-32 examples from the frozen SFT corpus, 1-5 optimizer steps:
  model load (4-bit NF4) -> adapter attach -> forward -> backward ->
  optimizer step -> checkpoint save -> reload

Measures VRAM at each stage for micro-batch 1 AND 2 (T3 history on the
1.7B: batch 1 fits, batch 2 OOM — for 3B-4B assume nothing, measure).
Records whether local QLoRA training is feasible on the RTX 4050 6 GB.

Usage:
  python scripts/t8_qlora_dryrun.py --model ID --label slug \
      [--steps 3] [--examples 16] [--seq 1024] [--rank 32]
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "evaluations" / "t8" / "training_feasibility"
CORPUS = REPO / "training" / "datasets" / "sciencemath-sft-v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def vram() -> dict:
    import torch
    if not torch.cuda.is_available():
        return {}
    return {"allocated_mib": round(torch.cuda.memory_allocated() / 2**20, 1),
            "reserved_mib": round(torch.cuda.memory_reserved() / 2**20, 1)}


def cleanup() -> None:
    gc.collect()
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def try_batch(model_id: str, records: list[dict], *, batch: int, steps: int,
              seq: int, rank: int, label: str, revision: str | None) -> dict:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, \
        TrainingArguments, Trainer

    from sciencemath.evaluation.model_loader import quantization_config
    from sciencemath.training.attach import adapter_active_state, attach_lora
    from sciencemath.training.sft_data import SFTCollator, tokenize_corpus

    rec: dict = {"micro_batch": batch, "label": label}
    try:
        tok = AutoTokenizer.from_pretrained(model_id)
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        feats, _stats = tokenize_corpus(tok, records, max_seq_length=seq)
        rec["features"] = len(feats)

        model = AutoModelForCausalLM.from_pretrained(
            model_id, revision=revision,
            quantization_config=quantization_config("bfloat16"),
            device_map="auto")
        model.config.use_cache = False
        peft_model = attach_lora(model, {
            "r": rank, "lora_alpha": rank * 2, "lora_dropout": 0.05,
            "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                               "gate_proj", "up_proj", "down_proj"]})
        state = adapter_active_state(peft_model)
        rec["adapter_active"] = bool(state["adapter_active"])
        rec["after_attach_vram"] = vram()

        args = TrainingArguments(
            output_dir=str(OUT / label / f"ckpt_b{batch}"),
            num_train_epochs=1, max_steps=steps,
            per_device_train_batch_size=batch,
            gradient_accumulation_steps=1,
            learning_rate=1e-4, warmup_steps=1, weight_decay=0.0,
            lr_scheduler_type="constant", max_grad_norm=0.3,
            seed=42, data_seed=42, gradient_checkpointing=True,
            bf16=True, logging_steps=1, save_steps=steps,
            save_total_limit=1, remove_unused_columns=False,
            label_names=["labels"], report_to=[],
        )
        trainer = Trainer(model=peft_model, args=args,
                          train_dataset=feats, data_collator=SFTCollator(
                              tok.pad_token_id))
        t0 = time.time()
        trainer.train()
        rec["train_time_s"] = round(time.time() - t0, 1)
        rec["peak_vram"] = vram()
        rec["peak_reserved_mib"] = round(
            torch.cuda.max_memory_reserved() / 2**20, 1)
        log_hist = list(trainer.state.log_history)
        rec["losses"] = [h["loss"] for h in log_hist if "loss" in h]

        # checkpoint + reload smoke
        ckpts = sorted((OUT / label / f"ckpt_b{batch}").glob("checkpoint-*"))
        rec["checkpoint_saved"] = bool(ckpts)
        del peft_model, model, trainer
        cleanup()
        rec["ok"] = True
        return rec
    except Exception as exc:  # noqa: BLE001 — OOM or any failure is data
        rec["ok"] = False
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        rec["oom"] = "OutOfMemoryError" in type(exc).__name__
        try:
            del model, peft_model  # noqa: F821
        except Exception:  # noqa: BLE001
            pass
        cleanup()
        return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--label", required=True)
    ap.add_argument("--steps", type=int, default=3)
    ap.add_argument("--examples", type=int, default=24)
    ap.add_argument("--seq", type=int, default=1024)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--batches", default="1,2",
                    help="comma list of micro-batch sizes to try")
    args = ap.parse_args()

    import torch
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [json.loads(l) for l in
             (CORPUS / "train.jsonl").read_text(encoding="utf-8")
             .splitlines() if l.strip()]
    records = lines[:args.examples]

    result: dict = {
        "dry_run": "T8.19 QLoRA feasibility",
        "label": args.label, "model": args.model,
        "revision": args.revision, "recorded_at": now(),
        "steps": args.steps, "examples": args.examples,
        "max_seq_length": args.seq, "lora_rank": args.rank,
        "corpus": str(CORPUS), "gpu": torch.cuda.get_device_name(0),
        "vram_total_mib": round(
            torch.cuda.get_device_properties(0).total_memory / 2**20)
        if torch.cuda.is_available() else None,
    }

    for batch in [int(b) for b in args.batches.split(",")]:
        cleanup()
        r = try_batch(args.model, records, batch=batch, steps=args.steps,
                      seq=args.seq, rank=args.rank, label=args.label,
                      revision=args.revision)
        result[f"micro_batch_{batch}"] = r
        if not r.get("ok") and r.get("oom") and batch == 1:
            result["feasible_local"] = False
            break
    feasible = [v for k, v in result.items()
                if k.startswith("micro_batch_") and v.get("ok")]
    result["feasible_local"] = bool(feasible)
    result["conclusion"] = (
        f"QLoRA fits at micro-batch {[r['micro_batch'] for r in feasible]} "
        if feasible else "QLoRA did NOT fit at any tested micro-batch; "
        "consider alternate training environments (T8.19 options)")

    (OUT / f"{args.label}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("label", "feasible_local", "conclusion")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())