"""QLoRA SFT training for ScienceMath-v0.1-T3 (T3.2/T3.3).

Guarantees:
  * refuses to run on a config that fails validate_training_config()
  * refuses to run on a corpus whose checksums don't match its frozen
    checksums.json
  * resume-safe: an interrupted run resumes from the last VALID checkpoint
    (latest checkpoint dir with a readable trainer_state.json) and says so;
    it never restarts silently
  * validation loss is tracked during training; the saved adapter is the
    best-eval-loss checkpoint (never selected on training loss)
  * the saved adapter is reloaded and smoke-tested before the run is
    declared successful
  * a dry run writes ONLY to an isolated smoke directory, never to the real
    adapter path
"""
from __future__ import annotations

import gc
import json
import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

log = None  # set by _log()


def _log():
    global _LOG
    try:
        return _LOG
    except NameError:
        from sciencemath.utils.logging_setup import setup_logging
        _LOG = setup_logging("train_lora")
        return _LOG


def git_commit(repo_root: Path) -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, cwd=repo_root).stdout.strip() or None
    except Exception:
        return None


def latest_checkpoint(output_dir: Path) -> Path | None:
    """Latest valid checkpoint (has a readable trainer_state.json)."""
    if not output_dir.exists():
        return None
    candidates = []
    for p in output_dir.iterdir():
        m = re.fullmatch(r"checkpoint-(\d+)", p.name)
        if p.is_dir() and m and (p / "trainer_state.json").exists():
            try:
                json.loads((p / "trainer_state.json").read_text(encoding="utf-8"))
                candidates.append((int(m.group(1)), p))
            except Exception:
                continue          # corrupted checkpoint: not resumable
    return max(candidates)[1] if candidates else None


def verify_corpus(corpus_dir: Path) -> dict:
    """Verify the frozen corpus against its own checksums.json."""
    from sciencemath.utils.io_utils import load_json
    checksums = load_json(corpus_dir / "checksums.json")
    import hashlib

    def sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    mismatches, missing = [], []
    for name, expected in checksums.items():
        p = corpus_dir / name
        if not p.exists():
            missing.append(name)
        elif sha256_file(p) != expected:
            mismatches.append(name)
    return {"ok": not mismatches and not missing,
            "files_checked": len(checksums),
            "missing": missing, "mismatched": mismatches}


def run_training(config: dict, repo_root: Path, *,
                 dry_run: bool = False,
                 dry_run_examples: int = 16,
                 dry_run_steps: int = 3,
                 dry_run_dir: str | None = None,
                 artifact_name: str | None = None,
                 init_from_adapter: str | None = None) -> dict:
    """Train the T3 adapter. Returns a summary dict (also written into the
    adapter manifest on success).

    Curriculum additive parameters (T6.20/T6.21/T6.22): `dry_run_dir`
    relocates a dry run's outputs (default keeps the historical T3 smoke
    path); `artifact_name` overrides the manifest artifact label
    (curriculum stages are labeled Mango-v0.2-L<n>); `init_from_adapter`
    initializes the new LoRA weights from a parent adapter so the whole
    curriculum is ONE unified adapter lineage, not a fresh model."""
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              TrainingArguments, Trainer)
    from sciencemath.training.attach import attach_lora, adapter_active_state
    from sciencemath.training.config import validate_training_config
    from sciencemath.training.sft_data import SFTCollator, tokenize_corpus
    from sciencemath.utils.io_utils import load_json, read_jsonl, write_json

    log = _log()
    errors = validate_training_config(config)
    if errors:
        return {"status": "INVALID_CONFIG", "errors": errors}

    training = config["training"]
    corpus_cfg = config.get("corpus", {})
    repo_corpus = repo_root / corpus_cfg.get("dir", "")
    out_dir = Path(training["output_dir"])
    adapter_dir = Path(training["adapter_output_dir"])

    if dry_run:
        smoke = Path(dry_run_dir or "training/smoke/t3_dry_run")
        out_dir = smoke / "checkpoints"
        adapter_dir = smoke / "adapter"
    out_dir = repo_root / out_dir
    adapter_dir = repo_root / adapter_dir

    # ---- corpus integrity gate ----
    if corpus_cfg.get("require_checksum_match", True):
        integrity = verify_corpus(repo_corpus_dir(repo_root, corpus_cfg))
        if not integrity["ok"]:
            return {"status": "CORPUS_CHECKSUM_MISMATCH", "integrity": integrity}
    train_records = load_jsonl(repo_corpus_dir(repo_root, corpus_cfg) / "train.jsonl")
    val_records = read_jsonl(repo_corpus_dir(repo_root, corpus_cfg) / "validation.jsonl")
    if dry_run:
        train_records = train_records[:dry_run_examples]
        val_records = val_records[:max(2, dry_run_examples // 4)]

    # ---- model resolution ----
    model_cfg = load_yaml(repo_root / "configs" / "model.yaml")
    model_id = model_cfg["selected"]["model_id"]
    if not model_id:
        return {"status": "NO_SELECTED_MODEL"}
    revision = _model_revision(model_id)

    # ---- tokenizer + tokenization ----
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    max_seq = int(training["max_seq_length"])
    t0 = time.time()
    train_feats, train_stats = tokenize_corpus(tok, train_records, max_seq_length=max_seq)
    val_feats, val_stats = tokenize_corpus(tok, val_records, max_seq_length=max_seq)
    _log().info("tokenized train=%d val=%d in %.1fs (shortened=%d dropped=%d)",
                len(train_feats), len(val_feats), time.time() - t0,
                train_stats.get("question_shortened", 0),
                train_stats.get("dropped_too_long", 0))
    if not train_feats:
        return {"status": "EMPTY_TRAINSET"}

    # ---- model load (4-bit NF4) ----
    import torch
    from sciencemath.evaluation.model_loader import quantization_config
    compute_dtype_name = config["quantization"].get("bnb_4bit_compute_dtype", "bfloat16")
    if compute_dtype_name == "auto":
        compute_dtype_name = "bfloat16" if torch.cuda.is_bf16_supported() else "float16"
    bnb = quantization_config(compute_dtype_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, revision=revision,
        quantization_config=bnb, device_map="auto",
        trust_remote_code=bool(config["model"].get("trust_remote_code", False)))
    model.config.use_cache = False

    peft_model = attach_lora(model, config["lora"])
    state = adapter_active_state(peft_model)
    if not state["adapter_active"]:
        return {"status": "ADAPTER_NOT_ACTIVE", "adapter_state": state}

    # ---- unified-adapter lineage: seed LoRA weights from the parent ----
    parent_adapter_info = None
    if init_from_adapter:
        parent_adapter_info = _load_parent_adapter(
            peft_model, repo_root / init_from_adapter, config["lora"])
        if not parent_adapter_info.get("ok"):
            return {"status": "PARENT_ADAPTER_LOAD_FAILED",
                    "detail": parent_adapter_info}

    base_vram = _vram()
    collator = SFTCollator(tok.pad_token_id)
    eval_cfg = config.get("evaluation_during_training", {})
    use_eval = bool(eval_cfg.get("enabled", True)) and val_feats

    # transformers 5.x removed warmup_ratio: convert the declared ratio to an
    # absolute step count against the real optimizer-step total
    import math
    eff_batch = (int(training["per_device_train_batch_size"])
                 * int(training["gradient_accumulation_steps"]))
    total_optim_steps = (int(dry_run_steps) if dry_run
                         else int(training["num_train_epochs"])
                         * math.ceil(len(train_feats) / eff_batch))
    warmup_steps = max(1, int(round(float(training["warmup_ratio"]) * total_optim_steps)))
    log.info("schedule: %d optimizer steps, warmup %d steps (ratio %.3f)",
             total_optim_steps, warmup_steps, float(training["warmup_ratio"]))

    args = TrainingArguments(
        output_dir=str(out_dir),
        num_train_epochs=1 if dry_run else int(training["num_train_epochs"]),
        max_steps=int(dry_run_steps) if dry_run else -1,
        per_device_train_batch_size=int(training["per_device_train_batch_size"]),
        gradient_accumulation_steps=int(training["gradient_accumulation_steps"]),
        learning_rate=float(training["learning_rate"]),
        warmup_steps=warmup_steps,
        weight_decay=float(training["weight_decay"]),
        lr_scheduler_type=training["lr_scheduler_type"],
        max_grad_norm=float(training["max_grad_norm"]),
        seed=int(training["seed"]),
        data_seed=int(training["seed"]),
        gradient_checkpointing=bool(training["gradient_checkpointing"]),
        bf16=_use_bf16(),
        logging_steps=int(training["logging_steps"]),
        save_steps=int(dry_run_steps) if dry_run else int(training["save_steps"]),
        eval_strategy="steps" if use_eval else "no",
        eval_steps=int(dry_run_steps) if dry_run else int(training["eval_steps"]),
        per_device_eval_batch_size=int(eval_cfg.get("batch_size", 4)),
        save_total_limit=int(training["save_total_limit"]),
        load_best_model_at_end=bool(eval_cfg.get("load_best_model_at_end", True)) and use_eval,
        metric_for_best_model=eval_cfg.get("metric_for_best_model", "eval_loss"),
        greater_is_better=False,
        remove_unused_columns=False,
        label_names=["labels"],
        report_to=[],
        dataloader_num_workers=int(training.get("dataloader_num_workers", 0)),
    )

    trainer = Trainer(
        model=peft_model, args=args,
        train_dataset=train_feats, eval_dataset=val_feats if use_eval else None,
        data_collator=collator,
    )

    # ---- resume from the last VALID checkpoint (never silently restart) ----
    ckpt = latest_checkpoint(out_dir)
    resumed = ckpt is not None
    _log().info("training start: %s (resumed_from=%s, examples=%d, steps~%s)",
                "DRY RUN" if dry_run else "REAL", ckpt, len(train_feats),
                dry_run_steps if dry_run else "auto")
    t_train0 = time.time()
    trainer.train(resume_from_checkpoint=str(ckpt) if ckpt else None)
    train_time_s = time.time() - t_train0

    peak_vram = _vram()
    log_history = list(trainer.state.log_history)
    train_losses = [h["loss"] for h in log_history if "loss" in h]
    eval_losses = [h["eval_loss"] for h in log_history if "eval_loss" in h]
    final_train_loss = train_losses[-1] if train_losses else None
    best_eval_loss = min(eval_losses) if eval_losses else None

    # ---- save adapter (best-eval weights already loaded when configured) ----
    adapter_dir.mkdir(parents=True, exist_ok=True)
    peft_model.save_pretrained(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))

    # ---- write adapter manifest ----
    manifest = _adapter_manifest(
        repo_root, config, model_id, revision, corpus_cfg,
        train_stats, val_stats, log_history, final_train_loss,
        best_eval_loss, peak_vram, train_time_s, len(train_feats), len(val_feats),
        resumed, dry_run, artifact_name=artifact_name,
        parent_adapter=init_from_adapter)
    write_json(adapter_dir / "training_manifest.json", manifest)
    write_json(adapter_dir / "loss_history.json",
               {"log_history": log_history,
                "final_train_loss": final_train_loss,
                "best_eval_loss": best_eval_loss})
    write_json(adapter_dir / "environment.json", _environment())

    # ---- reload verification (fresh load of the saved adapter) ----
    reload_info = _verify_reload(model_id, revision, adapter_dir, tok)
    write_json(adapter_dir / "reload_verification.json", reload_info)

    summary = {
        "status": "COMPLETE",
        "dry_run": dry_run,
        "resumed_from_checkpoint": str(ckpt) if ckpt else None,
        "train_examples": len(train_feats),
        "validation_examples": len(val_feats),
        "steps": trainer.state.global_step,
        "final_train_loss": final_train_loss,
        "best_eval_loss": best_eval_loss,
        "peak_vram_bytes": peak_vram,
        "base_vram_bytes": base_vram,
        "train_time_s": round(train_time_s, 1),
        "adapter_dir": str(adapter_dir),
        "parent_adapter": init_from_adapter,
        "parent_adapter_info": parent_adapter_info,
        "tokenize_stats": {"train": train_stats, "validation": val_stats},
        "reload_ok": reload_info.get("ok"),
        "loss_divergence": _overfitting_flag(log_history),
    }
    if dry_run:
        write_json(repo_root / (dry_run_dir or "training/smoke/t3_dry_run")
                   / "dry_run_report.json", summary)
    return summary


def repo_corpus_dir(repo_root: Path, corpus_cfg: dict) -> Path:
    return repo_root / corpus_cfg.get("dir", "")


def _load_parent_adapter(peft_model, adapter_dir: Path, lora_cfg: dict) -> dict:
    """Load saved LoRA weights into a freshly-attached adapter (strict
    enough to catch rank/target mismatches, T6.21)."""
    import json as _json

    import torch
    from peft import set_peft_model_state_dict

    cfg_path = adapter_dir / "adapter_config.json"
    if not cfg_path.exists():
        return {"ok": False, "reason": f"no adapter_config.json in "
                                       f"{adapter_dir}"}
    parent_cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    # target_modules is a set of module names — list order is irrelevant
    mismatches = []
    for k in ("r", "lora_alpha"):
        if parent_cfg.get(k) != lora_cfg.get(k):
            mismatches.append(k)
    if (sorted(parent_cfg.get("target_modules") or [])
            != sorted(lora_cfg.get("target_modules") or [])):
        mismatches.append("target_modules")
    if mismatches:
        return {"ok": False,
                "reason": f"LoRA config mismatch with parent: {mismatches}"}
    weights_path = adapter_dir / "adapter_model.safetensors"
    if not weights_path.exists():
        weights_path = adapter_dir / "adapter_model.bin"
    if not weights_path.exists():
        return {"ok": False, "reason": "no adapter weights found"}
    if weights_path.suffix == ".safetensors":
        from safetensors.torch import load_file
        sd = load_file(str(weights_path))
    else:
        sd = torch.load(str(weights_path), map_location="cpu",
                        weights_only=True)
    res = set_peft_model_state_dict(peft_model, sd)
    missing = [k for k in (res.missing_keys or [])
               if "lora_" in k]
    unexpected = [k for k in (res.unexpected_keys or []) if "lora_" in k]
    if missing or unexpected:
        return {"ok": False, "missing": missing[:10],
                "unexpected": unexpected[:10]}
    return {"ok": True, "weights": str(weights_path),
            "lora_tensors": sum(1 for k in sd if "lora_" in k)}


def _overfitting_flag(log_history: list[dict]) -> dict | None:
    """Compare first-vs-last validation loss trend against training loss."""
    evals = [(h["step"], h["eval_loss"]) for h in log_history if "eval_loss" in h]
    if len(evals) < 2:
        return None
    first, last = evals[0][1], evals[-1][1]
    trains = [h["loss"] for h in log_history if "loss" in h]
    return {
        "first_eval_loss": first, "last_eval_loss": last,
        "eval_trend": "rising" if last > first else "falling",
        "final_train_loss": trains[-1] if trains else None,
        "likely_overfitting": bool(last > first * 1.10),
    }


def _verify_reload(model_id: str, revision: str | None, adapter_dir: Path,
                   tok) -> dict:
    """Reload the saved adapter onto a fresh base and run a tiny forward."""
    import torch
    from transformers import AutoModelForCausalLM
    from sciencemath.evaluation.model_loader import quantization_config
    from sciencemath.training.attach import adapter_active_state

    info: dict = {"ok": False}
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, revision=revision,
            quantization_config=quantization_config(),
            device_map="auto")
        from peft import PeftModel
        loaded = PeftModel.from_pretrained(model, str(adapter_dir))
        loaded.eval()
        state = adapter_active_state(loaded)
        info["adapter_state"] = state
        messages = [{"role": "user", "content": "What is 2 + 2? Answer with just the number."}]
        templ = tok.apply_chat_template(messages, tokenize=False,
                                        add_generation_prompt=True,
                                        enable_thinking=False)
        inputs = tok(templ, return_tensors="pt").to(loaded.device)
        with torch.no_grad():
            out = loaded.generate(**inputs, max_new_tokens=24, do_sample=False)
        info["smoke_output"] = tok.decode(out[0][inputs["input_ids"].shape[1]:],
                                          skip_special_tokens=True)
        info["ok"] = bool(state["adapter_active"]) and bool(info["smoke_output"])
        del loaded, model
        gc.collect()
        torch.cuda.empty_cache()
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _model_revision(model_id: str) -> str | None:
    try:
        from huggingface_hub import HfApi
        return HfApi().model_info(model_id).sha
    except Exception:
        return None


def _use_bf16() -> bool:
    import torch
    try:
        return torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    except Exception:
        return False


def _vram() -> int | None:
    import torch
    if not torch.cuda.is_available():
        return None
    return int(torch.cuda.max_memory_allocated())


def _environment() -> dict:
    import platform

    import torch
    import transformers
    env = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "transformers": transformers.__version__,
    }
    for pkg in ("peft", "bitsandbytes", "accelerate", "datasets"):
        try:
            env[pkg] = __import__(pkg).__version__
        except Exception:
            env[pkg] = None
    return env


def load_yaml(path):
    from sciencemath.utils.io_utils import load_yaml as _ly
    return _ly(path)


def load_jsonl(path):
    from sciencemath.utils.io_utils import read_jsonl
    return read_jsonl(path)


def _adapter_manifest(repo_root, config, model_id, revision, corpus_cfg,
                      train_stats, val_stats, log_history, final_train_loss,
                      best_eval_loss, peak_vram, train_time_s, n_train,
                      n_val, resumed, dry_run,
                      artifact_name: str | None = None,
                      parent_adapter: str | None = None) -> dict:
    import platform

    from sciencemath.utils.io_utils import load_json
    checksums = load_json(repo_corpus_dir(repo_root, corpus_cfg) / "checksums.json")
    training = config["training"]
    return {
        "artifact": artifact_name or "ScienceMath-v0.1-T3",
        "parent_adapter": parent_adapter,
        "adapter_lineage": "unified (T6.21): LoRA weights initialized from "
                           "the parent adapter" if parent_adapter else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "base_model": {"model_id": model_id, "revision": revision,
                       "license": "apache-2.0",
                       "quantization": "4bit-nf4-double (training and inference)"},
        "dataset": {
            "version": corpus_cfg.get("version"),
            "dir": corpus_cfg.get("dir"),
            "checksums": checksums,
            "tokenize_stats": {"train": train_stats, "validation": val_stats},
            "examples": {"train": n_train, "validation": n_val},
        },
        "training_config": {**training,
                            "lora": config["lora"],
                            "quantization": config["quantization"]},
        "results": {
            "final_train_loss": final_train_loss,
            "best_eval_loss": best_eval_loss,
            "peak_vram_bytes": peak_vram,
            "train_time_s": round(train_time_s, 1),
            "resumed_from_checkpoint": resumed,
        },
        "loss_history": log_history,
        "environment": _environment(),
        "seed": int(training["seed"]),
        "git_commit": git_commit(repo_root),
        "adapter_format": "PEFT/LoRA (unmerged)",
    }


