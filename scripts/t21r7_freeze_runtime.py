"""Freeze the repaired T21R7 runtime before blind-world construction."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from t21r4_freeze_runtime import RUNTIME_GROUPS, _git, sha_group, sha_lf  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r7"
CANONICAL_BASE = "57f4188c736b7ffd59227deb808ecd29b02fcc33"
REPAIR_COMMIT = "ba3b1ce4f80886fd0f7d5cde4946a82109472f9c"
PREREG_COMMIT = "554f000ad511dedc5b7752887558ab24b1fa0d27"
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"


def _load(name: str) -> dict:
    return json.loads((OUT_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if (ROOT / "rag" / "gk_holdout_t21r7").exists() or \
            (OUT_DIR / "HOLDOUT_FROZEN").exists():
        raise SystemExit("runtime must freeze before any T21R7 holdout data")
    head = _git("rev-parse", "HEAD")
    ancestry = set(_git("log", "--pretty=%H", "-100").splitlines()) | {head}
    for label, commit in (
        ("canonical base", CANONICAL_BASE),
        ("repair commit", REPAIR_COMMIT),
        ("construction preregistration commit", PREREG_COMMIT),
    ):
        if commit not in ancestry:
            raise SystemExit(f"{label} {commit} is not in ancestry")

    replay = _load("t21r6_replay_non_promotional.json")
    qualification = _load("evaluator_qualification.json")
    pytest_result = _load("pytest_pre_freeze.json")
    if not replay.get("development_gate_pass"):
        raise SystemExit("T21R6 non-promotional replay gate is not PASS")
    if replay.get("old_failures_remaining") != 0 or \
            not replay.get("floors_all_pass") or \
            not replay.get("zero_tolerance_all_zero"):
        raise SystemExit("T21R6 replay repair/floor assertions are not clean")
    if not qualification.get("qualification_passed") or \
            not qualification.get("all_paths_exercised") or \
            qualification.get("uncaught_exceptions") != 0:
        raise SystemExit("T21R7 evaluator qualification is not clean")
    if pytest_result.get("failures") != 0 or pytest_result.get("errors") != 0:
        raise SystemExit("pre-freeze pytest is not clean")

    composites = {name: sha_group(spec)
                  for name, spec in RUNTIME_GROUPS.items()}
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    registry = SkillRegistry()
    registry_record = {
        "availability": registry.availability("KNOWLEDGE_RAG"),
        "registry_sha256": registry_sha256(registry),
        "skills_py_sha256_lf": sha_lf(
            ROOT / "src" / "sciencemath" / "executive" / "skills.py"),
        "counts": registry.counts(),
    }
    if registry_record["availability"] != "EXPERIMENTAL":
        raise SystemExit("KNOWLEDGE_RAG must remain EXPERIMENTAL")
    t15r = ROOT / "evaluations" / "t15r" / "mutation_safety_probe.json"
    if _git("hash-object", str(t15r)) != T15R_BLOB:
        raise SystemExit("T15R canonical blob drifted")

    construction_contract = OUT_DIR / "holdout_construction_contract.json"
    document = {
        "milestone": "T21R7 runtime freeze (before blind holdout)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "canonical_base": CANONICAL_BASE,
        "repair_commit": REPAIR_COMMIT,
        "construction_preregistration_commit": PREREG_COMMIT,
        "git_head": head,
        "git_tree_sha": _git("rev-parse", "HEAD^{tree}"),
        "t15r_canonical_blob": T15R_BLOB,
        "holdout_construction_contract_sha256": _sha256(
            construction_contract),
        "development_gates": {
            "t21r6_replay_rows": replay["rows_executed"],
            "t21r6_old_failures_remaining": 0,
            "all_32_floors_pass": True,
            "evaluator_qualification_cases": qualification["n_cases"],
            "pytest_tests": pytest_result["tests"],
            "pytest_failures": 0,
            "pytest_errors": 0,
        },
        "runtime_composites": composites,
        "knowledge_rag_registry": registry_record,
        "executive_router_status": "EXPERIMENTAL (unchanged)",
        "promotion_policy": (
            "KNOWLEDGE_RAG remains EXPERIMENTAL until the one-shot T21R7 "
            "blind holdout passes all unchanged promotion floors."
        ),
    }
    path = OUT_DIR / "runtime_freeze.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"wrote {path} at {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
