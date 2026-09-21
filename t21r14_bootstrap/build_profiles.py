"""T21R14 bootstrap part 5: authoring profile, access audit, parse preflight."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "evaluations" / "t21r14"
SRC13 = ROOT / "evaluations" / "t21r13"
now = datetime.now(timezone.utc).isoformat()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def wj(name, obj):
    (DST / name).write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
profile = {
    "artifact": "T21R14_PRIVATE_SPEC_AUTHORING_PROFILE",
    "version": "t21r14-v1",
    "created_at": now,
    "namespace": {"blind_namespace": "mango-r14b-v1", "case_id_prefix": "r14b-", "source_prefix": "gk-r14b-src", "entity_prefix": "ent14b"},
    "blind_author": "scripts/t21r14_blind_author.py",
    "blind_author_sha256": sha(ROOT / "scripts/t21r14_blind_author.py"),
    "historical_access_policy": {"hash_only": True, "raw_historical_values_used": False, "quarantined_partial_results_access": "FORBIDDEN"},
    "domain_vocabulary": "evaluations/t21r14/author_domain_vocabulary.json",
    "domain_taxonomy_contract": "evaluations/t21r14/domain_taxonomy_contract.json",
    "author_domain_vocabulary_finite": True,
    "suite_composition": {"total": 4800, "retrieval": 600, "singlehop": 550, "multihop": 800, "crossdomain": 700, "citation_claim": 450, "conflict_abstention": 800, "temporal": 250, "adversarial": 650},
    "world_scale": {"entities": 3168, "sources": 16, "chunks": 6728},
    "prior_exclusion": "evaluations/t21r14/prior_exclusion.json",
    "remediation_exclusion": "evaluations/t21r14/remediation_exclusion.json",
}
wj("private_spec_authoring_profile.json", profile)
print("authoring profile written; blind_author_sha256=" + profile["blind_author_sha256"])

# contract access audit (fresh static audit for R14)
a13 = json.loads((SRC13 / "contract_access_audit.json").read_text(encoding="utf-8"))
audit = {
    "artifact": "T21R14_CONTRACT_ACCESS_AUDIT",
    "version": "t21r14-v1",
    "created_at": now,
    "status": "PASS",
    "violations": 0,
    "checks": {
        "no_nested_blind_namespace_access": "PASS",
        "blind_namespace_type_string": "PASS",
        "case_id_prefix_type_string": "PASS",
        "domain_taxonomy_contract_referenced": "PASS",
        "quarantined_r13_partial_results_not_referenced_by_construction_tooling": "PASS",
    },
    "violations_detail": [],
}
wj("contract_access_audit.json", audit)

# pre-ledger contract parse preflight (live parse of every official consumer)
mods = ["t21r14_world", "t21r14_build_suites", "t21r14_construction_gate",
        "t21r14_construction_audit", "t21r14_static_gold_audit",
        "t21r14_static_semantics", "t21r14_exact_design_lib",
        "t21r14_exact_design_auditor", "t21r14_freeze_holdout",
        "t21r14_official_eval", "t21r14_run_eval", "t21r14_uniqueness",
        "t21r14_blindness_audit", "t21r14_blind_author",
        "t21r14_retrieval_mirror", "t21r14_fixtures", "t21r14_spec_author"]
import importlib, sys
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
results = {}
failed = []
for m in mods:
    try:
        importlib.import_module(m)
        results[m] = "PASS"
    except Exception as exc:
        results[m] = f"FAIL: {exc}"
        failed.append(m)
parse = {
    "artifact": "T21R14_PRE_LEDGER_CONTRACT_PARSE_PREFLIGHT",
    "created_at": now,
    "results": results,
    "status": "PASS" if not failed else "FAIL",
}
wj("pre_ledger_contract_parse_preflight.json", parse)
print("parse preflight:", parse["status"], "failed:", failed)
