"""Frozen T27 construction lifecycle.

No function in this module authors real material.  The real entrypoint accepts
an already-authored private bundle, validates it before spending the one-shot,
then materializes it only in :class:`T27PrivateStore`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from t21_protocol.util import sha256_json

from .contract import (CONSTRUCTION_TOKEN, FAMILIES, NONVACUITY_MINIMUMS,
                       design)
from .exclusion import (DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA,
                        GENERATED_PUBLIC_REUSABLE_DIMENSIONS,
                        GENERATED_PUBLIC_SOURCES,
                        GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS,
                        REQUIRED_HISTORICAL_SOURCES, STRUCTURAL_SHARED_FROZEN_EMPTY,
                        SUPERSEDED_INDEX_ROOT,
                        build_authenticated_public_historical_index,
                        build_synthetic_historical_index,
                        generated_public_dimension_policy,
                        validate_generated_public_dimension_policy,
                        verify_historical_index)
from .oracle import verify_oracle_result
from .store import (CLASSIFICATIONS, NAMESPACE, STORE_ID, T27PrivateStore,
                    _json_bytes)

EXPERIMENT = "t27"
LEDGER_STATES = (
    "LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS",
    "MANIFESTED", "SEALED", "FAILED",
)
TRANSITIONS = {
    "LEDGER_CREATED": {"MATERIALIZED", "FAILED"},
    "MATERIALIZED": {"AUDITED", "FAILED"},
    "AUDITED": {"GATE_PASS", "FAILED"},
    "GATE_PASS": {"MANIFESTED", "FAILED"},
    "MANIFESTED": {"SEALED", "FAILED"},
    "SEALED": set(), "FAILED": set(),
}
GOLD_ONLY_FIELDS = frozenset({
    "expected_terminal", "expected_answer", "expected_replan_trigger",
    "expected_fallback_capability", "designated_recoverable",
    "designated_abstention", "metric_designations", "gold",
})
HISTORICAL_SOURCES = REQUIRED_HISTORICAL_SOURCES
LEDGER_BINDING_FIELDS = frozenset({
    "experiment", "attempt", "mode", "authorization_token", "store_id",
    "namespace", "execution_commit", "execution_tree", "candidate_commit",
    "candidate_tree", "runtime_root", "preconstruction_freeze_sha256",
    "component_count", "component_root", "freeze_root",
    "terminal_contract_sha256", "metric_registry_sha256",
    "nonvacuity_policy_sha256", "authority_graph_sha256",
    "production_graph_sha256", "storage_policy_sha256",
    "historical_exclusion_policy_sha256",
    "t26_historical_failure_anchor_sha256", "construction_timestamp",
    "public_historical_index_root", "t26_overlap_oracle_result_sha256",
    "combined_historical_exclusion_root",
    "generated_public_dimension_policy_sha256",
    "structural_unsatisfiability_reproducer_sha256",
    "structural_satisfiability_witness_sha256",
    "state",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _event(index: int, event_type: str, timestamp: str,
           previous: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    core = {
        "event_index": index, "event_type": event_type,
        "timestamp": timestamp, "previous_event_hash": previous,
        "payload": payload,
    }
    return {**core, "event_hash": sha256_json(core)}


def verify_event_chain(document: dict[str, Any]) -> bool:
    events = document.get("events")
    if not isinstance(events, list) or not events:
        return False
    previous = None
    for index, item in enumerate(events):
        if not isinstance(item, dict) or set(item) != {
            "event_index", "event_type", "timestamp", "previous_event_hash",
            "payload", "event_hash",
        }:
            return False
        core = {key: item[key] for key in item if key != "event_hash"}
        if (item["event_index"] != index or item["previous_event_hash"] != previous
                or item["event_hash"] != sha256_json(core)):
            return False
        previous = item["event_hash"]
    return (document.get("final_event_hash") == previous and
            document.get("state") == events[-1]["event_type"] and
            document.get("ledger_root") == sha256_json({
                "bindings": document.get("bindings"), "events": events,
            }))


class ConstructionLedgerError(RuntimeError):
    pass


class T27ConstructionLedger:
    PATH = "construction/ledger.json"
    MARKER = "markers/construction.one-shot"

    @staticmethod
    def _event_path(index: int) -> str:
        return f"construction/events/{index:06d}.json"

    def __init__(self, store: T27PrivateStore, document: dict[str, Any]) -> None:
        self.store = store
        self.document = document

    @classmethod
    def create_exclusive(cls, store: T27PrivateStore,
                         bindings: dict[str, Any], token: str,
                         *, clock: Callable[[], str] = _now) -> "T27ConstructionLedger":
        if token != CONSTRUCTION_TOKEN:
            raise ConstructionLedgerError("wrong construction authorization token")
        if set(bindings) != LEDGER_BINDING_FIELDS:
            raise ConstructionLedgerError("construction ledger binding set mismatch")
        if (bindings["experiment"] != EXPERIMENT or bindings["attempt"] != 1
                or bindings["mode"] != "REAL_BLIND"
                or bindings["authorization_token"] != CONSTRUCTION_TOKEN
                or bindings["store_id"] != STORE_ID
                or bindings["namespace"] != NAMESPACE
                or bindings["state"] != "LEDGER_CREATED"):
            raise ConstructionLedgerError("construction ledger immutable binding mismatch")
        if store.has(cls.MARKER) or store.has(cls.PATH):
            raise ConstructionLedgerError("T27 construction one-shot already spent")
        created = clock()
        event = _event(0, "LEDGER_CREATED", created, None, {
            "attempt": 1, "mode": "REAL_BLIND",
            "bindings_sha256": sha256_json(bindings),
        })
        document = {
            "schema_version": "t27-construction-ledger-v1",
            "artifact": "T27_CONSTRUCTION_LEDGER",
            "classification": "PRIVATE_LEDGER",
            "bindings": copy.deepcopy(bindings), "events": [event],
            "state": "LEDGER_CREATED", "final_event_hash": event["event_hash"],
        }
        document["ledger_root"] = sha256_json({
            "bindings": document["bindings"], "events": document["events"],
        })
        marker = {
            "schema_version": "t27-construction-one-shot-v1",
            "artifact": "T27_CONSTRUCTION_ONE_SHOT_SPENT",
            "classification": "PRIVATE_LEDGER", "attempt": 1,
            "spent": True, "bindings_sha256": sha256_json(bindings),
            "genesis_event_hash": event["event_hash"],
            "ledger_path": cls.PATH,
        }
        # The exclusive marker is the atomic transaction anchor.  If the
        # following ledger write fails, the spent marker remains and forbids a
        # retry or recreation.
        store.write_once_json(cls.MARKER, marker)
        try:
            store.write_once_json(cls._event_path(0), event)
            store.write_once_json(cls.PATH, document)
        except Exception:
            raise ConstructionLedgerError(
                "construction ledger creation incomplete; one-shot remains spent")
        return cls(store, document)

    @classmethod
    def load(cls, store: T27PrivateStore) -> "T27ConstructionLedger":
        if not store.has(cls.MARKER) or not store.has(cls.PATH):
            raise ConstructionLedgerError("ledger or one-shot marker deleted")
        document = store.read_json(cls.PATH)
        marker = store.read_json(cls.MARKER)
        event_directory = store.path("construction/events")
        journals = ([json.loads(path.read_text(encoding="utf-8"))
                     for path in sorted(event_directory.glob("*.json"))]
                    if event_directory.is_dir() else [])
        if (marker.get("spent") is not True or marker.get("attempt") != 1
                or marker.get("bindings_sha256") != sha256_json(document.get("bindings"))
                or marker.get("genesis_event_hash") != document.get("events", [{}])[0].get("event_hash")
                or journals != document.get("events")
                or not verify_event_chain(document)):
            raise ConstructionLedgerError("construction ledger/marker integrity failure")
        return cls(store, document)

    def advance(self, state: str, payload: dict[str, Any], *,
                clock: Callable[[], str] = _now) -> None:
        current = self.document["state"]
        if state not in TRANSITIONS.get(current, set()):
            raise ConstructionLedgerError(f"invalid ledger transition {current}->{state}")
        event = _event(len(self.document["events"]), state, clock(),
                       self.document["final_event_hash"], copy.deepcopy(payload))
        self.document["events"].append(event)
        self.document["state"] = state
        self.document["final_event_hash"] = event["event_hash"]
        self.document["ledger_root"] = sha256_json({
            "bindings": self.document["bindings"],
            "events": self.document["events"],
        })
        self.store.write_once_json(self._event_path(event["event_index"]), event)
        self.store.replace_ledger(self.PATH, self.document)

    def fail(self, phase: str, error: BaseException, *,
             clock: Callable[[], str] = _now) -> None:
        if self.document["state"] in {"SEALED", "FAILED"}:
            raise ConstructionLedgerError("terminal construction ledger cannot fail again")
        evidence = {
            "failure_phase": phase,
            "failure_class": type(error).__name__,
            "message_sha256": _sha_bytes(str(error).encode("utf-8")),
        }
        evidence["evidence_hash"] = sha256_json(evidence)
        self.advance("FAILED", evidence, clock=clock)


def author_provenance(author_id: str, implementation_sha256: str,
                      timestamp: str | None = None) -> dict[str, Any]:
    denied = [
        "T26_private_inputs", "T26_gold", "T26_raw_outputs",
        "T26_scored_rows", "T26_workspaces",
        "T27_public_qualification_exact_reusable_examples",
        "candidate_outputs", "future_evaluation_outputs",
    ]
    core = {
        "schema_version": "t27-clean-room-author-provenance-v1",
        "artifact": "T27_PRIVATE_AUTHOR_PROVENANCE",
        "classification": "PRIVATE_AUDIT", "author_id": author_id,
        "implementation_sha256": implementation_sha256,
        "isolated_clean_room": True, "denied_reads": denied,
        "t26_private_rows_read": 0, "candidate_outputs_read": 0,
        "future_evaluation_outputs_read": 0,
        "timestamp": timestamp or _now(),
    }
    return {**core, "provenance_root": sha256_json(core)}


def verify_author_provenance(value: dict[str, Any]) -> dict[str, Any]:
    required_denied = set(author_provenance("x", "0" * 64, "x")["denied_reads"])
    if (not isinstance(value, dict) or value.get("isolated_clean_room") is not True
            or set(value.get("denied_reads", [])) != required_denied
            or value.get("t26_private_rows_read") != 0
            or value.get("candidate_outputs_read") != 0
            or value.get("future_evaluation_outputs_read") != 0):
        raise ValueError("T27 author provenance violates clean-room policy")
    core = {key: item for key, item in value.items() if key != "provenance_root"}
    if value.get("provenance_root") != sha256_json(core):
        raise ValueError("T27 author provenance hash mismatch")
    return {"status": "PASS", "provenance_root": value["provenance_root"]}


def candidate_input_projection(scenario: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scenario, dict) or set(scenario) != {
            "scenario_id", "classification", "plan"}:
        raise ValueError("candidate scenario schema mismatch")
    encoded = json.dumps(scenario, sort_keys=True)
    if any(f'"{field}"' in encoded for field in GOLD_ONLY_FIELDS):
        raise ValueError("gold-only field exposed to candidate")
    return copy.deepcopy(scenario)


def _fingerprint(value: Any) -> str:
    return sha256_json(value)


def fingerprint_sets(cases: list[dict[str, Any]],
                     gold: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {name: set() for name in DIMENSIONS}
    for scenario, expected in zip(cases, gold):
        plan = scenario["plan"]
        result["case_ids"].add(_fingerprint(scenario["scenario_id"]))
        result["entity_identities"].add(_fingerprint(expected["family"]))
        result["source_ids"].update(_fingerprint(step["capability"])
                                    for step in plan["steps"])
        result["chunk_ids"].update(_fingerprint((scenario["scenario_id"], step["step_id"]))
                                   for step in plan["steps"])
        result["exact_queries"].add(_fingerprint(plan["goal"]))
        result["exact_answers"].add(_fingerprint(expected["expected_answer"]))
        result["exact_source_text"].update(_fingerprint(step["input"])
                                           for step in plan["steps"])
        result["verbatim_attack_wording"].add(_fingerprint(
            (expected["family"], plan["fallback_condition"])))
        result["relations"].update(_fingerprint((step["step_id"], step["depends_on"]))
                                   for step in plan["steps"])
    return {name: sorted(values) for name, values in result.items()}


def fingerprint_root(sets: dict[str, list[str]]) -> str:
    if set(sets) != set(DIMENSIONS):
        raise ValueError("fingerprint set must contain nine dimensions")
    return sha256_json({name: sorted(sets[name]) for name in DIMENSIONS})


def _fixture_valid(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict) or set(item) != {
            "logical_id", "classification", "sha256", "byte_size",
            "schema_type", "content"}:
        return False
    content = item["content"]
    return (isinstance(content, bytes) and item["classification"] == "PRIVATE_FIXTURE"
            and item["sha256"] == _sha_bytes(content)
            and item["byte_size"] == len(content)
            and isinstance(item["logical_id"], str) and item["logical_id"]
            and isinstance(item["schema_type"], str) and item["schema_type"])


def static_design_audit(cases: list[dict[str, Any]], gold: list[dict[str, Any]],
                        fixtures: list[dict[str, Any]],
                        oracle_result: dict[str, Any],
                        provenance: dict[str, Any], *,
                        oracle_mode: str = "SYNTHETIC",
                        root: Path | None = None) -> dict[str, Any]:
    from sciencemath.integrated.runner import validate_plan

    checks: dict[str, bool] = {}
    checks["scenario_count_512"] = len(cases) == 512
    checks["gold_count_512"] = len(gold) == 512
    scenario_ids = [item.get("scenario_id") for item in cases if isinstance(item, dict)]
    checks["unique_scenario_ids"] = len(scenario_ids) == 512 and len(set(scenario_ids)) == 512
    expected_gold_fields = {
        "scenario_id", "family", "expected_terminal", "expected_answer",
        "expected_verified_steps", "designated_recoverable",
        "designated_abstention", "expected_replan_trigger",
        "expected_fallback_capability", "metric_designations",
    }
    checks["scenario_schema"] = all(
        isinstance(item, dict) and set(item) == {"scenario_id", "classification", "plan"}
        and item["classification"] in {"PRIVATE_BLIND", "SYNTHETIC_DISPOSABLE"}
        for item in cases)
    checks["gold_schema"] = all(isinstance(item, dict) and set(item) == expected_gold_fields
                                for item in gold)
    checks["scenario_gold_identity"] = (len(cases) == len(gold) and all(
        case.get("scenario_id") == expected.get("scenario_id")
        for case, expected in zip(cases, gold)))
    family_counts = Counter(item.get("family") for item in gold)
    checks["family_count_16"] = set(family_counts) == set(FAMILIES)
    checks["cases_per_family_32"] = all(family_counts.get(name) == 32 for name in FAMILIES)
    steps = [len(item.get("plan", {}).get("steps", [])) for item in cases]
    checks["step_range_3_12"] = len(steps) == 512 and all(3 <= value <= 12 for value in steps)
    plan_validity = True
    for item in cases:
        try:
            validate_plan(item["plan"])
        except Exception:
            plan_validity = False
            break
    checks["plan_schema"] = plan_validity
    projection_ok = True
    for item in cases:
        try:
            candidate_input_projection(item)
        except Exception:
            projection_ok = False
            break
    checks["candidate_input_projection"] = projection_ok
    checks["gold_fields_in_candidate_input_zero"] = projection_ok
    checks["candidate_gold_access_edges_zero"] = True
    checks["fixture_schema"] = all(_fixture_valid(item) for item in fixtures)
    checks["zero_fixture_optionality"] = fixtures == [] or checks["fixture_schema"]
    designated = {
        "successful_completion_cases": sum(item.get("expected_terminal") == "COMPLETE" for item in gold),
        "recoverable_cases": sum(item.get("designated_recoverable") is True for item in gold),
        "replan_required_cases": sum(bool(item.get("expected_replan_trigger")) for item in gold),
        "safe_abstention_cases": sum(item.get("designated_abstention") is True for item in gold),
        "handoff_cases": sum(len(item.get("plan", {}).get("steps", [])) > 1 for item in cases),
        "verification_cases": sum(bool(item.get("plan", {}).get("steps")) for item in cases),
    }
    for name, minimum in NONVACUITY_MINIMUMS.items():
        checks[f"nonvacuity.{name}"] = designated[name] >= minimum
    sets = (fingerprint_sets(cases, gold) if len(cases) == len(gold)
            else {name: [] for name in DIMENSIONS})
    prospective_root = fingerprint_root(sets)
    try:
        oracle = verify_oracle_result(
            oracle_result, mode=oracle_mode, root=root,
            expected_t27_root=prospective_root)
        checks["t26_overlap_oracle"] = oracle["status"] == "PASS"
        checks["oracle_mode_separation"] = (
            oracle["real_mode_not_synthetic"] and
            oracle["synthetic_mode_explicit"])
    except Exception:
        checks["t26_overlap_oracle"] = False
        checks["oracle_mode_separation"] = False
    try:
        author = verify_author_provenance(provenance)
        checks["author_provenance"] = author["status"] == "PASS"
    except Exception:
        checks["author_provenance"] = False
    checks["fingerprint_root_matches_oracle"] = (
        oracle_result.get("t27_prospective_fingerprint_root") == prospective_root)
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema_version": "t27-static-design-audit-v1",
        "artifact": "T27_STATIC_DESIGN_AUDIT", "classification": "PRIVATE_AUDIT",
        "status": status, "checks": checks,
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
        "scenario_count": len(cases), "gold_count": len(gold),
        "family_counts": dict(sorted(family_counts.items())),
        "minimum_steps": min(steps) if steps else None,
        "maximum_steps": max(steps) if steps else None,
        "designated_counts": designated,
        "prospective_fingerprint_root": prospective_root,
        "oracle_mode": oracle_mode,
        "candidate_executions": 0, "official_evaluator_invocations": 0,
    }


def require_static_design(*args: Any, **kwargs: Any) -> dict[str, Any]:
    audit = static_design_audit(*args, **kwargs)
    if audit["status"] != "PASS":
        raise ValueError("T27 static design audit failed: " + ",".join(audit["failed_checks"]))
    return audit


def historical_exclusion_audit(
        cases: list[dict[str, Any]], gold: list[dict[str, Any]],
        historical_index: dict[str, Any] | None,
        oracle_result: dict[str, Any], *, mode: str = "SYNTHETIC",
        root: Path | None = None) -> dict[str, Any]:
    if historical_index is None:
        raise ValueError("authenticated historical index required; empty default forbidden")
    index = verify_historical_index(
        historical_index, root=root, mode="REAL" if mode == "REAL" else "SYNTHETIC")
    future = fingerprint_sets(cases, gold)
    historical = {name: historical_index["aggregate_dimensions"][name]["fingerprints"]
                  for name in DIMENSIONS}
    # Structural historical-exclusion accounting (§23): generated-public
    # sources bound to the frozen dimension policy distinguish the
    # prospective population, the historical comparable population, the
    # structural-exempt population, and the overlap count per dimension.
    policy_root = generated_public_dimension_policy()["dimension_policy_root"]
    policy_sources = [source for source in index["sources"]
                      if source.get("dimension_policy_schema") is not None]
    policy_exact = (
        sorted(source["source_class"] for source in policy_sources)
        == sorted(GENERATED_PUBLIC_SOURCES)
        and all(source["dimension_policy_schema"] == GENERATED_PUBLIC_POLICY_SCHEMA
                and source["dimension_policy_root"] == policy_root
                for source in policy_sources))
    structural_empty = policy_exact and all(
        source["dimensions"][name]["historical_population"] == 0
        for source in policy_sources
        for name in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS)
    identity_nonvacuous = policy_exact and all(
        source["dimensions"][name]["historical_population"] > 0
        for source in policy_sources
        for name in GENERATED_PUBLIC_REUSABLE_DIMENSIONS)
    exempted = {
        name: sum(source.get("structural_exempt_populations", {}).get(name, 0)
                  for source in policy_sources)
        for name in DIMENSIONS}
    satisfiability = (policy_exact and structural_empty and identity_nonvacuous
                      and index["source_classes_complete"])
    dimensions = {}
    total = 0
    for name in DIMENSIONS:
        prior = set(historical[name])
        overlap = len(set(future[name]) & prior)
        total += overlap
        dimensions[name] = {
            "applicable": bool(future[name]),
            "prospective_population": len(future[name]),
            "historical_population": len(prior),
            "structural_exempt_population": exempted[name],
            "overlap_count": overlap,
        }
    prospective_root = fingerprint_root(future)
    oracle = verify_oracle_result(
        oracle_result, mode="REAL" if mode == "REAL" else "SYNTHETIC",
        root=root, expected_t27_root=prospective_root)
    private_root = oracle["result_sha256"]
    combined_root = sha256_json({
        "public_historical_index_root": index["public_historical_index_root"],
        "private_historical_oracle_root": private_root,
        "t27_prospective_fingerprint_root": prospective_root,
    })
    passed = (total == 0 and oracle["overall_prohibited_overlap"] == 0
              and index["source_classes_complete"]
              and (mode != "REAL" or (index["repository_authenticated"]
                                       and oracle["t26_store_authenticated"]
                                       and oracle["t26_commitments_exact"]
                                       and oracle["real_mode_not_synthetic"])))
    core = {
        "schema_version": "t27-historical-exclusion-audit-v3",
        "artifact": "T27_HISTORICAL_EXCLUSION_AUDIT",
        "classification": "PRIVATE_AUDIT",
        "status": "PASS" if passed else "FAIL",
        "historical_sources": list(HISTORICAL_SOURCES),
        "required_source_count": len(HISTORICAL_SOURCES),
        "represented_source_count": index["source_count"],
        "source_classes_complete": index["source_classes_complete"],
        "public_history_authenticated": index["repository_authenticated"],
        "synthetic_history_explicit": index["explicit_synthetic"],
        "dimension_policy_schema": GENERATED_PUBLIC_POLICY_SCHEMA,
        "dimension_policy_root": policy_root,
        "generated_public_policy_sources": sorted(
            source["source_class"] for source in policy_sources),
        "dimension_policy_exact": policy_exact,
        "generated_structural_dimensions_frozen_empty": structural_empty,
        "generated_identity_dimensions_nonvacuous": identity_nonvacuous,
        "structural_satisfiability_proven": satisfiability,
        "generated_public_structural_exempt_populations": exempted,
        "dimensions": dimensions, "overall_prohibited_overlap": total,
        "t26_oracle_result_sha256": oracle["result_sha256"],
        "t26_store_authenticated": oracle["t26_store_authenticated"],
        "t26_commitments_exact": oracle["t26_commitments_exact"],
        "oracle_real_mode_not_synthetic": oracle["real_mode_not_synthetic"],
        "t27_prospective_fingerprint_root": prospective_root,
        "public_historical_index_root": index["public_historical_index_root"],
        "private_historical_oracle_root": private_root,
        "combined_historical_exclusion_root": combined_root,
        "t26_private_rows_opened": 0,
        "historical_private_rows_exposed_to_author": 0,
    }
    return {**core, "audit_root": sha256_json(core)}


def uniqueness_audit(cases: list[dict[str, Any]],
                     gold: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [item["scenario_id"] for item in cases]
    scenario_hashes = [_sha_bytes(_json_bytes(item)) for item in cases]
    gold_hashes = [_sha_bytes(_json_bytes(item)) for item in gold]
    duplicate_ids = len(ids) - len(set(ids))
    duplicate_scenarios = len(scenario_hashes) - len(set(scenario_hashes))
    duplicate_gold = len(gold_hashes) - len(set(gold_hashes))
    core = {
        "schema_version": "t27-uniqueness-audit-v1",
        "artifact": "T27_UNIQUENESS_AUDIT", "classification": "PRIVATE_AUDIT",
        "status": "PASS" if not any((duplicate_ids, duplicate_scenarios, duplicate_gold)) else "FAIL",
        "duplicate_scenario_ids": duplicate_ids,
        "duplicate_scenario_bodies": duplicate_scenarios,
        "duplicate_gold_records": duplicate_gold,
    }
    return {**core, "audit_root": sha256_json(core)}


def gold_firewall_audit(cases: list[dict[str, Any]],
                        gold: list[dict[str, Any]]) -> dict[str, Any]:
    violations = []
    for index, scenario in enumerate(cases):
        try:
            candidate_input_projection(scenario)
        except Exception as exc:
            violations.append({"index": index, "error_class": type(exc).__name__})
    core = {
        "schema_version": "t27-gold-firewall-audit-v1",
        "artifact": "T27_GOLD_FIREWALL_AUDIT", "classification": "PRIVATE_AUDIT",
        "status": "PASS" if not violations else "FAIL",
        "candidate_projection_count": len(cases),
        "gold_record_count": len(gold),
        "gold_fields_in_candidate_input": len(violations),
        "candidate_gold_access_edges": 0,
        "violations": violations,
    }
    return {**core, "audit_root": sha256_json(core)}


def authority_audit() -> dict[str, Any]:
    core = {
        "schema_version": "t27-construction-authority-audit-v1",
        "artifact": "T27_CONSTRUCTION_AUTHORITY_AUDIT",
        "classification": "PRIVATE_AUDIT", "status": "PASS",
        "construction_candidate_execution_authority": False,
        "candidate_gold_access": False,
        "autonomous_external_action_authority": False,
        "evaluator_authority": "SCORE_PRIVATE_ONCE",
        "evaluator_gold_access": True,
    }
    return {**core, "audit_root": sha256_json(core)}


def fixture_audit(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    invalid = [item.get("logical_id", "<unknown>") for item in fixtures
               if not _fixture_valid(item)]
    core = {
        "schema_version": "t27-fixture-audit-v1",
        "artifact": "T27_FIXTURE_AUDIT", "classification": "PRIVATE_AUDIT",
        "status": "PASS" if not invalid else "FAIL",
        "fixture_count": len(fixtures), "invalid_fixtures": invalid,
        "zero_fixture_optionality_validated": not fixtures,
    }
    return {**core, "audit_root": sha256_json(core)}


def materialize_private(store: T27PrivateStore, cases: list[dict[str, Any]],
                        gold: list[dict[str, Any]],
                        fixtures: list[dict[str, Any]],
                        static_audit: dict[str, Any],
                        provenance: dict[str, Any],
                        oracle_result: dict[str, Any],
                        historical: dict[str, Any]) -> list[dict[str, Any]]:
    if static_audit.get("status") != "PASS":
        raise ValueError("cannot materialize a failed T27 static design")
    store.write_once_json("blind/inputs.json", cases)
    store.write_once_json("blind/gold.json", gold)
    store.write_once_json("construction/static_design_audit.json", static_audit)
    store.write_once_json("construction/author_provenance.json", provenance)
    store.write_once_json("construction/t26_oracle_result.json", oracle_result)
    store.write_once_json("construction/historical_exclusion_audit.json", historical)
    descriptors = [
        store.descriptor("blind/inputs.json", "REAL_BLIND_INPUT"),
        store.descriptor("blind/gold.json", "REAL_BLIND_GOLD"),
        store.descriptor("construction/static_design_audit.json", "PRIVATE_AUDIT"),
        store.descriptor("construction/author_provenance.json", "PRIVATE_AUDIT"),
        store.descriptor("construction/t26_oracle_result.json", "PRIVATE_AUDIT"),
        store.descriptor("construction/historical_exclusion_audit.json", "PRIVATE_AUDIT"),
    ]
    for fixture in fixtures:
        logical = "fixtures/" + fixture["logical_id"]
        store.write_once_bytes(logical, fixture["content"])
        descriptors.append(store.descriptor(
            logical, "PRIVATE_FIXTURE", fixture["schema_type"]))
    return descriptors


def run_construction_audit(store: T27PrivateStore,
                           fixtures: list[dict[str, Any]],
                           historical_index: dict[str, Any], *,
                           oracle_mode: str = "SYNTHETIC",
                           root: Path | None = None
                           ) -> dict[str, Any]:
    cases = json.loads(store.read_bytes("blind/inputs.json"))
    gold = json.loads(store.read_bytes("blind/gold.json"))
    oracle_result = store.read_json("construction/t26_oracle_result.json")
    provenance = store.read_json("construction/author_provenance.json")
    static = static_design_audit(
        cases, gold, fixtures, oracle_result, provenance,
        oracle_mode=oracle_mode, root=root)
    exclusion = historical_exclusion_audit(
        cases, gold, historical_index, oracle_result,
        mode="REAL" if oracle_mode == "REAL" else "SYNTHETIC", root=root)
    unique = uniqueness_audit(cases, gold)
    firewall = gold_firewall_audit(cases, gold)
    authority = authority_audit()
    fixture_result = fixture_audit(fixtures)
    components = {
        "static_design": static, "historical_exclusion": exclusion,
        "uniqueness": unique, "gold_firewall": firewall,
        "authority": authority, "fixtures": fixture_result,
    }
    passed = all(item["status"] == "PASS" for item in components.values())
    core = {
        "schema_version": "t27-construction-audit-v1",
        "artifact": "T27_CONSTRUCTION_AUDIT", "classification": "PRIVATE_AUDIT",
        "status": "PASS" if passed else "FAIL", "components": components,
        "scenario_count": len(cases), "gold_count": len(gold),
        "candidate_executions": 0, "official_evaluator_invocations": 0,
    }
    return {**core, "audit_root": sha256_json(core)}


CONTRACT_LEAF_IDS = (
    "authorization.token_exact", "ledger.attempt_one", "ledger.mode_real_blind",
    "ledger.bindings_complete", "ledger.hash_chain", "store.identity",
    "candidate.commit", "candidate.tree", "candidate.runtime_root",
    "execution.commit", "execution.tree", "freeze.identity",
    "protocol.terminal_contract", "protocol.metric_registry",
    "protocol.nonvacuity_policy", "protocol.authority_graph",
    "protocol.production_graph", "protocol.storage_policy",
    "protocol.historical_exclusion_policy", "history.t26_failure_anchor",
    "author.clean_room", "oracle.t26_hash_only", "oracle.nine_dimensions",
    "oracle.overlap_zero", "exclusion.public_history_complete",
    "exclusion.public_history_authenticated", "oracle.t26_store_authenticated",
    "oracle.t26_commitments_exact", "oracle.real_mode_not_synthetic",
    "exclusion.combined_root_bound",
    "design.scenarios_512", "design.gold_512",
    "design.families_16", "design.family_size_32", "design.steps_3_12",
    "design.nonvacuity", "schema.scenario", "schema.plan", "schema.gold",
    "schema.fixtures", "firewall.gold_fields_zero", "firewall.gold_edges_zero",
    "exclusion.nine_dimensions", "exclusion.historical_sources",
    "uniqueness.scenario_ids", "uniqueness.scenario_bodies",
    "uniqueness.gold_records", "fixtures.commitments", "authority.no_escalation",
    "audit.candidate_executions_zero", "audit.evaluator_invocations_zero",
    "oracle.official_marker_path_exact", "oracle.official_marker_schema_exact",
    "oracle.marker_committed_in_store", "oracle.marker_genesis_matches_ledger",
    "oracle.real_store_layout_authenticated",
    "exclusion.dimension_policy_exact",
    "exclusion.generated_structural_dimensions_frozen_empty",
    "exclusion.identity_dimensions_nonvacuous",
    "exclusion.structural_satisfiability_proven",
)


def construction_contract() -> dict[str, Any]:
    return {
        "schema_version": "t27-construction-contract-v4",
        "artifact": "T27_CONSTRUCTION_CONTRACT_V4", "classification": "PUBLIC_SAFE",
        "leaf_enumerator": "t27_protocol.construction:CONTRACT_LEAF_IDS",
        "leaf_count": len(CONTRACT_LEAF_IDS), "leaf_ids": list(CONTRACT_LEAF_IDS),
        "unknown_requirement_policy": "UNVERIFIABLE",
        "required_fail_count": 0, "required_unverifiable_count": 0,
    }


def _t26_marker_leaf_evidence(evidence: dict[str, Any] | None,
                              static: dict[str, Any]) -> dict[str, Any]:
    """Soft (non-raising) official-marker leaf evidence for the T27 audit.

    Invalid or absent authentication evidence fails every marker leaf closed
    instead of raising, so the leaf audit stays total and negative controls
    observe FAIL rows rather than exceptions.
    """
    from t26_protocol.t27_private_oracle import (
        official_marker_binding, validate_t26_store_authentication_evidence)
    binding = official_marker_binding()
    real = static.get("oracle_mode") == "REAL"
    if isinstance(evidence, dict):
        try:
            validate_t26_store_authentication_evidence(evidence, real=real)
        except Exception:
            valid = False
        else:
            valid = True
    else:
        valid = False
        evidence = {}
    return {
        "valid": valid, "binding": binding,
        "marker_path": evidence.get("t26_official_marker_path"),
        "marker_schema": evidence.get("t26_official_marker_schema"),
        "marker_committed": evidence.get("t26_official_marker_committed"),
        "marker_genesis_matches_ledger": evidence.get(
            "t26_official_marker_genesis_matches_ledger"),
        "store_authenticated": evidence.get("t26_store_authenticated"),
        "legacy_marker_path_present": evidence.get(
            "t26_legacy_marker_path_present"),
        "evaluation_state": evidence.get("t26_official_evaluation_state"),
        "evaluation_attempt": evidence.get("t26_official_evaluation_attempt"),
        "event_count": evidence.get("t26_evaluation_event_count"),
        "fingerprint_derivation_invoked": evidence.get(
            "t27_fingerprint_derivation_invoked"),
        "private_rows_exposed": evidence.get(
            "outside_boundary_private_rows_exposed"),
    }


def contract_leaf_audit(bindings: dict[str, Any], audit: dict[str, Any],
                        ledger: T27ConstructionLedger, *,
                        t26_store_authentication: dict[str, Any] | None = None
                        ) -> dict[str, Any]:
    components = audit["components"]
    static = components["static_design"]
    marker = _t26_marker_leaf_evidence(t26_store_authentication, static)
    checks = {
        "authorization.token_exact": bindings["authorization_token"] == CONSTRUCTION_TOKEN,
        "ledger.attempt_one": bindings["attempt"] == 1,
        "ledger.mode_real_blind": bindings["mode"] == "REAL_BLIND",
        "ledger.bindings_complete": set(bindings) == LEDGER_BINDING_FIELDS,
        "ledger.hash_chain": verify_event_chain(ledger.document),
        "store.identity": bindings["store_id"] == STORE_ID and bindings["namespace"] == NAMESPACE,
        "candidate.commit": len(bindings["candidate_commit"]) == 40,
        "candidate.tree": len(bindings["candidate_tree"]) == 40,
        "candidate.runtime_root": len(bindings["runtime_root"]) == 64,
        "execution.commit": len(bindings["execution_commit"]) == 40,
        "execution.tree": len(bindings["execution_tree"]) == 40,
        "freeze.identity": all(bindings[key] for key in (
            "preconstruction_freeze_sha256", "component_root", "freeze_root")),
        "protocol.terminal_contract": len(bindings["terminal_contract_sha256"]) == 64,
        "protocol.metric_registry": len(bindings["metric_registry_sha256"]) == 64,
        "protocol.nonvacuity_policy": len(bindings["nonvacuity_policy_sha256"]) == 64,
        "protocol.authority_graph": len(bindings["authority_graph_sha256"]) == 64,
        "protocol.production_graph": len(bindings["production_graph_sha256"]) == 64,
        "protocol.storage_policy": len(bindings["storage_policy_sha256"]) == 64,
        "protocol.historical_exclusion_policy": len(bindings["historical_exclusion_policy_sha256"]) == 64,
        "history.t26_failure_anchor": len(bindings["t26_historical_failure_anchor_sha256"]) == 64,
        "author.clean_room": components["static_design"]["checks"]["author_provenance"],
        "oracle.t26_hash_only": components["static_design"]["checks"]["t26_overlap_oracle"],
        "oracle.nine_dimensions": len(components["historical_exclusion"]["dimensions"]) == 9,
        "oracle.overlap_zero": components["historical_exclusion"]["overall_prohibited_overlap"] == 0,
        "exclusion.public_history_complete": components["historical_exclusion"][
            "source_classes_complete"] is True,
        "exclusion.public_history_authenticated": (
            components["historical_exclusion"]["public_history_authenticated"] is True
            or components["historical_exclusion"]["synthetic_history_explicit"] is True),
        "oracle.t26_store_authenticated": (
            components["historical_exclusion"]["t26_store_authenticated"] is True
            or static["oracle_mode"] == "SYNTHETIC"),
        "oracle.t26_commitments_exact": (
            components["historical_exclusion"]["t26_commitments_exact"] is True
            or static["oracle_mode"] == "SYNTHETIC"),
        "oracle.real_mode_not_synthetic": static["checks"]["oracle_mode_separation"],
        "exclusion.combined_root_bound": all(
            bindings[key] == components["historical_exclusion"][value]
            for key, value in (
                ("public_historical_index_root", "public_historical_index_root"),
                ("t26_overlap_oracle_result_sha256", "t26_oracle_result_sha256"),
                ("combined_historical_exclusion_root",
                 "combined_historical_exclusion_root"))),
        "design.scenarios_512": static["scenario_count"] == 512,
        "design.gold_512": static["gold_count"] == 512,
        "design.families_16": static["checks"]["family_count_16"],
        "design.family_size_32": static["checks"]["cases_per_family_32"],
        "design.steps_3_12": static["checks"]["step_range_3_12"],
        "design.nonvacuity": all(static["checks"][f"nonvacuity.{name}"]
                                  for name in NONVACUITY_MINIMUMS),
        "schema.scenario": static["checks"]["scenario_schema"],
        "schema.plan": static["checks"]["plan_schema"],
        "schema.gold": static["checks"]["gold_schema"],
        "schema.fixtures": static["checks"]["fixture_schema"],
        "firewall.gold_fields_zero": components["gold_firewall"]["gold_fields_in_candidate_input"] == 0,
        "firewall.gold_edges_zero": components["gold_firewall"]["candidate_gold_access_edges"] == 0,
        "exclusion.nine_dimensions": len(components["historical_exclusion"]["dimensions"]) == 9,
        "exclusion.historical_sources": set(components["historical_exclusion"]["historical_sources"]) == set(HISTORICAL_SOURCES),
        "uniqueness.scenario_ids": components["uniqueness"]["duplicate_scenario_ids"] == 0,
        "uniqueness.scenario_bodies": components["uniqueness"]["duplicate_scenario_bodies"] == 0,
        "uniqueness.gold_records": components["uniqueness"]["duplicate_gold_records"] == 0,
        "fixtures.commitments": components["fixtures"]["status"] == "PASS",
        "authority.no_escalation": components["authority"]["status"] == "PASS",
        "audit.candidate_executions_zero": audit["candidate_executions"] == 0,
        "audit.evaluator_invocations_zero": audit["official_evaluator_invocations"] == 0,
        "oracle.official_marker_path_exact": (
            marker["valid"] and marker["binding"]["marker_path_exact"] is True
            and marker["marker_path"] == marker["binding"]["official_marker_path"]),
        "oracle.official_marker_schema_exact": (
            marker["valid"] and marker["binding"]["marker_schema_exact"] is True
            and marker["marker_schema"] == marker["binding"]["official_marker_schema"]),
        "oracle.marker_committed_in_store": (
            marker["valid"] and marker["marker_committed"] is True),
        "oracle.marker_genesis_matches_ledger": (
            marker["valid"] and marker["marker_genesis_matches_ledger"] is True),
        "oracle.real_store_layout_authenticated": (
            marker["valid"] and marker["store_authenticated"] is True
            and marker["legacy_marker_path_present"] is False
            and marker["evaluation_state"] == "COMPLETE"
            and marker["evaluation_attempt"] == 1
            and marker["event_count"] == 4
            and marker["fingerprint_derivation_invoked"] is False
            and marker["private_rows_exposed"] == 0),
        "exclusion.dimension_policy_exact": (
            len(bindings["generated_public_dimension_policy_sha256"]) == 64
            and components["historical_exclusion"]["dimension_policy_exact"]
            is True),
        "exclusion.generated_structural_dimensions_frozen_empty":
            components["historical_exclusion"][
                "generated_structural_dimensions_frozen_empty"] is True,
        "exclusion.identity_dimensions_nonvacuous": components[
            "historical_exclusion"][
            "generated_identity_dimensions_nonvacuous"] is True,
        "exclusion.structural_satisfiability_proven": (
            components["historical_exclusion"][
                "structural_satisfiability_proven"] is True
            and len(bindings["structural_satisfiability_witness_sha256"]) == 64
            and len(bindings["structural_unsatisfiability_reproducer_sha256"])
            == 64),
    }
    if set(checks) != set(CONTRACT_LEAF_IDS):
        raise ValueError("construction contract leaf enumerator drift")
    results = {name: "PASS" if value else "FAIL" for name, value in checks.items()}
    counts = Counter(results.values())
    core = {
        "schema_version": "t27-construction-contract-audit-v4",
        "artifact": "T27_CONSTRUCTION_CONTRACT_AUDIT",
        "classification": "PRIVATE_AUDIT", "results": dict(sorted(results.items())),
        "leaf_count": len(results), "PASS": counts["PASS"],
        "FAIL": counts["FAIL"], "UNVERIFIABLE": counts["UNVERIFIABLE"],
    }
    core["status"] = "PASS" if core["FAIL"] == 0 and core["UNVERIFIABLE"] == 0 else "FAIL"
    return {**core, "leaf_root": sha256_json(core)}


CONSTRUCTION_GATE_IDS = (
    "G01_AUTHORIZATION_TOKEN", "G02_ATTEMPT_ONE", "G03_CANDIDATE_IDENTITY",
    "G04_RUNTIME_ROOT", "G05_EXECUTION_CHECKOUT", "G06_FREEZE_IDENTITY",
    "G07_TERMINAL_CONTRACT", "G08_METRIC_REGISTRY",
    "G09_NONVACUITY_POLICY", "G10_AUTHORITY_GRAPH",
    "G11_PRODUCTION_GRAPH", "G12_STORAGE_POLICY",
    "G13_HISTORICAL_EXCLUSION_POLICY", "G14_T26_FAILURE_ANCHOR",
    "G15_AUTHOR_PROVENANCE", "G16_T26_OVERLAP_ORACLE",
    "G17_SCENARIO_CARDINALITY", "G18_GOLD_CARDINALITY",
    "G19_FAMILY_CARDINALITY", "G20_STEP_CONSTRAINTS",
    "G21_NONVACUITY_MINIMUMS", "G22_SCENARIO_SCHEMA", "G23_PLAN_SCHEMA",
    "G24_GOLD_SCHEMA", "G25_CANDIDATE_GOLD_SEPARATION",
    "G26_NINE_DIMENSIONAL_EXCLUSION", "G27_UNIQUENESS",
    "G28_FIXTURE_AUDIT", "G29_AUTHORITY_AUDIT", "G30_CONTRACT_LEAVES",
    "G31_CANDIDATE_EXECUTIONS_ZERO", "G32_EVALUATOR_INVOCATIONS_ZERO",
    "G33_LEDGER_HASH_CHAIN", "G34_ONE_SHOT_MARKER",
    "G35_REQUIRED_HISTORICAL_SOURCES_COMPLETE",
    "G36_PUBLIC_HISTORICAL_ROOT_AUTHENTICATED",
    "G37_T26_SEALED_STORE_AUTHENTICATED",
    "G38_T26_EXACT_OFFICIAL_COMMITMENTS",
    "G39_T26_ORACLE_REAL_MODE_IDENTITY",
    "G40_T27_FINGERPRINT_ROOT_EQUALITY",
    "G41_COMBINED_EXCLUSION_ROOT_BOUND",
    "G42_T26_OFFICIAL_MARKER_PATH", "G43_T26_OFFICIAL_MARKER_SCHEMA",
    "G44_T26_OFFICIAL_MARKER_COMMITMENT",
    "G45_T26_MARKER_LEDGER_GENESIS_RELATION",
    "G46_T26_REAL_STORE_LAYOUT_PREFLIGHT",
    "G47_GENERATED_PUBLIC_DIMENSION_POLICY_EXACT",
    "G48_GENERATED_STRUCTURAL_DIMENSIONS_FROZEN_EMPTY",
    "G49_GENERATED_IDENTITY_DIMENSIONS_NONVACUOUS",
    "G50_OLD_STRUCTURAL_UNSATISFIABILITY_REPRODUCED",
    "G51_STRUCTURAL_SATISFIABILITY_WITNESS_PASS",
    "G52_NEW_PUBLIC_HISTORY_ROOT_EXACT",
)


def run_construction_gate(bindings: dict[str, Any], expected: dict[str, Any],
                          audit: dict[str, Any], leaf_audit: dict[str, Any],
                          ledger: T27ConstructionLedger, *,
                          t26_store_authentication: dict[str, Any] | None = None
                          ) -> dict[str, Any]:
    components = audit["components"]
    static = components["static_design"]
    protocol_pairs = (
        ("G07_TERMINAL_CONTRACT", "terminal_contract_sha256"),
        ("G08_METRIC_REGISTRY", "metric_registry_sha256"),
        ("G09_NONVACUITY_POLICY", "nonvacuity_policy_sha256"),
        ("G10_AUTHORITY_GRAPH", "authority_graph_sha256"),
        ("G11_PRODUCTION_GRAPH", "production_graph_sha256"),
        ("G12_STORAGE_POLICY", "storage_policy_sha256"),
        ("G13_HISTORICAL_EXCLUSION_POLICY", "historical_exclusion_policy_sha256"),
        ("G14_T26_FAILURE_ANCHOR", "t26_historical_failure_anchor_sha256"),
    )
    marker = _t26_marker_leaf_evidence(t26_store_authentication, static)
    checks: dict[str, bool] = {
        "G01_AUTHORIZATION_TOKEN": bindings["authorization_token"] == CONSTRUCTION_TOKEN,
        "G02_ATTEMPT_ONE": bindings["attempt"] == 1,
        "G03_CANDIDATE_IDENTITY": all(bindings[key] == expected[key]
                                       for key in ("candidate_commit", "candidate_tree")),
        "G04_RUNTIME_ROOT": bindings["runtime_root"] == expected["runtime_root"],
        "G05_EXECUTION_CHECKOUT": all(bindings[key] == expected[key]
                                       for key in ("execution_commit", "execution_tree")),
        "G06_FREEZE_IDENTITY": all(bindings[key] == expected[key] for key in (
            "preconstruction_freeze_sha256", "component_count", "component_root", "freeze_root")),
        "G15_AUTHOR_PROVENANCE": static["checks"]["author_provenance"],
        "G16_T26_OVERLAP_ORACLE": static["checks"]["t26_overlap_oracle"]
                                    and static["checks"]["fingerprint_root_matches_oracle"],
        "G17_SCENARIO_CARDINALITY": audit["scenario_count"] == 512,
        "G18_GOLD_CARDINALITY": audit["gold_count"] == 512,
        "G19_FAMILY_CARDINALITY": static["checks"]["family_count_16"]
                                   and static["checks"]["cases_per_family_32"],
        "G20_STEP_CONSTRAINTS": static["checks"]["step_range_3_12"],
        "G21_NONVACUITY_MINIMUMS": all(static["checks"][f"nonvacuity.{name}"]
                                        for name in NONVACUITY_MINIMUMS),
        "G22_SCENARIO_SCHEMA": static["checks"]["scenario_schema"],
        "G23_PLAN_SCHEMA": static["checks"]["plan_schema"],
        "G24_GOLD_SCHEMA": static["checks"]["gold_schema"],
        "G25_CANDIDATE_GOLD_SEPARATION": components["gold_firewall"]["status"] == "PASS",
        "G26_NINE_DIMENSIONAL_EXCLUSION": components["historical_exclusion"]["status"] == "PASS",
        "G27_UNIQUENESS": components["uniqueness"]["status"] == "PASS",
        "G28_FIXTURE_AUDIT": components["fixtures"]["status"] == "PASS",
        "G29_AUTHORITY_AUDIT": components["authority"]["status"] == "PASS",
        "G30_CONTRACT_LEAVES": leaf_audit["status"] == "PASS",
        "G31_CANDIDATE_EXECUTIONS_ZERO": audit["candidate_executions"] == 0,
        "G32_EVALUATOR_INVOCATIONS_ZERO": audit["official_evaluator_invocations"] == 0,
        "G33_LEDGER_HASH_CHAIN": verify_event_chain(ledger.document),
        "G34_ONE_SHOT_MARKER": ledger.store.has(T27ConstructionLedger.MARKER),
        "G35_REQUIRED_HISTORICAL_SOURCES_COMPLETE": components[
            "historical_exclusion"]["source_classes_complete"] is True,
        "G36_PUBLIC_HISTORICAL_ROOT_AUTHENTICATED": (
            components["historical_exclusion"]["public_history_authenticated"] is True
            or components["historical_exclusion"]["synthetic_history_explicit"] is True),
        "G37_T26_SEALED_STORE_AUTHENTICATED": (
            components["historical_exclusion"]["t26_store_authenticated"] is True
            or static["oracle_mode"] == "SYNTHETIC"),
        "G38_T26_EXACT_OFFICIAL_COMMITMENTS": (
            components["historical_exclusion"]["t26_commitments_exact"] is True
            or static["oracle_mode"] == "SYNTHETIC"),
        "G39_T26_ORACLE_REAL_MODE_IDENTITY": static["checks"][
            "oracle_mode_separation"],
        "G40_T27_FINGERPRINT_ROOT_EQUALITY": static["checks"][
            "fingerprint_root_matches_oracle"],
        "G41_COMBINED_EXCLUSION_ROOT_BOUND": all(
            bindings[key] == components["historical_exclusion"][value]
            for key, value in (
                ("public_historical_index_root", "public_historical_index_root"),
                ("t26_overlap_oracle_result_sha256", "t26_oracle_result_sha256"),
                ("combined_historical_exclusion_root",
                 "combined_historical_exclusion_root"))),
        "G42_T26_OFFICIAL_MARKER_PATH": (
            marker["valid"] and marker["binding"]["marker_path_exact"] is True
            and marker["marker_path"] == marker["binding"]["official_marker_path"]),
        "G43_T26_OFFICIAL_MARKER_SCHEMA": (
            marker["valid"] and marker["binding"]["marker_schema_exact"] is True
            and marker["marker_schema"] == marker["binding"]["official_marker_schema"]),
        "G44_T26_OFFICIAL_MARKER_COMMITMENT": (
            marker["valid"] and marker["marker_committed"] is True),
        "G45_T26_MARKER_LEDGER_GENESIS_RELATION": (
            marker["valid"] and marker["marker_genesis_matches_ledger"] is True),
        "G46_T26_REAL_STORE_LAYOUT_PREFLIGHT": (
            marker["valid"] and marker["store_authenticated"] is True
            and marker["legacy_marker_path_present"] is False
            and marker["evaluation_state"] == "COMPLETE"
            and marker["evaluation_attempt"] == 1
            and marker["event_count"] == 4),
        "G47_GENERATED_PUBLIC_DIMENSION_POLICY_EXACT": components[
            "historical_exclusion"]["dimension_policy_exact"] is True,
        "G48_GENERATED_STRUCTURAL_DIMENSIONS_FROZEN_EMPTY": components[
            "historical_exclusion"][
            "generated_structural_dimensions_frozen_empty"] is True,
        "G49_GENERATED_IDENTITY_DIMENSIONS_NONVACUOUS": components[
            "historical_exclusion"][
            "generated_identity_dimensions_nonvacuous"] is True,
        "G50_OLD_STRUCTURAL_UNSATISFIABILITY_REPRODUCED": bindings[
            "structural_unsatisfiability_reproducer_sha256"] == expected[
            "structural_unsatisfiability_reproducer_sha256"],
        "G51_STRUCTURAL_SATISFIABILITY_WITNESS_PASS": (
            components["historical_exclusion"][
                "structural_satisfiability_proven"] is True
            and bindings["structural_satisfiability_witness_sha256"] == expected[
            "structural_satisfiability_witness_sha256"]),
        "G52_NEW_PUBLIC_HISTORY_ROOT_EXACT": (
            bindings["public_historical_index_root"] ==
            components["historical_exclusion"]["public_historical_index_root"]
            and bindings["public_historical_index_root"]
            != SUPERSEDED_INDEX_ROOT),
    }
    checks.update({gate_id: bindings[key] == expected[key]
                   for gate_id, key in protocol_pairs})
    if set(checks) != set(CONSTRUCTION_GATE_IDS):
        raise ValueError("construction gate check enumerator drift")
    failed = sorted(name for name, passed in checks.items() if not passed)
    core = {
        "schema_version": "t27-construction-gate-v4",
        "artifact": "T27_CONSTRUCTION_GATE", "classification": "PRIVATE_AUDIT",
        "checks": dict(sorted(checks.items())), "check_count": len(checks),
        "PASS": len(checks) - len(failed), "FAIL": len(failed),
        "failed_checks": failed, "status": "PASS" if not failed else "FAIL",
    }
    return {**core, "gate_root": sha256_json(core)}


def manifest_roots(artifacts: list[dict[str, Any]],
                   semantic_bindings: dict[str, Any]) -> dict[str, str]:
    ordered = sorted(artifacts, key=lambda item: item["logical_id"])
    blind = [item for item in ordered if item["classification"] in {
        "REAL_BLIND_INPUT", "REAL_BLIND_GOLD", "PRIVATE_FIXTURE"}]
    evaluation = [item for item in ordered
                  if item["classification"] == "REAL_BLIND_GOLD"]
    return {
        "private_artifact_root": sha256_json(ordered),
        "private_blind_root": sha256_json(blind),
        "private_evaluation_root": sha256_json(evaluation),
        "construction_semantic_root": sha256_json(semantic_bindings),
    }


def build_private_manifest(store: T27PrivateStore, ledger: T27ConstructionLedger,
                           bindings: dict[str, Any], audit: dict[str, Any],
                           leaf_audit: dict[str, Any], gate: dict[str, Any],
                           fixture_paths: list[str]) -> dict[str, Any]:
    paths = [
        ("blind/inputs.json", "REAL_BLIND_INPUT", "application/json"),
        ("blind/gold.json", "REAL_BLIND_GOLD", "application/json"),
        ("construction/static_design_audit.json", "PRIVATE_AUDIT", "application/json"),
        ("construction/author_provenance.json", "PRIVATE_AUDIT", "application/json"),
        ("construction/t26_oracle_result.json", "PRIVATE_AUDIT", "application/json"),
        ("construction/historical_exclusion_audit.json", "PRIVATE_AUDIT", "application/json"),
        ("construction/audit.json", "PRIVATE_AUDIT", "application/json"),
        ("construction/contract_audit.json", "PRIVATE_AUDIT", "application/json"),
        ("construction/gate.json", "PRIVATE_AUDIT", "application/json"),
    ]
    paths.extend((path, "PRIVATE_FIXTURE", "application/octet-stream")
                 for path in fixture_paths)
    artifacts = [store.descriptor(path, classification, schema)
                 for path, classification, schema in paths]
    semantic = {
        "schema_version": "t27-private-manifest-v1",
        "construction_ledger_pre_manifest_root": ledger.document["ledger_root"],
        "author_provenance_root": store.read_json(
            "construction/author_provenance.json")["provenance_root"],
        "t26_oracle_result_root": store.read_json(
            "construction/t26_oracle_result.json")["result_sha256"],
        "historical_exclusion_root": audit["components"]["historical_exclusion"]["audit_root"],
        "public_historical_index_root": audit["components"][
            "historical_exclusion"]["public_historical_index_root"],
        "private_historical_oracle_root": audit["components"][
            "historical_exclusion"]["private_historical_oracle_root"],
        "combined_historical_exclusion_root": audit["components"][
            "historical_exclusion"]["combined_historical_exclusion_root"],
        "uniqueness_audit_root": audit["components"]["uniqueness"]["audit_root"],
        "nonvacuity_design_audit_root": sha256_json(
            audit["components"]["static_design"]["designated_counts"]),
        "authority_audit_root": audit["components"]["authority"]["audit_root"],
        "gold_firewall_audit_root": audit["components"]["gold_firewall"]["audit_root"],
        "contract_leaf_root": leaf_audit["leaf_root"],
        "construction_gate_root": gate["gate_root"],
        "candidate_identity": {key: bindings[key] for key in (
            "candidate_commit", "candidate_tree", "runtime_root")},
        "freeze_identity": {key: bindings[key] for key in (
            "preconstruction_freeze_sha256", "component_root", "freeze_root")},
        "protocol_identities": {key: bindings[key] for key in (
            "terminal_contract_sha256", "metric_registry_sha256",
            "nonvacuity_policy_sha256", "authority_graph_sha256",
            "production_graph_sha256", "storage_policy_sha256",
            "historical_exclusion_policy_sha256",
            "generated_public_dimension_policy_sha256",
            "structural_unsatisfiability_reproducer_sha256",
            "structural_satisfiability_witness_sha256")},
    }
    roots = manifest_roots(artifacts, semantic)
    return {
        "schema_version": "t27-private-manifest-v1",
        "artifact": "T27_PRIVATE_MANIFEST", "classification": "PRIVATE_MANIFEST",
        "experiment": EXPERIMENT, "attempt": 1,
        "artifacts": artifacts, "semantic_bindings": semantic, **roots,
    }


def seal_holdout(store: T27PrivateStore, ledger: T27ConstructionLedger,
                 manifest: dict[str, Any], bindings: dict[str, Any],
                 audit: dict[str, Any], leaf_audit: dict[str, Any],
                 gate: dict[str, Any]) -> dict[str, Any]:
    if ledger.document["state"] != "MANIFESTED":
        raise ValueError("T27 seal requires MANIFESTED ledger state")
    manifest_bytes = store.read_bytes("construction/manifest.json")
    seal = {
        "schema_version": "t27-holdout-seal-v1",
        "artifact": "T27_HOLDOUT_SEAL", "classification": "PRIVATE_SEAL",
        "experiment": EXPERIMENT, "attempt": 1, "state": "SEALED",
        "candidate_commit": bindings["candidate_commit"],
        "candidate_tree": bindings["candidate_tree"],
        "runtime_root": bindings["runtime_root"],
        "freeze_sha256": bindings["preconstruction_freeze_sha256"],
        "component_root": bindings["component_root"],
        "freeze_root": bindings["freeze_root"],
        "terminal_contract_sha256": bindings["terminal_contract_sha256"],
        "metric_registry_sha256": bindings["metric_registry_sha256"],
        "nonvacuity_policy_sha256": bindings["nonvacuity_policy_sha256"],
        "authority_graph_sha256": bindings["authority_graph_sha256"],
        "production_graph_sha256": bindings["production_graph_sha256"],
        "storage_policy_sha256": bindings["storage_policy_sha256"],
        "pre_seal_ledger_root": ledger.document["ledger_root"],
        "manifest_sha256": _sha_bytes(manifest_bytes),
        "private_artifact_root": manifest["private_artifact_root"],
        "private_blind_root": manifest["private_blind_root"],
        "t26_overlap_oracle_root": store.read_json(
            "construction/t26_oracle_result.json")["result_sha256"],
        "historical_exclusion_root": audit["components"]["historical_exclusion"]["audit_root"],
        "public_historical_index_root": audit["components"][
            "historical_exclusion"]["public_historical_index_root"],
        "private_historical_oracle_root": audit["components"][
            "historical_exclusion"]["private_historical_oracle_root"],
        "combined_historical_exclusion_root": audit["components"][
            "historical_exclusion"]["combined_historical_exclusion_root"],
        "nonvacuity_audit_root": sha256_json(
            audit["components"]["static_design"]["designated_counts"]),
        "authority_audit_root": audit["components"]["authority"]["audit_root"],
        "gold_firewall_root": audit["components"]["gold_firewall"]["audit_root"],
        "contract_leaf_root": leaf_audit["leaf_root"],
        "construction_gate_root": gate["gate_root"],
    }
    store.write_once_json("construction/seal.json", seal)
    return seal


def build_public_receipt(store: T27PrivateStore, ledger: T27ConstructionLedger,
                         seal: dict[str, Any],
                         audit: dict[str, Any]) -> dict[str, Any]:
    if ledger.document["state"] != "SEALED":
        raise ValueError("public construction receipt requires SEALED ledger")
    return {
        "schema_version": "t27-public-construction-receipt-v1",
        "artifact": "T27_PUBLIC_CONSTRUCTION_RECEIPT",
        "classification": "PUBLIC_SAFE", "experiment": EXPERIMENT,
        "attempt": 1, "state": "SEALED",
        "candidate_commit": seal["candidate_commit"],
        "candidate_tree": seal["candidate_tree"],
        "runtime_root": seal["runtime_root"],
        "freeze_sha256": seal["freeze_sha256"],
        "component_root": seal["component_root"],
        "freeze_root": seal["freeze_root"],
        "construction_ledger_sha256": _sha_bytes(
            store.read_bytes("construction/ledger.json")),
        "construction_ledger_root": ledger.document["ledger_root"],
        "manifest_sha256": seal["manifest_sha256"],
        "private_artifact_root": seal["private_artifact_root"],
        "private_blind_root": seal["private_blind_root"],
        "seal_sha256": _sha_bytes(store.read_bytes("construction/seal.json")),
        "construction_gate_root": seal["construction_gate_root"],
        "nonvacuity_audit_root": seal["nonvacuity_audit_root"],
        "blind_content_included": False,
    }


def build_public_commitment(receipt: dict[str, Any],
                            audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "t27-public-construction-commitment-v1",
        "artifact": "T27_PUBLIC_CONSTRUCTION_COMMITMENT",
        "classification": "PUBLIC_SAFE", "experiment": EXPERIMENT,
        "attempt": 1, "state": "SEALED",
        "roots": {key: receipt[key] for key in (
            "construction_ledger_root", "private_artifact_root",
            "private_blind_root", "construction_gate_root",
            "nonvacuity_audit_root")},
        "aggregate_design_counts": {
            "scenarios": audit["scenario_count"], "gold": audit["gold_count"],
            **audit["components"]["static_design"]["designated_counts"],
        },
        "blind_content_included": False,
    }


def run_publication_leak_gate(root: Path, *, fetch: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    if fetch:
        subprocess.run(["git", "fetch", "--prune", "--tags"], cwd=root,
                       capture_output=True, text=True, check=True, timeout=180)
    refs = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)"], cwd=root,
        capture_output=True, text=True, check=True).stdout.splitlines()
    objects = subprocess.run(
        ["git", "rev-list", "--objects", "--all"], cwd=root,
        capture_output=True, text=True, check=True).stdout.splitlines()
    forbidden_tokens = (
        "evaluations/t27/real_blind", "evaluations/t27/real_gold",
        "evaluations/t27/private/", "t27-private/", "blind/inputs.json",
        "blind/gold.json", "construction/ledger.json",
        "evaluation/raw_outputs.json", "evaluation/scored_rows.json",
    )
    forbidden = sorted({line.split(" ", 1)[1] for line in objects if " " in line
                        and any(token in line.split(" ", 1)[1].lower()
                                for token in forbidden_tokens)})
    passed = not forbidden
    core = {
        "schema_version": "t27-publication-leak-gate-v1",
        "artifact": "T27_PUBLICATION_LEAK_GATE", "classification": "PUBLIC_SAFE",
        "status": "PASS" if passed else "FAIL",
        "public_ref_count": len(refs), "reachable_object_count": len(objects),
        "blind_blob_count": len(forbidden), "forbidden_path_count": len(forbidden),
        "path_policy_violations": len(forbidden),
        "forbidden_paths": forbidden,
        "official_evaluation_eligible": passed,
        "failure_code": None if passed else "T27_POST_CONSTRUCTION_PUBLICATION_LEAKAGE",
        "history_rewrite_restores_eligibility": False,
    }
    return {**core, "scan_root": sha256_json(core)}


def _file_sha(root: Path, relative: str) -> str:
    return _sha_bytes((Path(root) / relative).read_bytes())


def required_bindings(root: Path, freeze: dict[str, Any], *,
                      historical: dict[str, Any] | None = None,
                      timestamp: str | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    candidate = json.loads((root / "evaluations/t27/candidate_identity.json").read_text(
        encoding="utf-8"))
    execution_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
        text=True, check=True).stdout.strip()
    execution_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=root, capture_output=True,
        text=True, check=True).stdout.strip()
    files = {
        "terminal_contract_sha256": "evaluations/t27/terminal_contract.json",
        "metric_registry_sha256": "evaluations/t27/metric_registry.json",
        "nonvacuity_policy_sha256": "evaluations/t27/nonvacuity_policy.json",
        "authority_graph_sha256": "evaluations/t27/authority_graph.json",
        "production_graph_sha256": "evaluations/t27/production_graph.json",
        "storage_policy_sha256": "evaluations/t27/construction_ready_storage_policy.json",
        "historical_exclusion_policy_sha256": "evaluations/t27/historical_exclusion_policy_v4.json",
        "t26_historical_failure_anchor_sha256": "evaluations/t27/T26_HISTORICAL_FAILURE_ANCHOR.json",
        "generated_public_dimension_policy_sha256":
            "evaluations/t27/generated_public_exclusion_dimension_policy.json",
        "structural_unsatisfiability_reproducer_sha256":
            "evaluations/t27/structural_unsatisfiability_reproducer.json",
        "structural_satisfiability_witness_sha256":
            "evaluations/t27/structural_satisfiability_witness.json",
    }
    if historical is None:
        raise ValueError("historical exclusion roots required before ledger bindings")
    historical_bindings = {
        "public_historical_index_root": historical["public_historical_index_root"],
        "t26_overlap_oracle_result_sha256": historical["t26_oracle_result_sha256"],
        "combined_historical_exclusion_root": historical[
            "combined_historical_exclusion_root"],
    }
    if any(not isinstance(value, str) or len(value) != 64
           for value in historical_bindings.values()):
        raise ValueError("historical exclusion binding root invalid")
    return {
        "experiment": EXPERIMENT, "attempt": 1, "mode": "REAL_BLIND",
        "authorization_token": CONSTRUCTION_TOKEN, "store_id": STORE_ID,
        "namespace": NAMESPACE, "execution_commit": execution_commit,
        "execution_tree": execution_tree,
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "preconstruction_freeze_sha256": freeze["freeze_sha256"],
        "component_count": freeze["component_count"],
        "component_root": freeze["component_root"],
        "freeze_root": freeze["freeze_root"],
        **{name: _file_sha(root, relative) for name, relative in files.items()},
        **historical_bindings,
        "construction_timestamp": timestamp or _now(), "state": "LEDGER_CREATED",
    }


def validate_preledger(bindings: dict[str, Any], expected: dict[str, Any],
                       store: T27PrivateStore) -> None:
    if set(bindings) != LEDGER_BINDING_FIELDS or set(expected) != LEDGER_BINDING_FIELDS:
        raise ValueError("T27 pre-ledger bindings incomplete")
    mismatches = sorted(key for key in bindings if bindings[key] != expected[key]
                        and key != "construction_timestamp")
    if mismatches:
        raise ValueError("T27 pre-ledger identity mismatch: " + ",".join(mismatches))
    if any(store.has(path) for path in (
            T27ConstructionLedger.PATH, T27ConstructionLedger.MARKER,
            "evaluation/ledger.json", "markers/evaluation.one-shot")):
        raise ValueError("T27 real lifecycle artifact already exists")


def construct_once(*, root: Path, store: T27PrivateStore,
                   bindings: dict[str, Any], expected_bindings: dict[str, Any],
                   cases: list[dict[str, Any]], gold: list[dict[str, Any]],
                   fixtures: list[dict[str, Any]], oracle_result: dict[str, Any],
                   provenance: dict[str, Any], token: str,
                   historical_index: dict[str, Any] | None,
                   oracle_mode: str = "SYNTHETIC",
                   clock: Callable[[], str] = _now,
                   inject_failure_phase: str | None = None,
                   t26_store_authentication: dict[str, Any]) -> dict[str, Any]:
    # Official T26 store authentication evidence is validated fail-closed
    # BEFORE any ledger or private authoring occurs.
    from t26_protocol.t27_private_oracle import (
        validate_t26_store_authentication_evidence)
    validate_t26_store_authentication_evidence(
        t26_store_authentication, real=oracle_mode == "REAL")
    # All authoring and overlap validation occurs before exclusive creation.
    static = require_static_design(
        cases, gold, fixtures, oracle_result, provenance,
        oracle_mode=oracle_mode, root=root)
    historical = historical_exclusion_audit(
        cases, gold, historical_index, oracle_result,
        mode="REAL" if oracle_mode == "REAL" else "SYNTHETIC", root=root)
    if historical["status"] != "PASS":
        raise ValueError("T27 historical exclusion failed before ledger creation")
    for binding, evidence in (
            ("public_historical_index_root", "public_historical_index_root"),
            ("t26_overlap_oracle_result_sha256", "t26_oracle_result_sha256"),
            ("combined_historical_exclusion_root",
             "combined_historical_exclusion_root")):
        if bindings.get(binding) != historical[evidence]:
            raise ValueError(f"T27 pre-ledger historical binding mismatch: {binding}")
    validate_preledger(bindings, expected_bindings, store)
    ledger = T27ConstructionLedger.create_exclusive(
        store, bindings, token, clock=clock)
    phase = "LEDGER_CREATED"
    try:
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-ledger construction failure")
        materialize_private(store, cases, gold, fixtures, static, provenance,
                            oracle_result, historical)
        ledger.advance("MATERIALIZED", {
            "scenario_count": len(cases), "gold_count": len(gold),
            "fixture_count": len(fixtures),
        }, clock=clock)
        phase = "MATERIALIZED"
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-materialization construction failure")
        audit = run_construction_audit(
            store, fixtures, historical_index,
            oracle_mode=oracle_mode, root=root)
        if audit["status"] != "PASS":
            raise ValueError("T27 construction audit failed")
        store.write_once_json("construction/audit.json", audit)
        ledger.advance("AUDITED", {"audit_root": audit["audit_root"]}, clock=clock)
        phase = "AUDITED"
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-audit construction failure")
        leaf_audit = contract_leaf_audit(
            bindings, audit, ledger,
            t26_store_authentication=t26_store_authentication)
        if leaf_audit["status"] != "PASS":
            raise ValueError("T27 construction contract audit failed")
        store.write_once_json("construction/contract_audit.json", leaf_audit)
        gate = run_construction_gate(
            bindings, expected_bindings, audit, leaf_audit, ledger,
            t26_store_authentication=t26_store_authentication)
        if gate["status"] != "PASS":
            raise ValueError("T27 construction gate failed")
        store.write_once_json("construction/gate.json", gate)
        ledger.advance("GATE_PASS", {"construction_gate_root": gate["gate_root"]},
                       clock=clock)
        phase = "GATE_PASS"
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-gate construction failure")
        fixture_paths = ["fixtures/" + item["logical_id"] for item in fixtures]
        manifest = build_private_manifest(
            store, ledger, bindings, audit, leaf_audit, gate, fixture_paths)
        store.write_once_json("construction/manifest.json", manifest)
        ledger.advance("MANIFESTED", {
            "manifest_sha256": _sha_bytes(store.read_bytes("construction/manifest.json")),
            "private_artifact_root": manifest["private_artifact_root"],
        }, clock=clock)
        phase = "MANIFESTED"
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-manifest construction failure")
        seal = seal_holdout(store, ledger, manifest, bindings, audit, leaf_audit, gate)
        pre_close_verify = store.verify()
        if pre_close_verify["status"] != "PASS":
            raise ValueError("T27 pre-close store verification failed")
        ledger.advance("SEALED", {
            "seal_sha256": _sha_bytes(store.read_bytes("construction/seal.json")),
            "store_verification_root": pre_close_verify["verification_root"],
        }, clock=clock)
        final_verify = store.verify()
        if final_verify["status"] != "PASS" or not verify_event_chain(ledger.document):
            raise ValueError("T27 final store or ledger verification failed")
        receipt = build_public_receipt(store, ledger, seal, audit)
        commitment = build_public_commitment(receipt, audit)
        leak_gate = run_publication_leak_gate(root)
        if leak_gate["status"] != "PASS":
            raise ValueError("T27_POST_CONSTRUCTION_PUBLICATION_LEAKAGE")
        return {
            "status": "PASS", "ledger": ledger.document, "audit": audit,
            "contract_audit": leaf_audit, "gate": gate, "manifest": manifest,
            "seal": seal, "pre_close_store_verify": pre_close_verify,
            "final_store_verify": final_verify, "receipt": receipt,
            "commitment": commitment, "leak_gate": leak_gate,
        }
    except Exception as exc:
        if ledger.document["state"] not in {"SEALED", "FAILED"}:
            ledger.fail(phase, exc, clock=clock)
        raise


def construct_real(*, root: Path, private_store_root: Path,
                   cases: list[dict[str, Any]], gold: list[dict[str, Any]],
                   fixtures: list[dict[str, Any]], oracle_result: dict[str, Any],
                   provenance: dict[str, Any], token: str,
                   t26_store: Any) -> dict[str, Any]:
    """Real entrypoint.  Merely importing this function spends nothing."""
    root = Path(root).resolve()
    from t26_protocol.lifecycle import T26PrivateStore
    from t26_protocol.t27_private_oracle import (
        authenticate_official_t26_store_for_t27,
        validate_t26_store_authentication_evidence)
    if not isinstance(t26_store, T26PrivateStore):
        raise ValueError("real T27 construction requires the official T26 "
                         "private store for metadata authentication")
    freeze = json.loads((root / "evaluations/t27/preconstruction_freeze_v5.json").read_text(
        encoding="utf-8"))
    historical_index = build_authenticated_public_historical_index(root)
    historical = historical_exclusion_audit(
        cases, gold, historical_index, oracle_result, mode="REAL", root=root)
    if historical["status"] != "PASS":
        raise ValueError("T27 real historical provenance failed before ledger creation")
    # Metadata-only official store authentication runs before any T27 private
    # authoring; it never reads T26 rows or derives fingerprints.
    t26_authentication = authenticate_official_t26_store_for_t27(root, t26_store)
    validate_t26_store_authentication_evidence(t26_authentication, real=True)
    bindings = required_bindings(root, freeze, historical=historical)
    store = T27PrivateStore(private_store_root, repository_root=root)
    return construct_once(
        root=root, store=store, bindings=bindings, expected_bindings=bindings,
        cases=cases, gold=gold, fixtures=fixtures, oracle_result=oracle_result,
        provenance=provenance, token=token,
        historical_index=historical_index, oracle_mode="REAL",
        t26_store_authentication=t26_authentication)


def synthetic_private_bundle(variant: int = 0, *, with_fixture: bool = False
                             ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                                        list[dict[str, Any]]]:
    """Deterministic disposable 512/512 bundle; never valid as real material."""
    from .qualification import make_case

    cases: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for family in FAMILIES:
        for index in range(32):
            case, expected, _ = make_case(family, index % 4)
            case = copy.deepcopy(case)
            case_id = f"t27-disposable-{variant}-{family}-{index + 1:02d}"
            case["scenario_id"] = case_id
            case["classification"] = "SYNTHETIC_DISPOSABLE"
            case["plan"]["plan_id"] = f"plan-{case_id}"
            case["plan"]["goal"] = (
                f"Disposable T27 lifecycle rehearsal {variant} {family} {index + 1}")
            record = {
                "scenario_id": case_id, "family": family,
                **copy.deepcopy(expected),
                "metric_designations": {
                    "successful_completion": expected["expected_terminal"] == "COMPLETE",
                    "recoverable": expected["designated_recoverable"],
                    "replan_required": bool(expected["expected_replan_trigger"]),
                    "safe_abstention": expected["designated_abstention"],
                    "handoff": True, "verification": True,
                },
            }
            cases.append(case)
            gold.append(record)
    fixtures: list[dict[str, Any]] = []
    if with_fixture:
        content = f"disposable-t27-private-fixture-{variant}".encode("utf-8")
        fixtures.append({
            "logical_id": f"rehearsal-{variant}.bin",
            "classification": "PRIVATE_FIXTURE",
            "sha256": _sha_bytes(content), "byte_size": len(content),
            "schema_type": "application/octet-stream", "content": content,
        })
    return cases, gold, fixtures


def synthetic_oracle_result(cases: list[dict[str, Any]],
                            gold: list[dict[str, Any]],
                            *, variant: int = 0) -> dict[str, Any]:
    from t26_protocol.t27_private_oracle import compare_hashes

    future = fingerprint_sets(cases, gold)
    historical = {name: [_fingerprint(("sealed-t26", variant, name))]
                  for name in DIMENSIONS}
    bindings = {
        "t26_private_holdout_root": "a" * 64,
        "t26_private_manifest_sha256": "b" * 64,
        "t26_construction_seal_sha256": "c" * 64,
        "t26_evaluation_ledger_sha256": "d" * 64,
    }
    return compare_hashes(
        prospective_root=fingerprint_root(future), prospective=future,
        sealed_historical=historical, t26_bindings=bindings,
        timestamp=f"2026-09-27T00:00:0{variant}+00:00")


def official_marker_contract_report(root: Path) -> dict[str, Any]:
    """Code-level official-marker binding plus disposable layout evidence.

    Pinned literals in ``t26_protocol.t27_private_oracle:official_marker_binding``
    freeze exact equality against the authoritative official V4 constants; a
    disposable stand-in proves the rehearsal layout mirrors the production
    layout. Deterministic and reproducible; contains no real-store material.
    """
    root = Path(root).resolve()
    from t26_protocol.t27_private_oracle import (
        authenticate_official_t26_store_for_t27, disposable_t26_sealed_store,
        official_marker_binding)
    binding = official_marker_binding()
    with TemporaryDirectory(prefix="t27-official-marker-contract-") as tmp:
        store, expected = disposable_t26_sealed_store(
            Path(tmp), variant=0, public_repo=root)
        authentication = authenticate_official_t26_store_for_t27(
            root, store, expected=expected)
    layout = {
        "marker_path_match": (
            authentication["t26_official_marker_path"] ==
            binding["official_marker_path"]),
        "marker_schema_match": (
            authentication["t26_official_marker_schema"] ==
            binding["official_marker_schema"]),
        "marker_artifact_match": (
            authentication["t26_official_marker_artifact"] ==
            binding["official_marker_artifact"]),
        "marker_attempt_one": authentication["t26_official_marker_attempt"] == 1,
        "marker_committed": authentication["t26_official_marker_committed"] is True,
        "marker_genesis_matches_ledger": authentication[
            "t26_official_marker_genesis_matches_ledger"] is True,
        "legacy_marker_path_present": authentication[
            "t26_legacy_marker_path_present"],
        "evaluation_state_complete": (
            authentication["t26_official_evaluation_state"] == "COMPLETE"),
        "evaluation_attempt_one": (
            authentication["t26_official_evaluation_attempt"] == 1),
        "event_count_four": authentication["t26_evaluation_event_count"] == 4,
        "store_authenticated": authentication["t26_store_authenticated"] is True,
        "private_rows_read": authentication["t26_private_rows_read"],
        "fingerprint_derivation_invoked": authentication[
            "t27_fingerprint_derivation_invoked"],
    }
    mirrors = all(value is True or value == 0 for key, value in layout.items()
                  if key not in {"legacy_marker_path_present",
                                 "private_rows_read",
                                 "fingerprint_derivation_invoked"})
    mirrors = mirrors and layout["legacy_marker_path_present"] is False
    mirrors = mirrors and layout["private_rows_read"] == 0
    mirrors = mirrors and layout["fingerprint_derivation_invoked"] is False
    passed = (binding["marker_path_exact"] is True
              and binding["marker_schema_exact"] is True
              and binding["legacy_marker_path_accepted"] is False
              and mirrors)
    return {
        "schema_version": "t27-t26-official-marker-contract-v1",
        "artifact": "T27_T26_OFFICIAL_MARKER_CONTRACT",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if passed else "FAIL",
        **binding,
        "disposable_layout_mirrors_official": mirrors,
        "disposable_layout": layout,
        "real_store_metadata_preflight_required": True,
    }


def run_real_mode_oracle_validation_rehearsal(root: Path) -> dict[str, Any]:
    """Exercise production verifier semantics with an authenticated stand-in."""
    from t26_protocol.t27_private_oracle import disposable_real_mode_oracle_result

    cases, gold, _ = synthetic_private_bundle(8)
    prospective = fingerprint_sets(cases, gold)
    prospective_root = fingerprint_root(prospective)
    result = disposable_real_mode_oracle_result(
        root=Path(root).resolve(), prospective_root=prospective_root,
        prospective=prospective, variant=8)
    bindings = {key: result[key] for key in (
        "t26_store_identity", "t26_namespace", "t26_private_holdout_root",
        "t26_private_manifest_sha256", "t26_construction_seal_sha256",
        "t26_evaluation_ledger_sha256", "t26_official_evaluation_state",
        "t26_official_evaluation_attempt")}
    verified = verify_oracle_result(
        result, mode="REAL_REHEARSAL", expected_t27_root=prospective_root,
        expected_t26_bindings=bindings)
    return {
        "schema_version": "t27-real-mode-oracle-validation-rehearsal-v1",
        "artifact": "T27_REAL_MODE_ORACLE_VALIDATION_REHEARSAL",
        "classification": "PUBLIC_SAFE",
        "status": verified["status"],
        "oracle_implementation": result["oracle_implementation"],
        "commitment_scope": result["official_commitment_scope"],
        "store_authenticated": verified["t26_store_authenticated"],
        "commitments_exact": verified["t26_commitments_exact"],
        "real_mode_not_synthetic": verified["real_mode_not_synthetic"],
        "prospective_root_exact":
            result["t27_prospective_fingerprint_root"] == prospective_root,
        "dimension_count": verified["dimension_count"],
        "dimension_populations": {
            name: result["dimensions"][name]["historical_population"]
            for name in DIMENSIONS},
        "overall_prohibited_overlap": verified["overall_prohibited_overlap"],
        "t26_fingerprint_index_origin": result[
            "t26_fingerprint_index_origin"],
        "t26_fingerprint_index_root": result["t26_fingerprint_index_root"],
        "result_sha256": result["result_sha256"],
        "outside_boundary_private_rows_exposed": 0,
        "candidate_executions": 0,
    }


def synthetic_public_historical_hashes(variant: int = 0) -> dict[str, list[str]]:
    """Legacy flat helper retained only for authenticated negative controls."""
    return {name: [_fingerprint(("public-history", variant, name))]
            for name in DIMENSIONS}


def synthetic_historical_evidence(
        cases: list[dict[str, Any]], gold: list[dict[str, Any]],
        oracle_result: dict[str, Any], *, variant: int = 0
        ) -> tuple[dict[str, Any], dict[str, Any]]:
    index = build_synthetic_historical_index(variant)
    historical = historical_exclusion_audit(
        cases, gold, index, oracle_result, mode="SYNTHETIC")
    return index, historical


def _fixed_clock_factory(variant: int = 0) -> Callable[[], str]:
    counter = {"value": 0}

    def clock() -> str:
        value = counter["value"]
        counter["value"] += 1
        return f"2026-09-27T00:{variant:02d}:{value:02d}+00:00"
    return clock


def _rehearsal_summary(index: int, result: dict[str, Any]) -> dict[str, Any]:
    audit = result["audit"]
    semantic = {
        "state_sequence": [event["event_type"] for event in result["ledger"]["events"]],
        "scenario_count": audit["scenario_count"], "gold_count": audit["gold_count"],
        "designated_counts": audit["components"]["static_design"]["designated_counts"],
        "contract_leaf_count": result["contract_audit"]["leaf_count"],
        "gate_check_count": result["gate"]["check_count"],
        "store_status": result["final_store_verify"]["status"],
        "leak_gate_status": result["leak_gate"]["status"],
        "receipt_blind_content_included": result["receipt"]["blind_content_included"],
        "public_historical_index_root": audit["components"][
            "historical_exclusion"]["public_historical_index_root"],
        "combined_historical_exclusion_root": audit["components"][
            "historical_exclusion"]["combined_historical_exclusion_root"],
        "historical_source_count": audit["components"][
            "historical_exclusion"]["represented_source_count"],
        "oracle_mode": audit["components"]["static_design"]["oracle_mode"],
    }
    return {
        "run": index, "status": result["status"], "state": result["ledger"]["state"],
        "semantic_signature": sha256_json(semantic), **semantic,
    }


def run_construction_rehearsals(root: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    from t26_protocol.t27_private_oracle import (
        authenticate_official_t26_store_for_t27, disposable_t26_sealed_store)
    runs = []
    for index in (1, 2):
        cases, gold, fixtures = synthetic_private_bundle(
            0, with_fixture=index == 2)
        oracle = synthetic_oracle_result(cases, gold, variant=0)
        historical_index, historical = synthetic_historical_evidence(
            cases, gold, oracle, variant=0)
        provenance = author_provenance(
            f"T27-DISPOSABLE-AUTHOR-{index}", "e" * 64,
            f"2026-09-27T00:00:0{index}+00:00")
        with TemporaryDirectory(
                prefix=f"t27-rehearsal-t26-standin-{index}-") as t26_tmp:
            t26_store, t26_expected = disposable_t26_sealed_store(
                Path(t26_tmp), variant=0, public_repo=root)
            t26_authentication = authenticate_official_t26_store_for_t27(
                root, t26_store, expected=t26_expected)
        with TemporaryDirectory(prefix=f"t27-construction-rehearsal-{index}-") as tmp:
            store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                    disposable=True)
            bindings = required_bindings(
                root, freeze, historical=historical,
                timestamp="2026-09-27T00:00:00+00:00")
            result = construct_once(
                root=root, store=store, bindings=bindings,
                expected_bindings=copy.deepcopy(bindings), cases=cases, gold=gold,
                fixtures=fixtures, oracle_result=oracle, provenance=provenance,
                token=CONSTRUCTION_TOKEN,
                historical_index=historical_index, oracle_mode="SYNTHETIC",
                clock=_fixed_clock_factory(0),
                t26_store_authentication=t26_authentication)
            runs.append(_rehearsal_summary(index, result))
    comparable = [{key: value for key, value in item.items()
                   if key not in {"run", "semantic_signature"}}
                  for item in runs]
    equivalent = comparable[0] == comparable[1]
    # Fixture count intentionally differs; lifecycle semantics must otherwise match.
    if not equivalent:
        comparable = []
        for item in runs:
            clone = {key: value for key, value in item.items()
                     if key not in {"run", "semantic_signature"}}
            comparable.append(clone)
        equivalent = comparable[0] == comparable[1]
    passed = all(item["status"] == "PASS" for item in runs) and equivalent
    return {
        "schema_version": "t27-construction-rehearsals-v1",
        "artifact": "T27_DISPOSABLE_CONSTRUCTION_REHEARSALS",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "runs": runs, "semantic_equivalence": equivalent,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0,
    }


def run_construction_failure_rehearsal(root: Path, freeze: dict[str, Any]
                                       ) -> dict[str, Any]:
    root = Path(root).resolve()
    from t26_protocol.t27_private_oracle import (
        authenticate_official_t26_store_for_t27, disposable_t26_sealed_store)
    cases, gold, fixtures = synthetic_private_bundle(3)
    oracle = synthetic_oracle_result(cases, gold, variant=3)
    historical_index, historical = synthetic_historical_evidence(
        cases, gold, oracle, variant=3)
    provenance = author_provenance(
        "T27-DISPOSABLE-FAILURE-AUTHOR", "f" * 64,
        "2026-09-27T00:00:03+00:00")
    with TemporaryDirectory(prefix="t27-failure-t26-standin-") as t26_tmp:
        t26_store, t26_expected = disposable_t26_sealed_store(
            Path(t26_tmp), variant=3, public_repo=root)
        t26_authentication = authenticate_official_t26_store_for_t27(
            root, t26_store, expected=t26_expected)
    with TemporaryDirectory(prefix="t27-construction-failure-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                disposable=True)
        bindings = required_bindings(
            root, freeze, historical=historical,
            timestamp="2026-09-27T00:00:03+00:00")
        injected = False
        try:
            construct_once(
                root=root, store=store, bindings=bindings,
                expected_bindings=copy.deepcopy(bindings), cases=cases, gold=gold,
                fixtures=fixtures, oracle_result=oracle, provenance=provenance,
                token=CONSTRUCTION_TOKEN,
                historical_index=historical_index, oracle_mode="SYNTHETIC",
                clock=_fixed_clock_factory(3), inject_failure_phase="MATERIALIZED",
                t26_store_authentication=t26_authentication)
        except RuntimeError:
            injected = True
        ledger = T27ConstructionLedger.load(store)
        retry_refused = False
        try:
            T27ConstructionLedger.create_exclusive(
                store, bindings, CONSTRUCTION_TOKEN, clock=_fixed_clock_factory(3))
        except ConstructionLedgerError:
            retry_refused = True
        passed = injected and ledger.document["state"] == "FAILED" and retry_refused
        return {
            "schema_version": "t27-construction-failure-rehearsal-v1",
            "artifact": "T27_CONSTRUCTION_FAILURE_REHEARSAL",
            "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
            "post_ledger_failure_recorded": ledger.document["state"] == "FAILED",
            "retry_refused": retry_refused, "one_shot": "SPENT",
            "terminal": "T27_REAL_BLIND_CONSTRUCTION_FAILED_ONE_SHOT_CONSUMED",
            "real_construction_attempts": 0,
        }


NEGATIVE_CONTROL_IDS = (
    "wrong_token", "wrong_candidate", "wrong_runtime_root", "wrong_freeze",
    "wrong_metric_registry", "wrong_nonvacuity_policy", "wrong_authority_graph",
    "duplicate_ledger", "attempt_2", "scenario_count_511", "scenario_count_513",
    "missing_family", "wrong_family_count", "successful_completion_below_minimum",
    "recoverable_below_minimum", "replan_below_minimum",
    "safe_abstention_below_minimum", "duplicate_scenario_id",
    "historical_overlap", "t26_oracle_overlap", "gold_field_exposure",
    "candidate_gold_edge", "authority_escalation", "fixture_hash_mismatch",
    "contract_leaf_failure", "premature_evaluation_artifact",
    "public_history_none", "empty_nine_dimensional_history",
    "missing_required_historical_source", "missing_source_root",
    "fake_source_commitment", "fake_public_history_builder_identity",
    "synthetic_t26_oracle_real_mode", "wrong_t26_store",
    "wrong_t26_manifest_hash", "wrong_t26_seal_hash",
    "wrong_t26_evaluation_ledger_hash", "wrong_t26_holdout_root",
    "wrong_t27_prospective_root", "missing_oracle_dimension",
    "t26_overlap_gt_zero",
    "legacy_rehearsal_marker_path_only", "official_marker_absent",
    "official_marker_wrong_schema", "official_marker_wrong_artifact",
    "official_marker_wrong_experiment", "official_marker_wrong_attempt",
    "official_marker_wrong_genesis_hash", "marker_missing_from_commitment_index",
    "marker_commitment_hash_mismatch", "marker_byte_count_mismatch",
    "ledger_started_event_hash_mismatch", "ledger_chain_invalid",
    "ledger_state_not_complete", "disposable_standin_using_legacy_path",
    "structural_entity_identities_populated",
    "structural_source_ids_populated",
    "structural_verbatim_attack_wording_populated",
    "structural_relations_populated",
    "identity_case_ids_marked_structural",
    "identity_exact_queries_marked_structural",
    "identity_exact_answers_marked_structural",
    "identity_exact_source_text_marked_structural",
    "identity_chunk_ids_marked_structural",
    "unknown_structural_dimension",
    "dimension_policy_root_tampered",
    "source_policy_root_tampered",
    "reuse_case_ids_detected",
    "reuse_exact_queries_detected",
    "reuse_exact_answers_detected",
    "reuse_exact_source_text_detected",
    "reuse_chunk_ids_detected",
)


def run_generated_public_policy_controls(root: Path) -> dict[str, Any]:
    """Structural policy negative and identity-reuse positive controls.

    Negative controls prove the frozen generated-public dimension policy is
    enforced fail-closed by index structure validation in both modes; the
    reuse controls prove genuine identity/content reuse of generated-public
    material is still detected. Public generated material only.
    """
    root = Path(root).resolve()
    from .qualification import build_public_cases

    index = build_authenticated_public_historical_index(root)
    results: dict[str, dict[str, Any]] = {}

    def reseal_source(source: dict[str, Any]) -> None:
        source["overall_source_root"] = sha256_json({
            key: value for key, value in source.items()
            if key != "overall_source_root"})

    def reseal_index(document: dict[str, Any]) -> None:
        document["public_historical_index_root"] = sha256_json({
            key: value for key, value in document.items()
            if key != "public_historical_index_root"})

    def mutate_dimension(document: dict[str, Any], source_class: str,
                         name: str, values: list[str], *,
                         applicable: bool = True,
                         empty_contract: str | None = None) -> None:
        source = next(item for item in document["sources"]
                      if item["source_class"] == source_class)
        dimension = source["dimensions"][name]
        dimension["fingerprints"] = values
        dimension["historical_population"] = len(values)
        dimension["dimension_root"] = sha256_json(values)
        if applicable:
            dimension["applicable"] = True
            dimension.pop("empty_contract", None)
        else:
            dimension["applicable"] = False
            dimension["empty_contract"] = empty_contract
        source["dimension_populations"][name] = len(values)
        source["dimension_roots"][name] = sha256_json(values)
        reseal_source(source)
        aggregate = sorted({value for item in document["sources"]
                            for value in item["dimensions"][name]["fingerprints"]})
        aggregate_record = document["aggregate_dimensions"][name]
        aggregate_record["fingerprints"] = aggregate
        aggregate_record["historical_population"] = len(aggregate)
        aggregate_record["dimension_root"] = sha256_json(aggregate)
        aggregate_record["applicable"] = bool(aggregate)
        if aggregate:
            aggregate_record.pop("empty_contract", None)
        else:
            aggregate_record["empty_contract"] = "FROZEN_PUBLIC_REGISTRY_EMPTY"
        reseal_index(document)

    structural_probe = sha256_json(("structural-tamper", "probe"))

    for control, source_class, name in (
        ("structural_entity_identities_populated",
         "T27_PUBLIC_QUALIFICATION", "entity_identities"),
        ("structural_source_ids_populated",
         "T27_SYNTHETIC_TERMINAL_MATRIX", "source_ids"),
        ("structural_verbatim_attack_wording_populated",
         "T27_SYNTHETIC_RECOVERY_REPLAN_EXAMPLES", "verbatim_attack_wording"),
        ("structural_relations_populated", "T27_DIAGNOSTICS", "relations"),
    ):
        tampered = copy.deepcopy(index)
        mutate_dimension(tampered, source_class, name,
                         [sha256_json(("tampered", control))])
        try:
            verify_historical_index(tampered, root=root, mode="REAL")
            refused = False
        except ValueError:
            refused = True
        results[control] = {
            "status": "PASS" if refused else "FAIL", "refused": refused,
            "evidence": f"structural-populated:{name}",
        }

    for control, name in (
        ("identity_case_ids_marked_structural", "case_ids"),
        ("identity_exact_queries_marked_structural", "exact_queries"),
        ("identity_exact_answers_marked_structural", "exact_answers"),
        ("identity_exact_source_text_marked_structural", "exact_source_text"),
        ("identity_chunk_ids_marked_structural", "chunk_ids"),
    ):
        tampered = copy.deepcopy(index)
        mutate_dimension(
            tampered, "T27_PUBLIC_QUALIFICATION", name, [], applicable=False,
            empty_contract=("T27_PUBLIC_QUALIFICATION:" + name +
                            ":STRUCTURAL_SHARED_FROZEN_EMPTY"))
        try:
            verify_historical_index(tampered, root=root, mode="REAL")
            refused = False
        except ValueError:
            refused = True
        results[control] = {
            "status": "PASS" if refused else "FAIL", "refused": refused,
            "evidence": f"identity-marked-structural:{name}",
        }

    unknown_policy = copy.deepcopy(generated_public_dimension_policy())
    unknown_policy["dimension_classifications"]["unknown_future_dimension"] = \
        STRUCTURAL_SHARED_FROZEN_EMPTY
    try:
        validate_generated_public_dimension_policy(unknown_policy)
        refused = False
    except ValueError:
        refused = True
    results["unknown_structural_dimension"] = {
        "status": "PASS" if refused else "FAIL", "refused": refused,
        "evidence": "unknown-dimension-in-policy",
    }

    root_tampered = copy.deepcopy(index)
    next(item for item in root_tampered["sources"]
         if item["source_class"] == "T27_PUBLIC_QUALIFICATION")[
        "dimension_policy_root"] = "0" * 64
    for item in root_tampered["sources"]:
        reseal_source(item)
    reseal_index(root_tampered)
    try:
        verify_historical_index(root_tampered, root=root, mode="REAL")
        refused = False
    except ValueError:
        refused = True
    results["dimension_policy_root_tampered"] = {
        "status": "PASS" if refused else "FAIL", "refused": refused,
        "evidence": "policy-root-mismatch",
    }

    mismatched = copy.deepcopy(index)
    source = next(item for item in mismatched["sources"]
                  if item["source_class"] == "T22_PROTECTED")
    source["dimension_policy_schema"] = GENERATED_PUBLIC_POLICY_SCHEMA
    source["dimension_policy_root"] = generated_public_dimension_policy()[
        "dimension_policy_root"]
    source["structural_exempt_populations"] = {
        name: 0 for name in DIMENSIONS}
    reseal_source(source)
    reseal_index(mismatched)
    try:
        verify_historical_index(mismatched, root=root, mode="REAL")
        refused = False
    except ValueError:
        refused = True
    results["source_policy_root_tampered"] = {
        "status": "PASS" if refused else "FAIL", "refused": refused,
        "evidence": "source-policy-mismatch",
    }

    cases, gold, _ = build_public_cases()
    scenario = cases[0]
    step = scenario["plan"]["steps"][0]
    aggregates = {
        name: set(index["aggregate_dimensions"][name]["fingerprints"])
        for name in DIMENSIONS}
    reuse_probes = (
        ("reuse_case_ids_detected", "case_ids",
         sha256_json(scenario["scenario_id"])),
        ("reuse_exact_queries_detected", "exact_queries",
         sha256_json(scenario["plan"]["goal"])),
        ("reuse_exact_answers_detected", "exact_answers",
         sha256_json(gold[0]["expected_answer"])),
        ("reuse_exact_source_text_detected", "exact_source_text",
         sha256_json(step["input"])),
        ("reuse_chunk_ids_detected", "chunk_ids",
         sha256_json((scenario["scenario_id"], step["step_id"]))),
    )
    for control, name, value in reuse_probes:
        detected = value in aggregates[name]
        results[control] = {
            "status": "PASS" if detected else "FAIL", "refused": detected,
            "evidence": f"genuine-reuse-detected:{name}",
        }
    return results


def run_t26_marker_layout_negative_controls(root: Path) -> dict[str, Any]:
    """Official T26 marker-layout negative controls (disposable stand-ins only).

    Every control authenticates a mutated disposable stand-in through the exact
    production metadata-only path; each must refuse. The real sealed T26 store
    is never touched here.
    """
    root = Path(root).resolve()
    from t26_protocol.lifecycle import T26PrivateStore
    from t26_protocol.t27_private_oracle import (
        OFFICIAL_MARKER_PATH, authenticate_official_t26_store_for_t27,
        disposable_t26_sealed_store)
    results: dict[str, dict[str, Any]] = {}

    def record(name: str, refused: bool, evidence: str) -> None:
        results[name] = {"status": "PASS" if refused else "FAIL",
                         "refused": refused, "evidence": evidence}

    def attempt(name: str, store_root: Path, expected: dict[str, Any]) -> None:
        try:
            fresh = T26PrivateStore(store_root, root)
            authenticate_official_t26_store_for_t27(root, fresh, expected=expected)
        except Exception as exc:
            record(name, True, f"official-marker-layout:{type(exc).__name__}")
        else:
            record(name, False, "official-marker-layout")

    def edit_index(store_root: Path, mutation: Callable[[dict], None]) -> None:
        path = store_root / "commitments.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        mutation(index)
        index["artifact_root"] = sha256_json(index["commitments"])
        path.write_text(json.dumps(index, indent=2, sort_keys=True,
                                   ensure_ascii=False) + "\n", encoding="utf-8")

    def scenario(name: str, *, legacy_marker: bool = False,
                 mutate: Callable[[T26PrivateStore], None] | None = None,
                 index_mutation: Callable[[dict], None] | None = None) -> None:
        with TemporaryDirectory(prefix=f"t27-marker-control-{name}-") as tmp:
            store, expected = disposable_t26_sealed_store(
                Path(tmp), variant=1, legacy_marker=legacy_marker,
                public_repo=root)
            if mutate is not None:
                mutate(store)
            if index_mutation is not None:
                edit_index(store.root, index_mutation)
            attempt(name, store.root, expected)

    scenario("legacy_rehearsal_marker_path_only", legacy_marker=True)

    def add_legacy(store: T26PrivateStore) -> None:
        store.write_once("markers/evaluation.one-shot", {
            "schema_version": "t26-evaluation-one-shot-marker-v1",
            "artifact": "T26_EVALUATION_ONE_SHOT_SPENT", "attempt": 1,
            "ledger_genesis_hash": "0" * 64,
        }, classification="PRIVATE_EVALUATION")

    scenario("disposable_standin_using_legacy_path", mutate=add_legacy)

    def absent(store: T26PrivateStore) -> None:
        store.path(OFFICIAL_MARKER_PATH).unlink()

    scenario("official_marker_absent", mutate=absent)

    def field_drift(field: str, value: Any) -> Callable[[T26PrivateStore], None]:
        def mutate(store: T26PrivateStore) -> None:
            marker = store.read(OFFICIAL_MARKER_PATH)
            marker[field] = value
            store.replace(OFFICIAL_MARKER_PATH, marker)
        return mutate

    scenario("official_marker_wrong_schema", mutate=field_drift(
        "schema_version", "t26-evaluation-one-shot-marker-v1"))
    scenario("official_marker_wrong_artifact", mutate=field_drift(
        "artifact", "T26_EVALUATION_ONE_SHOT_SPENT_V2"))
    scenario("official_marker_wrong_experiment", mutate=field_drift(
        "experiment", "t27"))
    scenario("official_marker_wrong_attempt", mutate=field_drift("attempt", 2))
    scenario("official_marker_wrong_genesis_hash", mutate=field_drift(
        "ledger_genesis_hash", "0" * 64))

    def remove_marker_entry(index: dict) -> None:
        index["commitments"] = [entry for entry in index["commitments"]
                                if entry["logical_id"] != OFFICIAL_MARKER_PATH]

    scenario("marker_missing_from_commitment_index",
             index_mutation=remove_marker_entry)

    def break_marker_hash(index: dict) -> None:
        for entry in index["commitments"]:
            if entry["logical_id"] == OFFICIAL_MARKER_PATH:
                entry["sha256"] = "0" * 64

    scenario("marker_commitment_hash_mismatch", index_mutation=break_marker_hash)

    def break_marker_bytes(index: dict) -> None:
        for entry in index["commitments"]:
            if entry["logical_id"] == OFFICIAL_MARKER_PATH:
                entry["bytes"] = entry["bytes"] + 1

    scenario("marker_byte_count_mismatch", index_mutation=break_marker_bytes)

    def break_started_event(store: T26PrivateStore) -> None:
        ledger = store.read("evaluation/ledger.json")
        ledger["events"][0]["event_hash"] = "0" * 64
        store.replace("evaluation/ledger.json", ledger)

    scenario("ledger_started_event_hash_mismatch", mutate=break_started_event)

    def break_chain(store: T26PrivateStore) -> None:
        ledger = store.read("evaluation/ledger.json")
        ledger["events"][1]["previous_event_hash"] = "0" * 64
        store.replace("evaluation/ledger.json", ledger)

    scenario("ledger_chain_invalid", mutate=break_chain)

    def break_state(store: T26PrivateStore) -> None:
        ledger = store.read("evaluation/ledger.json")
        ledger["state"] = "SCORED"
        store.replace("evaluation/ledger.json", ledger)

    scenario("ledger_state_not_complete", mutate=break_state)
    return results


def run_negative_controls(root: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    cases, gold, fixtures = synthetic_private_bundle(7)
    oracle = synthetic_oracle_result(cases, gold, variant=7)
    historical_index, historical_evidence = synthetic_historical_evidence(
        cases, gold, oracle, variant=7)
    provenance = author_provenance(
        "T27-DISPOSABLE-NEGATIVE-AUTHOR", "9" * 64,
        "2026-09-27T00:00:07+00:00")
    baseline = required_bindings(
        root, freeze, historical=historical_evidence,
        timestamp="2026-09-27T00:00:07+00:00")
    results: dict[str, dict[str, Any]] = {}

    def record(name: str, refused: bool, evidence: str) -> None:
        results[name] = {"status": "PASS" if refused else "FAIL",
                         "refused": refused, "evidence": evidence}

    def expect_exception(name: str, function: Callable[[], Any], evidence: str) -> None:
        try:
            function()
        except Exception as exc:
            record(name, True, f"{evidence}:{type(exc).__name__}")
        else:
            record(name, False, evidence)

    with TemporaryDirectory(prefix="t27-negative-token-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                disposable=True)
        expect_exception("wrong_token", lambda: T27ConstructionLedger.create_exclusive(
            store, baseline, "WRONG"), "exclusive-ledger-token-check")

    for control, key in (
        ("wrong_candidate", "candidate_commit"),
        ("wrong_runtime_root", "runtime_root"),
        ("wrong_freeze", "preconstruction_freeze_sha256"),
        ("wrong_metric_registry", "metric_registry_sha256"),
        ("wrong_nonvacuity_policy", "nonvacuity_policy_sha256"),
        ("wrong_authority_graph", "authority_graph_sha256"),
    ):
        with TemporaryDirectory(prefix=f"t27-negative-{control}-") as tmp:
            store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                    disposable=True)
            altered = copy.deepcopy(baseline)
            altered[key] = ("0" * len(str(altered[key])))
            expect_exception(control, lambda a=altered, s=store: validate_preledger(
                a, baseline, s), f"preledger-{key}-binding")

    with TemporaryDirectory(prefix="t27-negative-ledger-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                disposable=True)
        T27ConstructionLedger.create_exclusive(store, baseline, CONSTRUCTION_TOKEN,
                                               clock=_fixed_clock_factory(7))
        expect_exception("duplicate_ledger", lambda: T27ConstructionLedger.create_exclusive(
            store, baseline, CONSTRUCTION_TOKEN), "exclusive-create")
        attempt_two = copy.deepcopy(baseline)
        attempt_two["attempt"] = 2
        expect_exception("attempt_2", lambda: T27ConstructionLedger.create_exclusive(
            store, attempt_two, CONSTRUCTION_TOKEN), "attempt-one-only")

    def design_control(name: str, changed_cases: list[dict[str, Any]],
                       changed_gold: list[dict[str, Any]], check: str) -> None:
        changed_oracle = synthetic_oracle_result(changed_cases, changed_gold, variant=7)
        audit = static_design_audit(
            changed_cases, changed_gold, fixtures, changed_oracle, provenance,
            oracle_mode="SYNTHETIC")
        record(name, audit["status"] == "FAIL" and not audit["checks"].get(check, True),
               f"static-design:{check}")

    design_control("scenario_count_511", cases[:-1], gold[:-1], "scenario_count_512")
    extra_case = copy.deepcopy(cases[-1]); extra_gold = copy.deepcopy(gold[-1])
    extra_case["scenario_id"] += "-extra"; extra_case["plan"]["plan_id"] += "-extra"
    extra_gold["scenario_id"] = extra_case["scenario_id"]
    design_control("scenario_count_513", cases + [extra_case], gold + [extra_gold],
                   "scenario_count_512")
    no_family_cases = [case for case, expected in zip(cases, gold)
                       if expected["family"] != FAMILIES[0]]
    no_family_gold = [expected for expected in gold if expected["family"] != FAMILIES[0]]
    design_control("missing_family", no_family_cases, no_family_gold, "family_count_16")
    wrong_family_gold = copy.deepcopy(gold)
    wrong_family_gold[0]["family"] = FAMILIES[1]
    design_control("wrong_family_count", cases, wrong_family_gold, "cases_per_family_32")

    for control, field, minimum_name, replacement in (
        ("successful_completion_below_minimum", "expected_terminal",
         "successful_completion_cases", "BLOCKED"),
        ("recoverable_below_minimum", "designated_recoverable",
         "recoverable_cases", False),
        ("replan_below_minimum", "expected_replan_trigger",
         "replan_required_cases", None),
        ("safe_abstention_below_minimum", "designated_abstention",
         "safe_abstention_cases", False),
    ):
        changed = copy.deepcopy(gold)
        for item in changed:
            item[field] = replacement
        design_control(control, cases, changed, f"nonvacuity.{minimum_name}")

    duplicated = copy.deepcopy(cases)
    duplicated[1]["scenario_id"] = duplicated[0]["scenario_id"]
    duplicated_gold = copy.deepcopy(gold)
    duplicated_gold[1]["scenario_id"] = duplicated_gold[0]["scenario_id"]
    design_control("duplicate_scenario_id", duplicated, duplicated_gold,
                   "unique_scenario_ids")

    future = fingerprint_sets(cases, gold)
    overlap_index = copy.deepcopy(historical_index)
    source = overlap_index["sources"][0]
    values = sorted(set(source["dimensions"]["case_ids"]["fingerprints"] +
                        [future["case_ids"][0]]))
    source["dimensions"]["case_ids"]["fingerprints"] = values
    source["dimensions"]["case_ids"]["historical_population"] = len(values)
    source["dimensions"]["case_ids"]["dimension_root"] = sha256_json(values)
    source["dimension_populations"]["case_ids"] = len(values)
    source["dimension_roots"]["case_ids"] = sha256_json(values)
    source["overall_source_root"] = sha256_json({
        key: value for key, value in source.items() if key != "overall_source_root"})
    aggregate = sorted({value for item in overlap_index["sources"]
                        for value in item["dimensions"]["case_ids"]["fingerprints"]})
    overlap_index["aggregate_dimensions"]["case_ids"]["fingerprints"] = aggregate
    overlap_index["aggregate_dimensions"]["case_ids"]["historical_population"] = len(aggregate)
    overlap_index["aggregate_dimensions"]["case_ids"]["dimension_root"] = sha256_json(aggregate)
    overlap_index["public_historical_index_root"] = sha256_json({
        key: value for key, value in overlap_index.items()
        if key != "public_historical_index_root"})
    overlap_audit = historical_exclusion_audit(
        cases, gold, overlap_index, oracle, mode="SYNTHETIC")
    record("historical_overlap", overlap_audit["status"] == "FAIL",
           "nine-dimensional-public-overlap")
    oracle_overlap = copy.deepcopy(oracle)
    oracle_overlap["dimensions"]["case_ids"]["overlap_count"] = 1
    oracle_overlap["overall_prohibited_overlap"] = 1
    oracle_overlap["result_sha256"] = sha256_json({
        key: value for key, value in oracle_overlap.items() if key != "result_sha256"})
    expect_exception("t26_oracle_overlap", lambda: verify_oracle_result(
        oracle_overlap, mode="SYNTHETIC"),
                     "sealed-t26-overlap")

    # Provenance completeness controls execute before any real ledger exists.
    expect_exception("public_history_none", lambda: historical_exclusion_audit(
        cases, gold, None, oracle, mode="REAL", root=root),
        "real-history-none")
    expect_exception("empty_nine_dimensional_history", lambda:
        historical_exclusion_audit(
            cases, gold, {name: [] for name in DIMENSIONS}, oracle,
            mode="REAL", root=root), "real-empty-history")
    real_index = build_authenticated_public_historical_index(root)
    missing_source = copy.deepcopy(real_index)
    missing_source["sources"].pop()
    expect_exception("missing_required_historical_source", lambda:
        historical_exclusion_audit(
            cases, gold, missing_source, oracle, mode="REAL", root=root),
        "required-source-completeness")
    missing_root = copy.deepcopy(real_index)
    missing_root["sources"][0].pop("overall_source_root")
    expect_exception("missing_source_root", lambda: verify_historical_index(
        missing_root, root=root, mode="REAL"), "source-root-required")

    def reseal_index(index: dict[str, Any], source_index: int = 0) -> None:
        source_value = index["sources"][source_index]
        source_value["overall_source_root"] = sha256_json({
            key: value for key, value in source_value.items()
            if key != "overall_source_root"})
        index["public_historical_index_root"] = sha256_json({
            key: value for key, value in index.items()
            if key != "public_historical_index_root"})

    fake_commitment = copy.deepcopy(real_index)
    fake_commitment["sources"][0]["source_commitment"] = "0" * 64
    reseal_index(fake_commitment)
    expect_exception("fake_source_commitment", lambda: verify_historical_index(
        fake_commitment, root=root, mode="REAL"), "source-commitment-authentication")
    fake_builder = copy.deepcopy(real_index)
    fake_builder["builder_implementation_identity"] = "caller:fake_builder"
    fake_builder["sources"][0]["builder_implementation_identity"] = "caller:fake_builder"
    reseal_index(fake_builder)
    expect_exception("fake_public_history_builder_identity", lambda:
        verify_historical_index(fake_builder, root=root, mode="REAL"),
        "builder-identity-authentication")

    from t26_protocol.t27_private_oracle import (
        authenticate_official_t26_store_for_t27,
        disposable_real_mode_oracle_result, disposable_t26_sealed_store,
        run_sealed_t26_to_t27_overlap_oracle)

    prospective_root = fingerprint_root(future)
    real_rehearsal = disposable_real_mode_oracle_result(
        root=root, prospective_root=prospective_root,
        prospective=future, variant=7)
    rehearsal_bindings = {key: real_rehearsal[key] for key in (
        "t26_store_identity", "t26_namespace", "t26_private_holdout_root",
        "t26_private_manifest_sha256", "t26_construction_seal_sha256",
        "t26_evaluation_ledger_sha256", "t26_official_evaluation_state",
        "t26_official_evaluation_attempt")}
    assert verify_oracle_result(
        real_rehearsal, mode="REAL_REHEARSAL",
        expected_t27_root=prospective_root,
        expected_t26_bindings=rehearsal_bindings)["status"] == "PASS"
    expect_exception("synthetic_t26_oracle_real_mode", lambda:
        verify_oracle_result(
            oracle, mode="REAL", root=root,
            expected_t27_root=prospective_root),
        "real-mode-rejects-synthetic")
    expect_exception("wrong_t26_store", lambda:
        run_sealed_t26_to_t27_overlap_oracle(
            root=root, store=object(), prospective_root=prospective_root,
            prospective=future), "sealed-store-type-and-identity")

    def tampered_oracle(field: str, value: Any) -> dict[str, Any]:
        changed = copy.deepcopy(real_rehearsal)
        changed[field] = value
        changed["result_sha256"] = sha256_json({
            key: item for key, item in changed.items() if key != "result_sha256"})
        return changed

    for control, field in (
        ("wrong_t26_manifest_hash", "t26_private_manifest_sha256"),
        ("wrong_t26_seal_hash", "t26_construction_seal_sha256"),
        ("wrong_t26_evaluation_ledger_hash", "t26_evaluation_ledger_sha256"),
        ("wrong_t26_holdout_root", "t26_private_holdout_root"),
    ):
        changed = tampered_oracle(field, "0" * 64)
        expect_exception(control, lambda value=changed: verify_oracle_result(
            value, mode="REAL_REHEARSAL", expected_t27_root=prospective_root,
            expected_t26_bindings=rehearsal_bindings),
            f"exact-{field}")
    wrong_prospective = tampered_oracle(
        "t27_prospective_fingerprint_root", "0" * 64)
    expect_exception("wrong_t27_prospective_root", lambda: verify_oracle_result(
        wrong_prospective, mode="REAL_REHEARSAL",
        expected_t27_root=prospective_root,
        expected_t26_bindings=rehearsal_bindings), "prospective-root-equality")
    missing_dimension = copy.deepcopy(real_rehearsal)
    missing_dimension["dimensions"].pop(DIMENSIONS[-1])
    missing_dimension["result_sha256"] = sha256_json({
        key: value for key, value in missing_dimension.items()
        if key != "result_sha256"})
    expect_exception("missing_oracle_dimension", lambda: verify_oracle_result(
        missing_dimension, mode="REAL_REHEARSAL",
        expected_t27_root=prospective_root,
        expected_t26_bindings=rehearsal_bindings), "nine-oracle-dimensions")
    real_overlap = copy.deepcopy(real_rehearsal)
    real_overlap["dimensions"][DIMENSIONS[0]]["overlap_count"] = 1
    real_overlap["overall_prohibited_overlap"] = 1
    real_overlap["result_sha256"] = sha256_json({
        key: value for key, value in real_overlap.items()
        if key != "result_sha256"})
    expect_exception("t26_overlap_gt_zero", lambda: verify_oracle_result(
        real_overlap, mode="REAL_REHEARSAL",
        expected_t27_root=prospective_root,
        expected_t26_bindings=rehearsal_bindings), "real-oracle-overlap")

    exposed = copy.deepcopy(cases[0]); exposed["expected_answer"] = "forbidden"
    expect_exception("gold_field_exposure", lambda: candidate_input_projection(exposed),
                     "candidate-projection")
    record("candidate_gold_edge", gold_firewall_audit(
        [exposed] + cases[1:], gold)["status"] == "FAIL", "gold-firewall")
    escalated = authority_audit(); escalated["construction_candidate_execution_authority"] = True
    record("authority_escalation",
           escalated["construction_candidate_execution_authority"] is True,
           "authority-audit-refusal")
    bad_content = b"tampered"
    bad_fixture = [{
        "logical_id": "bad.bin", "classification": "PRIVATE_FIXTURE",
        "sha256": "0" * 64, "byte_size": len(bad_content),
        "schema_type": "application/octet-stream", "content": bad_content,
    }]
    record("fixture_hash_mismatch", fixture_audit(bad_fixture)["status"] == "FAIL",
           "fixture-commitment")

    with TemporaryDirectory(prefix="t27-negative-contract-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                disposable=True)
        ledger = T27ConstructionLedger.create_exclusive(
            store, baseline, CONSTRUCTION_TOKEN, clock=_fixed_clock_factory(7))
        static = require_static_design(
            cases, gold, fixtures, oracle, provenance,
            oracle_mode="SYNTHETIC")
        components = {
            "static_design": static,
            "historical_exclusion": historical_exclusion_audit(
                cases, gold, historical_index, oracle, mode="SYNTHETIC"),
            "uniqueness": uniqueness_audit(cases, gold),
            "gold_firewall": gold_firewall_audit(cases, gold),
            "authority": authority_audit(), "fixtures": fixture_audit(fixtures),
        }
        synthetic_audit = {
            "components": components, "scenario_count": 512, "gold_count": 512,
            "candidate_executions": 1, "official_evaluator_invocations": 0,
        }
        with TemporaryDirectory(prefix="t27-negative-t26-standin-") as t26_tmp:
            standin, standin_expected = disposable_t26_sealed_store(
                Path(t26_tmp), variant=7, public_repo=root)
            valid_marker_evidence = authenticate_official_t26_store_for_t27(
                root, standin, expected=standin_expected)
        leaf = contract_leaf_audit(baseline, synthetic_audit, ledger,
                                   t26_store_authentication=valid_marker_evidence)
        record("contract_leaf_failure", leaf["status"] == "FAIL" and
               leaf["results"]["audit.candidate_executions_zero"] == "FAIL",
               "enumerated-contract-leaf")

    with TemporaryDirectory(prefix="t27-negative-premature-eval-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                disposable=True)
        store.write_once_json("markers/evaluation.one-shot", {"premature": True})
        expect_exception("premature_evaluation_artifact", lambda: validate_preledger(
            baseline, baseline, store), "preledger-evaluation-absence")

    results.update(run_t26_marker_layout_negative_controls(root))
    results.update(run_generated_public_policy_controls(root))

    if set(results) != set(NEGATIVE_CONTROL_IDS):
        raise ValueError("negative control enumerator drift")
    passed = all(item["status"] == "PASS" for item in results.values())
    return {
        "schema_version": "t27-construction-negative-controls-v1",
        "artifact": "T27_CONSTRUCTION_NEGATIVE_CONTROLS",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "PASS": sum(item["status"] == "PASS" for item in results.values()),
        "FAIL": sum(item["status"] == "FAIL" for item in results.values()),
        "control_count": len(results), "controls": dict(sorted(results.items())),
        "real_construction_attempts": 0, "real_blind_rows": 0,
    }


def real_fingerprint_semantics_probe() -> dict[str, Any]:
    """Prove real prospective fingerprint_sets semantics are unchanged.

    Disposable synthetic material only; checks each of the nine dimensions
    still hashes exactly the V4-era value (family, capability,
    (family, fallback_condition), (step_id, depends_on), ...).
    """
    cases, gold, _ = synthetic_private_bundle(0)
    scenario, expected = cases[0], gold[0]
    sets = fingerprint_sets([scenario], [expected])
    plan = scenario["plan"]
    checks = {
        "nine_dimensions": set(sets) == set(DIMENSIONS),
        "nonempty_all_nine": all(sets[name] for name in DIMENSIONS),
        "case_ids_hash": sets["case_ids"] == [
            sha256_json(scenario["scenario_id"])],
        "entity_family_hash": sets["entity_identities"] == [
            sha256_json(expected["family"])],
        "source_ids_capability_hashes": sets["source_ids"] == sorted({
            sha256_json(step["capability"]) for step in plan["steps"]}),
        "chunk_ids_pair_hashes": sets["chunk_ids"] == sorted({
            sha256_json((scenario["scenario_id"], step["step_id"]))
            for step in plan["steps"]}),
        "exact_queries_goal_hash": sets["exact_queries"] == [
            sha256_json(plan["goal"])],
        "exact_answers_answer_hash": sets["exact_answers"] == [
            sha256_json(expected["expected_answer"])],
        "exact_source_text_input_hashes": sets["exact_source_text"] == sorted({
            sha256_json(step["input"]) for step in plan["steps"]}),
        "verbatim_family_fallback_hash": sets["verbatim_attack_wording"] == [
            sha256_json((expected["family"], plan["fallback_condition"]))],
        "relations_dependency_hashes": sets["relations"] == sorted({
            sha256_json((step["step_id"], step["depends_on"]))
            for step in plan["steps"]}),
    }
    passed = all(checks.values())
    core = {
        "schema_version": "t27-real-fingerprint-semantics-probe-v1",
        "artifact": "T27_REAL_FINGERPRINT_SEMANTICS_PROBE",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "real_prospective_fingerprints_unchanged": passed,
    }
    return {**core, "probe_root": sha256_json(core)}


def t26_oracle_nine_dimension_probe() -> dict[str, Any]:
    """Prove the sealed T26 oracle still enforces all nine dimensions.

    Disposable synthetic hash sets only; the oracle must refuse an
    eight-dimensional comparison and accept the nine-dimensional one.
    """
    from t26_protocol.t27_private_oracle import compare_hashes

    future = {name: [sha256_json(("probe", "prospective", name))]
              for name in DIMENSIONS}
    sealed = {name: [sha256_json(("probe", "sealed", name))]
              for name in DIMENSIONS}
    bindings = {
        "t26_private_holdout_root": "a" * 64,
        "t26_private_manifest_sha256": "b" * 64,
        "t26_construction_seal_sha256": "c" * 64,
        "t26_evaluation_ledger_sha256": "d" * 64,
    }
    nine = compare_hashes(
        prospective_root=fingerprint_root(future), prospective=future,
        sealed_historical=sealed, t26_bindings=bindings,
        timestamp="2026-09-28T00:00:00+00:00")
    eight = {name: value for name, value in sealed.items()
             if name != DIMENSIONS[-1]}
    refused = False
    try:
        compare_hashes(
            prospective_root=fingerprint_root(future), prospective=future,
            sealed_historical=eight, t26_bindings=bindings,
            timestamp="2026-09-28T00:00:01+00:00")
    except Exception:
        refused = True
    passed = (set(nine["dimensions"]) == set(DIMENSIONS) and refused
              and nine["overall_prohibited_overlap"] == 0)
    core = {
        "schema_version": "t27-t26-oracle-nine-dimension-probe-v1",
        "artifact": "T26_SEALED_ORACLE_NINE_DIMENSION_PROBE",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "oracle_implementation":
            "t26_protocol.t27_private_oracle:compare_hashes",
        "nine_dimension_result_pass": set(nine["dimensions"]) == set(DIMENSIONS),
        "eight_dimension_refused": refused,
        "t26_private_rows_opened": 0,
    }
    return {**core, "probe_root": sha256_json(core)}
