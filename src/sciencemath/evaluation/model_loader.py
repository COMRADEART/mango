"""Hardware-safe model loading for evaluation (T2).

Safety sequence, per GPU-safety rules:
  1. tokenizer load
  2. model load (recorded quantization, inference-only)
  3. tiny smoke prompt + VRAM measurement

No LoRA, no training, no adapter merging, no weight modification of any kind.
"""
from __future__ import annotations

import gc
import logging
import time

log = logging.getLogger("sciencemath.evaluate")


def _vram() -> tuple[int | None, int | None]:
    import torch

    if not torch.cuda.is_available():
        return None, None
    return (int(torch.cuda.max_memory_allocated()),
            int(torch.cuda.max_memory_reserved()))


def quantization_config(compute_dtype_name: str = "bfloat16"):
    """4-bit NF4 inference quantization config (recorded in artifacts)."""
    from transformers import BitsAndBytesConfig
    import torch

    dtype = getattr(torch, compute_dtype_name, torch.bfloat16)
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=dtype,
        bnb_4bit_use_double_quant=True,
    )


def load_model_safely(model_id: str, *, quantized_4bit: bool = True,
                      compute_dtype: str = "bfloat16",
                      smoke_prompt: str = "What is 2 + 2? Answer with just the number.") -> tuple:
    """Load tokenizer+model and run a one-prompt smoke test.

    Returns (tokenizer, model, info_dict) where info_dict["ok"] is False on
    failure with info_dict["error"] describing it. On OOM, GPU memory is
    cleared before returning, so a safer profile can be attempted.
    """
    info = {"ok": False, "error": None,
            "quantization": "4bit-nf4-double" if quantized_4bit else "bf16",
            "load_vram_bytes": None, "peak_vram_bytes": None,
            "reserved_vram_bytes": None, "smoke_latency_s": None}
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model = None
    tok = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    try:
        tok = AutoTokenizer.from_pretrained(model_id)
        model_kwargs = {}
        if torch.cuda.is_available():
            if quantized_4bit:
                model_kwargs["quantization_config"] = quantization_config(compute_dtype)
            model_kwargs["device_map"] = "auto"
            model_kwargs["dtype"] = "auto"
        else:
            model_kwargs["device_map"] = "cpu"   # smoke only; real runs need GPU

        t0 = time.time()
        model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
        model.eval()
        info["load_vram_bytes"] = _vram()[0]
        log.info("model %s loaded in %.1fs", model_id, time.time() - t0)

        # --- tiny smoke prompt (never optimized, just proves generate works) ---
        t1 = time.time()
        messages = [{"role": "user", "content": smoke_prompt}]
        templ = tok.apply_chat_template(messages, tokenize=False,
                                        add_generation_prompt=True)
        inputs = tok(templ, return_tensors="pt").to(model.device)
        with torch.no_grad():
            model.generate(**inputs, max_new_tokens=16, do_sample=False)
        info["smoke_latency_s"] = round(time.time() - t1, 2)
        info["peak_vram_bytes"], info["reserved_vram_bytes"] = _vram()
        info["ok"] = True
        log.info("smoke prompt OK (%.2fs)", info["smoke_latency_s"])
        return tok, model, info
    except torch.cuda.OutOfMemoryError as exc:
        _cleanup(model)
        info["error"] = f"OOM during load: {exc}"
        return None, None, info
    except Exception as exc:
        _cleanup(model)
        info["error"] = f"load failed: {type(exc).__name__}: {exc}"
        return None, None, info


def _cleanup(model) -> None:
    try:
        del model
    except Exception:
        pass
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass