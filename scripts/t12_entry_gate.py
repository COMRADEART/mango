"""T12.0 entry gate + T12.1 engine freeze.

Verifies the exact T11-closed state (commit c05396f) before any T12
implementation work: T11 report/audit/suite-checksum presence, firewall
and T3-adapter hash pins, scicomp engine source hashes (frozen for T12),
full pytest with zero failures/errors, GPU idle, and local/remote git
state.

Writes:
  evaluations/t12/t12_entry_gate.json
  evaluations/t12/scicomp_engine_freeze.json   (T12.1)

Exit 0 only if every gate check passes; otherwise STOP before T12.2.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

T11_HEAD = "c05396f"
FIREWALL_SHA = "f6c23e3d81cf6cda03ec601b7e8cc69283ea63b25170da4e46044573ebeb6cff"
ADAPTER_SHA = "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668"
T11_SUITE_SHA = "e6e3f04839c5cd0caa3f319e5c32ca511371c00a040eed25756e328a3aabf0f1"

ENGINE_FILES = [
    "schemas.py", "sandbox.py", "registry.py",
    "executor.py", "diagnostics.py", "linear_algebra.py", "calculus.py",
    "roots.py", "ode.py", "optimization.py", "statistics.py",
    "interpolation.py", "parameter_sweep.py", "trust.py", "verifier.py",
    "invocation.py", "router.py",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(name: str, ok: bool, detail) -> dict:
    return {"check": name, "status": "PASS" if ok else "FAIL",
            "detail": detail}


def main() -> int:
    checks = []

    # 1. T11 commit is HEAD
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                          capture_output=True, text=True).stdout.strip()
    head_short = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=str(ROOT), capture_output=True,
                                text=True).stdout.strip()
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=str(ROOT),
        capture_output=True, text=True).stdout.strip()
    checks.append(check("t11_commit_is_head",
                        head_short == T11_HEAD and "T11 close" in subject,
                        {"head": head, "short": head_short,
                         "subject": subject}))

    # 10. local/remote git state
    remote = subprocess.run(["git", "rev-parse", "origin/main"], cwd=str(ROOT),
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                           capture_output=True, text=True).stdout
    dirty_paths = sorted(line[3:].strip() for line in dirty.splitlines()
                         if line.strip())
    checks.append(check("git_state_recorded", True, {
        "local_head": head, "remote_main": remote,
        "local_only_commit": remote != head,
        "working_tree_paths": dirty_paths,
        "note": "pre-existing T10/T11-closed tree state; unchanged by T12.0",
    }))

    # 2/3. T11 final report + audit
    report = ROOT / "evaluations/t11/T11_FINAL_REPORT.md"
    checks.append(check("t11_final_report_present", report.exists(),
                        {"path": str(report)}))
    audit_path = ROOT / "evaluations/t11/final_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) \
        if audit_path.exists() else {}
    fails = [c["check"] for c in audit.get("checks", [])
             if c.get("status") != "PASS"]
    checks.append(check(
        "t11_final_audit_state_matches_closure",
        audit_path.exists()
        and audit.get("all_checks_pass") is False
        and fails == ["t11.40_adoption>=90%"],
        {"path": str(audit_path), "n_checks": len(audit.get("checks", [])),
         "failed": fails,
         "note": "T11 closed 21/22; sole expected FAIL is the adoption "
                 "gate that T12 re-measures"}))

    # 4. frozen T11 scicomp suite checksum
    suite = ROOT / "evaluations/t11/scicomp-suite/v1"
    suite_sha = sha256_file(suite / "questions.jsonl")
    checks.append(check("t11_suite_checksum",
                        suite_sha == T11_SUITE_SHA
                        == (suite / "checksum.txt").read_text(
                            encoding="utf-8").strip(),
                        {"sha256": suite_sha}))

    # 5. numerical engine source hashes -> T12.1 freeze
    scicomp = ROOT / "src/sciencemath/scicomp"
    freeze, missing = {}, []
    for name in ENGINE_FILES:
        p = scicomp / name
        if p.exists():
            freeze[name] = sha256_file(p)
        else:
            missing.append(name)
    checks.append(check("engine_sources_frozen", not missing,
                        {"files": len(freeze), "missing": missing}))
    freeze_doc = {
        "milestone": "T12.1 — scicomp engine freeze",
        "frozen_at": datetime.now().isoformat(),
        "baseline_commit": head,
        "policy": "T12 may modify planner schema/validation, routing guard, "
                  "and result-adoption interface. Solver behavior must NOT "
                  "change unless an independent deterministic engine defect "
                  "is proven. Any hash below changing during T12 must be "
                  "explicitly justified in the final report.",
        "files": freeze,
    }
    out_freeze = ROOT / "evaluations/t12/scicomp_engine_freeze.json"
    out_freeze.parent.mkdir(parents=True, exist_ok=True)
    out_freeze.write_text(json.dumps(freeze_doc, indent=2) + "\n",
                          encoding="utf-8")

    # 6/7. firewall + adapter pins
    fw_sha = sha256_file(ROOT / "src/sciencemath/executive/correction.py")
    checks.append(check("firewall_sha_unchanged", fw_sha == FIREWALL_SHA,
                        {"sha256": fw_sha}))
    ad_sha = sha256_file(
        ROOT / "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors")
    checks.append(check("t3_adapter_sha_exact", ad_sha == ADAPTER_SHA,
                        {"sha256": ad_sha}))

    # 8/9. full pytest, 0 failures/errors
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--junitxml",
         str(ROOT / "evaluations/t12/pytest_entry.xml")],
        cwd=str(ROOT), capture_output=True, text=True)
    counts = {}
    xml_path = ROOT / "evaluations/t12/pytest_entry.xml"
    if xml_path.exists():
        ts = ET.parse(xml_path).getroot()
        if ts.tag == "testsuites":
            ts = ts.find("testsuite")
        counts = {k: int(ts.get(k) or 0)
                  for k in ("tests", "failures", "errors", "skipped")}
    checks.append(check("full_pytest_zero_failures",
                        counts.get("failures") == 0
                        and counts.get("errors") == 0
                        and counts.get("tests", 0) >= 878,
                        counts))

    # 11. GPU idle
    try:
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
             "--format=csv,noheader"], capture_output=True, text=True)
        mem, util = [p.strip() for p in smi.stdout.strip().split(",")]
        idle = mem in ("0 MiB", "N/A") and util in ("0", "0 %", "N/A")
    except OSError:
        idle, mem, util = False, "nvidia-smi-missing", "?"
    checks.append(check("gpu_idle", idle, {"memory_used": mem,
                                           "utilization_pct": util}))

    all_pass = all(c["status"] == "PASS" for c in checks)
    doc = {
        "milestone": "T12 — SciComp Planner Fidelity and Promotion Closure",
        "phase": "T12.0 entry gate",
        "recorded_at": datetime.now().isoformat(),
        "status": "PASS" if all_pass else "FAIL",
        "checks": checks,
        "engine_freeze": "evaluations/t12/scicomp_engine_freeze.json",
    }
    out = ROOT / "evaluations/t12/t12_entry_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    for c in checks:
        print(f"[{c['status']}] {c['check']}: "
              f"{json.dumps(c['detail'])[:160]}")
    print("T12_ENTRY_GATE_PASS" if all_pass else "T12_ENTRY_GATE_FAIL")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())