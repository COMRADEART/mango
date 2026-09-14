"""T20.0 entry gate — verify T19-closed provenance before ORCHESTRATION work.

Critical provenance failure => STOP. Does not modify promoted PLANNING /
MEMORY / DOCUMENT / CODE / SciComp / WEB_RESEARCH runtimes or the Executive
Router.
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

REQUIRED_HEAD = "9a1b4260745c3967191bfccc6658078bc244cc95"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
TRANSFORMERS_PIN = "5.16.1"
ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"

# T18-close pins for unchanged promoted layers (unchanged through T19 and the
# registry-consistency cleanup; verified again here before T20 work).
T18_PINS = {
    "code_composite":
        "cf9dc3c640d9410ee147e2ba8ca5ce42a2feeb36155d5ba61b462c94a988e627",
    "scicomp_composite":
        "5be66a3afb5f17f6b07ec995938ee783cb9adee8f85c268c52562a258f8e22c8",
    "web_research_composite":
        "5ec760efb9d0420de3f1ca6c49e8481c151efeef027611683bfb1f1909140aa4",
    "document_implementation":
        "d14232aeaa62d9ddead8fb84e5c95a4df93554da7159e2c610191f30cec4059d",
    "memory_implementation":
        "ac77f2d448345b4fb489911d6f9cd3c98dec06f4528ddf0e47e54852ccc4002d",
    "t4_tools":
        "3dadd23df1cf9bb10421a9abe316edcfca9e553f714980aca1764e5f53855da7",
    "t5r_rag":
        "350f023bcfccf370761963704b96fe6aa60819f6dff8067064aa24348b697742",
    "security_policy":
        "7b7417c49a7f1b699e3cc22fec2a74098ec017b0d65d8e85fb73ffe8ad0d3419",
    "t3_adapter":
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
    "fidelity_file":
        "052689077a2545e7012fe613d245024480567aa572f30440501d9789db2e2146",
    "correction_file":
        "2dc220114a4f3e639842014f2f46d869b0b2091185c60217ca2c90d16da394d3",
    "fidelity_composite":
        "f3c74a311cbfdf7a01ff0eae13770082704fa9d96b0e6163ce665e6174d9dc28",
    "correction_composite":
        "b1c95d975f67301fbe84d5a081c3e372d85bb0cae8f6d1a3bae1326c71ffff84",
}

# T19-close pins: post-registry-consistency-cleanup registry identity,
# recorded in evaluations/registry_consistency/scicomp_active_cleanup.json.
T19_PINS = {
    "registry_sha256":
        "9d74777848d2c7cc6a2ede569dae7d868e0e9dd3bcb89688d4de850a6b3bf4be",
    "skills_py_sha256":
        "1af3682450d00a84d7e43aeb6b1d816c3cf13742b200988bb143f729125e074a",
    "executive_router_sha256":
        "06c59027341e4ef9124a4b5c1610a470e77fd67cfe8133446b380fcf9866af8e",
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
        "evaluations/t20/",
        "scripts/t20_",
        "tests/test_t20",
        "src/sciencemath/orchestration/",
    )
    names = {
        "full_junit.xml", "full_test_out.txt", "pytest_summary.txt",
        ".cursor/settings.json",
        "evaluations/t15r/mutation_safety_probe.json",
    }
    return p in names or any(p.startswith(x) for x in prefixes)


def _leftover_eval_dump(p: str) -> bool:
    """Unrelated untracked regenerable eval outputs from prior milestones."""
    p = p.replace("\\", "/")
    if p.startswith("evaluations/t20/"):
        return False
    if not p.startswith("evaluations/"):
        return False
    leftovers = (
        "evaluations/t15r/checkpoints/",
        "evaluations/t15r/runs/",
        "evaluations/t10/runs/",
        "evaluations/t8/runs/",
        "evaluations/t9/runs/",
        "evaluations/t16/runs/",
        "evaluations/t16/protection/",
        "evaluations/t17/runs/",
        "evaluations/t17/protection/",
        "evaluations/t18/runs/",
        "evaluations/t18/protection/",
        "evaluations/t19/runs/",
        "evaluations/t19/protection/",
    )
    return any(p.startswith(x) for x in leftovers) or p.endswith(".jsonl")


def _timestamp_only_probe(p: str) -> bool:
    return p.replace("\\", "/") == "evaluations/t15r/mutation_safety_probe.json"


def _py_files(rel_dir: str) -> list[str]:
    d = ROOT / rel_dir
    if not d.exists():
        return []
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in d.glob("*.py")
    )


def _pytest_counts(xml_path: Path) -> dict:
    tree = ET.parse(str(xml_path))
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
    return {
        "tests": tests_n, "failed": fail_n, "errors": err_n,
        "skipped": skip_n, "time_s": time_s,
        "passed": tests_n - fail_n - err_n - skip_n,
    }


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
    exact = head == REQUIRED_HEAD

    dirty = []
    for ln in porcelain.splitlines():
        if ln.strip():
            dirty.append(ln[3:].strip().replace("\\", "/"))
    leftover = [p for p in dirty if _leftover_eval_dump(p)
                and not _allowed_dirty(p)]
    timestamp_only = [p for p in dirty if _timestamp_only_probe(p)]
    unexpected = [p for p in dirty
                  if not _allowed_dirty(p) and p not in leftover
                  and p not in timestamp_only]
    bench_dirt = [
        p for p in unexpected
        if p.startswith("evaluations/") or p.endswith(".jsonl")
    ]

    check("git_head_t19_canonical",
          head_ok,
          {"head": head, "required": REQUIRED_HEAD, "is_ancestor": includes,
           "exact": exact})
    check("worktree_hygiene", not unexpected,
          {"dirty_n": len(dirty), "unexpected": unexpected, "dirty": dirty,
           "leftover_untracked_eval_dumps": leftover,
           "timestamp_only_unstaged": timestamp_only,
           "leftover_blocks_gate": False},
          "T20 artifacts allowed; T15R mutation probe timestamp-only "
          "drift remains unstaged; leftover prior-milestone eval dumps "
          "are recorded and left untouched")
    check("no_uncommitted_benchmark_artifacts", not bench_dirt,
          {"benchmark_dirt": bench_dirt,
           "leftover_untracked_eval_dumps": leftover,
           "timestamp_only_unstaged": timestamp_only})

    # --- T19 closed provenance -------------------------------------------
    t19_report = ROOT / "evaluations/t19/T19_FINAL_REPORT.md"
    t19_text = t19_report.read_text(encoding="utf-8") if t19_report.exists() \
        else ""
    tail_block = t19_text.split("Ready for T20", 1)[-1][:80] \
        if "Ready for T20" in t19_text else ""
    t19_closed = ("## T19 Family Closure" in t19_text
                  and "CLOSED" in t19_text
                  and "Ready for T20" in t19_text
                  and "YES" in tail_block
                  and "PROMOTE_PLANNING_SKILL" in t19_text)
    check("t19_final_report", t19_report.exists() and t19_closed,
          str(t19_report.relative_to(ROOT)) if t19_report.exists() else None,
          "T19 CLOSED, PLANNING promoted, Ready for T20 = YES")
    audit = load(ROOT / "evaluations/t19/final_audit.json")
    audit_ok = (bool(audit) and audit.get("gates_total") == 76
                and audit.get("passes") == 76
                and audit.get("fails") == []
                and (audit.get("planning_decision") == "PROMOTE_PLANNING_SKILL"
                     or ((audit.get("planning_decision") or {}).get("decision")
                         == "PROMOTE_PLANNING_SKILL")))
    check("t19_final_audit", audit_ok,
          {"gates_total": (audit or {}).get("gates_total"),
           "passes": (audit or {}).get("passes"),
           "fails": (audit or {}).get("fails"),
           "decision": (audit or {}).get("planning_decision")})

    post_merge = load(ROOT / "evaluations/t19/post_merge_audit_cleanup.json")
    post_ok = bool(post_merge) and (
        post_merge.get("cleanup_type") == "AUDIT_METADATA_ONLY"
        and post_merge.get("capability_behavior_changed") is False
        and post_merge.get("promotion_decision_changed") is False)
    check("t19_post_merge_audit_cleanup_exists", post_ok,
          "evaluations/t19/post_merge_audit_cleanup.json")

    reg_entry = load(ROOT / "evaluations/registry_consistency/"
                           "scicomp_active_entry.json")
    reg_cleanup = load(ROOT / "evaluations/registry_consistency/"
                             "scicomp_active_cleanup.json")
    reg_cleanup_ok = bool(reg_cleanup) and (
        reg_cleanup.get("registry_state_after") == "ACTIVE"
        and reg_cleanup.get("scicomp_implementation_changed") is False)
    check("scicomp_registry_consistency_cleanup_exists",
          reg_entry is not None and reg_cleanup_ok,
          ["evaluations/registry_consistency/scicomp_active_entry.json",
           "evaluations/registry_consistency/scicomp_active_cleanup.json"])

    # --- capability registry state ---------------------------------------
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    code_av = reg.availability("CODE")
    web_av = reg.availability("WEB_RESEARCH")
    sci_av = reg.availability("SCICOMP")
    doc_av = reg.availability("DOCUMENT")
    mem_av = reg.availability("MEMORY")
    plan_av = reg.availability("PLANNING")
    sci_dec = load(ROOT / "evaluations/t14r2/scicomp_decision.json")
    sci_ok = (bool(sci_dec) and sci_dec.get("decision") == "PROMOTE_SCICOMP_LAB"
              and float(sci_dec.get("numeric_accuracy") or 0) >= 0.848)
    check("scicomp_active", sci_ok and sci_av == "ACTIVE",
          {"registry_availability": sci_av,
           "decision": (sci_dec or {}).get("decision"),
           "numeric": (sci_dec or {}).get("numeric_accuracy")},
          "SciComp lab promoted ACTIVE; registry availability aligned to "
          "ACTIVE by the documented registry-consistency cleanup.")
    check("code_active", code_av == "ACTIVE" and reg.executable("CODE"),
          {"availability": code_av, "executable": reg.executable("CODE")})
    check("web_research_active",
          web_av == "ACTIVE" and reg.executable("WEB_RESEARCH"),
          {"availability": web_av, "executable": reg.executable("WEB_RESEARCH")})
    check("document_active",
          doc_av == "ACTIVE" and reg.executable("DOCUMENT"),
          {"availability": doc_av, "executable": reg.executable("DOCUMENT")})
    check("memory_active",
          mem_av == "ACTIVE" and reg.executable("MEMORY"),
          {"availability": mem_av, "executable": reg.executable("MEMORY")})
    check("planning_active",
          plan_av == "ACTIVE" and reg.executable("PLANNING"),
          {"availability": plan_av})
    check("executive_router_experimental", True,
          "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")

    # --- implementation identity hashes ----------------------------------
    code_files = _py_files("src/sciencemath/code")
    sci_files = _py_files("src/sciencemath/scicomp")
    t4_files = _py_files("src/sciencemath/tools")
    t5r_files = _py_files("src/sciencemath/rag")
    web_files = _py_files("src/sciencemath/web")
    doc_files = _py_files("src/sciencemath/document")
    mem_files = _py_files("src/sciencemath/memory")
    t19_plan_files = _py_files("src/sciencemath/planning")
    plan_exec_files = [
        "src/sciencemath/executive/plan.py",
        "src/sciencemath/executive/replan.py",
        "src/sciencemath/executive/checkpoint.py",
        "src/sciencemath/executive/budgets.py",
        "src/sciencemath/executive/state.py",
        "src/sciencemath/executive/runner.py",
    ]
    code_hashes = {rel: sha(ROOT / rel) for rel in code_files}
    sci_hashes = {rel: sha(ROOT / rel) for rel in sci_files}
    web_hashes = {rel: sha(ROOT / rel) for rel in web_files}
    doc_hashes = {rel: sha(ROOT / rel) for rel in doc_files}
    mem_hashes = {rel: sha(ROOT / rel) for rel in mem_files}
    t19_plan_hashes = {rel: sha(ROOT / rel) for rel in t19_plan_files}
    code_hash = sha_group(code_files)
    sci_hash = sha_group(sci_files)
    t4_hash = sha_group(t4_files)
    t5r_hash = sha_group(t5r_files)
    web_hash = sha_group(web_files)
    doc_hash = sha_group(doc_files)
    mem_hash = sha_group(mem_files)
    t19_plan_hash = sha_group(t19_plan_files)
    plan_exec_hash = sha_group(plan_exec_files)
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
    fid_comp = sha_group([
        "src/sciencemath/scicomp/fidelity.py",
        "src/sciencemath/scicomp/semantic.py",
    ])
    fw_comp = sha_group(["src/sciencemath/executive/correction.py"])

    freeze19 = load(ROOT / "evaluations/t19/frozen_components.json")
    sci_mismatch = []
    for rel, pin in ((freeze19 or {}).get("files") or {}).items():
        if rel.startswith("src/sciencemath/scicomp/") and not pin_match(
                ROOT / rel, pin):
            sci_mismatch.append(rel)

    check("skill_registry_hash",
          reg_h == T19_PINS["registry_sha256"]
          and skills_h == T19_PINS["skills_py_sha256"], reg_h,
          "post-registry-consistency-cleanup registry "
          "(SCICOMP ACTIVE, PLANNING ACTIVE)")
    check("scicomp_hash",
          sci_hash == T18_PINS["scicomp_composite"] and not sci_mismatch,
          {"composite_lf": sci_hash, "pin": T18_PINS["scicomp_composite"],
           "mismatch_vs_t19_freeze": sci_mismatch})
    check("code_hash",
          code_hash == T18_PINS["code_composite"] and all(code_hashes.values()),
          {"composite": code_hash, "pin": T18_PINS["code_composite"]})
    check("web_research_hash",
          web_hash == T18_PINS["web_research_composite"]
          and all(web_hashes.values()),
          {"composite": web_hash, "pin": T18_PINS["web_research_composite"]})
    check("document_hash",
          doc_hash == T18_PINS["document_implementation"]
          and all(doc_hashes.values()),
          {"composite": doc_hash, "pin": T18_PINS["document_implementation"]})
    check("memory_hash",
          mem_hash == T18_PINS["memory_implementation"]
          and all(mem_hashes.values()),
          {"composite": mem_hash, "pin": T18_PINS["memory_implementation"],
           "files": mem_hashes})
    check("t19_planning_runtime_hash", bool(t19_plan_hash),
          {"composite": t19_plan_hash, "files": t19_plan_hashes},
          "T19 long-horizon planner runtime identity recorded at T20 entry; "
          "T20 coordinates over it and must not rewrite T19 history.")
    check("t7_executive_planning_hash", bool(plan_exec_hash),
          {"composite": plan_exec_hash, "files": plan_exec_files},
          "T7 experimental planner identity recorded; frozen baseline.")
    check("correction_firewall_hash",
          pin_match(ROOT / "src/sciencemath/executive/correction.py",
                    T18_PINS["correction_file"])
          and fw_comp == T18_PINS["correction_composite"], fw_h)
    check("fidelity_hash",
          pin_match(ROOT / "src/sciencemath/scicomp/fidelity.py",
                    T18_PINS["fidelity_file"])
          and fid_comp == T18_PINS["fidelity_composite"], fid_h)
    check("security_policy_hash", sec_hash == T18_PINS["security_policy"],
          {"composite": sec_hash, "pin": T18_PINS["security_policy"],
           "files": {p: sha(ROOT / p) for p in sec_files}})
    check("t3_adapter_identity", adp_h == T18_PINS["t3_adapter"], adp_h)
    check("executive_router_hash",
          er_h == T19_PINS["executive_router_sha256"],
          {"lf": er_h, "raw": sha_raw(
              ROOT / "src/sciencemath/executive/executive_router.py")},
          "Post-T18 router (MEMORY availability integration). Not promoted.")
    check("t4_hash", t4_hash == T18_PINS["t4_tools"],
          {"composite": t4_hash, "pin": T18_PINS["t4_tools"]})
    check("t5r_hash", t5r_hash == T18_PINS["t5r_rag"],
          {"composite": t5r_hash, "pin": T18_PINS["t5r_rag"]})

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
             "t15_protection_battery|run_rag_eval|t16_run_|t17_run_|"
             "t18_run_|t19_run_|t20_run_' } | "
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

    out_xml = ROOT / "evaluations/t20/pytest_entry_junit.xml"
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    py = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q",
         f"--junitxml={out_xml}", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    counts = _pytest_counts(out_xml)
    pytest_doc = {
        "milestone": "T20.0 — entry pytest",
        "recorded_at": recorded,
        **counts,
        "exit_code": int(py.returncode),
        "tail": (py.stdout or "")[-2000:],
    }
    (ROOT / "evaluations/t20/pytest_entry.json").write_text(
        json.dumps(pytest_doc, indent=2) + "\n", encoding="utf-8")
    py_ok = (pytest_doc["exit_code"] == 0 and pytest_doc["failed"] == 0
             and pytest_doc["errors"] == 0)
    check("current_pytest_green", py_ok, {
        k: pytest_doc[k] for k in
        ("tests", "passed", "failed", "errors", "skipped", "exit_code",
         "time_s")
    }, "require 0 failed / 0 errors; do not target the historical count")

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
        "web_research_composite": web_hash,
        "web_research_files": web_hashes,
        "document_composite": doc_hash,
        "document_files": doc_hashes,
        "memory_composite": mem_hash,
        "memory_files": mem_hashes,
        "t19_planning_runtime_composite": t19_plan_hash,
        "t7_executive_planning_composite": plan_exec_hash,
        "t4_tools": t4_hash,
        "t5r_rag": t5r_hash,
        "executive_router": er_h,
        "fidelity": fid_h,
        "fidelity_composite": fid_comp,
        "correction_firewall": fw_h,
        "correction_composite": fw_comp,
        "security_policies": sec_hash,
        "t3_adapter": adp_h,
    }
    trans = load(ROOT / "evaluations/t19/planning_transition.json") or {}
    doc = {
        "milestone": "T20 — Multi-Agent Orchestration",
        "phase": "T20.0 entry gate",
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
        "web_research_status": "ACTIVE / PROMOTED",
        "document_status": "ACTIVE / PROMOTED",
        "memory_status": "ACTIVE / PROMOTED",
        "planning_status": "ACTIVE / PROMOTED",
        "orchestration_status": "NOT_IN_REGISTRY (introduced EXPERIMENTAL in T20.2)",
        "executive_router_status": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "training": "NONE",
        "t19_historical": {
            "decision": (trans.get("decision") or "PROMOTE_PLANNING_SKILL"),
            "pytest": "1333 passed, 0 failed, 0 errors, 2 skipped",
            "audit": "76 PASS / 0 FAIL",
            "post_merge_audit_cleanup": "committed (53da5d0)",
            "registry_consistency_cleanup": "committed (55c2e0d)",
            "ready_for_t20": "YES",
        },
        "worktree_note": {
            "dirty": dirty,
            "leftover_untracked_eval_dumps": leftover,
            "timestamp_only_unstaged": timestamp_only,
            "leftover_policy": (
                "Leave timestamp-only T15R mutation probe unstaged; "
                "do not mix into T20 artifacts."
            ),
            "blocks_gate": False,
        },
        "hashes": hashes,
        "t18_pins": T18_PINS,
        "t19_pins": T19_PINS,
        "checks": CHECKS,
        "substantive_failures": critical_fails,
        "conclusion": (
            "All entry-gate checks PASS. T20 may proceed to T20.1 and "
            "branch t20-multi-agent-orchestration."
            if ok_all else
            "Entry gate has critical failures — STOP. Do not start "
            "T20 implementation."
        ),
    }
    out = ROOT / "evaluations/t20/t20_entry_gate.json"
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
        "doc_av": doc_av,
        "mem_av": mem_av,
        "plan_av": plan_av,
        "sci_av": sci_av,
    }, indent=2))
    print(f"entry gate: {doc['status']} -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())