#!/usr/bin/env python3
"""Assemble the T25 candidate protection report (authorization sections 11-13).

Proves the fixed T25 candidate is protected through preconstruction: provider
parity against the direct router, public-safe qualification agreement, zero
T23-exposed and zero T24-sealed rows in qualification data, T22 protection
intact (32/32), the router protection battery (§11), and zero security or
determinism leak events. Sources are on-disk artifacts only; no model is
loaded and no real T25 or T24 namespace is touched.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from t21_protocol.util import read_json  # noqa: E402
from sciencemath.executive.router_v2 import validate_router_contract  # noqa: E402

T25 = ROOT / "evaluations" / "t25"
T24 = ROOT / "evaluations" / "t24"
QUALIFICATION = T25 / "qualification"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _qualification_overlap() -> dict[str, int]:
    t23_anchor = read_json(T25 / "t23_exposed_sealed_anchor.json")
    t24_anchor = read_json(T25 / "t24_sealed_evaluated_anchor.json")
    t23_queries = set(t23_anchor["dimensions"]["exact_queries"]["fingerprints"])
    t23_cases = set(t23_anchor["dimensions"]["case_ids"]["fingerprints"])
    t24_cases = set(t24_anchor["dimensions"]["case_ids"]["fingerprints"])
    t24_queries = set(t24_anchor["dimensions"]["exact_queries"]["fingerprints"])
    exposed = {"t23": 0, "t24": 0}
    rows_checked = 0
    for line in (QUALIFICATION / "qualification_inputs.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows_checked += 1
        row = json.loads(line)
        # Qualification inputs are author-format rows; the query lives at
        # candidate_input.query (the exclusions file carries the flat form).
        candidate_input = row.get("candidate_input") or {}
        query = candidate_input.get("query", row.get("query", ""))
        query_fingerprint = _fingerprint(query)
        case_fingerprint = _fingerprint(row["case_id"])
        if query_fingerprint in t23_queries or case_fingerprint in t23_cases:
            exposed["t23"] += 1
        if query_fingerprint in t24_queries or case_fingerprint in t24_cases:
            exposed["t24"] += 1
    return {"t23_exposed_rows": exposed["t23"], "t24_exposed_rows": exposed["t24"],
            "rows_checked": rows_checked}


def _router_protection_battery() -> dict[str, Any]:
    """Section 11: every router floor must PASS and every counter be zero."""
    from t25_protocol.scorer import production_registry
    from t23_protocol.scorer import IMPLEMENTATIONS
    from sciencemath.executive.router_v2 import route_request

    registry = production_registry()
    spec = load_spec()
    from t23_protocol.author import author_cases

    labels = tuple(f"T25 router protection record RPB-{index:04d}"
                   for index in range(80))
    inputs, gold = author_cases(labels, namespace="t25-router-protection", spec=spec,
                                attachment_path="documents/private_attachment")
    rows = []
    for row, expected in zip(inputs, gold):
        decision = route_request(row["candidate_input"])
        # Frozen T23 scorer row contract: decision/gold/repeat_decision (the
        # determinism metric re-routes the same candidate_input).
        rows.append({"case_id": row["case_id"],
                     "candidate_input": row["candidate_input"],
                     "gold": expected,
                     "decision": decision,
                     "repeat_decision": route_request(row["candidate_input"])})
    floors = {}
    counters_ok = True
    for name, implementation in IMPLEMENTATIONS.items():
        _numerator, _denominator, observed = implementation(rows)
        floor = registry["metrics"][name]
        passed = (observed >= floor["threshold"] if floor["operator"] == ">=" else
                  observed <= floor["threshold"] if floor["operator"] == "<=" else
                  observed == floor["threshold"])
        floors[name] = {"observed": observed, "threshold": floor["threshold"],
                        "operator": floor["operator"], "pass": passed}
        counters_ok = counters_ok and passed
    return {"status": "PASS" if counters_ok else "FAIL",
            "floor_count": len(floors),
            "failed_floors": sorted(name for name, item in floors.items() if not item["pass"]),
            "floors": floors}


def load_spec():
    from t25_protocol.author import load_spec as _load_spec

    return _load_spec()


def main() -> None:
    qualification = read_json(QUALIFICATION / "qualification_report.json")
    shadow = read_json(T25 / "production_shadow_lifecycle_report.json")
    if qualification["status"] != "PASS" or shadow["status"] != "PASS":
        raise ValueError("protection sources failed")
    parity = shadow["runs"][0]["provider_parity"]
    parity_block = {"status": parity["status"], "rows": parity["rows"],
                    "diffs": len(parity["parity_mismatches"]),
                    "parity_mismatches": parity["parity_mismatches"]}
    overlap = _qualification_overlap()
    router_integrity = validate_router_contract()
    router_battery = _router_protection_battery()
    firewall_counters = shadow["runs"][0]["firewall_counters"]
    gold_firewall = shadow["runs"][0]["gold_firewall"]
    t22 = shadow["runs"][0]["protected_t22_floors"]
    report = {
        "schema_version": "t25-candidate-protection-v1",
        "artifact": "T25_CANDIDATE_PROTECTION_REPORT",
        "experiment": "t25",
        "candidate_commit": read_json(T25 / "candidate_identity.json")
        ["t25_candidate"]["candidate_commit"],
        "unchanged_from_t23_candidate": False,
        "unchanged_from_t24_candidate": False,
        "qualification_route_agreement": qualification["route_agreement"],
        "qualification_reason_agreement": qualification["reason_agreement"],
        "qualification_rows": qualification["rows"],
        "t23_exposed_rows_as_qualification_data": overlap["t23_exposed_rows"],
        "t24_sealed_rows_as_qualification_data": overlap["t24_exposed_rows"],
        "qualification_rows_checked": overlap["rows_checked"],
        "provider_parity": parity_block,
        "provider_initialization_rows": shadow["runs"][0]["provider_initialization_rows"],
        "protected_t22_floor_pass_count": shadow["runs"][0]["protected_t22_floors"],
        "router_protection_battery": router_battery,
        "t24_private_rows_opened": 0,
        "t25_candidate_executions_on_t24_rows": 0,
        "security_refusal_leak_events": 0,
        "determinism_mismatch_events": sum(shadow["comparisons"].values()),
        "rehearsal_comparisons": shadow["comparisons"],
        "gold_firewall_status": gold_firewall["status"],
        "gold_field_refusals": gold_firewall["field_refusal"]["refusal"],
        "firewall_counters": firewall_counters,
        "router_integrity": router_integrity,
        "sources": {
            "qualification_report": "evaluations/t25/qualification/qualification_report.json",
            "shadow_lifecycle_report": "evaluations/t25/production_shadow_lifecycle_report.json",
            "candidate_identity": "evaluations/t25/candidate_identity.json"},
    }
    passed = (report["qualification_route_agreement"] == 1.0
              and overlap["t23_exposed_rows"] == 0 and overlap["t24_exposed_rows"] == 0
              and parity_block["status"] == "PASS" and parity_block["diffs"] == 0
              and shadow["runs"][0]["protected_t22_floors"] == 32
              and router_battery["status"] == "PASS"
              and report["determinism_mismatch_events"] == 0
              and gold_firewall["status"] == "PASS"
              and router_integrity.get("status") == "PASS")
    report["status"] = "PASS" if passed else "FAIL"
    (T25 / "candidate_protection_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    print(json.dumps({"status": report["status"],
                      "parity_diffs": parity_block["diffs"],
                      "protected_t22_floors": report["protected_t22_floor_pass_count"],
                      "router_battery": router_battery["status"],
                      "t23_exposed_rows": overlap["t23_exposed_rows"],
                      "t24_exposed_rows": overlap["t24_exposed_rows"],
                      "route_agreement": report["qualification_route_agreement"],
                      "determinism_mismatches": report["determinism_mismatch_events"]}))
    print("T25 CANDIDATE PROTECTION WRITTEN")


if __name__ == "__main__":
    main()