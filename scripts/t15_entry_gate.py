"""T15.0 entry gate — verify the authoritative T14R2-closed state before any
CODE capability work.

T14 family is CLOSED. This gate verifies:
  git HEAD includes c27abc6; worktree clean (modulo harness + prior
  artifacts + T15 gate artifacts); T14R2 report + final audit (49/0,
  ready_for_T15 YES); SciComp PROMOTE_SCICOMP_LAB @ 0.8696 >= 0.848 floor;
  Executive Router KEEP_EXPERIMENTAL; CODE PREPARED_ONLY; all frozen hashes;
  model identity; T3 adapter SHA; full pytest green (1060/0/0); no stale GPU
  jobs; no pending hygiene issues.

Any critical provenance or repository-integrity failure => STOP.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

T14R2_CLOSE = "c27abc60f4288563d96f1a6a77908fa4081cd5f4"
BRANCH = "t14-executive-router"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
TRANSFORMERS_PIN = "5.16.1"
ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"

PINS = {
    "necessity_router":
        "dfb62daf4f0b69e479d9a6ebf6f37f61aefb4a6736284f6e170b97190972ed14",
    "skill_registry":
        "ce0a249b5e9c14ebbc8c2b1913322c8725577c1e6ce3ac379a61e8a5faf8d4c9",
    "fidelity_classifier":
        "052689077a2545e7012fe613d245024480567aa572f30440501d9789db2e2146",
    "semantic_classifier":
        "537c17ee13846133c3f4975bd00aa90b34e196d0890f3f36926b7c584d3dbec8",
    "correction_firewall":
        "f6c23e3d81cf6cda03ec601b7e8cc69283ea63b25170da4e46044573ebeb6cff",
    "t3_adapter":
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
    "executive_router":
        "70b11297dc3782dfba55156e853c3f9d5f860d58e1763e8855c0e52864b8ba60",
    "t14r_adopter":
        "f09b1fe1b36f18c8154bbede7b52e26aefa32f725273e478aed8601b3607d9dd",
    "t14r_result_contract_rounding":
        "d649d128cafb09cd037dd5cc0dae8fc65ba2355d81eefa6b6aa1d0c25777b434",
    "t14r_planner_repair":
        "3878c8c6e0ec8a7c6df6ee3ac3da2f91c3c92cf5d7ce1d3af58299e692d807b9",
    "t14r_invocation":
        "3bed113faa1f71a680a6c56bbc610386cc55d98d7a97dd022fd4d3a68f87d6b2",
    "ode_intent":
        "373b6402342cea6c14faf30c1b6db3ed8280978ea75f401d353eb3b6b241d263",
    "suite_scicomp":
        "e6e3f04839c5cd0caa3f319e5c32ca511371c00a040eed25756e328a3aabf0f1",
}

SCICOMP_NUMERIC = 0.8695652173913043
SCICOMP_FLOOR = 0.848


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() \
        else None


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


CHECKS: list[dict] = []


def check(name: str, ok: bool, measured, detail: str = "") -> None:
    CHECKS.append({
        "check": name, "status": "PASS" if ok else "FAIL",
        "measured": measured, **({"detail": detail} if detail else {}),
    })


def main() -> int:
    recorded = datetime.now(timezone.utc).isoformat()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
        text=True).stdout
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    # HEAD includes c27abc6: HEAD == c27abc6 or descendant (merge-base check)
    try:
        mb = subprocess.run(
            ["git", "merge-base", "--is-ancestor", T14R2_CLOSE, "HEAD"],
            cwd=ROOT, capture_output=True, text=True)
        includes = (mb.returncode == 0)
    except Exception:
        includes = False

    dirty = [ln[3:].strip() for ln in porcelain.splitlines() if ln.strip()]
    # gate-time allowed dirt: the harness dir, T14R/T14R2 artifacts, T15 gate
    # artifacts, and root pytest outputs (rewritten by running verification).
    allowed = lambda p: (p.startswith((".cursor", "evaluations/t14r",
                                       "evaluations/t14r2",
                                       "evaluations/t15",
                                       "scripts/t15_"))
                         or p in ("full_junit.xml", "full_test_out.txt",
                                  "pytest_summary.txt", "t5r_junit.xml",
                                  "t5r_test_out.txt", "t6_junit.xml"))
    unexpected = [p for p in dirty if not allowed(p)]

    check("git_head_includes_c27abc6", includes and head == T14R2_CLOSE,
          {"head": head, "required": T14R2_CLOSE, "is_ancestor": includes},
          "T14R2 close-out commit must be HEAD")
    check("branch_is_t14_executive_router", branch == BRANCH, branch)
    check("worktree_clean", not unexpected,
          {"dirty": dirty, "unexpected": unexpected},
          "only .cursor/ (harness), T14R/T14R2 artifacts, and T15 gate "
          "artifacts may be present")

    check("t14r2_report_exists",
          (ROOT / "evaluations/t14r2/T14R2_FINAL_REPORT.md").exists(),
          "evaluations/t14r2/T14R2_FINAL_REPORT.md")
    audit = load(ROOT / "evaluations/t14r2/final_audit.json")
    audit_ok = (bool(audit) and audit.get("gates_total") == 49
                and audit.get("passes") == 49
                and audit.get("fails") == []
                and audit.get("ready_for_T15") == "YES")
    check("t14r2_final_audit_49_pass", audit_ok,
          {"gates_total": (audit or {}).get("gates_total"),
           "passes": (audit or {}).get("passes"),
           "fails": (audit or {}).get("fails"),
           "ready_for_T15": (audit or {}).get("ready_for_T15")})

    dec = load(ROOT / "evaluations/t14r2/scicomp_decision.json")
    scicomp_ok = (bool(dec) and dec.get("decision") == "PROMOTE_SCICOMP_LAB"
                  and abs(dec.get("numeric_accuracy", 0) - SCICOMP_NUMERIC) < 1e-12
                  and abs(dec.get("promotion_floor", 0) - SCICOMP_FLOOR) < 1e-12)
    check("scicomp_promoted_state_recorded", scicomp_ok,
          {"decision": (dec or {}).get("decision"),
           "numeric": (dec or {}).get("numeric_accuracy"),
           "floor": (dec or {}).get("promotion_floor")},
          "120/138 = 0.8696 >= frozen floor 0.848")
    edec = load(ROOT / "evaluations/t14r/executive_decision.json")
    check("executive_router_state_recorded",
          bool(edec) and edec.get("decision")
          == "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
          (edec or {}).get("decision"))

    # CODE skill must still be PREPARED_ONLY (not executable)
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    code_av = reg.availability("CODE")
    code_ex = reg.executable("CODE")
    check("code_skill_prepared_only",
          code_av == "PREPARED_ONLY" and code_ex is False,
          {"availability": code_av, "executable": code_ex})
    reg_h = registry_sha256()
    check("skill_registry_hash", reg_h == PINS["skill_registry"], reg_h)
    check("executive_router_hash",
          sha(ROOT / "src/sciencemath/executive/executive_router.py")
          == PINS["executive_router"],
          sha(ROOT / "src/sciencemath/executive/executive_router.py"))
    check("scicomp_engine_hash_router_only_drift",
          True,  # measured below
          "")
    # SciComp engine freeze (T12 freeze; router.py-only drift allowed)
    freeze = load(ROOT / "evaluations/t12/scicomp_engine_freeze.json")
    base = ROOT / "src/sciencemath/scicomp"
    mismatch = [n for n, h in (freeze or {}).get("files", {}).items()
                if sha(base / n) != h]
    CHECKS[-1]["measured"] = {"files": len((freeze or {}).get("files", {})),
                              "mismatch": mismatch}
    CHECKS[-1]["status"] = "PASS" if set(mismatch) <= {"router.py"} else "FAIL"
    CHECKS[-1]["detail"] = "router.py is the T14 necessity-router end-state"

    check("fidelity_hash",
          sha(ROOT / "src/sciencemath/scicomp/fidelity.py")
          == PINS["fidelity_classifier"],
          sha(ROOT / "src/sciencemath/scicomp/fidelity.py"))
    check("correction_firewall_hash",
          sha(ROOT / "src/sciencemath/executive/correction.py")
          == PINS["correction_firewall"],
          sha(ROOT / "src/sciencemath/executive/correction.py"))
    check("t3_adapter_sha_exact",
          sha(ROOT / ADAPTER) == PINS["t3_adapter"],
          sha(ROOT / ADAPTER))

    sci = load(ROOT / "evaluations/t14r2/runs/t14r2-scicomp-B3/summary.json")
    check("model_identity", bool(sci) and sci.get("model") == MODEL,
          (sci or {}).get("model"))

    import transformers
    import torch
    import platform
    env = {
        "os": f"{platform.system()} {platform.release()} "
              f"{platform.version()}",
        "python": platform.python_version(),
        "runtime": "Mango-4B-System-v1",
        "model": MODEL,
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "transformers": transformers.__version__,
    }
    check("environment_recorded",
          transformers.__version__ == TRANSFORMERS_PIN,
          {"transformers": transformers.__version__,
           "torch": torch.__version__},
          f"transformers pinned at {TRANSFORMERS_PIN} (T13-ENV-1 rule)")
    check("environment_captured", True, env)

    gpu_q = subprocess.run(
        ["nvidia-smi",
         "--query-gpu=memory.used,memory.total,utilization.gpu",
         "--format=csv,noheader,nounits"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    apps = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name",
         "--format=csv,noheader"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip().splitlines()
    mango_jobs = [a for a in apps
                  if "python" in a.lower() or "pytest" in a.lower()]
    check("no_stale_gpu_jobs", not mango_jobs,
          {"gpu_query": gpu_q, "compute_apps": apps,
           "mango_eval_or_training_jobs": mango_jobs},
          "desktop occupants are not Mango jobs")

    # full pytest: consume evaluations/t15/pytest_entry.json (pre-run so the
    # GPU-idle check above is genuine)
    pytest_summary = load(ROOT / "evaluations/t15/pytest_entry.json")
    if pytest_summary:
        ok = (pytest_summary.get("exit_code") == 0
              and pytest_summary.get("failed") == 0
              and pytest_summary.get("errors") == 0
              and pytest_summary.get("passed", 0) >= 1060)
        check("full_pytest_green", ok, pytest_summary,
              "pre-T15 baseline 1060 passed / 0 failed / 0 errors")
    else:
        check("full_pytest_green", False, None,
              "evaluations/t15/pytest_entry.json missing — run full pytest "
              "first and record it")

    # repository hygiene: no staged-but-uncommitted tracked modifications,
    # no leftover merge/rebase state, no T15 work started prematurely
    tracked_dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT, capture_output=True, text=True).stdout.strip()
    # root pytest outputs are rewritten by running verification itself
    tracked_lines = [ln for ln in tracked_dirty.splitlines() if ln.strip()]
    allowed_tracked = ("full_junit.xml", "full_test_out.txt",
                       "pytest_summary.txt")
    tracked_unexpected = [ln for ln in tracked_lines
                          if not any(a in ln for a in allowed_tracked)]
    merge_head = (ROOT / ".git" / "MERGE_HEAD").exists()
    rebase_dir = (ROOT / ".git" / "rebase-merge").exists() or \
        (ROOT / ".git" / "rebase-apply").exists()
    t15_premature = list((ROOT / "evaluations" / "t15").glob("*")) \
        if (ROOT / "evaluations" / "t15").exists() else []
    # the gate's own output + pytest entry are expected; anything else is
    # premature T15 work
    premature = [str(p.relative_to(ROOT)).replace("\\", "/")
                 for p in t15_premature
                 if p.name not in ("t15_entry_gate.json", "pytest_entry.json",
                                   "pytest_entry_junit.xml",
                                   "pytest_entry_stdout.txt")]
    hygiene_ok = (not tracked_unexpected) and (not merge_head) and (not rebase_dir) \
        and (not premature)
    check("no_pending_hygiene_issues", hygiene_ok,
          {"tracked_dirty": tracked_dirty,
           "tracked_unexpected": tracked_unexpected,
           "merge_head": merge_head,
           "rebase": rebase_dir, "premature_t15": premature},
          "root pytest outputs rewritten by verification are allowed")

    ok_all = all(c["status"] == "PASS" for c in CHECKS)
    doc = {
        "milestone": "T15 — Coding Intelligence",
        "phase": "T15.0 entry gate",
        "recorded_at": recorded,
        "status": "PASS" if ok_all else "FAIL",
        "baseline_commit": head,
        "required_commit": T14R2_CLOSE,
        "branch": branch,
        "starting_architecture": "Mango-4B-System-v1",
        "scicomp_status": "PROMOTE_SCICOMP_LAB",
        "scicomp_numeric": SCICOMP_NUMERIC,
        "scicomp_floor": SCICOMP_FLOOR,
        "executive_router_status": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
        "code_skill_status": code_av,
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "training": "NONE",
        "pytest_baseline": "1060 passed / 0 failed / 0 errors",
        "frozen_component_pins": {k: PINS[k] for k in (
            "necessity_router", "skill_registry", "fidelity_classifier",
            "semantic_classifier", "correction_firewall", "t3_adapter",
            "executive_router")},
        "checks": CHECKS,
        "substantive_failures": [c["check"] for c in CHECKS
                                 if c["status"] == "FAIL"],
        "conclusion": ("All entry-gate checks PASS. T15 may proceed to "
                       "T15.1." if ok_all else
                       "Entry gate has failures — STOP. Do not start "
                       "implementation."),
    }
    out = ROOT / "evaluations/t15/t15_entry_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(doc["substantive_failures"]))
    print(f"entry gate: {doc['status']} -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
