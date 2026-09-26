"""Additive T26 V3/V4-compatible evaluation protocol.

This module supersedes only ``t26_protocol.lifecycle:evaluate_once``.  It does
not alter construction, scoring, production execution, the candidate, or the
original 244-component V3 construction freeze.  Real evaluation remains
token-gated and is intentionally never invoked by addendum requalification.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from t21_protocol.util import sha256_json

from .construction import recompute_manifest_roots, run_publication_leak_gate
from .lifecycle import T26PrivateStore
from .scorer import score_suite

EVALUATION_TOKEN = "T26_ONE_SHOT_OFFICIAL_EVALUATION"
SYNTHETIC_TOKEN = "T26_DISPOSABLE_SYNTHETIC_EVALUATION"
EVALUATION_IMPLEMENTATION = "t26_protocol.evaluation_v2:run_real_evaluation"
LEGACY_IMPLEMENTATION = "t26_protocol.lifecycle:evaluate_once"

LEDGER_SCHEMA = "t26-evaluation-ledger-v2"
MARKER_SCHEMA = "t26-evaluation-one-shot-marker-v1"
RECEIPT_SCHEMA = "t26-public-evaluation-receipt-v2"
ADDENDUM_SCHEMA = "t26-evaluation-protocol-addendum-v1"
ADDENDUM_FREEZE_SCHEMA = "t26-evaluation-addendum-freeze-v1"
LEDGER_PATH = "evaluation/ledger.json"
MARKER_PATH = "evaluation/one_shot_spent.json"
STATES = ("STARTED", "EXECUTED", "SCORED", "COMPLETE")
NEXT_STATE = {"STARTED": "EXECUTED", "EXECUTED": "SCORED",
              "SCORED": "COMPLETE"}

CONSTRUCTION_PUBLIC_COMMIT = "4fb890d99806d484d59c7a667df61ed4d1cbfed8"
ORIGINAL_FREEZE_SHA256 = "b0c49c7f6370130420e9881a9312fd87e212c09d5818df9876f0ba28f534e3dd"
ORIGINAL_FREEZE_COMPONENT_ROOT = "b59aa987472f1b7ef1d098ebf80fc5a3b1b6244fb96eba3ca852c6ee0c725a0a"
ORIGINAL_FREEZE_ROOT = "7ec02173e02fb498ebe487aa01e225fa1e6c0c8600672aeec0b107e363efa5da"
ORIGINAL_FREEZE_COMPONENT_COUNT = 244

SCORER_SHA256 = "c0185f150c8d52d0c3b451a9e7a076de82cd48c3cd0a3e36ab309a28e9aefa15"
METRIC_REGISTRY_SHA256 = "3cc8b0b5e09ebd29b809a6fe50e5ff27854778c2b749b787746a0509cf3b67b4"
PRODUCTION_SHA256 = "594a481fcbf1ea4ad04fe8ce7fae4a9c01a07a2a83563689347b7fae32088697"
AUTHORITY_GRAPH_SHA256 = "2c1400d8d42795bcab30ceb2f651c0c9d54f90add0230614c51eff5f6b154e36"
FIREWALL_SHA256 = "172cdd1965a7efd5eed8617768967da51001949152b45b5c5e8a2a786d9bd03d"

# Public-safe SHA-256 commitments used only to detect exact blind blobs in
# reachable Git history.  No private bytes are needed by this scan.
SEALED_BLIND_CONTENT_SHA256 = frozenset({
    "f730610c6a7bcb6849f782742c9551b5b46ec216e4b353e19af3fb440bf4675d",
    "5bae5ed8dd557b8ee41c95b783300da4c9eb125fa6afa5983b39cacb49a1ba81",
})

GOLD_ONLY_FIELDS = frozenset({
    "family", "expected_terminal", "expected_answer", "expected_capabilities",
    "expected_replan_trigger", "recoverable_failure", "safe_abstention",
    "scoring_metadata", "score", "gold",
})

LEDGER_BINDING_FIELDS = (
    "experiment", "attempt", "authorization", "material_mode",
    "candidate_commit", "candidate_tree", "runtime_root",
    "construction_seal_sha256", "construction_ledger_sha256",
    "construction_ledger_root", "private_manifest_sha256",
    "private_artifact_root", "private_blind_root",
    "original_v3_freeze_sha256", "original_v3_freeze_root",
    "evaluation_addendum_freeze_sha256", "evaluation_addendum_freeze_root",
    "scorer_sha256", "metric_registry_sha256", "production_runtime_sha256",
    "authority_graph_sha256", "firewall_sha256",
)

ADDENDUM_COMPONENTS = {
    "t26_protocol/evaluation_v2.py": "EVALUATION_PROTOCOL",
    "tests/test_t26_evaluation_v2.py": "EVALUATION_TEST_GATE",
    "scripts/t26_evaluation_addendum.py": "EVALUATION_REPRODUCTION_ENTRYPOINT",
    "evaluations/t26/T26_EVALUATION_PROTOCOL_ADDENDUM.json": "PUBLIC_ADDENDUM",
    "evaluations/t26/T26_EVALUATION_REHEARSAL_REPORT.json": "PUBLIC_REHEARSAL_REPORT",
    "evaluations/t26/T26_EVALUATION_NEGATIVE_CONTROLS.json": "PUBLIC_NEGATIVE_CONTROLS",
    "T26_CONSTRUCTION_PUBLIC_RECEIPT.json": "SEALED_CONSTRUCTION_RECEIPT",
    "T26_PUBLIC_CONSTRUCTION_COMMITMENT.json": "SEALED_CONSTRUCTION_COMMITMENT",
    "evaluations/t26/preconstruction_freeze.json": "ORIGINAL_V3_FREEZE",
    "evaluations/t26/candidate_identity.json": "CANDIDATE_IDENTITY",
    "t26_protocol/construction.py": "SEALED_CONSTRUCTION_PROTOCOL",
    "t26_protocol/lifecycle.py": "PRIVATE_STORE_RUNTIME",
    "t26_protocol/scorer.py": "FROZEN_SCORER",
    "t26_protocol/production.py": "FROZEN_PRODUCTION_RUNTIME",
    "src/sciencemath/integrated/runner.py": "FROZEN_CANDIDATE_RUNTIME",
    "evaluations/t26/metric_registry.json": "FROZEN_METRIC_REGISTRY",
    "evaluations/t26/authority_graph.json": "FROZEN_AUTHORITY_GRAPH",
    "evaluations/t26/live_web_firewall_registry.json": "FROZEN_FIREWALL",
}


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()


def _fetch_prune_public_refs(root: Path) -> tuple[str, ...]:
    """Refresh and enumerate every public remote/tag ref before one-shot use."""
    subprocess.run(
        ["git", "fetch", "--prune", "--tags", "--no-recurse-submodules",
         "origin"],
        cwd=root, capture_output=True, text=True, check=True)
    refs = tuple(filter(None, _git(
        root, "for-each-ref", "--format=%(refname)",
        "refs/remotes/origin", "refs/tags").splitlines()))
    if not refs:
        raise ValueError("no fetched public refs available for T26 leak preflight")
    return refs


def _repo_bytes(root: Path, relative: str) -> bytes:
    """Hash the normalized representation Git stores, independent of CRLF."""
    from .freeze import _repository_bytes, _text_attributes

    attribute = _text_attributes(root, [relative])[relative]
    return _repository_bytes(root, relative, attribute)


def _repo_sha(root: Path, relative: str) -> str:
    return _sha(_repo_bytes(root, relative))


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def validate_candidate_payload(candidate_case: dict[str, Any]) -> None:
    if set(candidate_case) != {"scenario_id", "plan", "classification"}:
        raise ValueError("candidate-visible scenario schema mismatch")
    leaked = sorted(GOLD_ONLY_FIELDS & _walk_keys(candidate_case))
    if leaked:
        raise ValueError(f"candidate-visible gold field exposure: {leaked}")


def candidate_view(scenario: dict[str, Any]) -> dict[str, Any]:
    if set(scenario) != {"scenario_id", "plan", "classification", "family"}:
        raise ValueError("sealed scenario schema mismatch")
    candidate_case = {key: scenario[key]
                      for key in ("scenario_id", "plan", "classification")}
    validate_candidate_payload(candidate_case)
    return candidate_case


def verify_original_v3_components(root: Path) -> dict[str, Any]:
    """Verify the explicit original 244-component set, ignoring additions."""
    root = Path(root).resolve()
    frozen = json.loads((root / "evaluations/t26/preconstruction_freeze.json")
                        .read_text(encoding="utf-8"))
    if (frozen.get("freeze_sha256") != ORIGINAL_FREEZE_SHA256 or
            frozen.get("component_count") != ORIGINAL_FREEZE_COMPONENT_COUNT or
            frozen.get("component_root") != ORIGINAL_FREEZE_COMPONENT_ROOT or
            frozen.get("freeze_root") != ORIGINAL_FREEZE_ROOT):
        raise ValueError("original V3 freeze identity mismatch")
    relatives = [entry["path"] for entry in frozen["components"]]
    from .freeze import _repository_bytes, _text_attributes

    attributes = _text_attributes(root, relatives)
    recomputed = []
    for entry in frozen["components"]:
        relative = entry["path"]
        data = _repository_bytes(root, relative, attributes[relative])
        current = {"path": relative, "sha256": _sha(data),
                   "byte_size": len(data), "role": entry["role"]}
        recomputed.append(current)
    mismatches = [entry["path"] for entry, actual in
                  zip(frozen["components"], recomputed, strict=True)
                  if entry != actual]
    component_root = sha256_json(recomputed)
    root_input = {key: value for key, value in frozen.items()
                  if key not in {"component_count", "components", "freeze_root",
                                 "freeze_sha256"}}
    freeze_root = sha256_json(root_input)
    without_sha = {key: value for key, value in frozen.items()
                   if key != "freeze_sha256"}
    freeze_sha = _sha(json.dumps(
        without_sha, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8"))
    if (mismatches or component_root != ORIGINAL_FREEZE_COMPONENT_ROOT or
            freeze_root != ORIGINAL_FREEZE_ROOT or
            freeze_sha != ORIGINAL_FREEZE_SHA256):
        raise ValueError("original V3 frozen component drift")
    return {"status": "PASS", "component_count": len(recomputed),
            "component_root": component_root, "freeze_root": freeze_root,
            "freeze_sha256": freeze_sha, "mismatches": []}


def _verify_authority(root: Path) -> dict[str, Any]:
    graph = json.loads((root / "evaluations/t26/authority_graph.json")
                       .read_text(encoding="utf-8"))
    nodes = graph["nodes"]
    candidate_nodes = (
        "planner", "plan_validator", "orchestrator", "executive_router",
        "capability_dispatcher", "capabilities", "handoff_validator",
        "verification_layer", "checkpoint_manager", "replan_controller",
        "budget_controller", "completion_gate",
    )
    if (nodes["planner"]["may_execute"] or
            nodes["planner"]["may_perform_external_action"] or
            nodes["orchestrator"]["may_execute"] !=
            ["registered_internal_capability"] or
            nodes["orchestrator"]["may_perform_external_action"] or
            graph.get("external_action_authority") is not False or
            any(nodes[name]["gold_access"] for name in candidate_nodes)):
        raise ValueError("frozen authority boundary mismatch")
    return {"status": "PASS", "planner_authority": "PROPOSE_ONLY",
            "orchestrator_authority": "COORDINATE_INTERNAL_WORK_ONLY",
            "external_autonomous_action_authority": False,
            "candidate_gold_access": False}


def build_addendum_document(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    receipt = json.loads((root / "T26_CONSTRUCTION_PUBLIC_RECEIPT.json")
                         .read_text(encoding="utf-8"))
    commitment = json.loads((root / "T26_PUBLIC_CONSTRUCTION_COMMITMENT.json")
                            .read_text(encoding="utf-8"))
    candidate = json.loads((root / "evaluations/t26/candidate_identity.json")
                           .read_text(encoding="utf-8"))
    freeze = json.loads((root / "evaluations/t26/preconstruction_freeze.json")
                        .read_text(encoding="utf-8"))
    authority = _verify_authority(root)
    if receipt["receipt_root"] != "526680d17c73f033528b4ead95a4f3f98999180b0d432f64f85fa4bb85909d51":
        raise ValueError("construction receipt root mismatch")
    if commitment["commitment_root"] != "231eb9bf766a046ca93ae4cb935e3d71bbd00a5167578961ab17fce87e05d03c":
        raise ValueError("construction commitment root mismatch")
    identities = {
        "scorer_sha256": _repo_sha(root, "t26_protocol/scorer.py"),
        "metric_registry_sha256": _repo_sha(
            root, "evaluations/t26/metric_registry.json"),
        "production_runtime_sha256": _repo_sha(root, "t26_protocol/production.py"),
        "authority_graph_sha256": _repo_sha(
            root, "evaluations/t26/authority_graph.json"),
        "firewall_sha256": _repo_sha(
            root, "evaluations/t26/live_web_firewall_registry.json"),
    }
    expected = {
        "scorer_sha256": SCORER_SHA256,
        "metric_registry_sha256": METRIC_REGISTRY_SHA256,
        "production_runtime_sha256": PRODUCTION_SHA256,
        "authority_graph_sha256": AUTHORITY_GRAPH_SHA256,
        "firewall_sha256": FIREWALL_SHA256,
    }
    if identities != expected:
        raise ValueError("frozen evaluation dependency drift")
    return {
        "schema_version": ADDENDUM_SCHEMA,
        "artifact": "T26_EVALUATION_PROTOCOL_ADDENDUM",
        "experiment": "t26",
        "classification": "PUBLIC_SAFE",
        "root_cause": "PRE_EVALUATION_INFRASTRUCTURE_SCHEMA_COMPATIBILITY_DEFECT",
        "legacy_evaluation_entrypoint": LEGACY_IMPLEMENTATION,
        "legacy_entrypoint_status": "SUPERSEDED_PRE_EVALUATION_NO_REAL_EXECUTION",
        "replacement_evaluation_entrypoint": EVALUATION_IMPLEMENTATION,
        "construction_superseded": False,
        "construction_public_commit": CONSTRUCTION_PUBLIC_COMMIT,
        "construction_receipt_root": receipt["receipt_root"],
        "construction_commitment_root": commitment["commitment_root"],
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "construction_ledger_sha256": receipt["construction_ledger_sha256"],
        "construction_ledger_root": receipt["construction_ledger_root"],
        "private_manifest_sha256": receipt["private_manifest_sha256"],
        "private_artifact_root": receipt["private_artifact_root"],
        "private_blind_root": receipt["private_blind_root"],
        "construction_seal_sha256": receipt["seal_sha256"],
        "original_v3_freeze_sha256": freeze["freeze_sha256"],
        "original_v3_freeze_component_count": freeze["component_count"],
        "original_v3_freeze_component_root": freeze["component_root"],
        "original_v3_freeze_root": freeze["freeze_root"],
        **identities,
        "evaluation_authorization_token": EVALUATION_TOKEN,
        "evaluation_implementation_sha256": _repo_sha(
            root, "t26_protocol/evaluation_v2.py"),
        "seal_schema": "t26-holdout-seal-v3",
        "manifest_schema": "t26-private-manifest-v4",
        "evaluation_ledger_schema": LEDGER_SCHEMA,
        "evaluation_state_machine": list(STATES),
        "failure_state": "FAILED",
        "real_evaluation_authorized": False,
        "external_action_authority": False,
        "authority_verification": authority,
        "raw_private_content_included": False,
    }


def verify_addendum_document(root: Path,
                             document: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    observed = document if document is not None else json.loads(
        (root / "evaluations/t26/T26_EVALUATION_PROTOCOL_ADDENDUM.json")
        .read_text(encoding="utf-8"))
    expected = build_addendum_document(root)
    if observed != expected:
        raise ValueError("T26 evaluation addendum identity mismatch")
    return dict(observed)


def build_addendum_freeze(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    addendum = verify_addendum_document(root)
    original = verify_original_v3_components(root)
    entries = []
    for relative, role in sorted(ADDENDUM_COMPONENTS.items()):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"evaluation addendum component missing: {relative}")
        data = _repo_bytes(root, relative)
        entries.append({"path": relative, "sha256": _sha(data),
                        "byte_size": len(data), "role": role})
    core = {
        "schema_version": ADDENDUM_FREEZE_SCHEMA,
        "artifact": "T26_EVALUATION_ADDENDUM_FREEZE",
        "experiment": "t26",
        "classification": "PUBLIC_SAFE",
        "original_v3_freeze_sha256": original["freeze_sha256"],
        "original_v3_freeze_component_root": original["component_root"],
        "original_v3_freeze_root": original["freeze_root"],
        "construction_public_commit": addendum["construction_public_commit"],
        "construction_receipt_root": addendum["construction_receipt_root"],
        "construction_commitment_root": addendum["construction_commitment_root"],
        "candidate_commit": addendum["candidate_commit"],
        "candidate_tree": addendum["candidate_tree"],
        "runtime_root": addendum["runtime_root"],
        "evaluation_implementation_sha256":
            addendum["evaluation_implementation_sha256"],
        "scorer_sha256": addendum["scorer_sha256"],
        "metric_registry_sha256": addendum["metric_registry_sha256"],
        "production_runtime_sha256": addendum["production_runtime_sha256"],
        "authority_graph_sha256": addendum["authority_graph_sha256"],
        "firewall_sha256": addendum["firewall_sha256"],
        "real_evaluation_authorized": False,
        "original_construction_freeze_replaced": False,
    }
    document = {**core, "component_count": len(entries),
                "components": entries, "component_root": sha256_json(entries),
                "freeze_root": sha256_json(core)}
    document["freeze_sha256"] = _sha(json.dumps(
        document, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8"))
    return document


def verify_addendum_freeze(root: Path,
                           document: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    observed = document if document is not None else json.loads(
        (root / "evaluations/t26/T26_EVALUATION_ADDENDUM_FREEZE.json")
        .read_text(encoding="utf-8"))
    expected = build_addendum_freeze(root)
    if observed != expected:
        raise ValueError("T26 evaluation addendum freeze mismatch")
    return {"status": "PASS", "component_count": observed["component_count"],
            "component_root": observed["component_root"],
            "freeze_root": observed["freeze_root"],
            "freeze_sha256": observed["freeze_sha256"]}


def _resolve_manifest_artifact(manifest: dict[str, Any], logical_id: str,
                               classification: str) -> dict[str, Any]:
    matches = [entry for entry in manifest.get("artifacts", [])
               if entry.get("logical_id") == logical_id]
    if len(matches) != 1:
        raise ValueError(f"sealed manifest artifact cardinality mismatch: {logical_id}")
    entry = matches[0]
    if (entry.get("classification") != classification or
            not isinstance(entry.get("sha256"), str) or
            len(entry["sha256"]) != 64 or
            not isinstance(entry.get("byte_size"), int) or
            entry["byte_size"] <= 0):
        raise ValueError(f"sealed manifest artifact binding invalid: {logical_id}")
    return dict(entry)


def _verify_store_artifact(store: T26PrivateStore,
                           entry: dict[str, Any]) -> bytes:
    commitment = store.commitment(entry["logical_id"])
    if (commitment.get("classification") != entry["classification"] or
            commitment.get("sha256") != entry["sha256"] or
            commitment.get("bytes") != entry["byte_size"]):
        raise ValueError("private store/manifest artifact commitment mismatch")
    data = store.read_bytes(entry["logical_id"])
    if _sha(data) != entry["sha256"] or len(data) != entry["byte_size"]:
        raise ValueError("sealed private artifact bytes drifted")
    return data


def verify_store_compatibility(
        store: T26PrivateStore, root: Path, *,
        expected_addendum: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Verify V3 seal/V4 manifest and locate exact input/gold artifacts."""
    root = Path(root).resolve()
    store_verification = store.verify()
    manifest_bytes = store.read_bytes("construction/manifest.json")
    seal_bytes = store.read_bytes("construction/seal.json")
    ledger_bytes = store.read_bytes("construction/ledger.json")
    manifest = json.loads(manifest_bytes)
    seal = json.loads(seal_bytes)
    ledger = json.loads(ledger_bytes)
    if manifest.get("schema_version") != "t26-private-manifest-v4":
        raise ValueError("T26 evaluator requires t26-private-manifest-v4")
    if (seal.get("schema_version") != "t26-holdout-seal-v3" or
            seal.get("state") != "SEALED" or ledger.get("state") != "SEALED"):
        raise ValueError("T26 evaluator requires a sealed V3 construction")
    if _sha(manifest_bytes) != seal.get("private_manifest_sha256"):
        raise ValueError("private manifest/seal hash mismatch")
    roots = recompute_manifest_roots(manifest)
    if any(manifest.get(key) != value for key, value in roots.items()):
        raise ValueError("private manifest root recomputation mismatch")
    candidate = manifest["candidate_identity"]
    freeze = manifest["freeze_identity"]
    for key in ("candidate_commit", "candidate_tree", "runtime_root"):
        if seal.get(key) != candidate.get(key):
            raise ValueError("candidate identity differs between manifest and seal")
    for seal_key, manifest_key in (
            ("freeze_sha256", "freeze_sha256"),
            ("freeze_component_root", "component_root"),
            ("freeze_root", "freeze_root")):
        if seal.get(seal_key) != freeze.get(manifest_key):
            raise ValueError("freeze identity differs between manifest and seal")
    inputs = _resolve_manifest_artifact(
        manifest, "construction/inputs.json", "REAL_BLIND_INPUT")
    gold = _resolve_manifest_artifact(
        manifest, "construction/gold.json", "REAL_BLIND_GOLD")
    if expected_addendum is not None:
        checks = {
            "candidate_commit": candidate["candidate_commit"],
            "candidate_tree": candidate["candidate_tree"],
            "runtime_root": candidate["runtime_root"],
            "private_manifest_sha256": _sha(manifest_bytes),
            "private_artifact_root": manifest["private_artifact_root"],
            "private_blind_root": manifest["private_blind_root"],
            "construction_seal_sha256": _sha(seal_bytes),
            "construction_ledger_sha256": _sha(ledger_bytes),
            "construction_ledger_root": ledger["final_event_hash"],
            "original_v3_freeze_sha256": freeze["freeze_sha256"],
            "original_v3_freeze_root": freeze["freeze_root"],
        }
        if any(expected_addendum.get(key) != value
               for key, value in checks.items()):
            raise ValueError("sealed construction/addendum binding mismatch")
    return {"status": "PASS", "store_verification": store_verification,
            "manifest": manifest, "seal": seal, "ledger": ledger,
            "manifest_sha256": _sha(manifest_bytes),
            "seal_sha256": _sha(seal_bytes),
            "ledger_sha256": _sha(ledger_bytes),
            "manifest_roots": roots, "inputs_entry": inputs,
            "gold_entry": gold}


def require_publication_pass(report: dict[str, Any]) -> None:
    if (report.get("status") != "PASS" or report.get("blind_blob_count") != 0 or
            report.get("path_policy_violations")):
        raise ValueError("T26_OFFICIAL_EVALUATION_REFUSED_PUBLICATION_LEAKAGE")


def require_sealed_state(seal: dict[str, Any]) -> None:
    if seal.get("state") != "SEALED":
        raise ValueError("unsealed T26 construction refused")


def validate_evaluation_attempt(attempt: int) -> None:
    if attempt != 1:
        raise ValueError("T26 evaluation permits attempt 1 only")


def _marker_committed(store: T26PrivateStore) -> bool:
    try:
        store.commitment(MARKER_PATH)
        return True
    except (KeyError, ValueError):
        return False


def require_evaluation_absent(store: T26PrivateStore) -> None:
    if (store.has(LEDGER_PATH) or store.has(MARKER_PATH) or
            _marker_committed(store)):
        raise EvaluationLedgerError("T26 evaluation one-shot already spent")


class EvaluationLedgerError(RuntimeError):
    """Terminal evaluation one-shot or state-machine violation."""


class EvaluationTechnicalAbort(RuntimeError):
    """Official post-ledger failure; the evaluation one-shot remains spent."""


class T26EvaluationLedger:
    def __init__(self, store: T26PrivateStore, document: dict[str, Any]) -> None:
        self.store = store
        self.document = document

    @classmethod
    def create_exclusive(cls, store: T26PrivateStore,
                         bindings: dict[str, Any]) -> "T26EvaluationLedger":
        validate_evaluation_attempt(bindings.get("attempt"))
        if set(bindings) != set(LEDGER_BINDING_FIELDS):
            raise ValueError("evaluation ledger binding set mismatch")
        require_evaluation_absent(store)
        created = _now()
        event = {"event_index": 0, "event_type": "STARTED",
                 "timestamp": created, "previous_event_hash": "0" * 64,
                 "payload": {"one_shot_spent": True}}
        event["event_hash"] = sha256_json(event)
        document = {
            "schema_version": LEDGER_SCHEMA,
            "artifact": "T26_OFFICIAL_EVALUATION_LEDGER",
            "experiment": "t26", "attempt": 1,
            "authorization": bindings["authorization"],
            "material_mode": bindings["material_mode"],
            "state": "STARTED", "created_at": created,
            "updated_at": created, "bindings": dict(sorted(bindings.items())),
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
                        {"error": "evaluation one-shot marker creation failed"})
            raise
        return ledger

    @property
    def state(self) -> str:
        return str(self.document["state"])

    def advance(self, target: str, payload: dict[str, Any]) -> None:
        if NEXT_STATE.get(self.state) != target:
            raise EvaluationLedgerError(
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
            raise EvaluationLedgerError("complete evaluation cannot fail")
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
        if document != self.document:
            raise EvaluationLedgerError("evaluation ledger drift")
        if (document.get("schema_version") != LEDGER_SCHEMA or
                document.get("artifact") != "T26_OFFICIAL_EVALUATION_LEDGER" or
                document.get("experiment") != "t26" or
                document.get("attempt") != 1 or
                set(document.get("bindings", {})) != set(LEDGER_BINDING_FIELDS)):
            raise EvaluationLedgerError("evaluation ledger envelope invalid")
        if (document.get("event_count") != len(document.get("events", [])) or
                not document.get("events")):
            raise EvaluationLedgerError("evaluation event count mismatch")
        previous = "0" * 64
        for index, event in enumerate(document["events"]):
            if (event["event_index"] != index or
                    event["previous_event_hash"] != previous):
                raise EvaluationLedgerError("evaluation event chain broken")
            body = {key: value for key, value in event.items()
                    if key != "event_hash"}
            if sha256_json(body) != event["event_hash"]:
                raise EvaluationLedgerError("evaluation event hash mismatch")
            previous = event["event_hash"]
        states = [event["event_type"] for event in document["events"]]
        if states[0] != "STARTED":
            raise EvaluationLedgerError("evaluation genesis state invalid")
        for prior, current in zip(states, states[1:]):
            if current != "FAILED" and NEXT_STATE.get(prior) != current:
                raise EvaluationLedgerError("evaluation transition invalid")
        if (document.get("state") != states[-1] or
                document.get("final_event_hash") != previous):
            raise EvaluationLedgerError("evaluation terminal envelope mismatch")
        if states[-1] == "FAILED" and "failure" not in document:
            raise EvaluationLedgerError("failed evaluation lacks failure evidence")
        marker = self.store.read(MARKER_PATH)
        if (marker.get("schema_version") != MARKER_SCHEMA or
                marker.get("artifact") != "T26_EVALUATION_ONE_SHOT_SPENT" or
                marker.get("experiment") != "t26" or
                marker.get("attempt") != 1 or
                marker.get("ledger_genesis_hash") !=
                document["events"][0]["event_hash"]):
            raise EvaluationLedgerError("evaluation marker mismatch")
        return {"status": "PASS", "state": document["state"],
                "event_count": document["event_count"],
                "final_event_hash": document["final_event_hash"]}


def load_evaluation_ledger(store: T26PrivateStore) -> T26EvaluationLedger:
    if not store.has(LEDGER_PATH):
        raise ValueError("T26 evaluation ledger absent")
    return T26EvaluationLedger(store, store.read(LEDGER_PATH))


def _evaluation_bindings(compatibility: dict[str, Any],
                         addendum: dict[str, Any],
                         addendum_freeze: dict[str, Any], *, token: str,
                         material_mode: str) -> dict[str, Any]:
    manifest = compatibility["manifest"]
    ledger = compatibility["ledger"]
    return {
        "experiment": "t26", "attempt": 1,
        "authorization": token, "material_mode": material_mode,
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
        "evaluation_addendum_freeze_sha256": addendum_freeze["freeze_sha256"],
        "evaluation_addendum_freeze_root": addendum_freeze["freeze_root"],
        "scorer_sha256": addendum["scorer_sha256"],
        "metric_registry_sha256": addendum["metric_registry_sha256"],
        "production_runtime_sha256": addendum["production_runtime_sha256"],
        "authority_graph_sha256": addendum["authority_graph_sha256"],
        "firewall_sha256": addendum["firewall_sha256"],
    }


def build_public_evaluation_receipt(
        store: T26PrivateStore, ledger: T26EvaluationLedger,
        score: dict[str, Any], compatibility: dict[str, Any],
        result_hashes: dict[str, str]) -> dict[str, Any]:
    if ledger.state != "COMPLETE":
        raise ValueError("public evaluation receipt requires COMPLETE ledger")
    bindings = ledger.document["bindings"]
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "artifact": "T26_PUBLIC_EVALUATION_RECEIPT",
        "experiment": "t26", "attempt": 1, "state": "COMPLETE",
        "capability_status": score["status"],
        "scenario_count": score["scenario_count"],
        "metrics": score["metrics"],
        "critical_counters": score["critical_counters"],
        "candidate_commit": bindings["candidate_commit"],
        "candidate_tree": bindings["candidate_tree"],
        "runtime_root": bindings["runtime_root"],
        "construction_seal_sha256": compatibility["seal_sha256"],
        "evaluation_ledger_sha256": store.commitment(LEDGER_PATH)["sha256"],
        "evaluation_ledger_root": ledger.document["final_event_hash"],
        "private_result_hashes": dict(sorted(result_hashes.items())),
        "raw_rows_included": False, "gold_included": False,
        "scenario_bodies_included": False,
    }
    receipt["receipt_root"] = sha256_json(
        {key: value for key, value in receipt.items() if key != "receipt_root"})
    return receipt


def _require_token(token: str, *, real: bool) -> None:
    expected = EVALUATION_TOKEN if real else SYNTHETIC_TOKEN
    if token != expected:
        raise PermissionError("exact T26 evaluation authorization token required")


def _run_evaluation(
        root: Path, store: T26PrivateStore, *, token: str,
        runner_factory: Callable[[Path], Any], real: bool,
        refs: tuple[str, ...] = (), inject_failure_after_ledger: bool = False,
        verify_freeze_document: bool = True,
) -> dict[str, Any]:
    root = Path(root).resolve()
    _require_token(token, real=real)
    addendum = verify_addendum_document(root)
    original = verify_original_v3_components(root)
    if verify_freeze_document:
        freeze_verification = verify_addendum_freeze(root)
        addendum_freeze = json.loads(
            (root / "evaluations/t26/T26_EVALUATION_ADDENDUM_FREEZE.json")
            .read_text(encoding="utf-8"))
    else:
        freeze_verification = {"status": "NOT_YET_FINALIZED"}
        addendum_freeze = {
            "freeze_sha256": "0" * 64, "freeze_root": "0" * 64}
    require_evaluation_absent(store)
    compatibility = verify_store_compatibility(
        store, root, expected_addendum=addendum if real else None)
    require_sealed_state(compatibility["seal"])
    scan_refs = refs
    if real:
        refreshed_refs = _fetch_prune_public_refs(root)
        scan_refs = tuple(sorted(set(refreshed_refs) | set(refs)))
    leak_report = run_publication_leak_gate(store, root, refs=scan_refs)
    require_publication_pass(leak_report)

    inputs_bytes = _verify_store_artifact(store, compatibility["inputs_entry"])
    gold_bytes = _verify_store_artifact(store, compatibility["gold_entry"])
    cases = json.loads(inputs_bytes)
    gold = json.loads(gold_bytes)
    if len(cases) != 512 or len(gold) != 512:
        raise ValueError("sealed evaluation cardinality must be 512/512")
    candidate_cases = [candidate_view(scenario) for scenario in cases]
    if any(key.get("scenario_id") != scenario.get("scenario_id")
           for scenario, key in zip(cases, gold, strict=True)):
        raise ValueError("sealed scenario/gold identity mismatch")

    bindings = _evaluation_bindings(
        compatibility, addendum, addendum_freeze, token=token,
        material_mode="REAL_BLIND" if real else "DISPOSABLE_SYNTHETIC")
    ledger: T26EvaluationLedger | None = None
    try:
        ledger = T26EvaluationLedger.create_exclusive(store, bindings)
        if inject_failure_after_ledger:
            raise RuntimeError("injected post-ledger evaluation failure")
        outputs = []
        plans = []
        workspaces = []
        for index, candidate_case in enumerate(candidate_cases):
            workspace_id = "case-%04d-%s" % (
                index, hashlib.sha256(candidate_case["scenario_id"].encode())
                .hexdigest()[:12])
            case_root = store.path(f"evaluation/workspaces/{workspace_id}")
            case_root.mkdir(parents=True, exist_ok=False)
            workspaces.append(workspace_id)
            runner = runner_factory(case_root)
            if not hasattr(runner, "run"):
                raise TypeError("evaluation runner factory returned no run method")
            outputs.append(runner.run(candidate_case))
            plans.append(candidate_case["plan"])
        if len(outputs) != 512 or len(set(workspaces)) != 512:
            raise RuntimeError("evaluation execution/workspace cardinality mismatch")
        raw_meta = store.write_once(
            "evaluation/raw_outputs.json", outputs,
            classification="PRIVATE_EVALUATION")
        provenance = {
            "schema_version": "t26-evaluation-provenance-v1",
            "artifact": "T26_EVALUATION_PROVENANCE",
            "experiment": "t26", "attempt": 1,
            "material_mode": bindings["material_mode"],
            "candidate_execution_count": len(outputs),
            "workspace_count": len(workspaces),
            "workspace_reuse_count": len(workspaces) - len(set(workspaces)),
            "workspace_identity_root": sha256_json(workspaces),
            "external_action_authority": False,
            "candidate_gold_access": False,
            "runner_initialization_executes_scenario": False,
            "construction_scenarios_rerun": 0,
        }
        provenance_meta = store.write_once(
            "evaluation/provenance.json", provenance,
            classification="PRIVATE_EVALUATION")
        ledger.advance("EXECUTED", {
            "candidate_execution_count": len(outputs),
            "raw_outputs_sha256": raw_meta["sha256"],
            "provenance_sha256": provenance_meta["sha256"],
        })

        scored = score_suite(outputs, gold, plans)
        rows = scored.pop("rows")
        scored_meta = store.write_once(
            "evaluation/scored_rows.json", rows,
            classification="PRIVATE_EVALUATION")
        summary_meta = store.write_once(
            "evaluation/summary.json", scored,
            classification="PRIVATE_EVALUATION")
        ledger.advance("SCORED", {
            "scenario_count": scored["scenario_count"],
            "capability_status": scored["status"],
            "scored_rows_sha256": scored_meta["sha256"],
            "summary_sha256": summary_meta["sha256"],
        })
        ledger.advance("COMPLETE", {
            "scenario_count": scored["scenario_count"],
            "raw_outputs_sha256": raw_meta["sha256"],
            "scored_rows_sha256": scored_meta["sha256"],
            "summary_sha256": summary_meta["sha256"],
            "provenance_sha256": provenance_meta["sha256"],
        })
        chain = ledger.verify()
        final_store = store.verify()
        result_hashes = {
            "raw_outputs_sha256": raw_meta["sha256"],
            "scored_rows_sha256": scored_meta["sha256"],
            "summary_sha256": summary_meta["sha256"],
            "provenance_sha256": provenance_meta["sha256"],
        }
        receipt = build_public_evaluation_receipt(
            store, ledger, scored, compatibility, result_hashes)
        verdict = ("T26_ONE_SHOT_OFFICIAL_EVALUATION_COMPLETE_CAPABILITY_PASS"
                   if scored["status"] == "PASS" else
                   "T26_ONE_SHOT_OFFICIAL_EVALUATION_COMPLETE_CAPABILITY_FAIL")
        return {
            "status": "COMPLETE", "verdict": verdict,
            "material_mode": bindings["material_mode"],
            "scenario_count": len(outputs), "score": scored,
            "ledger": ledger.document, "ledger_verification": chain,
            "store_verification": final_store, "receipt": receipt,
            "compatibility": {
                "status": compatibility["status"],
                "manifest_schema": compatibility["manifest"]["schema_version"],
                "seal_schema": compatibility["seal"]["schema_version"],
                "manifest_roots": compatibility["manifest_roots"],
            },
            "gold_firewall": {"status": "PASS",
                              "candidate_fields": sorted(candidate_cases[0]),
                              "gold_fields_exposed": 0},
            "publication_gate": leak_report,
            "original_freeze_verification": original,
            "addendum_freeze_verification": freeze_verification,
        }
    except Exception as exc:
        spent_ledger = ledger
        if spent_ledger is None and store.has(LEDGER_PATH):
            spent_ledger = load_evaluation_ledger(store)
        if (spent_ledger is not None and
                spent_ledger.state not in {"FAILED", "COMPLETE"}):
            spent_ledger.fail(
                spent_ledger.state, type(exc).__name__, {"error": str(exc)})
        if real and spent_ledger is not None:
            raise EvaluationTechnicalAbort(
                "T26_OFFICIAL_EVALUATION_TECHNICAL_ABORT_ONE_SHOT_CONSUMED"
            ) from exc
        raise


def run_real_evaluation(
        root: Path, store: T26PrivateStore, *, token: str,
        runner_factory: Callable[[Path], Any], refs: tuple[str, ...] = (),
        inject_failure_after_ledger: bool = False,
) -> dict[str, Any]:
    """Authorized official entrypoint. Never called during addendum work."""
    return _run_evaluation(
        root, store, token=token, runner_factory=runner_factory, real=True,
        refs=refs, inject_failure_after_ledger=inject_failure_after_ledger,
        verify_freeze_document=True)


def run_disposable_evaluation(
        root: Path, store: T26PrivateStore, *, token: str,
        runner_factory: Callable[[Path], Any], refs: tuple[str, ...] = (),
        inject_failure_after_ledger: bool = False,
        verify_freeze_document: bool = True,
) -> dict[str, Any]:
    """Synthetic-only rehearsal entrypoint using an isolated disposable store."""
    return _run_evaluation(
        root, store, token=token, runner_factory=runner_factory, real=False,
        refs=refs, inject_failure_after_ledger=inject_failure_after_ledger,
        verify_freeze_document=verify_freeze_document)


def build_disposable_sealed_store(root: Path, store: T26PrivateStore,
                                  variant: int) -> dict[str, Any]:
    """Construct a deterministic disposable V4-manifest/V3-seal test store."""
    from .construction import (_synthetic_oracle_result, construct_real,
                               synthetic_author_provenance,
                               synthetic_private_bundle)

    cases, gold, _fixtures = synthetic_private_bundle(variant)
    fixtures: list[dict[str, Any]] = []
    for serial, (scenario, key) in enumerate(zip(cases, gold, strict=True)):
        steps = scenario["plan"]["steps"]
        target = 100000 + serial * 97 + variant * 7919
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


def disposable_runner_factory(_variant: int) -> Callable[[Path], Any]:
    from sciencemath.integrated.runner import IntegratedRunner
    from .qualification import fixture_adapters

    def factory(workspace: Path) -> IntegratedRunner:
        return IntegratedRunner(
            fixture_adapters({"kind": "none"}), sandbox_root=workspace)
    return factory


def semantic_evaluation_view(result: dict[str, Any]) -> dict[str, Any]:
    """Timestamp/root-free rehearsal view used for reproducibility."""
    return {
        "status": result["status"],
        "material_mode": result["material_mode"],
        "scenario_count": result["scenario_count"],
        "capability_status": result["score"]["status"],
        "metrics": result["score"]["metrics"],
        "critical_counters": result["score"]["critical_counters"],
        "ledger_states": [event["event_type"]
                          for event in result["ledger"]["events"]],
        "ledger_event_count": result["ledger"]["event_count"],
        "manifest_schema": result["compatibility"]["manifest_schema"],
        "seal_schema": result["compatibility"]["seal_schema"],
        "gold_firewall": result["gold_firewall"],
        "workspace_count": result["scenario_count"],
        "candidate_execution_count": result["scenario_count"],
        "raw_rows_included": result["receipt"]["raw_rows_included"],
        "gold_included": result["receipt"]["gold_included"],
    }


def run_public_addendum_leak_scan(root: Path,
                                  refs: tuple[str, ...] = ()) -> dict[str, Any]:
    """Full reachable-history scan using only public-safe blind commitments."""
    root = Path(root).resolve()
    refs = refs or tuple(filter(None, _git(
        root, "for-each-ref", "--format=%(refname)",
        "refs/remotes/origin", "refs/tags").splitlines()))
    object_lines = _git(root, "rev-list", "--objects", *refs).splitlines()
    object_ids = sorted({line.split(" ", 1)[0] for line in object_lines})
    check = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=root, input=("\n".join(object_ids) + "\n").encode(),
        capture_output=True, check=True).stdout.decode().splitlines()
    blob_ids = [line.split()[0] for line in check if line.endswith(" blob")]
    raw = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root,
        input=("\n".join(blob_ids) + "\n").encode(),
        capture_output=True, check=True).stdout
    cursor = 0
    matches = 0
    for _expected in blob_ids:
        newline = raw.index(b"\n", cursor)
        header = raw[cursor:newline].decode().split()
        size = int(header[2])
        start = newline + 1
        data = raw[start:start + size]
        cursor = start + size + 1
        if _sha(data) in SEALED_BLIND_CONTENT_SHA256:
            matches += 1
    history_paths = {line.strip() for line in _git(
        root, "log", "--format=", "--name-only", *refs).splitlines()
        if line.strip()}
    worktree_paths = {path.relative_to(root).as_posix()
                      for path in root.rglob("*")
                      if path.is_file() and ".git" not in path.parts}
    forbidden_fragments = (
        "/real_blind/", "/private/", "/evaluation/", "blind/",
        "T26_PRIVATE_AUTHORING", "T26_PRIVATE_EVALUATION")
    path_violations = sorted({path for path in history_paths | worktree_paths
                              if any(fragment in path for fragment in
                                     forbidden_fragments)
                              and path.startswith("evaluations/t26/")})
    status = "PASS" if not matches and not path_violations else "FAIL"
    return {"schema_version": "t26-evaluation-addendum-publication-scan-v1",
            "artifact": "T26_EVALUATION_ADDENDUM_PUBLICATION_SCAN",
            "status": status, "refs_scanned": len(refs),
            "history_object_count": len(object_ids),
            "history_blob_count": len(blob_ids),
            "blind_blob_count": matches,
            "path_policy_violations": path_violations,
            "private_bytes_read": False}


def run_negative_controls(root: Path) -> dict[str, Any]:
    """Public/synthetic refusal matrix; never touches the real T26 store."""
    from copy import deepcopy
    from tempfile import TemporaryDirectory

    root = Path(root).resolve()
    base = build_addendum_document(root)
    results: dict[str, bool] = {}

    def refused(name: str, function: Callable[[], Any]) -> None:
        try:
            function()
            results[name] = False
        except Exception:
            results[name] = True

    refused("wrong_token", lambda: _require_token("wrong", real=True))
    mutations = {
        "wrong_candidate": ("candidate_commit", "0" * 40),
        "wrong_seal": ("construction_seal_sha256", "0" * 64),
        "wrong_manifest": ("private_manifest_sha256", "0" * 64),
        "wrong_private_blind_root": ("private_blind_root", "0" * 64),
        "wrong_construction_ledger": ("construction_ledger_sha256", "0" * 64),
        "wrong_scorer_sha": ("scorer_sha256", "0" * 64),
        "wrong_metric_registry": ("metric_registry_sha256", "0" * 64),
        "wrong_authority_graph": ("authority_graph_sha256", "0" * 64),
    }
    for name, (field, value) in mutations.items():
        changed = deepcopy(base)
        changed[field] = value
        refused(name, lambda changed=changed: verify_addendum_document(root, changed))
    with TemporaryDirectory(prefix="t26-eval-negative-") as tmp:
        fake = T26PrivateStore(Path(tmp) / "T26-STORE-01", root)
        fake.write_once(LEDGER_PATH, {"state": "STARTED"},
                        classification="PRIVATE_EVALUATION")
        refused("duplicate_evaluation_ledger",
                lambda: require_evaluation_absent(fake))
    refused("attempt_2", lambda: validate_evaluation_attempt(2))
    refused("gold_field_candidate_exposure", lambda: validate_candidate_payload({
        "scenario_id": "synthetic", "plan": {},
        "classification": "PRIVATE_BLIND", "expected_answer": "forbidden"}))
    refused("public_leakage", lambda: require_publication_pass({
        "status": "FAIL", "blind_blob_count": 1,
        "path_policy_violations": []}))
    refused("unsealed_construction",
            lambda: require_sealed_state({"state": "MANIFESTED"}))
    ordered = [{"control": name, "refused": results[name]}
               for name in sorted(results)]
    return {"schema_version": "t26-evaluation-negative-controls-v1",
            "artifact": "T26_EVALUATION_NEGATIVE_CONTROLS",
            "status": "PASS" if all(results.values()) else "FAIL",
            "control_count": len(results),
            "refused_count": sum(results.values()),
            "not_refused": sorted(name for name, ok in results.items() if not ok),
            "controls": ordered, "real_private_rows_read": 0,
            "real_candidate_executions": 0,
            "official_evaluator_invocations": 0}
