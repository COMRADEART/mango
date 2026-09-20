"""T21R14 bootstrap part 3: 14x8 prior-exclusion registry, remediation
exclusion (with taxonomy-remediation fixtures), author domain vocabulary,
crossdomain pair registry, consumer matrix, coverage report."""
from __future__ import annotations
import base64, gzip, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import t21r13_uniqueness as u13
DST = ROOT / "evaluations" / "t21r14"
SRC13 = ROOT / "evaluations" / "t21r13"
DIMENSIONS = u13.DIMENSIONS
R13_MILESTONE = "T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE"

def canonical_set_sha(values):
    ordered = sorted(set(values))
    payload = ("\n".join(ordered) + ("\n" if ordered else "")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()

def encode_plain(values):
    ordered = sorted(set(values))
    return {
        "count": len(ordered),
        "set_sha256": canonical_set_sha(set(ordered)),
        "fingerprints": ordered,
        "normalization": "NFKC exact UTF-8",
    }

def encode_entity(values):
    doc = encode_plain(values)
    doc["normalization"] = "NFKC+casefold+whitespace"
    return doc

# --- verify the 13-milestone R13 registry decodes cleanly -------------------
r13 = json.loads((SRC13 / "prior_exclusion.json").read_text(encoding="utf-8"))
decoded13 = {}
for mname, block in r13["milestones"].items():
    dims = block["dimensions"]
    assert set(dims) == set(DIMENSIONS), mname
    for d, doc in dims.items():
        decoded13.setdefault(mname, {})[d] = u13._decode(doc)
assert len(decoded13) == 13
for mname, dims in decoded13.items():
    for d in DIMENSIONS:
        assert all(len(v) == 64 and all(c in "0123456789abcdef" for c in v) for v in dims[d])
print("R13 registry verified: 13 milestones, 104 valid sets")

# --- fingerprint the sealed R13 holdout (hash-only) -------------------------
sources = u13._load_jsonl(ROOT / "rag/gk_holdout_t21r13/sources.jsonl")
chunks = u13._load_jsonl(ROOT / "rag/gk_holdout_t21r13/chunks.jsonl")
rows = []
for p in sorted((SRC13 / "suites").glob("*/holdout.jsonl")):
    rows.extend(u13._load_jsonl(p))
world = u13._load_jsonl(ROOT / "rag/gk_holdout_t21r13/world.jsonl")
fp = u13.fingerprint_material(sources, chunks, rows, world)
r13_dims = {}
for d in DIMENSIONS:
    doc = encode_plain(fp[d])
    if d == "entity_identities":
        doc["normalization"] = "NFKC+casefold+whitespace"
    r13_dims[d] = doc
r13_milestone = {
    "non_promotional": True,
    "raw_material_committed": True,
    "sealed_commit": "78a2c84e02b989d7ea4aed284975e70420d95c7e",
    "official_commit": "a8fbafd8107a9fa019750f8ad77760f22b7cb893",
    "official_result": "T21R13_OFFICIAL_EVALUATION_INFRASTRUCTURE_FAILURE",
    "rows_officially_executed": 1955,
    "rows_officially_scored": 0,
    "candidate_outputs_quarantined": True,
    "exclusion_scope": "complete sealed R13 holdout (all 4800 rows), not only executed rows",
    "source_artifacts": [
        {"identity": "git:78a2c84e02b989d7ea4aed284975e70420d95c7e/rag/gk_holdout_t21r13/sources.jsonl", "sha256": hashlib.sha256(sources_path_bytes).hexdigest()} if False else {"identity": "git:78a2c84e02b989d7ea4aed284975e70420d95c7e/evaluations/t21r13/holdout_manifest.json", "sha256": hashlib.sha256((SRC13 / "holdout_manifest.json").read_bytes()).hexdigest()},
    ],
    "dimensions": r13_dims,
}
milestones = dict(r13["milestones"])
milestones[R13_MILESTONE] = r13_milestone
milestone_order = list(r13["milestone_order"]) + [R13_MILESTONE]
assert set(milestone_order) == set(milestones)
registry = {
    "artifact": "T21R14_PRIOR_EXCLUSION",
    "version": "t21r14-v1",
    "fingerprint_algorithm": "SHA-256",
    "payload_encoding": "plain sorted unique lowercase hex SHA-256 fingerprint arrays",
    "raw_values_included": False,
    "historical_milestone_count": 14,
    "historical_dimensions": 8,
    "milestone_order": milestone_order,
    "milestones": milestones,
}
p = DST / "prior_exclusion.json"
p.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
sets_total = 14 * 8
import t21r14_uniqueness as u14
dec = u14.validate_artifact(registry)
valid = sum(len(dims) for dims in dec.values())
print("R14 registry written and validated: 14 milestones,", valid, "sets")
