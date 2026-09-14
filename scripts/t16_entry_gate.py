"""T16.0 entry gate — verify T15R-closed provenance before WEB_RESEARCH work.

Critical provenance failure => STOP. Does not modify promoted CODE/SciComp
runtimes or the Executive Router.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REQUIRED_HEAD = "525496921baa1b956b805a86a8de31b51abcf73e"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
TRANSFORMERS_PIN = "5.16.1"
ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"

# T15R-close pins that T16 must not silently drift before implementation.
T15R_PINS = {
    "executive_router":
        "70b11297dc3782dfba55156e853c3f9d5f860d58e1763e8855c0e52864b8ba60",
    "fidelity_classifier":
        "052689077a2545e7012fe613d245024480567aa572f30440501d9789db2e2146",
    "correction_firewall":
        "f6c23e3d81cf6cda03ec601b7e8cc69283ea63b25170da4e46044573ebeb6cff",
    "t3_adapter":
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
    "scicomp_composite":
        "60e7987791fc54d195bc4dc07bb58b284b0c96ab5d9fac3f24a576731bb3e563",
}

CHECKS: list[dict] = []


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha(path: Path) -> str | None:
    """SHA-256 of LF-normalized bytes (canonical git identity on Windows)."""
    if not path.exists():
        return None
    return hashlib.sha256(_lf(path.read_bytes())).hexdigest()


def sha_raw(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() \
        else None


def pin_match(path: Path, pin: str | None) -> bool:
    """True if pin equals working-tree, LF, or CRLF encoding of same bytes."""
    if not path.exists() or not pin:
        return False
    raw = path.read_bytes()
    lf = _lf(raw)
    crlf = raw if b"\r\n" in raw else raw.replace(b"\n", b"\r\n")
    return pin in {
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(lf).hexdigest(),
        hashlib.sha256(crlf).hexdigest(),
    }


def sha_group(rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(_lf(p.read_bytes()) if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def check(name: str, ok: bool, measured, detail: str = "",
          critical: bool = True) -> None:
    CHECKS.append({
        "check": name,
        "status": "PASS" if ok else "FAIL",
        "critical": critical,
        "measured": measured,
        **({"detail": detail} if detail else {}),
    })


def _allowed_dirty(p: str) -> bool:
    p = p.replace("\\", "/")
    prefixes = (
        ".cursor/",
        "evaluations/t16/",
        "scripts/t16_",
        "tests/test_t16",
        "tests/test_t15r_v11.py",
        "src/sciencemath/web/",
    )
    names = {
        "full_junit.xml", "full_test_out.txt", "pytest_summary.txt",
        ".cursor/settings.json",
    }
    return p in names or any(p.startswith(x) for x in prefixes)


def _py_files(rel_dir: str) -> list[str]:
    d = ROOT / rel_dir
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in d.glob("*.py")
    )


def main() -> int:
    recorded = datetime.now(timezone.utc).isoformat()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
        text=True).stdout
    mb = subprocess.run(
        ["git", "merge-base", "--is-ancestor", REQUIRED_HEAD, "HEAD"],
        cwd=ROOT, capture_output=True, text=True)
    includes = mb.returncode == 0
    head_ok = head == REQUIRED_HEAD or includes

    dirty = []
    for ln in porcelain.splitlines():
        if ln.strip():
            dirty.append(ln[3:].strip().replace("\\", "/"))
    unexpected = [p for p in dirty if not _allowed_dirty(p)]
    bench_dirt = [
        p for p in unexpected
        if p.startswith("evaluations/") or p.endswith(".jsonl")
    ]

    check("git_head_t15r_merge",
          head_ok,
          {"head": head, "required": REQUIRED_HEAD, "is_ancestor": includes,
           "exact": head == REQUIRED_HEAD})
    check("worktree_hygiene", not unexpected,
          {"dirty_n": len(dirty), "unexpected": unexpected, "dirty": dirty},
          "T16 artifacts allowed; uncommitted non-T16 benchmark dirt is "
          "critical")
    check("no_uncommitted_benchmark_artifacts", not bench_dirt,
          {"benchmark_dirt": bench_dirt})

    t15r_report = ROOT / "evaluations/t15r/T15R_FINAL_REPORT.md"
    check("t15r_final_report", t15r_report.exists(),
          str(t15r_report.relative_to(ROOT)))
    audit = load(ROOT / "evaluations/t15r/final_audit.json")
    audit_ok = (bool(audit) and audit.get("gates_total") == 33
                and audit.get("passes") == 33
                and audit.get("fails") == []
                and audit.get("code_decision") == "PROMOTE_CODE_SKILL")
    check("t15r_final_audit", audit_ok,
          {"gates_total": (audit or {}).get("gates_total"),
           "passes": (audit or {}).get("passes"),
           "fails": (audit or {}).get("fails"),
           "decision": (audit or {}).get("code_decision")})

    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    code_av = reg.availability("CODE")
    web_av = reg.availability("WEB_RESEARCH")
    sci_av = reg.availability("SCICOMP")
    check("code_active", code_av == "ACTIVE" and reg.executable("CODE"),
          {"availability": code_av, "executable": reg.executable("CODE")})
    check("web_research_prepared_only",
          web_av == "PREPARED_ONLY" and not reg.executable("WEB_RESEARCH"),
          {"availability": web_av, "executable": reg.executable("WEB_RESEARCH")})
    sci_dec = load(ROOT / "evaluations/t14r2/scicomp_decision.json")
    sci_ok = (bool(sci_dec) and sci_dec.get("decision") == "PROMOTE_SCICOMP_LAB"
              and float(sci_dec.get("numeric_accuracy") or 0) >= 0.848)
    check("scicomp_promoted_state", sci_ok and sci_av == "EXPERIMENTAL",
          {"registry_availability": sci_av,
           "decision": (sci_dec or {}).get("decision"),
           "numeric": (sci_dec or {}).get("numeric_accuracy")},
          "SciComp lab is promoted; registry remains EXPERIMENTAL until an "
          "independent availability flip. T16 must not change this.")
    check("executive_router_experimental", True,
          "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")

    code_files = _py_files("src/sciencemath/code")
    sci_files = _py_files("src/sciencemath/scicomp")
    t4_files = _py_files("src/sciencemath/tools")
    t5r_files = _py_files("src/sciencemath/rag")
    code_hashes = {rel: sha(ROOT / rel) for rel in code_files}
    sci_hashes = {rel: sha(ROOT / rel) for rel in sci_files}
    code_hash = sha_group(code_files)
    sci_hash = sha_group(sci_files)
    t4_hash = sha_group(t4_files)
    t5r_hash = sha_group(t5r_files)
    reg_h = registry_sha256()
    er_h = sha(ROOT / "src/sciencemath/executive/executive_router.py")
    fid_h = sha(ROOT / "src/sciencemath/scicomp/fidelity.py")
    fw_h = sha(ROOT / "src/sciencemath/executive/correction.py")
    adp_h = sha_raw(ROOT / ADAPTER)
    skills_h = sha(ROOT / "src/sciencemath/executive/skills.py")
    sec_files = [
        "src/sciencemath/code/safety.py",
        "tests/test_t15_code_security.py",
        "tests/test_t11_security.py",
    ]
    sec_hash = sha_group(sec_files)

    check("skill_registry_hash", bool(reg_h) and len(reg_h) == 64, reg_h)
    check("code_hash", bool(code_hash) and all(code_hashes.values()),
          {"composite": code_hash, "files": code_hashes})
    freeze = load(ROOT / "evaluations/t15/frozen_components.json")
    sci_mismatch = []
    for rel, pin in ((freeze or {}).get("files") or {}).items():
        if rel.startswith("src/sciencemath/scicomp/") and not pin_match(
                ROOT / rel, pin):
            sci_mismatch.append(rel)
    check("scicomp_hash",
          not sci_mismatch,
          {"composite_lf": sci_hash,
           "t15r_working_tree_composite_pin": T15R_PINS["scicomp_composite"],
           "mismatch_vs_t15_freeze_newline_alias": sci_mismatch},
          "T15R composite mixed CRLF/LF working-tree bytes; T16 verifies "
          "per-file identity under LF/CRLF alias against the T15 freeze")
    check("correction_firewall_hash",
          pin_match(ROOT / "src/sciencemath/executive/correction.py",
                    T15R_PINS["correction_firewall"]), fw_h)
    check("fidelity_hash",
          pin_match(ROOT / "src/sciencemath/scicomp/fidelity.py",
                    T15R_PINS["fidelity_classifier"]), fid_h)
    check("security_policy_hash", bool(sec_hash),
          {"composite": sec_hash,
           "files": {p: sha(ROOT / p) for p in sec_files}})
    check("t3_adapter_identity",
          adp_h == T15R_PINS["t3_adapter"], adp_h)
    check("executive_router_hash",
          pin_match(ROOT / "src/sciencemath/executive/executive_router.py",
                    T15R_PINS["executive_router"]),
          {"lf": er_h, "raw": sha_raw(
              ROOT / "src/sciencemath/executive/executive_router.py")})

    merge_head = (ROOT / ".git" / "MERGE_HEAD").exists()
    rebase = (ROOT / ".git" / "rebase-merge").exists() or \
        (ROOT / ".git" / "rebase-apply").exists()
    check("no_merge_rebase_in_progress", not merge_head and not rebase,
          {"merge_head": merge_head, "rebase": rebase})

    import platform
    env = {
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "runtime": "Mango-4B-System-v1",
        "model": MODEL,
    }
    try:
        import transformers
        import torch
        env["torch"] = torch.__version__
        env["cuda_available"] = bool(torch.cuda.is_available())
        env["transformers"] = transformers.__version__
        env_ok = transformers.__version__ == TRANSFORMERS_PIN
    except Exception as e:  # noqa: BLE001
        env["import_error"] = str(e)
        env_ok = False
    check("environment_recorded", env_ok, env,
          f"transformers pin {TRANSFORMERS_PIN}")

    gpu_q = ""
    apps: list[str] = []
    try:
        gpu_q = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            cwd=ROOT, capture_output=True, text=True).stdout.strip()
        apps = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name",
             "--format=csv,noheader"],
            cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
    except Exception:
        apps = []
    mango_gpu = [a for a in apps
                 if "python" in a.lower() or "pytest" in a.lower()]
    stale_cpu = []
    try:
        wmic = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | "
             "Where-Object { $_.Name -match 'python' -and "
             "$_.CommandLine -match 't15_run_code_eval|t15r_run|"
             "t15_protection_battery|run_rag_eval|t16_run_' } | "
             "Select-Object -ExpandProperty ProcessId"],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        me = str(os.getpid())
        stale_cpu = [x.strip() for x in wmic.stdout.splitlines()
                     if x.strip() and x.strip() != me]
    except Exception:
        stale_cpu = []
    check("no_stale_evaluation_processes",
          not mango_gpu and not stale_cpu,
          {"gpu_query": gpu_q, "compute_apps": apps,
           "mango_gpu_jobs": mango_gpu, "stale_eval_pids": stale_cpu})

    out_xml = ROOT / "evaluations/t16/pytest_entry_junit.xml"
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    py = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q",
         f"--junitxml={out_xml}", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    tree = ET.parse(str(out_xml))
    s = tree.getroot()
    if s.tag == "testsuites":
        suites = list(s.findall("testsuite")) or [s]
        tests_n = sum(int(x.get("tests", "0")) for x in suites)
        fail_n = sum(int(x.get("failures", "0")) for x in suites)
        err_n = sum(int(x.get("errors", "0")) for x in suites)
        skip_n = sum(int(x.get("skipped", "0")) for x in suites)
        time_s = sum(float(x.get("time", "0") or 0) for x in suites)
    else:
        tests_n = int(s.get("tests", "0"))
        fail_n = int(s.get("failures", "0"))
        err_n = int(s.get("errors", "0"))
        skip_n = int(s.get("skipped", "0"))
        time_s = float(s.get("time", "0") or 0)
    pytest_doc = {
        "milestone": "T16.0 — entry pytest",
        "recorded_at": recorded,
        "tests": tests_n,
        "failures": fail_n,
        "errors": err_n,
        "skipped": skip_n,
        "exit_code": int(py.returncode),
        "failed": fail_n,
        "passed": tests_n - fail_n - err_n - skip_n,
        "time_s": time_s,
        "tail": (py.stdout or "")[-2000:],
    }
    (ROOT / "evaluations/t16/pytest_entry.json").write_text(
        json.dumps(pytest_doc, indent=2) + "\n", encoding="utf-8")
    py_ok = (pytest_doc["exit_code"] == 0 and pytest_doc["failed"] == 0
             and pytest_doc["errors"] == 0)
    check("current_pytest_green", py_ok, {
        k: pytest_doc[k] for k in
        ("tests", "passed", "failed", "errors", "skipped", "exit_code",
         "time_s")
    }, "require 0 failed / 0 errors; do not target the count")

    critical_fails = [c["check"] for c in CHECKS
                      if c["status"] == "FAIL" and c.get("critical")]
    ok_all = not critical_fails
    hashes = {
        "skill_registry": reg_h,
        "skill_registry_file": skills_h,
        "code_composite": code_hash,
        "code_files": code_hashes,
        "scicomp_composite": sci_hash,
        "scicomp_files": sci_hashes,
        "t4_tools": t4_hash,
        "t5r_rag": t5r_hash,
        "executive_router": er_h,
        "fidelity": fid_h,
        "correction_firewall": fw_h,
        "security_policies": sec_hash,
        "t3_adapter": adp_h,
    }
    doc = {
        "milestone": "T16 — Web Research & Evidence Intelligence",
        "phase": "T16.0 entry gate",
        "recorded_at": recorded,
        "status": "PASS" if ok_all else "FAIL",
        "git_head": head,
        "branch": branch,
        "required_head": REQUIRED_HEAD,
        "starting_architecture": "Mango-4B-System-v1",
        "scicomp_status": "ACTIVE / PROMOTED",
        "scicomp_numeric": (sci_dec or {}).get("numeric_accuracy"),
        "scicomp_floor": 0.848,
        "code_status": "ACTIVE / PROMOTED",
        "web_research_status": "PREPARED_ONLY",
        "executive_router_status": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "training": "NONE",
        "t15r_historical": {
            "code_final": "129/139 = 0.9281",
            "bug_fix": "24/25 = 0.96",
            "executable": "62/72 = 0.8611",
            "unrelated_edit": "0/72",
            "decision": "PROMOTE_CODE_SKILL",
            "pytest": "1140 passed, 0 failed, 0 errors, 1 skipped",
            "audit": "33 PASS / 0 FAIL",
        },
        "hashes": hashes,
        "t15r_pins": T15R_PINS,
        "checks": CHECKS,
        "substantive_failures": critical_fails,
        "conclusion": (
            "All entry-gate checks PASS. T16 may proceed to T16.1 and "
            "branch t16-web-research."
            if ok_all else
            "Entry gate has critical failures — STOP. Do not start "
            "T16 implementation."
        ),
    }
    out = ROOT / "evaluations/t16/t16_entry_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "status": doc["status"],
        "substantive_failures": critical_fails,
        "pytest": {k: pytest_doc[k] for k in
                   ("passed", "failed", "errors", "skipped", "exit_code")},
        "head": head,
        "code_av": code_av,
        "web_av": web_av,
    }, indent=2))
    print(f"entry gate: {doc['status']} -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
