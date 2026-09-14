"""T19.65 protection summary: hash-identity of promoted layers + security."""
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
    t18p = json.loads(
        (ROOT / "evaluations/t18/protection/regression_summary.json").read_text(
            encoding="utf-8"))
    t18fin = json.loads(
        (ROOT / "evaluations/t18/runs/t18-final/summary.json").read_text(
            encoding="utf-8"))
    ident = {
        "code": sha_group(py_files("src/sciencemath/code")) == pins.get("code"),
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
        "executive_router": sha_group([
            "src/sciencemath/executive/executive_router.py",
        ]) == pins.get("executive_router"),
    }
    mut = subprocess.run(
        [sys.executable, "scripts/t15r_mutation_probe.py"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    mut_src = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    dest_mut = ROOT / "evaluations/t19/mutation_safety_probe.json"
    if mut_src.exists():
        dest_mut.write_bytes(mut_src.read_bytes())
    mut_ok = mut.returncode == 0

    prot_dir = ROOT / "evaluations/t19/protection"
    prot_dir.mkdir(parents=True, exist_ok=True)
    sec = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_t19_planning_security.py",
         "tests/test_t18_memory_security.py",
         "tests/test_t17_document_security.py",
         "tests/test_t16_web_security.py",
         "tests/test_t15_code_security.py",
         "tests/test_t11_security.py", "-q",
         "--junitxml=evaluations/t19/protection/security_junit.xml",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    sec_ok = sec.returncode == 0
    ident_ok = all(ident.values())
    mem = t18fin.get("combined") or t18fin.get("memory") or {}
    layers = {}
    for name, layer in (t18p.get("layers") or {}).items():
        if name in ("mutation", "security_pytest", "hash_identity"):
            continue
        layers[name] = {
            "status": "PASS" if ident_ok and layer.get("status") == "PASS"
            else "FAIL",
            "t18_status": layer.get("status"),
            "identity_preserved": ident_ok,
            "note": "T19 did not re-run GPU protection layers; promoted "
                    "component hashes match the T19.1 freeze so T18 "
                    "ALL_PASS results remain valid.",
        }
    layers["memory"] = {
        "status": "PASS" if ident.get("memory")
        and mem.get("fabricated_memory_claim", 1) == 0 else "FAIL",
        "identity_preserved": ident.get("memory"),
        "owner_isolation": mem.get("owner_isolation"),
        "fabricated_memory_claim": mem.get("fabricated_memory_claim"),
        "secret_persisted": mem.get("secret_persisted"),
        "prompt_injection_success": mem.get("prompt_injection_success"),
        "deleted_memory_resurfacing": mem.get("deleted_memory_resurfacing"),
    }
    layers["mutation"] = {"status": "PASS" if mut_ok else "FAIL",
                          "exit_code": mut.returncode}
    layers["security_pytest"] = {"status": "PASS" if sec_ok else "FAIL",
                                 "exit_code": sec.returncode,
                                 "stdout_tail": (sec.stdout or "")[-800:]}
    layers["hash_identity"] = {"status": "PASS" if ident_ok else "FAIL",
                               "checks": ident}
    all_pass = ident_ok and mut_ok and sec_ok and all(
        L.get("status") == "PASS" for L in layers.values())
    out = {
        "milestone": "T19.65 protection battery",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_PASS" if all_pass else "FAIL",
        "identity": ident,
        "layers": layers,
        "t18_protection_reused": True,
        "gpu_layers_rerun": False,
        "reason": "CODE/SciComp/WEB/DOCUMENT/MEMORY/T4/T5R/fidelity/"
                  "correction/router hashes unchanged vs T19.1 freeze; "
                  "T18 protection ALL_PASS reused. Mutation probe and "
                  "security pytest re-executed.",
    }
    (prot_dir / "regression_summary.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    (prot_dir / "security_summary.json").write_text(
        json.dumps({"violations": 0 if sec_ok else 1,
                    "exit_code": sec.returncode}, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({"status": out["status"], "ident_ok": ident_ok,
                      "mut_ok": mut_ok, "sec_ok": sec_ok}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
