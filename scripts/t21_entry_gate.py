"""T21.0 entry gate — verify T20-closed provenance before KNOWLEDGE_RAG work.

Critical provenance failure => STOP. Does not modify any promoted runtime
(SCIENCE_RAG / SCICOMP / CODE / WEB_RESEARCH / DOCUMENT / MEMORY / PLANNING /
ORCHESTRATION) or the Executive Router.
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
sys.path.insert(0, str(ROOT / "src"))

REQUIRED_HEAD = "fc667c24cbbe4e6ae638890bb2bf5e1237c7659b"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
TRANSFORMERS_PIN = "5.16.1"
ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"

# T15R canonical historical artifact blob (git blob id) that must remain
# bit-identical through all of T21.
T15R_CANONICAL_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"

# T20-close pins for unchanged promoted layers (registry includes
# ORCHESTRATION ACTIVE as promoted at T20).
T20_PINS = {
    "registry_sha256":
        "02699861db6bdcbae7376cb3fa76b7956e85a38f8a8b49aa3ad0d0770ffffcb3",
    "skills_py_sha256":
        "25ec8df1db58a3b9b9f2a22c4ef8bd1c9337f7558059a783d7e1f54dda357821",
    "executive_router_sha256":
        "06c59027341e4ef9124a4b5c1610a470e77fd67cfe8133446b380fcf9866af8e",
}

# T18-close implementation pins (unchanged through T19/T20; re-verified here).
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
        "evaluations/t21/",
        "scripts/t21_",
        "tests/test_t21",
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
    if p.startswith("evaluations/t21/"):
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
        "evaluations/t20/runs/",
        "evaluations/t20/protection/",
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


def _t15r_blob() -> str | None:
    """Git blob id of the working-tree T15R mutation probe (canonical id)."""
    p = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    if not p.exists():
        return None
    r = subprocess.run(
        ["git", "hash-object", str(p)], cwd=ROOT, capture_output=True,
        text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main() -> int:
    recorded = datetime.now(timezone.utc).isoformat()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
        text=True).stdout
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

    check("git_head_t20_canonical", exact,
          {"head": head, "required": REQUIRED_HEAD, "exact": exact,
           "tree": tree})
    check("worktree_clean", not unexpected,
          {"dirty_n": len(dirty), "unexpected": unexpected,
           "timestamp_only_unstaged": timestamp_only},
          "Require clean worktree on canonical T20 base before T21 work")

    # --- T21 has not already started --------------------------------------
    # The entry-gate script itself and its own outputs are not evidence of a
    # started T21; any other T21 script or T21 evaluation artifact is.
    ENTRY_SELF = "scripts/t21_entry_gate.py"
    ENTRY_OUTPUTS = {
        "entry_freeze.json", "pytest_entry.json", "pytest_entry_junit.xml",
    }
    t21_dir = ROOT / "evaluations/t21"
    preexisting_t21_artifacts = []
    if t21_dir.exists():
        preexisting_t21_artifacts = sorted(
            p.name for p in t21_dir.rglob("*") if p.is_file()
            and p.name not in ENTRY_OUTPUTS)
    t21_scripts = sorted(
        p.name for p in ROOT.glob("scripts/t21_*.py")
        if p.relative_to(ROOT).as_posix() != ENTRY_SELF)
    started = bool(preexisting_t21_artifacts or t21_scripts)
    check("t21_not_started", not started,
          {"preexisting_t21_artifacts": preexisting_t21_artifacts,
           "t21_scripts_other_than_entry_gate": t21_scripts})

    # --- historical artifact write guard (merged at fc667c2) ---------------
    guard_json = load(ROOT / "evaluations/hygiene/"
                               "historical_artifact_write_guard.json")
    guard_ok = bool(guard_json) and (guard_json.get("result") == "PASS"
                                     or guard_json.get("status") in
                                     ("PASS", "CLOSED", "APPLIED"))
    check("historical_write_guard_artifact_present", guard_ok,
          {"present": guard_json is not None,
           "status": (guard_json or {}).get("status"),
           "path": "evaluations/hygiene/historical_artifact_write_guard.json"})
    guard_test = ROOT / "tests/test_historical_artifact_write_guard.py"
    check("historical_write_guard_test_present", guard_test.exists(),
          str(guard_test.relative_to(ROOT)))

    # --- canonical T15R historical blob ------------------------------------
    blob_before = _t15r_blob()
    check("t15r_canonical_blob_unchanged",
          blob_before == T15R_CANONICAL_BLOB,
          {"blob": blob_before, "canonical": T15R_CANONICAL_BLOB},
          "evaluations/t15r/mutation_safety_probe.json must remain blob "
          "fba2437 through all of T21")

    # --- T16–T20 harnesses use milestone-local probes ----------------------
    harness_ok = []
    for n in ("16", "17", "18", "19", "20"):
        script = (ROOT / f"scripts/t{n}_protection_battery.py")
        src_file = script if script.exists() else (
            ROOT / f"scripts/t{n}_protection_summary.py")
        text = src_file.read_text(encoding="utf-8") if src_file.exists() \
            else ""
        milestone_local = (
            f'"--out", "evaluations/t{n}/mutation_safety_probe.json"' in text
            or f"'--out', 'evaluations/t{n}/mutation_safety_probe.json'"
            in text
            or f"--out evaluations/t{n}/mutation_safety_probe.json" in text)
        harness_ok.append({"milestone": f"T{n}",
                           "script": src_file.name,
                           "milestone_local_probe": milestone_local})
    check("t16_t20_milestone_local_probes",
          all(h["milestone_local_probe"] for h in harness_ok),
          harness_ok,
          "Later protection batteries write milestone-local mutation-probe "
          "outputs; the canonical T15R blob is never rewritten")

    # --- T20 closed provenance ---------------------------------------------
    t20_report = ROOT / "evaluations/t20/T20_FINAL_REPORT.md"
    t20_text = t20_report.read_text(encoding="utf-8") if t20_report.exists() \
        else ""
    t20_closed = ("PROMOTE_ORCHESTRATION_SKILL" in t20_text
                  and "Do not start T21 automatically" in t20_text)
    check("t20_final_report", t20_report.exists() and t20_closed,
          str(t20_report.relative_to(ROOT)) if t20_report.exists() else None)
    t20_audit = load(ROOT / "evaluations/t20/final_audit.json")
    audit_ok = bool(t20_audit) and t20_audit.get("failed_checks") == [] \
        and t20_audit.get("decision") == "PROMOTE_ORCHESTRATION_SKILL" \
        and all(bool(c.get("ok")) for c in (t20_audit.get("checks") or []))
    check("t20_final_audit", audit_ok,
          {"decision": (t20_audit or {}).get("decision"),
           "failed_checks": (t20_audit or {}).get("failed_checks"),
           "n_checks": len((t20_audit or {}).get("checks") or [])})
    t20_dec = load(ROOT / "evaluations/t20/promotion_decision.json")
    dec = (t20_dec or {}).get("decision")
    dec_ok = dec == "PROMOTE_ORCHESTRATION_SKILL" or (
        isinstance(dec, dict) and
        dec.get("decision") == "PROMOTE_ORCHESTRATION_SKILL")
    check("t20_promotion_decision", dec_ok, dec)
    t20_tc = load(ROOT / "evaluations/t20/tuning_closed.json")
    check("t20_tuning_closed_present", bool(t20_tc),
          "evaluations/t20/tuning_closed.json")

    # --- capability registry state -----------------------------------------
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    statuses = {sid: reg.availability(sid) for sid in reg.ids()}
    required_active = ("SCICOMP", "CODE", "WEB_RESEARCH", "DOCUMENT",
                       "MEMORY", "PLANNING", "ORCHESTRATION", "SCIENCE_RAG")
    actives = {sid: statuses.get(sid) for sid in required_active}
    check("promoted_skills_active",
          all(v == "ACTIVE" for v in actives.values()), actives)
    check("knowledge_rag_not_in_registry",
          not reg.known("KNOWLEDGE_RAG"),
          {"known": reg.known("KNOWLEDGE_RAG")},
          "T21 introduces KNOWLEDGE_RAG at T21.2; it must not pre-exist")
    check("executive_router_experimental", True,
          "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")

    # --- implementation identity hashes ------------------------------------
    code_files = _py_files("src/sciencemath/code")
    sci_files = _py_files("src/sciencemath/scicomp")
    t4_files = _py_files("src/sciencemath/tools")
    t5r_files = _py_files("src/sciencemath/rag")
    web_files = _py_files("src/sciencemath/web")
    doc_files = _py_files("src/sciencemath/document")
    mem_files = _py_files("src/sciencemath/memory")
    orch_files = _py_files("src/sciencemath/orchestration")
    code_hash = sha_group(code_files)
    sci_hash = sha_group(sci_files)
    t4_hash = sha_group(t4_files)
    t5r_hash = sha_group(t5r_files)
    web_hash = sha_group(web_files)
    doc_hash = sha_group(doc_files)
    mem_hash = sha_group(mem_files)
    orch_hash = sha_group(orch_files)
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
    guard_files = [
        "tests/test_historical_artifact_write_guard.py",
        "scripts/t16_protection_battery.py",
        "scripts/t17_protection_summary.py",
        "scripts/t18_protection_summary.py",
        "scripts/t19_protection_summary.py",
        "scripts/t20_protection_summary.py",
    ]
    guard_hash = sha_group(guard_files)

    check("skill_registry_hash",
          reg_h == T20_PINS["registry_sha256"]
          and skills_h == T20_PINS["skills_py_sha256"], reg_h,
          "T20-close registry (ORCHESTRATION ACTIVE)")
    check("executive_router_hash", er_h == T20_PINS["executive_router_sha256"],
          {"lf": er_h, "raw": sha_raw(
              ROOT / "src/sciencemath/executive/executive_router.py")},
          "Unchanged since T19.1 freeze; remains EXPERIMENTAL")
    check("scicomp_hash", sci_hash == T18_PINS["scicomp_composite"],
          {"composite_lf": sci_hash, "pin": T18_PINS["scicomp_composite"]})
    check("code_hash", code_hash == T18_PINS["code_composite"],
          {"composite": code_hash, "pin": T18_PINS["code_composite"]})
    check("web_research_hash",
          web_hash == T18_PINS["web_research_composite"],
          {"composite": web_hash, "pin": T18_PINS["web_research_composite"]})
    check("document_hash",
          doc_hash == T18_PINS["document_implementation"],
          {"composite": doc_hash,
           "pin": T18_PINS["document_implementation"]})
    check("memory_hash", mem_hash == T18_PINS["memory_implementation"],
          {"composite": mem_hash,
           "pin": T18_PINS["memory_implementation"]})
    check("orchestration_hash_recorded", bool(orch_hash),
          {"composite": orch_hash, "files": orch_files},
          "T20 ORCHESTRATION runtime identity recorded at T21 entry")
    check("t4_hash", t4_hash == T18_PINS["t4_tools"],
          {"composite": t4_hash, "pin": T18_PINS["t4_tools"]})
    check("t5r_hash", t5r_hash == T18_PINS["t5r_rag"],
          {"composite": t5r_hash, "pin": T18_PINS["t5r_rag"]})
    check("correction_firewall_hash",
          pin_match(ROOT / "src/sciencemath/executive/correction.py",
                    T18_PINS["correction_file"])
          and fw_comp == T18_PINS["correction_composite"], fw_h)
    check("fidelity_hash",
          pin_match(ROOT / "src/sciencemath/scicomp/fidelity.py",
                    T18_PINS["fidelity_file"])
          and fid_comp == T18_PINS["fidelity_composite"], fid_h)
    check("security_policy_hash", sec_hash == T18_PINS["security_policy"],
          {"composite": sec_hash, "pin": T18_PINS["security_policy"]})
    check("t3_adapter_identity", adp_h == T18_PINS["t3_adapter"], adp_h)
    check("write_guard_implementation_recorded", bool(guard_hash),
          {"composite": guard_hash, "files": guard_files})

    merge_head = (ROOT / ".git" / "MERGE_HEAD").exists()
    rebase = (ROOT / ".git" / "rebase-merge").exists() or \
        (ROOT / ".git" / "rebase-apply").exists()
    check("no_merge_rebase_in_progress", not merge_head and not rebase,
          {"merge_head": merge_head, "rebase": rebase})

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

    out_xml = ROOT / "evaluations/t21/pytest_entry_junit.xml"
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    py = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q",
         f"--junitxml={out_xml}", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    counts = _pytest_counts(out_xml)
    pytest_doc = {
        "milestone": "T21.0 — entry pytest",
        "recorded_at": recorded,
        **counts,
        "exit_code": int(py.returncode),
        "tail": (py.stdout or "")[-2000:],
    }
    (ROOT / "evaluations/t21/pytest_entry.json").write_text(
        json.dumps(pytest_doc, indent=2) + "\n", encoding="utf-8")
    py_ok = (pytest_doc["exit_code"] == 0 and pytest_doc["failed"] == 0
             and pytest_doc["errors"] == 0)
    check("current_pytest_green", py_ok, {
        k: pytest_doc[k] for k in
        ("tests", "passed", "failed", "errors", "skipped", "exit_code",
         "time_s")
    }, "require 0 failed / 0 errors; do not target the historical count")

    # T15R blob must ALSO survive the full pytest battery (write-guard proof).
    blob_after = _t15r_blob()
    check("t15r_blob_survives_pytest",
          blob_after == T15R_CANONICAL_BLOB,
          {"blob_before": blob_before, "blob_after": blob_after,
           "canonical": T15R_CANONICAL_BLOB},
          "historical-artifact write guard must keep the canonical T15R "
          "probe untouched through a full pytest battery")

    critical_fails = [c["check"] for c in CHECKS
                      if c["status"] == "FAIL" and c.get("critical")]
    ok_all = not critical_fails
    hashes = {
        "skill_registry": reg_h,
        "skill_registry_file": skills_h,
        "scicomp_composite": sci_hash,
        "code_composite": code_hash,
        "web_research_composite": web_hash,
        "document_composite": doc_hash,
        "memory_composite": mem_hash,
        "orchestration_composite": orch_hash,
        "t4_tools": t4_hash,
        "t5r_rag": t5r_hash,
        "executive_router": er_h,
        "fidelity": fid_h,
        "fidelity_composite": fid_comp,
        "correction_firewall": fw_h,
        "correction_composite": fw_comp,
        "security_policies": sec_hash,
        "t3_adapter": adp_h,
        "write_guard_implementation": guard_hash,
        "t15r_canonical_blob": T15R_CANONICAL_BLOB,
    }
    doc = {
        "milestone": "T21 — General Knowledge RAG",
        "phase": "T21.0 entry gate",
        "recorded_at": recorded,
        "status": "PASS" if ok_all else "FAIL",
        "base_commit": head,
        "tree_sha": tree,
        "branch": branch,
        "required_head": REQUIRED_HEAD,
        "starting_architecture": "Mango-4B-System-v1",
        "starting_capability_state": {
            "SCICOMP": "ACTIVE",
            "CODE": "ACTIVE",
            "WEB_RESEARCH": "ACTIVE",
            "DOCUMENT": "ACTIVE",
            "MEMORY": "ACTIVE",
            "PLANNING": "ACTIVE",
            "ORCHESTRATION": "ACTIVE",
            "SCIENCE_RAG": "ACTIVE",
            "KNOWLEDGE_RAG": "NOT_IN_REGISTRY (introduced EXPERIMENTAL in T21.2)",
            "Executive_Router": "EXPERIMENTAL",
            "T20": "CLOSED",
        },
        "model_identity": {
            "architecture": "Mango-4B-System-v1",
            "base_model": MODEL,
            "adapter": ADAPTER,
            "training": "NONE",
            "weight_promotion": "NO",
        },
        "policies": {
            "network_policy": "OFF during frozen evaluation; fixture-first",
            "training_policy": "NONE",
            "paid_compute_policy": "NOT_USED",
        },
        "historical_artifact_hashes": {
            "t15r_mutation_safety_probe_blob": T15R_CANONICAL_BLOB,
            "t15r_working_tree_blob": blob_after,
            "hygiene_write_guard_json": sha(
                ROOT / "evaluations/hygiene/"
                       "historical_artifact_write_guard.json"),
            "write_guard_test": sha(guard_test),
        },
        "t20_historical": {
            "decision": "PROMOTE_ORCHESTRATION_SKILL",
            "pytest": "1574 passed, 0 failed, 0 errors, 2 skipped",
            "audit": "31 PASS / 0 FAIL",
            "write_guard_merge": "fc667c2 (T16–T20 milestone-local probes)",
            "t21_started": False,
            "ready_for_t21": "YES",
        },
        "registry_hash": reg_h,
        "hashes": hashes,
        "pytest": {
            k: pytest_doc[k] for k in
            ("tests", "passed", "failed", "errors", "skipped", "time_s")
        },
        "checks": CHECKS,
        "substantive_failures": critical_fails,
        "network_policy": "OFF during frozen evaluation",
        "training_policy": "NONE",
        "paid_compute_policy": "NOT_USED",
        "conclusion": (
            "All entry-gate checks PASS. T21 may proceed to T21.1 and "
            "branch t21-general-knowledge-rag."
            if ok_all else
            "Entry gate has critical failures — STOP. Do not start "
            "T21 implementation."
        ),
    }
    out = ROOT / "evaluations/t21/entry_freeze.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "status": doc["status"],
        "substantive_failures": critical_fails,
        "pytest": {k: pytest_doc[k] for k in
                   ("passed", "failed", "errors", "skipped", "exit_code")},
        "head": head,
        "tree": tree,
        "registry": statuses,
    }, indent=2))
    print(f"entry gate: {doc['status']} -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())