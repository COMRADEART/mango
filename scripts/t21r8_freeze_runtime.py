"""T21R8 — freeze the production runtime identity BEFORE any blind world.

Writes ``evaluations/t21r8/runtime_freeze.json`` recording the composite
SHA-256 hashes of every preregistered runtime group (``knowledge_runtime``
recursively covers ``src/sciencemath/knowledge/`` and therefore the new R8
``evidence_paths.py`` / ``relations.py`` / ``pipeline.py`` / ``retrieval.py``
/ ``injection.py`` and every other knowledge runtime file), the knowledge
registry record, the Executive Router state, the T15R canonical blob, and
the contract/semantics/runner hashes.

The script REFUSES when any future blind material already exists, when the
``freeze_precheck.json`` gate is missing/stale/failed, when KNOWLEDGE_RAG is
not EXPERIMENTAL, when the T15R canonical blob has drifted, or when T22 has
started.  It generates NO holdout data of any kind.

Usage: python scripts/t21r8_freeze_runtime.py
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

from t21r4_freeze_runtime import RUNTIME_GROUPS, sha_group, sha_lf  # noqa: E402


T15R_PROBE = ROOT / "evaluations" / "t15r" / "mutation_safety_probe.json"

# Future blind material: NONE of this may exist when the runtime freezes.
BLIND_MATERIAL = (
    "rag/gk_holdout_t21r8",
    "evaluations/t21r8/HOLDOUT_FROZEN",
    "evaluations/t21r8/holdout_manifest.json",
    "evaluations/t21r8/evaluation_run_ledger.json",
    "evaluations/t21r8/raw_results.jsonl",
    "evaluations/t21r8/holdout_results.json",
)

T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"

# Preregistered T21R8 lineage (canonical historical base .. preregistration
# integrity closure); every commit must be an ancestor of the frozen HEAD.
LINEAGE = {
    "canonical_historical_base": "bffe86b67107ba2a097aa3030acc17e687d84d25",
    "base_remediation": "4242e1bd7bb74c9f3f6d52f70fb04788e2e6d481",
    "forensic": "2626f4e9ec7a83cd40ad7cd1b80bdc34296748dd",
    "repair": "fc633540e84a8c11d287a13ea878333f1eba1ed8",
    "qualification": "ee2270246fd374143b90d57051976bf63c3e8d86",
    "preregistration": "f804a5706025a173e40879be5629e8a74dc585ec",
    "preregistration_integrity":
        "40696a066e091d74f5d443837de4b0c9d4c2de3c",
}


def _default_git(args: list[str], root: Path) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse_blind_material(root: Path) -> None:
    """Refuse if any future T21R8 blind material already exists."""
    for rel in BLIND_MATERIAL:
        if (root / rel).exists():
            raise SystemExit(
                "T21R8_FREEZE_ORDER_VIOLATION: blind material already "
                f"exists ({rel}); the runtime must freeze BEFORE any blind "
                "world construction")


def _load_precheck(root: Path, head: str) -> dict:
    path = root / "evaluations" / "t21r8" / "freeze_precheck.json"
    if not path.exists():
        raise SystemExit(
            "T21R8_FREEZE_ENTRY_BLOCKED: freeze_precheck.json is missing; "
            "run the clean-tip full pytest gate first")
    precheck = json.loads(path.read_text(encoding="utf-8"))
    if precheck.get("status") != "PASS":
        raise SystemExit("T21R8_FREEZE_ENTRY_BLOCKED: precheck not PASS")
    if precheck.get("tested_head") != head:
        raise SystemExit(
            f"T21R8_FREEZE_ENTRY_BLOCKED: precheck tested_head "
            f"{precheck.get('tested_head')} differs from current HEAD {head}")
    if precheck.get("failed") != 0 or precheck.get("errors") != 0 \
            or precheck.get("exit_code") != 0:
        raise SystemExit(
            "T21R8_FREEZE_ENTRY_BLOCKED: precheck test run is not clean")
    if not precheck.get("blind_artifacts_absent"):
        raise SystemExit(
            "T21R8_FREEZE_ENTRY_BLOCKED: precheck did not confirm blind "
            "artifact absence")
    states = precheck.get("states") or {}
    if states.get("KNOWLEDGE_RAG") != "EXPERIMENTAL" or \
            states.get("Executive_Router") != "EXPERIMENTAL":
        raise SystemExit(
            "T21R8_FREEZE_ENTRY_BLOCKED: precheck state is not "
            "EXPERIMENTAL/EXPERIMENTAL")
    if states.get("T21") != "OPEN" or states.get("T22") != "BLOCKED":
        raise SystemExit(
            "T21R8_FREEZE_ENTRY_BLOCKED: precheck T21/T22 state drifted")
    return precheck


def _registry_record(root: Path) -> dict:
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    registry = SkillRegistry()
    return {
        "availability": registry.availability("KNOWLEDGE_RAG"),
        "registry_sha256": registry_sha256(registry),
        "skills_py_sha256_lf": sha_lf(
            root / "src" / "sciencemath" / "executive" / "skills.py"),
        "counts": registry.counts(),
    }


def main(root: Path = ROOT, git_fn=None) -> int:
    out_dir = root / "evaluations" / "t21r8"
    git = git_fn or _default_git
    refuse_blind_material(root)
    if (root / "evaluations" / "t22").exists():
        raise SystemExit("T21R8_FREEZE_ORDER_VIOLATION: T22 has started")
    if (out_dir / "runtime_freeze.json").exists():
        raise SystemExit(
            "T21R8_FREEZE_ORDER_VIOLATION: runtime_freeze.json already "
            "exists; the runtime freezes exactly once")

    head = git(["rev-parse", "HEAD"], root)
    precheck = _load_precheck(root, head)

    ancestry = set(git(["log", "--pretty=%H", "-200"], root).splitlines())
    ancestry.add(head)
    for label, commit in LINEAGE.items():
        if commit not in ancestry:
            raise SystemExit(
                f"T21R8_FREEZE_ENTRY_BLOCKED: {label} commit {commit} is not "
                "in ancestry")

    registry_record = _registry_record(root)
    if registry_record["availability"] != "EXPERIMENTAL":
        raise SystemExit(
            "KNOWLEDGE_RAG must remain EXPERIMENTAL at T21R8 runtime freeze")

    probe = root / "evaluations" / "t15r" / "mutation_safety_probe.json"
    blob = git(["hash-object", str(probe)], root)
    if blob != T15R_BLOB:
        raise SystemExit(f"T15R canonical blob drifted: {blob}")

    composites = {name: sha_group(spec) for name, spec in
                  RUNTIME_GROUPS.items()}
    document = {
        "milestone": "T21R8 runtime freeze (before blind-world construction)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "lineage": LINEAGE,
        "git_head": head,
        "git_tree_sha": git(["rev-parse", "HEAD^{tree}"], root),
        "freeze_precheck_sha256": _sha256(
            root / "evaluations" / "t21r8" / "freeze_precheck.json"),
        "t15r_canonical_blob": T15R_BLOB,
        "runtime_composites": composites,
        "knowledge_rag_registry": registry_record,
        "executive_router_status": "EXPERIMENTAL (unchanged)",
        "executive_router_sha256": composites["executive_router"],
        "validation_contract_sha256": _sha256(
            root / "evaluations" / "t21r8" / "validation_contract.json"),
        "holdout_construction_contract_sha256": _sha256(
            root / "evaluations" / "t21r8"
            / "holdout_construction_contract.json"),
        "scoring_semantics_file_sha256": _sha256(
            root / "evaluations" / "t21r8" / "scoring_semantics.json"),
        "official_runner_sha256": _sha256(
            root / "scripts" / "t21r8_official_eval.py"),
        "promotion_policy": (
            "KNOWLEDGE_RAG remains EXPERIMENTAL until the one-shot T21R8 "
            "blind holdout passes every preregistered floor."),
    }
    out = out_dir / "runtime_freeze.json"
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "RUNTIME_FROZEN",
        "path": str(out),
        "git_head": head,
        "composites": len(composites),
        "knowledge_rag": registry_record["availability"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())