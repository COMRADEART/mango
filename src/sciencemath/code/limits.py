"""T15.36 — bounded resource limits for coding-agent execution."""
from __future__ import annotations

DEFAULT_LIMITS = {
    "max_files_read": 40,
    "max_files_modified": 8,
    "max_commands": 20,
    "max_repair_iterations": 3,  # T15R.8 default; 4–5 only with progress
    "max_repair_iterations_hard_cap": 5,
    "max_execution_seconds": 600,
    "max_output_bytes": 200_000,
    "max_diff_lines": 500,
}


def check_limits(usage: dict, limits: dict | None = None) -> tuple:
    """Return (ok: bool, violated: list)."""
    lim = dict(DEFAULT_LIMITS)
    if limits:
        lim.update(limits)
    violated = [k for k, v in lim.items()
                if usage.get(k, 0) > v]
    return (not violated, violated)
