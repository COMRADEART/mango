"""Print failing dev rows for a T21 suite (diagnostic aid)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402

SUITES = ROOT / "evaluations" / "t21" / "suites"


def main() -> None:
    suite = sys.argv[1]
    split = sys.argv[2] if len(sys.argv) > 2 else "dev"
    corpus = load_corpus()
    path = SUITES / suite / f"{split}.jsonl"
    failures = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        gold = row["gold"]
        result = answer_knowledge(row["request"]["query"], corpus)
        lowered = result.answer.lower()
        ok = result.status == gold["expect_status"]
        if ok and gold["expect_status"] == "ANSWER":
            ok = all(s in lowered for s in
                     gold.get("expect_answer_contains", []))
            if ok and gold.get("require_citations"):
                ok = bool(result.citations) and \
                    result.citation_report.get("ok")
        if not ok:
            failures += 1
            print(f"[{row['case_id']}] {row['category']}")
            print(f"  query: {row['request']['query']}")
            print(f"  expected: {gold['expect_status']} "
                  f"contains={gold.get('expect_answer_contains')}")
            print(f"  got: {result.status} answer={result.answer[:150]!r}")
            print(f"  trace: {result.decision_trace}")
            nz = [k for k, v in result.zero_tolerance.items() if v]
            if nz:
                print(f"  ZERO-TOLERANCE: {nz}")
    print(f"{suite}/{split}: {failures} failures")


if __name__ == "__main__":
    main()