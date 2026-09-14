"""T21R.7 — freeze the fresh holdout (HOLDOUT_FROZEN).

Records the complete identity of the frozen holdout material: the corpus,
all 8 suites, every gold row, the preregistered contract, the runtime
freeze, the pre-freeze QA reports, and the evaluator source that will run
the one-shot evaluation. After this file exists, the one_shot_rule of
validation_contract.json applies: no runtime change, no gold change, no
query change, no floor lowering, no dropping failing cases, no
scoring-semantics change, no special-case rules.

Output: evaluations/t21r/holdout_manifest.json
        evaluations/t21r/HOLDOUT_FROZEN
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r"

SUITES = [
    "mango-t21r-retrieval-holdout-v1",
    "mango-t21r-singlehop-holdout-v1",
    "mango-t21r-multihop-holdout-v1",
    "mango-t21r-crossdomain-holdout-v1",
    "mango-t21r-citation-claim-holdout-v1",
    "mango-t21r-conflict-abstention-holdout-v1",
    "mango-t21r-temporal-holdout-v1",
    "mango-t21r-adversarial-holdout-v1",
]

CORPUS_FILES = ["sources.jsonl", "chunks.jsonl", "corpus_manifest.json"]

FREEZE_INPUTS = [
    ("runtime_freeze", OUT_DIR / "runtime_freeze.json"),
    ("validation_contract", OUT_DIR / "validation_contract.json"),
    ("gold_qa_report", OUT_DIR / "gold_qa_report.json"),
    ("holdout_uniqueness", OUT_DIR / "holdout_uniqueness.json"),
    ("corpus_builder", ROOT / "scripts" / "t21r_corpus.py"),
    ("fixtures", ROOT / "scripts" / "t21r_fixtures.py"),
    ("suite_builder", ROOT / "scripts" / "t21r_build_suites.py"),
    ("gold_qa_script", ROOT / "scripts" / "t21r_gold_qa.py"),
    ("uniqueness_script", ROOT / "scripts" / "t21r_uniqueness.py"),
    ("evaluator", ROOT / "scripts" / "t21r_run_eval.py"),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def sha256_lf(path: Path) -> str:
    text = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(text).hexdigest()


def main() -> int:
    evaluator = FREEZE_INPUTS[-1][1]
    if not evaluator.exists():
        raise SystemExit(
            "t21r_run_eval.py must exist before HOLDOUT_FROZEN: the "
            "evaluator source is part of the frozen identity so the "
            "one-shot evaluation uses the exact scoring code frozen here.")
    frozen_at = datetime.now(timezone.utc).isoformat()

    suites_block = {}
    total = 0
    for name in SUITES:
        holdout = OUT_DIR / "suites" / name / "holdout.jsonl"
        manifest = OUT_DIR / "suites" / name / "manifest.json"
        rows = [json.loads(line)
                for line in holdout.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        total += len(rows)
        suites_block[name] = {
            "rows": len(rows),
            "holdout_sha256": sha256_lf(holdout),
            "manifest_sha256": sha256_file(manifest),
            "frozen_manifest": json.loads(manifest.read_text(
                encoding="utf-8")),
        }

    contract = json.loads((OUT_DIR / "validation_contract.json")
                          .read_text(encoding="utf-8"))
    minimums = contract["suite_minimums"]
    below = {n: {"rows": suites_block[n]["rows"], "minimum": m}
             for n, m in minimums.items()
             if suites_block[n]["rows"] < m}
    if below:
        raise SystemExit(f"suite below contract minimum: {below}")
    if total < contract["minimum_holdout_total"]:
        raise SystemExit(f"total {total} < minimum_holdout_total "
                         f"{contract['minimum_holdout_total']}")

    manifest = {
        "milestone": "T21R.7 holdout freeze",
        "frozen_at": frozen_at,
        "holdout_total": total,
        "minimum_holdout_total": contract["minimum_holdout_total"],
        "one_shot_rule": contract["one_shot_rule"],
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
    corpus_manifest = CORPUS_DIR / "corpus_manifest.json"
    if corpus_manifest.exists():
        manifest["corpus"]["corpus_manifest.json"] = {
            "path": corpus_manifest.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(corpus_manifest),
        }
    manifest["corpus_manifest_sha256"] = sha256_file(corpus_manifest)
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
            "rule": contract["one_shot_rule"],
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(f"HOLDOUT_FROZEN total={total} manifest_sha256={manifest_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())