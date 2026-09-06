"""Resume-capable frozen-suite evaluation runner (T2).

Guarantees:
  * predictions are appended one JSON line at a time and flushed (append-safe)
  * restarting skips eval_ids already present in predictions.jsonl
  * CUDA OOM mid-run is caught, recorded as failure OOM, cleanup run, and the
    loop continues (never crashes the machine, never silently swaps models)
  * raw model output is preserved untouched; extraction happens separately
No training, no LoRA, no weight modification — inference only.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from sciencemath.evaluation.extraction import (
    answers_match,
    extract_answer,
    signals_uncertainty,
)
from sciencemath.evaluation.metrics import compute_metrics, metrics_markdown
from sciencemath.evaluation.prompts import build_evaluation_content, render_for_model
from sciencemath.evaluation.taxonomy import classify_failure
from sciencemath.utils.io_utils import read_jsonl, write_json

log = logging.getLogger("sciencemath.evaluate")


def _model_info(model_id: str) -> dict:
    """Best-effort upstream revision resolution (recorded for provenance)."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(model_id)
        return {"model_revision": info.sha, "gated": bool(info.gated)}
    except Exception as exc:
        return {"model_revision": f"unresolved ({exc})", "gated": "unknown"}


def done_eval_ids(predictions_path: Path) -> set[str]:
    if not predictions_path.exists():
        return set()
    done = set()
    with open(predictions_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["eval_id"])
            except Exception:
                continue      # corrupted tail line: retried, not trusted
    return done


class PredictionWriter:
    """Append-safe JSONL writer: one record per line, flushed immediately,
    never rewritten except by an explicit atomic metrics/manifest update."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")

    def write(self, record: dict) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False,
                                  default=str) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def evaluate_model(*, model_id: str, mode: str, model_slug: str,
                   suite_dir: Path, out_dir: Path,
                   generation: dict, quantized_4bit: bool = True,
                   enable_thinking: bool | None = None,
                   max_seq_tokens: int = 2048,
                   model=None, tokenizer=None,
                   limit: int | None = None) -> dict:
    """Run the frozen suite on one model. Returns the run summary dict.

    mode: declared PRIMARY or SECONDARY mode label stored in artifacts
          (e.g. 'thinking', 'non_thinking', 'cot').
    generation: dict with seed/temperature/top_p/top_k/max_new_tokens/
                repetition penalty - recorded verbatim in artifacts.
    model/tokenizer: when supplied, the caller's already-loaded model object
          is evaluated as-is (e.g. a PeftModel with an adapter attached) —
          no internal reload, so adapter weights are actually active. When
          omitted, the base model is loaded via load_model_safely.
    """
    import torch
    from sciencemath.evaluation.model_loader import load_model_safely

    suite = read_jsonl(suite_dir / "questions.jsonl")
    if limit:
        suite = suite[:limit]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- artifacts recorded before/at load time ----
    info = _model_info(model_id)
    write_json(out_dir / "model_metadata.json", {
        "model_id": model_id, **info,
        "declared_mode": mode,
        "thinking_enabled": enable_thinking,
        "quantized_4bit": quantized_4bit,
        "note": "quantization applies to inference only; base weights unmodified",
    })

    write_json(out_dir / "generation_config.json", {
        "generation": generation,
        "mode": mode,
        "thinking_enabled": enable_thinking,
        "max_seq_tokens": max_seq_tokens,
        "determinism_note":
            "greedy where do_sample=false; sampled thinking mode uses the "
            "recorded sampling config with fixed torch seed per question",
    })

    if model is None:
        tok, model, load_info = load_model_safely(
            model_id, quantized_4bit=quantized_4bit)
        write_json(out_dir / "hardware.json", {"load": load_info})
        if not load_info.get("ok"):
            log.error("model load failed: %s", load_info.get("error"))
            write_json(out_dir / "manifest.json", {
                "model_id": model_id, "status": "LOAD_FAILED",
                "error": load_info.get("error"),
            })
            return {"status": "LOAD_FAILED", "error": load_info.get("error")}
    else:
        if tokenizer is None:
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained(model_id)
            if tok.pad_token_id is None:
                tok.pad_token = tok.eos_token
        else:
            tok = tokenizer
        load_info = {"ok": True, "provided_by_caller": True,
                     "note": "model loaded by caller (adapter attached externally)"
                     if getattr(model, "peft_config", None) else
                     "model loaded by caller"}
        log.info("using caller-provided model (adapter-aware evaluation)")

    pred_path = out_dir / "predictions.jsonl"
    done = done_eval_ids(pred_path)
    writer = PredictionWriter(pred_path)
    fail_log = open(out_dir / "failures.jsonl", "a", encoding="utf-8")
    log.info("resume: %d of %d questions already evaluated", len(done), len(suite))

    gen_cfg = dict(generation)
    do_sample = bool(gen_cfg.get("do_sample", False))
    seed = int(gen_cfg.get("seed", 42))

    t_run0 = time.time()
    try:
        for item in suite:
            eval_id = item["eval_id"]
            if eval_id in done:
                continue
            content = build_evaluation_content(
                item["question"], item["answer_type"], item.get("choices"))
            templ = render_for_model(tok, content,
                                     enable_thinking=enable_thinking)
            record = {
                "eval_id": eval_id,
                "category": item.get("category"),
                "source": item.get("source"),
                "question": item["question"],
                "expected_answer": item.get("expected_answer"),
                "answer_type": item["answer_type"],
                "raw_model_output": None,
                "extracted_answer": None,
                "correct": None,
                "evaluation_method": None,
                "model_id": model_id,
                "model_revision": info.get("model_revision"),
                "mode": mode,
                "thinking_enabled": enable_thinking,
                "generation": gen_cfg,
                "latency_s": None,
                "input_tokens": None,
                "output_tokens": None,
                "finish_reason": None,
                "error": None,
                "failure": None,
            }
            try:
                t0 = time.time()
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)
                inputs = tok(templ, return_tensors="pt",
                             truncation=True, max_length=max_seq_tokens)
                inputs = {k: v.to(model.device) for k, v in inputs.items()}
                n_in = int(inputs["input_ids"].shape[1])
                gen_kwargs = {
                    "max_new_tokens": int(gen_cfg.get("max_new_tokens", 1024)),
                    "pad_token_id": tok.pad_token_id or tok.eos_token_id,
                }
                if do_sample:
                    gen_kwargs.update({
                        "do_sample": True,
                        "temperature": float(gen_cfg["temperature"]),
                        "top_p": float(gen_cfg["top_p"]),
                        "top_k": int(gen_cfg.get("top_k", 0)),
                    })
                else:
                    gen_kwargs["do_sample"] = False
                if gen_cfg.get("repetition_penalty"):
                    gen_kwargs["repetition_penalty"] = float(gen_cfg["repetition_penalty"])
                with torch.no_grad():
                    out = model.generate(**inputs, **gen_kwargs)
                latency = time.time() - t0
                n_out = int(out.shape[1]) - n_in
                raw = tok.decode(out[0][n_in:], skip_special_tokens=True)
                finish = "length" if n_out >= int(
                    gen_cfg.get("max_new_tokens", 1024)) else "stop"
            except torch.cuda.OutOfMemoryError as exc:
                record["error"] = f"OOM: {exc}"
                record["failure"] = "OOM"
                torch.cuda.empty_cache()
                writer.write(record)
                continue
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["failure"] = classify_failure(
                    correct=False, extracted=None,
                    answer_type=item["answer_type"], choices=item.get("choices"),
                    raw="", error=record["error"])
                writer.write(record)
                continue

            record.update({
                "raw_model_output": raw,
                "latency_s": round(latency, 3),
                "input_tokens": n_in,
                "output_tokens": n_out,
                "finish_reason": finish,
            })

            expected = item.get("expected_answer")
            extracted = extract_answer(raw, item["answer_type"],
                                       item.get("choices"))
            record["extracted_answer"] = extracted

            # ---- correctness by category semantics ----
            if item.get("category") == "uncertainty_calibration":
                # correct behavior = signal uncertainty instead of fabricating
                ok = signals_uncertainty(raw)
                record["evaluation_method"] = "uncertainty_signal_detection"
            elif item["answer_type"] == "multiple_choice":
                ok = extracted is not None and extracted == expected
                record["evaluation_method"] = "exact_choice_match"
            elif item["answer_type"] == "numeric":
                ok = answers_match(str(expected), extracted or "")
                record["evaluation_method"] = "numeric_exact_match"
            else:
                ok = answers_match(str(expected), extracted or "")
                record["evaluation_method"] = "normalized_text_match"
            record["correct"] = bool(ok) if expected != "__UNKNOWN__" else bool(ok)

            record["failure"] = classify_failure(
                correct=record["correct"], extracted=extracted,
                answer_type=item["answer_type"], choices=item.get("choices"),
                raw=raw or "", finish_reason=None if finish == "stop" else finish,
                expected_answer=expected, category=item.get("category", ""))
            writer.write(record)

            if record.get("failure"):
                fail_log.write(json.dumps({
                    "eval_id": eval_id, "category": record["category"],
                    "failure": record["failure"],
                    "extracted_answer": extracted,
                    "expected_answer": expected,
                }, ensure_ascii=False, default=str) + "\n")
                fail_log.flush()
    finally:
        writer.close()
        fail_log.close()

    # ---- metrics + manifest (atomic) ----
    predictions = read_jsonl(pred_path)
    peak_vram = None
    if torch.cuda.is_available():
        peak_vram = int(torch.cuda.max_memory_allocated())
    metrics = compute_metrics(predictions, peak_vram_bytes=peak_vram,
                              model_load_vram_bytes=load_info.get("load_vram_bytes"))
    write_json(out_dir / "metrics.json", metrics)
    with open(out_dir / "metrics.md", "w", encoding="utf-8") as f:
        f.write(metrics_markdown(model_slug, metrics))

    write_json(out_dir / "manifest.json", {
        "model_id": model_id,
        "model_revision": info.get("model_revision"),
        "status": "COMPLETE" if len(predictions) >= len(suite) else "PARTIAL",
        "mode": mode,
        "thinking_enabled": enable_thinking,
        "quantized_4bit": quantized_4bit,
        "suite": str(suite_dir),
        "questions_total": len(suite),
        "questions_answered": len(predictions),
        "generation": gen_cfg,
        "runtime_s": round(time.time() - t_run0, 1),
        "load": load_info,
    })
    return {"status": "COMPLETE", "n_predictions": len(predictions),
            "metrics": metrics}