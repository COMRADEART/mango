"""Fail-closed, bounded execution of explicit internal capability plans.

The T19 planner remains PROPOSE_ONLY.  This layer accepts a validated plan and
coordinates registered internal adapters; it never grants external-action
authority.  Adapter registration is trusted deployment configuration, whereas
scenario text, retrieved material, and adapter outputs are data.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from sciencemath.executive.router_v2 import route_request
from sciencemath.executive.skills import SKILL_IDS

AUTHORITY = "COORDINATE_INTERNAL_WORK_ONLY"
CLASSIFICATIONS = frozenset({"PUBLIC_SAFE", "PRIVATE_EVALUATION", "PRIVATE_BLIND"})
TERMINALS = frozenset({"COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
                       "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY",
                       "SECURITY_REFUSAL", "ERROR"})
REPLAN_TRIGGERS = frozenset({"UNAVAILABLE_CAPABILITY", "VERIFICATION_FAILURE",
                             "RETRIEVAL_CONFLICT", "DEPENDENCY_FAILURE",
                             "RECOVERABLE_ERROR", "BUDGET_CHANGE",
                             "NEW_EVIDENCE", "SCHEMA_MISMATCH"})
DEFAULT_BUDGET = {"max_steps": 8, "max_step_retries": 1,
                  "max_total_retries": 3, "max_replans": 2,
                  "max_wall_seconds": 30}
PLAN_FIELDS = frozenset({"plan_id", "version", "goal", "steps", "budgets",
                         "completion_condition", "fallback_condition",
                         "authority"})
STEP_FIELDS = frozenset({"step_id", "capability", "depends_on", "router_input",
                         "input", "input_from", "preconditions", "expected_output",
                         "verification", "fallback_capability"})
RESULT_FIELDS = frozenset({"status", "value", "evidence", "provenance",
                           "classification", "confidence"})


class ExecutionError(ValueError):
    """Malformed or unsafe state: fail closed."""


class RecoverableError(RuntimeError):
    """A retry of the same idempotent internal operation may succeed."""


class UnavailableError(RuntimeError):
    """A capability is unavailable and requires fallback or abstention."""


class AuthorityError(ExecutionError):
    """A capability attempted to cross the internal-only boundary."""


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str
                                     ).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _closed_keys(value: Any, allowed: frozenset[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) - allowed:
        raise ExecutionError(f"{label}: malformed or unknown fields")


def _budget(value: Any) -> dict[str, int]:
    _closed_keys(value, frozenset(DEFAULT_BUDGET), "budget")
    if set(value) != set(DEFAULT_BUDGET):
        raise ExecutionError("budget: all limits are required")
    if any(type(v) is not int or v < 0 for v in value.values()):
        raise ExecutionError("budget: limits must be nonnegative integers")
    if not 3 <= value["max_steps"] <= 12 or not 1 <= value["max_wall_seconds"] <= 300:
        raise ExecutionError("budget: step or wall limit outside frozen range")
    if value["max_step_retries"] > 2 or value["max_total_retries"] > 6 or value["max_replans"] > 3:
        raise ExecutionError("budget: retry or replan limit outside frozen range")
    return dict(value)


def validate_plan(plan: Any) -> dict[str, Any]:
    """Validate a complete, dependency-ordered, internal-only plan."""
    _closed_keys(plan, PLAN_FIELDS, "plan")
    if set(plan) != PLAN_FIELDS or plan["authority"] != AUTHORITY:
        raise ExecutionError("plan: missing fields or authority escalation")
    if not isinstance(plan["plan_id"], str) or not plan["plan_id"] or not isinstance(plan["goal"], str) or not plan["goal"].strip():
        raise ExecutionError("plan: id and goal required")
    if type(plan["version"]) is not int or plan["version"] != 1:
        raise ExecutionError("plan: initial version must be 1")
    steps = plan["steps"]
    budget = _budget(plan["budgets"])
    if not isinstance(steps, list) or not 3 <= len(steps) <= budget["max_steps"]:
        raise ExecutionError("plan: requires 3 to max_steps genuine steps")
    ids: set[str] = set()
    for index, step in enumerate(steps):
        _closed_keys(step, STEP_FIELDS, "step")
        if set(step) != STEP_FIELDS:
            raise ExecutionError("step: missing contract fields")
        sid = step["step_id"]
        cap = step["capability"]
        if not isinstance(sid, str) or not sid or sid in ids or cap not in SKILL_IDS:
            raise ExecutionError("step: duplicate id or unknown capability")
        if not isinstance(step["depends_on"], list) or any(d not in ids for d in step["depends_on"]):
            raise ExecutionError("step: dependencies must refer to prior steps")
        if index and not step["depends_on"]:
            raise ExecutionError("step: later steps require a dependency")
        if not isinstance(step["router_input"], dict) or not isinstance(step["input"], dict):
            raise ExecutionError("step: router input and input must be objects")
        if not isinstance(step["input_from"], dict) or any(
                not isinstance(k, str) or v not in step["depends_on"]
                for k, v in step["input_from"].items()):
            raise ExecutionError("step: invalid input_from handoff")
        if index and not step["input_from"]:
            raise ExecutionError("step: dependency must carry an output")
        if not isinstance(step["preconditions"], list) or not all(
                isinstance(p, str) and p for p in step["preconditions"]):
            raise ExecutionError("step: invalid preconditions")
        _closed_keys(step["expected_output"], frozenset({"required_fields", "classification"}), "expected_output")
        if set(step["expected_output"]) != {"required_fields", "classification"} or step["expected_output"]["classification"] not in CLASSIFICATIONS:
            raise ExecutionError("step: invalid expected output")
        if not isinstance(step["expected_output"]["required_fields"], list) or not all(
                isinstance(f, str) and f in RESULT_FIELDS for f in step["expected_output"]["required_fields"]):
            raise ExecutionError("step: invalid required output fields")
        _closed_keys(step["verification"], frozenset({"kind", "required", "parameters"}), "verification")
        if set(step["verification"]) != {"kind", "required", "parameters"} or step["verification"]["kind"] not in {"schema", "evidence", "numeric", "citation"} or step["verification"]["required"] is not True or not isinstance(step["verification"]["parameters"], dict):
            raise ExecutionError("step: explicit verification is required")
        fallback = step["fallback_capability"]
        if fallback is not None and (fallback not in SKILL_IDS or fallback == cap):
            raise ExecutionError("step: invalid fallback capability")
        ids.add(sid)
    _closed_keys(plan["completion_condition"], frozenset({"required_steps", "final_step", "final_verification"}), "completion")
    cc = plan["completion_condition"]
    if set(cc) != {"required_steps", "final_step", "final_verification"} or cc["required_steps"] != [s["step_id"] for s in steps] or cc["final_step"] != steps[-1]["step_id"] or cc["final_verification"] is not True:
        raise ExecutionError("completion: every mandatory step and final verification required")
    _closed_keys(plan["fallback_condition"], frozenset({"on_failure", "on_insufficient_evidence"}), "fallback")
    fc = plan["fallback_condition"]
    if set(fc) != {"on_failure", "on_insufficient_evidence"} or fc["on_failure"] != "SAFE_ABSTAIN" or fc["on_insufficient_evidence"] != "INSUFFICIENT_EVIDENCE":
        raise ExecutionError("fallback: must fail closed")
    return json.loads(json.dumps(plan))


@dataclass(frozen=True)
class Adapter:
    capability: str
    execute: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    internal_only: bool = True
    may_perform_external_action: bool = False

    def __post_init__(self) -> None:
        if self.capability not in SKILL_IDS or not callable(self.execute) or not self.internal_only or self.may_perform_external_action:
            raise ExecutionError("adapter registration denied")


class IntegratedRunner:
    def __init__(self, adapters: Mapping[str, Adapter], *, sandbox_root: Path):
        self.adapters = dict(adapters)
        if any(key != adapter.capability for key, adapter in self.adapters.items()):
            raise ExecutionError("adapter registry mismatch")
        self.sandbox_root = Path(sandbox_root).resolve()
        if not self.sandbox_root.is_dir():
            raise ExecutionError("sandbox root absent")

    def _checkpoint_path(self, scenario_id: str) -> Path:
        if not scenario_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in scenario_id):
            raise ExecutionError("invalid scenario id")
        path = (self.sandbox_root / "checkpoints" / f"{scenario_id}.json").resolve()
        if self.sandbox_root not in path.parents:
            raise ExecutionError("checkpoint escape")
        return path

    @staticmethod
    def _save(path: Path, state: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"state": state, "sha256": _sha(state)}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _load(path: Path, scenario_id: str, plan_sha: str) -> dict[str, Any]:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if set(envelope) != {"state", "sha256"} or _sha(envelope["state"]) != envelope["sha256"]:
            raise ExecutionError("checkpoint integrity failure")
        state = envelope["state"]
        if state.get("scenario_id") != scenario_id or state.get("original_plan_sha256") != plan_sha or state.get("authority") != AUTHORITY:
            raise ExecutionError("checkpoint identity or authority mismatch")
        return state

    @staticmethod
    def _verify(step: dict[str, Any], result: dict[str, Any], payload: dict[str, Any]) -> bool:
        if set(result) - RESULT_FIELDS or any(f not in result for f in step["expected_output"]["required_fields"]):
            return False
        if result.get("status") != "OK" or result.get("classification") != step["expected_output"]["classification"]:
            return False
        if not isinstance(result.get("provenance"), dict) or not result["provenance"].get("source_id"):
            return False
        if result.get("confidence") not in {"HIGH", "MEDIUM", "LOW"}:
            return False
        kind = step["verification"]["kind"]
        if kind == "schema":
            return result.get("value") is not None
        evidence = result.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return False
        if any(not isinstance(e, dict) or not e.get("source_id") or not e.get("chunk_id") or not e.get("citation") or e.get("classification") not in CLASSIFICATIONS or not e.get("freshness") for e in evidence):
            return False
        if kind == "citation" or kind == "evidence":
            return result.get("value") is not None
        if kind == "numeric":
            params = step["verification"]["parameters"]
            if not isinstance(result.get("value"), (int, float)):
                return False
            if params.get("operation") == "add_previous":
                previous, delta = payload.get("previous"), payload.get("delta")
                return (type(previous) in {int, float} and type(delta) in {int, float}
                        and abs(previous + delta - result["value"]) <= float(params.get("tolerance", 0)))
            if params.get("operation") != "add":
                return False
            terms = payload.get("terms")
            return isinstance(terms, list) and terms and all(type(x) in {int, float} for x in terms) and abs(sum(terms) - result["value"]) <= float(params.get("tolerance", 0))
        return False

    def run(self, scenario: dict[str, Any], *, resume: bool = False,
            stop_after_steps: int | None = None) -> dict[str, Any]:
        """Execute or resume; trace contains commitments, not raw step content."""
        if not isinstance(scenario, dict) or set(scenario) != {"scenario_id", "plan", "classification"}:
            raise ExecutionError("scenario malformed or gold field exposed")
        sid = scenario["scenario_id"]
        path = self._checkpoint_path(sid)
        if scenario["classification"] not in CLASSIFICATIONS:
            raise ExecutionError("scenario unclassified")
        plan = validate_plan(scenario["plan"])
        plan_sha = _sha(plan)
        if resume:
            if not path.exists():
                raise ExecutionError("checkpoint absent")
            state = self._load(path, sid, plan_sha)
            if state["terminal"] == "COMPLETE":
                return self._public(state)
            if state["terminal"] != "PARTIAL":
                raise ExecutionError("terminal checkpoint cannot resume")
        else:
            if path.exists():
                raise ExecutionError("existing checkpoint; resume required")
            state = {"scenario_id": sid, "plan_id": plan["plan_id"],
                     "original_plan_sha256": plan_sha, "plan_version": 1,
                     "plan_history": [{"version": 1, "sha256": plan_sha}],
                     "authority": AUTHORITY, "terminal": "PARTIAL",
                     "outputs": {}, "verified": [], "trace": [], "replans": [],
                     "handoffs": [],
                     "retry_count": 0, "step_attempts": {},
                     "budget": plan["budgets"], "started_at": _now(),
                     "elapsed_seconds": 0.0}
            self._save(path, state)
        tick = time.monotonic()
        completed_this_run = 0
        for step in plan["steps"]:
            step_id = step["step_id"]
            if step_id in state["verified"]:
                continue
            if stop_after_steps is not None and completed_this_run >= stop_after_steps:
                break
            if len(state["verified"]) >= plan["budgets"]["max_steps"] or state["elapsed_seconds"] + time.monotonic() - tick > plan["budgets"]["max_wall_seconds"]:
                state["terminal"] = "BUDGET_EXHAUSTED"
                break
            if any(dep not in state["verified"] for dep in step["depends_on"]):
                state["terminal"] = "BLOCKED"
                break
            payload = dict(step["input"])
            for field, producer_id in step["input_from"].items():
                producer = next(s for s in plan["steps"] if s["step_id"] == producer_id)
                upstream = state["outputs"].get(producer_id)
                if not upstream or not self._handoff_valid(producer, step, upstream, scenario["classification"]):
                    state["terminal"] = "ERROR"
                    state["trace"].append({"scenario_id": sid, "plan_id": plan["plan_id"],
                                           "step_id": step_id, "status": "HANDOFF_REJECTED",
                                           "verification_result": "FAIL", "replan_event": None,
                                           "budget_state": self._budget_state(state),
                                           "completion_state": "ERROR"})
                    self._save(path, state)
                    return self._public(state)
                payload[field] = upstream["value"]
                state["handoffs"].append({
                    "producer": producer_id, "consumer": step_id,
                    "producer_capability": producer["capability"],
                    "consumer_capability": step["capability"],
                    "schema": producer["expected_output"],
                    "provenance_commitment": _sha(upstream["provenance"]),
                    "authority": AUTHORITY,
                    "classification": upstream["classification"],
                    "confidence": upstream["confidence"], "status": "VALID"})
            selected = step["capability"]
            fallback_used = False
            while True:
                start = _now()
                outcome = "ERROR"
                result: dict[str, Any] | None = None
                failure = ""
                try:
                    router_input = dict(step["router_input"])
                    router_input["requested_capability"] = selected
                    decision = route_request(router_input)
                    if decision.get("selected_capability") != selected:
                        raise ExecutionError("router/capability selection mismatch")
                    adapter = self.adapters.get(selected)
                    if adapter is None:
                        raise UnavailableError("registered adapter unavailable")
                    result = adapter.execute(payload, {"scenario_id": sid,
                                                       "step_id": step_id,
                                                       "idempotency_key": _sha([sid, step_id]),
                                                       "sandbox_root": str(self.sandbox_root),
                                                       "authority": AUTHORITY,
                                                       "classification": scenario["classification"],
                                                       "router_input": router_input,
                                                       "router_decision": decision})
                    if isinstance(result, dict) and (result.get("requested_action") or
                                                     result.get("may_perform_external_action")):
                        raise AuthorityError("external action request refused")
                    if not isinstance(result, dict) or set(result) - RESULT_FIELDS:
                        raise ExecutionError("invalid capability response")
                    if result.get("status") == "SECURITY_REFUSAL":
                        outcome, failure = "SECURITY_REFUSAL", "AUTHORITY_REQUEST"
                    elif result.get("status") == "INSUFFICIENT_EVIDENCE":
                        outcome, failure = "INSUFFICIENT_EVIDENCE", "MISSING_EVIDENCE"
                    elif result.get("status") == "CONFLICTING_EVIDENCE":
                        outcome, failure = "INSUFFICIENT_EVIDENCE", "RETRIEVAL_CONFLICT"
                    elif not self._verify(step, result, payload):
                        outcome, failure = "VERIFICATION_FAILURE", "VERIFICATION_FAILURE"
                    else:
                        outcome = "VERIFIED"
                except UnavailableError:
                    outcome, failure = "UNAVAILABLE_CAPABILITY", "UNAVAILABLE_CAPABILITY"
                except RecoverableError:
                    outcome, failure = "RECOVERABLE_ERROR", "RECOVERABLE_ERROR"
                except AuthorityError:
                    outcome, failure = "SECURITY_REFUSAL", "AUTHORITY_REQUEST"
                except Exception:
                    outcome, failure = "ERROR", "SCHEMA_MISMATCH"
                attempts = state["step_attempts"].get(step_id, 0) + 1
                state["step_attempts"][step_id] = attempts
                event = {"scenario_id": sid, "plan_id": plan["plan_id"],
                         "plan_version": state["plan_version"], "step_id": step_id,
                         "capability_selected": selected, "input_commitment": _sha(payload),
                         "output_commitment": _sha(result) if result is not None else None,
                         "start_timestamp": start, "end_timestamp": _now(),
                         "status": outcome,
                         "verification_result": "PASS" if outcome == "VERIFIED" else "FAIL",
                         "retry_count": max(0, attempts - 1), "replan_event": None,
                         "budget_state": self._budget_state(state),
                         "completion_state": "PARTIAL"}
                state["trace"].append(event)
                if outcome == "VERIFIED":
                    state["outputs"][step_id] = result
                    state["verified"].append(step_id)
                    completed_this_run += 1
                    self._save(path, state)
                    break
                if outcome == "RECOVERABLE_ERROR" and attempts <= plan["budgets"]["max_step_retries"] and state["retry_count"] < plan["budgets"]["max_total_retries"]:
                    state["retry_count"] += 1
                    self._save(path, state)
                    continue
                if outcome == "SECURITY_REFUSAL":
                    state["terminal"] = "SECURITY_REFUSAL"
                elif outcome == "INSUFFICIENT_EVIDENCE":
                    state["terminal"] = "INSUFFICIENT_EVIDENCE"
                elif failure in REPLAN_TRIGGERS and not fallback_used and step["fallback_capability"] and state["plan_version"] - 1 < plan["budgets"]["max_replans"]:
                    fallback_used = True
                    selected = step["fallback_capability"]
                    state["plan_version"] += 1
                    replan = {"trigger": failure, "step_id": step_id,
                              "from_capability": step["capability"],
                              "to_capability": selected,
                              "original_plan_sha256": plan_sha,
                              "new_version": state["plan_version"]}
                    replan["new_plan_sha256"] = _sha([plan_sha, state["replans"] + [replan]])
                    state["replans"].append(replan)
                    state["plan_history"].append({"version": state["plan_version"],
                                                  "sha256": replan["new_plan_sha256"]})
                    event["replan_event"] = replan
                    self._save(path, state)
                    continue
                elif outcome == "UNAVAILABLE_CAPABILITY":
                    state["terminal"] = "UNAVAILABLE_CAPABILITY"
                elif outcome == "RECOVERABLE_ERROR" and state["retry_count"] >= plan["budgets"]["max_total_retries"]:
                    state["terminal"] = "BUDGET_EXHAUSTED"
                else:
                    state["terminal"] = "ERROR"
                break
            if state["terminal"] != "PARTIAL":
                break
        if len(state["verified"]) == len(plan["steps"]) and all(
                sid_ in state["verified"] for sid_ in plan["completion_condition"]["required_steps"]):
            final_id = plan["completion_condition"]["final_step"]
            if final_id in state["outputs"] and state["trace"][-1]["verification_result"] == "PASS":
                state["terminal"] = "COMPLETE"
        state["elapsed_seconds"] += time.monotonic() - tick
        if state["trace"]:
            state["trace"][-1]["completion_state"] = state["terminal"]
        self._save(path, state)
        return self._public(state)

    @staticmethod
    def _handoff_valid(producer: dict[str, Any], consumer: dict[str, Any],
                       output: dict[str, Any], classification: str) -> bool:
        return (producer["capability"] in SKILL_IDS and consumer["capability"] in SKILL_IDS
                and producer["step_id"] in consumer["depends_on"]
                and output.get("status") == "OK"
                and output.get("classification") == classification
                and isinstance(output.get("provenance"), dict)
                and bool(output["provenance"].get("source_id"))
                and output["provenance"].get("instruction_authority", 0) == 0
                and output.get("confidence") in {"HIGH", "MEDIUM", "LOW"}
                and all(f in output for f in producer["expected_output"]["required_fields"]))

    @staticmethod
    def _budget_state(state: dict[str, Any]) -> dict[str, int]:
        return {"steps_completed": len(state["verified"]),
                "total_retries": state["retry_count"],
                "replans": len(state["replans"])}

    @staticmethod
    def _public(state: dict[str, Any]) -> dict[str, Any]:
        final_id = state["verified"][-1] if state["verified"] else None
        final = state["outputs"].get(final_id, {}) if final_id else {}
        return {"scenario_id": state["scenario_id"], "plan_id": state["plan_id"],
                "original_plan_sha256": state["original_plan_sha256"],
                "plan_history": state["plan_history"], "terminal": state["terminal"],
                "verified_steps": list(state["verified"]),
                "final_answer": final.get("value") if state["terminal"] == "COMPLETE" else None,
                "final_answer_commitment": _sha(final.get("value")) if state["terminal"] == "COMPLETE" else None,
                "trace": list(state["trace"]), "replans": list(state["replans"]),
                "handoffs": list(state["handoffs"]),
                "budget_state": IntegratedRunner._budget_state(state),
                "authority": state["authority"]}
