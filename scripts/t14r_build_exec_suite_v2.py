"""T14R.21 — corrected executive suite v2 (deduplication only).

The frozen mango-executive-router-eval-v1 contains 20 rows whose gold is
an accidental duplicate: the T14 suite builder records every no-tool
question twice (once no_tool_tasks/GENERAL, once numeric_scicomp/SCICOMP
with gold_necessity COMPUTE_REQUIRED). Each duplicate row contradicts
its twin's gold for the identical question text.

v2 removes ONLY those 20 duplicate rows — the no-tool gold row for each
question already exists in the suite (development or final split). No
gold is rewritten, no question is edited, no row is added; thresholds
are unchanged. The 3 SCIENCE_RAG and 1 MATH_T4 genuine AVAILABLE_TOOL_
MISSED rows are kept so the corrected suite still measures the router's
actual miss rate.

Writes evaluations/t14r/suites/executive-router/v2/ with checksum +
manifest documenting the correction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evaluations/t14/suites/executive-router/v1/questions.jsonl"
OUT = ROOT / "evaluations/t14r/suites/executive-router/v2"


def main() -> int:
    items = [json.loads(l) for l in SRC.read_text(encoding="utf-8")
             .splitlines() if l.strip()]
    by_q: dict[str, list[dict]] = {}
    for it in items:
        by_q.setdefault(it["question"], []).append(it)

    drop: set[str] = set()
    for q, twins in by_q.items():
        if len(twins) < 2:
            continue
        for it in twins:
            if (it["primary_skill"] in ("MATH_T4", "SCICOMP", "SCIENCE_RAG")
                    and any(t["primary_skill"] in ("GENERAL", "NO_TOOL")
                            for t in twins)):
                drop.add(it["eval_id"])

    kept = [it for it in items if it["eval_id"] not in drop]
    OUT.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(it, ensure_ascii=False) for it in kept) + "\n"
    (OUT / "questions.jsonl").write_text(text, encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (OUT / "checksum.txt").write_text(sha + "\n", encoding="utf-8")

    manifest = {
        "suite": "mango-executive-router-eval-v2",
        "corrected_from": "mango-executive-router-eval-v1",
        "correction": "remove 20 duplicate-gold rows (no-tool questions "
                      "recorded twice with contradictory SCICOMP gold by "
                      "the T14 suite builder loop); no other change",
        "rows_v1": len(items),
        "rows_v2": len(kept),
        "removed": sorted(drop),
        "removed_count": len(drop),
        "thresholds": {"top2_route_accuracy": 0.92,
                       "tool_required_recall": 0.90},
        "note": ("thresholds unchanged; the genuine AVAILABLE_TOOL_MISSED "
                 "rows (3 SCIENCE_RAG factual + 1 MATH_T4 arithmetic) are "
                 "kept so the corrected suite still measures the router's "
                 "real miss rate"),
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in
                      ("rows_v1", "rows_v2", "removed_count")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())