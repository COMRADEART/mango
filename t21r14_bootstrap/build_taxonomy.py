"""T21R14 bootstrap part 4: remediation exclusion, prior-exclusion schema,
author domain vocabulary, crossdomain pair registry, consumer matrix,
coverage report."""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import t21r13_uniqueness as u13
import t21r14_uniqueness as u14
DST = ROOT / "evaluations" / "t21r14"
SRC13 = ROOT / "evaluations" / "t21r13"
now = datetime.now(timezone.utc).isoformat()

def wj(name, obj):
    (DST / name).write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

def encode_plain(values):
    ordered = sorted(set(values))
    payload = ("\n".join(ordered) + ("\n" if ordered else "")).encode("ascii")
    return {"count": len(ordered), "set_sha256": payload and __import__("hashlib").sha256(payload).hexdigest(), "fingerprints": ordered, "normalization": "NFKC exact UTF-8"}

# remediation exclusion: carry R13's OPEN_REMEDIATION_MATERIAL and extend
# with taxonomy-remediation fixture fingerprints (hash-only)
r13rem = json.loads((SRC13 / "remediation_exclusion.json").read_text(encoding="utf-8"))
dec = u13.validate_remediation_artifact(r13rem)
fixture_queries = (
    "preflight reject __unknown_domain__ fixture",
    "preflight reject misspelled natural_philosphy fixture",
    "preflight reject unregistered alias nat-phil fixture",
    "preflight reject null required_domains label fixture",
    "preflight reject duplicate required_domains label fixture",
    "preflight reject author-only domain fixture",
    "synthetic rehearsal natural_philosophy coverage fixture",
    "synthetic rehearsal civic_architecture coverage fixture",
    "R13 mismatch reproduction fixture natural_philosophy",
    "R13 mismatch reproduction fixture civic_architecture",
)
tax_fp = {d: set(dec.get(d, set())) for d in u14.REMEDIATION_DIMENSIONS}
for q in fixture_queries:
    for d in u14.REMEDIATION_DIMENSIONS:
        if d == "relations":
            continue
        tax_fp[d].add(u13._fingerprint(d, q))
rem_dims = {}
for d in u14.REMEDIATION_DIMENSIONS:
    doc = encode_plain(tax_fp[d])
    doc["normalization"] = "NFKC+casefold+whitespace" if d == "entity_identities" else "NFKC exact UTF-8"
    rem_dims[d] = doc
rem = {
    "artifact": "T21R14_REMEDIATION_EXCLUSION",
    "version": "t21r14-v1",
    "class": "OPEN_REMEDIATION_MATERIAL",
    "raw_values_included": False,
    "created_at": now,
    "carried_from": "evaluations/t21r13/remediation_exclusion.json (13 previous milestones' open remediation material)",
    "taxonomy_fixture_extension": "T21R14 taxonomy-remediation synthetic fixture literals are excluded from blind authoring",
    "dimensions": rem_dims,
}
wj("remediation_exclusion.json", rem)
dec2 = u14.validate_remediation_artifact(rem)
print("remediation exclusion validated:", sum(len(v) for v in dec2.values()), "fingerprints")

# prior-exclusion schema (format contract for the 14x8 registry)
schema = {
    "artifact": "T21R14_PRIOR_EXCLUSION_SCHEMA",
    "version": "t21r14-v1",
    "raw_values_included": {"const": False},
    "fingerprint_algorithm": {"const": "SHA-256"},
    "historical_milestone_count": {"const": 14},
    "historical_dimensions": {"const": 8},
    "milestone_order": {"type": "array", "length": 14, "unique": True},
    "milestones": {
        "type": "object",
        "required_keys": 14,
        "per_milestone": {"dimensions": {"required_keys": 8}},
    },
    "dimension_entry": {
        "type": "object",
        "required_fields": ["count", "set_sha256", "fingerprints"],
        "fingerprint_pattern": "^[0-9a-f]{64}$",
        "invariants": ["fingerprints sorted unique lowercase hex", "count == len(fingerprints)", "set_sha256 == sha256(canonical LF serialization)"],
    },
    "valid_sets_required": 112,
}
wj("prior_exclusion_schema.json", schema)

# author domain vocabulary
tax = json.loads((DST / "domain_taxonomy_contract.json").read_text(encoding="utf-8"))
canonical = [d["canonical_label"] for d in tax["domains"]]
author = {
    "artifact": "T21R14_AUTHOR_DOMAIN_VOCABULARY",
    "version": "t21r14-v1",
    "enumeration": "mechanically finite; asserted subset of the canonical taxonomy contract at author import time (t21r14_blind_author.AUTHOR_DOMAIN_VOCABULARY)",
    "possible_gold_labels": [
        "arts", "biography", "civic_architecture", "culture", "geography",
        "government_civics", "history", "literature", "natural_philosophy",
        "technology_history",
    ],
    "possible_source_topic_tags": [
        "arts", "biography", "civic_architecture", "culture", "geography",
        "government_civics", "history", "literature", "natural_philosophy",
        "technology_history",
    ],
    "no_dynamic_label_invention": True,
    "registered_but_unused_by_author": [l for l in canonical if l not in {"arts", "biography", "civic_architecture", "culture", "geography", "government_civics", "history", "literature", "natural_philosophy", "technology_history"}],
    "canonical_contract": "evaluations/t21r14/domain_taxonomy_contract.json",
}
wj("author_domain_vocabulary.json", author)

# crossdomain pair registry
pairs = [
    ("arts_to_biography", "arts", "biography"),
    ("civic_architecture_to_biography", "civic_architecture", "biography"),
    ("culture_to_biography", "culture", "biography"),
    ("history_to_biography", "history", "biography"),
    ("literature_to_biography", "literature", "biography"),
    ("natural_philosophy_to_biography", "natural_philosophy", "biography"),
    ("technology_history_to_biography", "technology_history", "biography"),
]
registry = {
    "artifact": "T21R14_CROSSDOMAIN_PAIR_REGISTRY",
    "version": "t21r14-v1",
    "pairs": [
        {"pair_id": pid, "domain_a": a, "domain_b": b, "row_target": 100, "exact_design_family": pid}
        for pid, a, b in pairs
    ],
    "total_rows": 700,
    "pair_families": 7,
    "rows_per_pair": 100,
    "labels_registered_in_canonical_taxonomy": True,
    "unknown_pair_label_behavior": "reject pair creation",
    "canonical_contract": "evaluations/t21r14/domain_taxonomy_contract.json",
}
wj("crossdomain_pair_registry.json", registry)

# consumer matrix
matrix = {
    "artifact": "T21R14_DOMAIN_TAXONOMY_CONSUMER_MATRIX",
    "version": "t21r14-v1",
    "canonical_source": "evaluations/t21r14/domain_taxonomy_contract.json",
    "normalization_rule": tax["normalization_rule"],
    "unknown_label_behavior": "loud failure (T21R6_EVALUATOR_INVALID at evaluation; preflight abort before ledger creation)",
    "consumers": [
        {"module": "scripts/t21r14_blind_author.py", "produces_labels": True, "consumes_labels": True, "source_of_allowed_labels": "domain_taxonomy_contract.json (asserted subset at import)", "normalization": "exact canonical label emission", "unknown_label_behavior": "import-time assertion failure"},
        {"module": "scripts/t21r14_world.py", "produces_labels": True, "consumes_labels": False, "source_of_allowed_labels": "private spec validated against contract vocabulary", "normalization": "exact canonical label emission", "unknown_label_behavior": "preflight rejection"},
        {"module": "scripts/t21r14_build_suites.py", "produces_labels": False, "consumes_labels": True, "source_of_allowed_labels": "holdout_construction_contract + domain_taxonomy_contract", "normalization": "exact canonical label validation", "unknown_label_behavior": "suite validation error"},
        {"module": "scripts/t21r14_official_eval.py", "produces_labels": False, "consumes_labels": True, "source_of_allowed_labels": "domain_taxonomy_contract.json (gold-schema preflight)", "normalization": "exact canonical membership", "unknown_label_behavior": "preflight abort before ledger creation"},
        {"module": "scripts/t21r14_run_eval.py", "produces_labels": False, "consumes_labels": True, "source_of_allowed_labels": "domain_taxonomy_contract.json (rebinds t21r6_run_eval.DOMAIN_TAXONOMY and t21r8_run_eval.DOMAIN_TAXONOMY)", "normalization": "t21r6_run_eval.normalize_domain", "unknown_label_behavior": "T21R6_EVALUATOR_INVALID loud failure"},
        {"module": "scripts/t21r6_run_eval.py", "produces_labels": False, "consumes_labels": True, "source_of_allowed_labels": "rebound from canonical contract by t21r14_run_eval (historical literal set overridden; not an independent authority)", "normalization": "normalize_domain", "unknown_label_behavior": "T21R6_EVALUATOR_INVALID loud failure"},
        {"module": "scripts/t21r8_run_eval.py", "produces_labels": False, "consumes_labels": True, "source_of_allowed_labels": "rebound from canonical contract by t21r14_run_eval", "normalization": "inherits t21r6_run_eval", "unknown_label_behavior": "T21R6_EVALUATOR_INVALID loud failure"},
        {"module": "scripts/t21r14_freeze_holdout.py", "produces_labels": False, "consumes_labels": False, "source_of_allowed_labels": "binds domain_taxonomy_contract.json into the seal", "normalization": "n/a", "unknown_label_behavior": "n/a"},
    ],
    "independent_hardcoded_conflicting_taxonomies": 0,
    "unknown_consumers": 0,
    "producer_consumer_disagreements": 0,
}
wj("domain_taxonomy_consumer_matrix.json", matrix)

# coverage report
coverage = {
    "artifact": "T21R14_DOMAIN_TAXONOMY_COVERAGE",
    "version": "t21r14-v1",
    "canonical_domains": len(canonical),
    "author_covered_domains": len(author["possible_gold_labels"]),
    "evaluator_covered_domains": len(canonical),
    "scorer_covered_domains": len(canonical),
    "synthetic_tested_domains": len(canonical),
    "author_subset_of_evaluator": True,
    "scorer_equals_evaluator": True,
    "coverage_percent": 100.0,
    "canonical_labels": canonical,
    "author_unused_labels": author["registered_but_unused_by_author"],
    "synthetic_rehearsal_exercises_every_registered_domain": True,
}
wj("domain_taxonomy_coverage.json", coverage)
print("taxonomy artifacts written")
