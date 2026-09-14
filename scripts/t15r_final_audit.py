"""T15R.37 final audit — independent, no manual overrides."""
from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CODE_DIR = ROOT / "src/sciencemath/code"
V1_FINAL = ROOT / "evaluations/t15/suites/mango-code-eval-v1/final.jsonl"
V11 = ROOT / "evaluations/t15r/suites/mango-code-eval-v1.1"
RL = ROOT / "evaluations/t15r/suites/mango-code-repair-loop-v1"


def sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def sha_group(files: list[Path]) -> str:
    """Content hash keyed by repo-relative posix paths (matches entry gate)."""
    h = hashlib.sha256()
    for p in files:
        rel = p.resolve().relative_to(ROOT).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes() if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    checks: list[dict] = []

    def check(name, ok, measured, detail=""):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL",
                       "measured": measured, "detail": detail})
        return ok

    entry = load(ROOT / "evaluations/t15r/t15r_entry_gate.json")
    check("entry_gate", bool(entry) and entry.get("status") == "PASS",
          (entry or {}).get("status"))
    pins = (entry or {}).get("frozen_component_pins") or (
        (entry or {}).get("hashes") or {})

    er_h = sha(ROOT / "src/sciencemath/executive/executive_router.py")
    check("executive_router_hash_unchanged",
          er_h == (pins.get("executive_router") or
                   (entry or {}).get("hashes", {}).get("executive_router")),
          er_h)
    fid_h = sha(ROOT / "src/sciencemath/scicomp/fidelity.py")
    want_fid = (entry or {}).get("hashes", {}).get("fidelity")
    check("fidelity_hash_unchanged", fid_h == want_fid, fid_h)
    fw_h = sha(ROOT / "src/sciencemath/executive/correction.py")
    want_fw = (entry or {}).get("hashes", {}).get("correction_firewall")
    check("correction_firewall_hash_unchanged", fw_h == want_fw, fw_h)
    adp = ROOT / "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"
    adp_h = sha(adp)
    want_adp = (entry or {}).get("hashes", {}).get("t3_adapter")
    check("t3_adapter_hash_unchanged", adp_h == want_adp, adp_h)
    sci_h = sha_group(sorted((ROOT / "src/sciencemath/scicomp").glob("*.py")))
    want_sci = (entry or {}).get("hashes", {}).get("scicomp_composite")
    check("scicomp_hash_unchanged", sci_h == want_sci, sci_h)

    v1_sha = sha(V1_FINAL)
    check("t15_v1_historical_unchanged",
          v1_sha == "1676bd9e5a539efdb7d2160c1d88604d1f7d2fc8e2a7568f819189861389bddc",
          v1_sha)
    t15p = ROOT / "evaluations/t15/runs/code-final/predictions.jsonl"
    check("t15_historical_predictions_present", t15p.exists(), str(t15p))

    man11 = load(V11 / "manifest.json")
    check("v11_checksum_frozen",
          bool(man11) and sha(V11 / "final.jsonl") == man11.get("final_sha256"),
          (man11 or {}).get("final_sha256"))
    check("v11_behavioral_changes_none",
          (man11 or {}).get("behavioral_changes") == "NONE",
          (man11 or {}).get("behavioral_changes"))

    rlman = load(RL / "manifest.json")
    check("repair_microbench_checksum",
          bool(rlman) and sha(RL / "final.jsonl") == rlman.get("final_sha256"),
          (rlman or {}).get("final_sha256"))
    rsum = load(ROOT / "evaluations/t15r/repair_microbench/summary.json")
    check("repair_microbench_targets",
          bool(rsum) and rsum.get("all_pass") is True,
          (rsum or {}).get("rates"))

    freeze = load(ROOT / "evaluations/t15r/t15_failure_freeze.json")
    check("failure_freeze_present",
          bool(freeze) and freeze.get("n_executable_failures") == 28,
          (freeze or {}).get("n_executable_failures"))

    pred_p = ROOT / "evaluations/t15r/runs/code-final/predictions.jsonl"
    suite_ids = [json.loads(l)["task_id"] for l in
                 (V11 / "final.jsonl").read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    rows = []
    if pred_p.exists():
        rows = [json.loads(l) for l in pred_p.read_text(encoding="utf-8")
                .splitlines() if l.strip() and not json.loads(l).get("skipped")]
    ids = [r["task_id"] for r in rows]
    check("final_split_isolation",
          set(ids) == set(suite_ids) and len(ids) == len(suite_ids) == 139,
          f"{len(ids)}/{len(suite_ids)}")
    check("task_ids_unique", len(ids) == len(set(ids)), len(ids))
    check("no_missing_tasks", set(suite_ids) - set(ids) == set(),
          sorted(set(suite_ids) - set(ids))[:8])
    check("no_duplicate_tasks", len(ids) == len(set(ids)), None)

    summary = load(ROOT / "evaluations/t15r/runs/code-final/summary.json")
    check("model_identity",
          ((summary or {}).get("model") or {}).get("model")
          == "Qwen/Qwen3-4B-Instruct-2507",
          (summary or {}).get("model"))

    code_files = sorted(CODE_DIR.glob("*.py"))
    check("code_implementation_hash_recorded",
          bool(code_files), sha_group(code_files))
    check("repair_loop_present",
          (CODE_DIR / "repair_state.py").exists(),
          sha(CODE_DIR / "repair_state.py"))

    fl = load(ROOT / "evaluations/t15r/floors_evaluation.json")
    check("floors_evaluated", bool(fl), (fl or {}).get("decision"))
    cfail = (fl or {}).get("critical_failures") or []
    qfail = (fl or {}).get("quality_failures") or []
    check("critical_safety_floors", cfail == [], cfail)
    check("bug_fix_metrics_recorded",
          "bug_fix_success" in ((fl or {}).get("floors") or {}),
          ((fl or {}).get("floors") or {}).get("bug_fix_success"))
    check("executable_metrics_recorded",
          "executable_task_success" in ((fl or {}).get("floors") or {}),
          ((fl or {}).get("floors") or {}).get("executable_task_success"))
    check("unrelated_edit_metrics_recorded",
          "unrelated_edit_rate" in ((fl or {}).get("floors") or {}),
          ((fl or {}).get("floors") or {}).get("unrelated_edit_rate"))

    prot = load(ROOT / "evaluations/t15r/protection/regression_summary.json")
    check("protection_battery",
          bool(prot) and prot.get("status") == "ALL_PASS",
          (prot or {}).get("status"))
    sec = load(ROOT / "evaluations/t15r/protection/security_summary.json")
    check("security_zero_violations",
          bool(sec) and sec.get("violations") == 0,
          (sec or {}).get("violations"))
    sci = load(ROOT / "evaluations/t15r/protection/t15r-scicomp-recheck/summary.json")
    check("scicomp_numeric_holds",
          bool(sci) and (sci.get("numeric_accuracy") or 0) >= 0.848
          and (sci.get("pipeline_exception_count") or 0) == 0,
          {"numeric": (sci or {}).get("numeric_accuracy"), "floor": 0.848})

    xml = ROOT / "evaluations/t15r/full_junit.xml"
    if not xml.exists():
        xml = ROOT / "full_junit.xml"
    counts = {}
    ok_py = False
    if xml.exists():
        ts = ET.parse(xml).getroot()
        if ts.tag == "testsuites":
            ts = ts.find("testsuite")
        counts = {k: int(ts.get(k) or 0)
                  for k in ("tests", "failures", "errors", "skipped")}
        ok_py = counts.get("failures") == 0 and counts.get("errors") == 0 \
            and counts.get("tests", 0) >= 1000
    check("pytest_green", ok_py, counts)

    check("no_training",
          (entry or {}).get("training") == "NONE"
          and (entry or {}).get("weight_promotion") == "NO",
          {"training": (entry or {}).get("training"),
           "weights": (entry or {}).get("weight_promotion")})
    check("no_paid_compute",
          (entry or {}).get("paid_compute") == "NOT_USED",
          (entry or {}).get("paid_compute"))

    from sciencemath.executive.skills import SkillRegistry
    av = SkillRegistry().availability("CODE")
    decision = (fl or {}).get("decision")
    promote = decision == "PROMOTE_CODE_SKILL" and not cfail and not qfail \
        and (prot or {}).get("status") == "ALL_PASS" and ok_py
    if promote:
        want_av = "ACTIVE"
        code_decision = "PROMOTE_CODE_SKILL"
    elif decision == "REJECT_CODE_SKILL":
        want_av = "DISABLED"
        code_decision = "REJECT_CODE_SKILL"
    else:
        want_av = av  # KEEP experimental/prepared
        code_decision = "KEEP_CODE_SKILL_EXPERIMENTAL"
    check("code_decision_consistent",
          (not promote) or av == "ACTIVE",
          {"decision": code_decision, "availability": av})
    check("skill_availability_recorded", av in (
        "ACTIVE", "EXPERIMENTAL", "PREPARED_ONLY", "DISABLED"), av)

    all_pass = all(c["status"] == "PASS" for c in checks)
    out = {
        "milestone": "T15R final audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "gates_total": len(checks),
        "passes": sum(1 for c in checks if c["status"] == "PASS"),
        "fails": [c["check"] for c in checks if c["status"] == "FAIL"],
        "checks": checks,
        "code_decision": code_decision,
        "code_availability": av,
        "manual_override": False,
        "passed": all_pass,
        "failed": not all_pass,
    }
    dest = ROOT / "evaluations/t15r/final_audit.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passes": out["passes"], "fails": out["fails"],
                      "decision": code_decision, "availability": av},
                     indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
