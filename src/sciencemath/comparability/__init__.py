"""T31 — public comparability of the frozen Mango T30 adapter against its base.

This package answers one question and refuses to answer any other:

    Under identical, reproducible evaluation conditions, what capability does
    the frozen Mango T30 adapter gain or lose relative to the frozen
    Qwen3-1.7B base model?

It is an *evaluation layer only*. It trains nothing, tunes nothing, and holds
no opinion about what the answer should be. The names below are the frozen
vocabulary the whole package shares, so that a run's configuration, its raw
rows, its scored rows and its report all refer to the same things by the same
spellings.
"""
from __future__ import annotations

from .contract import (
    ARM_ADAPTER, ARM_BASE, ARMS, BENCHMARKS, BENCHMARK_ORDER, DECISION_FAIL,
    DECISION_PARTIAL, DECISION_PASS, ERROR_CATEGORIES, EXTRACTION_FAILED,
    EXTRACTION_OK, SCHEMA_VERSION,
)
from .identity import BENCHMARK_IDENTITIES, MODEL_IDENTITIES

__all__ = [
    "ARM_ADAPTER", "ARM_BASE", "ARMS", "BENCHMARKS", "BENCHMARK_IDENTITIES",
    "BENCHMARK_ORDER", "DECISION_FAIL", "DECISION_PARTIAL", "DECISION_PASS",
    "ERROR_CATEGORIES", "EXTRACTION_FAILED", "EXTRACTION_OK",
    "MODEL_IDENTITIES", "SCHEMA_VERSION",
]
