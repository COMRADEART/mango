"""T21R14 synthetic end-to-end rehearsal (disposable fixtures, stub candidate
outputs) through the REAL official evaluation pipeline: evaluator, scorer,
domain aggregation, 32-floor calculation, and the gold/taxonomy preflight.
No real R14 material is created; the replica is discarded."""
from __future__ import annotations
import json, shutil, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import t21r14_run_eval as run_eval14
import t21r14_official_eval as official14
OUT14 = ROOT / "evaluations" / "t21r14"
SUITES = run_eval14.SUITES

def stub_raw(row, suite):
    expected = (row.get("gold") or {}).get("expect_status") or "ANSWER"
    raw = {
        "status": expected, "expected_status": expected, "rank": 1,
        "correct": True, "citation_report_ok": True, "n_citations": 1,
        "citation_verdicts": ["OK"], "contains_ok": True,
        "citations_ok": True, "counters": {}, "counters_nonzero": [],
        "required_sources_ok": True, "required_domains":
            (row.get("gold") or {}).get("required_domains") or [],
        "required_domains_ok": True, "cited_source_domains": [],
        "coverage": 1.0, "n_evidence_items": 2,
        "evidence_chunk_ids": (row.get("gold") or {}).get("required_chunk_ids") or [],
        "conflicts_surfaced": expected == "CONFLICTING_EVIDENCE",
        "temporal_action": expected, "snapshot_date": None,
        "decision_trace": [], "query_injection": False,
        "status_match": True, "claim_counts": {"SUPPORTED": 1}, "claims_supported": True, "required_sources": [],
        "source_injection": False, "scoring_stub": True,
    }
    return raw

def build_mini_rows():
    tax = json.loads((OUT14 / "domain_taxonomy_contract.json").read_text(encoding="utf-8"))
    canonical = [d["canonical_label"] for d in tax["domains"]]
    rows = {}
    def add(suite, row):
        row.setdefault("suite_id", suite)
        rows.setdefault(suite, []).append(row)
    # retrieval: one row per canonical domain label (14)
    for i, dom in enumerate(canonical):
        add(SUITES[0], {"case_id": f"pre14q-ret-{i:03d}", "mode": "retrieval",
                        "category": dom,
                        "request": {"query": f"pre14q synthetic retrieval probe {i}"},
                        "gold": {"expect_status": "ANSWER", "required_domains": [dom]},
                        "construction_tags": [], "construction": {}})
    # answer-family suites: every canonical domain label (14 each)
    for sidx, suite in enumerate(SUITES[1:4]):
        for i, dom in enumerate(canonical):
            add(suite, {"case_id": f"pre14q-ans-{sidx}-{i:03d}", "mode": "answer",
                        "category": dom,
                        "request": {"query": f"pre14q synthetic answer probe {sidx}-{i}"},
                        "gold": {"expect_status": "ANSWER", "required_domains": [dom], "expect_answer_contains": ["value"]},
                        "construction_tags": [], "construction": {}})
    # citation-claim suite
    for i in range(4):
        add(SUITES[4], {"case_id": f"pre14q-cit-{i:03d}", "mode": "answer", "category": "citation",
                        "request": {"query": f"pre14q synthetic citation probe {i}"},
                        "gold": {"expect_status": "ANSWER", "expect_answer_contains": ["value"], "required_sources": [f"pre14q-src-{i}"]},
                        "construction_tags": [], "construction": {}})
    # conflict-abstention suite (abstain + conflict branches)
    for i, expect in enumerate(["INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"] * 3):
        add(SUITES[5], {"case_id": f"pre14q-abs-{i:03d}", "mode": "answer", "category": "conflict",
                        "request": {"query": f"pre14q synthetic conflict probe {i}"},
                        "gold": {"expect_status": expect},
                        "construction_tags": [], "construction": {}})
    # temporal suite (explicit current + stale snapshot + historical as-of + static web)
    for i, cat in enumerate(["explicit_current", "latest phrasing", "snapshot_answer", "historical_as_of", "snapshot_too_old"] * 2):
        add(SUITES[6], {"case_id": f"pre14q-tmp-{i:03d}", "mode": "answer", "category": cat,
                        "request": {"query": f"pre14q synthetic temporal probe {i}"},
                        "gold": {"expect_status": "ANSWER"},
                        "construction_tags": [], "construction": {}})
    # adversarial suite (security categories)
    for i, tag in enumerate(["prompt_injection", "citation_id_spoof", "source_authority_escalation", "memory_backfill", "retrieved_code_execution", "unauthorized_network", "unauthorized_memory_write"] * 2):
        add(SUITES[7], {"case_id": f"pre14q-adv-{i:03d}", "mode": "answer", "category": tag,
                        "request": {"query": f"pre14q synthetic adversarial probe {i}"},
                        "gold": {"expect_status": "ANSWER"},
                        "construction_tags": [tag], "construction": {}})
    return rows, canonical

def main() -> int:
    stages = {}
    validation_contract = json.loads((OUT14 / "validation_contract.json").read_text(encoding="utf-8"))
    rows, canonical = build_mini_rows()
    assert list(rows) == SUITES, list(rows)
    total = sum(len(v) for v in rows.values())
    stages["synthetic_rows"] = {s: len(rows[s]) for s in SUITES}
    stages["synthetic_rows_total"] = total
    # stub the candidate; exercise the REAL evaluator/scorer/floor path
    orig_answer = run_eval14._qualified.run_answer_row
    orig_retrieval = run_eval14._qualified.run_retrieval_row
    run_eval14._qualified.run_answer_row = lambda row, corpus: (stub_raw(row, None), None)
    run_eval14._qualified.run_retrieval_row = lambda row, corpus: stub_raw(row, None)
    replica = Path(tempfile.mkdtemp(prefix="t21r14-synth-"))
    try:
        raw_path = replica / "mini_raw_results.jsonl"
        # corpus is not touched by the stubs, but evaluate() signature needs one
        class _NullCorpus:
            sources = []
            chunks = []
        result = run_eval14.evaluate(_NullCorpus(), rows, raw_path, validation_contract)
        stages["official_evaluator"] = "PASS"
        stages["rows_through_evaluator"] = result["runtime_rows_executed"]
        stages["official_scorer"] = "PASS" if result.get("per_suite") else "FAIL"
        per_suite = result.get("per_suite") or {}
        stages["retrieval_metrics_keys"] = sorted((per_suite.get(SUITES[0]) or {}).get("metrics", {}))
        stages["domain_macro"] = "PASS" if result.get("metrics") else "FAIL"
        stages["floor_calculations"] = len(result["floor_comparisons"])
        stages["floor_names"] = [c["floor"] for c in result["floor_comparisons"]]
        stages["zero_tolerance_totals"] = result["zero_tolerance_totals"]
        # every canonical domain reached the scorer
        seen = set()
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.update(json.loads(line).get("required_domains") or [])
        stages["canonical_domains_reached_scorer"] = len(seen & set(canonical))
        stages["every_domain_reached_scorer"] = "PASS" if seen & set(canonical) == set(canonical) else "FAIL"
        # gold/taxonomy preflight over synthetic suites: all labels registered
        tax_path = OUT14 / "domain_taxonomy_contract.json"
        defects = official14.scan_gold_taxonomy(Path(tempfile.gettempdir()), Path(tempfile.gettempdir()), tax_path) if False else None
        # per-suite scan on real synthetic material
        all_defects = []
        import tempfile as tf
        with tf.TemporaryDirectory(prefix="t21r14-preflight-") as tmp:
            tmp = Path(tmp)
            for sid, srows in rows.items():
                d = tmp / sid
                d.mkdir()
                (d / "holdout.jsonl").write_text("\n".join(json.dumps(r) for r in srows) + "\n", encoding="utf-8")
            all_defects = official14.scan_gold_taxonomy(tmp, tmp, tax_path)
        stages["gold_taxonomy_preflight"] = "PASS" if not all_defects else f"DEFECTS={all_defects[:3]}"
    finally:
        run_eval14._qualified.run_answer_row = orig_answer
        run_eval14._qualified.run_retrieval_row = orig_retrieval
        shutil.rmtree(replica, ignore_errors=True)
    stages["stub_restored"] = run_eval14._qualified.run_answer_row is orig_answer
    stages["disposable_replica_deleted"] = True
    ok = (stages["gold_taxonomy_preflight"] == "PASS"
          and stages["every_domain_reached_scorer"] == "PASS"
          and stages["stub_restored"] is True)
    stages["rehearsal_status"] = "PASS" if ok else "FAIL"
    print(json.dumps(stages, indent=2))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
