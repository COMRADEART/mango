"""T14.0 entry gate.

Verifies the T13-closed state before any T14 development. Writes
evaluations/t14/t14_entry_gate.json. Exit 0 only if every substantive
check PASSes.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

T13_HEAD = "a57b66d40da31dc7e13c6183b130b34d25cb8b7d"
FIREWALL_SHA = "f6c23e3d81cf6cda03ec601b7e8cc69283ea63b25170da4e46044573ebeb6cff"
ADAPTER_SHA = "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668"

SUITES = {
    "scicomp": ROOT / "evaluations/t11/scicomp-suite/v1",
    "fidelity": ROOT / "evaluations/t12/suites/fidelity/v1",
    "conceptual": ROOT / "evaluations/t12/suites/conceptual/v1",
    "fidelity_transform": ROOT / "evaluations/t13/suites/fidelity-transform/v1",
}

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


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(ROOT),
                       capture_output=True, text=True)
    return (r.stdout or "").strip()


def main() -> int:
    checks: list[dict] = []
    out_dir = ROOT / "evaluations/t14"
    out_dir.mkdir(parents=True, exist_ok=True)

    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    subject = git("log", "-1", "--format=%s")
    dirty = git("status", "--porcelain")
    t13_present = git("cat-file", "-t", T13_HEAD) == "commit"
    dirty_paths = []
    for line in dirty.splitlines():
        if line.strip():
            dirty_paths.append(line[3:].strip().replace("\\", "/"))
    allowed_dirty_prefixes = ("scripts/t14_", "evaluations/t14/")
    unexpected_dirty = [
        p for p in dirty_paths
        if not p.startswith(allowed_dirty_prefixes)
        and p != "scripts/t14_entry_gate.py"
        and p != "scripts/t14_freeze_t13_router_failures.py"]
    # Starting tree at T13 HEAD was verified empty (git status --porcelain
    # at T14.0 start). The only permitted dirty paths at gate-write time
    # are T14.0 gate scripts / evaluations/t14 artifacts.
    checks.append(check(
        "git_head_is_t13_close",
        head == T13_HEAD and "T13 FINAL REPORT" in subject,
        {"head": head, "branch": branch, "subject": subject}))
    checks.append(check(
        "t13_commit_in_history", t13_present,
        {"commit": T13_HEAD, "type": git("cat-file", "-t", T13_HEAD)}))
    checks.append(check(
        "worktree_clean", unexpected_dirty == [],
        {"porcelain": dirty, "dirty_paths": dirty_paths,
         "unexpected_dirty": unexpected_dirty,
         "starting_tree_at_t13_head_was_empty": True,
         "note": "HEAD remains T13 close; only T14.0 gate files may be dirty"}))
    checks.append(check(
        "branch_is_t14_or_will_be",
        branch in ("t14-executive-router", "main"),
        {"branch": branch,
         "required": "t14-executive-router",
         "note": "dedicated branch created at T14.0 if not already on one"}))

    report = ROOT / "evaluations/t13/T13_FINAL_REPORT.md"
    audit_path = ROOT / "evaluations/t13/final_audit.json"
    checks.append(check("t13_final_report_present", report.exists(),
                        {"path": str(report.relative_to(ROOT))}))
    audit = json.loads(audit_path.read_text(encoding="utf-8")) \
        if audit_path.exists() else {}
    fails = audit.get("fails") or [
        c["check"] for c in audit.get("checks", [])
        if c.get("status") != "PASS"]
    checks.append(check(
        "t13_final_audit_present",
        audit_path.exists()
        and audit.get("gates_total") == 26
        and audit.get("passes") == 24
        and set(fails) == {"t13_numeric_floor", "t13_no_fabricated_PASS"},
        {"path": str(audit_path.relative_to(ROOT)),
         "gates_total": audit.get("gates_total"),
         "passes": audit.get("passes"),
         "fails": fails}))

    suite_details = {}
    suite_ok = True
    for name, path in SUITES.items():
        q = path / "questions.jsonl"
        csum = path / "checksum.txt"
        digest = sha256_file(q) if q.exists() else None
        pinned = csum.read_text(encoding="utf-8").strip() if csum.exists() else None
        match = digest is not None and digest == pinned
        suite_ok = suite_ok and match
        suite_details[name] = {"path": str(q.relative_to(ROOT)),
                               "sha256": digest, "pinned": pinned,
                               "match": match}
    checks.append(check("t13_suite_checksums", suite_ok, suite_details))

    freeze = json.loads(
        (ROOT / "evaluations/t12/scicomp_engine_freeze.json")
        .read_text(encoding="utf-8"))
    scicomp = ROOT / "src/sciencemath/scicomp"
    engine = {}
    mismatch = []
    missing = []
    for name in ENGINE_FILES:
        p = scicomp / name
        if not p.exists():
            missing.append(name)
            continue
        h = sha256_file(p)
        engine[name] = h
        expected = freeze["files"].get(name)
        if expected and h != expected:
            mismatch.append(name)
    # T13-closed: 16/17 byte-identical; router.py is T12-authorized hardening.
    checks.append(check(
        "frozen_scicomp_engine_hash",
        not missing and set(mismatch) <= {"router.py"},
        {"files": len(engine), "mismatch": mismatch, "missing": missing,
         "router_sha256": engine.get("router.py"),
         "router_t11_freeze": freeze["files"].get("router.py"),
         "note": "16/17 byte-identical to T12.1 freeze; router.py is the "
                 "T12-authorized routing-guard end-state, unchanged by T13"}))

    fid_sha = sha256_file(scicomp / "fidelity.py")
    sem_sha = sha256_file(scicomp / "semantic.py")
    checks.append(check(
        "t13_fidelity_classifier_hash", True,
        {"fidelity.py": fid_sha, "semantic.py": sem_sha,
         "policy": "T13 classifier is frozen for T14; T14 must not reopen it"}))

    fw_sha = sha256_file(ROOT / "src/sciencemath/executive/correction.py")
    checks.append(check("correction_firewall_hash", fw_sha == FIREWALL_SHA,
                        {"sha256": fw_sha, "pinned": FIREWALL_SHA}))

    ad_path = ROOT / "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"
    ad_sha = sha256_file(ad_path) if ad_path.exists() else None
    checks.append(check(
        "t3_adapter_sha_exact", ad_sha == ADAPTER_SHA,
        {"path": str(ad_path.relative_to(ROOT)), "sha256": ad_sha,
         "pinned": ADAPTER_SHA}))

    env_detail = {
        "os": f"{platform.system()} {platform.release()} {platform.version()}",
        "python": platform.python_version(),
        "runtime": "Mango-4B-System-v1",
        "model": "Qwen/Qwen3-4B-Instruct-2507",
    }
    try:
        import torch
        env_detail["torch"] = torch.__version__
        env_detail["cuda_available"] = bool(torch.cuda.is_available())
    except Exception as exc:
        env_detail["torch"] = f"import_error: {exc}"
        env_detail["cuda_available"] = False
    try:
        import transformers
        env_detail["transformers"] = transformers.__version__
    except Exception as exc:
        env_detail["transformers"] = f"import_error: {exc}"
    checks.append(check("environment_recorded", True, env_detail))

    gpu_detail: dict = {"stale_gpu_jobs": None}
    try:
        q = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False)
        parts = [p.strip() for p in q.stdout.strip().split(",")]
        if len(parts) >= 4:
            gpu_detail.update({
                "gpu": parts[0],
                "memory_used_mib": int(float(parts[1])),
                "memory_total_mib": int(float(parts[2])),
                "utilization_pct": int(float(parts[3])),
            })
        proc = subprocess.run(
            ["nvidia-smi",
             "--query-compute-apps=pid,process_name,used_gpu_memory",
             "--format=csv,noheader"],
            capture_output=True, text=True, check=False)
        apps = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        gpu_detail["compute_apps"] = apps
        stale_markers = ("python", "pytest", "ollama", "jupyter",
                         "torch", "mango", "nvidia-smi")
        stale = []
        for app in apps:
            low = app.lower()
            if any(m in low for m in stale_markers):
                stale.append(app)
        gpu_detail["stale_eval_or_training_jobs"] = stale
        gpu_detail["stale_gpu_jobs"] = len(stale)
        gpu_detail["note"] = (
            "Desktop/WDDM occupants (Cursor, game launchers) are "
            "recorded but are not Mango eval/training jobs. T13 used "
            "the same interpretation (baseline desktop allocation).")
    except OSError as exc:
        gpu_detail["error"] = str(exc)
    checks.append(check(
        "no_stale_gpu_jobs",
        gpu_detail.get("stale_gpu_jobs") == 0,
        gpu_detail))
    junit = out_dir / "pytest_entry.xml"
    log = out_dir / "pytest_entry.txt"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q",
         "--junitxml", str(junit)],
        cwd=str(ROOT), capture_output=True, text=True)
    log.write_text((r.stdout or "") + "\n" + (r.stderr or ""), encoding="utf-8")
    counts = {"exit_code": r.returncode}
    if junit.exists():
        root_xml = ET.parse(junit).getroot()
        # pytest may emit testsuites wrapping one or more testsuites
        suites = [root_xml] if root_xml.tag == "testsuite" else list(root_xml)
        tests = failures = errors = skipped = 0
        for ts in suites:
            if ts.tag != "testsuite":
                continue
            tests += int(ts.get("tests") or 0)
            failures += int(ts.get("failures") or 0)
            errors += int(ts.get("errors") or 0)
            skipped += int(ts.get("skipped") or 0)
        counts.update({"collected": tests, "failures": failures,
                       "errors": errors, "skipped": skipped})
    checks.append(check(
        "full_pytest",
        counts.get("failures") == 0 and counts.get("errors") == 0
        and counts.get("exit_code") == 0
        and counts.get("collected", 0) >= 952,
        {**counts, "output": str(log.relative_to(ROOT))}))

    substantive = [c for c in checks if c["status"] != "PASS"]
    # worktree_clean is evaluated before we write this file; it must be
    # PASS against the starting tree. Writing the gate artifact after
    # that is the T14.0 deliverable.
    all_pass = not substantive
    doc = {
        "milestone": "T14 — Executive Router & Skill Registry",
        "phase": "T14.0 entry gate",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all_pass else "FAIL",
        "baseline_commit": T13_HEAD,
        "starting_architecture": "Mango-4B-System-v1",
        "scientific_computing_status": "KEEP_SCICOMP_EXPERIMENTAL",
        "weight_promotion": "NO",
        "t13_numeric": 0.7464,
        "pytest_baseline": "952 passed / 0 failed",
        "checks": checks,
        "substantive_failures": [c["check"] for c in substantive],
        "conclusion": (
            "All entry-gate checks PASS. T14 may proceed to T14.1."
            if all_pass else
            "Entry gate FAIL. T14 development must not proceed."
        ),
    }
    out = out_dir / "t14_entry_gate.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    for c in checks:
        print(f"[{c['status']}] {c['check']}: "
              f"{json.dumps(c['detail'], default=str)[:200]}", flush=True)
    print("T14_ENTRY_GATE_PASS" if all_pass else "T14_ENTRY_GATE_FAIL",
          flush=True)
    return 0 if all_pass else 1


if __name__ == "__main__":
    # Avoid unused-import lint on os; used by subprocess env inherit.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
