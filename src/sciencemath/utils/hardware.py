"""Hardware detection and conservative settings recommendation.

Used by every GPU-touching stage (T2 baseline eval, T3 QLoRA training, T6
chat) to pick settings that fit available VRAM and avoid CUDA OOM. Pure
Python + optional torch: works on CPU-only machines, Kaggle, Colab.
"""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field, asdict


@dataclass
class HardwareReport:
    platform_name: str
    python_version: str
    torch_installed: bool
    torch_version: str | None
    cuda_available: bool
    cuda_version: str | None
    device_name: str | None
    device_count: int
    total_vram_bytes: int | None
    compute_capability: tuple[int, int] | None
    bf16_supported: bool

    # Derived recommended settings (conservative; see recommend_settings)
    recommendations: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def detect_hardware() -> HardwareReport:
    """Probe torch/CUDA/GPU. Never raises; a missing/torch-less machine
    simply reports cuda_available=False."""
    report = HardwareReport(
        platform_name=platform.platform(),
        python_version=sys.version.split()[0],
        torch_installed=False,
        torch_version=None,
        cuda_available=False,
        cuda_version=None,
        device_name=None,
        device_count=0,
        total_vram_bytes=None,
        compute_capability=None,
        bf16_supported=False,
    )
    try:
        import torch
    except Exception:
        return report

    report.torch_installed = True
    report.torch_version = torch.__version__
    report.cuda_available = bool(torch.cuda.is_available())
    if not report.cuda_available:
        return report

    report.device_count = torch.cuda.device_count()
    idx = torch.cuda.current_device()
    props = torch.cuda.get_device_properties(idx)
    report.device_name = props.name
    report.total_vram_bytes = int(props.total_memory)
    report.compute_capability = (props.major, props.minor)
    if hasattr(torch.cuda, "get_device_capability"):
        report.compute_capability = torch.cuda.get_device_capability(idx)
    try:
        report.bf16_supported = bool(torch.cuda.is_bf16_supported())
    except Exception:
        report.bf16_supported = False
    report.cuda_version = getattr(torch.version, "cuda", None)
    return report


def recommend_settings(report: HardwareReport) -> dict:
    """Return training/inference settings known to be safe for the measured
    hardware. Deliberately conservative on <=6 GB to avoid OOM crashes.

    Tiers (4-bit QLoRA, seq len 1024, gradient checkpointing on):
      < 4 GB : no training; inference on <=1.5B 4-bit only
      4-8 GB : batch 2 x accum 8, 4-bit, max 4B model
      8-16 GB: batch 4 x accum 4
      > 16 GB: batch 8 x accum 2 (or plain 16-bit training)
    """
    if not report.cuda_available:
        return {
            "device": "cpu",
            "can_train_qlora": False,
            "note": "No CUDA device: use CPU for preprocessing/evaluation only. "
                    "Train on Kaggle/Colab with a free GPU.",
            "precision": "float32",
            "load_in_4bit": False,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 16,
            "max_seq_length": 512,
            "max_model_params_b": 0,
        }

    vram_gb = (report.total_vram_bytes or 0) / (1024 ** 3)
    precision = "bfloat16" if report.bf16_supported else "float16"

    if vram_gb < 4:
        tier = dict(
            device="cuda",
            can_train_qlora=False,
            precision=precision,
            load_in_4bit=True,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=16,
            max_seq_length=512,
            max_model_params_b=1.5,
        )
    elif vram_gb < 8:
        tier = dict(
            device="cuda",
            can_train_qlora=True,
            precision=precision,
            load_in_4bit=True,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=8,
            max_seq_length=1024,
            max_model_params_b=4.0,
        )
    elif vram_gb < 16:
        tier = dict(
            device="cuda",
            can_train_qlora=True,
            precision=precision,
            load_in_4bit=True,
            per_device_train_batch_size=4,
            gradient_accumulation_steps=4,
            max_seq_length=2048,
            max_model_params_b=7.0,
        )
    else:
        tier = dict(
            device="cuda",
            can_train_qlora=True,
            precision=precision,
            load_in_4bit=False,
            per_device_train_batch_size=8,
            gradient_accumulation_steps=2,
            max_seq_length=2048,
            max_model_params_b=8.0,
        )
    tier["measured_vram_gb"] = round(vram_gb, 2)
    tier["gradient_checkpointing"] = tier["can_train_qlora"] or vram_gb >= 8
    return tier


def full_report() -> HardwareReport:
    report = detect_hardware()
    report.recommendations = recommend_settings(report)
    return report