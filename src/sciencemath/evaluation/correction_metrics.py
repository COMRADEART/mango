"""Deterministic T9 correction metrics; no model judging."""
from __future__ import annotations

from math import sqrt


def correction_metrics(rows: list[dict]) -> dict:
    true_rows = [r for r in rows if r["case_class"] == "TRUE_FAIL"]
    false_rows = [r for r in rows if r["case_class"] == "FALSE_FAIL"]
    corrected = sum(r.get("initial_correct") is False and r.get("final_correct") is True
                    for r in true_rows)
    preserved = sum(r.get("initial_correct") is True and r.get("final_correct") is True
                    for r in false_rows)
    over = sum(r.get("initial_correct") is True and r.get("final_correct") is False
               for r in false_rows)
    under = sum(r.get("initial_correct") is False and r.get("final_correct") is False
                for r in true_rows)
    blind = sum(bool(r.get("changed")) and r.get("feedback_trust") == "UNVERIFIED"
                for r in rows)
    return {
        "true_correction": corrected / len(true_rows) if true_rows else None,
        "false_feedback_preservation": preserved / len(false_rows) if false_rows else None,
        "overcorrection": over / len(false_rows) if false_rows else None,
        "under_correction": under / len(true_rows) if true_rows else None,
        "blind_agreement": blind / len(rows) if rows else None,
        "net_correction_benefit": corrected - over,
        "counts": {"corrected_wrong": corrected, "preserved_correct": preserved,
                   "destroyed_correct": over, "still_wrong": under,
                   "blind_agreement": blind},
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]
