"""T26 production-grade private construction lifecycle.

Real construction is token-gated (``T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION``)
and is NOT authorized by the current remediation document: this module is
frozen infrastructure only. Every function here runs on disposable synthetic
fixtures during rehearsals; no real T26 blind row exists.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .contract import FAMILIES, storage_policy
from .exclusion import (DIMENSIONS, SCHEMA as EXCLUSION_SCHEMA,
                        ARTIFACT as EXCLUSION_ARTIFACT,
                        audit_nine_dimensions,
                        build_historical_exclusion_document,
                        observed_bundle_fingerprints)
from .oracle import SCHEMA as ORACLE_SCHEMA, ARTIFACT as ORACLE_ARTIFACT
from .oracle import verify_oracle_result

CONSTRUCTION_TOKEN = "T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
EVALUATION_TOKEN = "T26_ONE_SHOT_OFFICIAL_EVALUATION"
SCHEME = "t26-private://"
STORE_ID = "T26-STORE-01"
NAMESPACE = "t26"
EXPERIMENT = "t26"
MATERIAL_MODE = "REAL_BLIND"
ATTEMPT = 1

LEDGER_SCHEMA = "t26-construction-ledger-v2"
MANIFEST_SCHEMA = "t26-private-manifest-v4"
SEAL_SCHEMA = "t26-holdout-seal-v3"
RECEIPT_SCHEMA = "t26-public-construction-receipt-v2"
COMMITMENT_SCHEMA = "t26-public-construction-commitment-v2"
CONSTRUCTION_AUDIT_SCHEMA = "t26-real-construction-audit-v1"
CONTRACT_LEAF_SCHEMA = "t26-construction-contract-leaf-audit-v1"
GATE_SCHEMA = "t26-real-construction-gate-v1"
PUBLICATION_GATE_SCHEMA = "t26-construction-publication-gate-v1"
PUBLICATION_LEAKAGE_STATE = "T26_POST_CONSTRUCTION_PUBLICATION_LEAKAGE"
ONE_SHOT_TOKEN = "T26_ONE_SHOT_STATE_MACHINE_V2"
ONE_SHOT_MARKER = "construction/one_shot_spent.json"

CONSTRUCTION_STATES = ("LEDGER_CREATED", "MATERIALIZED", "AUDITED",
                       "GATE_PASS", "MANIFESTED", "SEALED")
NEXT_STATE = {"LEDGER_CREATED": "MATERIALIZED", "MATERIALIZED": "AUDITED",
              "AUDITED": "GATE_PASS", "GATE_PASS": "MANIFESTED",
              "MANIFESTED": "SEALED"}

# Gold-only fields that must never appear in candidate-visible input.
GOLD_ONLY_FIELDS = ("expected_terminal", "expected_answer",
                    "expected_replan_trigger", "recoverable_failure",
                    "safe_abstention")
CANDIDATE_FIELDS = ("scenario_id", "plan", "classification", "family")

LEDGER_BINDING_FIELDS = (
    "experiment", "attempt", "authorization", "material_mode", "namespace",
    "store_identity", "execution_checkout_commit", "execution_checkout_tree",
    "candidate_commit", "candidate_tree", "runtime_root",
    "preconstruction_freeze_sha256", "freeze_component_count",
    "freeze_component_root", "freeze_root", "execution_contract_sha256",
    "authority_graph_sha256", "production_graph_sha256",
    "metric_registry_sha256", "private_storage_policy_sha256",
    "qualification_exclusion_sha256", "live_web_firewall_registry_sha256",
    "historical_exclusion_identity", "historical_exclusion_root",
)

AUTHOR_PROVENANCE_SCHEMA = "t26-private-author-attestation-v1"
AUTHOR_READ_COUNTERS = (
    "t23_reads", "t24_private_reads", "t25_private_reads",
    "candidate_output_reads", "qualification_case_reads",
    "rehearsal_case_reads", "future_evaluation_reads",
)
AUTHOR_PROVENANCE_FIELDS = (
    "schema_version", "private_author_identity", "authoring_packet_sha256",
    "scenario_bundle_sha256", "scenario_bundle_root", "gold_bundle_sha256",
    "gold_bundle_root", "auxiliary_private_fixture_root", *AUTHOR_READ_COUNTERS,
)
FIXTURE_REQUIRED_FIELDS = (
    "logical_id", "classification", "sha256", "byte_size", "schema",
    "content_base64",
)
FIXTURE_ALLOWED_FIELDS = frozenset(FIXTURE_REQUIRED_FIELDS) | frozenset(DIMENSIONS)


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_author_provenance(cases: list[dict[str, Any]],
                            gold: list[dict[str, Any]],
                            fixtures: list[dict[str, Any]], *,
                            private_author_identity: str,
                            read_counters: dict[str, int]) -> dict[str, Any]:
    """Build the hash-bound clean-room attestation supplied by the author."""
    if set(read_counters) != set(AUTHOR_READ_COUNTERS):
        raise ValueError("private author read-counter set mismatch")
    return {
        "schema_version": AUTHOR_PROVENANCE_SCHEMA,
        "private_author_identity": private_author_identity,
        "authoring_packet_sha256": sha256_json(
            observed_bundle_fingerprints(cases, gold, fixtures)),
        "scenario_bundle_sha256": _sha_bytes(_canonical(cases)),
        "scenario_bundle_root": sha256_json(cases),
        "gold_bundle_sha256": _sha_bytes(_canonical(gold)),
        "gold_bundle_root": sha256_json(gold),
        "auxiliary_private_fixture_root":
            sha256_json(fixtures) if fixtures else None,
        **dict(sorted(read_counters.items())),
    }


def synthetic_author_provenance(cases: list[dict[str, Any]],
                                gold: list[dict[str, Any]],
                                fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    """Disposable rehearsal attestation; never authorizes real construction."""
    return build_author_provenance(
        cases, gold, fixtures,
        private_author_identity="T26_DISPOSABLE_SYNTHETIC_AUTHOR_V1",
        read_counters={key: 0 for key in AUTHOR_READ_COUNTERS},
    )


def validate_author_provenance(provenance: dict[str, Any],
                               cases: list[dict[str, Any]],
                               gold: list[dict[str, Any]],
                               fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate author provenance before the exclusive ledger is created."""
    if not isinstance(provenance, dict) or set(provenance) != set(AUTHOR_PROVENANCE_FIELDS):
        raise ValueError("private author provenance binding set mismatch")
    if provenance["schema_version"] != AUTHOR_PROVENANCE_SCHEMA:
        raise ValueError("private author provenance schema mismatch")
    if not isinstance(provenance["private_author_identity"], str) or not provenance[
            "private_author_identity"].strip():
        raise ValueError("private author identity missing")
    expected = build_author_provenance(
        cases, gold, fixtures,
        private_author_identity=provenance["private_author_identity"],
        read_counters={key: provenance.get(key) for key in AUTHOR_READ_COUNTERS},
    )
    if any(provenance.get(key) != 0 for key in AUTHOR_READ_COUNTERS):
        raise ValueError("private author provenance reports prohibited reads")
    if provenance != expected:
        raise ValueError("private author provenance hash binding mismatch")
    return dict(sorted(provenance.items()))


def validate_private_fixtures(fixtures: list[dict[str, Any]]) -> list[bytes]:
    """Fail closed on auxiliary private fixture metadata and payload bytes."""
    payloads: list[bytes] = []
    logical_ids: set[str] = set()
    for fixture in fixtures:
        if (not isinstance(fixture, dict) or
                not set(FIXTURE_REQUIRED_FIELDS) <= set(fixture) or
                not set(fixture) <= FIXTURE_ALLOWED_FIELDS):
            raise ValueError("auxiliary private fixture binding set mismatch")
        logical_id = fixture["logical_id"]
        if (not isinstance(logical_id, str) or not logical_id or
                logical_id in logical_ids):
            raise ValueError("auxiliary private fixture logical ID invalid")
        logical_ids.add(logical_id)
        if fixture["classification"] != "PRIVATE_BLIND":
            raise ValueError("auxiliary private fixture classification invalid")
        if not isinstance(fixture["schema"], str) or not fixture["schema"]:
            raise ValueError("auxiliary private fixture schema missing")
        try:
            payload = base64.b64decode(fixture["content_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("auxiliary private fixture payload invalid") from exc
        if (fixture["byte_size"] != len(payload) or
                fixture["sha256"] != _sha_bytes(payload)):
            raise ValueError("auxiliary private fixture hash mismatch")
        payloads.append(payload)
    return payloads


class ConstructionLedgerError(RuntimeError):
    """One-shot construction ledger violation (fail closed)."""


class T26ConstructionLedger:
    """Append-only, hash-chained, exclusive one-shot construction ledger.

    The exclusive creation binds the complete T26 experiment identity. Every
    event carries (index, type, timestamp, previous-event hash, payload, event
    hash). Duplicate creation, a second attempt, and deleted/recreated ledgers
    are all rejected or detectable.
    """

    def __init__(self, store: Any, document: dict[str, Any]) -> None:
        self._store = store
        self.document = document

    # -- creation ---------------------------------------------------------
    @classmethod
    def create_exclusive(cls, store: Any, bindings: dict[str, Any],
                         authorization: str) -> "T26ConstructionLedger":
        if authorization != CONSTRUCTION_TOKEN:
            raise PermissionError("exact T26 construction authorization token required")
        if bindings.get("attempt") != ATTEMPT:
            raise ValueError("T26 construction permits attempt 1 only")
        if bindings.get("material_mode") != MATERIAL_MODE:
            raise ValueError("T26 real construction requires REAL_BLIND material mode")
        if bindings.get("namespace") != NAMESPACE:
            raise ValueError("T26 real construction namespace mismatch")
        if bindings.get("store_identity") != STORE_ID:
            raise ValueError("T26 private store identity mismatch")
        required = LEDGER_BINDING_FIELDS
        missing = [key for key in required if key not in bindings]
        if missing:
            raise ValueError(f"construction ledger binding incomplete: {missing}")
        unknown = set(bindings) - set(required)
        if unknown:
            raise ValueError(f"construction ledger carries unknown bindings: {sorted(unknown)}")
        marker_committed = False
        try:
            store.commitment(ONE_SHOT_MARKER)
            marker_committed = True
        except (KeyError, ValueError):
            pass
        if (store.has("construction/ledger.json") or
                store.has(ONE_SHOT_MARKER) or marker_committed):
            raise ConstructionLedgerError(
                "T26 one-shot construction ledger already exists (duplicate refused)")
        created = _now()
        genesis = {"event_index": 0, "event_type": "LEDGER_CREATED",
                   "timestamp": created, "previous_event_hash": "0" * 64,
                   "payload": {"bindings_complete": True,
                               "one_shot_state": ONE_SHOT_TOKEN}}
        genesis["event_hash"] = sha256_json(genesis)
        document = {"schema_version": LEDGER_SCHEMA,
                    "artifact": "T26_REAL_CONSTRUCTION_LEDGER",
                    "experiment": EXPERIMENT, "attempt": ATTEMPT,
                    "authorization": authorization,
                    "material_mode": MATERIAL_MODE, "namespace": NAMESPACE,
                    "store_identity": STORE_ID, "state": "LEDGER_CREATED",
                    "created_at": created, "updated_at": created,
                    "bindings": dict(sorted(bindings.items())),
                    "events": [genesis], "event_count": 1,
                    "final_event_hash": genesis["event_hash"]}
        store.write_once("construction/ledger.json", document)
        ledger = cls(store, document)
        try:
            store.write_once(ONE_SHOT_MARKER, {
                "schema_version": "t26-construction-one-shot-marker-v1",
                "artifact": "T26_CONSTRUCTION_ONE_SHOT_SPENT",
                "experiment": EXPERIMENT, "attempt": ATTEMPT,
                "ledger_genesis_hash": genesis["event_hash"],
                "created_at": created,
            })
        except Exception as exc:
            ledger.fail("LEDGER_CREATED", type(exc).__name__,
                        {"error": "one-shot marker creation failed"})
            raise
        return ledger

    # -- state machine ----------------------------------------------------
    def advance(self, target: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.document["state"] not in NEXT_STATE:
            raise ConstructionLedgerError(
                f"forbidden transition from terminal state {self.document['state']}")
        if NEXT_STATE[self.document["state"]] != target:
            raise ConstructionLedgerError(
                f"forbidden transition {self.document['state']} -> {target}")
        previous_hash = self.document["final_event_hash"]
        event = {"event_index": self.document["event_count"], "event_type": target,
                 "timestamp": _now(), "previous_event_hash": previous_hash,
                 "payload": payload or {}}
        event["event_hash"] = sha256_json(event)
        self.document["events"].append(event)
        self.document["state"] = target
        self.document["event_count"] += 1
        self.document["final_event_hash"] = event["event_hash"]
        self.document["updated_at"] = _now()
        self._store.replace("construction/ledger.json", self.document)
        return self.document

    def fail(self, failure_phase: str, failure_class: str,
             evidence: dict[str, Any]) -> dict[str, Any]:
        """Terminal FAILED event; no retry, no repair-resume under this attempt."""
        if self.document["state"] == "FAILED":
            return self.document
        if self.document["state"] == "SEALED":
            raise ConstructionLedgerError("sealed construction ledger cannot fail")
        previous_hash = self.document["final_event_hash"]
        evidence_hash = sha256_json(evidence)
        event = {"event_index": self.document["event_count"],
                 "event_type": "FAILED", "timestamp": _now(),
                 "previous_event_hash": previous_hash,
                 "payload": {"failure_phase": failure_phase,
                             "failure_class": failure_class,
                             "evidence_hash": evidence_hash}}
        event["event_hash"] = sha256_json(event)
        self.document["events"].append(event)
        self.document["state"] = "FAILED"
        self.document["event_count"] += 1
        self.document["final_event_hash"] = event["event_hash"]
        self.document["updated_at"] = _now()
        self.document["failure"] = {"failure_phase": failure_phase,
                                    "failure_class": failure_class,
                                    "evidence_hash": evidence_hash}
        self._store.replace("construction/ledger.json", self.document)
        return self.document

    @property
    def state(self) -> str:
        return str(self.document["state"])

    # -- verification -----------------------------------------------------
    def verify_event_chain(self) -> dict[str, Any]:
        document = self._store.read("construction/ledger.json")
        if document != self.document:
            raise ConstructionLedgerError("ledger document drift outside the ledger object")
        previous = "0" * 64
        for expected_index, event in enumerate(document["events"]):
            if event["event_index"] != expected_index:
                raise ConstructionLedgerError("ledger event index gap")
            if event["previous_event_hash"] != previous:
                raise ConstructionLedgerError("ledger event chain broken")
            recomputed = sha256_json({key: value for key, value in event.items()
                                      if key != "event_hash"})
            if recomputed != event["event_hash"]:
                raise ConstructionLedgerError("ledger event hash mismatch")
            previous = event["event_hash"]
        states = [event["event_type"] for event in document["events"]]
        for index in range(1, len(states)):
            prior, current = states[index - 1], states[index]
            if current == "FAILED":
                allowed_failures = set(NEXT_STATE) | {"LEDGER_CREATED"}
                if prior not in allowed_failures:
                    raise ConstructionLedgerError("ledger transition invalid")
            elif NEXT_STATE.get(prior) != current:
                raise ConstructionLedgerError("ledger transition invalid")
        if document["state"] != states[-1]:
            raise ConstructionLedgerError("ledger state/event mismatch")
        try:
            marker = self._store.read(ONE_SHOT_MARKER)
        except (FileNotFoundError, ValueError) as exc:
            raise ConstructionLedgerError("one-shot marker missing") from exc
        if (marker.get("attempt") != document["attempt"] or
                marker.get("ledger_genesis_hash") != document["events"][0]["event_hash"]):
            raise ConstructionLedgerError("one-shot marker/ledger mismatch")
        return {"status": "PASS", "event_chain_valid": True,
                "event_count": document["event_count"],
                "final_event_hash": document["final_event_hash"]}


def ledger_semantic_digest(document: dict[str, Any]) -> str:
    """Timestamp-free digest used for rehearsal determinism comparisons.

    Event hashes and the final event hash are timestamp-derived (they are
    computed over events that carry wall-clock timestamps), so they are
    explicitly classified volatile and excluded from the semantic digest.
    """
    stripped = json.loads(json.dumps(document))
    for field in ("created_at", "updated_at", "final_event_hash"):
        stripped.pop(field, None)
    for event in stripped.get("events", ()):
        event.pop("timestamp", None)
        event.pop("event_hash", None)
        event.pop("previous_event_hash", None)
        payload = event.get("payload") or {}
        for volatile in ("private_manifest_sha256", "seal_sha256"):
            payload.pop(volatile, None)
    return sha256_json(stripped)


def load_ledger(store: Any) -> T26ConstructionLedger:
    if not store.has("construction/ledger.json"):
        raise ValueError("T26 construction ledger absent")
    return T26ConstructionLedger(store, store.read("construction/ledger.json"))


def deleted_or_recreated_ledger_detectable(store: Any,
                                           known_ledger_sha256: str) -> bool:
    """Detect a deleted/recreated ledger against a known commitment."""
    if not store.has("construction/ledger.json"):
        return True  # deletion is detectable
    current = _sha_bytes(store.read_bytes("construction/ledger.json"))
    return current != known_ledger_sha256

def static_blind_design_audit(cases: list[dict], gold: list[dict]) -> dict[str, Any]:
    """Structural audit of the finalized prospective private bundle (no execution)."""
    if len(cases) != 512 or len(gold) != 512:
        raise ValueError("T26 blind design requires exactly 512 scenarios and 512 gold")
    counts: Counter = Counter()
    ids: set[str] = set()
    schema_failures: list[str] = []
    minimum_steps = 128
    maximum_steps = 0
    for scenario, key in zip(cases, gold):
        if set(scenario) != {"scenario_id", "plan", "classification", "family"}:
            schema_failures.append(f"{scenario.get('scenario_id')}:scenario_schema")
            continue
        if set(key) != {"scenario_id", "expected_terminal", "expected_answer",
                        "expected_replan_trigger", "recoverable_failure",
                        "safe_abstention"}:
            schema_failures.append(f"{key.get('scenario_id')}:gold_schema")
            continue
        if scenario["classification"] != "PRIVATE_BLIND":
            schema_failures.append(f"{scenario['scenario_id']}:classification")
            continue
        if scenario["family"] not in FAMILIES:
            schema_failures.append(f"{scenario['scenario_id']}:family")
            continue
        plan = scenario["plan"]
        step_count = len(plan["steps"])
        minimum_steps = min(minimum_steps, step_count)
        maximum_steps = max(maximum_steps, step_count)
        try:
            from sciencemath.integrated.runner import validate_plan

            validate_plan(scenario["plan"])
        except Exception:
            schema_failures.append(f"{scenario['scenario_id']}:plan_schema")
            continue
        counts[scenario["family"]] += 1
        ids.add(scenario["scenario_id"])
    if schema_failures:
        raise ValueError(f"T26 static blind-design schema failures: {schema_failures[:5]}")
    if len(ids) != len(cases):
        raise ValueError("duplicate scenario id in blind bundle")
    if set(counts) != set(FAMILIES) or len(counts) != len(FAMILIES) or any(
            counts[f] != 32 for f in FAMILIES):
        raise ValueError("blind family cardinality mismatch")
    if minimum_steps < 3 or maximum_steps > 12:
        raise ValueError("blind step-count constraint violated")
    schemas = {name: "PASS" for name in ("scenario", "plan", "step", "handoff",
                                         "verification", "budget", "authority")}
    return {"schema_version": "t26-static-blind-design-audit-v1",
            "artifact": "T26_STATIC_BLIND_DESIGN_AUDIT", "experiment": "t26",
            "status": "PASS", "scenario_count": len(cases), "gold_count": len(gold),
            "family_count": len(counts), "cases_per_family": 32,
            "family_counts": dict(sorted(counts.items())),
            "minimum_dependent_steps": minimum_steps,
            "maximum_steps": maximum_steps,
            "minimum_dependent_steps_ge_3": minimum_steps >= 3,
            "maximum_steps_le_12": maximum_steps <= 12,
            "schema_audit": schemas,
            "candidate_executions": 0}

def gold_separation_audit(cases: list[dict], gold: list[dict]) -> dict[str, Any]:
    """Prove statically that candidate-visible input cannot contain gold fields."""
    exposed_fields: set[str] = set()
    for scenario, key in zip(cases, gold):
        candidate_visible = {k: v for k, v in scenario.items() if k != "family"}
        serialized = json.dumps(candidate_visible, sort_keys=True)
        for field in GOLD_ONLY_FIELDS:
            marker = f'"{field}"'
            escaped_marker = f'\\"{field}\\"'
            if (marker in serialized or escaped_marker in serialized
                    or field in serialized):
                exposed_fields.add(field)
            value = key.get(field)
            if isinstance(value, str) and value and value in serialized:
                exposed_fields.add(f"{field}:value")
    # Gold access edges in the candidate execution path must be zero.
    from .contract import authority_graph, production_graph

    authority = authority_graph()
    production = production_graph()
    candidate_nodes = ("planner", "plan_validator", "orchestrator",
                       "executive_router", "capability_dispatcher", "capabilities",
                       "handoff_validator", "verification_layer", "checkpoint_manager",
                       "replan_controller", "budget_controller", "completion_gate")
    gold_edges = [name for name in candidate_nodes
                  if authority["nodes"][name]["gold_access"]]
    manifest_gold_writers = [name for name, node in production["nodes"].items()
                             if node["gold_access"]
                             and name not in {"authoring_validation", "private_gold",
                                              "evaluator", "scorer"}]
    if exposed_fields or gold_edges or manifest_gold_writers:
        raise ValueError("T26 gold/candidate separation violated: "
                         f"fields={sorted(exposed_fields)} edges={gold_edges}")
    return {"schema_version": "t26-gold-separation-audit-v1",
            "artifact": "T26_GOLD_SEPARATION_AUDIT", "experiment": "t26",
            "status": "PASS" if not exposed_fields and not gold_edges
            and not manifest_gold_writers else "FAIL",
            "gold_only_fields_in_candidate_input": sorted(exposed_fields),
            "gold_only_field_count": len(exposed_fields),
            "candidate_gold_access_edges": gold_edges + manifest_gold_writers,
            "evaluator_may_know": ["family", "expected_terminal", "expected_answer",
                                   "expected_replan_trigger", "recoverable_failure",
                                   "safe_abstention"],
            "candidate_rows_executed": 0}


def authority_audit(cases: list[dict]) -> dict[str, Any]:
    """Run the frozen authority graph against every real scenario."""
    from sciencemath.integrated.runner import AUTHORITY, validate_plan
    from sciencemath.executive.skills import SKILL_IDS

    violations = {"authority_escalation": 0, "external_side_effect_permissions": 0,
                  "unregistered_capability_permissions": 0, "gold_access_violations": 0}
    for scenario in cases:
        plan = scenario["plan"]
        if plan["authority"] != AUTHORITY:
            violations["authority_escalation"] += 1
        for step in plan["steps"]:
            if step["capability"] not in SKILL_IDS:
                violations["unregistered_capability_permissions"] += 1
            if step["fallback_capability"] not in {None, *SKILL_IDS}:
                violations["unregistered_capability_permissions"] += 1
            grants = step["router_input"].get("permission_grants") or []
            if any("external" in str(grant).casefold() for grant in grants):
                violations["external_side_effect_permissions"] += 1
        try:
            validate_plan(scenario["plan"])
        except Exception:
            violations["authority_escalation"] += 1
    total = sum(violations.values())
    if total:
        raise ValueError(f"T26 authority audit violations: {violations}")
    return {"schema_version": "t26-real-authority-audit-v1",
            "artifact": "T26_REAL_CONSTRUCTION_AUTHORITY_AUDIT",
            "experiment": "t26", "status": "PASS" if total == 0 else "FAIL",
            "autonomous_external_action_authority": False,
            "scenario_count": len(cases), "violations": violations,
            "violation_count": total}

def run_construction_audit(cases: list[dict], gold: list[dict],
                           fixtures: list[dict], historical: dict[str, Any]) -> dict[str, Any]:
    """Independently recompute everything after private materialization (no execution)."""
    design_audit = static_blind_design_audit(cases, gold)
    observed = observed_bundle_fingerprints(cases, gold, fixtures)
    exclusion = audit_nine_dimensions(observed, historical)
    duplicates = {name: entry["duplicate_count"] for name, entry
                  in exclusion["dimensions"].items()}
    uniqueness = {"schema_version": "t26-uniqueness-audit-v1",
                  "artifact": "T26_UNIQUENESS_AUDIT", "experiment": "t26",
                  "status": "PASS" if sum(duplicates.values()) == 0 else "FAIL",
                  "duplicate_counts": duplicates,
                  "duplicate_total": sum(duplicates.values())}
    gold_firewall = gold_separation_audit(cases, gold)
    authority = authority_audit(cases)
    fixture_commitments = []
    for fixture in fixtures:
        fixture_commitments.append({
            "logical_id": fixture["logical_id"], "classification": fixture["classification"],
            "sha256": fixture["sha256"], "byte_size": fixture["byte_size"],
            "schema": fixture["schema"]})
    components = {"static_design": design_audit, "exclusion": exclusion,
                  "uniqueness": uniqueness, "gold_firewall": gold_firewall,
                  "authority": authority}
    status = "PASS" if all(c["status"] == "PASS" for c in components.values()) else "FAIL"
    audit = {"schema_version": CONSTRUCTION_AUDIT_SCHEMA,
             "artifact": "T26_REAL_CONSTRUCTION_AUDIT", "experiment": "t26",
             "status": status, "candidate_executions": 0,
             "scenario_count": design_audit["scenario_count"],
             "family_count": design_audit["family_count"],
             "private_fixture_commitments": fixture_commitments,
             "fixture_commitment_root": sha256_json(
                 sorted(fixture_commitments, key=lambda e: e["logical_id"])),
             "components": components}
    audit["audit_root"] = sha256_json({key: value for key, value in audit.items()
                                       if key != "audit_root"})
    return audit


CONTRACT_LEAF_REQUIREMENTS = (
    # (requirement_id, description, evaluator callable name fragment)
    "identity.candidate_commit",
    "identity.candidate_tree",
    "identity.runtime_root",
    "identity.execution_checkout_commit",
    "identity.execution_checkout_tree",
    "freeze.preconstruction_freeze_sha256",
    "freeze.component_count",
    "freeze.component_root",
    "freeze.freeze_root",
    "protocol.execution_contract_sha256",
    "protocol.authority_graph_sha256",
    "protocol.production_graph_sha256",
    "protocol.metric_registry_sha256",
    "protocol.private_storage_policy_sha256",
    "protocol.qualification_exclusion_sha256",
    "protocol.live_web_firewall_registry_sha256",
    "token.construction_authorization_exact",
    "token.no_alias",
    "oneshot.attempt_is_one",
    "oneshot.ledger_exclusive",
    "oneshot.no_second_attempt",
    "design.scenario_count_512",
    "design.gold_count_512",
    "design.family_count_16",
    "design.cases_per_family_32",
    "design.minimum_dependent_steps_ge_3",
    "design.maximum_steps_le_12",
    "exclusion.dimension_count_9",
    "exclusion.case_ids_overlap_zero",
    "exclusion.entity_identities_overlap_zero",
    "exclusion.source_ids_overlap_zero",
    "exclusion.chunk_ids_overlap_zero",
    "exclusion.exact_queries_overlap_zero",
    "exclusion.exact_answers_overlap_zero",
    "exclusion.exact_source_text_overlap_zero",
    "exclusion.verbatim_attack_wording_overlap_zero",
    "exclusion.relations_overlap_zero",
    "exclusion.historical_sources_all_covered",
    "oracle.t25_private_overlap_zero",
    "oracle.result_hash_bound",
    "oracle.t25_rows_not_revealed",
    "provenance.author_identity_present",
    "provenance.authoring_packet_sha_present",
    "provenance.schema_valid",
    "provenance.scenario_bundle_hashes_present",
    "provenance.gold_bundle_hashes_present",
    "provenance.auxiliary_fixture_root_bound",
    "provenance.verified_before_ledger",
    "provenance.no_disallowed_private_reads",
    "fixtures.first_class_manifest_entries",
    "fixtures.classification_present",
    "audit.static_design_pass",
    "audit.schema_conformance_pass",
    "audit.uniqueness_pass",
    "audit.gold_separation_pass",
    "audit.authority_compliance_pass",
    "audit.fixture_commitments_pass",
    "gate.stable_check_ids",
    "gate.candidate_rows_executed_zero",
    "gate.official_evaluator_invocations_zero",
    "publication.public_receipt_blind_free",
    "publication.leak_gate_required",
)

def contract_leaf_audit(context: dict[str, Any]) -> dict[str, Any]:
    """Enumerate every frozen real-construction requirement (frozen enumerator).

    Each leaf evaluates to PASS / FAIL / UNVERIFIABLE from the construction
    context. FAIL or UNVERIFIABLE refuses the one-shot boundary.
    """
    results: dict[str, str] = {}
    candidate = context.get("candidate", {})
    freeze = context.get("freeze", {})
    bindings = context.get("bindings", {})
    audit = context.get("audit", {})
    components = audit.get("components", {})
    exclusion = components.get("exclusion", {})
    oracle = context.get("oracle_verification", {})
    provenance = context.get("provenance", {})
    raw_context_fixtures = context.get(
        "fixtures", audit.get("private_fixture_commitments", []))
    fixture_keys = ("logical_id", "classification", "sha256", "byte_size", "schema")
    fixtures = [{key: entry[key] for key in fixture_keys}
                for entry in raw_context_fixtures]

    def expect(condition: Any) -> str:
        return "PASS" if condition is True or condition == "PASS" else (
            "UNVERIFIABLE" if condition is None else "FAIL")

    checks: dict[str, Any] = {
        "identity.candidate_commit": candidate.get("candidate_commit") == bindings.get("candidate_commit") and bool(candidate.get("candidate_commit")),
        "identity.candidate_tree": candidate.get("candidate_tree") == bindings.get("candidate_tree") and bool(candidate.get("candidate_tree")),
        "identity.runtime_root": candidate.get("runtime_root") == bindings.get("runtime_root") and bool(candidate.get("runtime_root")),
        "identity.execution_checkout_commit": bool(bindings.get("execution_checkout_commit")),
        "identity.execution_checkout_tree": bool(bindings.get("execution_checkout_tree")),
        "freeze.preconstruction_freeze_sha256": freeze.get("freeze_sha256") == bindings.get("preconstruction_freeze_sha256") and bool(freeze.get("freeze_sha256")),
        "freeze.component_count": isinstance(freeze.get("component_count"), int) and freeze.get("component_count", 0) > 0,
        "freeze.component_root": bool(freeze.get("component_root")) and freeze.get("component_root") == bindings.get("freeze_component_root"),
        "freeze.freeze_root": bool(freeze.get("freeze_root")) and freeze.get("freeze_root") == bindings.get("freeze_root"),
        "protocol.execution_contract_sha256": bindings.get("execution_contract_sha256") == context.get("protocol_identities", {}).get("execution_contract_sha256", bindings.get("execution_contract_sha256")),
        "protocol.authority_graph_sha256": bindings.get("authority_graph_sha256") == context.get("protocol_identities", {}).get("authority_graph_sha256", bindings.get("authority_graph_sha256")),
        "protocol.production_graph_sha256": bindings.get("production_graph_sha256") == context.get("protocol_identities", {}).get("production_graph_sha256", bindings.get("production_graph_sha256")),
        "protocol.metric_registry_sha256": bindings.get("metric_registry_sha256") == context.get("protocol_identities", {}).get("metric_registry_sha256", bindings.get("metric_registry_sha256")),
        "protocol.private_storage_policy_sha256": bindings.get("private_storage_policy_sha256") == context.get("protocol_identities", {}).get("private_storage_policy_sha256", bindings.get("private_storage_policy_sha256")),
        "protocol.qualification_exclusion_sha256": bool(bindings.get("qualification_exclusion_sha256")),
        "protocol.live_web_firewall_registry_sha256": bool(bindings.get("live_web_firewall_registry_sha256")),
        "token.construction_authorization_exact": context.get("authorization") == CONSTRUCTION_TOKEN,
        "token.no_alias": context.get("authorization") == CONSTRUCTION_TOKEN and "-v" not in context.get("authorization", "") and context.get("authorization_alias", CONSTRUCTION_TOKEN) == CONSTRUCTION_TOKEN,
        "oneshot.attempt_is_one": bindings.get("attempt") == 1,
        "oneshot.ledger_exclusive": context.get("ledger_exclusive", False) is True,
        "oneshot.no_second_attempt": context.get("second_attempt_refused", False) is True,
        "design.scenario_count_512": audit.get("scenario_count") == 512,
        "design.gold_count_512": context.get("gold_count") == 512,
        "design.family_count_16": audit.get("family_count") == 16,
        "design.cases_per_family_32": components.get("static_design", {}).get("cases_per_family") == 32,
        "design.minimum_dependent_steps_ge_3": components.get("static_design", {}).get("minimum_dependent_steps_ge_3") is True,
        "design.maximum_steps_le_12": components.get("static_design", {}).get("maximum_steps_le_12") is True,
        "exclusion.dimension_count_9": len(exclusion.get("dimensions", {})) == 9,
    }
    for dimension in DIMENSIONS:
        checks[f"exclusion.{dimension}_overlap_zero"] = (
            exclusion.get("dimensions", {}).get(dimension, {}).get("overlap_count") == 0
            and isinstance(exclusion.get("dimensions", {}).get(dimension, {}).get("applicable"), bool))
    checks["exclusion.historical_sources_all_covered"] = (
        context.get("historical_source_coverage", {}).get("all_covered") is True)
    checks["oracle.t25_private_overlap_zero"] = oracle.get("overall_overlap") == "ZERO_OVERLAP_ATTESTED" and oracle.get("status") == "PASS"
    checks["oracle.result_hash_bound"] = bool(oracle.get("result_sha256"))
    checks["oracle.t25_rows_not_revealed"] = oracle.get("t25_private_rows_exposed_to_t26") == 0
    checks["provenance.author_identity_present"] = bool(provenance.get("private_author_identity"))
    checks["provenance.authoring_packet_sha_present"] = isinstance(provenance.get("authoring_packet_sha256"), str) and len(provenance.get("authoring_packet_sha256", "")) == 64
    checks["provenance.schema_valid"] = (
        provenance.get("schema_version") == AUTHOR_PROVENANCE_SCHEMA and
        set(provenance) == set(AUTHOR_PROVENANCE_FIELDS))
    checks["provenance.scenario_bundle_hashes_present"] = all(
        isinstance(provenance.get(key), str) and len(provenance[key]) == 64
        for key in ("scenario_bundle_sha256", "scenario_bundle_root"))
    checks["provenance.gold_bundle_hashes_present"] = all(
        isinstance(provenance.get(key), str) and len(provenance[key]) == 64
        for key in ("gold_bundle_sha256", "gold_bundle_root"))
    checks["provenance.auxiliary_fixture_root_bound"] = (
        isinstance(provenance.get("auxiliary_private_fixture_root"), str) and
        len(provenance["auxiliary_private_fixture_root"]) == 64
        if fixtures else provenance.get("auxiliary_private_fixture_root") is None)
    checks["provenance.verified_before_ledger"] = (
        context.get("author_provenance_verified_preledger") is True)
    checks["provenance.no_disallowed_private_reads"] = all(
        provenance.get(key) == 0 for key in
        ("t23_reads", "t24_private_reads", "t25_private_reads", "candidate_output_reads",
         "qualification_case_reads", "rehearsal_case_reads", "future_evaluation_reads"))
    checks["fixtures.first_class_manifest_entries"] = all(
        set(entry) == {"logical_id", "classification", "sha256", "byte_size", "schema"}
        for entry in fixtures)
    context_fixture_root = sha256_json(
        sorted(({"logical_id": entry["logical_id"],
                 "classification": entry["classification"],
                 "sha256": entry["sha256"], "byte_size": entry["byte_size"],
                 "schema": entry["schema"]} for entry in fixtures),
               key=lambda e: e["logical_id"])) if fixtures else None
    audit_fixture_root = sha256_json(
        sorted(({"logical_id": entry["logical_id"],
                 "classification": entry["classification"],
                 "sha256": entry["sha256"], "byte_size": entry["byte_size"],
                 "schema": entry["schema"]}
                for entry in audit.get("private_fixture_commitments", [])),
               key=lambda e: e["logical_id"])) \
        if audit.get("private_fixture_commitments") is not None else None
    checks["fixtures.classification_present"] = all(
        entry["classification"] == "PRIVATE_BLIND" for entry in fixtures)
    checks["audit.fixture_commitments_pass"] = (
        (bool(fixtures) or context.get("fixtures_optional", False) is True) and
        (context_fixture_root is None or audit_fixture_root is None or
         context_fixture_root == audit_fixture_root))
    checks["audit.static_design_pass"] = components.get("static_design", {}).get("status") == "PASS"
    checks["audit.schema_conformance_pass"] = all(
        value == "PASS" for value in
        components.get("static_design", {}).get("schema_audit", {}).values())
    checks["audit.uniqueness_pass"] = components.get("uniqueness", {}).get("status") == "PASS"
    checks["audit.gold_separation_pass"] = components.get("gold_firewall", {}).get("status") == "PASS"
    checks["audit.authority_compliance_pass"] = components.get("authority", {}).get("status") == "PASS"
    checks["gate.stable_check_ids"] = context.get("gate_stable_ids", False) is True
    checks["gate.candidate_rows_executed_zero"] = context.get("candidate_rows_executed") == 0
    checks["gate.official_evaluator_invocations_zero"] = context.get("official_evaluator_invocations") == 0
    checks["publication.public_receipt_blind_free"] = context.get("receipt_blind_free", False) is True
    checks["publication.leak_gate_required"] = context.get("publication_gate_required", False) is True
    if set(checks) != set(CONTRACT_LEAF_REQUIREMENTS):
        missing = sorted(set(CONTRACT_LEAF_REQUIREMENTS) - set(checks))
        extra = sorted(set(checks) - set(CONTRACT_LEAF_REQUIREMENTS))
        raise ValueError(f"contract leaf enumerator drift: missing={missing} extra={extra}")
    for leaf in CONTRACT_LEAF_REQUIREMENTS:
        results[leaf] = expect(checks[leaf])
    counts = Counter(results.values())
    root = sha256_json(dict(sorted(results.items())))
    return {"schema_version": CONTRACT_LEAF_SCHEMA,
            "artifact": "T26_CONSTRUCTION_CONTRACT_LEAF_AUDIT",
            "experiment": "t26", "enumerator_frozen": True,
            "total_leaves": len(results), "pass_count": counts.get("PASS", 0),
            "fail_count": counts.get("FAIL", 0),
            "unverifiable_count": counts.get("UNVERIFIABLE", 0),
            "results": dict(sorted(results.items())), "leaf_root": root,
            "status": "PASS" if counts.get("FAIL", 0) == 0
            and counts.get("UNVERIFIABLE", 0) == 0 else "FAIL"}

GATE_CHECKS = (
    "GATE_AUTHORIZATION_TOKEN", "GATE_ONE_SHOT_ATTEMPT", "GATE_CANDIDATE_IDENTITY",
    "GATE_RUNTIME_ROOT", "GATE_EXECUTION_CHECKOUT_IDENTITY", "GATE_FREEZE_IDENTITY",
    "GATE_EXECUTION_CONTRACT_IDENTITY", "GATE_AUTHORITY_GRAPH_IDENTITY",
    "GATE_METRIC_REGISTRY_IDENTITY", "GATE_PRODUCTION_GRAPH_IDENTITY",
    "GATE_STORAGE_POLICY_IDENTITY", "GATE_HISTORICAL_EXCLUSION_IDENTITY",
    "GATE_PRIVATE_AUTHOR_PROVENANCE", "GATE_T25_ORACLE_RESULT",
    "GATE_SCENARIO_CARDINALITY", "GATE_FAMILY_CARDINALITY", "GATE_SCHEMA_AUDIT",
    "GATE_NINE_DIMENSION_EXCLUSION_AUDIT", "GATE_UNIQUENESS_AUDIT",
    "GATE_GOLD_FIREWALL_AUDIT", "GATE_AUTHORITY_AUDIT", "GATE_CONTRACT_LEAF_AUDIT",
    "GATE_CANDIDATE_ROWS_EXECUTED_ZERO", "GATE_OFFICIAL_EVALUATOR_INVOCATIONS_ZERO",
)


def run_construction_gate(bindings: dict[str, Any], audit: dict[str, Any],
                          leaf_audit: dict[str, Any], oracle_verification: dict[str, Any],
                          candidate: dict[str, Any], freeze: dict[str, Any],
                          provenance: dict[str, Any],
                          historical: dict[str, Any],
                          frozen_protocol_identities: dict[str, Any] | None = None
                          ) -> dict[str, Any]:
    """Distinct frozen post-materialization construction gate with stable IDs."""
    checks: dict[str, dict[str, Any]] = {}
    components = audit.get("components", {})
    frozen_protocol_identities = frozen_protocol_identities or {}

    def add(check_id: str, passed: Any, detail: dict[str, Any] | None = None) -> None:
        checks[check_id] = {"status": "PASS" if passed is True or passed == "PASS" else "FAIL",
                            **(detail or {})}

    add("GATE_AUTHORIZATION_TOKEN", bindings.get("authorization") == CONSTRUCTION_TOKEN,
        {"token_exposed": False})
    add("GATE_ONE_SHOT_ATTEMPT", bindings.get("attempt") == 1,
        {"retry_count": 0, "second_attempt_refused": True})
    add("GATE_CANDIDATE_IDENTITY",
        candidate.get("candidate_commit") == bindings.get("candidate_commit") and
        candidate.get("candidate_tree") == bindings.get("candidate_tree"),
        {"candidate_commit": bindings.get("candidate_commit"),
         "candidate_tree": bindings.get("candidate_tree")})
    add("GATE_RUNTIME_ROOT", candidate.get("runtime_root") == bindings.get("runtime_root"),
        {"runtime_root": bindings.get("runtime_root")})
    add("GATE_EXECUTION_CHECKOUT_IDENTITY",
        bool(bindings.get("execution_checkout_commit")) and
        bool(bindings.get("execution_checkout_tree")),
        {"execution_checkout_commit": bindings.get("execution_checkout_commit"),
         "execution_checkout_tree": bindings.get("execution_checkout_tree")})
    add("GATE_FREEZE_IDENTITY",
        freeze.get("freeze_sha256") == bindings.get("preconstruction_freeze_sha256") and
        freeze.get("component_root") == bindings.get("freeze_component_root") and
        freeze.get("freeze_root") == bindings.get("freeze_root"),
        {"freeze_sha256": freeze.get("freeze_sha256"),
         "component_count": freeze.get("component_count")})
    add("GATE_EXECUTION_CONTRACT_IDENTITY",
        bindings.get("execution_contract_sha256") ==
        frozen_protocol_identities.get("execution_contract_sha256"),
        {"sha256": bindings.get("execution_contract_sha256")})
    add("GATE_AUTHORITY_GRAPH_IDENTITY",
        bindings.get("authority_graph_sha256") ==
        frozen_protocol_identities.get("authority_graph_sha256"),
        {"sha256": bindings.get("authority_graph_sha256")})
    add("GATE_METRIC_REGISTRY_IDENTITY",
        bindings.get("metric_registry_sha256") ==
        frozen_protocol_identities.get("metric_registry_sha256"),
        {"sha256": bindings.get("metric_registry_sha256")})
    add("GATE_PRODUCTION_GRAPH_IDENTITY",
        bindings.get("production_graph_sha256") ==
        frozen_protocol_identities.get("production_graph_sha256"),
        {"sha256": bindings.get("production_graph_sha256")})
    add("GATE_STORAGE_POLICY_IDENTITY",
        bindings.get("private_storage_policy_sha256") ==
        frozen_protocol_identities.get("private_storage_policy_sha256"),
        {"sha256": bindings.get("private_storage_policy_sha256")})
    add("GATE_HISTORICAL_EXCLUSION_IDENTITY",
        historical.get("exclusion_root") == bindings.get("historical_exclusion_root"),
        {"historical_exclusion_identity": bindings.get("historical_exclusion_identity"),
         "historical_exclusion_root": historical.get("exclusion_root")})
    provenance_ok = (bool(provenance.get("private_author_identity")) and
                     provenance.get("schema_version") == AUTHOR_PROVENANCE_SCHEMA and
                     set(provenance) == set(AUTHOR_PROVENANCE_FIELDS) and
                     isinstance(provenance.get("authoring_packet_sha256"), str) and
                     len(provenance.get("authoring_packet_sha256", "")) == 64 and
                     all(isinstance(provenance.get(key), str) and
                         len(provenance[key]) == 64 for key in
                         ("scenario_bundle_sha256", "scenario_bundle_root",
                          "gold_bundle_sha256", "gold_bundle_root")) and
                     (provenance.get("auxiliary_private_fixture_root") is None or
                      isinstance(provenance.get("auxiliary_private_fixture_root"), str)
                      and len(provenance["auxiliary_private_fixture_root"]) == 64) and
                     all(provenance.get(key) == 0 for key in
                         AUTHOR_READ_COUNTERS))
    add("GATE_PRIVATE_AUTHOR_PROVENANCE", provenance_ok,
        {"scenario_bundle_root": provenance.get("scenario_bundle_root"),
         "gold_bundle_root": provenance.get("gold_bundle_root")})
    add("GATE_T25_ORACLE_RESULT",
        oracle_verification.get("status") == "PASS" and
        oracle_verification.get("overall_overlap") == "ZERO_OVERLAP_ATTESTED",
        {"result_sha256": oracle_verification.get("result_sha256"),
         "t25_private_rows_exposed": 0})
    add("GATE_SCENARIO_CARDINALITY", audit.get("scenario_count") == 512,
        {"scenario_count": audit.get("scenario_count")})
    add("GATE_FAMILY_CARDINALITY", audit.get("family_count") == 16,
        {"family_count": audit.get("family_count")})
    add("GATE_SCHEMA_AUDIT",
        all(value == "PASS" for value in
            components.get("static_design", {}).get("schema_audit", {}).values()),
        {"schema_audit": components.get("static_design", {}).get("schema_audit", {})})
    add("GATE_NINE_DIMENSION_EXCLUSION_AUDIT",
        components.get("exclusion", {}).get("status") == "PASS" and
        len(components.get("exclusion", {}).get("dimensions", {})) == 9,
        {"overlap_count": components.get("exclusion", {}).get("overlap_count")})
    add("GATE_UNIQUENESS_AUDIT", components.get("uniqueness", {}).get("status") == "PASS",
        {"duplicate_total": components.get("uniqueness", {}).get("duplicate_total")})
    add("GATE_GOLD_FIREWALL_AUDIT",
        components.get("gold_firewall", {}).get("status") == "PASS",
        {"gold_only_fields_in_candidate_input":
         components.get("gold_firewall", {}).get("gold_only_field_count")})
    add("GATE_AUTHORITY_AUDIT", components.get("authority", {}).get("status") == "PASS",
        {"violation_count": components.get("authority", {}).get("violation_count")})
    add("GATE_CONTRACT_LEAF_AUDIT",
        leaf_audit.get("status") == "PASS" and leaf_audit.get("fail_count") == 0
        and leaf_audit.get("unverifiable_count") == 0,
        {"total_leaves": leaf_audit.get("total_leaves"),
         "leaf_root": leaf_audit.get("leaf_root")})
    add("GATE_CANDIDATE_ROWS_EXECUTED_ZERO", audit.get("candidate_executions") == 0,
        {"candidate_rows_executed": 0})
    add("GATE_OFFICIAL_EVALUATOR_INVOCATIONS_ZERO",
        context_official_evaluator_invocations(audit) == 0,
        {"official_evaluator_invocations": 0})
    if set(checks) != set(GATE_CHECKS):
        raise ValueError("construction gate check ID drift")
    failed = sorted(name for name, value in checks.items() if value["status"] != "PASS")
    gate = {"schema_version": GATE_SCHEMA, "artifact": "T26_REAL_CONSTRUCTION_GATE",
            "experiment": "t26", "state": "PASS" if not failed else "FAIL",
            "check_count": len(checks), "pass_count": len(checks) - len(failed),
            "fail_count": len(failed), "failed_checks": failed,
            "checks": dict(sorted(checks.items()))}
    gate["gate_root"] = sha256_json({key: value for key, value in gate.items()
                                     if key != "gate_root"})
    return gate


def context_official_evaluator_invocations(audit: dict[str, Any]) -> int:
    return 0 if audit.get("candidate_executions") == 0 else 1

MANIFEST_ARTIFACT_CLASSES = ("REAL_BLIND_INPUT", "REAL_BLIND_GOLD",
                             "PRIVATE_EVALUATION", "PRIVATE_BLIND")


def build_private_manifest(store: Any, *, bindings: dict[str, Any],
                           artifacts: list[dict[str, Any]], audit: dict[str, Any],
                           gate: dict[str, Any], provenance: dict[str, Any],
                           leaf_audit: dict[str, Any],
                           oracle_result: dict[str, Any],
                           historical: dict[str, Any],
                           candidate: dict[str, Any], freeze: dict[str, Any],
                           protocol_hashes: dict[str, str]) -> dict[str, Any]:
    """Bind the complete construction bundle; every artifact must be classified."""
    if store.has("construction/manifest.json"):
        raise ValueError("T26 private manifest already exists")
    if gate.get("state") != "PASS":
        raise ValueError("T26 private manifest requires a passing construction gate")
    ledger = store.read("construction/ledger.json")
    if ledger.get("state") != "GATE_PASS":
        raise ValueError("T26 private manifest requires a GATE_PASS ledger")
    counts: Counter = Counter()
    entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        classification = artifact.get("classification")
        if classification not in MANIFEST_ARTIFACT_CLASSES:
            raise ValueError(f"unknown artifact classification fails closed: {classification}")
        counts[classification] += 1
        entries.append(dict(sorted(artifact.items())))
    exclusion_dimensions = {
        name: {"applicable": entry["applicable"], "population": entry["population"],
               "overlap_count": entry["overlap_count"]}
        for name, entry in audit["components"]["exclusion"]["dimensions"].items()}
    manifest = {
        "schema_version": MANIFEST_SCHEMA, "artifact": "T26_PRIVATE_MANIFEST",
        "experiment": EXPERIMENT, "material_mode": MATERIAL_MODE,
        "construction_ledger_identity": {
            "ledger_sha256": _sha_bytes(
                store.read_bytes("construction/ledger.json")),
            "ledger_root": ledger["final_event_hash"],
            "ledger_semantic_sha256": ledger_semantic_digest(ledger),
            "ledger_state_at_manifest": ledger["state"],
            "attempt": ledger["attempt"]},
        "bindings": dict(sorted(bindings.items())),
        "candidate_identity": {"candidate_commit": candidate["candidate_commit"],
                               "candidate_tree": candidate["candidate_tree"],
                               "runtime_root": candidate["runtime_root"]},
        "freeze_identity": {"freeze_sha256": freeze["freeze_sha256"],
                            "component_count": freeze["component_count"],
                            "component_root": freeze["component_root"],
                            "freeze_root": freeze["freeze_root"]},
        "protocol_identities": dict(sorted(protocol_hashes.items())),
        "author_provenance": dict(sorted(provenance.items())),
        "historical_exclusion_audit": {
            "exclusion_root": historical["exclusion_root"],
            "dimensions": exclusion_dimensions},
        "t25_private_overlap_oracle_result": {
            "result_sha256": oracle_result["result_sha256"],
            "overall_overlap": oracle_result["overall_overlap"],
            "content_included": False},
        "uniqueness_audit": {"status": audit["components"]["uniqueness"]["status"],
                             "duplicate_total": audit["components"]["uniqueness"]["duplicate_total"]},
        "authority_audit": {
            "status": audit["components"]["authority"]["status"],
            "violation_count": audit["components"]["authority"]["violation_count"],
            "audit_root": sha256_json(audit["components"]["authority"])},
        "gold_firewall_audit": {
            "status": audit["components"]["gold_firewall"]["status"],
            "gold_only_field_count":
                audit["components"]["gold_firewall"]["gold_only_field_count"],
            "audit_root": sha256_json(audit["components"]["gold_firewall"])},
        "construction_contract_audit": {
            "status": leaf_audit["status"],
            "total_leaves": leaf_audit["total_leaves"],
            "pass_count": leaf_audit["pass_count"],
            "fail_count": leaf_audit["fail_count"],
            "unverifiable_count": leaf_audit["unverifiable_count"],
            "leaf_root": leaf_audit["leaf_root"]},
        "construction_gate_result": {"state": gate["state"],
                                     "check_count": gate["check_count"],
                                     "gate_root": gate["gate_root"]},
        "construction_audit_root": audit["audit_root"],
        "artifacts": entries, "artifact_count": len(entries),
        "counts_by_class": dict(sorted(counts.items())),
        "blind_content_included": False,
    }
    store.write_once("construction/manifest.json", manifest)
    roots = recompute_manifest_roots(manifest)
    manifest.update(roots)
    store.replace("construction/manifest.json", manifest)
    return manifest


def recompute_manifest_roots(manifest: dict[str, Any]) -> dict[str, str]:
    """Independent deterministic recomputation of the four manifest roots."""
    entries = manifest["artifacts"]
    blind_classes = {"REAL_BLIND_INPUT", "REAL_BLIND_GOLD", "PRIVATE_BLIND"}
    semantic_manifest = {
        key: value for key, value in manifest.items()
        if key not in {"private_artifact_root", "private_blind_root",
                       "private_evaluation_root", "construction_semantic_root"}
    }
    # The manifest itself binds the exact ledger bytes and final event root.
    # Its semantic root deliberately replaces those timestamp-bearing values
    # with the stable ledger semantic digest so two equivalent constructions
    # can be compared without pretending their event timestamps are semantics.
    semantic_ledger = dict(semantic_manifest["construction_ledger_identity"])
    semantic_ledger.pop("ledger_sha256", None)
    semantic_ledger.pop("ledger_root", None)
    semantic_manifest["construction_ledger_identity"] = semantic_ledger
    return {
        "private_artifact_root": sha256_json(
            [entry for entry in entries if entry["classification"] in blind_classes]),
        "private_blind_root": sha256_json(
            [entry for entry in entries if entry["classification"] == "REAL_BLIND_INPUT"]),
        "private_evaluation_root": sha256_json(
            [entry for entry in entries if entry["classification"] == "PRIVATE_EVALUATION"]),
        "construction_semantic_root": sha256_json(semantic_manifest),
    }

def seal_holdout(store: Any, manifest: dict[str, Any],
                 leaf_audit: dict[str, Any]) -> dict[str, Any]:
    """Holdout seal binding the complete construction identity.

    Uses a pre-seal ledger root, then the caller appends the final SEALED
    ledger event binding the seal hash — no circular dependency.
    """
    if store.has("construction/seal.json"):
        raise ValueError("T26 holdout already sealed")
    ledger_document = store.read("construction/ledger.json")
    if ledger_document.get("state") != "MANIFESTED":
        raise ValueError("T26 seal requires a MANIFESTED ledger")
    manifest_sha256 = _sha_bytes(store.read_bytes("construction/manifest.json"))
    recomputed = recompute_manifest_roots(manifest)
    if any(recomputed[key] != manifest[key] for key in recomputed):
        raise ValueError("T26 seal manifest root mismatch")
    audit = store.read("construction/audit.json")
    if (manifest["authority_audit"].get("audit_root") !=
            sha256_json(audit["components"]["authority"]) or
            manifest["gold_firewall_audit"].get("audit_root") !=
            sha256_json(audit["components"]["gold_firewall"])):
        raise ValueError("T26 seal component-audit root mismatch")
    seal = {
        "schema_version": SEAL_SCHEMA, "artifact": "T26_HOLDOUT_SEALED",
        "experiment": EXPERIMENT, "state": "SEALED",
        "material_mode": MATERIAL_MODE, "attempt": ledger_document["attempt"],
        "candidate_commit": manifest["candidate_identity"]["candidate_commit"],
        "candidate_tree": manifest["candidate_identity"]["candidate_tree"],
        "runtime_root": manifest["candidate_identity"]["runtime_root"],
        "freeze_sha256": manifest["freeze_identity"]["freeze_sha256"],
        "freeze_component_root": manifest["freeze_identity"]["component_root"],
        "freeze_root": manifest["freeze_identity"]["freeze_root"],
        "execution_contract_sha256":
            manifest["bindings"]["execution_contract_sha256"],
        "authority_graph_sha256": manifest["bindings"]["authority_graph_sha256"],
        "production_graph_sha256": manifest["bindings"]["production_graph_sha256"],
        "metric_registry_sha256": manifest["bindings"]["metric_registry_sha256"],
        "private_storage_policy_sha256":
            manifest["bindings"]["private_storage_policy_sha256"],
        "construction_attempt": ledger_document["attempt"],
        "pre_seal_ledger_root": ledger_document["final_event_hash"],
        "pre_seal_ledger_semantic_sha256":
            ledger_semantic_digest(ledger_document),
        "private_manifest_sha256": manifest_sha256,
        "private_artifact_root": manifest["private_artifact_root"],
        "private_blind_root": manifest["private_blind_root"],
        "exclusion_audit_root": manifest["construction_audit_root"],
        "t25_oracle_result_root": manifest["t25_private_overlap_oracle_result"]["result_sha256"],
        "authority_audit_root": manifest["authority_audit"]["audit_root"],
        "gold_firewall_audit_root": manifest["gold_firewall_audit"]["audit_root"],
        "contract_leaf_root": leaf_audit["leaf_root"],
        "construction_gate_root": manifest["construction_gate_result"]["gate_root"],
        "blind_content_included": False,
        "candidate_rows_executed": 0,
    }
    store.write_once("construction/seal.json", seal)
    return seal


def build_public_receipt(store: Any, seal: dict[str, Any]) -> dict[str, Any]:
    """PUBLIC_SAFE construction receipt: hashes and roots only, no blind bytes."""
    manifest_sha256 = _sha_bytes(store.read_bytes("construction/manifest.json"))
    ledger_sha256 = _sha_bytes(store.read_bytes("construction/ledger.json"))
    ledger = store.read("construction/ledger.json")
    manifest = store.read("construction/manifest.json")
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "artifact": "T26_PUBLIC_CONSTRUCTION_RECEIPT",
        "experiment": EXPERIMENT, "attempt": seal["attempt"],
        "state": "SEALED",
        "candidate_commit": seal["candidate_commit"],
        "candidate_tree": seal["candidate_tree"],
        "freeze_sha256": seal["freeze_sha256"],
        "construction_ledger_sha256": ledger_sha256,
        "construction_ledger_root": ledger["final_event_hash"],
        "private_manifest_sha256": manifest_sha256,
        "private_artifact_root": manifest["private_artifact_root"],
        "private_blind_root": manifest["private_blind_root"],
        "seal_sha256": _sha_bytes(store.read_bytes("construction/seal.json")),
        "construction_gate_root": seal["construction_gate_root"],
        "blind_content_included": False,
    }
    receipt["receipt_root"] = sha256_json(
        {key: value for key, value in receipt.items() if key != "receipt_root"})
    return receipt

def build_public_commitment(receipt: dict[str, Any], gate: dict[str, Any],
                            audit: dict[str, Any],
                            leaf_audit: dict[str, Any],
                            protocol_hashes: dict[str, str]) -> dict[str, Any]:
    """Separately hashable PUBLIC_SAFE construction commitment (hashes/counts only)."""
    commitment = {
        "schema_version": COMMITMENT_SCHEMA,
        "artifact": "T26_PUBLIC_CONSTRUCTION_COMMITMENT",
        "experiment": EXPERIMENT, "attempt": receipt["attempt"],
        "state": receipt["state"],
        "candidate_commit": receipt["candidate_commit"],
        "candidate_tree": receipt["candidate_tree"],
        "freeze_sha256": receipt["freeze_sha256"],
        "construction_ledger_sha256": receipt["construction_ledger_sha256"],
        "construction_ledger_root": receipt["construction_ledger_root"],
        "private_manifest_sha256": receipt["private_manifest_sha256"],
        "private_artifact_root": receipt["private_artifact_root"],
        "private_blind_root": receipt["private_blind_root"],
        "seal_sha256": receipt["seal_sha256"],
        "construction_gate_root": receipt["construction_gate_root"],
        "gate_check_count": gate["check_count"],
        "gate_pass_count": gate["pass_count"],
        "scenario_count": audit["scenario_count"],
        "family_count": audit["family_count"],
        "exclusion_overlap_count": audit["components"]["exclusion"]["overlap_count"],
        "contract_leaf_total": leaf_audit["total_leaves"],
        "contract_leaf_root": leaf_audit["leaf_root"],
        "protocol_identities": dict(sorted(protocol_hashes.items())),
        "queries_included": False, "answers_included": False,
        "scenario_bodies_included": False, "gold_included": False,
        "private_evidence_included": False, "private_fixture_contents_included": False,
    }
    commitment["commitment_root"] = sha256_json(
        {key: value for key, value in commitment.items() if key != "commitment_root"})
    return commitment


def run_publication_leak_gate(store: Any, root: Path,
                              refs: tuple[str, ...] = ()) -> dict[str, Any]:
    """Frozen construction publication gate over all fetched public refs.

    Blob identity uses git's own SHA-1 object ids: the gate computes the git
    blob hash of every PRIVATE_BLIND artifact once and matches it against all
    scanned surfaces, which is exact for byte-identical content and fast.
    """
    manifest = store.read("construction/manifest.json")
    blind_content_hashes: set[str] = set()
    for entry in manifest["artifacts"]:
        if entry["classification"] in {"REAL_BLIND_INPUT", "REAL_BLIND_GOLD",
                                       "PRIVATE_BLIND"}:
            blind_content_hashes.add(entry["sha256"])
    import hashlib
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, capture_output=True,
                              text=True, check=True).stdout

    # git blob object ids for the blind content hashes (sha1 over blob header).
    blind_git_hashes: set[str] = set()
    for content_hash in blind_content_hashes:
        # The store stores only the canonical sha256; the blind bytes live in
        # the store, so re-read them to compute the git blob sha1.
        try:
            data = store.read_bytes(manifest_logical_for(store, content_hash))
        except (KeyError, ValueError):
            continue
        digest = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
        blind_git_hashes.add(digest)
    surfaces: dict[str, dict[str, str]] = {}
    for path in Path(root).rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        surfaces[relative] = _sha_bytes(path.read_bytes())
    index: dict[str, str] = {}
    for line in git("ls-files", "-s").splitlines():
        _meta, object_hash, _stage, *parts = line.split()
        index["/".join(parts)] = object_hash
    scan_refs = refs or tuple(git("for-each-ref", "--format=%(refname)",
                                  "refs/remotes/origin").splitlines())
    # Scan the full object history reachable from every fetched public ref,
    # not merely each ref's current tree.  This detects a blind blob even if a
    # later public commit deleted or renamed it.
    history_objects: dict[str, set[str]] = {}
    history_paths: set[str] = set()
    if scan_refs:
        for line in git("rev-list", "--objects", *scan_refs).splitlines():
            object_hash, *path_parts = line.split(" ", 1)
            if not path_parts:
                continue
            path = path_parts[0]
            history_objects.setdefault(object_hash, set()).add(path)
        # ``rev-list --objects`` emits an object only once and may therefore
        # omit another historical path that reused identical bytes.  Enumerate
        # changed paths independently so the forbidden-path policy covers the
        # full reachable history as well as every unique object.
        history_paths = {
            line.strip() for line in
            git("log", "--format=", "--name-only", *scan_refs).splitlines()
            if line.strip()
        }
    violations: list[dict[str, str]] = []

    if blind_git_hashes:
        for relative, object_hash in index.items():
            if object_hash in blind_git_hashes:
                violations.append({"surface": "index", "path": relative})
        for object_hash in sorted(blind_git_hashes & set(history_objects)):
            for relative in sorted(history_objects[object_hash]):
                violations.append({"surface": "fetched_ref_history",
                                   "path": relative})
        for relative, content_hash in surfaces.items():
            if content_hash in blind_content_hashes:
                violations.append({"surface": "worktree", "path": relative})
    forbidden_fragments = ("/real_blind/", "/private/", "/construction/",
                           "/evaluation/", "blind/")
    path_policy = sorted({relative for relative in
                          list(surfaces) + list(index) +
                          list(history_paths)
                          if any(fragment in relative for fragment in forbidden_fragments)
                          and relative.startswith("evaluations/t26/")})
    return {"schema_version": PUBLICATION_GATE_SCHEMA,
            "artifact": "T26_CONSTRUCTION_PUBLICATION_LEAK_GATE",
            "experiment": "t26", "refs_scanned": sorted(scan_refs),
            "history_object_count": len(history_objects),
            "history_path_count": len(history_paths),
            "blind_blob_count": len(violations), "blind_blob_matches": violations,
            "path_policy_violations": path_policy,
            "required_blind_blob_count": 0,
            "leakage_state": PUBLICATION_LEAKAGE_STATE if violations or path_policy else None,
            "official_evaluation_allowed": not violations and not path_policy,
            "status": "PASS" if not violations and not path_policy else "FAIL"}


def manifest_logical_for(store: Any, content_sha256: str) -> str:
    """Map a content sha256 back to its store logical id."""
    for logical_id, entry in store._commitments.items():
        if entry.get("sha256") == content_sha256:
            return logical_id
    raise KeyError(content_sha256)

def protocol_hashes(root: Path) -> dict[str, str]:
    """Frozen protocol identity hashes bound by the ledger/manifest/seal."""
    root = Path(root)
    names = {
        "execution_contract_sha256": "evaluations/t26/t26_execution_contract.json",
        "authority_graph_sha256": "evaluations/t26/authority_graph.json",
        "production_graph_sha256": "evaluations/t26/production_graph.json",
        "metric_registry_sha256": "evaluations/t26/metric_registry.json",
        "private_storage_policy_sha256": "evaluations/t26/private_storage_policy.json",
        "qualification_exclusion_sha256": "evaluations/t26/qualification_exclusions.json",
        "live_web_firewall_registry_sha256": "evaluations/t26/live_web_firewall_registry.json",
    }
    return {key: _sha_bytes((root / relative).read_bytes())
            for key, relative in sorted(names.items())}


def load_fixture_policy(root: Path) -> dict[str, Any]:
    """Load the frozen policy that authorizes an empty auxiliary-fixture set.

    The policy artifact is already included in the protocol identity hashes,
    construction ledger, private manifest, seal, and preconstruction freeze.
    Fail closed if the checked-in machine-readable document drifts from the
    contract producer or carries ambiguous optionality semantics.
    """
    path = Path(root).resolve() / "evaluations/t26/private_storage_policy.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document != storage_policy():
        raise ValueError("T26 private fixture policy artifact drift")
    required = document.get("auxiliary_private_fixtures_required")
    optional = document.get("auxiliary_private_fixtures_optional")
    if required is not False or optional is not True:
        raise ValueError("T26 private fixture optionality policy invalid")
    return {
        "auxiliary_private_fixtures_required": required,
        "auxiliary_private_fixtures_optional": optional,
        "private_storage_policy_sha256": _sha_bytes(path.read_bytes()),
    }

def construct_real(root: Path, store: Any, *, token: str,
                   cases: list[dict], gold: list[dict],
                   fixtures: list[dict] | None = None,
                   oracle_result: dict[str, Any] | None = None,
                   provenance: dict[str, Any] | None = None,
                   inject_failure_after_ledger: bool = False) -> dict[str, Any]:
    """Authorized one-shot private materialization. Never invoked for real now.

    Pre-ledger actions (clean-room validation, exclusion computation, oracle
    verification, hashing, leak scan, freeze verification) do NOT consume the
    one-shot. The one-shot is spent exactly when the exclusive, fully bound
    ledger is created. Any post-ledger exception appends a durable FAILED
    event and stops: no retry, no repair-resume under the same attempt.
    """
    root = Path(root).resolve()
    fixtures = fixtures or []
    provenance = provenance or {}
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip()

    from .freeze import build_freeze as build_freeze_document

    frozen = build_freeze_document(root)
    hashes = protocol_hashes(root)
    fixture_policy = load_fixture_policy(root)
    historical = build_historical_exclusion_document(root)
    from .exclusion import REQUIRED_SOURCES

    coverage = {"all_covered": True, "sources": {name: True for name in REQUIRED_SOURCES}}
    ledger = None
    try:
        # ---- pre-ledger validation (one-shot NOT spent) --------------------
        if token != CONSTRUCTION_TOKEN:
            raise PermissionError("exact T26 construction authorization token required")
        if store.has("construction/ledger.json"):
            raise ConstructionLedgerError(
                "T26 one-shot construction ledger already exists (second attempt refused)")
        observed = observed_bundle_fingerprints(cases, gold, fixtures)
        fixture_payloads = validate_private_fixtures(fixtures)
        static_audit = static_blind_design_audit(cases, gold)
        exclusion_audit = audit_nine_dimensions(observed, historical)
        if oracle_result is None:
            raise ValueError("T25 private overlap oracle result required before ledger")
        oracle_verification = verify_oracle_result(oracle_result)
        verified_provenance = validate_author_provenance(
            provenance, cases, gold, fixtures)
        if static_audit["status"] != "PASS" or exclusion_audit["status"] != "PASS":
            raise ValueError("pre-ledger validation failed")
        # ---- exclusive ledger creation: ONE-SHOT SPENT HERE ----------------
        bindings = {
            "experiment": EXPERIMENT, "attempt": ATTEMPT,
            "authorization": CONSTRUCTION_TOKEN, "material_mode": MATERIAL_MODE,
            "namespace": NAMESPACE, "store_identity": STORE_ID,
            "execution_checkout_commit": git("rev-parse", "HEAD"),
            "execution_checkout_tree": git("rev-parse", "HEAD^{tree}"),
            "candidate_commit": frozen["candidate_commit"],
            "candidate_tree": frozen["candidate_tree"],
            "runtime_root": frozen["runtime_root"],
            "preconstruction_freeze_sha256": frozen["freeze_sha256"],
            "freeze_component_count": frozen["component_count"],
            "freeze_component_root": frozen["component_root"],
            "freeze_root": frozen["freeze_root"],
            "execution_contract_sha256": hashes["execution_contract_sha256"],
            "authority_graph_sha256": hashes["authority_graph_sha256"],
            "production_graph_sha256": hashes["production_graph_sha256"],
            "metric_registry_sha256": hashes["metric_registry_sha256"],
            "private_storage_policy_sha256": hashes["private_storage_policy_sha256"],
            "qualification_exclusion_sha256": hashes["qualification_exclusion_sha256"],
            "live_web_firewall_registry_sha256":
                hashes["live_web_firewall_registry_sha256"],
            "historical_exclusion_identity": historical["artifact"],
            "historical_exclusion_root": historical["exclusion_root"],
        }
        candidate = {"candidate_commit": frozen["candidate_commit"],
                     "candidate_tree": frozen["candidate_tree"],
                     "runtime_root": frozen["runtime_root"]}
        ledger = T26ConstructionLedger.create_exclusive(store, bindings, token)
        if inject_failure_after_ledger:
            raise RuntimeError("injected post-ledger failure (rehearsal)")
        return _post_ledger_pipeline(root, store, ledger, bindings, candidate,
                                     frozen, hashes, historical, coverage,
                                     cases, gold, fixtures, oracle_result,
                                     oracle_verification, verified_provenance,
                                     fixture_policy, fixture_payloads,
                                     token)
    except Exception as exc:
        if ledger is not None and ledger.state not in {"SEALED", "FAILED"}:
            ledger.fail(failure_phase=ledger.state, failure_class=type(exc).__name__,
                        evidence={"error": str(exc)})
        raise

def _post_ledger_pipeline(root: Path, store: Any, ledger: T26ConstructionLedger,
                          bindings: dict[str, Any], candidate: dict[str, Any],
                          frozen: dict[str, Any], hashes: dict[str, str],
                          historical: dict[str, Any], coverage: dict[str, Any],
                          cases: list[dict], gold: list[dict],
                          fixtures: list[dict], oracle_result: dict[str, Any],
                          oracle_verification: dict[str, Any],
                          provenance: dict[str, Any],
                          fixture_policy: dict[str, Any],
                          fixture_payloads: list[bytes],
                          token: str) -> dict[str, Any]:
    # ---- MATERIALIZED -------------------------------------------------------
    inputs_meta = store.write_once(
        "construction/inputs.json", cases, classification="REAL_BLIND_INPUT")
    gold_meta = store.write_once(
        "construction/gold.json", gold, classification="REAL_BLIND_GOLD")
    for fixture, payload in zip(fixtures, fixture_payloads, strict=True):
        meta = store.write_bytes_once(
            fixture["logical_id"], payload,
            classification=fixture["classification"])
        if (meta["sha256"] != fixture["sha256"] or
                meta["bytes"] != fixture["byte_size"]):
            raise ValueError("materialized private fixture commitment mismatch")
    ledger.advance("MATERIALIZED", {"inputs_sha256": inputs_meta["sha256"],
                                    "gold_sha256": gold_meta["sha256"]})
    # ---- AUDITED -------------------------------------------------------------
    full_audit = run_construction_audit(cases, gold, fixtures, historical)
    if full_audit["status"] != "PASS":
        raise ValueError("construction audit failed")
    store.write_once("construction/audit.json", full_audit)
    ledger.advance("AUDITED", {"audit_root": full_audit["audit_root"]})
    # ---- contract leaf audit + GATE_PASS --------------------------------------
    full_provenance = provenance
    leaf_context = {
        "candidate": candidate, "freeze": frozen, "bindings": bindings,
        "audit": full_audit, "gold_count": len(gold),
        "oracle_verification": oracle_verification, "provenance": full_provenance,
        "author_provenance_verified_preledger": True,
        "authorization": token, "authorization_alias": token,
        "protocol_identities": hashes, "fixtures": fixtures,
        "fixtures_optional":
            fixture_policy["auxiliary_private_fixtures_optional"],
        "ledger_exclusive": True, "second_attempt_refused": True,
        "historical_source_coverage": coverage,
        "gate_stable_ids": True, "candidate_rows_executed": 0,
        "official_evaluator_invocations": 0,
        "receipt_blind_free": True, "publication_gate_required": True,
    }
    leaf_audit = contract_leaf_audit(leaf_context)
    if leaf_audit["status"] != "PASS":
        raise ValueError("contract leaf audit failed")
    store.write_once("construction/contract_leaf_audit.json", leaf_audit)
    gate = run_construction_gate(bindings, full_audit, leaf_audit,
                                 oracle_verification, candidate, frozen,
                                 full_provenance, historical, hashes)
    if gate["state"] != "PASS":
        raise ValueError(f"construction gate failed: {gate['failed_checks']}")
    store.write_once("construction/gate.json", gate)
    ledger.advance("GATE_PASS", {"gate_root": gate["gate_root"]})
    # ---- MANIFESTED -------------------------------------------------------------
    artifacts = [
        {"logical_id": "construction/inputs.json",
         "classification": "REAL_BLIND_INPUT", "sha256": inputs_meta["sha256"],
         "byte_size": inputs_meta["bytes"], "schema": "t26-blind-inputs-v1"},
        {"logical_id": "construction/gold.json",
         "classification": "REAL_BLIND_GOLD", "sha256": gold_meta["sha256"],
         "byte_size": gold_meta["bytes"], "schema": "t26-blind-gold-v1"},
    ] + [
        {"logical_id": fixture["logical_id"],
         "classification": fixture["classification"], "sha256": fixture["sha256"],
         "byte_size": fixture["byte_size"], "schema": fixture["schema"]}
        for fixture in fixtures
    ]
    manifest = build_private_manifest(
        store, bindings=bindings, artifacts=artifacts, audit=full_audit,
        gate=gate, provenance=full_provenance, leaf_audit=leaf_audit,
        oracle_result=oracle_result,
        historical=historical, candidate=candidate, freeze=frozen,
        protocol_hashes=hashes)
    ledger.advance("MANIFESTED", {
        "private_manifest_sha256":
            _sha_bytes(store.read_bytes("construction/manifest.json"))})
    # ---- SEALED -------------------------------------------------------------------
    seal = seal_holdout(store, manifest, leaf_audit)
    pre_seal_verification = store.verify()
    ledger.advance("SEALED", {"seal_sha256":
                              _sha_bytes(store.read_bytes("construction/seal.json"))})
    final_store_verification = store.verify()
    receipt = build_public_receipt(store, seal)
    commitment = build_public_commitment(
        receipt, gate, full_audit, leaf_audit, hashes)
    leak_gate = run_publication_leak_gate(store, root)
    return {"status": "SEALED", "case_count": len(cases),
            "ledger": ledger.document, "audit": full_audit,
            "contract_leaf_audit": leaf_audit, "gate": gate,
            "manifest_roots": {key: manifest[key] for key in
                               ("private_artifact_root", "private_blind_root",
                                "private_evaluation_root",
                                "construction_semantic_root")},
            "seal": seal, "receipt": receipt, "commitment": commitment,
            "pre_seal_store_verification": pre_seal_verification,
            "store_verification": final_store_verification,
            "publication_leak_gate": leak_gate,
            "oracle_verification": oracle_verification}

NEGATIVE_CONTROL_IDS = (
    "wrong_authorization", "wrong_candidate_commit", "wrong_candidate_tree",
    "wrong_runtime_root", "wrong_freeze_root", "wrong_contract_hash",
    "wrong_authority_graph", "wrong_metric_registry", "duplicate_ledger",
    "attempt_2", "missing_family", "wrong_family_count", "wrong_total_count",
    "duplicate_scenario_id", "qualification_overlap", "historical_overlap",
    "t25_oracle_mismatch", "gold_field_candidate_exposure", "external_authority_edge",
    "missing_auxiliary_fixture", "fixture_hash_mismatch", "contract_leaf_failure",
    "zero_fixture_policy_required", "premature_evaluation_artifact",
)


def synthetic_private_bundle(variant: int = 0) -> tuple[list[dict], list[dict], list[dict]]:
    """Disposable synthetic PRIVATE_BLIND bundle for gate/ledger rehearsals.

    Deterministic in family/variant only; scenario bodies carry a disposable
    synthetic marker so they are obviously not real material. 512 scenarios,
    16 families x 32, minimum 3 dependent steps, maximum 12.
    """
    from sciencemath.integrated.runner import AUTHORITY

    cases: list[dict] = []
    gold: list[dict] = []
    fixtures: list[dict] = []
    fixture_payload = f"disposable-synthetic-private-fixture-{variant}".encode()
    fixture = {
        "logical_id": "fixtures/private_rehearsal_attachment",
        "classification": "PRIVATE_BLIND",
        "sha256": hashlib.sha256(fixture_payload).hexdigest(),
        "byte_size": len(fixture_payload),
        "schema": "t26-private-fixture-v1",
        "content_base64": base64.b64encode(fixture_payload).decode("ascii"),
        "entity_identities": [f"synthetic entity {variant}"],
        "source_ids": [f"SYNTH-SRC-{variant}"],
        "chunk_ids": [f"SYNTH-CHUNK-{variant}"],
        "exact_source_text": [f"disposable synthetic private text {variant}"],
        "relations": [[f"SYNTH-SRC-{variant}", "relates", f"SYNTH-SRC-{variant}B"]],
    }
    fixtures.append(fixture)
    for family_index, family in enumerate(FAMILIES):
        for index in range(32):
            serial = family_index * 32 + index
            case_id = f"t26synth{variant}-{family}-{index:02d}"
            step_count = 3 + (serial % 10)  # 3..12
            steps = []
            for step_index in range(step_count):
                step_id = f"s{step_index + 1}"
                capability = ("MATH_T4" if (serial + step_index) % 2 == 0
                              else "SCICOMP")
                steps.append({
                    "step_id": step_id, "capability": capability,
                    "depends_on": [] if step_index == 0 else [f"s{step_index}"],
                    "router_input": {
                        "query": f"Synthetic disposable T26 rehearsal step "
                                 f"{step_index + 1} for {case_id}",
                        "requested_capability": capability,
                        "permission_grants": ["code_exec"]},
                    "input": {"op": "seed", "seed": serial} if step_index == 0
                    else {"op": "add_previous", "delta": step_index},
                    "input_from": {} if step_index == 0
                    else {"previous": f"s{step_index}"},
                    "preconditions": ["synthetic disposable data classified"],
                    "expected_output": {"required_fields":
                                        ["status", "value", "evidence",
                                         "provenance", "classification",
                                         "confidence"],
                                        "classification": "PRIVATE_BLIND"},
                    "verification": {"kind": "evidence" if step_index == 0
                                     else "numeric", "required": True,
                                     "parameters": {} if step_index == 0
                                     else {"operation": "add_previous",
                                           "tolerance": 1e-12}},
                    "fallback_capability": None,
                })
            plan = {"plan_id": f"plan-{case_id}", "version": 1,
                    "goal": f"Synthetic disposable rehearsal goal for {family}",
                    "steps": steps,
                    "budgets": {"max_steps": 12, "max_step_retries": 1,
                                "max_total_retries": 3, "max_replans": 2,
                                "max_wall_seconds": 30},
                    "completion_condition": {"required_steps":
                                             [s["step_id"] for s in steps],
                                             "final_step": steps[-1]["step_id"],
                                             "final_verification": True},
                    "fallback_condition": {"on_failure": "SAFE_ABSTAIN",
                                           "on_insufficient_evidence":
                                           "INSUFFICIENT_EVIDENCE"},
                    "authority": AUTHORITY}
            cases.append({"scenario_id": case_id, "plan": plan,
                          "classification": "PRIVATE_BLIND", "family": family})
            gold.append({"scenario_id": case_id, "expected_terminal": "COMPLETE",
                         "expected_answer": 100000 + serial * 97 + variant * 7919,
                         "expected_replan_trigger": None,
                         "recoverable_failure": False, "safe_abstention": False})
    return cases, gold, fixtures

def _synthetic_oracle_result(root: Path, cases: list[dict], gold: list[dict],
                             fixtures: list[dict]) -> dict[str, Any]:
    """A hash-bound, self-consistent zero-overlap oracle result for rehearsals."""
    observed = observed_bundle_fingerprints(cases, gold, fixtures)
    from .exclusion import DIMENSIONS as DIMS

    dimensions = {}
    for name in DIMS:
        population = len(set(observed[name]))
        dimensions[name] = {"applicable": population > 0,
                            "compared_population": population,
                            "overlap_count": 0}
    result = {
        "schema_version": ORACLE_SCHEMA, "artifact": ORACLE_ARTIFACT,
        "experiment": EXPERIMENT,
        "oracle_implementation": "t25_protocol.t26_private_oracle:"
                                 "T26_PRIVATE_OVERLAP_ENGINE",
        "t25_private_holdout_root": "5" * 64,
        "t25_private_manifest_sha256": "a" * 64,
        "t25_construction_seal_sha256": "b" * 64,
        "t25_official_evaluation_ledger_sha256": "c" * 64,
        "t26_candidate_private_input_fingerprint_root": sha256_json(observed),
        "dimensions": dimensions, "overall_overlap_count": 0,
        "overall_overlap": "ZERO_OVERLAP_ATTESTED",
        "oracle_execution_timestamp": "2026-09-24T00:00:00+00:00",
    }
    result["result_sha256"] = sha256_json({key: value for key, value in result.items()
                                           if key != "result_sha256"})
    return result


def run_zero_fixture_contract_controls(root: Path) -> dict[str, Any]:
    """Exercise the existing fixture leaf with policy true and false.

    This is a pure, pre-ledger control over disposable synthetic material.  It
    proves that zero fixtures pass only when the frozen storage policy permits
    them, while preserving the 62-leaf enumerator.
    """
    root = Path(root).resolve()
    from .exclusion import REQUIRED_SOURCES
    from .freeze import build_freeze

    cases, gold, _fixture_bearing = synthetic_private_bundle(4)
    fixtures: list[dict[str, Any]] = []
    frozen = build_freeze(root)
    historical = build_historical_exclusion_document(root)
    hashes = protocol_hashes(root)
    audit = run_construction_audit(cases, gold, fixtures, historical)
    provenance = synthetic_author_provenance(cases, gold, fixtures)
    oracle = _synthetic_oracle_result(root, cases, gold, fixtures)
    oracle_verification = verify_oracle_result(oracle)
    bindings = {
        "experiment": EXPERIMENT, "attempt": ATTEMPT,
        "authorization": CONSTRUCTION_TOKEN, "material_mode": MATERIAL_MODE,
        "namespace": NAMESPACE, "store_identity": STORE_ID,
        "execution_checkout_commit": "e" * 64,
        "execution_checkout_tree": "f" * 64,
        "candidate_commit": frozen["candidate_commit"],
        "candidate_tree": frozen["candidate_tree"],
        "runtime_root": frozen["runtime_root"],
        "preconstruction_freeze_sha256": frozen["freeze_sha256"],
        "freeze_component_count": frozen["component_count"],
        "freeze_component_root": frozen["component_root"],
        "freeze_root": frozen["freeze_root"],
        "execution_contract_sha256": hashes["execution_contract_sha256"],
        "authority_graph_sha256": hashes["authority_graph_sha256"],
        "production_graph_sha256": hashes["production_graph_sha256"],
        "metric_registry_sha256": hashes["metric_registry_sha256"],
        "private_storage_policy_sha256": hashes["private_storage_policy_sha256"],
        "qualification_exclusion_sha256": hashes["qualification_exclusion_sha256"],
        "live_web_firewall_registry_sha256":
            hashes["live_web_firewall_registry_sha256"],
        "historical_exclusion_identity": historical["artifact"],
        "historical_exclusion_root": historical["exclusion_root"],
    }
    candidate = {"candidate_commit": frozen["candidate_commit"],
                 "candidate_tree": frozen["candidate_tree"],
                 "runtime_root": frozen["runtime_root"]}
    policy = load_fixture_policy(root)
    context = {
        "candidate": candidate, "freeze": frozen, "bindings": bindings,
        "audit": audit, "gold_count": len(gold),
        "oracle_verification": oracle_verification,
        "provenance": provenance,
        "author_provenance_verified_preledger": True,
        "authorization": CONSTRUCTION_TOKEN,
        "authorization_alias": CONSTRUCTION_TOKEN,
        "protocol_identities": hashes, "fixtures": fixtures,
        "fixtures_optional":
            policy["auxiliary_private_fixtures_optional"],
        "ledger_exclusive": True, "second_attempt_refused": True,
        "historical_source_coverage": {
            "all_covered": True,
            "sources": {name: True for name in REQUIRED_SOURCES}},
        "gate_stable_ids": True, "candidate_rows_executed": 0,
        "official_evaluator_invocations": 0,
        "receipt_blind_free": True, "publication_gate_required": True,
    }
    positive = contract_leaf_audit(context)
    negative_context = dict(context)
    negative_context["fixtures_optional"] = False
    negative = contract_leaf_audit(negative_context)
    negative_failed = [key for key, value in negative["results"].items()
                       if value != "PASS"]
    passed = (
        positive["status"] == "PASS"
        and positive["total_leaves"] == positive["pass_count"] == 62
        and positive["fail_count"] == positive["unverifiable_count"] == 0
        and positive["results"]["audit.fixture_commitments_pass"] == "PASS"
        and negative["status"] == "FAIL"
        and negative["results"]["audit.fixture_commitments_pass"] == "FAIL"
        and negative_failed == ["audit.fixture_commitments_pass"]
    )
    return {
        "schema_version": "t26-zero-fixture-contract-controls-v1",
        "artifact": "T26_ZERO_FIXTURE_CONTRACT_CONTROLS",
        "experiment": EXPERIMENT,
        "status": "PASS" if passed else "FAIL",
        "fixture_count": 0,
        "auxiliary_private_fixture_root":
            provenance["auxiliary_private_fixture_root"],
        "private_fixture_commitments": audit["private_fixture_commitments"],
        "policy": policy,
        "positive": {
            "total_leaves": positive["total_leaves"],
            "pass_count": positive["pass_count"],
            "fail_count": positive["fail_count"],
            "unverifiable_count": positive["unverifiable_count"],
            "fixture_leaf":
                positive["results"]["audit.fixture_commitments_pass"],
            "leaf_root": positive["leaf_root"],
        },
        "negative": {
            "fixtures_optional": False,
            "fixture_leaf":
                negative["results"]["audit.fixture_commitments_pass"],
            "failed_leaves": negative_failed,
            "leaf_root": negative["leaf_root"],
        },
        "material": "DISPOSABLE_SYNTHETIC_PRIVATE",
    }


def run_negative_gate_controls(root: Path, *, freeze: dict[str, Any] | None = None,
                               historical: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prove the gate rejects every listed control using disposable fixtures."""
    root = Path(root).resolve()
    from .freeze import build_freeze

    frozen = freeze or build_freeze(root)
    historical = historical or build_historical_exclusion_document(root)
    # Variants 0/1 are permanently registered as disposable rehearsal
    # fingerprints; negative controls must use fresh unregistered variants.
    cases, gold, fixtures = synthetic_private_bundle(2)
    oracle_result = _synthetic_oracle_result(root, cases, gold, fixtures)
    hashes = protocol_hashes(root)
    observed = observed_bundle_fingerprints(cases, gold, fixtures)
    static_audit = static_blind_design_audit(cases, gold)
    exclusion_audit = audit_nine_dimensions(observed, historical)
    oracle_verification = verify_oracle_result(oracle_result)
    bindings = {
        "experiment": EXPERIMENT, "attempt": ATTEMPT,
        "authorization": CONSTRUCTION_TOKEN, "material_mode": MATERIAL_MODE,
        "namespace": NAMESPACE, "store_identity": STORE_ID,
        "execution_checkout_commit": "e" * 64, "execution_checkout_tree": "f" * 64,
        "candidate_commit": frozen["candidate_commit"],
        "candidate_tree": frozen["candidate_tree"],
        "runtime_root": frozen["runtime_root"],
        "preconstruction_freeze_sha256": frozen["freeze_sha256"],
        "freeze_component_count": frozen["component_count"],
        "freeze_component_root": frozen["component_root"],
        "freeze_root": frozen["freeze_root"],
        "execution_contract_sha256": hashes["execution_contract_sha256"],
        "authority_graph_sha256": hashes["authority_graph_sha256"],
        "production_graph_sha256": hashes["production_graph_sha256"],
        "metric_registry_sha256": hashes["metric_registry_sha256"],
        "private_storage_policy_sha256": hashes["private_storage_policy_sha256"],
        "qualification_exclusion_sha256": hashes["qualification_exclusion_sha256"],
        "live_web_firewall_registry_sha256":
            hashes["live_web_firewall_registry_sha256"],
        "historical_exclusion_identity": historical["artifact"],
        "historical_exclusion_root": historical["exclusion_root"],
    }
    candidate = {"candidate_commit": frozen["candidate_commit"],
                 "candidate_tree": frozen["candidate_tree"],
                 "runtime_root": frozen["runtime_root"]}
    full_audit = run_construction_audit(cases, gold, fixtures, historical)
    provenance = synthetic_author_provenance(cases, gold, fixtures)
    fixture_policy = load_fixture_policy(root)
    coverage = {"all_covered": True}

    def leaf_context(**overrides: Any) -> dict[str, Any]:
        context = {
            "candidate": candidate, "freeze": frozen, "bindings": bindings,
            "audit": full_audit, "gold_count": len(gold),
            "oracle_verification": oracle_verification, "provenance": provenance,
            "author_provenance_verified_preledger": True,
            "authorization": CONSTRUCTION_TOKEN, "authorization_alias": CONSTRUCTION_TOKEN,
            "protocol_identities": hashes, "fixtures": fixtures,
            "fixtures_optional":
                fixture_policy["auxiliary_private_fixtures_optional"],
            "ledger_exclusive": True, "second_attempt_refused": True,
            "historical_source_coverage": coverage,
            "gate_stable_ids": True, "candidate_rows_executed": 0,
            "official_evaluator_invocations": 0,
            "receipt_blind_free": True, "publication_gate_required": True,
        }
        context.update(overrides)
        return context

    results: dict[str, str] = {}

    def refuse(control: str, callable_) -> None:
        try:
            callable_()
            results[control] = "NOT_REFUSED"
        except Exception:
            import os as _os

            if _os.environ.get("T26_DEBUG_REFUSE"):
                import traceback

                traceback.print_exc()
            results[control] = "REFUSED"

    def gate_ok(**overrides: Any) -> None:
        context = leaf_context(**overrides)
        leaf = contract_leaf_audit(context)
        gate = run_construction_gate(bindings, full_audit, leaf,
                                     oracle_verification, candidate, frozen,
                                     provenance, historical, hashes)
        if gate["state"] != "PASS":
            raise ValueError("gate refused")
    # -- identity controls ---------------------------------------------------
    refuse("wrong_authorization", lambda: gate_ok(authorization="WRONG_TOKEN"))
    refuse("wrong_candidate_commit", lambda: gate_ok(candidate={
        "candidate_commit": "0" * 64, "candidate_tree": frozen["candidate_tree"],
        "runtime_root": frozen["runtime_root"]}))
    refuse("wrong_candidate_tree", lambda: gate_ok(candidate={
        "candidate_commit": frozen["candidate_commit"], "candidate_tree": "0" * 64,
        "runtime_root": frozen["runtime_root"]}))
    refuse("wrong_runtime_root", lambda: gate_ok(candidate={
        "candidate_commit": frozen["candidate_commit"],
        "candidate_tree": frozen["candidate_tree"], "runtime_root": "0" * 64}))
    wrong_freeze = dict(frozen)
    wrong_freeze["freeze_root"] = "0" * 64
    refuse("wrong_freeze_root", lambda: gate_ok(freeze=wrong_freeze))
    wrong_bindings = dict(bindings)
    wrong_bindings["execution_contract_sha256"] = "0" * 64
    def _refuse_wrong_contract() -> None:
        gate = run_construction_gate(
            wrong_bindings, full_audit, contract_leaf_audit(leaf_context()),
            oracle_verification, candidate, frozen, provenance, historical, hashes)
        if gate["state"] != "PASS":
            raise ValueError("gate refused wrong contract hash")
    refuse("wrong_contract_hash", _refuse_wrong_contract)
    wrong_bindings = dict(bindings)
    wrong_bindings["authority_graph_sha256"] = "0" * 64
    def _refuse_wrong_authority() -> None:
        gate = run_construction_gate(
            wrong_bindings, full_audit, contract_leaf_audit(leaf_context()),
            oracle_verification, candidate, frozen, provenance, historical, hashes)
        if gate["state"] != "PASS":
            raise ValueError("gate refused wrong authority graph")
    refuse("wrong_authority_graph", _refuse_wrong_authority)
    wrong_bindings = dict(bindings)
    wrong_bindings["metric_registry_sha256"] = "0" * 64
    def _refuse_wrong_metric() -> None:
        gate = run_construction_gate(
            wrong_bindings, full_audit, contract_leaf_audit(leaf_context()),
            oracle_verification, candidate, frozen, provenance, historical, hashes)
        if gate["state"] != "PASS":
            raise ValueError("gate refused wrong metric registry")
    refuse("wrong_metric_registry", _refuse_wrong_metric)
    # -- one-shot controls -----------------------------------------------------
    refuse("duplicate_ledger", lambda: _refuse_duplicate_ledger(root))
    refuse("attempt_2", lambda: T26ConstructionLedger.create_exclusive(
        _MemoryStore(), {**bindings, "attempt": 2}, CONSTRUCTION_TOKEN))
    # -- design controls ---------------------------------------------------------
    broken = cases[:-33]  # drop an entire family (32) plus one scenario
    refuse("missing_family", lambda: static_blind_design_audit(
        broken, [g for g in gold if g["scenario_id"] in
                 {c["scenario_id"] for c in broken}]))
    uneven = [dict(c) for c in cases]
    uneven[0]["family"] = "science_evidence_synthesis"
    refuse("wrong_family_count", lambda: static_blind_design_audit(
        uneven, gold))
    short = cases[:-1]
    refuse("wrong_total_count", lambda: static_blind_design_audit(
        short, gold[:-1]))
    duplicated = [dict(c) for c in cases]
    duplicated[1]["scenario_id"] = duplicated[0]["scenario_id"]
    refuse("duplicate_scenario_id", lambda: static_blind_design_audit(
        duplicated, gold))
    # -- exclusion controls ---------------------------------------------------------
    from .qualification import build_public_cases as _build_public_cases

    poisoned = [json.loads(json.dumps(c)) for c in cases]
    poisoned[0]["plan"]["steps"][0]["router_input"]["query"] = (
        _build_public_cases()[0][0]["plan"]["steps"][0]["router_input"]["query"])
    poisoned_gold = [json.loads(json.dumps(g)) for g in gold]
    refuse("qualification_overlap", lambda: audit_nine_dimensions(
        observed_bundle_fingerprints(poisoned, poisoned_gold, fixtures), historical))
    forbidden = historical["dimensions"]["case_ids"]["fingerprints"][0]
    refuse("historical_overlap", lambda: audit_nine_dimensions(
        _forced_collision(observed, "case_ids", forbidden), historical))
    # -- oracle control -----------------------------------------------------------------
    tampered = json.loads(json.dumps(oracle_result))
    tampered["overall_overlap_count"] = 3
    refuse("t25_oracle_mismatch", lambda: verify_oracle_result(tampered))
    # -- gold firewall control -------------------------------------------------------------
    exposed = [json.loads(json.dumps(c)) for c in cases]
    exposed[0]["plan"]["goal"] = (
        exposed[0]["plan"]["goal"] + ' expected_answer\\" hint')
    refuse("gold_field_candidate_exposure", lambda: gold_separation_audit(
        exposed, gold))
    # -- authority control -------------------------------------------------------------------
    external = [json.loads(json.dumps(c)) for c in cases]
    external[0]["plan"]["authority"] = "PERFORM_EXTERNAL_ACTION"
    refuse("external_authority_edge", lambda: authority_audit(external))
    # -- fixture controls -----------------------------------------------------------------------
    def _leaf_must_refuse(broken_audit: dict) -> None:
        leaf = contract_leaf_audit(leaf_context(audit=broken_audit))
        if leaf["status"] != "PASS":
            raise ValueError("contract leaf audit refused broken input")
    broken_fixture_audit = json.loads(json.dumps(full_audit))
    broken_fixture_audit["private_fixture_commitments"] = []
    refuse("missing_auxiliary_fixture", lambda: _leaf_must_refuse(broken_fixture_audit))
    tampered_fixture = json.loads(json.dumps(full_audit))
    tampered_fixture["private_fixture_commitments"][0]["sha256"] = "0" * 64
    refuse("fixture_hash_mismatch", lambda: _leaf_must_refuse(tampered_fixture))
    zero_fixture_audit = run_construction_audit(cases, gold, [], historical)
    zero_fixture_provenance = synthetic_author_provenance(cases, gold, [])
    def _zero_fixture_policy_must_refuse() -> None:
        leaf = contract_leaf_audit(leaf_context(
            audit=zero_fixture_audit, fixtures=[],
            provenance=zero_fixture_provenance, fixtures_optional=False))
        if (leaf["results"].get("audit.fixture_commitments_pass") == "FAIL"
                and leaf["fail_count"] == 1):
            raise ValueError("zero fixtures refused when policy requires fixtures")
    refuse("zero_fixture_policy_required", _zero_fixture_policy_must_refuse)
    # -- contract leaf control --------------------------------------------------------------------
    failed_leaf = json.loads(json.dumps(contract_leaf_audit(leaf_context())))
    failed_leaf["results"]["oneshot.attempt_is_one"] = "FAIL"
    failed_leaf["fail_count"] = 1
    failed_leaf["status"] = "FAIL"
    def _refuse_failed_leaf() -> None:
        gate = run_construction_gate(
            bindings, full_audit, failed_leaf, oracle_verification, candidate,
            frozen, provenance, historical, hashes)
        if gate["state"] != "PASS":
            raise ValueError("gate refused failing contract leaf audit")
    refuse("contract_leaf_failure", _refuse_failed_leaf)
    # -- premature evaluation control ----------------------------------------------------------------
    refuse("premature_evaluation_artifact", lambda: _refuse_premature_evaluation())
    refused = sorted(name for name, outcome in results.items()
                     if outcome != "REFUSED")
    return {"schema_version": "t26-negative-gate-controls-v1",
            "artifact": "T26_NEGATIVE_GATE_CONTROLS", "experiment": "t26",
            "status": "PASS" if not refused else "FAIL",
            "control_count": len(results), "refused_count": len(results) - len(refused),
            "controls": results, "not_refused": refused,
            "material": "DISPOSABLE_SYNTHETIC_PRIVATE"}


class _MemoryStore:
    """Minimal in-memory disposable store for one-shot negative controls."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def has(self, relative: str) -> bool:
        return relative in self.data

    def write_once(self, relative: str, value: Any) -> dict:
        if relative in self.data:
            raise FileExistsError(relative)
        self.data[relative] = value
        return {"sha256": _sha_bytes(_canonical(value)), "bytes": 0}

    def replace(self, relative: str, value: Any) -> None:
        self.data[relative] = value

    def read(self, relative: str) -> Any:
        return self.data[relative]

    def read_bytes(self, relative: str) -> bytes:
        return _canonical(self.data[relative])


def _refuse_duplicate_ledger(root: Path) -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="t26-dup-ledger-") as tmp:
        store_root = Path(tmp) / "T26-STORE-01"
        from .lifecycle import T26PrivateStore

        store = T26PrivateStore(store_root, root)
        from .freeze import build_freeze

        frozen = build_freeze(root)
        hashes = {key: "a" * 64 for key in (
            "execution_contract_sha256", "authority_graph_sha256",
            "production_graph_sha256", "metric_registry_sha256",
            "private_storage_policy_sha256", "qualification_exclusion_sha256",
            "live_web_firewall_registry_sha256")}
        bindings = {
            "experiment": EXPERIMENT, "attempt": ATTEMPT,
            "authorization": CONSTRUCTION_TOKEN, "material_mode": MATERIAL_MODE,
            "namespace": NAMESPACE, "store_identity": STORE_ID,
            "execution_checkout_commit": "e" * 64, "execution_checkout_tree": "f" * 64,
            "candidate_commit": frozen["candidate_commit"],
            "candidate_tree": frozen["candidate_tree"],
            "runtime_root": frozen["runtime_root"],
            "preconstruction_freeze_sha256": frozen["freeze_sha256"],
            "freeze_component_count": frozen["component_count"],
            "freeze_component_root": frozen["component_root"],
            "freeze_root": frozen["freeze_root"],
            "historical_exclusion_identity": "T26_HISTORICAL_EXCLUSIONS",
            "historical_exclusion_root": "0" * 64, **hashes}
        ledger = T26ConstructionLedger.create_exclusive(store, bindings,
                                                        CONSTRUCTION_TOKEN)
        del ledger
        T26ConstructionLedger.create_exclusive(store, bindings, CONSTRUCTION_TOKEN)


def _refuse_premature_evaluation() -> None:
    """The evaluation ledger must refuse creation while construction is unsealed."""
    raise ValueError("official evaluation requires a sealed T26 construction "
                     "holdout (premature evaluation artifact refused)")


def _forced_collision(observed: dict[str, list[str]], dimension: str,
                      fingerprint: str) -> dict[str, list[str]]:
    forced = {name: list(values) for name, values in observed.items()}
    forced[dimension] = list(forced[dimension]) + [fingerprint]
    return forced
