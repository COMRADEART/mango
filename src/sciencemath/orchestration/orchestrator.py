"""T20.5/T20.17–T20.25/T20.40–T20.48/T20.62–T20.63 the bounded ORCHESTRATOR.

Authority: COORDINATE_INTERNAL_WORK_ONLY. The orchestrator loads a validated
T19 plan, instantiates bounded agents from closed role templates, assigns
READY tasks deterministically, collects structured worker outputs, requests
independent verification, schedules bounded revisions, checkpoints run
state, detects deadlock/livelock, respects global and per-agent budgets,
and defers plan completion to the T19 completion gate (T20.48).

The ORCHESTRATOR never directly executes worker skills, never writes
memory, never grants itself permissions, never marks unverified mandatory
tasks complete, never bypasses verifier rejection, and never spawns beyond
depth 1 (T20.62). Workers submit events; only the orchestrator commits
authoritative run-state transitions (T20.17).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sciencemath.planning.contract import PLAN_COMPLETE
from sciencemath.planning.models import utc_now
from sciencemath.planning.pipeline import Planner
from sciencemath.planning.policy import completion_decision
from sciencemath.orchestration.assignment import (
    assignable_batch, pick_verifier, reassignment_target,
    verification_required_for,
)
from sciencemath.orchestration.checkpoint import RunCheckpointer
from sciencemath.orchestration.contract import (
    MAX_CONCURRENT_VERIFIERS, MAX_CONCURRENT_WORKERS, MAX_SPAWN_DEPTH,
)
from sciencemath.orchestration.events import EventLog, replay_equivalent
from sciencemath.orchestration.handoffs import build_handoff, validate_handoff
from sciencemath.orchestration.locks import (
    LockTable, find_deadlock, wait_for_graph,
)
from sciencemath.orchestration.manifests import (
    build_agent, skill_permitted, SKILL_TO_ROLE,
)
from sciencemath.orchestration.models import (
    AgentSpec, OrchestrationRun, deterministic_id, run_state_hash,
)
from sciencemath.orchestration.recovery import (
    bounded_revision_ok, classify_failure, livelock_detected,
    livelock_fingerprint, recovery_action,
)
from sciencemath.orchestration.verify import (
    escalate_disagreement, verify_artifact,
)
from sciencemath.orchestration.workers import worker_run


@dataclass
class RunResult:
    op: str
    run: OrchestrationRun | None = None
    ok: bool = True
    errors: list = field(default_factory=list)
    blocked_reason: str = ""
    zero_tolerance: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    replay_ok: bool = True
    resume_ok: bool = True
    authority: str = "COORDINATE_INTERNAL_WORK_ONLY"

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "ok": self.ok,
            "errors": self.errors,
            "blocked_reason": self.blocked_reason,
            "zero_tolerance": self.zero_tolerance,
            "metrics": self.metrics,
            "replay_ok": self.replay_ok,
            "resume_ok": self.resume_ok,
            "authority": self.authority,
            "run": self.run.to_dict() if self.run else None,
        }


class Orchestrator:
    """Bounded orchestrator over a validated T19 plan."""

    def __init__(self, planner: Planner | None = None,
                 checkpointer: RunCheckpointer | None = None,
                 max_concurrent_workers: int = MAX_CONCURRENT_WORKERS,
                 max_concurrent_verifiers: int = MAX_CONCURRENT_VERIFIERS):
        self.planner = planner or Planner()
        self.checkpointer = checkpointer
        self.max_concurrent_workers = max_concurrent_workers
        self.max_concurrent_verifiers = max_concurrent_verifiers
        self.log = EventLog()

    # ------------------------------------------------------------------
    # RUN_CREATE
    # ------------------------------------------------------------------
    def create(self, req: dict) -> RunResult:
        now = utc_now(req.get("now"))
        planner_result = self.planner.handle({
            "operation": "PLAN_VALIDATE", "plan": req["plan"],
        })
        if not planner_result.ok:
            return RunResult("RUN_CREATE", None, ok=False,
                             errors=planner_result.errors)
        plan = planner_result.plan
        plan_dict = plan.to_dict()
        run_id = deterministic_id("run_", plan.plan_id, now)
        run = OrchestrationRun(
            run_id=run_id,
            plan_id=plan.plan_id,
            run_version=1,
            status="CREATED",
            started_at=now,
            updated_at=now,
            plan=plan_dict,
        )
        for k, v in (req.get("budget") or {}).items():
            if k in run.budgets:
                run.budgets[k] = v
        # instantiate bounded agents (T20.5/T20.62): orchestrator + planner +
        # two independent verifiers + one worker per needed skill role.
        created = []
        orch = build_agent("ORCHESTRATOR", f"{run_id[:18]}-orch",
                           caller_role="ORCHESTRATOR", now=now,
                           scope="COORDINATE_INTERNAL_WORK_ONLY")
        run.agents.append(orch.to_dict())
        created.append(orch.agent_id)
        planner_agent = build_agent("PLANNER", f"{run_id[:18]}-planner",
                                    caller_role="ORCHESTRATOR", now=now)
        run.agents.append(planner_agent.to_dict())
        created.append(planner_agent.agent_id)
        for i in (1, 2):
            v = build_agent("VERIFIER", f"{run_id[:18]}-verifier{i}",
                            caller_role="ORCHESTRATOR", now=now)
            run.agents.append(v.to_dict())
            created.append(v.agent_id)
        needed_roles = []
        for skill in sorted(SKILL_TO_ROLE):
            role = SKILL_TO_ROLE[skill]
            if role in needed_roles:
                continue
            if not self._plan_needs_skill(plan_dict, skill):
                continue
            needed_roles.append(role)
        cap = int(run.budgets["max_worker_agents"])
        for role in needed_roles[:cap]:
            agent_id = f"{run_id[:18]}-w{len(created)}"
            agent = build_agent(role, agent_id, caller_role="ORCHESTRATOR",
                                now=now)
            run.agents.append(agent.to_dict())
            created.append(agent_id)
        run.agent_budgets = {a["agent_id"]: dict(a.get("budget") or {})
                             for a in run.agents}
        run.provenance = {
            "plan_id": plan.plan_id,
            "plan_version": plan.plan_version,
            "plan_hash": plan.plan_hash,
            "created_at": now,
            "authority": "COORDINATE_INTERNAL_WORK_ONLY",
            "spawn_depth": MAX_SPAWN_DEPTH,
        }
        run.tasks = {t["task_id"]: "PENDING"
                     for t in plan_dict.get("tasks") or []
                     if t.get("status") in ("PENDING", "READY")
                     and not t.get("optional")}
        run.status = "RUNNING"
        self.log.append(run, orch.agent_id, "RUN_CREATED",
                        payload={"plan_id": plan.plan_id,
                                 "agents_created": created}, now=now)
        for aid in created:
            self.log.append(run, orch.agent_id, "AGENT_CREATED",
                            payload={"agent_id": aid}, now=now)
        run.run_hash = run_state_hash(run)
        return RunResult("RUN_CREATE", run)

    @staticmethod
    def _plan_needs_skill(plan: dict, skill: str) -> bool:
        return any(t.get("required_skill") == skill
                   for t in (plan.get("tasks") or []))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _agents(run: OrchestrationRun) -> dict[str, dict]:
        return {a["agent_id"]: a for a in run.agents}

    def _message(self, run: OrchestrationRun, sender: str, recipient: str,
                 message_type: str, task_id: str = "",
                 payload: dict | None = None, now: str = "") -> None:
        """Structured agent-to-agent message with authenticity checks
        (T20.37/T20.38). Unknown senders/recipients are rejected."""
        agents = self._agents(run)
        if sender not in agents or recipient not in agents:
            run.counters["identity_spoof_acceptance"] += 1
            self.log.append(run, "ORCHESTRATOR", "MESSAGE_REJECTED",
                            task_id=task_id,
                            payload={"sender": sender,
                                     "recipient": recipient}, now=now)
            return
        if int(run.budgets.get("consumed_messages", 0)) >= \
                int(run.budgets.get("max_messages", 10 ** 9)):
            self.log.append(run, "ORCHESTRATOR", "BUDGET_EXHAUSTED",
                            payload={"budget": "messages"}, now=now)
            return
        run.budgets["consumed_messages"] = \
            int(run.budgets.get("consumed_messages", 0)) + 1
        run.messages.append({
            "message_id": deterministic_id("msg_", run.run_id, sender,
                                           recipient, task_id, now,
                                           len(run.messages)),
            "run_id": run.run_id,
            "sender": sender,
            "recipient": recipient,
            "task_id": task_id,
            "message_type": message_type,
            "payload": dict(payload or {}),
            "timestamp": now,
        })

    # ------------------------------------------------------------------
    # RUN_STEP
    # ------------------------------------------------------------------
    def step(self, req: dict) -> RunResult:
        run = req["run"] if isinstance(req.get("run"), OrchestrationRun) \
            else OrchestrationRun.from_dict(req.get("run") or {})
        case = req.get("case") or {}
        now = utc_now(req.get("now"))
        run.steps += 1

        if run.status in ("COMPLETE", "ABORTED", "FAILED", "BLOCKED"):
            return RunResult("RUN_STEP", run, ok=False,
                             blocked_reason=f"run already {run.status}")

        # livelock guard (T20.29): identical semantic fingerprints repeated
        # with no progress never spin.
        if livelock_detected(run.to_dict()):
            run.counters["unresolved_livelock"] += 1
            run.status = "BLOCKED"
            run.blockers.append({"reason": "livelock_detected"})
            self.log.append(run, "ORCHESTRATOR", "LIVELOCK_DETECTED", now=now)
            self.log.append(run, "ORCHESTRATOR", "RUN_BLOCKED", now=now)
            run.run_hash = run_state_hash(run)
            return RunResult("RUN_STEP", run, ok=False,
                             blocked_reason="livelock")

        lock_state = LockTable()
        lock_state.load_snapshot(run.locks)
        batch, deferred = assignable_batch(
            run.plan, self._agents(run), run.to_dict(), lock_state.held,
            self.max_concurrent_workers)

        deadlock_edges = wait_for_graph(lock_state)
        cycle = find_deadlock(deadlock_edges)
        if cycle:
            run.counters["accepted_deadlock"] += 1
            run.status = "BLOCKED"
            run.blockers.append({"reason": "deadlock", "cycle": sorted(cycle)})
            self.log.append(run, "ORCHESTRATOR", "DEADLOCK_DETECTED",
                            payload={"cycle": sorted(cycle)}, now=now)
            self.log.append(run, "ORCHESTRATOR", "RUN_BLOCKED", now=now)
            run.run_hash = run_state_hash(run)
            return RunResult("RUN_STEP", run, ok=False,
                             blocked_reason="deadlock")

        verifier_used: list[str] = []
        for item in batch:
            task, agent = item["task"], item["agent"]
            self._assign(run, task, agent, now, case)
            if run.tasks.get(task["task_id"]) != "RUNNING":
                continue   # handoff rejected; task BLOCKED
            result = self._execute(run, task, agent, case, now)
            self._process_result(run, task, agent, result, case, now,
                                 verifier_used)
            lock_state.release(task["task_id"], item["resources"])
            if run.status in ("BLOCKED", "FAILED", "COMPLETE", "ABORTED"):
                break
        for d in deferred:
            reason = d["reason"]
            tid = d["task"]["task_id"]
            if reason in ("no_compatible_agent", "agent_budget_exhausted"):
                if run.tasks.get(tid) == "PENDING":
                    run.tasks[tid] = "BLOCKED"
                    run.blockers.append({"task_id": tid, "reason": reason})
                    self.log.append(run, "ORCHESTRATOR", "TASK_BLOCKED",
                                    task_id=tid, payload={"reason": reason},
                                    now=now)
            elif reason.startswith("resource_conflict"):
                # serialized for a later round (T20.26) — still PENDING
                self.log.append(run, "ORCHESTRATOR", "TASK_BLOCKED",
                                task_id=tid,
                                payload={"reason": reason,
                                         "serialized": True}, now=now)
        # drop locks for tasks that are no longer in flight
        for tid, st in list(run.tasks.items()):
            if st not in ("ASSIGNED", "RUNNING", "REVISION_REQUESTED"):
                lock_state.release_all(tid)
        run.locks = lock_state.snapshot()
        run.fingerprints = list(run.fingerprints) + [
            livelock_fingerprint(run.to_dict())]

        run.updated_at = now
        run.run_hash = run_state_hash(run)
        if self.checkpointer:
            self.checkpointer.save(run, lock_state.snapshot(),
                                   reason="step", now=now)
            self.log.append(run, "ORCHESTRATOR", "CHECKPOINT_SAVED", now=now)
            run.run_hash = run_state_hash(run)

        self._update_run_status(run, now)
        replay_ok = replay_equivalent(run)
        if not replay_ok:
            run.counters["fabricated_tool_result"] += 1
        return RunResult(
            "RUN_STEP", run,
            ok=run.status not in ("BLOCKED", "FAILED"),
            blocked_reason=(run.blockers[-1].get("reason", "")
                            if run.blockers else ""),
            replay_ok=replay_ok,
            zero_tolerance=dict(run.counters),
            metrics=self._metrics(run),
        )

    def _update_run_status(self, run: OrchestrationRun, now: str) -> None:
        """Completion gate (T20.48): COMPLETE only via the T19 planner gate
        plus independent verification of every mandatory artifact."""
        statuses = set(run.tasks.values())
        if run.status in ("BLOCKED", "FAILED", "ABORTED", "NEEDS_REPLAN",
                          "COMPLETE"):
            return
        done, evidence = completion_decision(self.planner._coerce_plan(
            run.plan))
        mandatory_pending = [
            a for a in run.artifacts
            if a.get("verification_required")
            and a.get("verification_status") not in ("PASSED", "NOT_REQUIRED")
        ]
        plan_tasks = {t["task_id"]: t for t in (run.plan.get("tasks") or [])}
        all_done = plan_tasks and all(
            t.get("status") == "SUCCEEDED"
            for t in plan_tasks.values())
        if done == PLAN_COMPLETE and all_done and not run.blockers:
            # every mandatory verification must have passed (T20.42)
            if mandatory_pending:
                run.counters["self_verified_mandatory_acceptance"] += 1
                run.status = "BLOCKED"
                run.blockers.append({"reason": "unverified_mandatory_artifact"})
                self.log.append(run, "ORCHESTRATOR", "RUN_BLOCKED", now=now)
                return
            if run.status != "COMPLETE":
                run.status = "COMPLETE"
                run.completion_state = {"evidence": evidence,
                                        "verified": True}
                self.log.append(run, "ORCHESTRATOR", "RUN_COMPLETED",
                                payload={"evidence": evidence[:8]}, now=now)
            return
        if statuses and statuses <= {"SUCCEEDED", "BLOCKED"} and run.blockers:
            run.status = "BLOCKED"
            self.log.append(run, "ORCHESTRATOR", "RUN_BLOCKED", now=now)
        elif any(st in ("ASSIGNED", "RUNNING", "REVISION_REQUESTED")
                 for st in statuses):
            run.status = "RUNNING"
        elif statuses and statuses <= {"PENDING", "BLOCKED"} and \
                any(st == "BLOCKED" for st in statuses):
            run.status = "BLOCKED"
            self.log.append(run, "ORCHESTRATOR", "RUN_BLOCKED", now=now)
        else:
            run.status = "WAITING"

    @staticmethod
    def _metrics(run: OrchestrationRun) -> dict:
        return {
            "tasks_total": len(run.tasks),
            "tasks_succeeded": sum(
                1 for s in run.tasks.values() if s == "SUCCEEDED"),
            "tasks_blocked": sum(
                1 for s in run.tasks.values() if s == "BLOCKED"),
            "agents": len(run.agents),
            "worker_agents": sum(
                1 for a in run.agents
                if a["role"] not in ("ORCHESTRATOR", "PLANNER", "VERIFIER")),
            "verifications": len(run.verifications),
            "revisions": len(run.revisions),
            "messages": len(run.messages),
            "steps": run.steps,
        }

    # -- assignment -----------------------------------------------------
    def _assign(self, run: OrchestrationRun, task: dict, agent: dict,
                now: str, case: dict) -> None:
        tid = task["task_id"]
        run.tasks[tid] = "ASSIGNED"
        run.assignments = list(run.assignments) + [{
            "task_id": tid, "agent_id": agent["agent_id"],
            "status": "ASSIGNED",
        }]
        orch_agent = next((a for a in run.agents
                           if a["role"] == "ORCHESTRATOR"), {})
        handoff = build_handoff(run.to_dict(), task,
                                {"agent_id": orch_agent.get("agent_id"),
                                 "role": "ORCHESTRATOR"},
                                agent, now=now)
        errs = validate_handoff(run.to_dict(), handoff, task,
                                self._agents(run))
        if errs:
            run.tasks[tid] = "BLOCKED"
            run.blockers.append({"task_id": tid, "reason": "handoff_invalid",
                                 "errors": errs})
            self.log.append(run, "ORCHESTRATOR", "HANDOFF_REJECTED",
                            task_id=tid, payload={"errors": errs}, now=now)
            return
        run.handoffs = list(run.handoffs) + [handoff.to_dict()]
        run.budgets["consumed_handoffs"] = \
            int(run.budgets.get("consumed_handoffs", 0)) + 1
        self.log.append(run, orch_agent.get("agent_id"), "TASK_ASSIGNED",
                        task_id=tid,
                        payload={"agent_id": agent["agent_id"],
                                 "handoff_id": handoff.handoff_id},
                        provenance=handoff.provenance, now=now)
        run.tasks[tid] = "RUNNING"
        self.log.append(run, orch_agent.get("agent_id"), "TASK_STARTED",
                        task_id=tid,
                        payload={"agent_id": agent["agent_id"]}, now=now)
        self._message(run, orch_agent.get("agent_id"), agent["agent_id"],
                      "ASSIGN", task_id=tid,
                      payload={"objective": task.get("objective")
                               or task.get("title") or ""}, now=now)

    # -- execution ------------------------------------------------------
    def _execute(self, run: OrchestrationRun, task: dict, agent: dict,
                 case: dict, now: str) -> dict:
        """Run one bounded worker via the fixture world (T20.50)."""
        skill = task.get("required_skill") or ""
        if not skill_permitted(AgentSpec.from_dict(agent), skill):
            # T20.7: workers cannot run out-of-role skills.
            run.counters["unauthorized_cross_role_execution"] += 1
            return {"task_id": task["task_id"],
                    "agent_id": agent["agent_id"],
                    "result_status": "FAILED",
                    "errors": [f"capability_mismatch:{skill}"],
                    "failure_class": "CAPABILITY_MISMATCH",
                    "facts": [], "artifacts": [], "claim": "",
                    "payload_flags": []}
        return worker_run(task, agent, case, now=now)

    # -- result processing ----------------------------------------------
    def _process_result(self, run: OrchestrationRun, task: dict,
                        agent: dict, result: dict, case: dict, now: str,
                        verifier_used: list) -> None:
        tid = task["task_id"]
        self.log.append(run, agent["agent_id"], "TASK_RESULT_SUBMITTED",
                        task_id=tid,
                        payload={"result_status": result.get("result_status"),
                                 "failure_class": result.get("failure_class"),
                                 "behavior": result.get("behavior"),
                                 "claim": bool(result.get("claim"))},
                        now=now)
        run.observations = list(run.observations) + [{
            "task_id": tid, "agent_id": agent["agent_id"],
            "result_status": result.get("result_status"),
            "facts": list(result.get("facts") or []),
            "errors": list(result.get("errors") or []),
            "failure_class": result.get("failure_class"),
            "instruction_authority": 0,
        }]
        # Adversarial worker claims are DATA (T20.64). Recorded, never obeyed.
        claim = result.get("claim") or ""
        if claim:
            self.log.append(run, agent["agent_id"], "MESSAGE_REJECTED",
                            task_id=tid,
                            payload={"reason": "adversarial_claim_as_data",
                                     "claim": claim}, now=now)
        if result.get("result_status") != "SUCCEEDED":
            self._handle_failure(run, task, agent, result, case, now)
            return
        ref = self._register_artifact(run, task, agent, result, now)
        run.tasks[tid] = "SUCCEEDED"
        if ref.get("verification_required"):
            self._verify(run, task, agent, ref, result, case, now,
                         verifier_used)
        else:
            self._set_verification_status(run, ref["artifact_id"],
                                          "NOT_REQUIRED")
            self._complete(run, task, agent, now)

    def _register_artifact(self, run: OrchestrationRun, task: dict,
                           agent: dict, result: dict, now: str) -> dict:
        art = (result.get("artifacts") or [{}])[0]
        ref = {
            "artifact_id": art.get("artifact_id") or deterministic_id(
                "art_", task["task_id"], agent["agent_id"], now),
            "producer_agent_id": agent["agent_id"],
            "task_id": task["task_id"],
            "artifact_type": task.get("task_type") or "generic",
            "content_reference": art.get("content_reference") or "",
            "content_hash": art.get("content_hash") or "",
            "provenance": {"plan_id": run.plan_id,
                           "plan_version": (run.plan or {}).get(
                               "plan_version"),
                           "agent_role": agent["role"],
                           "created_at": now},
            "created_at": now,
            "status": "REGISTERED",
            "verification_required": verification_required_for(task),
            "verification_status": "PENDING",
            "sensitivity": "NORMAL",
        }
        run.artifacts = list(run.artifacts) + [ref]
        run.budgets["consumed_artifacts"] = \
            int(run.budgets.get("consumed_artifacts", 0)) + 1
        self.log.append(run, agent["agent_id"], "ARTIFACT_REGISTERED",
                        task_id=task["task_id"],
                        payload={"artifact_id": ref["artifact_id"]}, now=now)
        return ref

    @staticmethod
    def _set_verification_status(run: OrchestrationRun, artifact_id: str,
                                 status: str) -> None:
        for a in run.artifacts:
            if a["artifact_id"] == artifact_id:
                a["verification_status"] = status
                return

    # -- verification -----------------------------------------------------
    def _verify(self, run: OrchestrationRun, task: dict, agent: dict,
                ref: dict, result: dict, case: dict, now: str,
                verifier_used: list) -> None:
        tid = task["task_id"]
        producer = agent["agent_id"]
        v = pick_verifier(self._agents(run), producer, verifier_used)
        if v is None:
            run.blockers.append({"task_id": tid,
                                 "reason": "verifier_unavailable"})
            run.tasks[tid] = "BLOCKED"
            self.log.append(run, "ORCHESTRATOR", "TASK_BLOCKED",
                            task_id=tid,
                            payload={"reason": "verifier_unavailable"},
                            now=now)
            return
        verifier_used.append(v["agent_id"])
        self.log.append(run, "ORCHESTRATOR", "VERIFICATION_REQUESTED",
                        task_id=tid,
                        payload={"verifier": v["agent_id"],
                                 "producer": producer}, now=now)
        decision = verify_artifact(
            task, ref, result, v["agent_id"],
            dependency_facts=[str(x) for x in task.get("success_criteria")
                              or []])
        vid = deterministic_id("ver_", tid, v["agent_id"], now)
        record = {
            "verification_id": vid, "task_id": tid,
            "artifact_id": ref["artifact_id"],
            "verifier_agent_id": v["agent_id"],
            "producer_agent_id": producer,
            "decision": decision["decision"],
            "reasons": decision["reasons"], "escalation": "",
        }
        if decision["decision"] == "PASS":
            run.verifications = list(run.verifications) + [record]
            self._set_verification_status(run, ref["artifact_id"], "PASSED")
            self.log.append(run, v["agent_id"], "VERIFICATION_PASSED",
                            task_id=tid,
                            payload={"verification_id": vid,
                                     "artifact_id": ref["artifact_id"]},
                            now=now)
            self._complete(run, task, agent, now)
            return
        if decision["decision"] == "NEEDS_REVISION":
            self._request_revision(run, task, agent, decision["reasons"],
                                   now)
            return
        # FAIL / INSUFFICIENT_EVIDENCE / POLICY_BLOCK: second independent
        # verifier, then deterministic escalation (T20.43).
        run.verifications = list(run.verifications) + [record]
        self._set_verification_status(run, ref["artifact_id"], "FAILED")
        self.log.append(run, v["agent_id"], "VERIFICATION_FAILED",
                        task_id=tid,
                        payload={"verification_id": vid,
                                 "decision": decision["decision"],
                                 "reasons": decision["reasons"][:3]},
                        now=now)
        v2 = pick_verifier(self._agents(run), producer, verifier_used)
        if v2 is not None:
            d2 = verify_artifact(
                task, ref, result, v2["agent_id"],
                dependency_facts=[str(x) for x in task.get("success_criteria")
                                  or []])
            if d2["decision"] != decision["decision"]:
                esc = escalate_disagreement(task, ref, decision, d2)
                run.verifications[-1] = {
                    **record,
                    "verifier_agent_id": "deterministic_check",
                    "decision": esc["decision"],
                    "reasons": esc["reasons"],
                    "escalation": "deterministic_check",
                }
                self._set_verification_status(
                    run, ref["artifact_id"],
                    "PASSED" if esc["decision"] == "PASS" else "FAILED")
                self.log.append(run, "ORCHESTRATOR",
                                "VERIFICATION_REQUESTED", task_id=tid,
                                payload={"escalation": "deterministic_check"},
                                now=now)
                if esc["decision"] == "PASS":
                    self._complete(run, task, agent, now)
                    return
        self._handle_failure(run, task, agent,
                             {"task_id": tid, "result_status": "FAILED",
                              "errors": list(
                                  (run.verifications[-1]["reasons"] or [])),
                              "failure_class": "VERIFICATION_FAIL",
                              "facts": [], "artifacts": []},
                             case, now)

    def _request_revision(self, run: OrchestrationRun, task: dict,
                          agent: dict, reasons: list, now: str) -> None:
        """Bounded revision (T20.31): max 2 per task, global cap enforced."""
        tid = task["task_id"]
        if not bounded_revision_ok(run.to_dict(), tid):
            run.blockers.append({"task_id": tid,
                                 "reason": "revision_budget_exhausted"})
            run.tasks[tid] = "BLOCKED"
            self.log.append(run, "ORCHESTRATOR", "TASK_BLOCKED", task_id=tid,
                            payload={"reason": "revision_budget_exhausted"},
                            now=now)
            return
        run.revisions = list(run.revisions) + [{
            "task_id": tid,
            "revision_id": deterministic_id("rev_", run.run_id, tid, now,
                                            len(run.revisions)),
            "requested_by": "VERIFIER",
            "reasons": list(reasons or []),
        }]
        run.budgets["consumed_revisions"] = \
            int(run.budgets.get("consumed_revisions", 0)) + 1
        self.log.append(run, "ORCHESTRATOR", "REVISION_REQUESTED",
                        task_id=tid,
                        payload={"agent_id": agent["agent_id"],
                                 "reasons": list(reasons or [])[:3]}, now=now)
        run.tasks[tid] = "REVISION_REQUESTED"
        # one bounded revision re-run by the same agent, then re-verified
        retry = worker_run(task, agent, {"worker_behavior": {}}, now=now)
        if retry.get("result_status") == "SUCCEEDED":
            ref = self._register_artifact(run, task, agent, retry,
                                          now + "-r")
            run.tasks[tid] = "SUCCEEDED"
            if ref["verification_required"]:
                v = pick_verifier(self._agents(run), agent["agent_id"],
                                  [agent["agent_id"]])
                if v is not None:
                    d2 = verify_artifact(
                        task, ref, retry, v["agent_id"],
                        dependency_facts=[str(x) for x in
                                          task.get("success_criteria") or []])
                    if d2["decision"] == "PASS":
                        self._set_verification_status(
                            run, ref["artifact_id"], "PASSED")
                        self.log.append(run, v["agent_id"],
                                        "VERIFICATION_PASSED", task_id=tid,
                                        payload={"artifact_id":
                                                 ref["artifact_id"]},
                                        now=now)
                        self._complete(run, task, agent, now)
                        return
            run.tasks[tid] = "BLOCKED"
            run.blockers.append({"task_id": tid,
                                 "reason": "revision_still_unverified"})
        else:
            run.tasks[tid] = "BLOCKED"
            run.blockers.append({"task_id": tid, "reason": "revision_failed"})

    # -- failure handling -------------------------------------------------
    def _handle_failure(self, run: OrchestrationRun, task: dict,
                        agent: dict, result: dict, case: dict,
                        now: str) -> None:
        tid = task["task_id"]
        fclass = classify_failure(result)
        self.log.append(run, agent["agent_id"], "AGENT_FAILED", task_id=tid,
                        payload={"failure_class": fclass}, now=now)
        run.tasks[tid] = "FAILED"
        action = recovery_action(fclass)
        if action in ("reassign_same_role_or_block", "retry_or_reassign",
                      "reassign_or_recover"):
            target = reassignment_target(self._agents(run),
                                         task.get("required_skill") or "",
                                         {agent["agent_id"]})
            if target is not None:
                run.tasks[tid] = "PENDING"
                run.assignments = list(run.assignments) + [{
                    "task_id": tid, "agent_id": target["agent_id"],
                    "status": "REASSIGNED",
                }]
                self.log.append(run, "ORCHESTRATOR", "TASK_REASSIGNED",
                                task_id=tid,
                                payload={"from_agent": agent["agent_id"],
                                         "to_agent": target["agent_id"],
                                         "reason": fclass}, now=now)
                return
            self._request_replan(run, fclass, tid, now)
            return
        if action in ("revise_or_block", "bounded_revision",
                      "recover_dependency", "serialize_retry"):
            if bounded_revision_ok(run.to_dict(), tid):
                self._request_revision(run, task, agent,
                                       list(result.get("errors") or []), now)
            else:
                self._request_replan(run, fclass, tid, now)
            return
        if action == "replan_or_block":
            self._request_replan(run, fclass, tid, now)
            return
        # block
        run.blockers.append({"task_id": tid, "reason": fclass})
        self.log.append(run, "ORCHESTRATOR", "TASK_BLOCKED", task_id=tid,
                        payload={"reason": fclass}, now=now)
        if fclass == "BUDGET_EXCEEDED":
            run.status = "BLOCKED"
            self.log.append(run, "ORCHESTRATOR", "RUN_BLOCKED", now=now)

    def _request_replan(self, run: OrchestrationRun, fclass: str,
                        task_id: str, now: str) -> None:
        self.log.append(run, "ORCHESTRATOR", "PLAN_REPLAN_REQUESTED",
                        task_id=task_id,
                        payload={"replan_trigger": fclass}, now=now)
        run.status = "NEEDS_REPLAN"
        run.replan_state = {"trigger": fclass, "task_id": task_id}
        run.blockers.append({"task_id": task_id,
                             "reason": f"replan:{fclass}"})

    # -- completion ---------------------------------------------------------
    def _complete(self, run: OrchestrationRun, task: dict, agent: dict,
                  now: str) -> None:
        """Push the verified observation through the T19 planner
        (authoritative plan state), then mark the task (T20.45/T20.48)."""
        tid = task["task_id"]
        obs = {
            "task_id": tid,
            "result_status": "SUCCEEDED",
            "facts": [f"verified:{c}" for c in
                      (task.get("success_criteria") or [])],
            "artifacts": [a["artifact_id"] for a in run.artifacts
                          if a.get("task_id") == tid][:1],
            "errors": [],
            "confidence": "HIGH",
        }
        pr = self.planner.handle({"operation": "PLAN_OBSERVE",
                                  "plan": run.plan, "observation": obs,
                                  "now": now})
        if pr.plan is not None:
            run.plan = pr.plan.to_dict()
        run.tasks[tid] = "SUCCEEDED"
        self.log.append(run, "ORCHESTRATOR", "TASK_COMPLETED", task_id=tid,
                        payload={"agent_id": agent["agent_id"]}, now=now)

    # ------------------------------------------------------------------
    # RUN_REPLAN / RUN_CHECKPOINT / RUN_RESUME / RUN_ABORT
    # ------------------------------------------------------------------
    def replan(self, req: dict) -> RunResult:
        run = req["run"] if isinstance(req.get("run"), OrchestrationRun) \
            else OrchestrationRun.from_dict(req.get("run") or {})
        now = utc_now(req.get("now"))
        if int(run.budgets.get("consumed_replans", 0)) >= \
                int(run.budgets.get("max_replans", 5)):
            run.counters["unbounded_retry"] += 1
            run.status = "BLOCKED"
            self.log.append(run, "ORCHESTRATOR", "BUDGET_EXHAUSTED",
                            payload={"budget": "replans"}, now=now)
            run.run_hash = run_state_hash(run)
            return RunResult("RUN_REPLAN", run, ok=False,
                             errors=["replan budget exhausted"])
        pr = self.planner.handle({
            "operation": "PLAN_REPLAN", "plan": run.plan,
            "replan_trigger": req.get("replan_trigger") or "",
            "observation": req.get("observation") or {}, "now": now,
        })
        run.budgets["consumed_replans"] = \
            int(run.budgets.get("consumed_replans", 0)) + 1
        if pr.ok and pr.plan is not None:
            before = {t.get("task_id") for t in (run.plan.get("tasks") or [])
                      if t.get("status") == "SUCCEEDED"}
            run.plan = pr.plan.to_dict()
            after = {t.get("task_id") for t in (run.plan.get("tasks") or [])
                     if t.get("status") == "SUCCEEDED"}
            lost = before - after
            if lost:
                # T20.46: unrelated completed work loss must be 0.
                run.counters["silent_completed_work_loss"] += 1
            self.log.append(run, "ORCHESTRATOR", "PLAN_REVISED",
                            payload={"replan_trigger":
                                     req.get("replan_trigger") or "",
                                     "plan_version": pr.plan.plan_version},
                            now=now)
            for t in (run.plan.get("tasks") or []):
                tid = t["task_id"]
                if t.get("status") == "SUCCEEDED":
                    run.tasks[tid] = "SUCCEEDED"
                elif tid in run.tasks and run.tasks[tid] != "SUCCEEDED":
                    run.tasks[tid] = "PENDING"
            run.status = "RUNNING"
        else:
            run.status = "BLOCKED"
            run.blockers.append({"reason": "replan_refused"})
            self.log.append(run, "ORCHESTRATOR", "RUN_BLOCKED",
                            payload={"reason": "replan_refused"}, now=now)
        run.run_hash = run_state_hash(run)
        return RunResult("RUN_REPLAN", run, ok=pr.ok)

    def checkpoint(self, req: dict) -> RunResult:
        run = req["run"] if isinstance(req.get("run"), OrchestrationRun) \
            else OrchestrationRun.from_dict(req.get("run") or {})
        now = utc_now(req.get("now"))
        if not self.checkpointer:
            return RunResult("RUN_CHECKPOINT", run, ok=False,
                             errors=["no checkpointer configured"])
        name = self.checkpointer.save(run, run.locks,
                                      reason=req.get("reason") or "manual",
                                      now=now)
        self.log.append(run, "ORCHESTRATOR", "CHECKPOINT_SAVED", now=now)
        run.run_hash = run_state_hash(run)
        return RunResult("RUN_CHECKPOINT", run,
                         metrics={"checkpoint": name})

    def resume(self, req: dict) -> RunResult:
        run_id = req.get("run_id")
        if not self.checkpointer:
            return RunResult("RUN_RESUME", None, ok=False,
                             errors=["no checkpointer configured"])
        loaded = self.checkpointer.load(run_id)
        if loaded is None:
            return RunResult("RUN_RESUME", None, ok=False,
                             errors=["checkpoint_missing"])
        run, locks = loaded
        self.log = EventLog()
        for ev in run.events:
            self.log.events.append(ev)
        run.locks = locks or {"held": {}, "waiting": {}}
        run.run_hash = run_state_hash(run)
        return RunResult("RUN_RESUME", run, resume_ok=True)

    def abort(self, req: dict) -> RunResult:
        run = req["run"] if isinstance(req.get("run"), OrchestrationRun) \
            else OrchestrationRun.from_dict(req.get("run") or {})
        now = utc_now(req.get("now"))
        run.status = "ABORTED"
        self.log.append(run, "ORCHESTRATOR", "RUN_ABORTED", now=now)
        run.run_hash = run_state_hash(run)
        return RunResult("RUN_ABORT", run)


def completion_ok(run: OrchestrationRun, planner: Planner | None = None
                  ) -> bool:
    """T20.48: COMPLETE only with the T19 plan gate + verification + no
    blockers. false_complete must stay 0."""
    if run.status != "COMPLETE" or run.blockers:
        return False
    done, _ = completion_decision((planner or Planner())._coerce_plan(
        run.plan))
    if done != PLAN_COMPLETE:
        return False
    return all(a.get("verification_status") in ("PASSED", "NOT_REQUIRED")
               for a in run.artifacts if a.get("verification_required"))