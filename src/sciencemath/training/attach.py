"""LoRA attachment and programmatic adapter-state detection (T3).

`adapter_active_state()` is the ablation-check primitive: it reads the model
object itself (not config files) so an evaluation can PROVE whether an
adapter is active on the weights being used.
"""
from __future__ import annotations

import logging

log = logging.getLogger("sciencemath.training")


def adapter_active_state(model) -> dict:
    """Programmatically detect whether a PEFT adapter is attached AND enabled.

    Returns {"adapter_active", "adapter_names", "is_peft_model",
             "adapters_disabled"} — recorded verbatim into eval artifacts.
    """
    is_peft = hasattr(model, "peft_config") and bool(getattr(model, "peft_config", None))
    names = list(getattr(model, "peft_config", {}).keys()) if is_peft else []
    # peft sets _adapters_disabled inside the disable_adapter() context
    disabled = bool(getattr(model, "_adapters_disabled", False))
    active = getattr(model, "active_adapters", None)
    active_names = list(active) if active is not None else names
    return {
        "is_peft_model": is_peft,
        "adapter_names": names,
        "adapter_active": bool(is_peft and active_names and not disabled),
        "adapters_disabled": disabled,
    }


def attach_lora(model, lora_cfg: dict):
    """Attach a LoRA adapter per configs/training.yaml [lora] section.

    Uses prepare_model_for_kbit_training for the 4-bit base. Returns the
    PeftModel."""
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    prepared = prepare_model_for_kbit_training(model)
    lconfig = LoraConfig(
        r=int(lora_cfg["r"]),
        lora_alpha=int(lora_cfg["lora_alpha"]),
        lora_dropout=float(lora_cfg["lora_dropout"]),
        target_modules=list(lora_cfg["target_modules"]),
        bias="none",
        task_type="CAUSAL_LM",
    )
    peft_model = get_peft_model(prepared, lconfig)
    peft_model.print_trainable_parameters()
    return peft_model


def load_base_with_adapter(model_id: str, adapter_dir: str,
                           *, quantized_4bit: bool = True):
    """Load the base model (4-bit) and attach a saved adapter for inference.

    Returns (tokenizer, model, info_dict). The adapter is loaded, never
    merged — base weights stay untouched on disk."""
    from peft import PeftModel

    from sciencemath.evaluation.model_loader import load_model_safely

    tok, model, info = load_model_safely(model_id, quantized_4bit=quantized_4bit)
    if not info.get("ok"):
        return None, None, info
    try:
        peft_model = PeftModel.from_pretrained(model, str(adapter_dir),
                                               adapter_name="t3")
        peft_model.set_adapter("t3")
        peft_model.eval()
        state = adapter_active_state(peft_model)
        info["adapter_state"] = state
        info["adapter_dir"] = str(adapter_dir)
        log.info("adapter loaded: active=%s names=%s",
                 state["adapter_active"], state["adapter_names"])
        return tok, peft_model, info
    except Exception as exc:
        info["ok"] = False
        info["error"] = f"adapter attach failed: {type(exc).__name__}: {exc}"
        return None, None, info