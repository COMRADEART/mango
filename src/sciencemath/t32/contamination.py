"""T32 Phase 3: contamination gate for the fresh pool.

Directive rule: no T31 evaluation question (or near-duplicate of one) may
enter T32 training. The pool build removed DIRECT duplicates by fingerprint;
this gate adds the NEAR check with the same parameters the frozen T30 corpus
build used (4-gram shingle Jaccard, threshold 0.90) against every T31
evaluation item question of all five benchmarks.

Contaminated pool records are REMOVED and the remediation recorded, exactly
like the T30 build's contamination_gate(). The cleaned pool
(fresh_pool_clean.jsonl) is re-verified with a direct re-check before the
mixture stage may touch it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")

from common import REPO_ROOT  # noqa: E402

from sciencemath.datasets.leakage import (  # noqa: E402
    find_direct_leakage,
    find_near_leakage,
)
from sciencemath.utils.io_utils import read_jsonl, write_jsonl  # noqa: E402

ROOT = REPO_ROOT
POOLS = ROOT / "training/t32/pools"
BENCHMARKS = ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq")


def main() -> int:
    pool = read_jsonl(POOLS / "fresh_pool.jsonl")
    print("pool records:", len(pool), flush=True)

    # T31 eval questions: base-arm scored rows (both arms share the identical
    # frozen membership verified in T31).
    eval_sets: dict[str, list[dict]] = {}
    for b in BENCHMARKS:
        rows = read_jsonl(ROOT / f"evaluations/t31/scored/base/{b}.jsonl")
        eval_sets[f"t31_{b}"] = [{"id": r["item_id"], "question": r["question"],
                                  "source": f"t31-eval/{b}"} for r in rows]
        print(f"t31_{b}: {len(rows)} eval questions", flush=True)

    direct = find_direct_leakage(pool, eval_sets)
    near = find_near_leakage(pool, eval_sets, threshold=0.90)
    leaked_ids = {p.train_id for p in direct.pairs} | {p.train_id for p in near.pairs}

    sim_by_id = {}
    for p in near.pairs:
        sim_by_id.setdefault(p.train_id, p.similarity)
    removed = [{"id": r["id"], "source": r.get("source"),
                "source_id": r.get("source_id"),
                "kind": ("direct" if r["id"] in {p.train_id for p in direct.pairs}
                         else "near"),
                "similarity": sim_by_id.get(r["id"], 1.0)}
               for r in pool if r["id"] in leaked_ids]
    by_source: dict[str, dict] = {}
    for rm in removed:
        by_source.setdefault(rm["source"], {}).setdefault(rm["kind"], 0)
        by_source[rm["source"]][rm["kind"]] += 1

    kept = [r for r in pool if r["id"] not in leaked_ids]

    # re-verify clean after remediation
    recheck = find_direct_leakage(kept, eval_sets)
    if recheck.has_direct:
        raise SystemExit("contamination gate FAILED: direct leakage remains "
                         "after remediation")

    out = POOLS / "fresh_pool_clean.jsonl"
    write_jsonl(out, kept)
    body = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                   for r in kept)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

    report = {
        "artifact": "T32_CONTAMINATION_REPORT",
        "schema_version": "t32-mixture-v1",
        "gate": ("T32 fresh pool vs all T31 evaluation item questions "
                 "(base-arm scored rows; both arms share frozen membership)"),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "stage_order": [
            "1. pools.py: direct fingerprint exclusion vs T30 corpus "
            "(train+validation) and T31 eval questions",
            "2. THIS GATE: near-leakage (4-gram shingle Jaccard >= 0.90, "
            "the T30-build parameters) vs T31 eval questions; direct re-check",
        ],
        "eval_questions_total": sum(len(v) for v in eval_sets.values()),
        "candidates_checked": len(pool),
        "direct_leakage_found": len(direct.direct),
        "near_leakage_found": len(near.near),
        "records_removed": len(removed),
        "removals_by_source_kind": by_source,
        "removed_records": removed,
        "kept": len(kept),
        "remediation": ("contaminated records (direct and near >= 0.90 Jaccard) "
                        "REMOVED from the T32 pool before any mixture use; "
                        "full removal list in fresh_pool_removed.jsonl"),
        "kept_sha256": digest,
        "passed_after_remediation": True,
    }
    (POOLS / "contamination_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    (POOLS / "fresh_pool_removed.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in removed),
        encoding="utf-8", newline="\n")

    print(f"direct {len(direct.direct)} | near {len(near.near)} | "
          f"removed {len(removed)} | kept {len(kept)} | sha {digest[:12]}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())