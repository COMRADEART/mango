"""T31.8 The frozen evaluation configuration.

The brief's ordering is explicit: validate the loader, validate the scorer,
smoke-test the base model, verify raw capture, verify extraction, *then*
"freeze the evaluation configuration", "hash the configuration", and "only
then run the full base and adapter evaluations". It also forbids the failure
this ordering exists to prevent: "Do not choose decoding settings after
viewing which side scores better."

This module is the single place those settings live. The hash it produces is
recorded on every row of every run, so a row generated under a different
configuration cannot be quietly mixed into a set generated under this one.

Two decisions deserve their reasoning stated, because both are visible in the
results and a reader is entitled to check them:

**Greedy decoding.** ``do_sample=False`` for the primary comparison. The brief
prefers deterministic greedy decoding for the primary comparable benchmark,
and determinism is what makes a paired comparison meaningful — with sampling,
a difference between arms can be a difference between two draws.

**Thinking disabled, for both arms.** Qwen3 supports a reasoning mode
(``enable_thinking``). It is switched *off* for the primary arm, for both
sides, and the choice is recorded here rather than discovered later. The
reason is not that thinking is unrepresentative — it is that thinking length
is itself a learned behaviour, so an adapter that reasons longer than its base
would differ from it in two ways at once. Holding it off leaves the weights as
the only variable. The cost is real and is disclosed as a limitation: this
under-reports what either model can do when allowed to reason, and the report
says so rather than presenting the numbers as a model's ceiling.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any, Final

from sciencemath.comparability.contract import BENCHMARKS, SCHEMA_VERSION
from sciencemath.comparability.identity import (
    BENCHMARK_IDENTITIES, MODEL_IDENTITIES,
)

#: Settings shared by both arms and every benchmark. ``None`` for top_p and
#: top_k is what transformers expects alongside greedy decoding; recording
#: them explicitly means "we did not set these" is a fact on the artifact
#: rather than an absence.
DECODING: Final = {
    "do_sample": False,
    "temperature": None,
    "top_p": None,
    "top_k": None,
    "repetition_penalty": 1.0,
    "num_beams": 1,
    "enable_thinking": False,
    "dtype": "bfloat16",
    "device": "cuda:0",
    "quantization": "none",
    "batch_size": 8,
    "seed": 20260930,
    "seed_policy": (
        "Greedy decoding is seed-independent. A fixed seed is still recorded "
        "and set so that the optional sampled robustness arm is reproducible."
    ),
}

#: The reasoning-enabled arm, run only after the primary arm completes and
#: reported separately. Identical to DECODING but for the one flag, so that
#: the two arms of the *robustness* check also differ in exactly one thing.
DECODING_THINKING: Final = {**DECODING, "enable_thinking": True,
                            "max_new_tokens_scale": 4}

#: The brief asks for stop tokens to be recorded.
STOP_TOKEN_IDS: Final = (151645,)     # <|im_end|>

ARM_KINDS: Final = ("primary", "thinking")


class ConfigError(RuntimeError):
    """The frozen configuration is missing, malformed, or has drifted."""


def environment_manifest() -> dict[str, Any]:
    """Runtime facts that affect what a number means.

    Recorded because two runs on different torch or transformers versions are
    not the same experiment even when every setting matches.
    """
    manifest: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }
    try:
        import torch
        manifest.update({
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_device_count": torch.cuda.device_count(),
        })
        if torch.cuda.is_available():
            manifest["gpu_name"] = torch.cuda.get_device_name(0)
            total = torch.cuda.get_device_properties(0).total_memory
            manifest["gpu_total_memory_bytes"] = int(total)
    except ImportError:                            # pragma: no cover
        manifest["torch"] = "absent"
    for name in ("transformers", "datasets", "peft", "accelerate", "sympy"):
        try:
            module = __import__(name)
            manifest[name] = getattr(module, "__version__", "unknown")
        except ImportError:                        # pragma: no cover
            manifest[name] = "absent"
    return manifest


def decoding_policy(*, thinking: bool = False) -> dict[str, Any]:
    """The decoding settings plus the per-benchmark generation budgets."""
    base = dict(DECODING_THINKING if thinking else DECODING)
    base.pop("max_new_tokens_scale", None)
    budgets = {name: spec["max_new_tokens"] for name, spec in BENCHMARKS.items()}
    if thinking:
        budgets = {name: value * 4 for name, value in budgets.items()}
    return {**base, "max_new_tokens": budgets,
            "stop_token_ids": list(STOP_TOKEN_IDS)}


def frozen_config(*, suite_hashes: dict[str, str] | None = None,
                  chat_template_sha256: str = "") -> dict[str, Any]:
    """The complete configuration, ready to be hashed and written.

    ``suite_hashes`` and ``chat_template_sha256`` are supplied by the caller
    because computing them requires loading the datasets and the tokenizer.
    A configuration frozen without them would not pin what was actually
    evaluated, so they are required, not optional in spirit — the caller that
    omits them gets a config whose hash cannot vouch for the items.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": "T31_FROZEN_EVALUATION_CONFIG",
        "models": MODEL_IDENTITIES,
        "benchmarks": BENCHMARK_IDENTITIES,
        "prompt_policy_hash": _prompt_policy_hash(),
        "chat_template_sha256": chat_template_sha256,
        "suite_hashes": dict(suite_hashes or {}),
        "decoding_primary": decoding_policy(thinking=False),
        "decoding_secondary": decoding_policy(thinking=True),
        "experimental_variable": (
            "The adapter is attached to the same base revision it declares as "
            "its parent. Items, prompt policy, chat template, decoding "
            "settings, extractor and scorer are identical for both arms; the "
            "only difference is which weights produce the tokens."
        ),
        "environment": environment_manifest(),
    }


def _prompt_policy_hash() -> str:
    from sciencemath.comparability.prompts import prompt_policy_hash
    return prompt_policy_hash()


def config_hash(config: dict[str, Any]) -> str:
    """Canonical hash of a configuration.

    Deliberately excludes nothing: if a field is in the config it is part of
    the identity, so adding a setting changes the hash and a stale artifact is
    detectable rather than merely suspect.
    """
    payload = {key: value for key, value in config.items()
               if key != "config_sha256"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def freeze(path: Path, config: dict[str, Any]) -> str:
    """Write the configuration once, refuse to overwrite it, return its hash.

    Write-once is the point. A configuration that can be rewritten after
    seeing results is not frozen, and the failure it enables — adjusting
    settings and re-running only the losing arm — would be invisible in the
    final artifact.
    """
    from sciencemath.utils.io_utils import write_json

    digest = config_hash(config)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing_hash = config_hash(existing)
        if existing_hash != digest:
            raise ConfigError(
                f"refusing to overwrite a frozen configuration: {path} "
                f"hashes to {existing_hash}, the new one to {digest}. A "
                f"configuration that changes after results exist is not "
                f"frozen.")
        return digest

    payload = dict(config)
    payload["config_sha256"] = digest
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, atomic=True)
    return digest


def load_frozen(path: Path) -> dict[str, Any]:
    """Read a frozen configuration and verify it has not drifted."""
    if not path.exists():
        raise ConfigError(f"no frozen configuration at {path}")
    config = json.loads(path.read_text(encoding="utf-8"))
    recorded = config.get("config_sha256")
    if not recorded:
        raise ConfigError(f"{path} carries no config_sha256")
    actual = config_hash(config)
    if actual != recorded:
        raise ConfigError(
            f"{path} has drifted: recorded {recorded}, computed {actual}")
    return config
