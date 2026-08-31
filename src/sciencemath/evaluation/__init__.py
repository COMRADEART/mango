"""Evaluation (T2/T4 — not implemented yet).

Planned public surface: prompt builders, answer extraction, the PASS/FAIL/
UNKNOWN math verifier, exact-match metrics, and evaluation writers producing
manifest.json / predictions.jsonl / metrics.json / metrics.md / failures.jsonl
under evaluations/base and evaluations/tuned.
"""
__all__: list[str] = []

_NOT_IMPLEMENTED = (
    "sciencemath.evaluation is planned for milestones T2 (baseline) and T4 "
    "(verifier). This import is a placeholder so the package layout exists."
)


def __getattr__(name):
    raise ImportError(_NOT_IMPLEMENTED)