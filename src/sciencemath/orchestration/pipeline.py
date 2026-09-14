"""T20.2/T20.5/T20.6 orchestration facade.

Public entrypoint handling RUN_OPS: RUN_CREATE / RUN_STEP / RUN_STATUS /
RUN_CHECKPOINT / RUN_RESUME / RUN_BLOCK / RUN_ABORT / RUN_REPLAN /
RUN_COMPLETE. Deterministic, no LLM inference, no network, no side effects.
"""
from __future__ import annotations

from sciencemath.orchestration.contract import RUN_OPS
from sciencemath.orchestration.orchestrator import (
    Orchestrator, RunResult, completion_ok,
)
from sciencemath.orchestration.models import OrchestrationRun


class OrchestrationError(ValueError):
    """Invalid orchestration operation."""


class OrchestratorFacade:
    """Dispatch RUN_OPS to the bounded orchestrator."""

    def __init__(self, orchestrator: Orchestrator | None = None):
        self.orch = orchestrator or Orchestrator()
        self._runs: dict[str, OrchestrationRun] = {}

    def handle(self, request: dict) -> RunResult:
        op = request.get("op") or request.get("operation") or "RUN_CREATE"
        if op not in RUN_OPS:
            raise OrchestrationError(f"unknown op {op!r}")
        if op == "RUN_CREATE":
            res = self.orch.create(request)
            if res.run is not None:
                self._runs[res.run.run_id] = res.run
            return res
        if op == "RUN_STEP":
            res = self.orch.step(request)
            if res.run is not None:
                self._runs[res.run.run_id] = res.run
            return res
        if op == "RUN_STATUS":
            rid = request.get("run_id")
            run = self._runs.get(rid)
            if run is None:
                return RunResult("RUN_STATUS", None, ok=False,
                                 errors=["run_not_found"])
            return RunResult("RUN_STATUS", run,
                             metrics=self.orch._metrics(run))
        if op == "RUN_CHECKPOINT":
            return self.orch.checkpoint(request)
        if op == "RUN_RESUME":
            res = self.orch.resume(request)
            if res.run is not None:
                self._runs[res.run.run_id] = res.run
            return res
        if op == "RUN_BLOCK":
            return self.orch.abort(request)   # bounded refusal path
        if op == "RUN_ABORT":
            return self.orch.abort(request)
        if op == "RUN_REPLAN":
            res = self.orch.replan(request)
            if res.run is not None:
                self._runs[res.run.run_id] = res.run
            return res
        if op == "RUN_COMPLETE":
            rid = request.get("run_id")
            run = self._runs.get(rid)
            if run is None:
                return RunResult("RUN_COMPLETE", None, ok=False,
                                 errors=["run_not_found"])
            # completion is planner-gated, never forced (T20.48)
            from sciencemath.planning.contract import PLAN_COMPLETE
            from sciencemath.planning.policy import completion_decision
            done, evidence = completion_decision(
                self.orch.planner._coerce_plan(run.plan))
            if done == PLAN_COMPLETE:
                return RunResult("RUN_COMPLETE", run,
                                 metrics={"evidence": evidence})
            return RunResult("RUN_COMPLETE", run, ok=False,
                             blocked_reason="plan gate not satisfied")
        raise OrchestrationError(f"unhandled op {op!r}")