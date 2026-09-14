"""T17 protection summary: hash-identity of promoted layers + security + mutation."""
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
        (ROOT / "evaluations/t17/frozen_components.json").read_text(encoding="utf-8"))
    pins = freeze.get("composites") or {}
    t16p = json.loads(
        (ROOT / "evaluations/t16/protection/regression_summary.json").read_text(
            encoding="utf-8"))
    ident = {
        "code": sha_group(py_files("src/sciencemath/code")) == pins.get("code"),
        "scicomp": sha_group(py_files("src/sciencemath/scicomp")) == pins.get("scicomp"),
        "web_research": sha_group(py_files("src/sciencemath/web")) == pins.get("web_research"),
        "t4_tools": sha_group(py_files("src/sciencemath/tools")) == pins.get("t4_tools"),
        "t5r_rag": sha_group(py_files("src/sciencemath/rag")) == pins.get("t5r_rag"),
        "fidelity": sha_group([
            "src/sciencemath/scicomp/fidelity.py",
            "src/sciencemath/scicomp/semantic.py",
        ]) == pins.get("fidelity"),
        "correction_firewall": sha_group([
            "src/sciencemath/executive/correction.py",
        ]) == pins.get("correction_firewall"),
    }
    # mutation probe (local, no training)
    mut = subprocess.run(
        [sys.executable, "scripts/t15r_mutation_probe.py"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    mut_src = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    if mut_src.exists():
        (ROOT / "evaluations/t17/mutation_safety_probe.json").write_bytes(
            mut_src.read_bytes())
    mut_doc = json.loads(mut_src.read_text(encoding="utf-8")) if mut_src.exists() else {}
    mut_ok = mut.returncode == 0

    sec = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_t17_document_security.py",
         "tests/test_t16_web_security.py",
         "tests/test_t15_code_security.py",
         "tests/test_t11_security.py", "-q",
         "--junitxml=evaluations/t17/protection/security_junit.xml",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    sec_ok = sec.returncode == 0
    ident_ok = all(ident.values())
    layers = {}
    for name, layer in (t16p.get("layers") or {}).items():
        layers[name] = {
            "status": "PASS" if ident_ok and layer.get("status") == "PASS" else "FAIL",
            "t16_status": layer.get("status"),
            "identity_preserved": ident_ok,
            "note": "T17 did not re-run GPU protection layers; promoted "
                    "component hashes match the T17.1 freeze so T16 "
                    "ALL_PASS results remain valid.",
            **{k: v for k, v in layer.items() if k != "status"},
        }
    layers["mutation"] = {"status": "PASS" if mut_ok else "FAIL",
                          "exit_code": mut.returncode}
    layers["security_pytest"] = {"status": "PASS" if sec_ok else "FAIL",
                                 "exit_code": sec.returncode}
    layers["hash_identity"] = {"status": "PASS" if ident_ok else "FAIL",
                               "checks": ident}
    all_pass = ident_ok and mut_ok and sec_ok and all(
        L.get("status") == "PASS" for L in layers.values())
    out = {
        "milestone": "T17.48 protection battery",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_PASS" if all_pass else "FAIL",
        "identity": ident,
        "layers": layers,
        "t16_protection_reused": True,
        "gpu_layers_rerun": False,
        "reason": "CODE/SciComp/WEB/T4/T5R/fidelity/correction hashes unchanged "
                  "vs T17.1 freeze; T16 protection ALL_PASS reused. Mutation "
                  "probe and security pytest re-executed.",
    }
    dest = ROOT / "evaluations/t17/protection/regression_summary.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    (ROOT / "evaluations/t17/protection/security_summary.json").write_text(
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
