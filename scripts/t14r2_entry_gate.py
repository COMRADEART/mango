"""T14R2.0 entry gate — verify the authoritative T14R state before any
ODE planner work.

Bounded T14R2 milestone: ODE planner operation selection closure. T14R2
may NOT change the T14 necessity router, Executive Router, skill
registry, T13 fidelity/semantic classifiers, SciComp numerical engine,
T14R verified-result adopter, T14R deterministic rounding policy, or the
correction firewall — every one of those is hash-checked here. The only
primary-editable area is ODE planner operation selection and ODE request
construction.

Checks (all must PASS):
  git HEAD is the T14R close commit; clean worktree; T14R report/audit;
  frozen suite checksums; frozen SciComp engine (T12 freeze,
  router.py-only drift); T14 necessity router hash; Executive Router
  hash; skill registry hash; T13 fidelity + semantic classifier hashes;
  T14R adopter + rounding + repair layer hashes (T14R2 pins, recorded
  here for the first time); T10 correction firewall hash; T3 adapter
  SHA; model identity; environment (transformers pinned); GPU idle;
  full pytest.
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

T14R_CLOSE = "e8b8a23602fab04845a37d812e271977605f46b9"
BRANCH = "t14-executive-router"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
TRANSFORMERS_PIN = "5.16.1"
ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"

# pins recorded in evaluations/t14r/t14r_entry_gate.json (T14R.0) and
# evaluations/t14r/final_audit.json
PINS = {
    "fidelity_classifier":
        "052689077a2545e7012fe613d245024480567aa572f30440501d9789db2e2146",
    "semantic_classifier":
        "537c17ee13846133c3f4975bd00aa90b34e196d0890f3f36926b7c584d3dbec8",
    "correction_firewall":
        "f6c23e3d81cf6cda03ec601b7e8cc69283ea63b25170da4e46044573ebeb6cff",
    "t3_adapter":
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
    "necessity_router":
        "dfb62daf4f0b69e479d9a6ebf6f37f61aefb4a6736284f6e170b97190972ed14",
    "skill_registry":
        "ce0a249b5e9c14ebbc8c2b1913322c8725577c1e6ce3ac379a61e8a5faf8d4c9",
    "suite_scicomp":
        "e6e3f04839c5cd0caa3f319e5c32ca511371c00a040eed25756e328a3aabf0f1",
    "suite_fidelity":
        "f598825c7823f30af1f5162e8d754542f80b10bd99608f4310e0594e93cadd7e",
    "suite_conceptual":
        "16d7b4d5f3fe5c79141d9bbeed0d1921f176654c12ce2a4c271f9701b17c1fd3",
    "suite_fidelity_transform":
        "f3bad0f886bea819ba692cc955053805b01bf302edd876bd3c4b3b0da3049d5c",
    "suite_necessity_final":
        "b96da421ae5cbc333d9a6a6637a14347b1c1ce3be78eb56a820925b964ee4a62",
    "suite_executive_final":
        "ea05e60b49ba6ba2f222e75343fe193792198044d13b191ce96202fdc2020bce",
}

# T14R2 pins: frozen out-of-scope components WITHOUT a prior recorded
# pin (T14R layers + Executive Router). Computed here; the final audit
# re-verifies them against this file.
T14R2_PINS_FILES = {
    "executive_router": "src/sciencemath/executive/executive_router.py",
    "t14r_adopter": "src/sciencemath/scicomp/adoption.py",
    "t14r_result_contract_rounding":
        "src/sciencemath/scicomp/result_contract.py",
    "t14r_planner_repair": "src/sciencemath/scicomp/planner_repair.py",
    "t14r_invocation": "src/sciencemath/scicomp/invocation.py",
}


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

    dirty = [ln[3:].strip() for ln in porcelain.splitlines() if ln.strip()]
    # gate-time allowed dirt: the harness dir, T14R artifacts (including
    # the leftover run-instrument pickle), and T14R2's own gate artifacts
    allowed = lambda p: (p.startswith((".cursor", "evaluations/t14r",
                                       "evaluations/t14r2",
                                       "scripts/t14r2_")))
    unexpected = [p for p in dirty if not allowed(p)]

    check("git_head_is_t14r_close", head == T14R_CLOSE,
          {"head": head, "branch": branch},
          "T14R close e8b8a23 'T14R close-out: protection battery "
          "ALL_PASS, security 0, final audit 33/34'")
    check("branch_is_t14", branch == BRANCH, branch)
    check("worktree_clean", not unexpected,
          {"dirty": dirty, "unexpected": unexpected},
          "only .cursor/ (harness), T14R artifacts, and T14R2 gate "
          "artifacts may be dirty")

    check("t14r_final_report_present",
          (ROOT / "evaluations/t14r/T14R_FINAL_REPORT.md").exists(),
          "evaluations/t14r/T14R_FINAL_REPORT.md")
    audit = load(ROOT / "evaluations/t14r/final_audit.json")
    fails = [c["check"] for c in (audit or {}).get("checks", [])
             if c.get("status") != "PASS"]
    check("t14r_final_audit_33_of_34",
          bool(audit) and len(fails) == 1
          and fails == ["scicomp_numeric_floor"],
          {"total": len((audit or {}).get("checks", [])), "fails": fails})

    # frozen suite checksums
    suites = {
        "scicomp": ("evaluations/t11/scicomp-suite/v1/questions.jsonl",),
        "fidelity": ("evaluations/t12/suites/fidelity/v1/questions.jsonl",),
        "conceptual": (
            "evaluations/t12/suites/conceptual/v1/questions.jsonl",),
        "fidelity_transform": (
            "evaluations/t13/suites/fidelity-transform/v1/questions.jsonl",),
        "necessity_final": (
            "evaluations/t14/suites/necessity/v1/final.jsonl",),
        "executive_final": (
            "evaluations/t14/suites/executive-router/v1/final.jsonl",),
    }
    for name, (rel,) in suites.items():
        h = sha(ROOT / rel)
        ok = h == PINS[f"suite_{name}"]
        check(f"suite_checksum_{name}", ok, h)

    # frozen SciComp engine (T12 freeze; router.py-only drift allowed)
    freeze = load(ROOT / "evaluations/t12/scicomp_engine_freeze.json")
    base = ROOT / "src/sciencemath/scicomp"
    mismatch = [n for n, h in (freeze or {}).get("files", {}).items()
                if sha(base / n) != h]
    check("frozen_scicomp_engine_hash", set(mismatch) <= {"router.py"},
          {"files": len((freeze or {}).get("files", {})),
           "mismatch": mismatch},
          "router.py is the T14 necessity-router end-state (pinned below)")

    def comp_hash(rel: str, pin_name: str, label: str) -> None:
        h = sha(ROOT / rel)
        check(label, h == PINS[pin_name], h)

    comp_hash("src/sciencemath/scicomp/router.py", "necessity_router",
              "necessity_router_hash")
    comp_hash("src/sciencemath/scicomp/fidelity.py", "fidelity_classifier",
              "t13_fidelity_classifier_hash")
    comp_hash("src/sciencemath/scicomp/semantic.py", "semantic_classifier",
              "t13_semantic_classifier_hash")
    comp_hash("src/sciencemath/executive/correction.py",
              "correction_firewall", "correction_firewall_hash")
    comp_hash(ADAPTER, "t3_adapter", "t3_adapter_sha_exact")

    from sciencemath.executive.skills import registry_sha256
    reg_h = registry_sha256()
    check("skill_registry_hash", reg_h == PINS["skill_registry"], reg_h)

    # T14R2 pins for frozen out-of-scope components without prior pins
    pins_out: dict[str, str] = {}
    for name, rel in T14R2_PINS_FILES.items():
        h = sha(ROOT / rel)
        pins_out[name] = {"path": rel, "sha256": h}
        check(f"t14r2_pin_recorded_{name}", h is not None, h,
              "recorded as the T14R2 freeze pin; re-verified at final "
              "audit")

    sci = load(ROOT / "evaluations/t14r/runs/t14r-scicomp-B2/summary.json")
    check("model_identity", bool(sci) and sci.get("model") == MODEL,
          (sci or {}).get("model"))
    check("t14r_scicomp_metrics_present",
          bool(sci) and abs(
              sci.get("numeric_accuracy", 0) - 113 / 138) < 1e-12
          and sci.get("model_adoption_rate") is not None,
          {"numeric": (sci or {}).get("numeric_accuracy"),
           "adoption": (sci or {}).get("model_adoption_rate")})

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
          transformers.__version__ == TRANSFORMERS_PIN
          and torch.cuda.is_available(),
          {"transformers": transformers.__version__,
           "torch": torch.__version__},
          f"transformers pinned at {TRANSFORMERS_PIN} (T13-ENV-1 rule)")
    check("environment_captured", True, env)

    # GPU idle: no Mango eval/training compute apps
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
          "desktop occupants (launcher/overlay/IDE) are not Mango jobs")

    # full pytest (consumed from the pre-run report; the gate itself
    # does not run pytest so the GPU is genuinely idle when checked)
    pytest_summary = load(ROOT / "evaluations/t14r2/pytest_entry_summary.json")
    if pytest_summary:
        ok = (pytest_summary.get("exit_code") == 0
              and pytest_summary.get("failed") == 0
              and pytest_summary.get("errors") == 0
              and pytest_summary.get("passed", 0) >= 1030)
        check("full_pytest", ok,
              {"passed": pytest_summary.get("passed"),
               "failed": pytest_summary.get("failed"),
               "errors": pytest_summary.get("errors"),
               "skipped": pytest_summary.get("skipped"),
               "exit_code": pytest_summary.get("exit_code")},
              "baseline 1030 passed / 0 failed / 0 errors")
    else:
        check("full_pytest", False, None,
              "evaluations/t14r2/pytest_entry_summary.json missing — run "
              "pytest first")

    ok_all = all(c["status"] == "PASS" for c in CHECKS)
    doc = {
        "milestone": "T14R2 — ODE Planner Operation Selection Closure",
        "phase": "T14R2.0 entry gate",
        "recorded_at": recorded,
        "status": "PASS" if ok_all else "FAIL",
        "baseline_commit": head,
        "starting_architecture": "Mango-4B-System-v1",
        "scicomp_status": "KEEP_SCICOMP_EXPERIMENTAL",
        "executive_router_status": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "training": "NONE",
        "t11_numeric": 0.8478,
        "t12_numeric": 0.7029,
        "t13_numeric": 0.7464,
        "t14_numeric": 0.7318840579710145,
        "t14r_numeric": (sci or {}).get("numeric_accuracy"),
        "t14r_adoption": (sci or {}).get("model_adoption_rate"),
        "promotion_floor_numeric": 0.848,
        "pytest_baseline": "1030 passed / 0 failed / 0 errors",
        "frozen_component_pins": {
            k: PINS[k] for k in (
                "necessity_router", "skill_registry", "fidelity_classifier",
                "semantic_classifier", "correction_firewall", "t3_adapter")},
        "t14r2_frozen_pins_no_prior_record": pins_out,
        "checks": CHECKS,
        "substantive_failures": [c["check"] for c in CHECKS
                                 if c["status"] == "FAIL"],
        "conclusion": ("All entry-gate checks PASS. T14R2 may proceed to "
                       "T14R2.1." if ok_all else
                       "Entry gate has failures — STOP."),
    }
    out = ROOT / "evaluations/t14r2/t14r2_entry_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(doc["substantive_failures"]))
    print(f"entry gate: {doc['status']} -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())