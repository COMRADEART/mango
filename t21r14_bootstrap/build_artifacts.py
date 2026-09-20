"""T21R14 bootstrap part 2: contract artifacts (ported + taxonomy wiring)."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evaluations" / "t21r13"
DST = ROOT / "evaluations" / "t21r14"
DST.mkdir(parents=True, exist_ok=True)
COMMON = [
    ("t21r13_", "t21r14_"),
    ("t21r13", "t21r14"),
    ("T21R13_", "T21R14_"),
    ("mango-r13b-v1", "mango-r14b-v1"),
    ("r13b-", "r14b-"),
    ("pre13q-", "pre14q-"),
    ("R13B", "R14B"),
    ("gk-r13b", "gk-r14b"),
]
def transform_obj(obj):
    text = json.dumps(obj, ensure_ascii=False)
    for old, new in COMMON:
        text = text.replace(old, new)
    return json.loads(text)
def wj(name, obj):
    p = DST / name
    p.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return p
PORT = [
    "holdout_construction_contract.json",
    "preregistration.json",
    "validation_contract.json",
    "scoring_semantics.json",
    "exact_design_schema.json",
    "exact_design_tag_vocabulary.json",
    "contract_gate_coverage.json",
    "contract_schema.json",
    "contract_consumer_matrix.json",
    "blindness_policy.json",
    "negative_controls.json",
    "schema_negative_controls.json",
]
for name in PORT:
    obj = json.loads((SRC / name).read_text(encoding="utf-8"))
    obj = transform_obj(obj)
    if name == "holdout_construction_contract.json":
        obj["independence"]["historical_milestones"] = 14
        obj["independence"]["includes_T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE"] = True
        obj["domain_taxonomy_contract"] = "evaluations/t21r14/domain_taxonomy_contract.json"
        obj["domain_taxonomy_rule"] = "single canonical source of truth; unknown gold.required_domains labels abort official preflight before ledger creation"
    if name in ("validation_contract.json", "scoring_semantics.json", "preregistration.json"):
        obj["domain_taxonomy_contract"] = "evaluations/t21r14/domain_taxonomy_contract.json"
    wj(name, obj)
    print("ported", name)
one_shot = {
    "artifact": "T21R14_ONE_SHOT_POLICY",
    "construction": {"mode": "one-shot", "automatic_regeneration": "FORBIDDEN", "existing_construction_ledger": "REFUSE", "failed_construction": "PERMANENT"},
    "official_evaluation": {"mode": "one-shot", "automatic_retry": "FORBIDDEN", "existing_evaluation_ledger": "REFUSE", "failed_evaluation": "PERMANENT"},
    "version": "t21r14-v1",
}
wj("one_shot_policy.json", one_shot)
print("one_shot_policy written")
