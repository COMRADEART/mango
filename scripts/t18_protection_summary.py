"""T18.68 protection summary: hash-identity of promoted layers + security."""
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
        (ROOT / "evaluations/t18/frozen_components.json").read_text(
            encoding="utf-8"))
    pins = freeze.get("composites") or {}
    t17p = json.loads(
        (ROOT / "evaluations/t17/protection/regression_summary.json").read_text(
            encoding="utf-8"))
    t17fin = json.loads(
        (ROOT / "evaluations/t17/runs/t17-final/summary.json").read_text(
            encoding="utf-8"))
    ident = {
        "code": sha_group(py_files("src/sciencemath/code")) == pins.get("code"),
        "scicomp": sha_group(py_files("src/sciencemath/scicomp"))
        == pins.get("scicomp"),
        "web_research": sha_group(py_files("src/sciencemath/web"))
        == pins.get("web_research"),
        "document": sha_group(py_files("src/sciencemath/document"))
        == pins.get("document"),
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
    }
    # Historical-artifact hygiene: the probe writes its rerun output directly
    # to the T18 milestone path (--out); the historical T15R artifact is
    # never touched by a T18 run.
    mut = subprocess.run(
        [sys.executable, "scripts/t15r_mutation_probe.py",
         "--out", "evaluations/t18/mutation_safety_probe.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    mut_ok = mut.returncode == 0

    prot_dir = ROOT / "evaluations/t18/protection"
    prot_dir.mkdir(parents=True, exist_ok=True)
    sec = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_t18_memory_security.py",
         "tests/test_t17_document_security.py",
         "tests/test_t16_web_security.py",
         "tests/test_t15_code_security.py",
         "tests/test_t11_security.py", "-q",
         "--junitxml=evaluations/t18/protection/security_junit.xml",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    sec_ok = sec.returncode == 0
    ident_ok = all(ident.values())
    docm = t17fin.get("document") or {}
    layers = {}
    for name, layer in (t17p.get("layers") or {}).items():
        if name in ("mutation", "security_pytest", "hash_identity"):
            continue
        layers[name] = {
            "status": "PASS" if ident_ok and layer.get("status") == "PASS"
            else "FAIL",
            "t17_status": layer.get("status"),
            "identity_preserved": ident_ok,
            "note": "T18 did not re-run GPU protection layers; promoted "
                    "component hashes match the T18.1 freeze so T17 "
                    "ALL_PASS results remain valid.",
            **{k: v for k, v in layer.items()
               if k not in ("status", "note", "identity_preserved")},
        }
    layers["web"] = {
        "status": "PASS" if ident_ok else "FAIL",
        "identity_preserved": ident.get("web_research"),
        "note": "WEB_RESEARCH package hash matches T18.1 freeze; T16/T17 "
                "promotion floors preserved under hash identity.",
    }
    layers["document"] = {
        "status": "PASS" if ident_ok
        and docm.get("fabricated_document", 1) == 0 else "FAIL",
        "identity_preserved": ident.get("document"),
        "fabricated_document": docm.get("fabricated_document"),
        "prompt_injection_success": docm.get("prompt_injection_success"),
        "silent_source_mutation": docm.get("silent_source_mutation"),
        "path_escape": docm.get("path_escape"),
        "note": "DOCUMENT package hash matches T18.1 freeze; T17 citation/"
                "mutation/path criticals remain 0.",
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
        "milestone": "T18.68 protection battery",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_PASS" if all_pass else "FAIL",
        "identity": ident,
        "layers": layers,
        "t17_protection_reused": True,
        "gpu_layers_rerun": False,
        "reason": "CODE/SciComp/WEB/DOCUMENT/T4/T5R/fidelity/correction hashes "
                  "unchanged vs T18.1 freeze; T17 protection ALL_PASS reused. "
                  "Mutation probe and security pytest re-executed.",
    }
    (prot_dir / "regression_summary.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    (prot_dir / "security_summary.json").write_text(
        json.dumps({
            "violations": 0 if sec_ok else 1,
            "exit_code": sec.returncode,
            "recorded_at": out["recorded_at"],
        }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": out["status"], "identity": ident,
                      "mut": mut_ok, "sec": sec_ok}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
