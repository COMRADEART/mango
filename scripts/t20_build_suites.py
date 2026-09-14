"""T20.51–T20.57/T20.60 suite builder. FINAL checksums frozen at generation.

Seven benchmark suites over the bounded multi-agent orchestration runtime.
Rows are deterministic; no LLM inference and no network at eval time.

Row schema:
  case_id, category, mode ("run" | "probe"),
  request   — plan-creation request (goal/required_skills/...)
  plan      — optional explicit plan dict (long-horizon strict scenarios)
  case      — fixture-world directives (worker_behavior, failure_class, ...)
  driver    — {"max_steps", "allow_replans"}
  probe     — probe kind + fixture fields (mode == "probe")
  gold      — expected observations (fixed vocabulary, checked by the runner)

Fixture behavior vocabulary (src/sciencemath/orchestration/workers.py):
  success, partial, failure, timeout, conflict, malicious,
  missing_evidence, revision_demand, crash, self_verify_claim.
One-off failure/timeout/crash fail once per task then recover; a "failure"
with explicit non-TRANSIENT failure_class persists (replan / blocked paths).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t20/suites"

SKILLS = ("SCICOMP", "CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY", "GENERAL")
NOW = "2026-01-01T00:00:00Z"


def sha_lf(text: str) -> str:
    return hashlib.sha256(
        text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    path.write_text(body, encoding="utf-8", newline="\n")
    return sha_lf(body)


# ---------------------------------------------------------------------------
# gold builders
# ---------------------------------------------------------------------------
def g_complete(goal: str, skills: list, **req) -> dict:
    g = {"expect_status": "COMPLETE", "plan_gate": True,
         "zero_tolerance_zero": True, "require": {}, "max_steps": 60}
    g["request"] = {"goal": goal, "required_skills": skills, **req}
    return g


def g_expect(status: str, *, reason: str = "", **kw) -> dict:
    g = {"expect_status": status, "plan_gate": None,
         "zero_tolerance_zero": True, "require": {}, "max_steps": 60}
    if reason:
        g["blocked_reason_contains"] = reason
    g.update(kw)
    return g


def with_req(gold: dict, **require) -> dict:
    out = dict(gold)
    out["require"] = {**gold.get("require", {}), **require}
    return out


def case(cid: str, cat: str, gold: dict, *, case_d: dict | None = None,
         driver: dict | None = None) -> dict:
    return {"case_id": cid, "category": cat, "mode": "run",
            "request": gold.pop("request", {}),
            "plan": None, "case": case_d or {},
            "driver": driver or {"max_steps": gold.get("max_steps", 60),
                                 "allow_replans": 2},
            "gold": gold}


def probe(cid: str, cat: str, kind: str, fixture: dict, gold: dict) -> dict:
    return {"case_id": cid, "category": cat, "mode": "probe",
            "probe": kind, "fixture": fixture, "gold": gold}


# handoff rejection variants — exact validate_handoff error strings
HANDOFF_VARIANTS = (
    "unknown_target_agent", "task_already_succeeded",
    "target_lacks_skill:CODE", "target_paid_access_forbidden",
    "budget_invalid", "required_artifact_missing",
    "constraint_set_incomplete", "success_criteria_incomplete",
    "provenance_incomplete", "handoff_cycle_exceeds_limit",
)

# verify_artifact probe variants → expected decisions
VERIFY_VARIANTS = {
    "pass_full": "PASS",
    "no_evidence": "INSUFFICIENT_EVIDENCE",
    "missing_hash": "INSUFFICIENT_EVIDENCE",
    "partial_coverage": "NEEDS_REVISION",
    "failed_test_as_success": "FAIL",
    "fabricated_citation": "FAIL",
    "numeric_mismatch": "FAIL",
}

# classify_failure probe variants → expected classes (exact matcher strings)
CLASSIFY_VARIANTS = {
    "worker timeout": "AGENT_CRASH",
    "agent crashed mid-task": "AGENT_CRASH",
    "verification failed on artifact": "VERIFICATION_FAIL",
    "policy blocked this action": "POLICY_BLOCK",
    "budget exceeded for agent": "BUDGET_EXCEEDED",
    "required artifact missing from input": "MISSING_ARTIFACT",
    "resource conflict on lock": "RESOURCE_CONFLICT",
    "capability mismatch for skill": "CAPABILITY_MISMATCH",
    "invalid schema in request": "INVALID_INPUT",
    "simulated worker failure": "TRANSIENT",
}


# ---------------------------------------------------------------------------
# suite 1: mango-orchestration-core-v1 (220-300)
# ---------------------------------------------------------------------------
def core_rows() -> list[dict]:
    rows: list[dict] = []
    n = 0

    def add(gold: dict, cat: str, **kw) -> None:
        nonlocal n
        n += 1
        rows.append(case(f"oc-{n:04d}", cat, gold, **kw))

    # A. single-skill happy paths (30)
    for i in range(10):
        add(g_complete(f"Compute the mean of fixture dataset ds-{i}.",
                       ["SCICOMP"]), "single_skill")
    for i in range(10):
        add(g_complete(f"Fix the login bug in fixture repo r-{i}.",
                       ["CODE"]), "single_skill")
    for i in range(10):
        add(with_req(g_complete(f"Summarize contract document d-{i} with "
                                f"its renewal terms.", ["DOCUMENT"]),
                     verification_passed_min=1), "single_skill_verified")
    # B. multi-skill runs (40)
    for i in range(10):
        add(g_complete(f"Research the API for client {i}, then patch it.",
                       ["WEB_RESEARCH", "CODE"]), "multi_skill")
    for i in range(10):
        add(g_complete(f"Analyze dataset {i}, then summarize findings.",
                       ["SCICOMP", "DOCUMENT"]), "multi_skill")
    for i in range(10):
        add(g_complete(f"Recall decision {i}, parse contract {i}, compute "
                       f"the delta.", ["MEMORY", "DOCUMENT", "SCICOMP"]),
            "multi_skill")
    for i in range(10):
        add(g_complete(f"Search fixtures for fact {i}, verify freshness, "
                       f"document the answer.",
                       ["WEB_RESEARCH", "DOCUMENT"]), "multi_skill")
    # C. dependency / parallel (30)
    for i in range(10):
        add(g_complete(f"Chain code fix {i} then test verification.",
                       ["CODE"]), "dependency_ordering")
    for i in range(10):
        add(g_complete(f"Fan-out research {i}, then synthesize both "
                       f"answers.", ["WEB_RESEARCH"]), "parallel_branch")
    for i in range(10):
        add(g_complete(f"Parallel analysis of artifacts {i}, final "
                       f"summary.", ["SCICOMP", "GENERAL"]), "parallel_branch")
    # D. mandatory verification paths (30)
    for i in range(15):
        add(with_req(g_complete(f"Summarize contract {i} with citations.",
                                ["DOCUMENT"]),
                     verification_passed_min=1), "mandatory_verification")
    for i in range(15):
        add(with_req(g_complete(f"Verify web claim {i} with citations.",
                                ["WEB_RESEARCH"]),
                     verification_passed_min=1), "mandatory_verification")
    # E. handoff/provenance invariants (20)
    for i in range(20):
        add(with_req(g_complete(f"Multi-step document workflow {i}.",
                                ["DOCUMENT"]),
                     handoff_fields_complete=True), "handoff_provenance")
    # F. adversarial containment — claims are DATA (30)
    for i in range(10):
        add(with_req(g_complete(f"Research claim {i}, then document it.",
                                ["WEB_RESEARCH", "DOCUMENT"]),
                     claim_rejected_min=1),
            "adversarial_containment",
            case_d={"worker_behavior": {"t01": "malicious"}})
    for i in range(10):
        add(with_req(g_complete(f"Code task {i} then report.", ["CODE"]),
                     claim_rejected_min=1),
            "adversarial_containment",
            case_d={"worker_behavior": {"t01": "self_verify_claim"}})
    for i in range(10):
        add(g_complete(f"Document QA {i}.", ["DOCUMENT"]),
            "adversarial_containment",
            case_d={"malicious_observation": True})
    # G. recovery e2e — one-off failures recover through replan (30)
    for b in ("failure", "timeout", "crash"):
        for j in range(10):
            add(with_req(g_complete(f"Recover run {j} after {b}.", ["CODE"]),
                         replan_min=1), "transient_recovery",
                case_d={"worker_behavior": {"t01": b}},
                driver={"max_steps": 60, "allow_replans": 2})
    # H. bounded revision via partial coverage (10)
    # WEB_RESEARCH tasks carry 3 success criteria, so partial coverage
    # reliably triggers the bounded-revision path.
    for j in range(10):
        add(with_req(g_complete(f"Partial result run {j} then revision.",
                                ["WEB_RESEARCH"]), revision_min=1),
            "bounded_revision",
            case_d={"worker_behavior": {"t02": "partial"}})
    # I. revision-demand / missing-evidence recovery (20)
    for j in range(10):
        add(g_complete(f"Revision demand run {j}.", ["DOCUMENT"]),
            "revision_recovery",
            case_d={"worker_behavior": {"t01": "revision_demand"}})
    for j in range(10):
        add(g_complete(f"Missing evidence run {j}.", ["DOCUMENT"]),
            "evidence_recovery",
            case_d={"worker_behavior": {"t01": "missing_evidence"}})
    # J. persistent failure → replan requested (10)
    for j in range(10):
        add(g_expect("NEEDS_REPLAN"), "replan_requested",
            case_d={"worker_behavior": {"t01": "failure"},
                    "failure_class": "PERMANENT"},
            driver={"max_steps": 20, "allow_replans": 0})
    # K. simple decomposition pad to 260
    while len(rows) < 260:
        i = len(rows)
        add(g_complete(f"Pad orchestration task {i}.", ["GENERAL"]),
            "simple_decomposition")
    return rows[:260]


# ---------------------------------------------------------------------------
# suite 2: mango-orchestration-eval-v1 (350-500)
# ---------------------------------------------------------------------------
def eval_rows() -> list[dict]:
    rows: list[dict] = []
    n = 0

    def add(gold: dict, cat: str, **kw) -> None:
        nonlocal n
        n += 1
        rows.append(case(f"oe-{n:04d}", cat, gold, **kw))

    cycle = ["SCICOMP", "CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY",
             "GENERAL"]
    # broad happy-path coverage (240)
    for i in range(240):
        sk = [cycle[i % 6]]
        if i % 3 == 0:
            sk = [cycle[i % 6], cycle[(i + 1) % 6]]
        add(g_complete(f"Evaluation run {i} on fixture workload "
                       f"{i % 7}.", sk), "happy_path")
    # verification-required mix (60)
    for i in range(30):
        add(with_req(g_complete(f"Verified evaluation {i}.", ["DOCUMENT"]),
                     verification_passed_min=1), "verified_path")
    for i in range(30):
        add(with_req(g_complete(f"Web verification {i}.", ["WEB_RESEARCH"]),
                     verification_passed_min=1), "verified_path")
    # failure taxonomy e2e (60) — one-off behaviors recover via replan
    behaviors = ("failure", "timeout", "crash", "missing_evidence",
                 "revision_demand", "partial")
    for i in range(60):
        b = behaviors[i % len(behaviors)]
        add(with_req(g_complete(f"Recovery eval {i} after {b}.",
                                [cycle[i % 6]]),
                     replan_min=1 if b in ("failure", "timeout", "crash")
                     else 0),
            "failure_recovery",
            case_d={"worker_behavior": {"t02": b}},
            driver={"max_steps": 60, "allow_replans": 2})
    # checkpoint/resume (30)
    for i in range(30):
        add(with_req(g_complete(f"Checkpoint resume run {i}.", ["GENERAL"]),
                     checkpoint_saved=True), "checkpoint_resume")
    # replan flows (30)
    for i in range(30):
        add(with_req(g_complete(f"Replan flow {i}.", ["CODE"]),
                     replan_min=1), "observation_replan",
            case_d={"worker_behavior": {"t01": "failure"}},
            driver={"max_steps": 60, "allow_replans": 2})
    while len(rows) < 420:
        i = len(rows)
        add(g_complete(f"Eval pad run {i}.", ["GENERAL"]), "happy_path")
    return rows[:420]


# ---------------------------------------------------------------------------
# suite 3: mango-orchestration-long-horizon-v1 (>=30 FINAL, strict)
# ---------------------------------------------------------------------------
def make_long_horizon_plan(seed: int, n_tasks: int) -> dict:
    """Strict FINAL scenario plan: 15-30 tasks, >=3 skills, >=2 dependency
    edges, one parallel branch. Directive case adds observation replan,
    verifier-driven revision, and one recovery."""
    skills = ["SCICOMP", "CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY",
              "GENERAL"]
    tasks = []
    for i in range(1, n_tasks + 1):
        skill = skills[i % len(skills)]
        tasks.append({
            "task_id": f"t{i:02d}",
            "title": f"Long-horizon step {i} ({skill})",
            "objective": f"Perform bounded long-horizon step {i} for "
                         f"workflow {seed}",
            "task_type": "analysis",
            "required_skill": skill,
            "success_criteria": [f"long-horizon step {i} criterion a",
                                 f"long-horizon step {i} criterion b"],
            "status": "PENDING",
            "optional": False,
            "execution_authority": False,
            "side_effect_class": "READ_ONLY",
            "approval_required": False,
            "attempt_count": 0,
            "estimated_cost_class": "FREE",
            "dependencies": [f"t{i - 1:02d}"] if i > 1 else [],
            "rationale": {"dependency_reason": "sequential chain"},
        })
    # parallel branch: t07..t09 are siblings of the chain head t05
    for t in tasks[6:9]:
        t["dependencies"] = ["t05"]
    deps = [{"from": d, "to": t["task_id"], "reason": "chain"}
            for t in tasks for d in t["dependencies"]]
    return {
        "plan_id": f"lh-{seed:04d}",
        "goal": f"Long-horizon fixture workflow {seed}",
        "goal_type": "MIXED",
        "created_at": NOW,
        "updated_at": NOW,
        "status": "READY",
        "constraints": ["no network", "FREE cost only"],
        "preferences": [],
        "assumptions": [],
        "success_criteria": [f"long-horizon workflow {seed} completed"],
        "failure_criteria": [],
        "budget": {
            "max_tasks": n_tasks + 6, "max_replans": 5,
            "max_cost_class": "FREE", "consumed_tasks": 0,
            "consumed_replans": 0, "non_progress_streak": 0,
        },
        "tasks": tasks,
        "dependencies": deps,
        "provenance": {"goal_source": "fixture", "constraint_source": "user",
                       "memory_ids": [], "document_references": [],
                       "web_evidence_references": [], "observation_ids": [],
                       "schema_version": 1},
        "subgoals": [],
        "stop_conditions": ["all mandatory success criteria satisfied",
                            "no unresolved mandatory blocker",
                            "required evidence exists"],
        "replan_policy": "REPLAN_ON_BLOCKED",
        "history": [],
        "best_verified": {"completed": []},
        "plan_version": 1,
        "decision_metadata": [],
        "completion_evidence": [],
        "blocked_reason": None,
        "revisions": [],
        "graph_meta": {},
        "plan_hash": "",
    }


def long_horizon_rows() -> list[dict]:
    """36 strict scenarios; dev keeps the first 6, FINAL the last 30."""
    rows = []
    pool = [16, 18, 20, 22, 24, 26, 28, 30]
    for i in range(36):
        n_tasks = pool[i % len(pool)]
        plan = make_long_horizon_plan(i, n_tasks)
        # mandatory-verification tasks (CODE/WEB_RESEARCH/DOCUMENT: tid % 6
        # in {1,2,3}) so the partial result reliably reaches the verifier
        mandatory = [t for t in range(1, n_tasks + 1) if t % 6 in (1, 2, 3)]
        b_idx = i % len(mandatory)
        b_tid = mandatory[b_idx]                       # revision via verifier
        r_tid = mandatory[(b_idx + 1) % len(mandatory)]  # failure recovery
        p_tid = next(t for t in range(1, n_tasks + 1)
                     if t not in (b_tid, r_tid) and t % 6 not in (1, 2, 3))
        behavior = {f"t{b_tid:02d}": "partial",
                    f"t{r_tid:02d}": "failure",
                    f"t{p_tid:02d}": "timeout"}
        rows.append({
            "case_id": f"lh-{i:04d}", "category": "strict_long_horizon",
            "mode": "run", "request": {}, "plan": plan,
            "case": {"worker_behavior": behavior},
            "driver": {"max_steps": 200, "allow_replans": 3},
            "gold": {"expect_status": "COMPLETE", "plan_gate": True,
                     "zero_tolerance_zero": True, "require": {
                         "verification_passed_min": 1,
                         "revision_min": 1, "replan_min": 1,
                         "parallel_batch": True},
                     "max_steps": 200},
        })
    return rows


# ---------------------------------------------------------------------------
# suite 4: mango-agent-handoff-v1 (120-180)
# ---------------------------------------------------------------------------
def handoff_rows() -> list[dict]:
    rows: list[dict] = []
    for i in range(100):
        rows.append(case(
            f"oh-{i:04d}", "handoff_e2e",
            with_req(g_complete(f"Document handoff workflow {i}.",
                                ["DOCUMENT"]),
                     handoff_fields_complete=True),
            driver={"max_steps": 60, "allow_replans": 1}))
    for i, variant in enumerate(HANDOFF_VARIANTS * 5):
        rows.append(probe(f"ah-{i:04d}", "handoff_rejection", "handoff",
                          {"variant": variant},
                          {"expected_error_contains": variant}))
    return rows[:150]


# ---------------------------------------------------------------------------
# suite 5: mango-agent-verifier-v1 (150-220) — probe mode
# ---------------------------------------------------------------------------
def verifier_rows() -> list[dict]:
    rows: list[dict] = []
    n = 0

    def add(kind: str, fixture: dict, gold: dict, cat: str) -> None:
        nonlocal n
        n += 1
        rows.append(probe(f"av-{n:04d}", cat, kind, fixture, gold))

    for variant, expect in VERIFY_VARIANTS.items():
        for _ in range(14):
            add("verify", {"variant": variant},
                {"expect_decision": expect}, "verifier_decision")
    # numeric recheck boundary (30)
    for i in range(30):
        ok = i % 2 == 0
        add("verify", {"variant": "numeric_boundary",
                       "claim": 2.0 if ok else 2.5},
            {"expect_decision": "PASS" if ok else "FAIL"},
            "verifier_numeric")
    # injection containment (40)
    for i in range(40):
        add("injection", {"variant": "directives",
                          "contained": i % 2 == 0},
            {"expect_injection_flagged": True,
             "verification_not_waived": True}, "verifier_injection")
    # escalation (30): disagreeing verifiers escalate to the deterministic
    # check; agreeing verifiers do not.
    for i in range(30):
        agree = i % 2 == 0
        add("escalate", {"agree": agree},
            {"expect_escalation": not agree}, "verifier_escalation")
    while len(rows) < 200:
        n += 1
        rows.append(probe(f"av-{n:04d}", "verifier_decision", "verify",
                          {"variant": "pass_full"},
                          {"expect_decision": "PASS"}))
    return rows[:200]


# ---------------------------------------------------------------------------
# suite 6: mango-agent-concurrency-v1 (100-160)
# ---------------------------------------------------------------------------
def concurrency_rows() -> list[dict]:
    rows: list[dict] = []
    n = 0

    def add_e2e(gold: dict, cat: str, **kw) -> None:
        nonlocal n
        n += 1
        rows.append(case(f"ac-{n:04d}", cat, gold, **kw))

    def add_probe(kind: str, fixture: dict, gold: dict, cat: str) -> None:
        nonlocal n
        n += 1
        rows.append(probe(f"ac-{n:04d}", cat, kind, fixture, gold))

    # independent pairs completing inside one bounded batch (40)
    for i in range(40):
        add_e2e(g_complete(f"Bounded batch run {i}.", ["SCICOMP"]),
                "bounded_batch")
    # happy-path e2e with parallel dispatch (30)
    for i in range(30):
        add_e2e(g_complete(f"Parallel dispatch run {i}.",
                           ["WEB_RESEARCH", "DOCUMENT"]),
                "parallel_dispatch")
    # duplicate prevention probes (25)
    for _ in range(25):
        add_probe("duplicate", {},
                  {"expect_deferred_reason": "already_assigned"},
                  "duplicate_prevention")
    # write-serialization probes (25)
    for _ in range(25):
        add_probe("serialize", {},
                  {"expect_deferred_reason_prefix": "resource_conflict"},
                  "write_serialization")
    while len(rows) < 120:
        n += 1
        rows.append(case(f"ac-{n:04d}", "bounded_batch",
                         g_complete(f"Batch pad run {n}.", ["GENERAL"])))
    return rows[:120]


# ---------------------------------------------------------------------------
# suite 7: mango-agent-recovery-v1 (100-160)
# ---------------------------------------------------------------------------
def recovery_rows() -> list[dict]:
    rows: list[dict] = []
    n = 0

    def add_e2e(gold: dict, cat: str, **kw) -> None:
        nonlocal n
        n += 1
        rows.append(case(f"rc-{n:04d}", cat, gold, **kw))

    def add_probe(kind: str, fixture: dict, gold: dict, cat: str) -> None:
        nonlocal n
        n += 1
        rows.append(probe(f"rc-{n:04d}", cat, kind, fixture, gold))

    # e2e recovery (100)
    for i in range(25):
        b = ("failure", "timeout", "crash")[i % 3]
        add_e2e(with_req(g_complete(f"Transient retry run {i} after {b}.",
                                    ["CODE"]), replan_min=1),
                "transient_retry",
                case_d={"worker_behavior": {"t01": b}})
    for i in range(25):
        add_e2e(g_complete(f"Crash recovery run {i}.", ["DOCUMENT"]),
                "crash_recovery",
                case_d={"worker_behavior": {"t01": "crash"}})
    for i in range(25):
        add_e2e(g_complete(f"Timeout recovery run {i}.", ["SCICOMP"]),
                "timeout_recovery",
                case_d={"worker_behavior": {"t01": "timeout"}})
    for i in range(25):
        add_e2e(with_req(g_complete(f"Revision recovery run {i}.",
                                    ["WEB_RESEARCH"]), revision_min=1),
                "revision_recovery",
                case_d={"worker_behavior": {"t02": "partial"}})
    # probes (40)
    variants = sorted(CLASSIFY_VARIANTS)
    for i in range(20):
        v = variants[i % len(variants)]
        add_probe("classify", {"variant": v},
                  {"expect_class": CLASSIFY_VARIANTS[v]}, "failure_taxonomy")
    for i in range(10):
        used = i % 3
        add_probe("revision_bound", {"used": used},
                  {"expect_ok": used < 2}, "revision_bound")
    for i in range(10):
        add_probe("preserve", {"invalidate": i % 2 == 0},
                  {"expect_loss": 0}, "work_preservation")
    while len(rows) < 150:
        n += 1
        add_e2e(g_complete(f"Recovery pad run {n}.", ["GENERAL"]),
                "transient_retry")
    return rows[:150]


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    mid = len(rows) // 2
    return rows[:mid], rows[mid:]


def write_suite(name: str, rows: list[dict],
                final_slice: slice | None = None) -> dict:
    if final_slice is not None:
        dev, final = rows[:final_slice.start], rows[final_slice]
    else:
        dev, final = split(rows)
    d = OUT / name
    dev_sha = write_jsonl(d / "dev.jsonl", dev)
    fin_sha = write_jsonl(d / "final.jsonl", final)
    man = {
        "benchmark": name,
        "total": len(rows),
        "dev_n": len(dev),
        "final_n": len(final),
        "dev_sha256": dev_sha,
        "final_sha256": fin_sha,
        "final_checksum_frozen_before_tuning": True,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "categories": sorted({r["category"] for r in rows}),
    }
    (d / "manifest.json").write_text(
        json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return man


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows_by = {
        "mango-orchestration-core-v1": core_rows(),
        "mango-orchestration-eval-v1": eval_rows(),
        "mango-orchestration-long-horizon-v1": long_horizon_rows(),
        "mango-agent-handoff-v1": handoff_rows(),
        "mango-agent-verifier-v1": verifier_rows(),
        "mango-agent-concurrency-v1": concurrency_rows(),
        "mango-agent-recovery-v1": recovery_rows(),
    }
    # long-horizon: dev = first 6 warm-up scenarios, FINAL = all 30 strict
    mans = [write_suite("mango-orchestration-long-horizon-v1",
                        rows_by.pop("mango-orchestration-long-horizon-v1"),
                        final_slice=slice(6, 36))]
    mans += [write_suite(n, r) for n, r in rows_by.items()]
    frozen = {
        "milestone": "T20 FINAL frozen",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "tuning_closed": True,
        "final_checksums": {m["benchmark"]: m["final_sha256"] for m in mans},
        "notes": "FINAL frozen at generation; no post-observation edits "
                 "permitted (T20.58/T20.60).",
    }
    (ROOT / "evaluations/t20/tuning_closed.json").write_text(
        json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{k: m[k] for k in ("benchmark", "total", "dev_n",
                                         "final_n", "final_sha256")}
                      for m in mans], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())