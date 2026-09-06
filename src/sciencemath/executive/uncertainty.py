"""T7.15 — Uncertainty engine: categorical epistemic status ONLY.

Statuses are derived from OBSERVABLE signals (empty retrieval, failed
verification, contradictions, missing quantities) — never a model
self-assessment percentage. This is the direct fix for the measured
T6 weakness (uncertainty signaling 0.0000).
"""
from __future__ import annotations

import re

from sciencemath.executive.state import EVIDENCE_STATUSES

_INSUFFICIENT_PAT = re.compile(
    r"\b(insufficient|not enough information|cannot be determined|"
    r"missing (information|data|value)|no evidence|unknown)\b",
    re.IGNORECASE)


def signals_from_run(state: dict, observations: dict,
                     verification: dict, missing_information: list) -> dict:
    """Collect the observable signal vector (recorded per run).
    Retrieval history is unioned from the run-level flags the runner
    maintains on state (a replan re-arm may drop failed RETRIEVE
    observations from the live dict) and the live observations."""
    retrieval_obs = [ob for ob in observations.values()
                     if ob.get("action") == "RETRIEVE"]
    empty_retrieval = bool(state.get("retrieval_empty")) or any(
        ob.get("status") == "FAILED"
        and ob.get("detail", {}).get("error_type")
        == "RETRIEVAL_EMPTY" for ob in retrieval_obs)
    good_retrieval = bool(state.get("retrieval_ok")) or any(
        ob.get("status") == "OK" for ob in retrieval_obs)
    math_obs = [ob for ob in observations.values()
                if ob.get("action") == "MATH_TOOL"]
    tool_ok = any(ob.get("status") == "OK" for ob in math_obs)
    return {
        "empty_retrieval": empty_retrieval,
        "good_retrieval": good_retrieval,
        "tool_ok": tool_ok,
        "verification_verdict": verification.get("verdict", "UNKNOWN"),
        "missing_information": list(missing_information or []),
        "contradictions": bool(state.get("conflicts")),
    }


def decide_status(signals: dict) -> str:
    """Deterministic mapping signal-vector -> categorical status.
    Priority order is fixed and auditable."""
    if signals.get("contradictions"):
        return "CONFLICTING_EVIDENCE"
    missing = signals.get("missing_information") or []
    if signals.get("empty_retrieval") and not signals.get("good_retrieval"):
        return "INSUFFICIENT_INFORMATION"
    if missing and not signals.get("tool_ok"):
        return "INSUFFICIENT_INFORMATION"
    if signals.get("text_insufficient") and not signals.get("tool_ok"):
        # the model itself stated insufficiency in its output
        return "INSUFFICIENT_INFORMATION"
    v = signals.get("verification_verdict")
    if v == "VERIFIED":
        return "VERIFIED"
    if v == "FAILED":
        return "PARTIALLY_SUPPORTED"
    if signals.get("good_retrieval") and signals.get("tool_ok"):
        return "STRONGLY_SUPPORTED"
    if signals.get("good_retrieval") or signals.get("tool_ok"):
        return "PARTIALLY_SUPPORTED"
    return "UNCERTAIN"


def answer_should_decline(status: str, signals: dict) -> bool:
    """INSUFFICIENT_INFORMATION and CONFLICTING_EVIDENCE runs produce the
    insufficiency sentence recognized by the frozen grader
    (signals_uncertainty) rather than a guessed answer. A verified or
    tool-backed answer is never discarded just because ONE retrieval
    attempt came back empty."""
    if status in ("INSUFFICIENT_INFORMATION", "CONFLICTING_EVIDENCE"):
        return True
    if (signals.get("empty_retrieval")
            and not signals.get("good_retrieval")
            and not signals.get("tool_ok")):
        return True
    return False


DECLINE_SENTENCE = "There is insufficient information to answer."


def decline_answer(status: str) -> str:
    if status == "CONFLICTING_EVIDENCE":
        return ("The provided information contains contradictions. "
                + DECLINE_SENTENCE)
    return DECLINE_SENTENCE


def status_from_text(text: str) -> bool:
    """Does the model text itself signal insufficiency? (used when the
    model, given empty evidence, declines on its own)."""
    return bool(_INSUFFICIENT_PAT.search(text or ""))