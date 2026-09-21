import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "evaluations" / "t21r14"
SRC13 = ROOT / "evaluations" / "t21r13"
now = datetime.now(timezone.utc).isoformat()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
r13ev = json.loads((SRC13 / "evaluator_freeze.json").read_text(encoding="utf-8"))
EXCLUDE = {"preconstruction_qualification.json", "current_test_applicability.json",
           "test_failure_adjudication.json", "real_blind_construction_readiness.json",
           "pre_ledger_contract_parse_preflight.json", "T21R13_INTERFACE_REPAIR_RESULT.json"}
component_map = {}
for key in r13ev["component_sha256"]:
    base = key.rsplit("/", 1)[-1]
    if base in EXCLUDE:
        continue
    if key in ("evaluations/t21r12/T21R12_CLOSURE.json", "scripts/t21r12_official_eval.py"):
        new_key = key
    else:
        new_key = key.replace("evaluations/t21r13/", "evaluations/t21r14/").replace("scripts/t21r13_", "scripts/t21r14_").replace("tests/test_t21r13_", "tests/test_t21r14_")
    target = ROOT / new_key
    if target.is_file():
        component_map[new_key] = sha(target)
for extra in ["evaluations/t21r14/domain_taxonomy_contract.json",
              "evaluations/t21r14/domain_taxonomy_consumer_matrix.json",
              "evaluations/t21r14/domain_taxonomy_coverage.json",
              "evaluations/t21r14/author_domain_vocabulary.json",
              "evaluations/t21r14/crossdomain_pair_registry.json",
              "evaluations/t21r14/r13_partial_results_quarantine.json",
              "evaluations/t21r14/T21R14_INTERFACE_REPAIR_RESULT.json",
              "evaluations/t21r14/construction_gate_api_contract.json",
              "scripts/t21r14_synthetic_rehearsal.py",
              "scripts/t21r14_preconstruction.py"]:
    p = ROOT / extra
    if p.is_file():
        component_map[extra] = sha(p)
root = hashlib.sha256(json.dumps({"components": dict(sorted(component_map.items()))}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
ev = json.loads((DST / "evaluator_freeze.json").read_text(encoding="utf-8"))
ev["component_sha256"] = dict(sorted(component_map.items()))
ev["components"] = [{"path": k, "sha256": v} for k, v in sorted(component_map.items())]
ev["component_count"] = len(component_map)
ev["root_sha256"] = root
ev["created_at"] = now
ev["freeze_policy"] = "qualification/applicability/adjudication/readiness result artifacts are audit outputs, not frozen evaluator components; they bind the freeze root"
(DST / "evaluator_freeze.json").write_text(json.dumps(ev, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print("final evaluator freeze: components=", len(component_map), "root=", root)
