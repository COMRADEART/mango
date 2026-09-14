"""T21.56 — real local smoke: 8 representative query types end-to-end.

Runs answer_knowledge over one deterministic query per behavior class,
straight from the frozen suites, and asserts the expected routing,
statuses, citation behavior, and zero-tolerance counters. This is a live
rehearsal of the runtime contract on the real corpus (not a pytest mock).

Output: evaluations/t21/smoke.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402

SUITES_DIR = ROOT / "evaluations" / "t21" / "suites"
OUT_PATH = ROOT / "evaluations" / "t21" / "smoke.json"

# (name, suite, category to pick) — the expected status is each row's own
# frozen gold expectation, so the smoke rehearses the suite contract itself.
SMOKE_CASES = [
    ("simple_fact", "mango-general-knowledge-rag-v1", "city_country"),
    ("attribute_fact", "mango-general-knowledge-rag-v1",
     "person_field_of_study"),
    ("multihop_bridge", "mango-general-multihop-v1", "two_hop_bridge"),
    ("temporal_current_web_route", "mango-general-temporal-boundary-v1",
     "explicit_current"),
    ("temporal_as_of_static", "mango-general-temporal-boundary-v1",
     "historical_as_of"),
    ("absent_entity_abstain", "mango-general-abstention-v1",
     "nonexistent_person"),
    ("conflicting_evidence", "mango-general-abstention-v1",
     "unresolved_conflict"),
    ("injection_containment", "mango-general-adversarial-v1",
     "override_containment"),
]


def pick(suite: str, category: str) -> dict:
    for line in (SUITES_DIR / suite / "final.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["category"] == category:
            return row
    raise SystemExit(f"no row for {suite}/{category}")


def main() -> int:
    corpus = load_corpus()
    results = []
    ok_all = True
    for name, suite, category in SMOKE_CASES:
        row = pick(suite, category)
        result = answer_knowledge(row["request"]["query"], corpus)
        gold = row["gold"]
        expect_status = gold["expect_status"]
        zero_hits = [k for k, v in result.zero_tolerance.items() if v]
        ok = result.status == expect_status and not zero_hits
        if expect_status == "ANSWER":
            ok = ok and bool(result.answer.strip())
            ok = ok and all(
                s in result.answer.lower()
                for s in gold.get("expect_answer_contains", []))
            ok = ok and bool(result.citations) \
                and result.citation_report.get("ok", False)
        entry = {
            "case": name,
            "suite": suite,
            "category": category,
            "query": row["request"]["query"],
            "expected_status": expect_status,
            "status": result.status,
            "answer_head": result.answer[:160],
            "n_citations": len(result.citations),
            "citation_report_ok": bool(result.citation_report.get("ok")),
            "zero_tolerance_hits": zero_hits,
            "pass": ok,
        }
        results.append(entry)
        ok_all = ok_all and ok
        print(f"[{name}] status={result.status} pass={ok}")

    out = {
        "milestone": "T21.56 real local smoke",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "corpus_manifest_checksum":
            corpus.manifest.get("manifest_checksum"),
        "n_cases": len(results),
        "n_pass": sum(1 for r in results if r["pass"]),
        "cases": results,
        "status": "ALL_PASS" if ok_all else "FAIL",
    }
    OUT_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.as_posix()} status={out['status']}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())