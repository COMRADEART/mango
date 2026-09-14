"""T17.1 — freeze pre-T17 protected-component hashes.

Run after the T17.0 entry gate PASS and before DOCUMENT implementation.
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
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in (ROOT / rel_dir).glob("*.py")
    )


def main() -> int:
    from sciencemath.executive.skills import SkillRegistry, registry_sha256

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    groups = {
        "executive_router": [
            "src/sciencemath/executive/executive_router.py",
        ],
        "skill_registry": [
            "src/sciencemath/executive/skills.py",
        ],
        "code": py_files("src/sciencemath/code"),
        "scicomp": py_files("src/sciencemath/scicomp"),
        "web_research": py_files("src/sciencemath/web"),
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
        "milestone": "T17.1 — frozen pre-T17 architecture",
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
        "notes": [
            "T17 must not silently modify unrelated promoted capability behavior.",
            "Executive Router remains KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL.",
            "CODE, SciComp, and WEB_RESEARCH hashes are pins; DOCUMENT is additive.",
            "DOCUMENT remains PREPARED_ONLY until a promotion decision.",
            "MEMORY and PLANNING availability are unchanged.",
        ],
    }
    out = ROOT / "evaluations/t17/frozen_components.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "head": head,
        "registry": doc["registry_sha256"],
        "code": composites["code"],
        "scicomp": composites["scicomp"],
        "web": composites["web_research"],
        "router": composites["executive_router"],
        "availability": doc["registry_availability"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
