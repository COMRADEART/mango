"""T7.12/T7.13 — Replanning: event-triggered only, bounded, with stall
detection.

Legal replan triggers (fixed set):
  VERIFICATION_FAILED  — a CHECK/verify failed against tool recomputation
  RETRIEVAL_INSUFFICIENT — retrieval empty or failed
  CONTRADICTION        — detected conflict between observations
  DEPENDENCY_INVALID   — a needed dependency step failed

Not legal: "maybe try again", periodic replanning, replanning because a
step merely took long. Loop detection fingerprints failed plans
(autogen Magentic-One progress-ledger pattern A7); a repeated identical
failure terminates the run as STALLED.
"""
from __future__ import annotations

from sciencemath.executive.plan import plan_fingerprint

REPLAN_TRIGGERS = ("VERIFICATION_FAILED", "RETRIEVAL_INSUFFICIENT",
                   "CONTRADICTION", "DEPENDENCY_INVALID")


def detect_trigger(state: dict, verification: dict,
                   observations=None) -> tuple[str | None, str]:
    """Map the current state to at most one replan trigger. Deterministic
    priority: CONTRADICTION > VERIFICATION_FAILED > RETRIEVAL_INSUFFICIENT
    > DEPENDENCY_INVALID. `observations` (the current live dict, or a
    list) takes precedence over the (possibly stale) state history so a
    succeeded retry does not re-trigger the same failure."""
    if observations is not None:
        obs_list = [ob for ob in (observations.values()
                                  if isinstance(observations, dict)
                                  else observations)
                    if isinstance(ob, dict)]
    else:
        obs_list = [ob for ob in state.get("observations", [])
                    if isinstance(ob, dict)]
    if state.get("conflicts"):
        return "CONTRADICTION", ("conflicting values detected in the "
                                 "problem text")
    if verification.get("verdict") == "FAILED":
        return "VERIFICATION_FAILED", verification.get(
            "failing_check", "answer failed tool verification")
    retrieval_failed = any(
        ob.get("action") == "RETRIEVE" and ob.get("status") == "FAILED"
        for ob in obs_list)
    if retrieval_failed:
        return "RETRIEVAL_INSUFFICIENT", "retrieval produced no usable " \
                                         "evidence"
    failed = verification.get("failed_steps") or []
    if failed:
        return "DEPENDENCY_INVALID", f"steps {failed} failed"
    return None, ""


def replan_budget_ok(state: dict, budgets) -> bool:
    return state.get("replans", 0) < budgets.max_replans


def loop_fingerprint(state: dict, new_plan: dict) -> str:
    """Fingerprint of (failed plan history, proposed plan). Identical
    fingerprint twice => STALLED."""
    key = f"{plan_fingerprint(new_plan)}:{state.get('replans', 0)}" \
        if False else plan_fingerprint(new_plan)
    return key


def register_failure(state: dict, plan: dict, reason: str) -> str:
    """Record a failure fingerprint; returns the stall verdict."""
    fp = plan_fingerprint(plan)
    entry = {"fingerprint": fp, "reason": reason}
    history = state.setdefault("failure_fingerprints", [])
    history.append(entry)
    same = [h for h in history if h["fingerprint"] == fp]
    if len(same) >= 2:
        return "STALLED"
    return ""


def should_replan(state: dict, verification: dict, budgets,
                  observations=None) -> tuple[bool, str, str]:
    """Single deterministic decision point. Returns
    (replan?, trigger, reason)."""
    if not replan_budget_ok(state, budgets):
        return False, "", "replan budget exhausted"
    trigger, reason = detect_trigger(state, verification, observations)
    if trigger is None:
        return False, "", reason
    return True, trigger, reason


def build_replan_instruction(trigger: str, reason: str) -> str:
    """The model never invents the new plan freely; the deterministic
    fallback constructor runs with an amended understanding. This
    instruction is recorded for the trajectory log only."""
    return (f"Replan triggered by {trigger}: {reason}. The replacement "
            "plan is constructed deterministically from the amended "
            "understanding (deterministic plan constructor), not freely "
            "by the model.")