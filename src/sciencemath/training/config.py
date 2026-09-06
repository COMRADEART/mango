"""Training configuration validation (T3).

validate_training_config() is called before ANY training run (dry or real)
and before the smoke test; a config that fails validation cannot start a
run, so an accidental OOM-by-config cannot happen silently.
"""
from __future__ import annotations

ALLOWED_TARGET_MODULES = {
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
}


def validate_training_config(cfg: dict) -> list[str]:
    """Return a list of human-readable errors; empty means valid."""
    errors: list[str] = []

    training = cfg.get("training", {})
    quant = cfg.get("quantization", {})
    lora = cfg.get("lora", {})

    # ---- hard ranges (T3 contract: conservative 6 GB QLoRA) ----
    seq = training.get("max_seq_length")
    if not isinstance(seq, int) or not (256 <= seq <= 4096):
        errors.append(f"training.max_seq_length: {seq!r} outside 256..4096")
    bs = training.get("per_device_train_batch_size")
    if not isinstance(bs, int) or not (1 <= bs <= 4):
        errors.append(f"training.per_device_train_batch_size: {bs!r} outside 1..4")
    ga = training.get("gradient_accumulation_steps")
    if not isinstance(ga, int) or not (1 <= ga <= 64):
        errors.append(f"training.gradient_accumulation_steps: {ga!r} outside 1..64")
    eff = (bs or 0) * (ga or 0)
    if eff and not (4 <= eff <= 64):
        errors.append(f"effective batch {eff} outside 4..64")
    lr = training.get("learning_rate")
    if not isinstance(lr, (int, float)) or not (1e-5 <= lr <= 5e-4):
        errors.append(f"training.learning_rate: {lr!r} outside 1e-5..5e-4")
    epochs = training.get("num_train_epochs")
    if not isinstance(epochs, int) or not (1 <= epochs <= 5):
        errors.append(f"training.num_train_epochs: {epochs!r} outside 1..5")
    if not isinstance(training.get("seed"), int):
        errors.append("training.seed: must be an integer (determinism)")
    if not training.get("gradient_checkpointing", False):
        errors.append("training.gradient_checkpointing: must be true on 6 GB VRAM")

    # ---- quantization must be 4-bit NF4 QLoRA ----
    if not quant.get("load_in_4bit"):
        errors.append("quantization.load_in_4bit: must be true (QLoRA contract)")
    if quant.get("bnb_4bit_quant_type") != "nf4":
        errors.append("quantization.bnb_4bit_quant_type: expected nf4")

    # ---- LoRA sanity ----
    r = lora.get("r")
    if not isinstance(r, int) or not (8 <= r <= 128):
        errors.append(f"lora.r: {r!r} outside 8..128")
    alpha = lora.get("lora_alpha")
    if isinstance(r, int) and isinstance(alpha, int):
        ratio = alpha / r
        if not (0.5 <= ratio <= 4.0):
            errors.append(
                f"lora.lora_alpha/lora.r = {ratio:.2f} outside sane 0.5..4.0")
    dropout = lora.get("lora_dropout")
    if not isinstance(dropout, (int, float)) or not (0.0 <= dropout <= 0.2):
        errors.append(f"lora.lora_dropout: {dropout!r} outside 0..0.2")
    modules = lora.get("target_modules")
    if not modules:
        errors.append("lora.target_modules: empty")
    else:
        unknown = set(modules) - ALLOWED_TARGET_MODULES
        if unknown:
            errors.append(f"lora.target_modules: unknown modules {sorted(unknown)}")

    # ---- paths ----
    if not training.get("output_dir"):
        errors.append("training.output_dir: required")
    if not training.get("adapter_output_dir"):
        errors.append("training.adapter_output_dir: required")

    return errors


def expected_effective_batch(cfg: dict) -> int:
    training = cfg.get("training", {})
    return (int(training.get("per_device_train_batch_size", 0))
            * int(training.get("gradient_accumulation_steps", 0)))