"""T29 wrapper around public-only T19/T20/T22/T25 protections."""
from __future__ import annotations

from pathlib import Path


def run_protection(root: Path) -> dict:
    from t27_protocol.protection import run_protection as run_public_protection

    predecessor = run_public_protection(Path(root).resolve())
    return {
        "schema_version": "t29-protection-v1",
        "artifact": "T29_HISTORICAL_PUBLIC_PROTECTION",
        "classification": "PUBLIC_SAFE",
        "status": predecessor["status"],
        "t19": predecessor["t19"],
        "t20": predecessor["t20"],
        "t22": predecessor["t22"],
        "t25_router": predecessor["t25_router"],
        "t25_dispatch": predecessor["t25_dispatch"],
        "t27_official_evaluator_invoked": False,
        "historical_private_rows_accessed": 0,
        "candidate_executions_on_historical_rows": 0,
    }
