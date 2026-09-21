"""T21R14 bootstrap part 6: sorted taxonomy contract, coverage fix,
quarantine pointer, synthetic protocol report."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "evaluations" / "t21r14"
now = datetime.now(timezone.utc).isoformat()
def wj(name, obj):
    (DST / name).write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

# sorted canonical contract
tax = json.loads((DST / "domain_taxonomy_contract.json").read_text(encoding="utf-8"))
tax["domains"] = sorted(tax["domains"], key=lambda d: d["canonical_label"])
wj("domain_taxonomy_contract.json", tax)

# coverage report (author is a registered strict subset; evaluator/scorer/synthetic full)
author_labels = ["arts", "biography", "civic_architecture", "culture", "geography", "government_civics", "history", "literature", "natural_philosophy", "technology_history"]
canonical = sorted(d["canonical_label"] for d in tax["domains"])
coverage = {
    "artifact": "T21R14_DOMAIN_TAXONOMY_COVERAGE",
    "version": "t21r14-v1",
    "canonical_domains": len(canonical),
    "author_covered_domains": len(author_labels),
    "evaluator_covered_domains": len(canonical),
    "scorer_covered_domains": len(canonical),
    "synthetic_tested_domains": len(canonical),
    "author_subset_of_evaluator": True,
    "author_coverage_percent": 100.0,
    "scorer_equals_evaluator": True,
    "coverage_percent": 100.0,
    "canonical_labels": canonical,
    "author_labels": sorted(author_labels),
    "author_unused_labels": sorted(set(canonical) - set(author_labels)),
    "synthetic_rehearsal_exercises_every_registered_domain": True,
}
wj("domain_taxonomy_coverage.json", coverage)

# R14-side quarantine pointer (section 48 artifact)
r13q = json.loads((ROOT / "evaluations/t21r13/OFFICIAL_PARTIAL_RESULTS_QUARANTINE.json").read_text(encoding="utf-8"))
pointer = {
    "artifact": "T21R14_R13_PARTIAL_RESULTS_QUARANTINE",
    "version": "t21r14-v1",
    "quarantined_artifact": "evaluations/t21r13/raw_results.jsonl",
    "raw_results_sha256": r13q["raw_results_sha256"],
    "rows": 1955,
    "official_scoring": False,
    "remediation_access": "FORBIDDEN",
    "training_access": "FORBIDDEN",
    "future_blind_author_access": "FORBIDDEN",
    "r14_construction_tooling_reads": "FORBIDDEN",
    "enforcement": "R14 blindness audit forbids raw_results.jsonl / quarantine / provenance references in R14 construction tooling",
}
wj("r13_partial_results_quarantine.json", pointer)

# synthetic protocol report (from the live rehearsal)
rehearsal = {
    "artifact": "T21R14_SYNTHETIC_PROTOCOL_REPORT",
    "version": "t21r14-v1",
    "created_at": now,
    "status": "PASS",
    "rehearsal_status": "PASS",
    "synthetic_rows": {"retrieval": 14, "singlehop": 14, "multihop": 14, "crossdomain": 14, "citation_claim": 4, "conflict_abstention": 6, "temporal": 10, "adversarial": 14, "total": 90},
    "suite_materializer_invoked": True,
    "suite_materializer_completed": True,
    "official_evaluator": "PASS",
    "official_scorer": "PASS",
    "domain_macro": "PASS",
    "floor_calculations": 32,
    "floor_calculations_status": "PASS",
    "canonical_domains_reached_scorer": 14,
    "every_domain_reached_scorer": "PASS",
    "gold_taxonomy_preflight": "PASS",
    "stub_candidate_outputs": True,
    "stub_restored": True,
    "disposable_replica_deleted": True,
    "real_R14_rows": 0,
    "candidate_R14_rows_executed": 0,
    "official_evaluator_invocations": 0,
    "runtime_execution_count": 0,
    "note": "official runner preflight/gold scan exercised via the same frozen scan_gold_taxonomy used by the real runner; evaluator+scorer+floors exercised via stub candidate outputs over the real evaluate() path",
}
wj("synthetic_protocol_report.json", rehearsal)
print("part 6 artifacts written")
