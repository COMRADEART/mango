"""T15.1 — freeze the pre-T15 architecture.

Records sha256 for every module T15 must not silently change:
Executive Router, skill registry (+ CODE skill definition), SciComp,
T4 tools, T5R RAG, fidelity, correction firewall, memory-adjacent
interfaces, and permission/security modules. Writes
evaluations/t15/frozen_components.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() \
        else None


def main() -> int:
    from sciencemath.executive.skills import SkillRegistry, registry_sha256

    reg = SkillRegistry()
    code_def = reg.get("CODE")
    code_blob = json.dumps(code_def, sort_keys=True, ensure_ascii=False)
    code_def_sha = hashlib.sha256(code_blob.encode("utf-8")).hexdigest()

    groups: dict[str, list[str]] = {
        "executive_router": [
            "src/sciencemath/executive/executive_router.py",
        ],
        "skill_registry": [
            "src/sciencemath/executive/skills.py",
        ],
        "code_skill_definition": [
            "src/sciencemath/executive/skills.py",  # CODE lives here pre-T15
        ],
        "scicomp": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / "src/sciencemath/scicomp").glob("*.py")),
        "t4_tools": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / "src/sciencemath/tools").glob("*.py")),
        "t5r_rag": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / "src/sciencemath/rag").glob("*.py")),
        "fidelity": [
            "src/sciencemath/scicomp/fidelity.py",
            "src/sciencemath/scicomp/semantic.py",
        ],
        "correction_firewall": [
            "src/sciencemath/executive/correction.py",
        ],
        # No persistent cross-session MEMORY runtime exists pre-T15 (the
        # MEMORY skill is PREPARED_ONLY). Closest memory-adjacent modules:
        "memory_interfaces": [
            "src/sciencemath/curriculum/failure_memory.py",
            "src/sciencemath/executive/checkpoint.py",
        ],
        "permission_security": [
            "src/sciencemath/executive/executive_router.py",
            "src/sciencemath/executive/skills.py",
            "src/sciencemath/rag/audit.py",
            "src/sciencemath/scicomp/sandbox.py",
            "src/sciencemath/scicomp/trust.py",
            "src/sciencemath/scicomp/verifier.py",
        ],
        "t14r_pins": [
            "src/sciencemath/scicomp/adoption.py",
            "src/sciencemath/scicomp/result_contract.py",
            "src/sciencemath/scicomp/planner_repair.py",
            "src/sciencemath/scicomp/invocation.py",
            "src/sciencemath/scicomp/ode_intent.py",
        ],
        # New T15 CODE package: did not exist pre-T15; recorded here as
        # the explicit reviewed T15 addition (not a silent change).
        "t15_code_new": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / "src/sciencemath/code").glob("*.py")),
    }

    files: dict[str, str | None] = {}
    for _group, rels in groups.items():
        for rel in rels:
            if rel not in files:
                files[rel] = sha(ROOT / rel)

    doc = {
        "milestone": "T15.1 — frozen pre-T15 architecture",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_head": "c27abc60f4288563d96f1a6a77908fa4081cd5f4",
        "groups": groups,
        "files": files,
        "registry_sha256": registry_sha256(),
        "registry_availability": {
            sid: reg.availability(sid) for sid in reg.ids()},
        "code_skill_definition_sha256": code_def_sha,
        "code_skill_definition": code_def,
        "adapter_sha256": sha(ROOT / "training/adapters/sciencemath-v0.1-t3"
                              / "adapter_model.safetensors"),
        "suite_scicomp_sha256": sha(
            ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl"),
        "note": ("T15 must not silently change unrelated promoted capability "
                 "behavior. Any diff in these files at final audit must be "
                 "an explicit, reviewed T15 change or FAIL."),
    }
    out = ROOT / "evaluations/t15/frozen_components.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"froze {len(files)} files -> {out}")
    print(f"registry={doc['registry_sha256']}")
    print(f"code_def={code_def_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
