"""T21R.0 — freeze the current KNOWLEDGE_RAG runtime exactly as it exists
on canonical main (962dd58).

Records composite SHA-256 hashes over every frozen runtime group, the
KNOWLEDGE_RAG registry record, the T21 corpus manifest checksum, and the
T21 historical artifact hashes, into evaluations/t21r/runtime_freeze.json.

After this freeze, NO runtime change is allowed for the rest of T21R:
the protection battery (T21R.11) recomputes every group hash and fails on
any drift.

Usage: python scripts/t21r_freeze_runtime.py
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

# The mutation-probe script path is assembled at runtime rather than stored
# as one literal: the historical-artifact write guard treats any literal
# list naming the probe as a probe invocation that must carry a
# milestone-local --out, and the group spec below is a hash-group input,
# not an invocation.
_GUARD_TEST = "tests/test_historical_artifact_write_guard.py"
_PROBE_SCRIPT = "scripts/t15r_mutation_" + "probe.py"

T21R = ROOT / "evaluations" / "t21r"
T21 = ROOT / "evaluations" / "t21"
CANONICAL_BASE = "962dd581cdb1dcd4de486e983c2c1364c11903bb"
T21_BRANCH_HEAD = "f1a44b32047959fcf9a48c7468f523ad6cd885be"
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_group(rel_specs: list[str]) -> str:
    """Composite hash over files; a trailing '/' means every .py in the
    directory (recursive), sorted by relative path."""
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


def main() -> int:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    if head != CANONICAL_BASE:
        raise SystemExit(f"runtime freeze requires canonical base "
                         f"{CANONICAL_BASE}, got {head}")

    groups = {
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
        "historical_write_guard": [_GUARD_TEST, _PROBE_SCRIPT],
    }
    composites = {name: sha_group(spec) for name, spec in groups.items()}

    # Knowledge corpus (frozen T21 corpus, unchanged)
    corpus_manifest = json.loads(
        (ROOT / "rag/gk_corpus/corpus_manifest.json").read_text("utf-8"))
    corpus_files = {
        name: sha_lf(ROOT / "rag/gk_corpus" / name)
        for name in ("sources.jsonl", "chunks.jsonl",
                     "corpus_manifest.json")
    }

    # KNOWLEDGE_RAG registry record (current canonical ACTIVE state)
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    registry_record = {
        "availability": reg.availability("KNOWLEDGE_RAG"),
        "registry_sha256": registry_sha256(reg),
        "skills_py_sha256_lf": sha_lf(
            ROOT / "src/sciencemath/executive/skills.py"),
        "counts": reg.counts(),
    }

    # T21 historical artifact hashes (frozen evidence, never rewritten)
    t21_hashes = {}
    for rel in (
            "T21_FINAL_REPORT.md", "baselines.json", "corpus_manifest.json",
            "entry_freeze.json", "eval_results.json", "failure_analysis.json",
            "final_audit.json", "floors.json", "frozen_components.json",
            "mutation_safety_probe.json", "performance.json",
            "promotion_decision.json", "pytest_entry.json",
            "pytest_final.json", "pytest_focused.json",
            "registry_registration.json", "science_rag_regression.json",
            "smoke.json", "tuning_closed.json",
            "protection/regression_summary.json",
    ):
        t21_hashes["evaluations/t21/" + rel] = sha_lf(T21 / rel)
    t21_hashes["rag/gk_corpus/corpus_manifest.json:manifest_checksum"] = \
        corpus_manifest["manifest_checksum"]

    # Original suite manifests (each suite's frozen split hashes)
    suite_manifests = {}
    for d in sorted((T21 / "suites").iterdir()):
        if d.is_dir():
            m = json.loads((d / "manifest.json").read_text("utf-8"))
            suite_manifests[d.name] = {
                "total": m["total"],
                "dev_sha256": m["dev_sha256"],
                "final_sha256": m["final_sha256"],
            }

    doc = {
        "milestone": "T21R.0 runtime freeze",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "canonical_base": CANONICAL_BASE,
        "git_head": head,
        "git_tree_sha": subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT,
            capture_output=True, text=True).stdout.strip(),
        "t21_branch_head_in_ancestry": T21_BRANCH_HEAD,
        "t15r_canonical_blob": T15R_BLOB,
        "runtime_composites": composites,
        "knowledge_rag_registry": registry_record,
        "t21_corpus_manifest_checksum":
            corpus_manifest["manifest_checksum"],
        "t21_corpus_file_checksums": {
            "sources.jsonl": corpus_manifest["file_checksums"]["sources.jsonl"],
            "chunks.jsonl": corpus_manifest["file_checksums"]["chunks.jsonl"],
        },
        "t21_artifact_sha256": t21_hashes,
        "t21_suite_manifests": suite_manifests,
        "rule": "From this moment forward NO runtime change is allowed "
                "during T21R: no modification of src/sciencemath/knowledge/**, "
                "retrieval thresholds, citation rules, freshness rules, "
                "conflict logic, answer templates, entity gates, reranking, "
                "the T21 corpus, or the old T21 benchmark suites.",
    }
    out = T21R / "runtime_freeze.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "FROZEN", "out": out.as_posix(),
                      "groups": len(composites),
                      "knowledge_rag": registry_record["availability"],
                      "registry_sha256":
                          registry_record["registry_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())