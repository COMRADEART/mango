"""T21.1 — freeze pre-T21 protected-component hashes.

Run after the T21.0 entry gate PASS and before KNOWLEDGE_RAG implementation.
Does not modify promoted runtimes.
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

ADAPTER = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_lf(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(_lf(path.read_bytes())).hexdigest()


def sha_raw(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() \
        else None


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
    d = ROOT / rel_dir
    if not d.exists():
        return []
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in d.glob("*.py")
    )


def suite_files() -> list[str]:
    out = []
    base = ROOT / "evaluations" / "t20" / "suites"
    if base.exists():
        for d in sorted(base.iterdir()):
            if d.is_dir():
                for name in ("dev.jsonl", "final.jsonl", "manifest.json"):
                    p = d / name
                    if p.exists():
                        out.append(
                            str(p.relative_to(ROOT)).replace("\\", "/"))
    return out


def main() -> int:
    from sciencemath.executive.skills import SkillRegistry, registry_sha256

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    groups = {
        "executive_router": [
            "src/sciencemath/executive/executive_router.py",
        ],
        "t20_orchestration_runtime": py_files("src/sciencemath/orchestration"),
        "t19_planning_runtime": py_files("src/sciencemath/planning"),
        "t7_existing_planning": [
            "src/sciencemath/executive/plan.py",
            "src/sciencemath/executive/replan.py",
            "src/sciencemath/executive/checkpoint.py",
            "src/sciencemath/executive/budgets.py",
            "src/sciencemath/executive/state.py",
            "src/sciencemath/executive/runner.py",
        ],
        "skill_registry": [
            "src/sciencemath/executive/skills.py",
        ],
        "code": py_files("src/sciencemath/code"),
        "scicomp": py_files("src/sciencemath/scicomp"),
        "web_research": py_files("src/sciencemath/web"),
        "document": py_files("src/sciencemath/document"),
        "memory": py_files("src/sciencemath/memory"),
        "t4_tools": py_files("src/sciencemath/tools"),
        "t5r_rag": py_files("src/sciencemath/rag"),
        "fidelity": [
            "src/sciencemath/scicomp/fidelity.py",
            "src/sciencemath/scicomp/semantic.py",
        ],
        "correction_firewall": [
            "src/sciencemath/executive/correction.py",
        ],
        "security_policy": [
            "src/sciencemath/code/safety.py",
            "tests/test_t15_code_security.py",
            "tests/test_t11_security.py",
        ],
        "historical_write_guard": [
            "tests/test_historical_artifact_write_guard.py",
            "evaluations/hygiene/historical_artifact_write_guard.json",
        ],
        "historical_adapter": [ADAPTER],
        "promoted_eval_definitions": [
            "evaluations/t15/suites/mango-code-eval-v1/final.jsonl",
            "evaluations/t15/suites/mango-code-eval-v1/manifest.json",
            "evaluations/t15r/suites/mango-code-eval-v1.1/final.jsonl",
            "evaluations/t15r/suites/mango-code-eval-v1.1/manifest.json",
            "evaluations/t14r2/scicomp_decision.json",
            "evaluations/t16/suites/mango-web-eval-v1/final.jsonl",
            "evaluations/t16/suites/mango-web-eval-v1/manifest.json",
            "evaluations/t16/suites/mango-evidence-core-v1/final.jsonl",
            "evaluations/t16/suites/mango-evidence-core-v1/manifest.json",
            "evaluations/t16/web_research_transition.json",
            "evaluations/t17/suites/mango-document-eval-v1/final.jsonl",
            "evaluations/t17/suites/mango-document-eval-v1/manifest.json",
            "evaluations/t17/suites/mango-data-core-v1/final.jsonl",
            "evaluations/t17/suites/mango-data-core-v1/manifest.json",
            "evaluations/t17/document_transition.json",
            "evaluations/t18/suites/mango-memory-core-v1/final.jsonl",
            "evaluations/t18/suites/mango-memory-core-v1/manifest.json",
            "evaluations/t18/suites/mango-memory-eval-v1/final.jsonl",
            "evaluations/t18/suites/mango-memory-eval-v1/manifest.json",
            "evaluations/t18/memory_transition.json",
            *suite_files(),
            "evaluations/t20/t20_entry_gate.json",
            "evaluations/t20/final_audit.json",
            "evaluations/t20/promotion_decision.json",
            "evaluations/t15r/mutation_safety_probe.json",
        ],
    }
    files: dict[str, str | None] = {}
    composites: dict[str, str] = {}
    for name, rels in groups.items():
        for rel in rels:
            p = ROOT / rel
            files[rel] = sha_raw(p) if rel == ADAPTER else sha_lf(p)
        composites[name] = sha_group(rels) if name != "historical_adapter" \
            else (files[ADAPTER] or "")

    reg = SkillRegistry()
    doc = {
        "milestone": "T21.1 — frozen pre-T21 architecture",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "hash_normalization": "LF for text; raw bytes for adapter",
        "groups": groups,
        "composites": composites,
        "files": files,
        "registry_sha256": registry_sha256(),
        "registry_availability": {
            sid: rec["availability"] for sid, rec in reg.as_dict().items()
        },
        "t15r_canonical_blob": "fba2437f78633884bd31965d78a4250bd1ca893c",
        "notes": [
            "T21 must not silently modify unrelated promoted capability "
            "behavior.",
            "Executive Router remains KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL.",
            "SCIENCE_RAG (t5r_rag), CODE, SciComp, WEB_RESEARCH, DOCUMENT, "
            "MEMORY, PLANNING, and ORCHESTRATION hashes are pins.",
            "T21 adds KNOWLEDGE_RAG as a new EXPERIMENTAL registry entry and "
            "a new knowledge package; it must not replace SCIENCE_RAG and "
            "must not rewrite T16-T20 history.",
            "KNOWLEDGE_RAG stays EXPERIMENTAL until the preregistered "
            "promotion gates pass.",
            "The T15R mutation-safety probe remains immutable at blob "
            "fba2437; T21 protection runs use milestone-local --out.",
        ],
    }
    out = ROOT / "evaluations/t21/frozen_components.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "head": head,
        "registry": doc["registry_sha256"],
        "code": composites["code"],
        "scicomp": composites["scicomp"],
        "web": composites["web_research"],
        "document": composites["document"],
        "memory": composites["memory"],
        "planning": composites["t19_planning_runtime"],
        "orchestration": composites["t20_orchestration_runtime"],
        "t5r_rag": composites["t5r_rag"],
        "router": composites["executive_router"],
        "availability": doc["registry_availability"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())