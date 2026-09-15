"""T21R3.B1 — freeze the repaired KNOWLEDGE_RAG runtime BEFORE holdout data.

Records composite SHA-256 hashes over every frozen runtime group after the
T21R3 repair commit. KNOWLEDGE_RAG remains EXPERIMENTAL at freeze time.

Ordering: repair commit -> runtime freeze -> evaluator freeze -> holdout
construction -> HOLDOUT_FROZEN -> one-shot evaluation.

Usage: python scripts/t21r3_freeze_runtime.py
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

_GUARD_TEST = "tests/test_historical_artifact_write_guard.py"
_PROBE_SCRIPT = "scripts/t15r_mutation_" + "probe.py"

RUNTIME_GROUPS = {
    "knowledge_runtime": ["src/sciencemath/knowledge/"],
    "executive_skills": ["src/sciencemath/executive/skills.py"],
    "executive_router": ["src/sciencemath/executive/executive_router.py"],
    "science_rag_runtime": ["src/sciencemath/rag/"],
    "web_research_runtime": ["src/sciencemath/web/"],
    "document_runtime": ["src/sciencemath/document/"],
    "memory_runtime": ["src/sciencemath/memory/"],
    "planning_runtime": ["src/sciencemath/planning/"],
    "orchestration_runtime": ["src/sciencemath/orchestration/"],
    "scicomp_runtime": ["src/sciencemath/scicomp/"],
    "code_runtime": ["src/sciencemath/code/"],
    "correction_firewall": [
        "src/sciencemath/executive/correction.py",
        "src/sciencemath/executive/verify.py",
        "src/sciencemath/executive/repair.py",
        "src/sciencemath/executive/replan.py",
    ],
    "security_layer": [
        "src/sciencemath/knowledge/injection.py",
        "src/sciencemath/knowledge/provenance_spoof.py",
        "src/sciencemath/executive/state.py",
    ],
    "historical_write_guard": [_GUARD_TEST, _PROBE_SCRIPT],
}

OUT_DIR = ROOT / "evaluations" / "t21r3"
PROJECT_BASE = "ac7492b0f4e37fdc0adcb69d879c0f8c0b881372"
PARTIAL_CHECKPOINT = "775b750c6280141c234189ec907123926be11232"
REPAIR_COMMIT = "b0c03a0d8a974aa3248c07bf1dbc2ced4501b28d"
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_group(rel_specs: list[str]) -> str:
    paths: list[Path] = []
    for spec in rel_specs:
        if spec.endswith("/"):
            base = ROOT / spec
            paths.extend(sorted(p for p in base.rglob("*.py")
                                if "__pycache__" not in p.parts))
        else:
            paths.append(ROOT / spec)
    h = hashlib.sha256()
    for p in sorted(paths):
        rel = p.relative_to(ROOT).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(_lf(p.read_bytes()) if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()


def sha_lf(path: Path) -> str:
    return hashlib.sha256(_lf(path.read_bytes())).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def main() -> int:
    head = _git("rev-parse", "HEAD")
    log = _git("log", "--pretty=%H", "-50").splitlines()
    if PARTIAL_CHECKPOINT not in log and head != PARTIAL_CHECKPOINT:
        # also accept abbreviated match
        if not any(h.startswith(PARTIAL_CHECKPOINT[:12]) for h in log):
            raise SystemExit("partial checkpoint 775b750 not in ancestry")
    if REPAIR_COMMIT not in log and head != REPAIR_COMMIT:
        if not any(h.startswith(REPAIR_COMMIT[:12]) for h in log):
            raise SystemExit(f"repair commit {REPAIR_COMMIT} not in ancestry")

    if (ROOT / "evaluations" / "t22").exists():
        raise SystemExit("T22 must not have started")
    if (ROOT / "rag" / "gk_holdout_t21r3" / "world.jsonl").exists():
        raise SystemExit(
            "holdout world already exists: runtime must freeze BEFORE "
            "holdout construction")

    composites = {name: sha_group(spec)
                  for name, spec in RUNTIME_GROUPS.items()}

    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    registry_record = {
        "availability": reg.availability("KNOWLEDGE_RAG"),
        "registry_sha256": registry_sha256(reg),
        "skills_py_sha256_lf": sha_lf(
            ROOT / "src/sciencemath/executive/skills.py"),
        "counts": reg.counts(),
    }
    if registry_record["availability"] != "EXPERIMENTAL":
        raise SystemExit(
            "KNOWLEDGE_RAG must be EXPERIMENTAL at T21R3 runtime freeze")

    t15r = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    blob = _git("hash-object", str(t15r))
    if blob != T15R_BLOB:
        raise SystemExit(f"T15R blob drifted: {blob}")

    doc = {
        "milestone": "T21R3.B1 runtime freeze (repaired runtime, before holdout)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "project_base": PROJECT_BASE,
        "partial_checkpoint": PARTIAL_CHECKPOINT,
        "repair_commit": REPAIR_COMMIT,
        "git_head": head,
        "git_tree_sha": _git("rev-parse", "HEAD^{tree}"),
        "t15r_canonical_blob": T15R_BLOB,
        "runtime_composites": composites,
        "knowledge_rag_registry": registry_record,
        "executive_router_status": "EXPERIMENTAL (unchanged)",
        "order_rule": (
            "This freeze exists BEFORE rag/gk_holdout_t21r3 contains any "
            "holdout world/corpus and BEFORE the evaluator is frozen. From "
            "this moment forward NO runtime change is allowed during T21R3 "
            "holdout construction or the one-shot evaluation."
        ),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "runtime_freeze.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "FROZEN",
        "out": out.as_posix(),
        "repair_commit": REPAIR_COMMIT,
        "knowledge_rag": registry_record["availability"],
        "registry_sha256": registry_record["registry_sha256"],
        "knowledge_runtime": composites["knowledge_runtime"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
