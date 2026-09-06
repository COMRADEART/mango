"""T7.34 — Executive budgets and cost accounting.

Every axis the executive can consume is predeclared and bounded.
Exhaustion produces explicit terminal states, never exceptions
(research pattern A4).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

# defaults mirror configs/executive.yaml; the config file is authoritative
MAX_PLAN_ATTEMPTS = 2     # model-proposed plan tries (schema-feedback retry)
MAX_PLAN_STEPS = 6        # actions per plan (T7.6)
MAX_REPLANS = 2           # event-triggered replans (T7.12)
MAX_MODEL_CALLS = 16      # total generation calls per run
MAX_TOOL_CALLS = 8        # registry invocations per run
MAX_RETRIEVALS = 3        # retrieval invocations per run
MAX_TOTAL_SECONDS = 180.0
MAX_STEP_SECONDS = 60.0


@dataclass
class Budgets:
    max_plan_attempts: int = MAX_PLAN_ATTEMPTS
    max_plan_steps: int = MAX_PLAN_STEPS
    max_replans: int = MAX_REPLANS
    max_model_calls: int = MAX_MODEL_CALLS
    max_tool_calls: int = MAX_TOOL_CALLS
    max_retrievals: int = MAX_RETRIEVALS
    max_total_seconds: float = MAX_TOTAL_SECONDS
    max_step_seconds: float = MAX_STEP_SECONDS

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_config(cls, cfg: dict | None) -> "Budgets":
        cfg = cfg or {}
        return cls(
            max_plan_attempts=int(cfg.get("max_plan_attempts",
                                          MAX_PLAN_ATTEMPTS)),
            max_plan_steps=int(cfg.get("max_plan_steps", MAX_PLAN_STEPS)),
            max_replans=int(cfg.get("max_replans", MAX_REPLANS)),
            max_model_calls=int(cfg.get("max_model_calls", MAX_MODEL_CALLS)),
            max_tool_calls=int(cfg.get("max_tool_calls", MAX_TOOL_CALLS)),
            max_retrievals=int(cfg.get("max_retrievals", MAX_RETRIEVALS)),
            max_total_seconds=float(cfg.get("max_total_seconds",
                                            MAX_TOTAL_SECONDS)),
            max_step_seconds=float(cfg.get("max_step_seconds",
                                           MAX_STEP_SECONDS)),
        )


def default_usage() -> dict:
    return {
        "model_calls": 0,
        "tool_calls": 0,
        "retrievals": 0,
        "replans": 0,
        "plan_attempts": 0,
        "steps_executed": 0,
        "elapsed_s": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def exceeded(usage: dict, budgets: Budgets) -> str | None:
    """Return the FIRST exhausted budget axis, or None. Deterministic
    priority order so termination is reproducible."""
    checks = (
        ("max_model_calls", "model_calls"),
        ("max_tool_calls", "tool_calls"),
        ("max_retrievals", "retrievals"),
        ("max_replans", "replans"),
    )
    for cap_key, usage_key in checks:
        if usage.get(usage_key, 0) >= getattr(budgets, cap_key):
            return cap_key
    if usage.get("elapsed_s", 0.0) >= budgets.max_total_seconds:
        return "max_total_seconds"
    return None