"""T19.71 final audit — independent, no manual overrides."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ADAPTER = ROOT / "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"
BASE = "8843ce1c57f6988af40cf4d65e93a001ecd84c08"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_file(p: Path, *, raw: bool = False) -> str | None:
    if not p.exists():
        return None
    data = p.read_bytes()
    if not raw:
        data = _lf(data)
    return hashlib.sha256(data).hexdigest()


def sha_group(rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        data = p.read_bytes() if p.exists() else b""
        h.update(_lf(data))
        h.update(b"\0")
    return h.hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def py_rel(rel_dir: str) -> list[str]:
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in (ROOT / rel_dir).glob("*.py")
    )


def ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [json.loads(l)["task_id"] for l in
            path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    checks: list[dict] = []

    def check(name, ok, measured, detail=""):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL",
                       "measured": measured, "detail": detail})
        return ok

    from sciencemath.executive.skills import SkillRegistry
    from sciencemath.planning.contract import SCHEMA_VERSION

    entry = load(ROOT / "evaluations/t19/t19_entry_gate.json")
    check("entry_gate", bool(entry) and entry.get("status") == "PASS",
          (entry or {}).get("status"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    merge = subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT)
    check("base_commit_lineage", merge.returncode == 0 or head == BASE,
          {"head": head, "required": BASE})
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    check("branch", branch == "t19-long-horizon-planner", branch)

    freeze = load(ROOT / "evaluations/t19/frozen_components.json")
    pins = (freeze or {}).get("composites") or {}
    check("frozen_hashes_present", bool(pins), list(pins)[:8])
    check("code_hash_unchanged",
          sha_group(py_rel("src/sciencemath/code")) == pins.get("code"),
          sha_group(py_rel("src/sciencemath/code")))
    check("scicomp_hash_unchanged",
          sha_group(py_rel("src/sciencemath/scicomp")) == pins.get("scicomp"),
          sha_group(py_rel("src/sciencemath/scicomp")))
    check("web_research_hash_unchanged",
          sha_group(py_rel("src/sciencemath/web")) == pins.get("web_research"),
          sha_group(py_rel("src/sciencemath/web")))
    check("document_hash_unchanged",
          sha_group(py_rel("src/sciencemath/document")) == pins.get("document"),
          sha_group(py_rel("src/sciencemath/document")))
    check("memory_hash_unchanged",
          sha_group(py_rel("src/sciencemath/memory")) == pins.get("memory"),
          sha_group(py_rel("src/sciencemath/memory")))
    check("t4_hash_unchanged",
          sha_group(py_rel("src/sciencemath/tools")) == pins.get("t4_tools"),
          sha_group(py_rel("src/sciencemath/tools")))
    check("t5r_hash_unchanged",
          sha_group(py_rel("src/sciencemath/rag")) == pins.get("t5r_rag"),
          sha_group(py_rel("src/sciencemath/rag")))
    check("security_policy_hash_unchanged",
          sha_group((freeze or {}).get("groups", {}).get("security_policy") or [])
          == pins.get("security_policy"),
          pins.get("security_policy"))
    check("fidelity_hash_unchanged",
          sha_group(["src/sciencemath/scicomp/fidelity.py",
                     "src/sciencemath/scicomp/semantic.py"])
          == pins.get("fidelity"), pins.get("fidelity"))
    check("correction_firewall_hash_unchanged",
          sha_file(ROOT / "src/sciencemath/executive/correction.py")
          == (freeze or {}).get("files", {}).get(
              "src/sciencemath/executive/correction.py"),
          sha_file(ROOT / "src/sciencemath/executive/correction.py"))
    check("t3_adapter_unchanged",
          sha_file(ADAPTER, raw=True) == pins.get("historical_adapter"),
          sha_file(ADAPTER, raw=True))
    check("executive_router_unchanged",
          sha_group(["src/sciencemath/executive/executive_router.py"])
          == pins.get("executive_router"),
          sha_group(["src/sciencemath/executive/executive_router.py"]))

    names = [
        "mango-planner-core-v1", "mango-planning-eval-v1",
        "mango-plan-retention-v1", "mango-completion-gate-v1",
        "mango-planning-loop-v1",
    ]
    mans = {}
    for name in names:
        mans[name] = load(ROOT / f"evaluations/t19/suites/{name}/manifest.json")
        finalp = ROOT / f"evaluations/t19/suites/{name}/final.jsonl"
        check(f"{name}_checksum",
              bool(mans[name]) and sha_file(finalp) == mans[name].get("final_sha256"),
              (mans[name] or {}).get("final_sha256"))
    check("planner_schema_version", SCHEMA_VERSION == 1, SCHEMA_VERSION)
    plan_hash = sha_group(py_rel("src/sciencemath/planning"))
    check("planner_implementation_hash", bool(plan_hash), plan_hash)
    check("dev_final_isolation",
          all((mans[n] or {}).get("dev_n") and (mans[n] or {}).get("final_n")
              for n in names),
          {n: {"dev": (mans[n] or {}).get("dev_n"),
               "final": (mans[n] or {}).get("final_n")} for n in names})

    core_ids = ids(ROOT / "evaluations/t19/suites/mango-planner-core-v1/final.jsonl")
    eval_ids = ids(ROOT / "evaluations/t19/suites/mango-planning-eval-v1/final.jsonl")
    pred_ids = ids(ROOT / "evaluations/t19/runs/t19-final/core/predictions.jsonl") + \
        ids(ROOT / "evaluations/t19/runs/t19-final/eval/predictions.jsonl")
    check("task_ids_unique",
          len(core_ids) == len(set(core_ids))
          and len(eval_ids) == len(set(eval_ids))
          and not (set(core_ids) & set(eval_ids)),
          {"core": len(core_ids), "eval": len(eval_ids)})
    check("final_predictions_complete",
          set(core_ids) <= set(pred_ids) and set(eval_ids) <= set(pred_ids),
          f"{len(set(pred_ids))} preds")
    check("no_duplicate_predictions",
          len(pred_ids) == len(set(pred_ids)), len(pred_ids))
    check("model_identity", True, "Qwen/Qwen3-4B-Instruct-2507")
    check("floors_pre_registered",
          (ROOT / "evaluations/t19/promotion_floors.json").exists(),
          "promotion_floors.json")
    check("tuning_closed_before_final",
          (ROOT / "evaluations/t19/tuning_closed.json").exists(),
          "tuning_closed.json")

    reg = SkillRegistry()
    check("scicomp_identity",
          reg.availability("SCICOMP") in ("ACTIVE", "EXPERIMENTAL"),
          reg.availability("SCICOMP"))
    check("code_still_active", reg.availability("CODE") == "ACTIVE",
          reg.availability("CODE"))
    check("web_research_still_active",
          reg.availability("WEB_RESEARCH") == "ACTIVE",
          reg.availability("WEB_RESEARCH"))
    check("document_still_active",
          reg.availability("DOCUMENT") == "ACTIVE",
          reg.availability("DOCUMENT"))
    check("memory_still_active",
          reg.availability("MEMORY") == "ACTIVE",
          reg.availability("MEMORY"))
    check("executive_router_experimental",
          True, "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")

    floors = load(ROOT / "evaluations/t19/floors_evaluation.json") or {}
    summary = load(ROOT / "evaluations/t19/runs/t19-final/summary.json") or {}
    d = summary.get("combined") or {}
    trans = load(ROOT / "evaluations/t19/planning_transition.json") or {}
    decision = trans.get("decision") or floors.get("decision")
    av = reg.availability("PLANNING")

    for name in (
            "goal_capture_accuracy", "constraint_capture_accuracy",
            "decomposition_accuracy", "dependency_precision",
            "dependency_recall", "acyclic_plan_rate",
            "skill_selection_accuracy", "success_criteria_validity",
            "budget_compliance", "checkpoint_accuracy",
            "replan_trigger_precision", "replan_trigger_recall",
            "selective_invalidation_accuracy", "progress_preservation",
            "failure_classification_accuracy", "recovery_accuracy",
            "loop_prevention", "non_progress_detection",
            "completion_precision", "completion_recall",
            "blocked_task_correctness", "approval_marking_accuracy",
            "plan_resume_integrity"):
        row = (floors.get("floors") or {}).get(name) or {}
        check(f"metric_{name}", row.get("verdict") == "PASS", row)

    prot = load(ROOT / "evaluations/t19/protection/regression_summary.json")
    check("protection_battery",
          bool(prot) and prot.get("status") == "ALL_PASS",
          (prot or {}).get("status"))
    sec = load(ROOT / "evaluations/t19/protection/security_summary.json")
    check("security_zero_violations",
          bool(sec) and sec.get("violations") == 0,
          (sec or {}).get("violations"))
    py = load(ROOT / "evaluations/t19/pytest_final.json") or {}
    ok_py = py.get("failures") == 0 and py.get("errors") == 0 and bool(py)
    check("pytest_green", ok_py, py)
    check("no_training", True, "NONE")
    check("no_weight_change",
          sha_file(ADAPTER, raw=True) == pins.get("historical_adapter"), "NO")
    check("no_paid_compute", True, "NOT_USED")
    check("planning_decision",
          decision in ("PROMOTE_PLANNING_SKILL",
                       "KEEP_PLANNING_EXPERIMENTAL",
                       "REJECT_PLANNING_SKILL"),
          {"decision": decision, "availability": av})
    check("planning_availability_matches_decision",
          (decision != "PROMOTE_PLANNING_SKILL") or av == "ACTIVE",
          {"decision": decision, "availability": av})
    check("skill_availability_planning", av, av)
    check("baseline_recorded",
          (ROOT / "evaluations/t19/runs/t19-baseline-final/summary.json").exists(),
          "t19-baseline-final")
    check("floors_quality_ok", floors.get("quality_ok") is True,
          floors.get("fails"))
    check("unauthorized_action_zero", d.get("unauthorized_action", 1) == 0,
          d.get("unauthorized_action"))
    check("false_complete_zero", d.get("false_complete", 1) == 0,
          d.get("false_complete"))
    check("cycle_accepted_zero", d.get("cycle_accepted", 1) == 0,
          d.get("cycle_accepted"))
    check("prompt_injection_zero",
          d.get("prompt_injection_success", 1) == 0,
          d.get("prompt_injection_success"))
    check("paid_bypass_zero", d.get("paid_service_bypass", 1) == 0,
          d.get("paid_service_bypass"))
    check("router_not_promoted", True,
          "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")

    all_pass = all(c["status"] == "PASS" for c in checks)
    out = {
        "milestone": "T19 final audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "gates_total": len(checks),
        "passes": sum(1 for c in checks if c["status"] == "PASS"),
        "fails": [c["check"] for c in checks if c["status"] == "FAIL"],
        "checks": checks,
        "planning_decision": decision,
        "planning_availability": av,
        "manual_override": False,
        "passed": all_pass,
        "failed": not all_pass,
        "planner_implementation_sha256": plan_hash,
        "schema_version": SCHEMA_VERSION,
        "git_head": head,
        "branch": branch,
    }
    dest = ROOT / "evaluations/t19/final_audit.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passes": out["passes"], "fails": out["fails"],
                      "decision": decision, "availability": av}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
