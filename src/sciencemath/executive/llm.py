"""Executive model-call helper.

Mirrors the T5R/T6 deterministic greedy generation call (seeded, greedy
or recorded sampling, think-block stripped upstream). Token counts are
returned for cost accounting (T7.39).
"""
from __future__ import annotations

from sciencemath.evaluation.prompts import render_for_model


class ModelCallError(RuntimeError):
    pass


def call_model(model, tokenizer, user_content: str, generation: dict,
               *, max_seq_tokens: int = 4096,
               enable_thinking: bool = False) -> tuple[str, int, int]:
    """Generate greedily. Returns (text, input_tokens, output_tokens).

    Raises ModelCallError on failure — the caller records it as a
    FAILED observation (errors-as-observations), never silently."""
    import torch

    templ = render_for_model(tokenizer, user_content,
                             enable_thinking=enable_thinking)
    try:
        torch.manual_seed(int(generation.get("seed", 42)))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(generation.get("seed", 42)))
        inputs = tokenizer(templ, return_tensors="pt", truncation=True,
                           max_length=max_seq_tokens)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        n_in = int(inputs["input_ids"].shape[1])
        gen_kwargs = {
            "max_new_tokens": int(generation.get("max_new_tokens", 512)),
            "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
            "do_sample": False,
        }
        if generation.get("do_sample"):
            gen_kwargs.update({
                "do_sample": True,
                "temperature": float(generation["temperature"]),
                "top_p": float(generation["top_p"]),
                "top_k": int(generation.get("top_k", 0)),
            })
        with torch.no_grad():
            out = model.generate(**inputs, **gen_kwargs)
        n_out = int(out.shape[1]) - n_in
        text = tokenizer.decode(out[0][n_in:], skip_special_tokens=True)
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        raise ModelCallError(f"{type(exc).__name__}: {exc}") from exc

    from sciencemath.evaluation.extraction import strip_think_block
    return strip_think_block(text), n_in, n_out