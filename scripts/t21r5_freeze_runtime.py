"""T21R5 runtime freeze — recorded BEFORE holdout construction.

Freezes the repaired T21R5 knowledge runtime exactly as T21R4 froze its
repaired runtime: every runtime group composite is recorded at the
preregistered constants, KNOWLEDGE_RAG stays EXPERIMENTAL pending the
promotion decision, the Executive Router is untouched, and the T15R
canonical blob is verified. The T21R5 reliability repair commit and the
post-T21R4 main merge must both be in ancestry.

The T21R5 protection-battery registration in the historical write guard
was applied BEFORE this freeze (preregistered), so the
historical_write_guard group is recorded with the registration in place
- no re-record is needed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from t21r4_freeze_runtime import (  # noqa: E402
    RUNTIME_GROUPS,
    _git,
    sha_group,
    sha_lf,
)

OUT_DIR = ROOT / "evaluations" / "t21r5"
T21R4_MERGE_SHA = "6174ebde0972a3f199b231a160bdb0875eb9bb7a"
T21R5_REPAIR_COMMIT = "d8076beb1012f83723e1ccd91967cee2b5af2ab8"
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"


def main() -> int:
    head = _git("rev-parse", "HEAD")
    log = _git("log", "--pretty=%H", "-50").splitlines()
    if T21R4_MERGE_SHA not in log and head != T21R4_MERGE_SHA:
        raise SystemExit("T21R4 merge commit 6174ebd not in ancestry")
    if T21R5_REPAIR_COMMIT not in log and head != T21R5_REPAIR_COMMIT:
        raise SystemExit(
            f"repair commit {T21R5_REPAIR_COMMIT} not in ancestry")

    if (ROOT / "evaluations" / "t22").exists():
        raise SystemExit("T22 must not have started")
    if (ROOT / "rag" / "gk_holdout_t21r5" / "world.jsonl").exists():
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
            "KNOWLEDGE_RAG must be EXPERIMENTAL at T21R5 runtime freeze")

    t15r = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    blob = _git("hash-object", str(t15r))
    if blob != T15R_BLOB:
        raise SystemExit(f"T15R blob drifted: {blob}")

    doc = {
        "milestone": "T21R5 runtime freeze (repaired runtime, before holdout)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "t21r4_merge_sha": T21R4_MERGE_SHA,
        "repair_commit": T21R5_REPAIR_COMMIT,
        "git_head": head,
        "git_tree_sha": _git("rev-parse", "HEAD^{tree}"),
        "t15r_canonical_blob": T15R_BLOB,
        "runtime_composites": composites,
        "knowledge_rag_registry": registry_record,
        "executive_router_status": "EXPERIMENTAL (unchanged)",
        "promotion_policy": ("KNOWLEDGE_RAG may move to ACTIVE only after "
                             "the one-shot T21R5 blind holdout passes every "
                             "preregistered floor."),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "runtime_freeze.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_DIR / 'runtime_freeze.json'}")
    print(f"knowledge_rag={registry_record['availability']} "
          f"composites={len(composites)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())