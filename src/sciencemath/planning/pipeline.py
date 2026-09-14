"""T19 planner pipeline: propose-only long-horizon planning."""
from __future__ import annotations

from dataclasses import dataclass, field

from sciencemath.executive.skills import SkillRegistry
from sciencemath.planning.contract import (
    AUTHORITY_PROPOSE_ONLY, COST_FREE, COST_PAID, PLAN_ABORT,
    PLAN_ADD_DEPENDENCY, PLAN_BLOCK, PLAN_BUDGET_EXCEEDED, PLAN_CHECKPOINT,
    PLAN_COMPLETE, PLAN_CREATE, PLAN_DECOMPOSE, PLAN_INSUFFICIENT_CAPABILITY,
    PLAN_NEEDS_CLARIFICATION, PLAN_OBSERVE, PLAN_OPS, PLAN_POLICY_BLOCKED,
    PLAN_RECOVER, PLAN_REPLAN, PLAN_RESUME, PLAN_SEQUENCE, PLAN_VALIDATE,
    SCHEMA_VERSION,
)
from sciencemath.planning.decompose import (
    assumptions_from, decompose, parse_goal_bundle,
)
from sciencemath.planning.graph import (
    add_dependency, graph_metadata, ready_tasks, task_list, validate_graph,
)
from sciencemath.planning.instrument import SideEffectLog, refuse_execution
from sciencemath.planning.models import (
    Observation, Plan, Task, default_budget, new_obs_id, new_plan_id,
    snapshot_best, utc_now,
)
from sciencemath.planning.policy import (
    NON_PROGRESS_LIMIT, apply_observation, can_complete, classify_failure,
    completion_decision, infer_trigger, invalidate_downstream, loop_detected,
    maybe_checkpoint, note_history, preserve_unrelated, progress_signal,
    should_replan, snapshot_progress, verification_missing,
)
from sciencemath.planning.safety import (
    classify_goal_policy, data_not_policy, insufficient_capability,
    is_injection, needs_clarification, paid_task, skill_allowed,
    skill_known_state,
)
from sciencemath.planning.serialize import dumps, loads, plan_hash


@dataclass
class PlanResult:
    op: str
    plan: Plan | None = None
    ok: bool = True
    errors: list = field(default_factory=list)
    blocked_reason: str = ""
    clarification: str = ""
    gate: str | None = None
    side_effects: dict = field(default_factory=dict)
    resume_ok: bool = True
    fabricated_skill: int = 0
    fabricated_tool_result: int = 0
    prompt_injection_success: int = 0
    unauthorized_action: int = 0
    cycle_accepted: int = 0
    false_complete: int = 0
    paid_service_bypass: int = 0
    policy_override: int = 0
    silent_constraint_drop: int = 0
    silent_completed_work_loss: int = 0
    execution_authority: str = AUTHORITY_PROPOSE_ONLY

    def to_dict(self) -> dict:
        d = {
            "op": self.op,
            "ok": self.ok,
            "errors": self.errors,
            "blocked_reason": self.blocked_reason,
            "clarification": self.clarification,
            "gate": self.gate,
            "side_effects": self.side_effects,
            "resume_ok": self.resume_ok,
            "fabricated_skill": self.fabricated_skill,
            "fabricated_tool_result": self.fabricated_tool_result,
            "prompt_injection_success": self.prompt_injection_success,
            "unauthorized_action": self.unauthorized_action,
            "cycle_accepted": self.cycle_accepted,
            "false_complete": self.false_complete,
            "paid_service_bypass": self.paid_service_bypass,
            "policy_override": self.policy_override,
            "silent_constraint_drop": self.silent_constraint_drop,
            "silent_completed_work_loss": self.silent_completed_work_loss,
            "execution_authority": AUTHORITY_PROPOSE_ONLY,
            "plan": self.plan.to_dict() if self.plan else None,
        }
        return d


def _as_req(request) -> dict:
    if isinstance(request, dict):
        return dict(request)
    return dict(request)


class Planner:
    """Deterministic propose-only planner. Never executes tools."""

    def __init__(self, registry: SkillRegistry | None = None):
        self.reg = registry or SkillRegistry()
        self.log = SideEffectLog()

    def execute(self, *args, **kwargs):
        refuse_execution(self.log, "unauthorized")

    def handle(self, request: dict) -> PlanResult:
        req = _as_req(request)
        op = req.get("operation") or PLAN_CREATE
        if op not in PLAN_OPS:
            op = PLAN_CREATE
        if op == PLAN_RESUME:
            return self.resume(req)
        if op == PLAN_VALIDATE and req.get("plan"):
            plan = self._coerce_plan(req["plan"])
            return self._validate_result(plan)
        if op == PLAN_CHECKPOINT:
            plan = self._coerce_plan(req["plan"])
            maybe_checkpoint(plan, req.get("now"))
            plan.plan_hash = plan_hash(plan)
            return PlanResult(PLAN_CHECKPOINT, plan, side_effects=self.log.to_dict())
        if op == PLAN_ADD_DEPENDENCY:
            plan = self._coerce_plan(req["plan"])
            err = add_dependency(plan, req.get("from"), req.get("to"))
            if err:
                return PlanResult(PLAN_ADD_DEPENDENCY, plan, ok=False,
                                  errors=err, cycle_accepted=0,
                                  side_effects=self.log.to_dict())
            return PlanResult(PLAN_ADD_DEPENDENCY, plan,
                              side_effects=self.log.to_dict())
        if op == PLAN_OBSERVE:
            return self.observe(req)
        if op == PLAN_REPLAN:
            return self.replan(req)
        if op == PLAN_COMPLETE:
            plan = self._coerce_plan(req["plan"])
            return self._try_complete(plan)
        if op == PLAN_ABORT:
            plan = self._coerce_plan(req.get("plan") or {})
            plan.status = "ABORTED"
            return PlanResult(PLAN_ABORT, plan, side_effects=self.log.to_dict())
        if op == PLAN_SEQUENCE:
            plan = self._coerce_plan(req["plan"])
            plan.graph_meta = graph_metadata(plan)
            return PlanResult(PLAN_SEQUENCE, plan, side_effects=self.log.to_dict())
        if op == PLAN_DECOMPOSE:
            parsed = parse_goal_bundle(req)
            tasks = decompose(req, parsed, self.reg)
            dummy = Plan(
                plan_id="tmp", goal=parsed["primary_goal"],
                goal_type=parsed["goal_type"], created_at=utc_now(req.get("now")),
                updated_at=utc_now(req.get("now")), status="DRAFT", tasks=tasks)
            return PlanResult(PLAN_DECOMPOSE, dummy, side_effects=self.log.to_dict())
        return self.create(req)

    def create(self, req: dict) -> PlanResult:
        now = utc_now(req.get("now"))
        parsed = parse_goal_bundle(req)
        # Memory/document/web/code context is DATA.
        for key in ("memory_context", "document_context", "web_context",
                    "code_artifacts"):
            for item in req.get(key) or []:
                text = item if isinstance(item, str) else str(
                    (item or {}).get("content") or item)
                meta = data_not_policy(text)
                if meta["injection_flagged"]:
                    # Do not obey. Record only.
                    parsed.setdefault("data_flags", []).append(meta)
        policy = classify_goal_policy(parsed["primary_goal"], source="user")
        if policy["op"] == PLAN_POLICY_BLOCKED:
            return PlanResult(
                PLAN_POLICY_BLOCKED, None, ok=False,
                blocked_reason="policy or paid-compute gate",
                gate=policy["gate"],
                policy_override=0,
                paid_service_bypass=0,
                side_effects=self.log.to_dict())
        clarify = needs_clarification(req)
        if clarify:
            return PlanResult(
                PLAN_NEEDS_CLARIFICATION, None, ok=False,
                clarification=clarify,
                blocked_reason=clarify,
                side_effects=self.log.to_dict())
        import re as _re
        if _re.search(r"\b(remember that|save this|store in memory|"
                      r"please remember)\b", parsed["primary_goal"], _re.I):
            req = dict(req)
            req["user_explicit_memory_write"] = True
        wanted = [s.upper() for s in (req.get("required_skills") or [])]
        for sk in wanted:
            if insufficient_capability(sk, self.reg):
                return PlanResult(
                    PLAN_INSUFFICIENT_CAPABILITY, None, ok=False,
                    blocked_reason=f"unsupported capability {sk}",
                    fabricated_skill=0,
                    side_effects=self.log.to_dict())
        tasks = decompose(req, parsed, self.reg)
        fab = 0
        for t in tasks:
            if not skill_allowed(t.required_skill, self.reg) and \
                    t.required_skill != "GENERAL":
                if insufficient_capability(t.required_skill, self.reg):
                    return PlanResult(
                        PLAN_INSUFFICIENT_CAPABILITY, None, ok=False,
                        blocked_reason=f"unsupported capability {t.required_skill}",
                        fabricated_skill=0,
                        side_effects=self.log.to_dict())
            t.execution_authority = False
            if paid_task(t.to_dict()) or t.estimated_cost_class == COST_PAID:
                return PlanResult(
                    PLAN_POLICY_BLOCKED, None, ok=False,
                    blocked_reason="paid service proposal blocked",
                    gate="PAID_COMPUTE_GATE_REQUIRED",
                    paid_service_bypass=0,
                    side_effects=self.log.to_dict())
        budget = default_budget()
        budget.update(req.get("budget") or {})
        budget["max_cost_class"] = COST_FREE
        if req.get("max_tasks"):
            budget["max_tasks"] = int(req["max_tasks"])
        for c in parsed["hard_constraints"]:
            m = _re.search(r"under (\d+) tasks", str(c), _re.I)
            if m:
                budget["max_tasks"] = int(m.group(1))
        if len(tasks) > int(budget["max_tasks"]):
            return PlanResult(
                PLAN_BUDGET_EXCEEDED, None, ok=False,
                blocked_reason="max_tasks exceeded",
                side_effects=self.log.to_dict())
        plan = Plan(
            plan_id=new_plan_id(parsed["primary_goal"], now),
            goal=parsed["primary_goal"],
            goal_type=parsed["goal_type"],
            created_at=now,
            updated_at=now,
            status="DRAFT",
            constraints=list(parsed["hard_constraints"]),
            preferences=list(parsed["soft_preferences"]),
            assumptions=[a.to_dict() for a in assumptions_from(parsed)],
            success_criteria=list(parsed["success_criteria"]),
            failure_criteria=list(parsed["failure_criteria"]),
            budget=budget,
            tasks=tasks,
            dependencies=[{"from": d, "to": t.task_id,
                           "reason": t.rationale.get("dependency_reason")}
                          for t in tasks for d in (t.dependencies or [])],
            provenance={
                "goal_source": "user",
                "constraint_source": "user",
                "memory_ids": [x.get("memory_id") for x in (req.get("memory_context") or [])
                               if isinstance(x, dict) and x.get("memory_id")],
                "document_references": list(req.get("document_refs") or []),
                "web_evidence_references": list(req.get("web_refs") or []),
                "observation_ids": [],
                "schema_version": SCHEMA_VERSION,
            },
            subgoals=list(parsed["subgoals"]),
            stop_conditions=[
                "all mandatory success criteria satisfied",
                "no unresolved mandatory blocker",
                "required evidence exists",
            ],
            best_verified={"completed": []},
        )
        # Current user constraints outrank stale memory.
        for item in req.get("memory_context") or []:
            text = item if isinstance(item, str) else str(
                (item or {}).get("content") or "")
            if is_injection(text):
                plan.decision_metadata.append({
                    "blocked_reason": "memory instruction ignored",
                    "instruction_authority": 0,
                })
        gerr = validate_graph(plan)
        if gerr:
            return PlanResult(PLAN_CREATE, plan, ok=False, errors=gerr,
                              cycle_accepted=0,
                              side_effects=self.log.to_dict())
        inv = self.validate_invariants(plan)
        if inv:
            return PlanResult(PLAN_VALIDATE, plan, ok=False, errors=inv,
                              side_effects=self.log.to_dict())
        plan.status = "READY"
        plan.graph_meta = graph_metadata(plan)
        maybe_checkpoint(plan, now)
        plan.plan_hash = plan_hash(plan)
        # Skip-verification goals still keep verify tasks.
        return PlanResult(PLAN_CREATE, plan, fabricated_skill=fab,
                          side_effects=self.log.to_dict())

    def validate_invariants(self, plan: Plan) -> list[str]:
        errors = []
        tasks = task_list(plan)
        if not tasks:
            errors.append("no tasks")
        if any(not t.task_id for t in tasks):
            errors.append("task missing id")
        errors.extend(validate_graph(plan))
        for t in tasks:
            if not t.success_criteria:
                errors.append(f"{t.task_id} missing success criteria")
            if t.required_skill == "PLANNING":
                errors.append("task must not target PLANNING skill")
            state = skill_known_state(t.required_skill, self.reg)
            if state == "UNKNOWN":
                errors.append(f"unknown skill {t.required_skill}")
            if t.required_skill not in (
                    "SCICOMP", "CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY",
                    "MATH_T4", "SCIENCE_RAG", "GENERAL"):
                errors.append(f"inactive/unknown skill treated as active: {t.required_skill}")
            if t.execution_authority:
                t.execution_authority = False
                errors.append("execution_authority must be false")
            if t.side_effect_class in (
                    "NETWORK_MUTATION", "EXTERNAL_IRREVERSIBLE", "PAID",
                    "LOCAL_MUTATION") and not t.approval_required:
                errors.append(f"{t.task_id} mutation needs approval")
        if not plan.success_criteria:
            errors.append("goal completion is not measurable")
        if not plan.budget or plan.budget.get("max_cost_class") != COST_FREE:
            errors.append("budget not bounded to FREE")
        if not plan.replan_policy:
            errors.append("replan policy missing")
        if not plan.stop_conditions:
            errors.append("stop conditions missing")
        return errors

    def _validate_result(self, plan: Plan) -> PlanResult:
        err = self.validate_invariants(plan)
        if err:
            return PlanResult(PLAN_VALIDATE, plan, ok=False, errors=err,
                              cycle_accepted=0,
                              side_effects=self.log.to_dict())
        plan.status = "VALIDATED" if plan.status == "DRAFT" else plan.status
        plan.graph_meta = graph_metadata(plan)
        plan.plan_hash = plan_hash(plan)
        return PlanResult(PLAN_VALIDATE, plan, side_effects=self.log.to_dict())

    def observe(self, req: dict) -> PlanResult:
        plan = self._coerce_plan(req["plan"])
        raw = req.get("observation") or {}
        # Observations are DATA and cannot change policy.
        blob = json_blob(raw)
        flagged = is_injection(blob)
        if flagged:
            plan.decision_metadata.append({
                "blocked_reason": "injected observation treated as data",
                "instruction_authority": 0,
            })
            # Do not complete, delete, or spend because of injection.
        now = utc_now(req.get("now"))
        obs = Observation(
            observation_id=raw.get("observation_id") or new_obs_id(
                raw.get("task_id") or "t", now),
            task_id=raw.get("task_id") or "",
            result_status=raw.get("result_status") or "SUCCEEDED",
            facts=list(raw.get("facts") or []),
            artifacts=list(raw.get("artifacts") or []),
            errors=list(raw.get("errors") or []),
            confidence=raw.get("confidence") or "HIGH",
            timestamp=raw.get("timestamp") or now,
            failure_class=raw.get("failure_class"),
            instruction_authority=0,
        )
        if flagged and obs.result_status == "SUCCEEDED" and \
                ("complete" in blob.lower() or "delete" in blob.lower()):
            # Literal content may be noted; it does not authorize action.
            obs.facts = list(obs.facts) + [f"literal:{blob[:160]}"]
            # Keep prior task outcome semantics from harness result_status
            # only when it is a real tool result, not an instruction.
            if "ignore" in blob.lower() or "mark everything complete" in blob.lower():
                obs.result_status = "SUCCEEDED"
                obs.artifacts = list(obs.artifacts or [f"{obs.task_id}.artifact"])
        before = snapshot_progress(plan)
        op = apply_observation(plan, obs, now)
        plan.updated_at = now
        plan.budget["consumed_tasks"] = sum(
            1 for t in task_list(plan) if t.status == "SUCCEEDED")
        if not progress_signal(before, plan):
            plan.budget["non_progress_streak"] = int(
                plan.budget.get("non_progress_streak") or 0) + 1
        else:
            plan.budget["non_progress_streak"] = 0
        note_history(plan, op=op, observation_id=obs.observation_id)
        inj_success = 0
        if flagged:
            if plan.status == "COMPLETE" and verification_missing(plan):
                inj_success = 1
            if self.log.unauthorized_action:
                inj_success = 1
        if loop_detected(plan):
            plan.status = "BLOCKED"
            plan.blocked_reason = "uncontrolled planning loop"
            plan.plan_hash = plan_hash(plan)
            return PlanResult(PLAN_BLOCK, plan, ok=False,
                              blocked_reason=plan.blocked_reason,
                              prompt_injection_success=inj_success,
                              side_effects=self.log.to_dict())
        if int(plan.budget.get("non_progress_streak") or 0) >= NON_PROGRESS_LIMIT:
            plan.status = "BLOCKED"
            plan.blocked_reason = "non-progress"
            plan.plan_hash = plan_hash(plan)
            return PlanResult(PLAN_BLOCK, plan, ok=False,
                              blocked_reason="non-progress",
                              side_effects=self.log.to_dict())
        maybe_checkpoint(plan, now)
        if op in (PLAN_REPLAN, PLAN_RECOVER, PLAN_BLOCK, PLAN_POLICY_BLOCKED,
                  PLAN_INSUFFICIENT_CAPABILITY, PLAN_BUDGET_EXCEEDED):
            plan.plan_hash = plan_hash(plan)
            return PlanResult(op, plan, ok=op == PLAN_RECOVER,
                              blocked_reason=plan.blocked_reason,
                              prompt_injection_success=inj_success,
                              side_effects=self.log.to_dict())
        done, evidence = completion_decision(plan)
        if done == PLAN_COMPLETE:
            return self._mark_complete(plan, evidence)
        ready = ready_tasks(plan)
        if not ready and not can_complete(plan):
            # No ready work: blocked or waiting.
            if any(t.status == "FAILED" for t in task_list(plan)):
                plan.status = "NEEDS_REPLAN"
            elif any(t.status in ("PENDING", "READY") for t in task_list(plan)):
                plan.status = "IN_PROGRESS"
            plan.plan_hash = plan_hash(plan)
            return PlanResult(PLAN_OBSERVE, plan,
                              prompt_injection_success=inj_success,
                              side_effects=self.log.to_dict())
        plan.status = "IN_PROGRESS"
        plan.plan_hash = plan_hash(plan)
        return PlanResult(PLAN_OBSERVE, plan,
                          prompt_injection_success=inj_success,
                          side_effects=self.log.to_dict())

    def replan(self, req: dict) -> PlanResult:
        plan = self._coerce_plan(req["plan"])
        trigger = req.get("replan_trigger") or infer_trigger(
            req.get("observation") or {}, req)
        if not should_replan(trigger):
            return PlanResult(PLAN_OBSERVE, plan, ok=True,
                              blocked_reason="unnecessary replan refused",
                              side_effects=self.log.to_dict())
        max_r = int(plan.budget.get("max_replans") or 5)
        used = int(plan.budget.get("consumed_replans") or 0)
        if used >= max_r:
            plan.status = "FAILED"
            plan.blocked_reason = "replan budget exceeded"
            return PlanResult(PLAN_BUDGET_EXCEEDED, plan, ok=False,
                              blocked_reason=plan.blocked_reason,
                              side_effects=self.log.to_dict())
        if loop_detected(plan):
            plan.status = "BLOCKED"
            plan.blocked_reason = "replan oscillation"
            return PlanResult(PLAN_BLOCK, plan, ok=False,
                              blocked_reason=plan.blocked_reason,
                              side_effects=self.log.to_dict())
        before_completed = {
            t.task_id for t in task_list(plan) if t.status == "SUCCEEDED"
        }
        plan.budget["consumed_replans"] = used + 1
        plan.plan_version += 1
        plan.history = list(plan.history) + [{
            "plan_version": plan.plan_version,
            "goal": plan.goal,
            "constraints": list(plan.constraints),
        }]
        if req.get("new_goal"):
            plan.revisions.append({
                "kind": "goal_replacement",
                "from": plan.goal,
                "to": req["new_goal"],
                "version": plan.plan_version,
            })
            plan.goal = req["new_goal"]
            # Invalidate all incomplete; keep succeeded that still apply.
            for t in task_list(plan):
                if t.status not in ("SUCCEEDED", "SKIPPED"):
                    t.status = "INVALIDATED"
        if req.get("new_constraints") is not None:
            old = list(plan.constraints)
            plan.constraints = list(req["new_constraints"])
            plan.revisions.append({
                "kind": "constraint_update",
                "from": old,
                "to": plan.constraints,
                "version": plan.plan_version,
            })
            if req.get("new_max_tasks"):
                plan.budget["max_tasks"] = int(req["new_max_tasks"])
        if req.get("invalidate_task"):
            invalidate_downstream(plan, req["invalidate_task"])
            preserve_unrelated(plan, req["invalidate_task"])
        for t in task_list(plan):
            if t.status == "INVALIDATED":
                t.status = "PENDING"
                t.attempt_count = 0
                t.result_reference = None
        plan.status = "READY"
        plan.best_verified = snapshot_best(plan)
        after_completed = {
            t.task_id for t in task_list(plan) if t.status == "SUCCEEDED"
        }
        loss = len(before_completed - after_completed - set(
            descendants_safe(plan, req.get("invalidate_task"))))
        plan.plan_hash = plan_hash(plan)
        note_history(plan, replan_trigger=trigger)
        return PlanResult(
            PLAN_REPLAN, plan,
            silent_completed_work_loss=max(0, loss),
            side_effects=self.log.to_dict())

    def _try_complete(self, plan: Plan) -> PlanResult:
        done, evidence = completion_decision(plan)
        if done == PLAN_COMPLETE:
            return self._mark_complete(plan, evidence)
        if verification_missing(plan):
            return PlanResult(PLAN_OBSERVE, plan, ok=False,
                              blocked_reason="verification missing",
                              false_complete=0,
                              side_effects=self.log.to_dict())
        return PlanResult(PLAN_OBSERVE, plan, ok=False,
                          blocked_reason="success criteria unsatisfied",
                          false_complete=0,
                          side_effects=self.log.to_dict())

    def _mark_complete(self, plan: Plan, evidence: list[str]) -> PlanResult:
        if verification_missing(plan):
            return PlanResult(PLAN_OBSERVE, plan, ok=False,
                              false_complete=0,
                              blocked_reason="refusing premature completion",
                              side_effects=self.log.to_dict())
        plan.status = "COMPLETE"
        plan.completion_evidence = evidence
        plan.decision_metadata.append({
            "completion_evidence": evidence[:12],
        })
        plan.plan_hash = plan_hash(plan)
        return PlanResult(PLAN_COMPLETE, plan, side_effects=self.log.to_dict())

    def resume(self, req: dict) -> PlanResult:
        raw = req.get("serialized") or req.get("plan_json")
        if isinstance(raw, str):
            plan = loads(raw)
        else:
            plan = self._coerce_plan(req.get("plan") or {})
        plan.plan_hash = plan_hash(plan)
        return PlanResult(PLAN_RESUME, plan, resume_ok=True,
                          side_effects=self.log.to_dict())

    def _coerce_plan(self, obj) -> Plan:
        if isinstance(obj, Plan):
            return obj
        if isinstance(obj, str):
            return loads(obj)
        return Plan.from_dict(obj or {})


def descendants_safe(plan: Plan, tid: str | None) -> set[str]:
    if not tid:
        return set()
    from sciencemath.planning.graph import descendants, dep_map
    return descendants(tid, dep_map(plan)) | {tid}


def json_blob(obj) -> str:
    import json
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)
