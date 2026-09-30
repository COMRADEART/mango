"""T31.2 Pinned identities — the bytes, and where they came from.

A comparison is only reproducible if both sides are pinned to exact revisions
rather than to whatever a name resolved to on the day. Every identity here was
resolved from the local cache and recorded at the revision actually read.

Two of these entries need saying out loud, because a reader of the report is
entitled to know them and neither is visible from a model name:

* The base model and the adapter's declared base are the *same* revision. That
  is what makes the ablation clean: the adapter adds LoRA weights to exactly
  the checkpoint it was trained on, and no other variable moves.

* The adapter bytes are the historical **T3** checkpoint, re-tagged for the
  T30 release. The T30 promotion record identifies the frozen adapter by
  ``adapter_sha256`` alone and its ``official_general_context.json`` names the
  same hash as ``training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors``.
  The comparison is therefore against the T30 release artifact — the bytes the
  T30 milestone froze and published — while the *training provenance* of those
  bytes is the earlier T3 run. ``provenance_note`` carries this into every
  manifest the package writes, so it cannot be lost between here and the
  report.
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------
MODEL_IDENTITIES: Final = {
    "base": {
        "repo_id": "Qwen/Qwen3-1.7B",
        "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        "role": "frozen base model",
    },
    "adapter": {
        "repo_id": "ComradeRt/Mango-T30-1.7B",
        "revision": "ad4bac714e442ca5c9b20420847fcadad61a6123",
        "role": "frozen T30 release adapter",
        # The only identity the T30 promotion record pins. Re-verified against
        # the local blob before every run; a mismatch is a hard failure, not a
        # warning, because a different adapter is a different experiment.
        "weights_file": "adapter_model.safetensors",
        "weights_sha256":
            "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
        "weights_bytes": 139_512_976,
        "declared_base_repo_id": "Qwen/Qwen3-1.7B",
        "declared_base_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        "provenance_note": (
            "The T30 frozen adapter bytes are the historical T3 adapter "
            "checkpoint (training/adapters/sciencemath-v0.1-t3/"
            "adapter_model.safetensors), re-tagged as the T30 release. The "
            "T30 promotion record pins this artifact by sha256 only; the T30 "
            "official evaluation never measured it on any public benchmark."
        ),
    },
}

#: The adapter ships no tokenizer and no chat template of its own. This is
#: asserted in the tests rather than assumed: if the release ever gained one,
#: the tokenizer would stop being a shared, constant factor between the arms.
ADAPTER_MUST_NOT_SHIP: Final = ("tokenizer.json", "tokenizer_config.json",
                                 "chat_template.jinja", "vocab.json")

# ---------------------------------------------------------------------------
# the frozen T30 evidence set
# ---------------------------------------------------------------------------
#: Where the T30 milestone's own record lives, and the freeze identity it
#: declares. T31 is forbidden from modifying any of it, and GATE 1 is what
#: checks that: the record still declares this root, and the working tree
#: leaves the directory untouched. Recorded here rather than recomputed
#: because recomputing the 302-component freeze would mean re-running the T30
#: preconstruction machinery, and the tree-clean check already establishes
#: that the committed record is byte-identical to the one that was audited.
T30_PROMOTION_RECORD: Final = ("evaluations/t30/promotion/"
                               "T30_FINAL_PROMOTION_RECORD.json")
T30_FROZEN_FREEZE_SHA256: Final = (
    "d5671bc059d3134675b2eb7343d3deaee58bf98ad3a6aaf66d1c61ecb54db5da")

# ---------------------------------------------------------------------------
# benchmarks
# ---------------------------------------------------------------------------
#: ``expected_items`` is the fail-closed denominator. A run that scores fewer
#: items than this did not evaluate the benchmark, and the brief forbids
#: reporting a rate over a short set as though it were the benchmark's.
BENCHMARK_IDENTITIES: Final = {
    "gsm8k": {
        "repo_id": "openai/gsm8k",
        "config": "main",
        "split": "test",
        "revision": "740312add88f781978c0658806c59bc2815b9866",
        "expected_items": 1319,
        "license": "MIT",
    },
    "math500": {
        "repo_id": "HuggingFaceH4/MATH-500",
        "config": None,
        "split": "test",
        "revision": "6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be",
        "expected_items": 500,
        "license": "MIT (derived from hendrycks/competition_math)",
    },
    "arc_easy": {
        "repo_id": "allenai/ai2_arc",
        "config": "ARC-Easy",
        "split": "test",
        "revision": "210d026faf9955653af8916fad021475a3f00453",
        "expected_items": 2376,
        "license": "CC-BY-SA-4.0",
    },
    "arc_challenge": {
        "repo_id": "allenai/ai2_arc",
        "config": "ARC-Challenge",
        "split": "test",
        "revision": "210d026faf9955653af8916fad021475a3f00453",
        "expected_items": 1172,
        "license": "CC-BY-SA-4.0",
    },
    "sciq": {
        "repo_id": "allenai/sciq",
        "config": None,
        "split": "test",
        "revision": "2c94ad3e1aafab77146f384e23536f97a4849815",
        "expected_items": 1000,
        "license": "CC-BY-NC-3.0",
    },
}

#: Total items per arm across all five benchmarks.
TOTAL_EXPECTED_ITEMS: Final = sum(
    entry["expected_items"] for entry in BENCHMARK_IDENTITIES.values())
