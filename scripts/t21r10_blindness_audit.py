"""AST firewall for the real T21R10 blind builders and static auditors."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r10"
SCRIPTS = (
    "t21r10_world.py",
    "t21r10_build_suites.py",
    "t21r10_retrieval_mirror.py",
    "t21r10_construction_audit.py",
    "t21r10_construction_gate.py",
    "t21r10_static_semantics.py",
    "t21r10_static_gold_audit.py",
    "t21r10_uniqueness.py",
)
FORBIDDEN_MODULE_FRAGMENTS = (
    "sciencemath", "pipeline", "router", "retrieval", "evidence_paths",
    "relations", "conflicts", "citation", "injection", "run_eval",
)
ALLOWED_LOCAL_RETRIEVAL = "t21r10_retrieval_mirror"
FORBIDDEN_CALLS = {
    "answer_knowledge", "resolve_path", "retrieve_structured",
    "run_answer_row", "evaluate", "official_evaluation",
}


def audit_scripts(root: Path = ROOT) -> dict:
    violations: list[str] = []
    hashes: dict[str, str] = {}
    import hashlib
    for name in SCRIPTS:
        path = root / "scripts" / name
        if not path.is_file():
            violations.append(f"missing preregistered script: {name}")
            continue
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            else:
                imports = []
            for imported in imports:
                if imported == ALLOWED_LOCAL_RETRIEVAL:
                    continue
                if any(fragment in imported
                       for fragment in FORBIDDEN_MODULE_FRAGMENTS):
                    violations.append(f"{name}: forbidden import {imported}")
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else \
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if called in FORBIDDEN_CALLS:
                    violations.append(f"{name}: forbidden call {called}")
    return {
        "artifact": "T21R10_BLINDNESS_AUDIT",
        "status": "PASS" if not violations else "FAIL",
        "scripts": hashes,
        "violations": violations,
        "runtime_execution_count": 0,
    }


def main() -> int:
    report = audit_scripts()
    path = OUT_DIR / "holdout_blindness.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
