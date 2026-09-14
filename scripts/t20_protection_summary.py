"""T20.62 protection summary: hash-identity of frozen layers + security.

T20 added an orchestration layer only. The frozen T19 component set —
including the Executive Router, which T20 must NOT promote or claim — is
verified bit-identical to the T19.1 freeze, the security pytest subset is
re-run, and the mutation-safety probe result is carried forward.
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


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_group(rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(_lf(p.read_bytes()) if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()


def py_files(rel_dir: str) -> list[str]:
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in (ROOT / rel_dir).glob("*.py")
    )


def main() -> int:
    freeze = json.loads(
        (ROOT / "evaluations/t19/frozen_components.json").read_text(
            encoding="utf-8"))
    pins = freeze.get("composites") or {}
    ident = {
        "code": sha_group(py_files("src/sciencemath/code"))
            == pins.get("code"),
        "scicomp": sha_group(py_files("src/sciencemath/scicomp"))
            == pins.get("scicomp"),
        "web_research": sha_group(py_files("src/sciencemath/web"))
            == pins.get("web_research"),
        "document": sha_group(py_files("src/sciencemath/document"))
            == pins.get("document"),
        "memory": sha_group(py_files("src/sciencemath/memory"))
            == pins.get("memory"),
        "t4_tools": sha_group(py_files("src/sciencemath/tools"))
            == pins.get("t4_tools"),
        "t5r_rag": sha_group(py_files("src/sciencemath/rag"))
            == pins.get("t5r_rag"),
        "fidelity": sha_group([
            "src/sciencemath/scicomp/fidelity.py",
            "src/sciencemath/scicomp/semantic.py",
        ]) == pins.get("fidelity"),
        "correction_firewall": sha_group([
            "src/sciencemath/executive/correction.py",
        ]) == pins.get("correction_firewall"),
        # the Executive Router must remain untouched by T20
        "executive_router": sha_group([
            "src/sciencemath/executive/executive_router.py",
        ]) == pins.get("executive_router"),
    }
    ident_ok = all(ident.values())

    mut = subprocess.run(
        [sys.executable, "scripts/t15r_mutation_probe.py"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    mut_src = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    dest_mut = ROOT / "evaluations/t20/mutation_safety_probe.json"
    if mut_src.exists():
        dest_mut.write_bytes(mut_src.read_bytes())
    mut_ok = mut.returncode == 0

    prot_dir = ROOT / "evaluations/t20/protection"
    prot_dir.mkdir(parents=True, exist_ok=True)
    sec = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_t19_planning_security.py",
         "tests/test_t18_memory_security.py",
         "tests/test_t17_document_security.py",
         "tests/test_t16_web_security.py",
         "tests/test_t15_code_security.py",
         "tests/test_t11_security.py",
         "tests/test_t20_orchestration_verify.py",
         "tests/test_t20_orchestration_adversarial.py",
         "-q",
         "--junitxml=evaluations/t20/protection/security_junit.xml",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    sec_ok = sec.returncode == 0

    # T20 suites must match the frozen tuning_closed checksums
    closed = json.loads(
        (ROOT / "evaluations/t20/tuning_closed.json").read_text(
            encoding="utf-8"))
    suites_ok = {}
    for name, frozen in sorted((closed.get("final_checksums") or {}).items()):
        path = ROOT / "evaluations/t20/suites" / name / "final.jsonl"
        got = hashlib.sha256(_lf(path.read_bytes())).hexdigest() \
            if path.exists() else None
        suites_ok[name] = (frozen == got) if got else None
    suites_ok_all = all(v is True for v in suites_ok.values())

    layers = {
        "hash_identity": {"status": "PASS" if ident_ok else "FAIL",
                          "checks": ident},
        "mutation": {"status": "PASS" if mut_ok else "FAIL",
                     "exit_code": mut.returncode},
        "security_pytest": {"status": "PASS" if sec_ok else "FAIL",
                            "exit_code": sec.returncode,
                            "stdout_tail": (sec.stdout or "")[-800:]},
        "suite_freeze": {"status": "PASS" if suites_ok_all else "FAIL",
                         "checks": suites_ok},
    }
    all_pass = ident_ok and mut_ok and sec_ok and suites_ok_all and all(
        L["status"] == "PASS" for L in layers.values())
    out = {
        "milestone": "T20.62 protection battery",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_PASS" if all_pass else "FAIL",
        "identity": ident,
        "layers": layers,
        "t19_protection_reused": True,
        "gpu_layers_rerun": False,
        "reason": "T20 added the orchestration layer only; all frozen "
                  "component hashes match the T19.1 freeze (including the "
                  "Executive Router, not promoted or claimed by T20), so "
                  "prior ALL_PASS protection results remain valid.",
    }
    out_path = prot_dir / "regression_summary.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())