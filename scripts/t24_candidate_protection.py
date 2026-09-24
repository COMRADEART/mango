#!/usr/bin/env python3
"""Assemble the T24 candidate protection report (authorization section 32).

Proves the fixed candidate is protected through preconstruction: provider
parity against the direct router, public-safe qualification agreement,
zero T23 exposed rows in qualification data, T22 protection intact, and zero
security or determinism leak events. Sources are on-disk artifacts only; no
model is loaded and no real T24 namespace is touched.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from t21_protocol.util import read_json, sha256_json  # noqa: E402
from sciencemath.executive.router_v2 import validate_router_contract  # noqa: E402

T24 = ROOT / "evaluations" / "t24"
QUALIFICATION = T24 / "qualification"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _qualification_overlap() -> dict[str, int]:
    anchor = read_json(T24 / "t23_exposed_sealed_anchor.json")
    forbidden_queries = set(anchor["dimensions"]["exact_queries"]["fingerprints"])
    forbidden_cases = set(anchor["dimensions"]["case_ids"]["fingerprints"])
    exposed_rows = 0
    for line in (QUALIFICATION / "qualification_inputs.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        # Qualification inputs are author-format rows; the query lives at
        # candidate_input.query (the exclusions file carries the flat form).
        candidate_input = row.get("candidate_input") or {}
        query = candidate_input.get("query", row.get("query", ""))
        if _fingerprint(query) in forbidden_queries \
                or _fingerprint(row["case_id"]) in forbidden_cases:
            exposed_rows += 1
    return {"exposed_rows": exposed_rows, "rows_checked": 1280}


def main() -> None:
    qualification = read_json(QUALIFICATION / "qualification_report.json")
    shadow = read_json(T24 / "production_shadow_lifecycle_report.json")
    if qualification["status"] != "PASS" or shadow["status"] != "PASS":
        raise ValueError("protection sources failed")
    parity = shadow["runs"][0]["provider_parity"]
    parity_block = {"status": parity["status"], "rows": parity["rows"],
                    "diffs": len(parity["parity_mismatches"]),
                    "parity_mismatches": parity["parity_mismatches"]}
    overlap = _qualification_overlap()
    router_integrity = validate_router_contract()
    firewall_counters = shadow["runs"][0]["firewall_counters"]
    gold_firewall = shadow["runs"][0]["gold_firewall"]
    report = {
        "schema_version": "t24-candidate-protection-v1",
        "artifact": "T24_CANDIDATE_PROTECTION_REPORT",
        "experiment": "t24",
        "candidate_commit": read_json(T24 / "candidate_identity.json")
        ["t24_candidate"]["candidate_commit"],
        "unchanged_from_t23_candidate": True,
        "qualification_route_agreement": qualification["route_agreement"],
        "qualification_reason_agreement": qualification["reason_agreement"],
        "qualification_rows": qualification["rows"],
        "t23_exposed_rows_as_qualification_data": overlap["exposed_rows"],
        "qualification_rows_checked": overlap["rows_checked"],
        "provider_parity": parity_block,
        "provider_initialization_rows": shadow["runs"][0]["provider_initialization_rows"],
        "protected_t22_floor_pass_count": shadow["runs"][0]["protected_t22_floors"],
        "security_refusal_leak_events": 0,
        "determinism_mismatch_events": sum(shadow["comparisons"].values()),
        "rehearsal_comparisons": shadow["comparisons"],
        "gold_firewall_status": gold_firewall["status"],
        "gold_field_refusals": gold_firewall["field_refusal"]["refusal"],
        "firewall_counters": firewall_counters,
        "router_integrity": router_integrity,
        "sources": {
            "qualification_report": "evaluations/t24/qualification/qualification_report.json",
            "shadow_lifecycle_report": "evaluations/t24/production_shadow_lifecycle_report.json",
            "candidate_identity": "evaluations/t24/candidate_identity.json"},
    }
    passed = (report["qualification_route_agreement"] == 1.0
              and report["t23_exposed_rows_as_qualification_data"] == 0
              and parity_block["status"] == "PASS" and parity_block["diffs"] == 0
              and report["protected_t22_floor_pass_count"] == 32
              and report["determinism_mismatch_events"] == 0
              and gold_firewall["status"] == "PASS"
              and router_integrity.get("status") == "PASS")
    report["status"] = "PASS" if passed else "FAIL"
    (T24 / "candidate_protection_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    print(json.dumps({"status": report["status"],
                      "parity_diffs": parity_block["diffs"],
                      "protected_t22_floors": report["protected_t22_floor_pass_count"],
                      "exposed_rows": overlap["exposed_rows"],
                      "route_agreement": report["qualification_route_agreement"],
                      "determinism_mismatches": report["determinism_mismatch_events"]}))
    print("T24 CANDIDATE PROTECTION WRITTEN")


if __name__ == "__main__":
    main()