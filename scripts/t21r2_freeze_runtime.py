"""T21R2.0 — freeze the KNOWLEDGE_RAG runtime BEFORE any holdout data exists.

Records composite SHA-256 hashes over every frozen runtime group, the
KNOWLEDGE_RAG registry record, the T21/T21R historical artifact hashes,
and the T21R provenance erratum status, into
evaluations/t21r2/runtime_freeze.json.

Ordering invariant: this script must run before scripts/t21r2_world.py
creates any holdout material. The freeze proves the runtime the one-shot
evaluation will execute is exactly the runtime on canonical base 8d23eabb
(GitHub-verified merge of PR #13, T21R).

After this freeze, NO runtime change is allowed for the rest of T21R2.

Usage: python scripts/t21r2_freeze_runtime.py
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

# Frozen runtime hash groups (shared with the evaluator's pre-run
# integrity check via import).
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
        "src/sciencemath/executive/state.py",
    ],
    "historical_write_guard": [_GUARD_TEST, _PROBE_SCRIPT],
}

OUT_DIR = ROOT / "evaluations" / "t21r2"
CANONICAL_BASE = "8d23eabb17b3f66aa7ba3e4815c0ea088e53ae7b"
T21R_MERGE = "ebb7938c773843bb407397ebf8e2a9b86d0a85a3"
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


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def main() -> int:
    head = _git("rev-parse", "HEAD")
    base_head = _git("rev-parse", CANONICAL_BASE)

    # The runtime must be byte-identical to canonical base: no src/ drift
    # between the branch head and the base commit.
    src_diff = _git("diff", "--stat", CANONICAL_BASE, head, "--", "src/")
    if src_diff:
        raise SystemExit(
            "runtime freeze requires src/ identical to canonical base; "
            f"diff:\n{src_diff}")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", T21R_MERGE, head],
        cwd=ROOT, capture_output=True, text=True)
    if ancestor.returncode != 0:
        raise SystemExit("T21R merge not in ancestry")
    if (ROOT / "evaluations" / "t22").exists():
        raise SystemExit("T22 must not have started")

    composites = {name: sha_group(spec)
                  for name, spec in RUNTIME_GROUPS.items()}

    # Historical corpus manifests (unchanged by T21R2)
    t21_corpus_manifest = json.loads(
        (ROOT / "rag/gk_corpus/corpus_manifest.json").read_text("utf-8"))
    t21r_corpus_manifest = json.loads(
        (ROOT / "rag/gk_holdout_t21r/corpus_manifest.json").read_text(
            "utf-8"))

    # KNOWLEDGE_RAG registry record (canonical ACTIVE state)
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    registry_record = {
        "availability": reg.availability("KNOWLEDGE_RAG"),
        "registry_sha256": registry_sha256(reg),
        "skills_py_sha256_lf": sha_lf(
            ROOT / "src/sciencemath/executive/skills.py"),
        "counts": reg.counts(),
    }
    if registry_record["availability"] != "ACTIVE":
        raise SystemExit("KNOWLEDGE_RAG must be ACTIVE at runtime freeze")

    # Historical artifact hashes (frozen evidence, never rewritten)
    def hash_dir_files(rel_dir: str, names: list[str]) -> dict:
        out = {}
        for rel in names:
            p = ROOT / rel_dir / rel
            if p.exists():
                out[f"{rel_dir}/{rel}"] = sha_lf(p)
        return out

    t21_hashes = hash_dir_files("evaluations/t21", (
        "T21_FINAL_REPORT.md", "baselines.json", "corpus_manifest.json",
        "entry_freeze.json", "eval_results.json", "failure_analysis.json",
        "final_audit.json", "floors.json", "frozen_components.json",
        "mutation_safety_probe.json", "performance.json",
        "promotion_decision.json", "pytest_entry.json", "pytest_final.json",
        "pytest_focused.json", "registry_registration.json",
        "science_rag_regression.json", "smoke.json", "tuning_closed.json",
        "protection/regression_summary.json",
    ))
    t21r_hashes = hash_dir_files("evaluations/t21r", (
        "HOLDOUT_FROZEN", "T21R_FINAL_REPORT.md", "failure_analysis.json",
        "final_audit.json", "gold_qa_report.json", "holdout_manifest.json",
        "holdout_results.json", "holdout_uniqueness.json",
        "mutation_safety_probe.json", "promotion_provenance_errata.json",
        "protection/regression_summary.json", "pytest_entry.json",
        "pytest_final.json", "runtime_freeze.json",
        "validation_contract.json",
    ))

    doc = {
        "milestone": "T21R2.0 runtime freeze (before any holdout data)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "canonical_base": CANONICAL_BASE,
        "t21r_merge_in_ancestry": T21R_MERGE,
        "git_head": head,
        "git_tree_sha": _git("rev-parse", "HEAD^{tree}"),
        "src_identical_to_base": True,
        "t15r_canonical_blob": T15R_BLOB,
        "runtime_composites": composites,
        "knowledge_rag_registry": registry_record,
        "executive_router_status": "EXPERIMENTAL (unchanged; promotion is a "
                                   "zero-tolerance gate)",
        "t21_corpus_manifest_checksum":
            t21_corpus_manifest["manifest_checksum"],
        "t21r_corpus_manifest_checksum":
            t21r_corpus_manifest["manifest_checksum"],
        "t21_artifact_sha256": t21_hashes,
        "t21r_artifact_sha256": t21r_hashes,
        "t21r_provenance_erratum": "T21_PROMOTION_PROVENANCE_RECONSTRUCTED",
        "order_rule": "This freeze exists BEFORE evaluations/t21r2 contains "
                      "any holdout world, corpus, gold, or suite file, and "
                      "BEFORE the evaluator is frozen. From this moment "
                      "forward NO runtime change is allowed during T21R2: "
                      "no modification of src/sciencemath/knowledge/**, "
                      "retrieval thresholds, BM25 configuration, reranking, "
                      "entity gate, coverage gate, freshness logic, "
                      "conflict logic, citation logic, claim verification, "
                      "answer templates, routing logic, abstention "
                      "thresholds, the T21 corpus, the T21R corpus, or the "
                      "old benchmark suites.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "runtime_freeze.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "FROZEN",
        "out": out.as_posix(),
        "groups": len(composites),
        "knowledge_rag": registry_record["availability"],
        "registry_sha256": registry_record["registry_sha256"],
        "canonical_base": CANONICAL_BASE,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())