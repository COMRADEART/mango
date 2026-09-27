"""T26 official evaluation with canonical production-runner binding.

This additive successor leaves the sealed construction and evaluation-v2
predecessor bytes unchanged.  The real path has no runner-factory argument:
it internally builds and attests the one canonical production stack.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .construction import (_synthetic_oracle_result, construct_real,
                           run_publication_leak_gate,
                           synthetic_author_provenance,
                           synthetic_private_bundle)
from .evaluation_v2 import (
    EVALUATION_TOKEN, ORIGINAL_FREEZE_ROOT, ORIGINAL_FREEZE_SHA256,
    SCORER_SHA256, METRIC_REGISTRY_SHA256, AUTHORITY_GRAPH_SHA256,
    FIREWALL_SHA256, EvaluationTechnicalAbort, candidate_view,
    require_publication_pass, require_sealed_state,
    run_public_addendum_leak_scan, verify_addendum_document,
    verify_addendum_freeze, verify_original_v3_components,
    verify_store_compatibility, _fetch_prune_public_refs,
    _verify_store_artifact,
)
from .lifecycle import T26PrivateStore
from .official_runner import (
    FACTORY_ID, DeterministicFixtureSearchProvider,
    DeterministicGeneralContext, OfficialRunnerFactory,
    build_official_runner_factory, build_runner_identity_document,
    validate_corpus_mount, validate_factory_instance,
    validate_gold_free_mount, validate_stack_attestation,
    verify_runner_identity_document,
)
from .scorer import score_suite

SYNTHETIC_TOKEN = "T26_PRODUCTION_STACK_DISPOSABLE_EVALUATION"
IMPLEMENTATION = "t26_protocol.evaluation_v3:run_real_evaluation"
ADDENDUM_SCHEMA = "t26-evaluation-protocol-addendum-v2"
FREEZE_SCHEMA = "t26-evaluation-runner-binding-freeze-v1"
LEDGER_SCHEMA = "t26-production-bound-evaluation-ledger-v1"
MARKER_SCHEMA = "t26-evaluation-one-shot-marker-v2"

ADDENDUM_PATH = "evaluations/t26/T26_EVALUATION_PROTOCOL_ADDENDUM_V2.json"
FREEZE_PATH = "evaluations/t26/T26_EVALUATION_RUNNER_BINDING_FREEZE.json"
REHEARSAL_PATH = "evaluations/t26/T26_PRODUCTION_RUNNER_REHEARSAL_REPORT.json"
NEGATIVE_PATH = "evaluations/t26/T26_PRODUCTION_RUNNER_NEGATIVE_CONTROLS.json"
LEDGER_PATH = "evaluation/ledger.json"
MARKER_PATH = "evaluation/one_shot_spent.json"

PREDECESSOR_COMMIT = "8282a78a3c9543fb3dfa828d0fe1ed5267b8c7e7"
PREDECESSOR_FREEZE_SHA256 = "5b39e7a38a8f83b3a52df685e56c83773cef104f73d713aa41d363ac8b12adde"
PREDECESSOR_FREEZE_ROOT = "b0baf8653add2b34a37261676fbdd5fff566f7d372dedc4c079251c2fce873e1"
PREDECESSOR_COMPONENT_ROOT = "7a6cf07ad64ee037495af9f339150eef2e82281f9087e38db50b752fd8505ca6"

STATES = ("STARTED", "EXECUTED", "SCORED", "COMPLETE")
NEXT_STATE = {"STARTED": "EXECUTED", "EXECUTED": "SCORED",
              "SCORED": "COMPLETE"}

RUNNER_BINDING_FIELDS = (
    "official_runner_factory_id", "official_runner_factory_sha256",
    "production_runtime_sha256", "production_provider_id",
    "production_provider_sha256", "production_adapter_registry_root",
    "official_runner_policy_root", "live_provider_identity_root",
    "general_context_identity_root",
)

LEDGER_BINDING_FIELDS = (
    "experiment", "attempt", "authorization", "material_mode",
    "candidate_commit", "candidate_tree", "runtime_root",
    "construction_seal_sha256", "construction_ledger_sha256",
    "construction_ledger_root", "private_manifest_sha256",
    "private_artifact_root", "private_blind_root",
    "original_v3_freeze_sha256", "original_v3_freeze_root",
    "predecessor_addendum_freeze_sha256", "predecessor_addendum_freeze_root",
    "evaluation_addendum_freeze_sha256", "evaluation_addendum_freeze_root",
    "scorer_sha256", "metric_registry_sha256", "authority_graph_sha256",
    "firewall_sha256", *RUNNER_BINDING_FIELDS,
)

FREEZE_COMPONENTS = {
    "T26_CONSTRUCTION_PUBLIC_RECEIPT.json": "CONSTRUCTION_RECEIPT",
    "T26_PUBLIC_CONSTRUCTION_COMMITMENT.json": "CONSTRUCTION_COMMITMENT",
    "evaluations/t26/preconstruction_freeze.json": "ORIGINAL_V3_FREEZE",
    "evaluations/t26/candidate_identity.json": "CANDIDATE_IDENTITY",
    "evaluations/t26/T26_EVALUATION_ADDENDUM_FREEZE.json": "PREDECESSOR_FREEZE",
    "evaluations/t26/T26_EVALUATION_PROTOCOL_ADDENDUM.json": "PREDECESSOR_ADDENDUM",
    "evaluations/t26/T26_OFFICIAL_RUNNER_FACTORY.json": "RUNNER_FACTORY_IDENTITY",
    ADDENDUM_PATH: "RUNNER_BOUND_ADDENDUM",
    REHEARSAL_PATH: "PRODUCTION_STACK_REHEARSALS",
    NEGATIVE_PATH: "RUNNER_BINDING_NEGATIVE_CONTROLS",
    "t26_protocol/official_runner.py": "CANONICAL_RUNNER_FACTORY",
    "t26_protocol/evaluation_v3.py": "RUNNER_BOUND_EVALUATOR",
    "scripts/t26_runner_binding_addendum.py": "REPRODUCTION_ENTRYPOINT",
    "tests/test_t26_production_runner_binding.py": "TEST_GATE",
    "t26_protocol/production.py": "FROZEN_PRODUCTION_ADAPTERS",
    "t25_protocol/provider.py": "FROZEN_PRODUCTION_PROVIDER",
    "t25_protocol/firewall.py": "FROZEN_T25_FIREWALL",
    "t26_protocol/firewall.py": "FROZEN_T26_FIREWALL",
    "src/sciencemath/integrated/runner.py": "FROZEN_INTEGRATED_RUNNER",
    "src/sciencemath/executive/skills.py": "FROZEN_SKILL_REGISTRY",
    "t26_protocol/scorer.py": "FROZEN_SCORER",
    "evaluations/t26/metric_registry.json": "FROZEN_METRIC_REGISTRY",
    "evaluations/t26/authority_graph.json": "FROZEN_AUTHORITY_GRAPH",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_bytes(root: Path, relative: str) -> bytes:
    from .freeze import _repository_bytes, _text_attributes

    attribute = _text_attributes(root, [relative])[relative]
    return _repository_bytes(root, relative, attribute)


def _repo_sha(root: Path, relative: str) -> str:
    return _sha(_repo_bytes(root, relative))


def _verify_predecessor(root: Path) -> dict[str, Any]:
    verify_addendum_document(root)
    observed = verify_addendum_freeze(root)
    expected = {
        "freeze_sha256": PREDECESSOR_FREEZE_SHA256,
        "freeze_root": PREDECESSOR_FREEZE_ROOT,
        "component_root": PREDECESSOR_COMPONENT_ROOT,
        "component_count": 18,
    }
    if any(observed.get(key) != value for key, value in expected.items()):
        raise ValueError("evaluation-v2 predecessor addendum drift")
    return {"status": "PASS", "commit": PREDECESSOR_COMMIT, **expected}


def build_addendum_document(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    predecessor = _verify_predecessor(root)
    base = verify_addendum_document(root)
    runner = verify_runner_identity_document(root)
    return {
        "schema_version": ADDENDUM_SCHEMA,
        "artifact": "T26_EVALUATION_PROTOCOL_ADDENDUM_V2",
        "classification": "PUBLIC_SAFE", "experiment": "t26",
        "root_cause": "PRE_EVALUATION_PRODUCTION_RUNNER_IDENTITY_BINDING_DEFECT",
        "predecessor_addendum_commit": predecessor["commit"],
        "predecessor_addendum_freeze_sha256": predecessor["freeze_sha256"],
        "predecessor_addendum_freeze_root": predecessor["freeze_root"],
        "predecessor_addendum_component_root": predecessor["component_root"],
        "replacement_evaluation_entrypoint": IMPLEMENTATION,
        "superseded_evaluation_entrypoint":
            "t26_protocol.evaluation_v2:run_real_evaluation",
        "construction_superseded": False,
        "construction_public_commit": base["construction_public_commit"],
        "construction_receipt_root": base["construction_receipt_root"],
        "construction_commitment_root": base["construction_commitment_root"],
        "candidate_commit": base["candidate_commit"],
        "candidate_tree": base["candidate_tree"],
        "runtime_root": base["runtime_root"],
        "construction_ledger_sha256": base["construction_ledger_sha256"],
        "construction_ledger_root": base["construction_ledger_root"],
        "private_manifest_sha256": base["private_manifest_sha256"],
        "private_artifact_root": base["private_artifact_root"],
        "private_blind_root": base["private_blind_root"],
        "construction_seal_sha256": base["construction_seal_sha256"],
        "original_v3_freeze_sha256": base["original_v3_freeze_sha256"],
        "original_v3_freeze_root": base["original_v3_freeze_root"],
        "scorer_sha256": base["scorer_sha256"],
        "metric_registry_sha256": base["metric_registry_sha256"],
        "authority_graph_sha256": base["authority_graph_sha256"],
        "firewall_sha256": base["firewall_sha256"],
        "evaluation_implementation_sha256": _repo_sha(
            root, "t26_protocol/evaluation_v3.py"),
        "official_runner_factory_id": runner["factory_id"],
        "official_runner_factory_sha256":
            runner["factory_implementation_sha256"],
        "production_runtime_sha256": runner["production_runtime_sha256"],
        "production_adapter_registry_sha256":
            runner["production_adapter_registry_root"],
        "production_adapter_registry_root":
            runner["production_adapter_registry_root"],
        "production_provider_id": runner["production_provider_id"],
        "production_provider_sha256": runner["production_provider_sha256"],
        "t25_firewall_sha256": runner["t25_firewall_sha256"],
        "t26_firewall_sha256": runner["t26_firewall_sha256"],
        "official_runner_policy_root": runner["official_runner_policy_root"],
        "runner_factory_identity_root": runner["identity_root"],
        "real_path_accepts_runner_factory": False,
        "real_path_requires_live_provider": True,
        "real_evaluation_authorized": False,
        "external_action_authority": False,
        "candidate_gold_access": False,
    }


def verify_addendum_document_v2(
        root: Path, document: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    observed = document if document is not None else json.loads(
        (root / ADDENDUM_PATH).read_text(encoding="utf-8"))
    # Immutable predecessor verification: successor remediation changes the
    # runner inspector, so predecessor source components are not recomputed.
    if (_repo_sha(root, ADDENDUM_PATH) !=
            "3c7039aec5a37a6ea9499fe3e73bd8c908627b3b9a33ae806499d97349d2d3f2" or
            observed.get("schema_version") != ADDENDUM_SCHEMA or
            observed.get("evaluation_implementation_sha256") !=
            "42894d4dd41d7a91f73b71c9f1bd18f6a39441f813d4ad0784b0252610c250cd" or
            observed.get("official_runner_factory_sha256") !=
            "e8e2abd2056df3d251b1f6b414d81a1a40187d4b4b94d31f35bca98d066adf7f" or
            observed.get("candidate_commit") !=
            "6cb029c0f4edb4116c7f9a1f187cdc4671077a1f" or
            observed.get("runtime_root") !=
            "28f83990f5382400bac72cb34448ad5854c875d74655f1a571703f50d9cb453c"):
        raise ValueError("T26 runner-bound predecessor addendum mismatch")
    return dict(observed)


def build_addendum_freeze(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    addendum = verify_addendum_document_v2(root)
    original = verify_original_v3_components(root)
    predecessor = _verify_predecessor(root)
    entries = []
    for relative, role in sorted(FREEZE_COMPONENTS.items()):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"runner-binding freeze component missing: {relative}")
        data = _repo_bytes(root, relative)
        entries.append({"path": relative, "sha256": _sha(data),
                        "byte_size": len(data), "role": role})
    core = {
        "schema_version": FREEZE_SCHEMA,
        "artifact": "T26_EVALUATION_RUNNER_BINDING_FREEZE",
        "classification": "PUBLIC_SAFE", "experiment": "t26",
        "original_v3_freeze_sha256": original["freeze_sha256"],
        "original_v3_freeze_root": original["freeze_root"],
        "predecessor_addendum_commit": predecessor["commit"],
        "predecessor_addendum_freeze_sha256": predecessor["freeze_sha256"],
        "predecessor_addendum_freeze_root": predecessor["freeze_root"],
        "construction_public_commit": addendum["construction_public_commit"],
        "candidate_commit": addendum["candidate_commit"],
        "candidate_tree": addendum["candidate_tree"],
        "runtime_root": addendum["runtime_root"],
        "evaluation_implementation_sha256":
            addendum["evaluation_implementation_sha256"],
        "official_runner_factory_id": addendum["official_runner_factory_id"],
        "official_runner_factory_sha256":
            addendum["official_runner_factory_sha256"],
        "official_runner_policy_root":
            addendum["official_runner_policy_root"],
        "production_adapter_registry_root":
            addendum["production_adapter_registry_root"],
        "production_provider_sha256":
            addendum["production_provider_sha256"],
        "real_evaluation_authorized": False,
        "original_construction_freeze_replaced": False,
        "predecessor_addendum_rewritten": False,
    }
    document = {**core, "component_count": len(entries),
                "components": entries, "component_root": sha256_json(entries),
                "freeze_root": sha256_json(core)}
    document["freeze_sha256"] = _sha(json.dumps(
        document, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8"))
    return document


def verify_addendum_freeze_v2(
        root: Path, document: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    observed = document if document is not None else json.loads(
        (root / FREEZE_PATH).read_text(encoding="utf-8"))
    core = {key: value for key, value in observed.items() if key not in {
        "component_count", "components", "component_root", "freeze_root",
        "freeze_sha256"}}
    unhashed = {key: value for key, value in observed.items()
                if key != "freeze_sha256"}
    fixed = {
        "component_count": 23,
        "component_root":
            "de531c7805b7cf9dffbb3a2a02cc2cdaa0379062f6c28b7225623a117a97e14c",
        "freeze_root":
            "444b814fe0db11dc9887b42e509c101b9f6c55a7c5dafa237da8e5a0fc1a0b2e",
        "freeze_sha256":
            "874b6ce57fe1fb4903a91880a3702414fcadd02532a5d92fea07b0fb4194bfde",
    }
    if (any(observed.get(key) != value for key, value in fixed.items()) or
            observed.get("component_count") != len(observed.get("components", [])) or
            observed.get("component_root") != sha256_json(observed["components"]) or
            observed.get("freeze_root") != sha256_json(core) or
            observed.get("freeze_sha256") != _sha(json.dumps(
                unhashed, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode("utf-8"))):
        raise ValueError("T26 runner-binding predecessor freeze mismatch")
    return {"status": "PASS", "component_count": observed["component_count"],
            "component_root": observed["component_root"],
            "freeze_root": observed["freeze_root"],
            "freeze_sha256": observed["freeze_sha256"]}


class BoundEvaluationLedgerError(RuntimeError):
    pass


class BoundEvaluationLedger:
    def __init__(self, store: T26PrivateStore, document: dict[str, Any]) -> None:
        self.store = store
        self.document = document

    @property
    def state(self) -> str:
        return str(self.document["state"])

    @classmethod
    def create_exclusive(cls, store: T26PrivateStore,
                         bindings: dict[str, Any]) -> "BoundEvaluationLedger":
        if bindings.get("attempt") != 1 or set(bindings) != set(LEDGER_BINDING_FIELDS):
            raise ValueError("runner-bound evaluation ledger bindings invalid")
        if store.has(LEDGER_PATH) or store.has(MARKER_PATH):
            raise BoundEvaluationLedgerError("T26 evaluation one-shot already spent")
        created = _now()
        event = {"event_index": 0, "event_type": "STARTED",
                 "timestamp": created, "previous_event_hash": "0" * 64,
                 "payload": {"one_shot_spent": True,
                             "runner_factory_id":
                                 bindings["official_runner_factory_id"]}}
        event["event_hash"] = sha256_json(event)
        document = {
            "schema_version": LEDGER_SCHEMA,
            "artifact": "T26_OFFICIAL_EVALUATION_LEDGER",
            "experiment": "t26", "attempt": 1,
            "authorization": bindings["authorization"],
            "material_mode": bindings["material_mode"],
            "state": "STARTED", "created_at": created, "updated_at": created,
            "bindings": dict(sorted(bindings.items())),
            "events": [event], "event_count": 1,
            "final_event_hash": event["event_hash"],
        }
        store.write_once(LEDGER_PATH, document,
                         classification="PRIVATE_EVALUATION")
        ledger = cls(store, document)
        try:
            store.write_once(MARKER_PATH, {
                "schema_version": MARKER_SCHEMA,
                "artifact": "T26_EVALUATION_ONE_SHOT_SPENT",
                "experiment": "t26", "attempt": 1,
                "ledger_genesis_hash": event["event_hash"],
                "created_at": created,
            }, classification="PRIVATE_EVALUATION")
        except Exception as exc:
            ledger.fail("STARTED", type(exc).__name__,
                        {"error": "one-shot marker creation failed"})
            raise
        return ledger

    def advance(self, target: str, payload: dict[str, Any]) -> None:
        if NEXT_STATE.get(self.state) != target:
            raise BoundEvaluationLedgerError(
                f"forbidden evaluation transition {self.state} -> {target}")
        event = {"event_index": self.document["event_count"],
                 "event_type": target, "timestamp": _now(),
                 "previous_event_hash": self.document["final_event_hash"],
                 "payload": payload}
        event["event_hash"] = sha256_json(event)
        self.document["events"].append(event)
        self.document["state"] = target
        self.document["event_count"] += 1
        self.document["final_event_hash"] = event["event_hash"]
        self.document["updated_at"] = _now()
        self.store.replace(LEDGER_PATH, self.document)

    def fail(self, phase: str, failure_class: str,
             evidence: dict[str, Any]) -> None:
        if self.state == "FAILED":
            return
        if self.state == "COMPLETE":
            raise BoundEvaluationLedgerError("complete evaluation cannot fail")
        event = {"event_index": self.document["event_count"],
                 "event_type": "FAILED", "timestamp": _now(),
                 "previous_event_hash": self.document["final_event_hash"],
                 "payload": {"failure_phase": phase,
                             "failure_class": failure_class,
                             "evidence_hash": sha256_json(evidence)}}
        event["event_hash"] = sha256_json(event)
        self.document["events"].append(event)
        self.document["state"] = "FAILED"
        self.document["event_count"] += 1
        self.document["final_event_hash"] = event["event_hash"]
        self.document["updated_at"] = _now()
        self.document["failure"] = dict(event["payload"])
        self.store.replace(LEDGER_PATH, self.document)

    def verify(self) -> dict[str, Any]:
        document = self.store.read(LEDGER_PATH)
        if document != self.document or set(document.get("bindings", {})) != set(
                LEDGER_BINDING_FIELDS):
            raise BoundEvaluationLedgerError("runner-bound ledger drift")
        if document.get("event_count") != len(document.get("events", [])):
            raise BoundEvaluationLedgerError("runner-bound ledger count mismatch")
        previous = "0" * 64
        states = []
        for index, event in enumerate(document["events"]):
            body = {key: value for key, value in event.items()
                    if key != "event_hash"}
            if (event["event_index"] != index or
                    event["previous_event_hash"] != previous or
                    event["event_hash"] != sha256_json(body)):
                raise BoundEvaluationLedgerError("runner-bound ledger chain invalid")
            previous = event["event_hash"]
            states.append(event["event_type"])
        if (not states or states[0] != "STARTED" or
                document["state"] != states[-1] or
                document["final_event_hash"] != previous):
            raise BoundEvaluationLedgerError("runner-bound ledger envelope invalid")
        for prior, current in zip(states, states[1:]):
            if current != "FAILED" and NEXT_STATE.get(prior) != current:
                raise BoundEvaluationLedgerError("runner-bound transition invalid")
        marker = self.store.read(MARKER_PATH)
        if (marker.get("schema_version") != MARKER_SCHEMA or
                marker.get("ledger_genesis_hash") !=
                document["events"][0]["event_hash"]):
            raise BoundEvaluationLedgerError("runner-bound marker mismatch")
        return {"status": "PASS", "state": self.state,
                "event_count": document["event_count"],
                "final_event_hash": previous}


def load_ledger(store: T26PrivateStore) -> BoundEvaluationLedger:
    return BoundEvaluationLedger(store, store.read(LEDGER_PATH))


def _bindings(compatibility: dict[str, Any], addendum: dict[str, Any],
              freeze: dict[str, Any], factory: OfficialRunnerFactory,
              token: str, mode: str) -> dict[str, Any]:
    manifest = compatibility["manifest"]
    ledger = compatibility["ledger"]
    return {
        "experiment": "t26", "attempt": 1,
        "authorization": token, "material_mode": mode,
        "candidate_commit": manifest["candidate_identity"]["candidate_commit"],
        "candidate_tree": manifest["candidate_identity"]["candidate_tree"],
        "runtime_root": manifest["candidate_identity"]["runtime_root"],
        "construction_seal_sha256": compatibility["seal_sha256"],
        "construction_ledger_sha256": compatibility["ledger_sha256"],
        "construction_ledger_root": ledger["final_event_hash"],
        "private_manifest_sha256": compatibility["manifest_sha256"],
        "private_artifact_root": manifest["private_artifact_root"],
        "private_blind_root": manifest["private_blind_root"],
        "original_v3_freeze_sha256": addendum["original_v3_freeze_sha256"],
        "original_v3_freeze_root": addendum["original_v3_freeze_root"],
        "predecessor_addendum_freeze_sha256":
            addendum["predecessor_addendum_freeze_sha256"],
        "predecessor_addendum_freeze_root":
            addendum["predecessor_addendum_freeze_root"],
        "evaluation_addendum_freeze_sha256": freeze["freeze_sha256"],
        "evaluation_addendum_freeze_root": freeze["freeze_root"],
        "scorer_sha256": addendum["scorer_sha256"],
        "metric_registry_sha256": addendum["metric_registry_sha256"],
        "authority_graph_sha256": addendum["authority_graph_sha256"],
        "firewall_sha256": addendum["firewall_sha256"],
        **factory.binding(),
    }


def _run(root: Path, store: T26PrivateStore, *, token: str,
         real: bool, live_web_provider: Any, general_context: Any,
         refs: tuple[str, ...] = (), inject_failure_after_ledger: bool = False,
         verify_freeze_document: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    expected_token = EVALUATION_TOKEN if real else SYNTHETIC_TOKEN
    if token != expected_token:
        raise PermissionError("exact T26 production-bound authorization required")
    addendum = verify_addendum_document_v2(root)
    verify_original_v3_components(root)
    if verify_freeze_document:
        freeze_check = verify_addendum_freeze_v2(root)
        freeze = json.loads((root / FREEZE_PATH).read_text(encoding="utf-8"))
    else:
        freeze_check = {"status": "NOT_YET_FINALIZED"}
        freeze = {"freeze_sha256": "0" * 64, "freeze_root": "0" * 64}
    if store.has(LEDGER_PATH) or store.has(MARKER_PATH):
        raise BoundEvaluationLedgerError("T26 evaluation one-shot already spent")
    compatibility = verify_store_compatibility(
        store, root, expected_addendum=addendum if real else None)
    require_sealed_state(compatibility["seal"])
    scan_refs = refs
    if real:
        scan_refs = tuple(sorted(set(_fetch_prune_public_refs(root)) | set(refs)))
    leak = run_publication_leak_gate(store, root, refs=scan_refs)
    require_publication_pass(leak)
    cases = json.loads(_verify_store_artifact(
        store, compatibility["inputs_entry"]))
    gold = json.loads(_verify_store_artifact(
        store, compatibility["gold_entry"]))
    if len(cases) != 512 or len(gold) != 512:
        raise ValueError("sealed evaluation cardinality must be 512/512")
    candidate_cases = [candidate_view(scenario) for scenario in cases]
    if any(key.get("scenario_id") != scenario.get("scenario_id")
           for scenario, key in zip(cases, gold, strict=True)):
        raise ValueError("sealed scenario/gold identity mismatch")
    factory = build_official_runner_factory(
        root, live_web_provider=live_web_provider,
        general_context=general_context, real=real)
    validate_factory_instance(factory, root, real=real)
    preflight = factory.preflight()
    validate_stack_attestation(preflight, real=real)
    bindings = _bindings(
        compatibility, addendum, freeze, factory, token,
        "REAL_BLIND" if real else "DISPOSABLE_SYNTHETIC_PRODUCTION_STACK")
    ledger: BoundEvaluationLedger | None = None
    try:
        ledger = BoundEvaluationLedger.create_exclusive(store, bindings)
        if inject_failure_after_ledger:
            raise RuntimeError("injected post-ledger production-stack failure")
        outputs = []
        plans = []
        workspace_ids = []
        for index, candidate_case in enumerate(candidate_cases):
            workspace_id = "case-%04d-%s" % (
                index, hashlib.sha256(candidate_case["scenario_id"].encode())
                .hexdigest()[:12])
            workspace = store.path(f"evaluation/workspaces/{workspace_id}")
            workspace.mkdir(parents=True, exist_ok=False)
            runner = factory(workspace)
            outputs.append(runner.run(candidate_case))
            plans.append(candidate_case["plan"])
            workspace_ids.append(workspace_id)
        if (len(outputs) != 512 or len(set(workspace_ids)) != 512 or
                factory.runner_count != 512):
            raise RuntimeError("production runner execution cardinality mismatch")
        validate_stack_attestation(factory.last_stack, real=real)
        raw_meta = store.write_once(
            "evaluation/raw_outputs.json", outputs,
            classification="PRIVATE_EVALUATION")
        provenance = {
            "schema_version": "t26-production-runner-provenance-v1",
            "artifact": "T26_PRODUCTION_RUNNER_PROVENANCE",
            "experiment": "t26", "attempt": 1,
            "material_mode": bindings["material_mode"],
            "candidate_execution_count": len(outputs),
            "workspace_count": len(workspace_ids),
            "workspace_reuse_count": 0,
            "runner_initialization_executes_scenario": False,
            "construction_scenarios_rerun": 0,
            "runner_binding": factory.binding(),
            "runner_stack": factory.last_stack,
            "live_provider_identity": factory.live_provider_identity,
            "general_context_identity": factory.general_context_identity,
            "gold_ingress": {name: 0 for name in (
                "provider", "adapter_registry", "corpus_mount", "document_roots",
                "general_context", "web_provider", "memory",
                "workspace_initialization")},
        }
        provenance_meta = store.write_once(
            "evaluation/provenance.json", provenance,
            classification="PRIVATE_EVALUATION")
        ledger.advance("EXECUTED", {
            "candidate_execution_count": len(outputs),
            "runner_factory_id": FACTORY_ID,
            "raw_outputs_sha256": raw_meta["sha256"],
            "provenance_sha256": provenance_meta["sha256"],
        })
        scored = score_suite(outputs, gold, plans)
        rows = scored.pop("rows")
        rows_meta = store.write_once(
            "evaluation/scored_rows.json", rows,
            classification="PRIVATE_EVALUATION")
        summary_meta = store.write_once(
            "evaluation/summary.json", scored,
            classification="PRIVATE_EVALUATION")
        ledger.advance("SCORED", {
            "scenario_count": scored["scenario_count"],
            "capability_status": scored["status"],
            "scored_rows_sha256": rows_meta["sha256"],
            "summary_sha256": summary_meta["sha256"],
        })
        ledger.advance("COMPLETE", {
            "scenario_count": scored["scenario_count"],
            "runner_factory_id": FACTORY_ID,
            "raw_outputs_sha256": raw_meta["sha256"],
            "scored_rows_sha256": rows_meta["sha256"],
            "summary_sha256": summary_meta["sha256"],
            "provenance_sha256": provenance_meta["sha256"],
        })
        chain = ledger.verify()
        store_check = store.verify()
        receipt = {
            "schema_version": "t26-public-production-bound-evaluation-receipt-v1",
            "artifact": "T26_PUBLIC_EVALUATION_RECEIPT",
            "classification": "PUBLIC_SAFE", "experiment": "t26",
            "attempt": 1, "state": "COMPLETE",
            "scenario_count": scored["scenario_count"],
            "capability_status": scored["status"],
            "metrics": scored["metrics"],
            "critical_counters": scored["critical_counters"],
            "candidate_commit": bindings["candidate_commit"],
            "construction_seal_sha256": bindings["construction_seal_sha256"],
            "runner_factory_id": FACTORY_ID,
            "runner_factory_sha256":
                bindings["official_runner_factory_sha256"],
            "production_adapter_registry_root":
                bindings["production_adapter_registry_root"],
            "production_provider_id": bindings["production_provider_id"],
            "official_runner_policy_root":
                bindings["official_runner_policy_root"],
            "evaluation_ledger_sha256":
                store.commitment(LEDGER_PATH)["sha256"],
            "evaluation_ledger_root": ledger.document["final_event_hash"],
            "private_result_hashes": {
                "raw_outputs_sha256": raw_meta["sha256"],
                "scored_rows_sha256": rows_meta["sha256"],
                "summary_sha256": summary_meta["sha256"],
                "provenance_sha256": provenance_meta["sha256"],
            },
            "raw_rows_included": False, "gold_included": False,
            "scenario_bodies_included": False,
        }
        receipt["receipt_root"] = sha256_json(receipt)
        return {
            "status": "COMPLETE",
            "material_mode": bindings["material_mode"],
            "scenario_count": len(outputs), "score": scored,
            "ledger": ledger.document, "ledger_verification": chain,
            "store_verification": store_check, "receipt": receipt,
            "runner_binding": factory.binding(),
            "runner_stack": factory.last_stack,
            "live_provider_identity": factory.live_provider_identity,
            "gold_firewall": {"status": "PASS",
                              "candidate_fields": sorted(candidate_cases[0]),
                              "gold_fields_exposed": 0,
                              "ingress_counts": provenance["gold_ingress"]},
            "publication_gate": leak,
            "addendum_freeze_verification": freeze_check,
        }
    except Exception as exc:
        spent = ledger
        if spent is None and store.has(LEDGER_PATH):
            spent = load_ledger(store)
        if spent is not None and spent.state not in {"FAILED", "COMPLETE"}:
            spent.fail(spent.state, type(exc).__name__, {"error": str(exc)})
        if real and spent is not None:
            raise EvaluationTechnicalAbort(
                "T26_OFFICIAL_EVALUATION_TECHNICAL_ABORT_ONE_SHOT_CONSUMED"
            ) from exc
        raise


def run_real_evaluation(
        root: Path, store: T26PrivateStore, *, token: str,
        live_web_provider: Any, general_context: Any,
        refs: tuple[str, ...] = ()) -> dict[str, Any]:
    """Official entrypoint: the caller cannot inject a runner factory."""
    raise RuntimeError(
        "T26_EVALUATION_V3_SUPERSEDED_BY_GENERAL_CONTEXT_INSPECTION_ADDENDUM")


def run_production_disposable_evaluation(
        root: Path, store: T26PrivateStore, *, token: str,
        inject_failure_after_ledger: bool = False,
        verify_freeze_document: bool = True) -> dict[str, Any]:
    return _run(
        root, store, token=token, real=False,
        live_web_provider=DeterministicFixtureSearchProvider(),
        general_context=DeterministicGeneralContext(),
        inject_failure_after_ledger=inject_failure_after_ledger,
        verify_freeze_document=verify_freeze_document)


def build_production_disposable_store(
        root: Path, store: T26PrivateStore, variant: int) -> dict[str, Any]:
    cases, gold, _fixtures = synthetic_private_bundle(variant)
    fixtures: list[dict[str, Any]] = []
    for serial, (scenario, key) in enumerate(zip(cases, gold, strict=True)):
        steps = scenario["plan"]["steps"]
        for step_index, step in enumerate(steps):
            step["capability"] = "MATH_T4"
            step["router_input"]["requested_capability"] = "MATH_T4"
            step["input"] = ({"expression": str(serial)} if step_index == 0
                             else {"delta": step_index})
        target = 200000 + serial * 101 + variant * 8191
        prior = serial + sum(range(1, len(steps) - 1))
        steps[-1]["input"]["delta"] = target - prior
        key["expected_answer"] = target
    oracle = _synthetic_oracle_result(root, cases, gold, fixtures)
    provenance = synthetic_author_provenance(cases, gold, fixtures)
    return construct_real(
        root, store,
        token="T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
        cases=cases, gold=gold, fixtures=fixtures,
        oracle_result=oracle, provenance=provenance)


def semantic_view(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result["status"],
        "material_mode": result["material_mode"],
        "scenario_count": result["scenario_count"],
        "metrics": result["score"]["metrics"],
        "critical_counters": result["score"]["critical_counters"],
        "ledger_states": [event["event_type"]
                          for event in result["ledger"]["events"]],
        "runner_binding": result["runner_binding"],
        "runner_stack": result["runner_stack"],
        "gold_firewall": result["gold_firewall"],
        "raw_rows_included": result["receipt"]["raw_rows_included"],
        "gold_included": result["receipt"]["gold_included"],
    }


def run_negative_controls(root: Path) -> dict[str, Any]:
    from copy import deepcopy
    from tempfile import TemporaryDirectory
    from .evaluation_v2 import disposable_runner_factory
    from .qualification import fixture_adapters
    from .official_runner import validate_stack_attestation

    root = Path(root).resolve()
    old = json.loads((root /
        "evaluations/t26/T26_EVALUATION_NEGATIVE_CONTROLS.json")
        .read_text(encoding="utf-8"))
    if old.get("status") != "PASS" or old.get("refused_count") != 14:
        raise ValueError("predecessor negative controls drift")
    results: dict[str, bool] = {}

    def refused(name: str, function: Any) -> None:
        try:
            function()
            results[name] = False
        except Exception:
            results[name] = True

    refused("fixture_adapters_factory", lambda: validate_factory_instance(
        fixture_adapters({"kind": "none"}), root, real=True))
    refused("disposable_runner_factory", lambda: validate_factory_instance(
        disposable_runner_factory(1), root, real=True))
    refused("anonymous_lambda_factory", lambda: validate_factory_instance(
        lambda _path: None, root, real=True))
    identity = build_runner_identity_document(root)
    for name, field, value in (
        ("wrong_factory_id", "factory_id", "WRONG"),
        ("wrong_factory_sha", "factory_implementation_sha256", "0" * 64),
        ("wrong_production_py_sha", "production_runtime_sha256", "0" * 64),
        ("wrong_provider_class", "production_provider_id", "wrong:Provider"),
        ("wrong_t26_firewall", "t26_firewall_sha256", "0" * 64),
    ):
        changed = deepcopy(identity)
        changed[field] = value
        refused(name, lambda changed=changed: verify_runner_identity_document(
            root, changed))
    refused("synthetic_provider", lambda: build_official_runner_factory(
        root, live_web_provider=DeterministicFixtureSearchProvider(),
        general_context=DeterministicGeneralContext(), real=True))
    refused("fixture_web_provider", lambda: build_official_runner_factory(
        root, live_web_provider=DeterministicFixtureSearchProvider(),
        general_context=DeterministicGeneralContext(), real=True))
    bad_stack = {
        "factory_id": FACTORY_ID,
        "integrated_runner_used": True,
        "production_adapter_registry_used": True,
        "provider_id": "t25_protocol.provider:T25ProductionRouterProvider",
        "provider_kind": "REAL_CANDIDATE", "provider_synthetic": False,
        "workspace_mode": "REAL_EXPERIMENT",
        "firewall_search_provider_used": False, "t26_firewall_used": False,
        "inner_live_or_fixture": "live", "external_authority": False,
        "candidate_gold_access": False, "corpus_source": "FROZEN_PUBLIC",
        "document_root_source": "PER_SCENARIO_PRIVATE_WORKSPACE",
    }
    refused("unfirewalled_live_provider", lambda: validate_stack_attestation(
        bad_stack, real=True))
    with TemporaryDirectory(prefix="t26-wrong-corpus-") as tmp:
        refused("caller_selected_corpus_path", lambda: validate_corpus_mount(
            root, Path(tmp)))
    refused("gold_containing_mount", lambda: validate_gold_free_mount(
        root / "construction/gold.json"))
    ordered = [{"control": name, "refused": results[name]}
               for name in sorted(results)]
    new_refused = sum(results.values())
    total = old["control_count"] + len(results)
    return {
        "schema_version": "t26-production-runner-negative-controls-v1",
        "artifact": "T26_PRODUCTION_RUNNER_NEGATIVE_CONTROLS",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(results.values()) else "FAIL",
        "old_control_count": old["control_count"],
        "old_refused_count": old["refused_count"],
        "new_control_count": len(results), "new_refused_count": new_refused,
        "total_control_count": total,
        "total_refused_count": old["refused_count"] + new_refused,
        "not_refused": sorted(name for name, ok in results.items() if not ok),
        "new_controls": ordered,
        "real_private_rows_read": 0, "real_candidate_executions": 0,
        "official_evaluator_invocations": 0,
    }
