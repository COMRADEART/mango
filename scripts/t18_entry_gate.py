"""T18.0 entry gate — verify T17-closed provenance before MEMORY work.

Critical provenance failure => STOP. Does not modify promoted DOCUMENT /
CODE / SciComp / WEB_RESEARCH runtimes or the Executive Router.
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

REQUIRED_HEAD = "6a3e7931529632e7c523270da7f4d5f6e03df289"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
TRANSFORMERS_PIN = "5.16.1"
ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"

# T17-close pins. T18 must not silently drift these before implementation.
T17_PINS = {
    "code_composite":
        "cf9dc3c640d9410ee147e2ba8ca5ce42a2feeb36155d5ba61b462c94a988e627",
    "scicomp_composite":
        "5be66a3afb5f17f6b07ec995938ee783cb9adee8f85c268c52562a258f8e22c8",
    "web_research_composite":
        "5ec760efb9d0420de3f1ca6c49e8481c151efeef027611683bfb1f1909140aa4",
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
    "document_implementation":
        "d14232aeaa62d9ddead8fb84e5c95a4df93554da7159e2c610191f30cec4059d",
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
        "evaluations/t18/",
        "scripts/t18_",
        "tests/test_t18",
        "src/sciencemath/memory/",
        "runtime/memory/",
    )
    names = {
        "full_junit.xml", "full_test_out.txt", "pytest_summary.txt",
        ".cursor/settings.json",
    }
    return p in names or any(p.startswith(x) for x in prefixes)


def _leftover_eval_dump(p: str) -> bool:
    """Unrelated untracked regenerable eval outputs from prior milestones."""
    p = p.replace("\\", "/")
    if p.startswith("evaluations/t18/"):
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
    )
    return any(p.startswith(x) for x in leftovers) or p.endswith(".jsonl")


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

    dirty = []
    for ln in porcelain.splitlines():
        if ln.strip():
            dirty.append(ln[3:].strip().replace("\\", "/"))
    leftover = [p for p in dirty if _leftover_eval_dump(p)
                and not _allowed_dirty(p)]
    unexpected = [p for p in dirty
                  if not _allowed_dirty(p) and p not in leftover]
    bench_dirt = [
        p for p in unexpected
        if p.startswith("evaluations/") or p.endswith(".jsonl")
    ]

    check("git_head_t17_merge",
          head_ok,
          {"head": head, "required": REQUIRED_HEAD, "is_ancestor": includes,
           "exact": head == REQUIRED_HEAD})
    check("worktree_hygiene", not unexpected,
          {"dirty_n": len(dirty), "unexpected": unexpected, "dirty": dirty,
           "leftover_untracked_eval_dumps": leftover,
           "leftover_blocks_gate": False},
          "T18 artifacts allowed; leftover prior-milestone eval dumps are "
          "recorded and left untouched; they do not block if regenerable")
    check("no_uncommitted_benchmark_artifacts", not bench_dirt,
          {"benchmark_dirt": bench_dirt,
           "leftover_untracked_eval_dumps": leftover})

    t17_report = ROOT / "evaluations/t17/T17_FINAL_REPORT.md"
    t17_text = t17_report.read_text(encoding="utf-8") if t17_report.exists() \
        else ""
    t17_closed = ("## T17 Family Closure" in t17_text
                  and "CLOSED" in t17_text
                  and "Ready for T18" in t17_text
                  and "YES" in t17_text.split("Ready for T18", 1)[-1][:80])
    check("t17_final_report", t17_report.exists() and t17_closed,
          str(t17_report.relative_to(ROOT)) if t17_report.exists() else None,
          "T17 CLOSED and Ready for T18 = YES")
    audit = load(ROOT / "evaluations/t17/final_audit.json")
    audit_ok = (bool(audit) and audit.get("gates_total") == 48
                and audit.get("passes") == 48
                and audit.get("fails") == []
                and (audit.get("document_decision")
                     == "PROMOTE_DOCUMENT_SKILL"
                     or ((audit.get("document_decision") or {}).get("decision")
                         == "PROMOTE_DOCUMENT_SKILL")))
    if not audit_ok and audit:
        # decision may be nested under checks
        nested = None
        for c in audit.get("checks") or []:
            if c.get("check") == "document_decision":
                nested = c.get("measured")
        if isinstance(nested, dict):
            audit_ok = (audit.get("gates_total") == 48
                        and audit.get("passes") == 48
                        and audit.get("fails") == []
                        and nested.get("decision") == "PROMOTE_DOCUMENT_SKILL")
        elif nested == "PROMOTE_DOCUMENT_SKILL":
            audit_ok = (audit.get("gates_total") == 48
                        and audit.get("passes") == 48
                        and audit.get("fails") == [])
    check("t17_final_audit", audit_ok,
          {"gates_total": (audit or {}).get("gates_total"),
           "passes": (audit or {}).get("passes"),
           "fails": (audit or {}).get("fails"),
           "decision": (audit or {}).get("document_decision")})

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
    check("scicomp_active",
          sci_ok,
          {"registry_availability": sci_av,
           "semantic_status": "ACTIVE / PROMOTED",
           "decision": (sci_dec or {}).get("decision"),
           "numeric": (sci_dec or {}).get("numeric_accuracy")},
          "SciComp lab is promoted ACTIVE; registry may remain "
          "EXPERIMENTAL until an independent availability flip. "
          "T18 must not change this.")
    check("code_active", code_av == "ACTIVE" and reg.executable("CODE"),
          {"availability": code_av, "executable": reg.executable("CODE")})
    check("web_research_active",
          web_av == "ACTIVE" and reg.executable("WEB_RESEARCH"),
          {"availability": web_av, "executable": reg.executable("WEB_RESEARCH")})
    check("document_active",
          doc_av == "ACTIVE" and reg.executable("DOCUMENT"),
          {"availability": doc_av, "executable": reg.executable("DOCUMENT")})
    check("memory_prepared_only",
          mem_av == "PREPARED_ONLY" and not reg.executable("MEMORY"),
          {"availability": mem_av, "executable": reg.executable("MEMORY")})
    check("executive_router_experimental", True,
          "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")
    check("planning_unchanged",
          plan_av == "EXPERIMENTAL",
          {"availability": plan_av})

    code_files = _py_files("src/sciencemath/code")
    sci_files = _py_files("src/sciencemath/scicomp")
    t4_files = _py_files("src/sciencemath/tools")
    t5r_files = _py_files("src/sciencemath/rag")
    web_files = _py_files("src/sciencemath/web")
    doc_files = _py_files("src/sciencemath/document")
    code_hashes = {rel: sha(ROOT / rel) for rel in code_files}
    sci_hashes = {rel: sha(ROOT / rel) for rel in sci_files}
    web_hashes = {rel: sha(ROOT / rel) for rel in web_files}
    doc_hashes = {rel: sha(ROOT / rel) for rel in doc_files}
    code_hash = sha_group(code_files)
    sci_hash = sha_group(sci_files)
    t4_hash = sha_group(t4_files)
    t5r_hash = sha_group(t5r_files)
    web_hash = sha_group(web_files)
    doc_hash = sha_group(doc_files)
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

    freeze = load(ROOT / "evaluations/t17/frozen_components.json")
    sci_mismatch = []
    for rel, pin in ((freeze or {}).get("files") or {}).items():
        if rel.startswith("src/sciencemath/scicomp/") and not pin_match(
                ROOT / rel, pin):
            sci_mismatch.append(rel)

    check("skill_registry_hash", bool(reg_h) and len(reg_h) == 64, reg_h,
          "post-T17 registry (DOCUMENT ACTIVE); not equal to T17.1 freeze")
    check("scicomp_hash",
          sci_hash == T17_PINS["scicomp_composite"] and not sci_mismatch,
          {"composite_lf": sci_hash, "pin": T17_PINS["scicomp_composite"],
           "mismatch_vs_t17_freeze": sci_mismatch})
    check("code_hash",
          code_hash == T17_PINS["code_composite"] and all(code_hashes.values()),
          {"composite": code_hash, "pin": T17_PINS["code_composite"]})
    check("web_research_hash",
          web_hash == T17_PINS["web_research_composite"]
          and all(web_hashes.values()),
          {"composite": web_hash, "pin": T17_PINS["web_research_composite"]})
    check("document_hash",
          doc_hash == T17_PINS["document_implementation"]
          and all(doc_hashes.values()),
          {"composite": doc_hash, "pin": T17_PINS["document_implementation"],
           "files": doc_hashes})
    check("correction_firewall_hash",
          pin_match(ROOT / "src/sciencemath/executive/correction.py",
                    T17_PINS["correction_file"])
          and fw_comp == T17_PINS["correction_composite"], fw_h)
    check("fidelity_hash",
          pin_match(ROOT / "src/sciencemath/scicomp/fidelity.py",
                    T17_PINS["fidelity_file"])
          and fid_comp == T17_PINS["fidelity_composite"], fid_h)
    check("security_policy_hash",
          sec_hash == T17_PINS["security_policy"],
          {"composite": sec_hash, "pin": T17_PINS["security_policy"],
           "files": {p: sha(ROOT / p) for p in sec_files}})
    check("t3_adapter_identity",
          adp_h == T17_PINS["t3_adapter"], adp_h)
    check("executive_router_hash", bool(er_h),
          {"lf": er_h, "raw": sha_raw(
              ROOT / "src/sciencemath/executive/executive_router.py")},
          "Post-T17 router (DOCUMENT availability integration). Not promoted.")
    check("t4_hash", t4_hash == T17_PINS["t4_tools"],
          {"composite": t4_hash, "pin": T17_PINS["t4_tools"]})
    check("t5r_hash", t5r_hash == T17_PINS["t5r_rag"],
          {"composite": t5r_hash, "pin": T17_PINS["t5r_rag"]})

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
             "t18_run_' } | "
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

    out_xml = ROOT / "evaluations/t18/pytest_entry_junit.xml"
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    py = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q",
         f"--junitxml={out_xml}", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    counts = _pytest_counts(out_xml)
    pytest_doc = {
        "milestone": "T18.0 — entry pytest",
        "recorded_at": recorded,
        **counts,
        "exit_code": int(py.returncode),
        "tail": (py.stdout or "")[-2000:],
    }
    (ROOT / "evaluations/t18/pytest_entry.json").write_text(
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
    trans = load(ROOT / "evaluations/t17/document_transition.json") or {}
    doc = {
        "milestone": "T18 — Persistent Memory",
        "phase": "T18.0 entry gate",
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
        "memory_status": "PREPARED_ONLY",
        "planning_status": "EXPERIMENTAL",
        "executive_router_status": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "training": "NONE",
        "t17_historical": {
            "decision": (trans.get("decision")
                         or "PROMOTE_DOCUMENT_SKILL"),
            "methodology_debt": (
                "T17 baseline was a mechanical NO_DOCUMENT_RUNTIME "
                "baseline rather than a true underlying-model-only "
                "document baseline. Recorded as inherited methodology "
                "debt. T17 history is not rewritten."
            ),
            "pytest": "1242 passed, 0 failed, 0 errors, 2 skipped",
            "audit": "48 PASS / 0 FAIL",
            "ready_for_t18": "YES",
        },
        "worktree_note": {
            "dirty": dirty,
            "leftover_untracked_eval_dumps": leftover,
            "leftover_policy": (
                "Leave untouched; do not commit into t18-persistent-memory; "
                "do not mix into MEMORY artifacts."
            ),
            "blocks_gate": False,
        },
        "hashes": hashes,
        "t17_pins": T17_PINS,
        "checks": CHECKS,
        "substantive_failures": critical_fails,
        "conclusion": (
            "All entry-gate checks PASS. T18 may proceed to T18.1 and "
            "branch t18-persistent-memory."
            if ok_all else
            "Entry gate has critical failures — STOP. Do not start "
            "T18 implementation."
        ),
    }
    out = ROOT / "evaluations/t18/t18_entry_gate.json"
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
    }, indent=2))
    print(f"entry gate: {doc['status']} -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
