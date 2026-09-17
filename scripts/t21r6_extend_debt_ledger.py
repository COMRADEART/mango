"""T21R6 — complete the inherited historical debt ledger (one-time repair).

The entry-gate ledger pinned exactly one inherited mismatch
(scripts/t21r4_run_eval.py). The protection battery's freeze-identity
layers surface FIVE further freeze-input mismatches that pre-date T21R6:
each mismatched file is byte-identical to the canonical base
f71cdb6e7855ba20d58e38b05d7286457bc300ae and was last changed by its own
milestone's validation commit (the same post-freeze re-record pattern as
the pinned evaluator). This script mechanically re-verifies every
mismatch (manifest hash vs current file vs canonical-base git blob),
extends the ledger, and rewrites nothing outside evaluations/t21r6/.

Usage: python scripts/t21r6_extend_debt_ledger.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evaluations" / "t21r6" / "inherited_historical_debt.json"
BASE = "f71cdb6e7855ba20d58e38b05d7286457bc300ae"

# (milestone, label, path) as recorded in that milestone's holdout
# manifest freeze_inputs.
CANDIDATES = [
    ("t21r4", "runtime_freeze", "evaluations/t21r4/runtime_freeze.json",
     "fbe034aa68d9a2af816f3c4edddb2e76bc157442",
     "T21R4: validate conflict repair on strict fresh blind holdout"),
    ("t21r4", "holdout_uniqueness",
     "evaluations/t21r4/holdout_uniqueness.json",
     "fbe034aa68d9a2af816f3c4edddb2e76bc157442",
     "T21R4: validate conflict repair on strict fresh blind holdout"),
    ("t21r4", "evaluator_freeze_script",
     "scripts/t21r4_freeze_evaluator.py",
     "fbe034aa68d9a2af816f3c4edddb2e76bc157442",
     "T21R4: validate conflict repair on strict fresh blind holdout"),
    ("t21r5", "runtime_freeze", "evaluations/t21r5/runtime_freeze.json",
     "da044e483f9eb17685661892a75ca28397f9a0ea",
     "T21R5: validate repaired Knowledge RAG on fresh blind holdout"),
    ("t21r5", "holdout_uniqueness",
     "evaluations/t21r5/holdout_uniqueness.json",
     "da044e483f9eb17685661892a75ca28397f9a0ea",
     "T21R5: validate repaired Knowledge RAG on fresh blind holdout"),
]


def sha_raw(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def base_blob_sha(path: str) -> str:
    out = subprocess.run(
        ["git", "cat-file", "blob", f"{BASE}:{path}"],
        cwd=ROOT, capture_output=True, check=True).stdout
    return hashlib.sha256(out).hexdigest()


def main() -> int:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    existing_paths = {m["path"] for m in ledger["inherited_mismatches"]}
    added = []
    for milestone, label, rel, drift_sha, drift_subject in CANDIDATES:
        if rel in existing_paths:
            continue
        manifest = json.loads(
            (ROOT / "evaluations" / milestone / "holdout_manifest.json")
            .read_text(encoding="utf-8"))
        expected = manifest["freeze_inputs"][label]["sha256"]
        p = ROOT / rel
        actual = sha_raw(p)
        base_sha = base_blob_sha(rel)
        assert actual != expected, (rel, "no mismatch?")
        assert actual == base_sha, (rel, "file is NOT identical to the "
                                    "canonical base - NOT inherited debt")
        ledger["inherited_mismatches"].append({
            "path": rel,
            "artifact": f"evaluations/{milestone}/holdout_manifest.json",
            "ledger_field": f"freeze_inputs.{label}.sha256",
            "historical_expected_sha256": expected,
            "canonical_actual_sha256": actual,
            "canonical_base_sha_at_mismatch": BASE,
            "drift_origin_commit": drift_sha,
            "drift_origin_commit_subject": drift_subject,
        })
        added.append(rel)

    ledger["provenance"]["explanation"] = (
        "The T21R4/T21R5 validation commits (fbe034a, da044e4) re-recorded "
        "several of their own post-freeze artifacts after their holdout "
        "freeze manifests were written: evaluations/t21r4/runtime_freeze.json, "
        "evaluations/t21r4/holdout_uniqueness.json, "
        "scripts/t21r4_freeze_evaluator.py, evaluations/t21r5/runtime_freeze.json "
        "and evaluations/t21r5/holdout_uniqueness.json, in the same "
        "post-freeze re-record pattern as the originally pinned "
        "scripts/t21r4_run_eval.py. Every mismatched file is byte-identical "
        "to the canonical base f71cdb6e (mechanically re-verified by "
        "scripts/t21r6_extend_debt_ledger.py via git cat-file against the "
        "base blob), so the mismatches pre-date T21R6, are inherited from "
        "the canonical base, and are NOT new R6 corruption. T21R4/T21R5 "
        "history is NOT rewritten; the ledger only grows inside "
        "evaluations/t21r6/.")
    ledger["r6_protection_rule"]["pass_when"] = [
        "every inherited mismatch above is EXACTLY unchanged: the current "
        "file sha256 equals canonical_actual_sha256 AND the file is "
        "byte-identical to the canonical-base git blob",
        "no OTHER freeze-input label of the T21R4 or T21R5 holdout "
        "manifests fails its freeze-identity check",
        "no historical artifact or corpus differs from the canonical base",
    ]
    LEDGER.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps({"status": "LEDGER_EXTENDED",
                      "added": added,
                      "total_mismatches": len(ledger["inherited_mismatches"])},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())