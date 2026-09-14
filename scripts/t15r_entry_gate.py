"""T15R.0 entry gate — verify T15-closed provenance before any CODE repair-loop
work.

Critical provenance failure => STOP. Does not modify src/sciencemath/code/.
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

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
TRANSFORMERS_PIN = "5.16.1"
ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"
T14R2_CLOSE = "c27abc60f4288563d96f1a6a77908fa4081cd5f4"
SUITE_FINAL = ROOT / "evaluations/t15/suites/mango-code-eval-v1/final.jsonl"
MANIFEST = ROOT / "evaluations/t15/suites/mango-code-eval-v1/manifest.json"

T15_PINS = {
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
}

CODE_FILES = sorted(
    "src/sciencemath/code/" + p.name
    for p in (ROOT / "src/sciencemath/code").glob("*.py")
)

SCICOMP_FILES = sorted(
    "src/sciencemath/scicomp/" + p.name
    for p in (ROOT / "src/sciencemath/scicomp").glob("*.py")
)

CHECKS: list[dict] = []


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() \
        else None


def sha_group(rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes() if p.exists() else b"")
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
        "evaluations/t14r",
        "evaluations/t14r2",
        "evaluations/t15/",
        "evaluations/t15r/",
        "evaluations/t8/runs/t15-protect",
        "evaluations/t9/runs/t15-protect",
        "evaluations/t10/runs/t15-protect",
        "scripts/t15_",
        "scripts/t15r_",
        "tests/test_t15",
        "src/sciencemath/code/",
    )
    names = {
        "full_junit.xml", "full_test_out.txt", "pytest_summary.txt",
        "t5r_junit.xml", "t5r_test_out.txt", "t6_junit.xml",
        ".cursor/settings.json",
    }
    return p in names or any(p.startswith(x) for x in prefixes)


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
    mb = subprocess.run(
        ["git", "merge-base", "--is-ancestor", T14R2_CLOSE, "HEAD"],
        cwd=ROOT, capture_output=True, text=True)
    includes = mb.returncode == 0

    dirty = []
    for ln in porcelain.splitlines():
        if ln.strip():
            dirty.append(ln[3:].strip().replace("\\", "/"))
    unexpected = [p for p in dirty if not _allowed_dirty(p)]

    check("git_head_includes_t14r2_close", includes,
          {"head": head, "required_ancestor": T14R2_CLOSE,
           "is_ancestor": includes})
    check("worktree_hygiene", not unexpected,
          {"dirty_n": len(dirty), "unexpected": unexpected},
          "T15/T15R artifacts, CODE runtime, and harness dirt allowed; "
          "frozen non-CODE components must not appear as unexpected edits")

    t15_report = ROOT / "evaluations/t15/T15_FINAL_REPORT.md"
    t15_audit_p = ROOT / "evaluations/t15/t15_final_audit.json"
    check("t15_final_report_exists", t15_report.exists(),
          str(t15_report.relative_to(ROOT)))
    audit = load(t15_audit_p)
    audit_ok = (bool(audit) and audit.get("gates_total") == 27
                and audit.get("passes") == 27
                and audit.get("fails") == []
                and audit.get("decision", "").startswith(
                    "KEEP_CODE_SKILL_EXPERIMENTAL"))
    check("t15_final_audit_exists", audit_ok,
          {"gates_total": (audit or {}).get("gates_total"),
           "passes": (audit or {}).get("passes"),
           "fails": (audit or {}).get("fails"),
           "decision": (audit or {}).get("decision")})

    man = load(MANIFEST)
    suite_sha = sha(SUITE_FINAL)
    check("mango_code_eval_v1_checksum",
          bool(man) and suite_sha == man.get("final_sha256")
          and man.get("final_sha256") ==
          "1676bd9e5a539efdb7d2160c1d88604d1f7d2fc8e2a7568f819189861389bddc",
          {"final_sha256": suite_sha,
           "manifest": (man or {}).get("final_sha256"),
           "n_final": (man or {}).get("final_n")})

    freeze = load(ROOT / "evaluations/t15/frozen_components.json")
    code_hashes = {rel: sha(ROOT / rel) for rel in CODE_FILES}
    code_hash = sha_group(CODE_FILES)
    t15_code = (freeze or {}).get("files", {})
    code_drift = [rel for rel in CODE_FILES
                  if t15_code.get(rel) and t15_code[rel] != code_hashes[rel]]
    check("current_code_skill_hash",
          bool(code_hash) and all(code_hashes.values()),
          {"composite": code_hash, "files": code_hashes,
           "drift_from_t15_1_freeze": code_drift},
          "T15.1 freeze predates the documented utf-8 subprocess fix; "
          "drift in discovery/runner/testsel is expected and recorded")

    er_h = sha(ROOT / "src/sciencemath/executive/executive_router.py")
    check("executive_router_hash",
          er_h == T15_PINS["executive_router"], er_h)

    sci_hash = sha_group(SCICOMP_FILES)
    sci_file_hashes = {rel: sha(ROOT / rel) for rel in SCICOMP_FILES}
    sci_mismatch = []
    for rel, h in ((freeze or {}).get("files") or {}).items():
        if rel.startswith("src/sciencemath/scicomp/") and sci_file_hashes.get(rel) != h:
            sci_mismatch.append(rel)
    check("scicomp_hash",
          not sci_mismatch,
          {"composite": sci_hash, "mismatch_vs_t15_freeze": sci_mismatch})

    fid_h = sha(ROOT / "src/sciencemath/scicomp/fidelity.py")
    check("fidelity_hash", fid_h == T15_PINS["fidelity_classifier"], fid_h)

    fw_h = sha(ROOT / "src/sciencemath/executive/correction.py")
    check("correction_firewall_hash",
          fw_h == T15_PINS["correction_firewall"], fw_h)

    adp_h = sha(ROOT / ADAPTER)
    check("t3_adapter_hash", adp_h == T15_PINS["t3_adapter"], adp_h)

    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    reg_h = registry_sha256()
    check("skill_registry_hash",
          reg_h == T15_PINS["skill_registry"], reg_h)
    code_av = reg.availability("CODE")
    code_ex = reg.executable("CODE")
    # Semantic T15 close-out: KEEP_CODE_SKILL_EXPERIMENTAL. The registry
    # remains PREPARED_ONLY until an explicit T15R.30 availability flip
    # (EXPERIMENTAL→ACTIVE only on promotion). Routing must still fail
    # closed for CODE until that flip.
    check("code_skill_registry_availability",
          code_av == "PREPARED_ONLY" and code_ex is False,
          {"registry_availability": code_av, "executable": code_ex,
           "semantic_status": "EXPERIMENTAL"},
          "T15 left the registry PREPARED_ONLY; T15R treats CODE as "
          "EXPERIMENTAL semantically and only flips the registry on "
          "PROMOTE_CODE_SKILL")

    sec_files = [
        "src/sciencemath/code/safety.py",
        "tests/test_t15_code_security.py",
        "tests/test_t11_security.py",
    ]
    sec_hash = sha_group(sec_files)
    check("security_policies_present",
          all((ROOT / p).exists() for p in sec_files),
          {"composite": sec_hash, "files": {p: sha(ROOT / p) for p in sec_files}})

    prot = load(ROOT / "evaluations/t15/protection/regression_summary.json")
    check("t15_protection_all_pass",
          bool(prot) and prot.get("status") == "ALL_PASS",
          (prot or {}).get("status"))
    sec = load(ROOT / "evaluations/t15/protection/security_summary.json")
    check("t15_security_zero_violations",
          bool(sec) and sec.get("violations") == 0,
          (sec or {}).get("violations"))

    floors = load(ROOT / "evaluations/t15/floors_evaluation.json")
    check("t15_code_kept_experimental",
          bool(floors) and "KEEP_CODE_SKILL_EXPERIMENTAL" in (
              floors.get("decision") or ""),
          (floors or {}).get("decision"))

    # model identity from T15 code-final (unchanged)
    cs = load(ROOT / "evaluations/t15/runs/code-final/summary.json")
    model_ok = bool(cs) and ((cs.get("model") or {}).get("model") == MODEL
                             or cs.get("model") == MODEL)
    check("model_identity", model_ok,
          (cs or {}).get("model"), critical=True)

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

    # stale runner / GPU mango jobs
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
    # CPU-side stale eval processes (best-effort)
    stale_cpu = []
    try:
        wmic = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | "
             "Where-Object { $_.Name -match 'python' -and "
             "$_.CommandLine -match 't15_run_code_eval|t15r_run|"
             "t15_protection_battery|run_rag_eval' } | "
             "Select-Object -ExpandProperty ProcessId"],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        stale_cpu = [x.strip() for x in wmic.stdout.splitlines() if x.strip()]
    except Exception:
        stale_cpu = []
    check("no_stale_runner_processes",
          not mango_gpu and not stale_cpu,
          {"gpu_query": gpu_q, "compute_apps": apps,
           "mango_gpu_jobs": mango_gpu, "stale_eval_pids": stale_cpu})

    # full pytest (fresh, isolated subprocess)
    out_xml = ROOT / "evaluations/t15r/pytest_entry_junit.xml"
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    py = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q",
         f"--junitxml={out_xml}", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    tree = ET.parse(str(out_xml))
    s = tree.getroot()
    if s.tag == "testsuites":
        # aggregate if multiple suites
        suites = list(s.findall("testsuite"))
        if not suites:
            suites = [s]
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
        "milestone": "T15R.0 — entry pytest",
        "recorded_at": recorded,
        "tests": tests_n,
        "failures": fail_n,
        "errors": err_n,
        "skipped": skip_n,
        "exit_code": int(py.returncode),
        "failed": fail_n,
        "passed": tests_n - fail_n - err_n - skip_n,
        "time_s": time_s,
    }
    (ROOT / "evaluations/t15r/pytest_entry.json").write_text(
        json.dumps(pytest_doc, indent=2) + "\n", encoding="utf-8")
    py_ok = (pytest_doc["exit_code"] == 0 and pytest_doc["failed"] == 0
             and pytest_doc["errors"] == 0)
    check("current_pytest_green", py_ok, pytest_doc,
          "require 0 failed / 0 errors; do not target the count")

    merge_head = (ROOT / ".git" / "MERGE_HEAD").exists()
    rebase = (ROOT / ".git" / "rebase-merge").exists() or \
        (ROOT / ".git" / "rebase-apply").exists()
    check("no_merge_rebase_in_progress", not merge_head and not rebase,
          {"merge_head": merge_head, "rebase": rebase})

    critical_fails = [c["check"] for c in CHECKS
                      if c["status"] == "FAIL" and c.get("critical")]
    ok_all = not critical_fails
    doc = {
        "milestone": "T15R — Iterative Patch Retention & CODE Promotion Closure",
        "phase": "T15R.0 entry gate",
        "recorded_at": recorded,
        "status": "PASS" if ok_all else "FAIL",
        "git_head": head,
        "branch": branch,
        "starting_architecture": "Mango-4B-System-v1",
        "scicomp_status": "PROMOTED",
        "scicomp_numeric": 0.8695652173913043,
        "scicomp_floor": 0.848,
        "executive_router_status": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
        "code_skill_semantic_status": "EXPERIMENTAL",
        "code_skill_registry_availability": code_av,
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "training": "NONE",
        "t15_historical": {
            "overall": "111/139 = 0.7986",
            "bug_fix": "15/25 = 0.60",
            "executable": "44/72 = 0.6111",
            "unrelated_edit": "3/72 = 0.0417",
            "decision": "KEEP_CODE_SKILL_EXPERIMENTAL",
        },
        "hashes": {
            "code_skill_composite": code_hash,
            "code_files": code_hashes,
            "executive_router": er_h,
            "scicomp_composite": sci_hash,
            "fidelity": fid_h,
            "correction_firewall": fw_h,
            "t3_adapter": adp_h,
            "skill_registry": reg_h,
            "security_policies": sec_hash,
            "mango_code_eval_v1_final": suite_sha,
        },
        "frozen_component_pins": T15_PINS,
        "checks": CHECKS,
        "substantive_failures": critical_fails,
        "conclusion": (
            "All entry-gate checks PASS. T15R may proceed to T15R.1."
            if ok_all else
            "Entry gate has critical failures — STOP. Do not start "
            "implementation."
        ),
    }
    out = ROOT / "evaluations/t15r/t15r_entry_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "status": doc["status"],
        "substantive_failures": critical_fails,
        "pytest": {k: pytest_doc[k] for k in
                   ("passed", "failed", "errors", "skipped", "exit_code")},
        "code_hash": code_hash[:16],
    }, indent=2))
    print(f"entry gate: {doc['status']} -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
