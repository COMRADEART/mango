"""T20.61/T20.73–T20.79 suite runner. Deterministic; no LLM, no network.

Modes:
  run   — full orchestrator e2e: create -> bounded step loop; NEEDS_REPLAN
          is resolved through orchestrator.replan (bounded by allow_replans).
  probe — direct module calls against crafted fixtures (handoff/verify/
          escalation/assignment/recovery units).

Usage:
  python scripts/t20_run_eval.py <suite_dir_name>... [--split dev|final|both]
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.orchestration.assignment import assignable_batch  # noqa: E402
from sciencemath.orchestration.checkpoint import RunCheckpointer  # noqa: E402
from sciencemath.orchestration.handoffs import (  # noqa: E402
    build_handoff, validate_handoff,
)
from sciencemath.orchestration.orchestrator import (  # noqa: E402
    Orchestrator, completion_ok,
)
from sciencemath.orchestration.recovery import (  # noqa: E402
    bounded_revision_ok, classify_failure, livelock_detected,
    livelock_fingerprint, unrelated_completed_work_loss,
)
from sciencemath.orchestration.verify import (  # noqa: E402
    escalate_disagreement, verify_artifact, verifier_payload_is_data,
)
from sciencemath.orchestration.workers import (  # noqa: E402
    INJECTED_ORCHESTRATOR_DIRECTIVES, worker_run,
)
from sciencemath.planning.pipeline import Planner  # noqa: E402

NOW_BASE = "2026-01-01T00:{mm:02d}:{ss:02d}Z"
PLAN_COMPLETE = "PLAN_COMPLETE"

# one planner instance for the whole eval run (stateless wrt runs)
EVAL_PLANNER = Planner()


def step_now(i: int) -> str:
    return NOW_BASE.format(mm=(i // 60) % 60, ss=i % 60)


# ---------------------------------------------------------------------------
# run mode
# ---------------------------------------------------------------------------
def event_counts(run) -> dict:
    evs = run.events
    counts = {
        "verification_passed": sum(
            1 for e in evs if e["event_type"] == "VERIFICATION_PASSED"),
        "revisions": sum(
            1 for e in evs if e["event_type"] == "REVISION_REQUESTED"),
        "replans": sum(1 for e in evs if e["event_type"] == "PLAN_REVISED"),
        "claim_rejections": sum(
            1 for e in evs if e["event_type"] == "MESSAGE_REJECTED"
            and (e.get("payload") or {}).get("reason")
            == "adversarial_claim_as_data"),
        "checkpoint_saved": sum(
            1 for e in evs if e["event_type"] == "CHECKPOINT_SAVED"),
        "handoffs": len(run.handoffs),
    }
    started = [(e["task_id"], e["timestamp"]) for e in evs
               if e["event_type"] == "TASK_STARTED"]
    by_ts: dict[str, set] = {}
    for tid, ts in started:
        by_ts.setdefault(ts, set()).add(tid)
    counts["parallel_batch"] = any(len(v) >= 2 for v in by_ts.values())
    return counts


def run_case(row: dict, planner: Planner) -> dict:
    res = {"case_id": row["case_id"], "mode": "run", "ok": False,
           "failures": [], "status": "", "counters": {}}
    gold = row["gold"]
    driver = row["driver"]
    case_d = row.get("case") or {}

    if row.get("plan"):
        plan_dict = row["plan"]
    else:
        pr = planner.handle({"operation": "PLAN_CREATE",
                             **row["request"],
                             "hard_constraints":
                                 ["no network", "FREE cost only"],
                             "now": step_now(0)})
        if not pr.ok or pr.plan is None:
            res["failures"].append(f"plan_create_refused:{pr.blocked_reason}")
            res["status"] = "PLAN_CREATE_REFUSED"
            return res
        plan_dict = pr.plan.to_dict()

    ckpt_dir = None
    orch = Orchestrator(planner=planner)
    if gold.get("require", {}).get("checkpoint_saved"):
        ckpt_dir = tempfile.mkdtemp(prefix="t20ckpt-")
        orch = Orchestrator(
            planner=planner,
            checkpointer=RunCheckpointer(ckpt_dir))
    rr = orch.create({"plan": plan_dict, "now": step_now(0)})
    if not rr.ok:
        res["status"] = rr.run.status
        res["counters"] = dict(rr.zero_tolerance)
        res["failures"].append(f"create_refused:{rr.blocked_reason}")
        return _check(row, res, run=None, counts={})
    run = rr.run
    counts = {}
    replans_used = 0
    result = rr
    for i in range(1, int(driver.get("max_steps", 60)) + 1):
        result = orch.step({"run": run, "case": case_d, "now": step_now(i)})
        run = result.run
        if run.status == "NEEDS_REPLAN":
            if replans_used < int(driver.get("allow_replans", 0)):
                replans_used += 1
                result = orch.replan({
                    "run": run,
                    "replan_trigger": (run.replan_state or {}).get(
                        "trigger", ""),
                    "now": step_now(i)})
                run = result.run
            else:
                break
        if run.status in ("COMPLETE", "BLOCKED", "FAILED", "ABORTED"):
            break
    counts = event_counts(run)
    res["status"] = run.status
    res["counters"] = dict(run.counters)
    res["replay_ok"] = result.replay_ok
    res["replans_used"] = replans_used
    res["run"] = run
    return _check(row, res, run, counts)


def _check(row: dict, res: dict, run, counts: dict) -> dict:
    gold = row["gold"]
    fails = res["failures"]
    status = res["status"]
    if status != gold.get("expect_status"):
        fails.append(f"status:{status}!={gold.get('expect_status')}")
    if gold.get("plan_gate") and run is not None:
        gate = completion_ok(run, EVAL_PLANNER)
        if not gate:
            fails.append("plan_gate_not_complete")
    if gold.get("zero_tolerance_zero"):
        nz = {k: v for k, v in (res.get("counters") or {}).items() if v}
        if nz:
            fails.append(f"zero_tolerance:{nz}")
    if res.get("replay_ok") is False:
        fails.append("replay_mismatch")
    reason = gold.get("blocked_reason_contains")
    if reason:
        blocker_text = " ".join(
            b.get("reason", "") for b in ((run.blockers if run else []) or [])
        ) + " " + status
        if reason not in blocker_text:
            fails.append(f"blocked_reason_missing:{reason}")
    req = gold.get("require") or {}
    if run is not None:
        if req.get("verification_passed_min", 0) > \
                counts.get("verification_passed", 0):
            fails.append("require:verification_passed_min")
        if req.get("revision_min", 0) > counts.get("revisions", 0):
            fails.append("require:revision_min")
        if req.get("replan_min", 0) > counts.get("replans", 0):
            fails.append("require:replan_min")
        if req.get("claim_rejected_min", 0) > \
                counts.get("claim_rejections", 0):
            fails.append("require:claim_rejected_min")
        if req.get("checkpoint_saved") and counts.get("checkpoint_saved", 0) \
                < 1:
            fails.append("require:checkpoint_saved")
        if req.get("handoff_fields_complete"):
            for h in run.handoffs:
                if not (h.get("constraints") and h.get("success_criteria")
                        and h.get("remaining_budget")
                        and (h.get("provenance") or {}).get("plan_id")):
                    fails.append("require:handoff_fields_incomplete")
                    break
        if req.get("no_duplicate_assignment"):
            asg = [(a.get("task_id"), a.get("agent_id"))
                   for a in run.assignments if a.get("status") == "ASSIGNED"]
            if len(asg) != len(set(asg)):
                fails.append("require:duplicate_assignment")
    res["ok"] = not fails
    res["failures"] = fails
    return res


# ---------------------------------------------------------------------------
# probe mode
# ---------------------------------------------------------------------------
def _base_agents() -> dict:
    return {
        "orch-1": {"agent_id": "orch-1", "role": "ORCHESTRATOR",
                   "status": "READY", "allowed_skills": [],
                   "denied_skills": [], "budget": {"max_tasks": 5}},
        "w-code": {"agent_id": "w-code", "role": "CODE_WORKER",
                   "status": "READY", "allowed_skills": ["CODE"],
                   "denied_skills": [], "budget": {"max_tasks": 5}},
        "w-doc": {"agent_id": "w-doc", "role": "DOCUMENT_WORKER",
                  "status": "READY", "allowed_skills": ["DOCUMENT"],
                  "denied_skills": [], "budget": {"max_tasks": 5}},
    }


def _base_run() -> dict:
    return {
        "run_id": "probe-run", "plan_id": "probe-plan",
        "plan": {"plan_id": "probe-plan", "constraints": ["no network"],
                 "plan_version": 1},
        "budgets": {"max_cost_class": "FREE", "max_tasks": 10},
        "tasks": {"t01": "PENDING"},
        "artifacts": [{"artifact_id": "art-known"}],
        "handoffs": [],
        "agents": _base_agents(),
    }


def _base_task() -> dict:
    return {"task_id": "t01", "required_skill": "CODE",
            "task_type": "code", "success_criteria": ["criterion one"],
            "objective": "probe task"}


def _probe_handoff(fixture: dict) -> tuple[bool, list]:
    variant = fixture["variant"]
    run, task = _base_run(), _base_task()
    to_agent = run["agents"]["w-code"]
    handoff = build_handoff(run, task,
                            {"agent_id": "orch-1", "role": "ORCHESTRATOR"},
                            to_agent, now=step_now(0))
    if variant == "unknown_target_agent":
        handoff.to_agent = "ghost-agent"
    elif variant == "task_already_succeeded":
        run["tasks"]["t01"] = "SUCCEEDED"
    elif variant == "target_lacks_skill:CODE":
        run["agents"]["w-code"]["allowed_skills"] = ["DOCUMENT"]
    elif variant == "target_paid_access_forbidden":
        to_agent["paid_compute_access"] = True
    elif variant == "budget_invalid":
        handoff.remaining_budget["max_cost_class"] = "PAID"
    elif variant == "required_artifact_missing":
        handoff.artifact_refs = ["art-nonexistent"]
    elif variant == "constraint_set_incomplete":
        handoff.constraints = []
    elif variant == "success_criteria_incomplete":
        handoff.success_criteria = []
    elif variant == "provenance_incomplete":
        handoff.provenance = {"plan_id": None, "plan_version": 1,
                              "assigned_at": step_now(0),
                              "from_role": "ORCHESTRATOR",
                              "to_role": "CODE_WORKER"}
    elif variant == "handoff_cycle_exceeds_limit":
        # the walk follows edges OUT of the target: build a chain that
        # starts at w-code and runs past MAX_HANDOFF_CYCLE (4)
        run["handoffs"] = (
            [{"from_agent": "w-code", "to_agent": "c0"}]
            + [{"from_agent": f"c{k}", "to_agent": f"c{k + 1}"}
               for k in range(5)])
    errs = validate_handoff(run, handoff, task, run["agents"])
    expected = fixture["variant"]
    return (any(expected in e for e in errs), errs)


def _verify_fixture(fixture: dict) -> tuple[dict, dict, dict]:
    variant = fixture.get("variant", "pass_full")
    task = {"task_id": "t01", "required_skill": "CODE",
            "success_criteria": ["criterion one", "criterion two"]}
    artifact = {"artifact_id": "art-1",
                "content_hash": "ab" * 8,
                "producer_agent_id": "w-code"}
    result = {"result_status": "SUCCEEDED",
              "facts": ["criterion one", "criterion two"],
              "errors": [], "numeric_value": None, "payload_flags": []}
    if variant == "no_evidence":
        result["facts"] = []
    elif variant == "missing_hash":
        artifact.pop("content_hash")
    elif variant == "partial_coverage":
        result["facts"] = ["criterion one criterion two"]
    elif variant == "failed_test_as_success":
        result["errors"] = ["tests fail on case 3"]
    elif variant == "fabricated_citation":
        result["facts"] = ["cite:unrelated-source", "criterion one",
                           "criterion two"]
    elif variant == "numeric_mismatch":
        task["numeric_check"] = {"value": 2.0, "tol": 1e-9}
        result["facts"] = ["criterion one", "criterion two"]
        result["numeric_value"] = 2.5
    elif variant == "numeric_boundary":
        task["numeric_check"] = {"value": 2.0, "tol": 1e-9}
        result["facts"] = ["criterion one", "criterion two"]
        result["numeric_value"] = fixture.get("claim", 2.0)
    return task, artifact, result


def _probe_verify(fixture: dict) -> tuple[bool, dict]:
    task, artifact, result = _verify_fixture(fixture)
    d = verify_artifact(task, artifact, result, "verifier-1",
                        dependency_facts=[str(c) for c in
                                          task["success_criteria"]])
    ok = d["decision"] == fixture["gold"].get(
        "expect_decision") if "gold" in fixture else True
    return ok, {"decision": d["decision"], "reasons": d["reasons"][:3]}


def _probe_injection(fixture: dict) -> tuple[bool, dict]:
    text = INJECTED_ORCHESTRATOR_DIRECTIVES[0]
    flags = verifier_payload_is_data(text)
    task, artifact, result = _verify_fixture({"variant": "pass_full"})
    result["facts"] = task["success_criteria"] + [text]
    d = verify_artifact(task, artifact, result, "verifier-1",
                        dependency_facts=task["success_criteria"])
    rejected = any("rejected as data" in r for r in d["reasons"]) or \
        any("treated as data" in r for r in d["reasons"])
    ok = flags["injection_flagged"] and rejected
    return ok, {"injection_flagged": flags["injection_flagged"],
                "decision": d["decision"],
                "not_waived": rejected}


def _probe_escalate(fixture: dict) -> tuple[bool, dict]:
    task, artifact, _ = _verify_fixture({"variant": "pass_full"})
    deps = task["success_criteria"]
    first = verify_artifact(task, artifact, {"result_status": "SUCCEEDED",
                                             "facts": [], "errors": []},
                            "verifier-1", dependency_facts=deps)
    if fixture.get("agree"):
        second = dict(first)
    else:
        second = verify_artifact(task, artifact, _verify_fixture(
            {"variant": "pass_full"})[2], "verifier-2",
            dependency_facts=deps)
    esc = escalate_disagreement(task, artifact, first, second, deps)
    expect = fixture["gold"].get("expect_escalation") if "gold" in fixture \
        else None
    escalated = esc.get("escalation") == "deterministic_check"
    return (escalated == expect if expect is not None else True), {
        # "escalation" carries the BOOL the gold key expect_escalation
        # checks; the raw escalation label goes to escalation_kind
        "escalation": escalated,
        "escalation_kind": esc.get("escalation", ""),
        "decision": esc["decision"]}


def _probe_duplicate(_fixture: dict) -> tuple[bool, dict]:
    from sciencemath.orchestration.locks import LockTable
    run = _base_run()
    plan = {"tasks": [{"task_id": "t01", "required_skill": "CODE",
                       "status": "PENDING", "optional": False}],
            "dependencies": []}
    run["tasks"]["t01"] = "ASSIGNED"
    table = LockTable()
    batch, deferred = assignable_batch(plan, run["agents"], run,
                                       table.held)
    reason = (deferred[0]["reason"] if deferred else "")
    return reason == "already_assigned", {
        "deferred_reason": reason, "batch": len(batch)}


def _probe_serialize(_fixture: dict) -> tuple[bool, dict]:
    from sciencemath.orchestration.locks import LockTable
    run = _base_run()
    plan = {
        "tasks": [
            {"task_id": "t01", "required_skill": "CODE",
             "status": "RUNNING", "optional": False,
             "resources": ["document_fixture:d1"]},
            {"task_id": "t02", "required_skill": "CODE",
             "status": "READY", "optional": False,
             "resources": ["document_fixture:d1"]},
        ],
        "dependencies": []}
    run["tasks"] = {"t01": "ASSIGNED", "t02": "PENDING"}
    table = LockTable()
    table.acquire("t01", [{"resource_id": "document_fixture:d1",
                           "kind": "WRITE"}])
    batch, deferred = assignable_batch(plan, run["agents"], run,
                                       table.held)
    reason = (deferred[0]["reason"] if deferred else "")
    return reason.startswith("resource_conflict"), {
        "deferred_reason": reason,
        "deferred_reason_prefix": reason.split(":")[0],
        "batch": len(batch)}


def _probe_classify(fixture: dict) -> tuple[bool, dict]:
    cls = classify_failure({"errors": [fixture["variant"]],
                            "result_status": "FAILED"})
    return cls == fixture["gold"]["expect_class"], {"class": cls}


def _probe_revision_bound(fixture: dict) -> tuple[bool, dict]:
    used = int(fixture["used"])
    run = {"revisions": [{"task_id": "t1"}] * used,
           "budgets": {"consumed_revisions": used, "max_revisions": 12}}
    allowed = bounded_revision_ok(run, "t1")
    ok = allowed == fixture["gold"]["expect_ok"]
    return ok, {"used": used, "ok": allowed}


def _probe_preserve(fixture: dict) -> tuple[bool, dict]:
    def plan_with(statuses: dict) -> dict:
        return {"tasks": [{"task_id": tid, "status": st} for tid, st in
                          statuses.items()],
                "dependencies": [{"from": "t1", "to": "t2"}]}
    before = plan_with({"t1": "SUCCEEDED", "t2": "SUCCEEDED",
                        "t3": "SUCCEEDED", "t4": "PENDING"})
    if fixture.get("invalidate"):
        after = plan_with({"t1": "INVALIDATED", "t2": "INVALIDATED",
                           "t3": "SUCCEEDED", "t4": "PENDING"})
    else:
        after = before
    loss = unrelated_completed_work_loss(before, after, "t1")
    return loss == 0, {"loss": loss}


PROBES = {
    "handoff": _probe_handoff,
    "verify": _probe_verify,
    "injection": _probe_injection,
    "escalate": _probe_escalate,
    "duplicate": _probe_duplicate,
    "serialize": _probe_serialize,
    "classify": _probe_classify,
    "revision_bound": _probe_revision_bound,
    "preserve": _probe_preserve,
}


def probe_case(row: dict) -> dict:
    fn = PROBES[row["probe"]]
    fixture = dict(row.get("fixture") or {})
    fixture["gold"] = row["gold"]
    try:
        ok, detail = fn(fixture)
    except Exception as exc:   # noqa: BLE001 — eval boundary
        return {"case_id": row["case_id"], "mode": "probe", "ok": False,
                "failures": [f"probe_error:{type(exc).__name__}:{exc}"]}
    gold = row["gold"]
    for key, want in gold.items():
        if key.startswith("expect_"):
            got = detail.get(key[len("expect_"):])
            if got != want:
                ok = False
    return {"case_id": row["case_id"], "mode": "probe", "ok": ok,
            "failures": [] if ok else [f"gold_mismatch:{detail}"]}


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def load_rows(suite_dir: Path, split_name: str) -> list[dict]:
    path = suite_dir / f"{split_name}.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_suite(name: str, split_name: str) -> dict:
    suite_dir = ROOT / "evaluations/t20/suites" / name
    rows = load_rows(suite_dir, split_name)
    results = []
    for row in rows:
        if row["mode"] == "probe":
            results.append(probe_case(row))
        else:
            results.append(run_case(row, EVAL_PLANNER))
    passed = sum(1 for r in results if r["ok"])
    out = {
        "suite": name, "split": split_name, "total": len(rows),
        "passed": passed, "failed": len(rows) - passed,
        "pass_rate": round(passed / len(rows), 4) if rows else 0.0,
        "failures": [{"case_id": r["case_id"], "failures": r["failures"],
                      "status": r.get("status", "")}
                     for r in results if not r["ok"]][:50],
    }
    out_dir = ROOT / "evaluations/t20/results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.{split_name}.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    split_name = "final" if "--final" in argv else "dev"
    suites = args or [
        d.name for d in (ROOT / "evaluations/t20/suites").iterdir()
        if d.is_dir()]
    rc = 0
    for name in sorted(suites):
        out = run_suite(name, split_name)
        print(json.dumps({k: out[k] for k in
                          ("suite", "split", "total", "passed", "failed")}))
        if out["failed"]:
            rc = 1
            for f in out["failures"][:10]:
                print(f"  FAIL {f['case_id']} {f['status']} "
                      f"{f['failures']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))