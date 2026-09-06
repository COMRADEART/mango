"""T3 training config validation, checkpoint discovery, adapter detection."""
import json
from pathlib import Path

from sciencemath.training.attach import adapter_active_state
from sciencemath.training.config import expected_effective_batch, validate_training_config
from sciencemath.training.train import latest_checkpoint, _overfitting_flag
from sciencemath.utils.io_utils import load_yaml


def _valid_config() -> dict:
    return {
        "model": {"base_model_id": "Qwen/Qwen3-1.7B", "trust_remote_code": False},
        "corpus": {"version": "sciencemath-sft-v1",
                   "dir": "training/datasets/sciencemath-sft-v1",
                   "require_checksum_match": True},
        "training": {
            "output_dir": "training/checkpoints/x",
            "adapter_output_dir": "training/adapters/x",
            "num_train_epochs": 3,
            "max_seq_length": 1024,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 16,
            "learning_rate": 1.0e-4,
            "warmup_ratio": 0.03,
            "weight_decay": 0.01,
            "lr_scheduler_type": "cosine",
            "max_grad_norm": 1.0,
            "seed": 42,
            "gradient_checkpointing": True,
        },
        "quantization": {"load_in_4bit": True, "bnb_4bit_quant_type": "nf4"},
        "lora": {"r": 32, "lora_alpha": 64, "lora_dropout": 0.05,
                 "target_modules": ["q_proj", "o_proj"]},
    }


def test_real_config_validates():
    cfg = load_yaml(Path(__file__).resolve().parents[1] / "configs" / "training.yaml")
    assert validate_training_config(cfg) == []
    assert expected_effective_batch(cfg) >= 4


def test_valid_config_passes():
    assert validate_training_config(_valid_config()) == []


def test_missing_gradient_checkpointing_rejected():
    cfg = _valid_config()
    cfg["training"]["gradient_checkpointing"] = False
    errors = validate_training_config(cfg)
    assert any("gradient_checkpointing" in e for e in errors)


def test_out_of_range_lr_rejected():
    cfg = _valid_config()
    cfg["training"]["learning_rate"] = 1.0
    assert any("learning_rate" in e for e in validate_training_config(cfg))


def test_fp16_quantization_rejected():
    cfg = _valid_config()
    cfg["quantization"]["load_in_4bit"] = False
    assert any("load_in_4bit" in e for e in validate_training_config(cfg))


def test_bad_lora_ratio_rejected():
    cfg = _valid_config()
    cfg["lora"]["lora_alpha"] = 512
    errors = validate_training_config(cfg)
    assert any("lora_alpha" in e for e in errors)


def test_unknown_target_module_rejected():
    cfg = _valid_config()
    cfg["lora"]["target_modules"] = ["not_a_module"]
    assert any("unknown modules" in e for e in validate_training_config(cfg))


# ---------------------------------------------------------------- checkpoints
def test_latest_checkpoint_prefers_highest_valid(tmp_path):
    for n in (50, 100, 150):
        d = tmp_path / f"checkpoint-{n}"
        d.mkdir()
        (d / "trainer_state.json").write_text(json.dumps({"global_step": n}))
    assert latest_checkpoint(tmp_path) == tmp_path / "checkpoint-150"


def test_latest_checkpoint_ignores_corrupted(tmp_path):
    for n, content in ((100, json.dumps({"global_step": 100})), (150, "{corrupt")):
        d = tmp_path / f"checkpoint-{n}"
        d.mkdir()
        (d / "trainer_state.json").write_text(content)
    assert latest_checkpoint(tmp_path) == tmp_path / "checkpoint-100"


def test_latest_checkpoint_empty_dir(tmp_path):
    assert latest_checkpoint(tmp_path) is None
    assert latest_checkpoint(tmp_path / "missing") is None


# ------------------------------------------------------------- adapter state
class StubPeftModel:
    def __init__(self, peft=True, disabled=False):
        self.peft_config = {"t3": object()} if peft else {}
        self.active_adapters = ["t3"] if peft else []
        self._adapters_disabled = disabled


def test_adapter_active_true_when_attached_and_enabled():
    state = adapter_active_state(StubPeftModel())
    assert state["adapter_active"] is True
    assert state["adapter_names"] == ["t3"]


def test_adapter_inactive_when_disabled():
    state = adapter_active_state(StubPeftModel(disabled=True))
    assert state["adapter_active"] is False
    assert state["adapters_disabled"] is True


def test_adapter_inactive_on_plain_model():
    class Plain:
        pass
    state = adapter_active_state(Plain())
    assert state["adapter_active"] is False
    assert state["is_peft_model"] is False


# ------------------------------------------------------- overfitting signal
def test_overfitting_flag_rising_eval_loss():
    hist = [{"loss": 1.0, "step": 100, "eval_loss": 1.2},
            {"loss": 0.5, "step": 200, "eval_loss": 1.0},
            {"loss": 0.5, "step": 300, "eval_loss": 1.4}]
    flag = _overfitting_flag(hist)
    assert flag["likely_overfitting"] is True
    assert flag["eval_trend"] == "rising"


def test_overfitting_flag_falling_eval_loss():
    hist = [{"loss": 1.0, "step": 100, "eval_loss": 1.2},
            {"loss": 0.8, "step": 200, "eval_loss": 1.0},
            {"loss": 0.6, "step": 300, "eval_loss": 0.9}]
    assert _overfitting_flag(hist)["likely_overfitting"] is False


def test_overfitting_flag_needs_two_evals():
    assert _overfitting_flag([{"loss": 1.0, "step": 100, "eval_loss": 1.2}]) is None