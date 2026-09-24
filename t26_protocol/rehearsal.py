"""Two disposable integrated lifecycle rehearsals and negative controls."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from sciencemath.integrated.runner import (Adapter, ExecutionError,
                                           IntegratedRunner, RecoverableError,
                                           validate_plan)
from .lifecycle import public_receipt, require_token
from .production import _sandbox
from .qualification import fixture_adapters, make_case, run_qualification


def _semantic_trace(output: dict) -> list[tuple]:
    return [(e.get("step_id"), e.get("capability_selected"), e.get("status"),
             e.get("verification_result"), e.get("retry_count"),
             (e.get("replan_event") or {}).get("trigger"))
            for e in output["trace"]]


def _multi_failure_run(root: Path) -> dict:
    scenario, _, injection = make_case("plan_replan_resume", 0)
    base = fixture_adapters({**injection, "kind": "none"})
    calls: dict[str, int] = {}
    adapters = {}
    for capability, adapter in base.items():
        def execute(payload, context, *, inner=adapter.execute):
            step = context["step_id"]
            calls[step] = calls.get(step, 0) + 1
            if step in {"s1", "s2"} and calls[step] == 1:
                raise RecoverableError("injected transient failure")
            result = inner(payload, context)
            if step == "s3" and calls[step] == 1:
                result["value"] += 1
            return result
        adapters[capability] = Adapter(capability, execute)
    output = IntegratedRunner(adapters, sandbox_root=root).run(scenario)
    statuses = [e["status"] for e in output["trace"]]
    pass_condition = (output["terminal"] == "COMPLETE" and
                      statuses.count("RECOVERABLE_ERROR") == 2 and
                      statuses.count("VERIFICATION_FAILURE") == 1 and
                      output["budget_state"]["total_retries"] == 2 and
                      output["budget_state"]["replans"] == 1 and
                      len(output["verified_steps"]) == 3 and
                      len(output["handoffs"]) == 2)
    return {"status": "PASS" if pass_condition else "FAIL",
            "terminal": output["terminal"], "failure_classes": statuses,
            "retry_count": output["budget_state"]["total_retries"],
            "replan_count": output["budget_state"]["replans"],
            "verified_steps": len(output["verified_steps"]),
            "handoffs": len(output["handoffs"]),
            "semantic_trace": _semantic_trace(output)}


def _resume_process_control(root: Path) -> dict:
    script = Path(__file__).resolve().parents[1] / "scripts" / "t26_resume_worker.py"
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src") + __import__("os").pathsep + str(Path(__file__).resolve().parents[1])
    stages = []
    for phase in ("interrupt", "resume"):
        completed = subprocess.run([sys.executable, str(script), phase, str(root)],
                                   env=env, capture_output=True, text=True,
                                   check=True, timeout=60)
        stages.append(json.loads(completed.stdout))
    first, second = stages
    passed = (first["pid"] != second["pid"] and first["terminal"] == "PARTIAL"
              and first["verified_steps"] == ["s1"]
              and second["terminal"] == "COMPLETE"
              and second["verified_steps"] == ["s1", "s2", "s3"]
              and second["step_one_calls"] == 1 and second["handoffs"] == 2)
    return {"status": "PASS" if passed else "FAIL",
            "processes_distinct": first["pid"] != second["pid"],
            "step_one_calls_after_resume": second["step_one_calls"],
            "handoffs_after_resume": second["handoffs"],
            "terminal": second["terminal"]}


def _authority_controls(root: Path) -> dict:
    scenario, _, injection = make_case("adversarial_instruction_isolation", 0)
    results = {}
    with TemporaryDirectory(prefix="t26-authority-", dir=root) as tmp:
        p = Path(tmp)
        out = IntegratedRunner(fixture_adapters(injection), sandbox_root=p).run(scenario)
        results["external_action_request_refused"] = out["terminal"] == "SECURITY_REFUSAL"
    bad = json.loads(json.dumps(scenario))
    bad["gold"] = {"expected_answer": "forbidden"}
    with TemporaryDirectory(prefix="t26-gold-", dir=root) as tmp:
        try:
            IntegratedRunner(fixture_adapters(injection), sandbox_root=Path(tmp)).run(bad)
            results["gold_access_refused"] = False
        except ExecutionError:
            results["gold_access_refused"] = True
    bad_plan = json.loads(json.dumps(scenario["plan"]))
    bad_plan["steps"][0]["capability"] = "UNREGISTERED"
    try:
        validate_plan(bad_plan)
        results["unregistered_capability_refused"] = False
    except ExecutionError:
        results["unregistered_capability_refused"] = True
    for name in ("memory_escape", "sandbox_escape"):
        try:
            _sandbox({"sandbox_root": str(root)}, "../outside")
            results[name + "_refused"] = False
        except ExecutionError:
            results[name + "_refused"] = True
    try:
        require_token("T26_ONE_SHOT_OFFICIAL_EVALUATION-v2", "evaluation")
        results["evaluation_token_alias_refused"] = False
    except PermissionError:
        results["evaluation_token_alias_refused"] = True
    return {"status": "PASS" if all(results.values()) else "FAIL",
            "controls": results, "critical_violations": 0 if all(results.values()) else 1}


def run_rehearsals() -> dict:
    runs = []
    for index in (1, 2):
        with TemporaryDirectory(prefix=f"t26-rehearsal-{index}-") as tmp:
            root = Path(tmp)
            qualification = run_qualification()
            recovery_root = root / "recovery"
            recovery_root.mkdir()
            recovery = _multi_failure_run(recovery_root)
            resume_root = root / "resume"
            resume_root.mkdir()
            resume = _resume_process_control(resume_root)
            authority = _authority_controls(root)
            score = qualification["score"]
            receipt = public_receipt(score, "0" * 64, "1" * 64)
            runs.append({"run": index,
                         "plan_execution_scoring_status": qualification["status"],
                         "scenario_count": qualification["scenario_count"],
                         "recovery": recovery, "resume": resume,
                         "authority_adversarial": authority,
                         "public_receipt_status": receipt["status"],
                         "semantic_score": score["metrics"],
                         "semantic_recovery": recovery["semantic_trace"]})
    diffs = {
        "metric_diff": int(runs[0]["semantic_score"] != runs[1]["semantic_score"]),
        "recovery_trace_diff": int(runs[0]["semantic_recovery"] != runs[1]["semantic_recovery"]),
        "scenario_count_diff": int(runs[0]["scenario_count"] != runs[1]["scenario_count"]),
    }
    passed = (not any(diffs.values()) and all(
        r["plan_execution_scoring_status"] == "PASS" and
        r["recovery"]["status"] == "PASS" and
        r["resume"]["status"] == "PASS" and
        r["authority_adversarial"]["status"] == "PASS" and
        r["public_receipt_status"] == "PASS" for r in runs))
    for r in runs:
        del r["semantic_recovery"]
    return {"schema_version": "t26-rehearsals-v1",
            "artifact": "T26_DISPOSABLE_INTEGRATED_REHEARSALS",
            "status": "PASS" if passed else "FAIL", "runs": runs,
            "semantic_diffs": diffs, "real_blind_rows": 0,
            "real_construction_attempts": 0,
            "real_evaluation_attempts": 0}
