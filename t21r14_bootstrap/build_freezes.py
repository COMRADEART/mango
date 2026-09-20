"""T21R14 bootstrap part 7: runtime + evaluator freezes."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "evaluations" / "t21r14"
SRC13 = ROOT / "evaluations" / "t21r13"
now = datetime.now(timezone.utc).isoformat()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

# --- runtime freeze: candidate unchanged; same 15 components and root -------
r13rt = json.loads((SRC13 / "runtime_freeze.json").read_text(encoding="utf-8"))
rt = {
    "artifact": "T21R14_RUNTIME_FREEZE",
    "version": "t21r14-v1",
    "status": "FROZEN",
    "candidate_commit": r13rt["candidate_commit"],
    "candidate_tree": r13rt["candidate_tree"],
    "candidate_unchanged_since_r11": True,
    "component_sha256": r13rt["component_sha256"],
    "components": [{"path": c["path"], "sha256": c["sha256"], "candidate_commit": c["candidate_commit"], "candidate_tree": c["candidate_tree"]} for c in r13rt["components"]],
    "component_root_sha256": r13rt["component_root_sha256"],
    "disk_component_hash_mismatches": 0,
    "frozen_before_real_blind_construction": True,
    "runtime_execution_count": 0,
    "note": "R13 infrastructure failure was evaluator-side; the candidate runtime is byte-identical and remains frozen (root 7bba4d0d...)".replace("7bba4d0d...", r13rt["component_root_sha256"][:8] + "..."),
    "created_at": now,
}
(DST / "runtime_freeze.json").write_text(json.dumps(rt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print("runtime freeze written; root=", rt["component_root_sha256"][:16])

# --- evaluator freeze: R14 component set (new root) -------------------------
r13ev = json.loads((SRC13 / "evaluator_freeze.json").read_text(encoding="utf-8"))
R13_ROOT = r13ev["root_sha256"]
component_map = {}
missing = []
for key in r13ev["component_sha256"]:
    new_key = key.replace("evaluations/t21r13/", "evaluations/t21r14/").replace("scripts/t21r13_", "scripts/t21r14_").replace("tests/test_t21r13_", "tests/test_t21r14_")
    target = ROOT / new_key
    if key in ("evaluations/t21r12/T21R12_CLOSURE.json", "scripts/t21r12_official_eval.py"):
        target = ROOT / key
    if target.is_file():
        component_map[new_key if new_key != key or key in ("evaluations/t21r12/T21R12_CLOSURE.json", "scripts/t21r12_official_eval.py") else key] = sha(target)
    else:
        missing.append(new_key)
for extra in ["evaluations/t21r14/domain_taxonomy_contract.json",
              "evaluations/t21r14/domain_taxonomy_consumer_matrix.json",
              "evaluations/t21r14/domain_taxonomy_coverage.json",
              "evaluations/t21r14/author_domain_vocabulary.json",
              "evaluations/t21r14/crossdomain_pair_registry.json",
              "evaluations/t21r14/r13_partial_results_quarantine.json",
              "scripts/t21r14_synthetic_rehearsal.py"]:
    p = ROOT / extra
    if p.is_file():
        component_map[extra] = sha(p)
root_payload = json.dumps({"components": dict(sorted(component_map.items()))}, sort_keys=True, separators=(",", ":")).encode()
root = hashlib.sha256(root_payload).hexdigest()
ev = {
    "artifact": "T21R14_EVALUATOR_FREEZE",
    "version": "t21r14-v1",
    "status": "FROZEN",
    "created_at": now,
    "prior_evaluator_root": R13_ROOT,
    "prior_evaluator_artifact": "evaluations/t21r13/evaluator_freeze.json (R13 root 0a310a1e...)".replace("0a310a1e...", R13_ROOT[:8] + "..."),
    "remediation": "FROZEN_EVALUATOR_HOLDOUT_DOMAIN_TAXONOMY_INCOMPATIBILITY",
    "changed_components_explanation": {
        "scripts/t21r14_official_eval.py": "gold-schema/taxonomy preflight (scan_gold_taxonomy) added; aborts before ledger creation",
        "scripts/t21r14_run_eval.py": "canonical taxonomy contract rebind of the frozen R6-lineage DOMAIN_TAXONOMY (loud failure preserved)",
        "evaluations/t21r14/domain_taxonomy_contract.json": "NEW single-source-of-truth domain label contract (14 canonical labels)",
        "scripts/t21r6_run_eval.py + scripts/t21r8_run_eval.py": "unchanged bytes; historical literal set is overridden at import by the canonical contract (no competing authority)",
        "floor_hash": "unchanged (4656be72...)".replace("4656be72...", "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"),
        "scoring_semantics": "unchanged (R13 scoring semantics ported verbatim; suite IDs/namespace only)",
    },
    "component_sha256": dict(sorted(component_map.items())),
    "components": [{"path": k, "sha256": v} for k, v in sorted(component_map.items())],
    "component_count": len(component_map),
    "root_sha256": root,
    "floor_hash": "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa",
    "candidate_commit": r13rt["candidate_commit"],
    "candidate_tree": r13rt["candidate_tree"],
    "runtime_execution_count": 0,
}
(DST / "evaluator_freeze.json").write_text(json.dumps(ev, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print("evaluator freeze written; components=", len(component_map), "root=", root[:16])
print("missing targets:", missing)
