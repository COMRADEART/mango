"""T21R6 — freeze the blind holdout (HOLDOUT_FROZEN).

Records the complete identity of the frozen T21R6 holdout material: the
blind corpus (world, sources, chunks, manifest), all 8 gold suites, the
preregistered contract, the runtime freeze (recorded on the repaired
T21R6 runtime BEFORE holdout construction), the evaluator freeze, the
pre-freeze QA reports (static gold audit, uniqueness audit), and the
evaluator source that will run the one-shot evaluation. After this file
exists, the one_shot_rule of validation_contract.json applies: no runtime
change, no gold change, no query change, no corpus change, no floor
lowering, no dropping failing cases, no scoring-semantics change, no
special-case rules. Any post-freeze evaluator defect makes the decision
T21R6_EVALUATOR_INVALID - never a repair-and-rerun.

Output: evaluations/t21r6/holdout_manifest.json
        evaluations/t21r6/HOLDOUT_FROZEN
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r6"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r6"

SUITES = [
    "mango-t21r6-retrieval-holdout-v1",
    "mango-t21r6-singlehop-holdout-v1",
    "mango-t21r6-multihop-holdout-v1",
    "mango-t21r6-crossdomain-holdout-v1",
    "mango-t21r6-citation-claim-holdout-v1",
    "mango-t21r6-conflict-abstention-holdout-v1",
    "mango-t21r6-temporal-holdout-v1",
    "mango-t21r6-adversarial-holdout-v1",
]

# The T21R6 contract carries the one-shot rule in prose (its note) and the
# preregistered T21R6 mission rules; it is recorded verbatim here so the
# freeze marker is self-describing.
ONE_SHOT_RULE = ("Exactly ONE official exposure of the frozen T21R6 "
                 "holdout. A crash during the run still counts; no fix "
                 "and no rerun. No runtime change, no gold change, no "
                 "query change, no corpus change, no floor lowering, no "
                 "dropping failing cases, no scoring-semantics change, "
                 "no special-case rules after HOLDOUT_FROZEN.")

# All corpus data is frozen with LF-normalized hashes (the same convention
# the evaluator's pre-run integrity check applies).
CORPUS_FILES = [
    "world.jsonl", "sources.jsonl", "chunks.jsonl", "corpus_manifest.json",
]

FREEZE_INPUTS = [
    ("runtime_freeze", OUT_DIR / "runtime_freeze.json"),
    ("evaluator_freeze", OUT_DIR / "evaluator_freeze.json"),
    ("validation_contract", OUT_DIR / "validation_contract.json"),
    ("static_gold_audit", OUT_DIR / "static_gold_audit.json"),
    ("holdout_uniqueness", OUT_DIR / "holdout_uniqueness.json"),
    ("world_builder", ROOT / "scripts" / "t21r6_world.py"),
    ("corpus_renderer", ROOT / "scripts" / "t21r6_render_corpus.py"),
    ("suite_builder", ROOT / "scripts" / "t21r6_build_suites.py"),
    ("static_audit_script", ROOT / "scripts" / "t21r6_static_gold_audit.py"),
    ("uniqueness_script", ROOT / "scripts" / "t21r6_uniqueness.py"),
    ("evaluator_freeze_script", ROOT / "scripts" / "t21r6_freeze_evaluator.py"),
    ("evaluator", ROOT / "scripts" / "t21r6_run_eval.py"),
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    for label, path in FREEZE_INPUTS:
        if not path.exists():
            raise SystemExit(f"freeze input missing: {label} ({path.name})")
    for fname in CORPUS_FILES:
        if not (CORPUS_DIR / fname).exists():
            raise SystemExit(f"corpus data missing: {fname}")

    # Pre-freeze gates: the static gold audit must PASS and the uniqueness
    # audit must be UNIQUE - both against the exact reports being frozen.
    audit = json.loads((OUT_DIR / "static_gold_audit.json")
                       .read_text(encoding="utf-8"))
    if audit.get("status") != "PASS" or audit.get("failures"):
        raise SystemExit(
            "static gold audit is not PASS - holdout cannot be frozen")
    uniq = json.loads((OUT_DIR / "holdout_uniqueness.json")
                      .read_text(encoding="utf-8"))
    if uniq.get("verdict") != "UNIQUE":
        raise SystemExit("uniqueness audit is not UNIQUE - "
                         "holdout cannot be frozen")

    frozen_at = datetime.now(timezone.utc).isoformat()

    suites_block = {}
    total = 0
    for name in SUITES:
        holdout = OUT_DIR / "suites" / name / "holdout.jsonl"
        rows = [json.loads(line)
                for line in holdout.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        total += len(rows)
        suites_block[name] = {
            "rows": len(rows),
            "holdout_sha256": sha256_lf(holdout),
        }

    contract = json.loads((OUT_DIR / "validation_contract.json")
                          .read_text(encoding="utf-8"))
    minimums = contract["suite_minimums"]
    below = {n: {"rows": suites_block[n]["rows"], "minimum": m}
             for n, m in minimums.items()
             if suites_block[n]["rows"] < m}
    if below:
        raise SystemExit(f"suite below contract minimum: {below}")
    # The T21R6 contract records the total minimum in its note
    # ("total >= 3600 rows") rather than as a minimum_holdout_total key.
    TOTAL_MIN = 3600
    if total < TOTAL_MIN:
        raise SystemExit(f"total {total} < preregistered minimum "
                         f"{TOTAL_MIN}")

    manifest = {
        "milestone": "T21R6 blind holdout freeze",
        "frozen_at": frozen_at,
        "holdout_total": total,
        "preregistered_total_minimum": 3600,
        "one_shot_rule": ONE_SHOT_RULE,
        "blindness_rule": contract["note"],
        "freeze_inputs": {},
        "corpus": {},
        "suites": suites_block,
    }
    for label, path in FREEZE_INPUTS:
        manifest["freeze_inputs"][label] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
        }
    for fname in CORPUS_FILES:
        p = CORPUS_DIR / fname
        manifest["corpus"][fname] = {
            "path": p.relative_to(ROOT).as_posix(),
            "sha256": sha256_lf(p),
        }
    manifest_blob = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    manifest_sha = hashlib.sha256(
        manifest_blob.encode("utf-8").replace(b"\r\n", b"\n")).hexdigest()

    (OUT_DIR / "holdout_manifest.json").write_text(
        manifest_blob, encoding="utf-8", newline="\n")
    (OUT_DIR / "HOLDOUT_FROZEN").write_text(
        json.dumps({
            "HOLDOUT_FROZEN": True,
            "frozen_at": frozen_at,
            "holdout_manifest_sha256": manifest_sha,
            "holdout_total": total,
            "suites": {n: b["holdout_sha256"]
                       for n, b in suites_block.items()},
            "rule": ONE_SHOT_RULE,
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(f"HOLDOUT_FROZEN total={total} manifest_sha256={manifest_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())