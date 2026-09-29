"""Frozen one-shot T29 official evaluation infrastructure (§19–§39, §44–§52).

Corrected official evaluation protocol (successor to the adjudicated T27
defects A–I): closed signature ``evaluate_official(root, private_store_root,
token)`` owning the official environment, ledger-first exclusive creation
with store binding before any blind read, machine-only sealed-store and
absence preflights, the T27 sealed-compatibility preflight, the public leak
preflight, real gold firewall projection, post-ledger per-scenario
workspaces, and the FAIL_NONVACUITY scorer.  Post-ledger failure records
FAILED, leaves the marker spent, and refuses retry.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from t21_protocol.util import sha256_json

from .construction import (T29ConstructionLedger, _event, _fixed_clock_factory,
                           _sha_bytes, author_provenance,
                           candidate_input_projection, construct_once,
                           manifest_roots, required_bindings,
                           run_publication_leak_gate, synthetic_oracle_result,
                           synthetic_private_bundle,
                           synthetic_historical_evidence, verify_event_chain)
from .contract import CONSTRUCTION_TOKEN, CRITICAL_COUNTERS, EVALUATION_TOKEN
from .freeze import (PINNED_CANDIDATE_COMMIT, PINNED_CANDIDATE_TREE,
                     PINNED_RUNTIME_ROOT, T29_PRECONSTRUCTION_FREEZE_PATH,
                     build_freeze, verify_freeze)
from .official_environment import (FACTORY_CLASS, FACTORY_ID, IDENTITY_PATH,
                                   WORKSPACE_MODE,
                                   build_official_evaluation_environment,
                                   stage_environment_identity)
from .scorer import score_suite
from .store import NAMESPACE, STORE_ID, T29PrivateStore

EVALUATION_STATES = ("STARTED", "EXECUTED", "SCORED", "COMPLETE", "FAILED")
EVALUATION_TRANSITIONS = {
    "STARTED": {"EXECUTED", "FAILED"},
    "EXECUTED": {"SCORED", "FAILED"},
    "SCORED": {"COMPLETE", "FAILED"},
    "COMPLETE": set(), "FAILED": set(),
}
FAILURE_PHASES = ("STARTED", "BLIND_READ", "EXECUTED", "SCORED")
EVALUATION_ABSENCE_PATHS = (
    "evaluation/ledger.json", "markers/evaluation.one-shot",
    "evaluation/raw_outputs.json", "evaluation/scored_rows.json",
    "evaluation/summary.json", "evaluation/events",
)
REAL_BLIND_SCENARIOS = 512
REAL_BLIND_GOLD = 512
OFFICIAL_RUNNER_POLICY = {
    "caller_supplied_runner_allowed": False,
    "caller_supplied_environment_allowed": False,
    "factory_owns_provider_construction": True,
    "candidate_gold_access": False,
    "synthetic_data_source_allowed_only_for_disposable_rehearsal": True,
    "real_mode_requires_sealed_store": True,
    "ledger_first_ordering": True,
    "post_ledger_workspace_creation_only": True,
}
EVALUATION_BINDING_FIELDS = frozenset({
    "experiment", "attempt", "authorization_token", "candidate_commit",
    "candidate_tree", "runtime_root", "construction_seal_sha256",
    "construction_ledger_root", "manifest_sha256", "private_blind_root",
    "freeze_sha256", "metric_registry_sha256", "scorer_sha256",
    "official_runner_factory_id", "official_runner_factory_sha256",
    "official_runner_policy_root", "official_runner_identity_root",
    "provider_identity_root", "firewall_identity_root",
    "general_context_identity_root", "corpus_root",
    "document_mount_policy_root", "environment_root",
    "public_leak_scan_root", "store_verification_root", "authority",
    "timestamp", "state",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluation_ordering_proof(store: T29PrivateStore) -> dict[str, Any]:
    """Extract the §23 ordering chain from the durable store journal."""
    records = store.journal_records(0)
    blind_ops = {"read_bytes", "read_json"}

    def first_seq(path: str) -> int | None:
        return next((record["seq"] for record in records
                     if record.get("path") == path
                     and record.get("op") in blind_ops), None)

    bind = next((record["seq"] for record in records
                 if record.get("op") == "bind_ledger"), None)
    first_inputs = first_seq("blind/inputs.json")
    first_gold = first_seq("blind/gold.json")
    first_workspace = next((record["seq"] for record in records
                            if record.get("op") == "workspace_created"), None)
    first_execution = next((record["seq"] for record in records
                            if record.get("op") == "candidate_execution"),
                           None)
    preledger = [record for record in records
                 if "pre_ledger" in str(record.get("op", ""))]
    chain = (bind, first_inputs, first_gold, first_workspace, first_execution)
    strictly_increasing = all(entry is not None for entry in chain) and all(
        chain[index] < chain[index + 1] for index in range(len(chain) - 1))
    return {
        "ledger_created_seq": bind,
        "bind_ledger_seq": bind,
        "first_blind_inputs_read_seq": first_inputs,
        "first_blind_gold_read_seq": first_gold,
        "first_workspace_created_seq": first_workspace,
        "first_candidate_execution_seq": first_execution,
        "ordering_binding_precedes_blind_reads":
            bind is not None and first_inputs is not None
            and bind < first_inputs,
        "ordering_blind_inputs_before_gold":
            first_inputs is not None and first_gold is not None
            and first_inputs < first_gold,
        "ordering_reads_before_workspace":
            first_gold is not None and first_workspace is not None
            and first_gold < first_workspace,
        "ordering_workspace_precedes_candidate_execution":
            first_workspace is not None and first_execution is not None
            and first_workspace < first_execution,
        "ordering_strictly_increasing": strictly_increasing,
        "pre_ledger_refusals": len(preledger),
        "machine_only_journal": True,
    }


class EvaluationLedgerError(RuntimeError):
    pass


class T29EvaluationLedger:
    PATH = "evaluation/ledger.json"
    MARKER = "markers/evaluation.one-shot"

    @staticmethod
    def _event_path(index: int) -> str:
        return f"evaluation/events/{index:06d}.json"

    def __init__(self, store: T29PrivateStore, document: dict[str, Any]) -> None:
        self.store = store
        self.document = document

    @classmethod
    def create_exclusive(cls, store: T29PrivateStore,
                         bindings: dict[str, Any], token: str,
                         *,
                         clock: Callable[[], str] = _now) -> "T29EvaluationLedger":
        if token != EVALUATION_TOKEN:
            raise EvaluationLedgerError("wrong official T29 evaluation token")
        if set(bindings) != EVALUATION_BINDING_FIELDS:
            raise EvaluationLedgerError("evaluation ledger binding set mismatch")
        if (bindings["experiment"] != "t29" or bindings["attempt"] != 1
                or bindings["authorization_token"] != EVALUATION_TOKEN
                or bindings["authority"] != "SCORE_PRIVATE_ONCE"
                or bindings["state"] != "STARTED"):
            raise EvaluationLedgerError(
                "evaluation ledger immutable binding mismatch")
        if store.has(cls.MARKER) or store.has(cls.PATH):
            raise EvaluationLedgerError(
                "T29 official evaluation one-shot already spent")
        event = _event(0, "STARTED", clock(), None, {
            "attempt": 1, "bindings_sha256": sha256_json(bindings)})
        document = {
            "schema_version": "t29-evaluation-ledger-v1",
            "artifact": "T29_EVALUATION_LEDGER",
            "classification": "PRIVATE_LEDGER",
            "bindings": copy.deepcopy(bindings), "events": [event],
            "state": "STARTED", "final_event_hash": event["event_hash"],
        }
        document["ledger_root"] = sha256_json({
            "bindings": document["bindings"], "events": document["events"]})
        marker = {
            "schema_version": "t29-evaluation-one-shot-v1",
            "artifact": "T29_EVALUATION_ONE_SHOT_SPENT",
            "classification": "PRIVATE_LEDGER", "attempt": 1, "spent": True,
            "bindings_sha256": sha256_json(bindings),
            "genesis_event_hash": event["event_hash"], "ledger_path": cls.PATH,
        }
        store.write_once_json(cls.MARKER, marker)
        try:
            store.write_once_json(cls._event_path(0), event)
            store.write_once_json(cls.PATH, document)
        except Exception:
            raise EvaluationLedgerError(
                "evaluation ledger creation incomplete; one-shot remains spent")
        store.bind_evaluation_ledger(document)
        return cls(store, document)

    @classmethod
    def load(cls, store: T29PrivateStore) -> "T29EvaluationLedger":
        if not store.has(cls.MARKER) or not store.has(cls.PATH):
            raise EvaluationLedgerError("evaluation ledger or marker deleted")
        document = store.read_json(cls.PATH)
        marker = store.read_json(cls.MARKER)
        event_directory = store.path("evaluation/events")
        journals = ([json.loads(path.read_text(encoding="utf-8"))
                     for path in sorted(event_directory.glob("*.json"))]
                    if event_directory.is_dir() else [])
        if (marker.get("bindings_sha256") != sha256_json(document.get("bindings"))
                or marker.get("genesis_event_hash")
                != document.get("events", [{}])[0].get("event_hash")
                or journals != document.get("events")
                or not verify_event_chain(document)):
            raise EvaluationLedgerError(
                "evaluation ledger/marker integrity failure")
        return cls(store, document)

    def advance(self, state: str, payload: dict[str, Any], *,
                clock: Callable[[], str] = _now) -> None:
        current = self.document["state"]
        if state not in EVALUATION_TRANSITIONS[current]:
            raise EvaluationLedgerError(
                f"invalid evaluation transition {current}->{state}")
        event = _event(len(self.document["events"]), state, clock(),
                       self.document["final_event_hash"],
                       copy.deepcopy(payload))
        self.document["events"].append(event)
        self.document["state"] = state
        self.document["final_event_hash"] = event["event_hash"]
        self.document["ledger_root"] = sha256_json({
            "bindings": self.document["bindings"],
            "events": self.document["events"]})
        self.store.write_once_json(self._event_path(event["event_index"]), event)
        self.store.replace_ledger(self.PATH, self.document)

    def fail(self, phase: str, error: BaseException, *,
             clock: Callable[[], str] = _now) -> None:
        if self.document["state"] in {"COMPLETE", "FAILED"}:
            raise EvaluationLedgerError(
                "terminal evaluation ledger cannot fail again")
        evidence = {
            "failure_phase": phase, "failure_class": type(error).__name__,
            "evidence_hash": sha256_json({
                "phase": phase, "class": type(error).__name__,
                "message_sha256": hashlib.sha256(
                    str(error).encode()).hexdigest()})}
        self.advance("FAILED", evidence, clock=clock)


# --- preflight surfaces (all pre-ledger, metadata-only) ----------------------


def run_evaluation_absence_preflight(store: T29PrivateStore) -> dict[str, Any]:
    present = [path for path in EVALUATION_ABSENCE_PATHS if store.has(path)]
    if present:
        raise ValueError(
            f"T29 official evaluation one-shot already spent: {present}")
    return {
        "schema_version": "t29-evaluation-absence-preflight-v1",
        "artifact": "T29_EVALUATION_ABSENCE_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "checked_paths": list(EVALUATION_ABSENCE_PATHS),
        "evaluation_ledger_absent": True, "evaluation_marker_absent": True,
        "raw_outputs_absent": True, "scored_rows_absent": True,
        "summary_absent": True, "attempts": 0,
        "candidate_real_executions": 0, "private_rows_read": 0,
    }


def run_sealed_store_preflight(store: T29PrivateStore) -> dict[str, Any]:
    """Machine-only reverification of the sealed construction store (§31).

    Blind artifact bodies are hashed as raw sealed bytes only inside
    ``store.verify()``: rows parsed = 0, rows exposed = 0, content returned
    = 0.
    """
    verification = store.verify()
    if verification["status"] != "PASS":
        raise ValueError("sealed T29 private store verification failed")
    if verification.get("blind_rows_deserialized", 0) != 0:
        raise ValueError("pre-ledger verification deserialized blind rows")
    seal = json.loads(store.read_bytes("construction/seal.json"))
    construction_ledger = json.loads(
        store.read_bytes("construction/ledger.json"))
    if (seal.get("state") != "SEALED" or
            construction_ledger.get("state") != "SEALED"):
        raise ValueError("official evaluation requires sealed T29 construction")
    manifest = json.loads(store.read_bytes("construction/manifest.json"))
    return {
        "schema_version": "t29-sealed-store-preflight-v1",
        "artifact": "T29_SEALED_STORE_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "construction_ledger_state": construction_ledger.get("state"),
        "construction_marker_present": store.has("markers/construction.seal"),
        "seal_state": seal.get("state"),
        "manifest_sha256": _sha_bytes(
            store.read_bytes("construction/manifest.json")),
        "manifest_entry_count": len(manifest.get("artifacts", [])),
        "store_verification_root": sha256_json(verification),
        "machine_only_blind_hashing_boundary": {
            "rows_parsed": 0, "rows_exposed": 0, "content_returned": 0,
            "raw_sealed_artifact_bytes_hashed_only": True},
    }


def run_predecessor_anchor_preflight(root: Path, *, mode: str = "REAL"
                                     ) -> dict[str, Any]:
    """Validated historical anchors consumed by the official wrapper (§17).

    The T28 official evaluation failed at its frozen T27-compatibility
    preflight because the consumer indexed unvalidated raw report keys while
    the frozen producer had nested them.  T29 corrects the defect
    structurally: the wrapper consumes ONLY validated historical anchor
    state documents (``historical_anchor`` schema, exact §13 field set,
    roundtrip serialization) staged per predecessor; raw report indexing is
    impossible because every anchor passes the shared validator before any
    consumer key is read.

    Directional guard (§18): REAL mode validates the official staging at
    ``evaluations/t29/`` against the frozen official predecessor
    commitments; REAL_REHEARSAL validates the disposable staging under
    ``evaluations/t29/rehearsal/`` and refuses a real terminal anchor there.
    No private predecessor row is read at any point.
    """
    from .historical_anchor import (
        HistoricalAnchorError, anchor_sha256, load_historical_anchor_state,
        t27_official_anchor, t28_official_anchor,
    )

    if mode not in {"REAL", "REAL_REHEARSAL"}:
        raise ValueError(f"unknown official T29 evaluation mode: {mode}")
    root = Path(root).resolve()
    if mode == "REAL":
        anchor_directory = root / "evaluations/t29"
    else:
        anchor_directory = root / "evaluations/t29/rehearsal"
    anchors: dict[str, dict[str, Any]] = {}
    for predecessor in ("t27", "t28"):
        path = anchor_directory / f"historical_anchor_{predecessor}.json"
        anchor = load_historical_anchor_state(path)
        if anchor["experiment"] != predecessor:
            raise HistoricalAnchorError(
                f"historical anchor wrong experiment for {predecessor}: "
                + repr(anchor["experiment"]))
        if mode == "REAL":
            if anchor["evaluation_state"] == "SYNTHETIC_SEALED_UNEVALUATED":
                raise HistoricalAnchorError(
                    "REAL mode accepts only official predecessor "
                    "commitments; a disposable synthetic staging was "
                    "supplied for " + predecessor)
            official = (t27_official_anchor(root) if predecessor == "t27"
                        else t28_official_anchor(root))
            if anchor != official:
                raise HistoricalAnchorError(
                    f"staged {predecessor} anchor does not match the "
                    "official predecessor commitments")
        else:
            if anchor["evaluation_state"] != "SYNTHETIC_SEALED_UNEVALUATED":
                raise HistoricalAnchorError(
                    "REAL_REHEARSAL accepts only disposable authenticated "
                    "stand-ins; an official terminal anchor was staged for "
                    + predecessor)
        anchors[predecessor] = anchor
    return {
        "schema_version": "t29-predecessor-anchor-preflight-v1",
        "artifact": "T29_PREDECESSOR_ANCHOR_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": "PASS", "mode": mode,
        "predecessors": ("t27", "t28"),
        "t27_anchor_sha256": anchor_sha256(anchors["t27"]),
        "t28_anchor_sha256": anchor_sha256(anchors["t28"]),
        "t27_commitment_root": anchors["t27"]["commitment_root"],
        "t28_commitment_root": anchors["t28"]["commitment_root"],
        "t27_private_rows_read": anchors["t27"]["private_rows_read"],
        "t28_private_rows_read": anchors["t28"]["private_rows_read"],
        "predecessor_rows_deserialized": 0,
        "raw_report_indexing": False,
    }


# --- official identity + bindings -------------------------------------------


def runner_identity(root: Path) -> dict[str, Any]:
    """Identity surface of the closed T29 official evaluator."""
    root = Path(root).resolve()
    candidate = json.loads(
        (root / "evaluations/t29/candidate_identity.json")
        .read_text(encoding="utf-8"))
    return {
        "schema_version": "t29-official-runner-identity-v1",
        "artifact": "T29_OFFICIAL_RUNNER_IDENTITY",
        "classification": "PUBLIC_SAFE",
        "factory_id": FACTORY_ID, "factory_class": FACTORY_CLASS,
        "official_runner_policy_root": sha256_json(OFFICIAL_RUNNER_POLICY),
        "environment_builder": (
            "t29_protocol.official_environment:"
            "build_official_evaluation_environment"),
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "workspace_mode": WORKSPACE_MODE,
        "policy": dict(OFFICIAL_RUNNER_POLICY),
        "authority": "SCORE_PRIVATE_ONCE",
        "t27_token_superseded": (
            "T27_ONE_SHOT_OFFICIAL_EVALUATION never used; T27 evaluation "
            "remains UNSPENT_BUT_PERMANENTLY_INELIGIBLE"),
    }


def scorer_sha256(root: Path) -> str:
    return _sha_bytes(
        (Path(root).resolve() / "t29_protocol/scorer.py").read_bytes())


def official_corpus_root(root: Path) -> str:
    import subprocess
    return subprocess.run(
        ["git", "rev-parse", "HEAD:rag/gk_corpus"], cwd=Path(root).resolve(),
        capture_output=True, text=True, check=True).stdout.strip()


def official_document_mount_policy_root(root: Path) -> str:
    """Static mount-policy root; never derived from a live identity call.

    The T28 evaluation refused at its frozen preflight because the consumer
    recomputed a live policy root instead of binding the frozen one.  T29
    binds a constant policy map so the value is identical wherever the map
    is recomputed.
    """
    del root  # closed map; independent of repository state
    return sha256_json({
        "policy": "PER_SCENARIO_PRIVATE_EVALUATION_WORKSPACE",
        "derivation": ["sealed T29 private manifest",
                       "isolated evaluation workspace"],
        "cross_scenario_visibility": False,
    })


def official_firewall_identity_root() -> str:
    return sha256_json({
        "firewall_search_provider":
            "t25_protocol.firewall:FirewallSearchProvider",
        "t26_live_web_firewall":
            "t26_protocol.firewall:T26LiveWebSourceFirewall",
        "workspace_mode": WORKSPACE_MODE})


def evaluation_bindings(root: Path, seal: dict[str, Any], ledger_root: str,
                        environment: Any, commitments: dict[str, Any],
                        leak: dict[str, Any],
                        *, timestamp: str | None = None) -> dict[str, Any]:
    identity = runner_identity(root)
    binding = environment.binding()
    return {
        "experiment": "t29", "attempt": 1,
        "authorization_token": EVALUATION_TOKEN,
        "candidate_commit": seal["candidate_commit"],
        "candidate_tree": seal["candidate_tree"],
        "runtime_root": seal["runtime_root"],
        # The raw seal document cannot carry a self-hash; the byte-verified
        # seal commitment is bound from the store-commitment preflight
        # (already proven equal to the store seal bytes above).
        "construction_seal_sha256": commitments["seal_sha256"],
        "construction_ledger_root": ledger_root,
        "manifest_sha256": seal["manifest_sha256"],
        "private_blind_root": seal["private_blind_root"],
        "freeze_sha256": seal["freeze_sha256"],
        "metric_registry_sha256": seal["metric_registry_sha256"],
        "scorer_sha256": scorer_sha256(root),
        "official_runner_factory_id": FACTORY_ID,
        "official_runner_factory_sha256":
            binding["official_runner_identity_root"],
        "official_runner_policy_root":
            binding["official_runner_policy_root"],
        "official_runner_identity_root":
            binding["official_runner_identity_root"],
        "provider_identity_root": binding["live_provider_identity_root"],
        "firewall_identity_root": official_firewall_identity_root(),
        "general_context_identity_root":
            binding["general_context_identity_root"],
        "corpus_root": official_corpus_root(root),
        "document_mount_policy_root": official_document_mount_policy_root(root),
        "environment_root": binding["environment_root"],
        "public_leak_scan_root": sha256_json(leak),
        "store_verification_root": commitments["store_verification_root"],
        "authority": "SCORE_PRIVATE_ONCE", "timestamp": timestamp or _now(),
        "state": "STARTED",
    }


# --- public receipt ----------------------------------------------------------


def _public_evaluation_receipt(store: T29PrivateStore,
                               ledger: T29EvaluationLedger,
                               score: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "t29-public-evaluation-receipt-v1",
        "artifact": "T29_PUBLIC_EVALUATION_RECEIPT",
        "classification": "PUBLIC_SAFE", "experiment": "t29", "attempt": 1,
        "state": "COMPLETE",
        "evaluation_ledger_sha256": _sha_bytes(
            store.read_bytes("evaluation/ledger.json")),
        "evaluation_ledger_root": ledger.document["ledger_root"],
        "scenario_count": score["scenario_count"], "status": score["status"],
        "metrics": {name: {key: metric[key] for key in (
            "numerator", "denominator", "observed", "floor", "pass",
            "zero_denominator_policy")}
            for name, metric in score["metrics"].items()},
        "critical_counters": score["critical_counters"],
        "designated_counts": score["designated_counts"],
        "raw_outputs_included": False, "scored_rows_included": False,
        "gold_included": False, "scenario_bodies_included": False,
    }


def _evaluate_once(*, store: T29PrivateStore, bindings: dict[str, Any],
                   token: str,
                   build_runner: Callable[[str], Callable[[dict], dict]],
                   expected_counts: tuple[int, int] = (REAL_BLIND_SCENARIOS,
                                                       REAL_BLIND_GOLD),
                   clock: Callable[[], str] = _now,
                   inject_failure_phase: str | None = None) -> dict[str, Any]:
    """Ledger-first single official pass; callers cannot retry or inject."""
    if inject_failure_phase is not None and inject_failure_phase not in FAILURE_PHASES:
        raise ValueError(f"unknown injection phase: {inject_failure_phase}")
    ledger = T29EvaluationLedger.create_exclusive(
        store, bindings, token, clock=clock)
    phase = "STARTED"
    try:
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-ledger T29 evaluation failure")
        # Ledger bound; the exclusive ledger unlocks blind material (§35).
        cases = json.loads(store.read_bytes("blind/inputs.json"))
        phase = "BLIND_READ"
        gold = json.loads(store.read_bytes("blind/gold.json"))
        if (len(cases) != expected_counts[0] or
                len(gold) != expected_counts[1]):
            raise ValueError(
                "sealed T29 official evaluation requires "
                f"{expected_counts[0]}/{expected_counts[1]}")
        if any(set(case) != {"scenario_id", "classification", "plan"}
               for case in cases):
            raise ValueError("sealed T29 scenario schema mismatch")
        # Gold firewall: project candidate inputs (§36).
        projected = [candidate_input_projection(case) for case in cases]
        if inject_failure_phase == phase:
            raise RuntimeError(
                "injected post-blind-read T29 evaluation failure")
        # Post-ledger workspaces only (§37 / T27 defect I).
        workspaces = [store.create_evaluation_workspace(
            ledger.document, item["scenario_id"]) for item in projected]
        if len({path.name for path in workspaces}) != len(cases):
            raise ValueError("T29 evaluation workspace reuse detected")
        runners = [build_runner(workspace) for workspace in workspaces]
        # Candidate executions are journaled after workspaces (§23).
        outputs = []
        for item, runner in zip(projected, runners):
            store.record_candidate_execution(item["scenario_id"])
            outputs.append(runner(item))
        if len(outputs) != len(cases):
            raise ValueError("official T29 runner output cardinality mismatch")
        store.write_once_json("evaluation/raw_outputs.json", outputs)
        ledger.advance("EXECUTED", {
            "output_count": len(outputs),
            "raw_outputs_sha256": _sha_bytes(store.read_bytes(
                "evaluation/raw_outputs.json"))}, clock=clock)
        phase = "EXECUTED"
        if inject_failure_phase == phase:
            raise RuntimeError(
                "injected post-execution T29 evaluation failure")
        plans = [case["plan"] for case in cases]
        score = score_suite(outputs, gold, plans)
        scored_rows = [{
            "scenario_id": case["scenario_id"],
            "expected_terminal": expected["expected_terminal"],
            "observed_terminal": output.get("terminal"),
            "terminal_correct":
                output.get("terminal") == expected["expected_terminal"],
        } for case, expected, output in zip(cases, gold, outputs)]
        store.write_once_json("evaluation/scored_rows.json", scored_rows)
        store.write_once_json("evaluation/summary.json", score)
        ledger.advance("SCORED", {
            "score_status": score["status"],
            "summary_sha256": _sha_bytes(
                store.read_bytes("evaluation/summary.json")),
            "scored_rows_sha256": _sha_bytes(store.read_bytes(
                "evaluation/scored_rows.json"))}, clock=clock)
        phase = "SCORED"
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-score T29 evaluation failure")
        ledger.advance("COMPLETE", {
            "score_status": score["status"], "scenario_count": len(cases)},
            clock=clock)
        receipt = _public_evaluation_receipt(store, ledger, score)
        ordering = evaluation_ordering_proof(store)
        ordering_proved = all((
            ordering["ordering_binding_precedes_blind_reads"],
            ordering["ordering_blind_inputs_before_gold"],
            ordering["ordering_reads_before_workspace"],
            ordering["ordering_workspace_precedes_candidate_execution"],
            ordering["ordering_strictly_increasing"],
            ordering["ledger_created_seq"] is not None
            and ordering["first_blind_inputs_read_seq"] is not None
            and ordering["ledger_created_seq"]
            < ordering["first_blind_inputs_read_seq"]))
        store_verify = store.verify()
        return {
            "status": "PASS", "ledger": ledger.document, "score": score,
            "receipt": receipt, "ordering": ordering,
            "ordering_proved": ordering_proved,
            "gold_firewall": {
                "status": "PASS", "projected_rows": len(projected),
                "gold_fields_in_candidate_input": 0,
                "candidate_gold_access_edges": 0,
                "candidate_fields": sorted(projected[0]),
            },
            "post_score_store_verification_root":
                store_verify["verification_root"],
        }
    except Exception as exc:
        if ledger.document["state"] not in {"COMPLETE", "FAILED"}:
            ledger.fail(phase, exc, clock=clock)
        raise


class OfficialEvaluationRefusal(RuntimeError):
    """Phase-tagged official T29 wrapper refusal (fail-closed, pre-ledger)."""

    def __init__(self, phase: str, message: str) -> None:
        super().__init__(f"[{phase}] {message}")
        self.phase = phase


#: Mode-keyed construction-receipt staging paths.  Both live in
#: ``evaluations/t29`` SUBDIRECTORIES so they stay outside the canonical
#: freeze component glob (``evaluations/t29/*.json`` is non-recursive): a
#: construction receipt is written after the freeze is built and must never
#: itself become a freeze component.
T29_OFFICIAL_RECEIPT_STAGE = (
    "evaluations/t29/construction/construction_receipt.json")
T29_REHEARSAL_RECEIPT_STAGE = (
    "evaluations/t29/rehearsal/construction_receipt.json")
T29_REHEARSAL_ANCHOR_DIRECTORY = "evaluations/t29/rehearsal"
T29_REHEARSAL_ADAPTER_REGISTRY = (
    "evaluations/t29/rehearsal/adapter_registry.json")

WRAPPER_PHASE_CHAIN = (
    "sealed_store_preflight", "evaluation_absence_preflight",
    "historical_anchor_preflight", "store_commitment_cross_check",
    "model_hydration_preflight", "public_leak_preflight",
    "environment_construction", "evaluation_ledger", "blind_input_read",
    "blind_gold_read", "workspace_creation", "candidate_execution",
    "scored", "complete",
)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2,
                       ensure_ascii=False) + "\n").encode("utf-8")


def verify_store_commitments(root: Path, store: T29PrivateStore, *,
                             mode: str) -> dict[str, Any]:
    """Cross-check the sealed T29 construction store, receipt, and freeze.

    Machine-only (§31): blind bodies are read as raw sealed bytes for hashes
    inside ``store.verify()`` and never deserialized here.  Directional
    guards (§18): REAL accepts only an untagged official receipt on a
    non-disposable store; REAL_REHEARSAL accepts only a
    ``disposable_rehearsal``-tagged receipt on a disposable store.
    """
    from .store import CONSTRUCTION_LEDGER_PATH

    root = Path(root).resolve()
    if mode == "REAL":
        if store.disposable:
            raise OfficialEvaluationRefusal(
                "store_commitment_cross_check",
                "REAL mode requires a real non-disposable T29 private store")
        receipt_path = T29_OFFICIAL_RECEIPT_STAGE
    elif mode == "REAL_REHEARSAL":
        if not store.disposable:
            raise OfficialEvaluationRefusal(
                "store_commitment_cross_check",
                "REAL_REHEARSAL accepts only a disposable stand-in store")
        receipt_path = T29_REHEARSAL_RECEIPT_STAGE
    else:
        raise OfficialEvaluationRefusal(
            "mode_guard", f"unknown official T29 evaluation mode: {mode}")
    staged_receipt = root / receipt_path
    if not staged_receipt.is_file():
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            f"T29 construction receipt absent at the {mode} staging path: "
            + receipt_path)
    receipt = json.loads(staged_receipt.read_text(encoding="utf-8"))
    tagged = receipt.get("disposable_rehearsal")
    if mode == "REAL":
        if tagged is not None or "disposable_rehearsal" in receipt:
            raise OfficialEvaluationRefusal(
                "store_commitment_cross_check",
                "REAL mode refuses disposable-rehearsal-tagged construction "
                "material")
    elif tagged is None:
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "REAL_REHEARSAL accepts only tagged disposable stand-in "
            "construction material; an official (untagged) receipt was "
            "staged")
    if receipt.get("state") != "SEALED" or receipt.get(
            "artifact") != "T29_PUBLIC_CONSTRUCTION_RECEIPT":
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "T29 construction receipt is not a sealed official receipt")
    verification = store.verify()
    if verification["status"] != "PASS":
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "sealed T29 private store verification failed")
    if verification.get("blind_rows_deserialized", 0) != 0:
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "pre-ledger verification deserialized blind rows")
    seal = json.loads(store.read_bytes("construction/seal.json"))
    construction_ledger = json.loads(store.read_bytes(
        CONSTRUCTION_LEDGER_PATH))
    if seal.get("state") != "SEALED" or construction_ledger.get(
            "state") != "SEALED":
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "official evaluation requires a SEALED T29 construction store")
    candidate = json.loads(
        (root / "evaluations/t29/candidate_identity.json")
        .read_text(encoding="utf-8"))
    for field, pinned in (("candidate_commit", PINNED_CANDIDATE_COMMIT),
                          ("candidate_tree", PINNED_CANDIDATE_TREE),
                          ("runtime_root", PINNED_RUNTIME_ROOT)):
        for source in (receipt, seal, candidate):
            if source.get(field) != pinned:
                raise OfficialEvaluationRefusal(
                    "store_commitment_cross_check",
                    f"T29 candidate pin mismatch: {field}")
    staged_freeze_path = root / T29_PRECONSTRUCTION_FREEZE_PATH
    if not staged_freeze_path.is_file():
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "canonical T29 preconstruction freeze is not staged at "
            + T29_PRECONSTRUCTION_FREEZE_PATH)
    frozen = json.loads(staged_freeze_path.read_text(encoding="utf-8"))
    reverified = verify_freeze(root, frozen)
    if reverified["status"] != "PASS":
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "staged T29 preconstruction freeze fails repository "
            "re-verification: " + ",".join(reverified["mismatches"]))
    if frozen.get("freeze_sha256") != receipt.get("freeze_sha256") or \
            frozen.get("freeze_sha256") != seal.get("freeze_sha256"):
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "staged T29 freeze does not match the sealed construction "
            "freeze commitment")
    if frozen.get("real_construction_authorized") is not False or frozen.get(
            "real_evaluation_authorized") is not False:
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "T29 preconstruction freeze binds unauthorized real lifecycle "
            "flags")
    metric_registry_path = root / "evaluations/t29/metric_registry.json"
    if not metric_registry_path.is_file():
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "staged T29 metric registry absent")
    metric_registry_sha = _sha_bytes(metric_registry_path.read_bytes())
    manifest = json.loads(store.read_bytes("construction/manifest.json"))
    bound_metric_sha = manifest["semantic_bindings"][
        "protocol_identities"]["metric_registry_sha256"]
    if metric_registry_sha != bound_metric_sha:
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "staged T29 metric registry does not match the manifested "
            "metric registry SHA")
    if _sha_bytes(store.read_bytes("construction/seal.json")) != receipt.get(
            "seal_sha256") or _sha_bytes(
            store.read_bytes("construction/manifest.json")) != receipt.get(
            "manifest_sha256"):
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "construction receipt does not bind the sealed store artifact "
            "bytes")
    if receipt.get("construction_ledger_root") != construction_ledger.get(
            "ledger_root"):
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "construction receipt does not bind the construction ledger "
            "root")
    manifest_roots_observed = {
        key: manifest[key] for key in ("private_artifact_root",
                                       "private_blind_root")}
    for key, value in manifest_roots_observed.items():
        if (receipt.get(key) != value
                or seal.get(key) != value):
            raise OfficialEvaluationRefusal(
                "store_commitment_cross_check",
                "sealed private roots disagree with the manifest: " + key)
    materialized = next((event["payload"] for event in
                         construction_ledger.get("events", [])
                         if event.get("event_type") == "MATERIALIZED"), {})
    blind_counts = (materialized.get("scenario_count"),
                    materialized.get("gold_count"))
    if not (isinstance(blind_counts[0], int) and blind_counts[0] > 0
            and isinstance(blind_counts[1], int) and blind_counts[1] > 0):
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "construction ledger does not bind blind artifact counts")
    if mode == "REAL" and blind_counts != (REAL_BLIND_SCENARIOS,
                                           REAL_BLIND_GOLD):
        raise OfficialEvaluationRefusal(
            "store_commitment_cross_check",
            "real blind holdout requires exactly "
            f"{REAL_BLIND_SCENARIOS}/{REAL_BLIND_GOLD}; construction bound "
            f"{blind_counts[0]}/{blind_counts[1]}")
    return {
        "schema_version": "t29-store-commitment-verification-v1",
        "artifact": "T29_STORE_COMMITMENT_VERIFICATION",
        "classification": "PUBLIC_SAFE", "status": "PASS", "mode": mode,
        "receipt_path": receipt_path,
        "candidate_commit": PINNED_CANDIDATE_COMMIT,
        "candidate_tree": PINNED_CANDIDATE_TREE,
        "runtime_root": PINNED_RUNTIME_ROOT,
        "freeze_sha256": frozen["freeze_sha256"],
        "component_root": frozen["component_root"],
        "freeze_root": frozen["freeze_root"],
        "component_count": frozen["component_count"],
        "metric_registry_sha256": metric_registry_sha,
        "construction_ledger_sha256": receipt["construction_ledger_sha256"],
        "construction_ledger_root": receipt["construction_ledger_root"],
        "manifest_sha256": receipt["manifest_sha256"],
        "seal_sha256": receipt["seal_sha256"],
        "private_artifact_root": manifest_roots_observed[
            "private_artifact_root"],
        "private_blind_root": manifest_roots_observed["private_blind_root"],
        "blind_scenario_count": blind_counts[0],
        "blind_gold_count": blind_counts[1],
        "store_verification_root": verification["verification_root"],
        "store_disposable": store.disposable,
        "receipt_disposable_rehearsal_tagged": mode == "REAL_REHEARSAL",
    }


def run_model_hydration_preflight(root: Path, *, mode: str = "REAL"
                                  ) -> dict[str, Any]:
    """§27 model pin hydration preflight; never loads a model (§26).

    REAL: the pinned adapter bytes must exist in this repository with the
    pinned size, digest, and provenance manifest.  REAL_REHEARSAL: an
    explicitly tagged disposable adapter-substitute registry is required.
    """
    from .official_environment import MODEL_PINS

    root = Path(root).resolve()
    if mode not in {"REAL", "REAL_REHEARSAL"}:
        raise OfficialEvaluationRefusal(
            "model_hydration_preflight",
            f"unknown official T29 hydration mode: {mode}")
    if mode == "REAL":
        adapter_path = root / MODEL_PINS["adapter_path"]
        if not adapter_path.is_file():
            raise OfficialEvaluationRefusal(
                "model_hydration_preflight",
                "pinned official T29 adapter absent: "
                + str(MODEL_PINS["adapter_path"]))
        data = adapter_path.read_bytes()
        if len(data) != MODEL_PINS["adapter_bytes"]:
            raise OfficialEvaluationRefusal(
                "model_hydration_preflight",
                "pinned adapter byte size mismatch: "
                f"{len(data)} != {MODEL_PINS['adapter_bytes']}")
        if _sha_bytes(data) != MODEL_PINS["adapter_sha256"]:
            raise OfficialEvaluationRefusal(
                "model_hydration_preflight",
                "pinned adapter digest mismatch")
        manifest_path = adapter_path.parent / "artifact_manifest.json"
        if not manifest_path.is_file():
            raise OfficialEvaluationRefusal(
                "model_hydration_preflight",
                "pinned adapter provenance manifest absent")
        provenance = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (provenance.get("base_model") != MODEL_PINS["base_model_id"]
                or provenance.get("base_revision")
                != MODEL_PINS["base_revision"]):
            raise OfficialEvaluationRefusal(
                "model_hydration_preflight",
                "pinned adapter provenance disagrees with the frozen model "
                "pins")
        return {
            "schema_version": "t29-model-hydration-preflight-v1",
            "artifact": "T29_MODEL_HYDRATION_PREFLIGHT",
            "classification": "PUBLIC_SAFE", "status": "PASS", "mode": mode,
            "adapter_sha256": MODEL_PINS["adapter_sha256"],
            "adapter_bytes": MODEL_PINS["adapter_bytes"],
            "model_loaded": False,
            "hydration_tested_pre_ledger": True,
            "explicitly_tagged_disposable_substitute": None,
        }
    registry_path = root / T29_REHEARSAL_ADAPTER_REGISTRY
    if not registry_path.is_file():
        raise OfficialEvaluationRefusal(
            "model_hydration_preflight",
            "REAL_REHEARSAL requires the tagged disposable adapter "
            "registry")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if (registry.get("explicitly_tagged_disposable_substitute") is not True
            or registry.get("official_production_adapter_used") is not False):
        raise OfficialEvaluationRefusal(
            "model_hydration_preflight",
            "REAL_REHEARSAL requires an explicitly tagged disposable "
            "adapter substitute registry")
    return {
        "schema_version": "t29-model-hydration-preflight-v1",
        "artifact": "T29_MODEL_HYDRATION_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": "PASS", "mode": mode,
        "adapter_sha256": None, "adapter_bytes": 0,
        "model_loaded": False, "hydration_tested_pre_ledger": True,
        "explicitly_tagged_disposable_substitute": True,
    }


#: Staged official documents (§10/§13/§41): idempotent, PUBLIC_SAFE, and
#: byte-deterministic.  Stand-in placeholders are explicitly tagged and are
#: replaced - never mutated in place - by the real artifacts at real
#: construction.
_STANDIN_PLACEHOLDER_TAGGED = ("T27_HISTORICAL_FAILURE_ANCHOR.json",
                               "structural_unsatisfiability_reproducer.json",
                               "structural_satisfiability_witness.json")


def stage_official_documents(root: Path, *,
                             real_environment_root: str | None = None
                             ) -> dict[str, Any]:
    """Idempotently stage every official top-level T29 document (§13/§14).

    Freeze documents are NOT staged here (the freeze is written only by the
    §47 freeze stage).  The environment-identity document is always
    recomputed for the disposable rehearsal root (model-free); the real
    environment root is carried from the caller, or from an existing staged
    document, and stays ``None`` until the authorized real staging loads the
    qualified model stack.
    """
    from . import contract, exclusion
    from .official_environment import IDENTITY_PATH

    root = Path(root).resolve()
    staging = root / "evaluations/t29"
    staging.mkdir(parents=True, exist_ok=True)
    staged: list[str] = []

    def stage(relative: str, writer: Callable[[], Any]) -> bool:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            return False
        target.write_bytes(_canonical_bytes(writer()))
        staged.append(relative)
        return True

    candidate_document = {
        "schema_version": "t29-official-candidate-identity-v1",
        "artifact": "T29_OFFICIAL_CANDIDATE_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t29",
        "candidate_commit": PINNED_CANDIDATE_COMMIT,
        "candidate_tree": PINNED_CANDIDATE_TREE,
        "runtime_root": PINNED_RUNTIME_ROOT,
        "candidate_runtime_changes": 0,
        "candidate_runtime_changes_policy":
            "T29_INHERITS_T27_CANDIDATE_RUNTIME_UNCHANGED",
        "candidate_changed": False,
    }
    stage("evaluations/t29/candidate_identity.json",
          lambda: candidate_document)
    stage("evaluations/t29/metric_registry.json", contract.metric_registry)
    stage("evaluations/t29/terminal_contract.json", contract.execution_contract)
    stage("evaluations/t29/nonvacuity_policy.json", contract.nonvacuity_policy)
    stage("evaluations/t29/authority_graph.json", contract.authority_graph)
    stage("evaluations/t29/production_graph.json", contract.production_graph)
    from .store import storage_policy_successor
    stage("evaluations/t29/construction_ready_storage_policy.json",
          storage_policy_successor)
    stage("evaluations/t29/historical_exclusion_policy_v4.json",
          exclusion.historical_exclusion_policy_v4)
    stage("evaluations/t29/generated_public_exclusion_dimension_policy.json",
          exclusion.generated_public_dimension_policy)
    for relative, builder in (
            ("evaluations/t29/historical_anchor_t27.json",
             "t27"), ("evaluations/t29/historical_anchor_t28.json", "t28")):
        stage(relative, lambda predecessor=builder: _official_anchor_document(
            root, predecessor))
    for name in _STANDIN_PLACEHOLDER_TAGGED:
        if not (root / f"evaluations/t29/{name}").is_file():
            stage(f"evaluations/t29/{name}",
                  lambda name=name: {
                      "schema_version": "t29-standin-public-placeholder-v1",
                      "artifact": name.rsplit(".", 1)[0].upper(),
                      "classification": "PUBLIC_SAFE", "experiment": "t29",
                      "explicitly_tagged_disposable_substitute": True,
                      "standin_public_placeholder": name,
                      "real_binding": (
                          "replaced by the real artifact on the authorized "
                          "T29 real construction pass; absent placeholders "
                          "fail the construction gate"),
                  })
    from .official_environment import stage_environment_identity
    identity = stage_environment_identity(root, rehearsal_only=True)
    identity_document = {
        "schema_version": "t29-official-environment-identity-v1",
        "artifact": "T29_OFFICIAL_ENVIRONMENT_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t29",
        "environment_root": real_environment_root,
        "rehearsal_environment_root": identity["rehearsal_environment_root"],
        "live_provider_identity_root":
            identity["live_provider_identity_root"],
    }
    if identity_document["environment_root"] is None:
        prior = root / IDENTITY_PATH
        if prior.is_file():
            try:
                identity_document["environment_root"] = json.loads(
                    prior.read_text(encoding="utf-8")).get("environment_root")
            except ValueError:
                pass
    (root / IDENTITY_PATH).write_bytes(_canonical_bytes(identity_document))
    staged.append(IDENTITY_PATH)
    return {
        "schema_version": "t29-official-staging-v1",
        "artifact": "T29_OFFICIAL_DOCUMENT_STAGING",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "staged_paths": staged,
        "environment_identity_path": IDENTITY_PATH,
        "real_environment_root_staged":
            identity_document["environment_root"],
        "rehearsal_environment_root":
            identity_document["rehearsal_environment_root"],
        "placeholder_tagged_documents": list(_STANDIN_PLACEHOLDER_TAGGED),
        "idempotent": True,
    }


def _official_anchor_document(root: Path, predecessor: str) -> dict[str, Any]:
    from .historical_anchor import serialize_anchor, t27_official_anchor, \
        t28_official_anchor

    anchor = (t27_official_anchor(root) if predecessor == "t27"
              else t28_official_anchor(root))
    return json.loads(serialize_anchor(anchor).decode("utf-8"))


@contextmanager
def _phase_guard(phase: str) -> Any:
    """Tag every chain-stage failure with its wrapper phase (§19/§21)."""
    try:
        yield
    except OfficialEvaluationRefusal:
        raise
    except Exception as exc:
        raise OfficialEvaluationRefusal(
            phase, f"{type(exc).__name__}: {exc}") from exc


def _prepare_official_evaluation(root: Path, store: T29PrivateStore, *,
                                 mode: str) -> dict[str, Any]:
    """Wrapper-owned pre-ledger chain (§19), one phase per step, no bypass."""
    phases: dict[str, Any] = {}

    def complete(phase: str, evidence: dict[str, Any]) -> None:
        phases[phase] = {"entered": True, "completed": True, **evidence}

    root = Path(root).resolve()
    with _phase_guard("sealed_store_preflight"):
        sealing = run_sealed_store_preflight(store)
    complete("sealed_store_preflight", sealing)
    with _phase_guard("evaluation_absence_preflight"):
        absence = run_evaluation_absence_preflight(store)
    complete("evaluation_absence_preflight", absence)
    with _phase_guard("historical_anchor_preflight"):
        anchors = run_predecessor_anchor_preflight(root, mode=mode)
    complete("historical_anchor_preflight", anchors)
    with _phase_guard("store_commitment_cross_check"):
        commitments = verify_store_commitments(root, store, mode=mode)
    complete("store_commitment_cross_check", commitments)
    with _phase_guard("model_hydration_preflight"):
        hydration = run_model_hydration_preflight(root, mode=mode)
    complete("model_hydration_preflight", hydration)
    with _phase_guard("public_leak_preflight"):
        leak = run_publication_leak_gate(root)
        if leak.get("status") != "PASS" or leak.get("blind_blob_count", 1) != 0:
            raise OfficialEvaluationRefusal(
                "public_leak_preflight",
                "T29 public leak preflight refused evaluation")
    complete("public_leak_preflight", leak)
    with _phase_guard("environment_construction"):
        environment = build_official_evaluation_environment(
            root, real=(mode == "REAL"))
        binding = environment.binding()
        if mode == "REAL" and binding.get("live_or_fixture") != "live":
            raise OfficialEvaluationRefusal(
                "environment_construction",
                "official T29 REAL evaluation requires the approved live "
                "provider")
        if mode == "REAL_REHEARSAL" and binding.get(
                "live_or_fixture") == "live":
            raise OfficialEvaluationRefusal(
                "environment_construction",
                "REAL_REHEARSAL accepts only the disposable fixture "
                "provider stack")
        if "BOUND_BY_OFFICIAL_FACTORY" in json.dumps(binding):
            raise OfficialEvaluationRefusal(
                "environment_construction",
                "placeholder dependency in the official T29 environment")
        attestation = environment.preflight()
        from .official_environment import build_environment_identity_document
        identity_document = build_environment_identity_document(
            root, real=(mode == "REAL"),
            general_context_identity_root=
            binding["general_context_identity_root"],
            live_provider_identity_root=binding["live_provider_identity_root"])
    complete("environment_construction", {
        "environment_builder_id": binding["environment_builder_id"],
        "environment_root": binding["environment_root"],
        "live_or_fixture": binding["live_or_fixture"],
        "workspace_mode": binding["workspace_mode"],
        "network_required": binding["network_required"],
        "stack_attestation_root": sha256_json(attestation),
        "identity_mode_key": identity_document["identity_mode_key"],
    })
    with _phase_guard("bindings"):
        construction_ledger = json.loads(store.read_bytes(
            T29ConstructionLedger.PATH))
        seal = json.loads(store.read_bytes("construction/seal.json"))
        bindings = evaluation_bindings(
            root, seal, construction_ledger["ledger_root"], environment,
            commitments, leak)
        if any(value == "BOUND_BY_OFFICIAL_FACTORY"
               for value in bindings.values()):
            raise OfficialEvaluationRefusal(
                "bindings", "placeholder root in official T29 evaluation "
                "bindings")
    expected_counts = ((REAL_BLIND_SCENARIOS, REAL_BLIND_GOLD)
                       if mode == "REAL"
                       else (commitments["blind_scenario_count"],
                             commitments["blind_gold_count"]))

    def build_runner(workspace_path: str) -> Callable[[dict], dict]:
        workspace = Path(workspace_path).resolve()
        scenario_runner = environment.factory(workspace)
        return lambda projected: scenario_runner.run(projected)

    return {
        "bindings": bindings,
        "expected_counts": expected_counts,
        "build_runner": build_runner,
        "environment": environment,
        "phase_chain": [name for name in WRAPPER_PHASE_CHAIN],
        "preflights": phases,
        "store_commitments": commitments,
        "hydration": hydration,
        "anchor_preflight": anchors,
    }


def evaluate_official(root: Path, private_store_root: Path, token: str,
                      *, mode: str = "REAL") -> dict[str, Any]:
    """Real official T29 entrypoint (§19–§39); closed signature, no injection.

    The wrapper owns every dependency: mode guards, sealed-store reverification,
    evaluation-absence preflight, validated historical-anchor preflight,
    store-commitment cross-check, model hydration preflight, public leak
    preflight, frozen official environment construction, ledger-first
    exclusive creation, and then the single blind pass.  No blind row is
    deserialized before the STARTED ledger is bound to the store.
    """
    root = Path(root).resolve()
    if mode not in {"REAL", "REAL_REHEARSAL"}:
        raise OfficialEvaluationRefusal(
            "mode_guard", f"unknown official T29 evaluation mode: {mode}")
    store = T29PrivateStore(Path(private_store_root).resolve(),
                            repository_root=root,
                            disposable=(mode == "REAL_REHEARSAL"))
    if token != EVALUATION_TOKEN:
        raise OfficialEvaluationRefusal(
            "one_shot_guard", "wrong official T29 evaluation token")
    preparation = _prepare_official_evaluation(root, store, mode=mode)
    return _evaluate_once(
        store=store, bindings=preparation["bindings"], token=token,
        build_runner=preparation["build_runner"],
        expected_counts=preparation["expected_counts"])


# --- wrapper-driven disposable rehearsal machinery (§17–§21, §38–§39) --------
#
# Every rehearsal and negative control in this region drives the ACTUAL
# ``evaluate_official`` wrapper (never only ``_evaluate_once``, never only a
# preflight helper) against an independent disk-mirrored skeleton repository
# and a disposable stand-in store constructed by the real construction chain
# on synthetic material.  No real T29 blind row, gold row, or official
# predecessor private row exists at any point.

_WRAPPER_MIRROR_DIRECTORIES = (
    "t21_protocol", "t22_protocol", "t23_protocol", "t24_protocol",
    "t25_protocol", "t26_protocol", "t27_protocol", "t28_protocol",
    "t29_protocol", "src", "rag",
    "evaluations/t19", "evaluations/t20", "evaluations/t22",
    "evaluations/t25", "evaluations/t26", "evaluations/t27",
    "evaluations/t28", "evaluations/t29",
)


def _mirror_skeleton(root: Path, skeleton: Path) -> None:
    """Disk-byte mirror of every official wrapper dependency.

    The mirror copies CURRENT DISK bytes (commit state can lag the working
    tree, and the environment identity hashes working-tree module bytes).
    It deliberately excludes ``training/`` — the REAL-mode missing-production-
    adapter control depends on its absence — and ``.git``: a fresh
    one-commit repository is created here so the publication leak gate scans
    only the skeleton's own objects and stays network-free.
    """
    root = Path(root).resolve()
    skeleton.mkdir(parents=True, exist_ok=False)
    for name in _WRAPPER_MIRROR_DIRECTORIES:
        source = root / name
        if not source.is_dir():
            continue
        shutil.copytree(source, skeleton / name,
                        ignore=shutil.ignore_patterns(
                            "__pycache__", "*.pyc"))
    for pattern in ("scripts/t29*.py", "tests/test_t29*.py"):
        for path in root.glob(pattern):
            target = skeleton / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    _skeleton_git(skeleton)


def _skeleton_git(skeleton: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=skeleton,
                              capture_output=True, text=True, check=True,
                              encoding="utf-8").stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "T29 Wrapper Rehearsal Skeleton")
    git("config", "user.email", "t29-rehearsal@invalid")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-m", "T29 wrapper rehearsal skeleton", "-q")


@contextmanager
def _wrapper_rehearsal_skeleton(root: Path, *, variant: int,
                                real_shaped: bool):
    """One disposable skeleton + one real-chain stand-in store per run.

    ``real_shaped=False``: REAL_REHEARSAL wrapper runs — the store is
    disposable and the receipt/anchors carry the ``disposable_rehearsal``
    tag.  ``real_shaped=True``: REAL-mode wrapper controls — the store is
    disposable=False-shaped and the receipt is untagged, but the store is
    still built exclusively from SYNTHETIC_DISPOSABLE material, so no real
    exposure is possible.
    """
    root = Path(root).resolve()
    with TemporaryDirectory(prefix=f"t29-eval-rehearsal-{variant}-") as tmp:
        base = Path(tmp)
        skeleton = base / "repo"
        _mirror_skeleton(root, skeleton)
        stage_official_documents(skeleton)
        store = T29PrivateStore(base / "private", repository_root=skeleton,
                                disposable=not real_shaped)
        construction = _materialize_standin_store(
            skeleton, store, variant=variant, real_shaped=real_shaped,
            clock=_fixed_clock_factory(40 + variant))
        yield skeleton, store, construction
        store = None  # the whole tree is disposable and vanishes here


def _materialize_standin_store(skeleton: Path, store: T29PrivateStore, *,
                               variant: int, real_shaped: bool,
                               clock: Callable[[], str]) -> dict[str, Any]:
    """Construct one sealed disposable stand-in store via the REAL chain.

    The full ``construct_once`` lifecycle (ledger → materialization → audit →
    gate → manifest → seal → receipt) runs on a synthetic 512/512 disposable
    bundle, so the evaluation wrapper rehearses a store that is structurally
    indistinguishable from a real sealed construction.  Real-shaped stand-ins
    are indistinguishable from official stores (untagged receipt, official
    anchors) except for being synthetic and disposable.
    """
    from t27_protocol.t28_private_oracle import (
        authenticate_official_t27_store_for_t28, disposable_t27_sealed_store)
    from .historical_anchor import (build_historical_anchor_state,
                                    serialize_anchor)

    skeleton = Path(skeleton).resolve()
    cases, gold, fixtures = synthetic_private_bundle(
        variant, with_fixture=variant % 2 == 0)
    oracle_result = synthetic_oracle_result(cases, gold, variant=variant)
    historical_index, historical = synthetic_historical_evidence(
        cases, gold, oracle_result, variant=variant)
    provenance = author_provenance(
        f"T29-EVALUATION-REHEARSAL-AUTHOR-{variant}", "e" * 64,
        f"2026-09-27T00:00:0{variant % 10}+00:00")
    with TemporaryDirectory(
            prefix=f"t29-eval-rehearsal-{variant}-t27-") as t27_tmp:
        t27_store, t27_expected = disposable_t27_sealed_store(
            Path(t27_tmp), variant=variant, public_repo=skeleton)
        t27_authentication = authenticate_official_t27_store_for_t28(
            skeleton, t27_store, expected=t27_expected)
    freeze_document = build_freeze(skeleton)
    staged_freeze = skeleton / T29_PRECONSTRUCTION_FREEZE_PATH
    staged_freeze.parent.mkdir(parents=True, exist_ok=True)
    staged_freeze.write_bytes(_canonical_bytes(freeze_document))
    freeze_document = json.loads(staged_freeze.read_text(encoding="utf-8"))
    bindings = required_bindings(
        skeleton, freeze_document, historical=historical,
        timestamp=f"2026-09-27T00:00:0{variant % 10}+00:00")
    result = construct_once(
        root=skeleton, store=store, bindings=bindings,
        expected_bindings=copy.deepcopy(bindings), cases=cases, gold=gold,
        fixtures=fixtures, oracle_result=oracle_result, provenance=provenance,
        token=CONSTRUCTION_TOKEN, historical_index=historical_index,
        oracle_mode="SYNTHETIC", clock=clock,
        t27_store_authentication=t27_authentication)
    if (result["status"] != "PASS"
            or result["ledger"]["state"] != "SEALED"
            or result["final_store_verify"]["status"] != "PASS"):
        raise ValueError("T29 stand-in construction refused")
    materialized = next(event["payload"]
                        for event in result["ledger"]["events"]
                        if event["event_type"] == "MATERIALIZED")
    receipt = {**result["receipt"]}
    if not real_shaped:
        receipt["disposable_rehearsal"] = variant
    receipt_relative = (T29_OFFICIAL_RECEIPT_STAGE if real_shaped
                        else T29_REHEARSAL_RECEIPT_STAGE)
    receipt_target = skeleton / receipt_relative
    receipt_target.parent.mkdir(parents=True, exist_ok=True)
    receipt_target.write_bytes(_canonical_bytes(receipt))
    anchor_commitment_root = sha256_json({
        key: receipt[key] for key in (
            "construction_ledger_sha256", "construction_ledger_root",
            "manifest_sha256", "private_artifact_root", "private_blind_root",
            "seal_sha256")})
    if not real_shaped:
        anchor_directory = skeleton / T29_REHEARSAL_ANCHOR_DIRECTORY
        anchor_directory.mkdir(parents=True, exist_ok=True)
        # Synthetic-disposable rehearsal anchors bind the explicitly
        # synthetic eligibility vocabulary (§16: the official terminal
        # eligibility pairings are bound only by REAL anchors).
        for predecessor in ("t27", "t28"):
            anchor = build_historical_anchor_state(
                experiment=predecessor,
                construction_state="SEALED",
                construction_attempt=1,
                evaluation_state="SYNTHETIC_SEALED_UNEVALUATED",
                evaluation_attempt=0,
                evaluation_eligibility="SYNTHETIC_DISPOSABLE",
                capability_status="NOT_MEASURED",
                private_rows_read=0,
                store_authenticated=True,
                commitment_root=anchor_commitment_root)
            (anchor_directory /
             f"historical_anchor_{predecessor}.json").write_bytes(
                serialize_anchor(anchor))
        (skeleton / T29_REHEARSAL_ADAPTER_REGISTRY).write_bytes(
            _canonical_bytes({
                "schema_version": "t29-rehearsal-adapter-registry-v1",
                "artifact": "T29_REHEARSAL_ADAPTER_REGISTRY",
                "classification": "SYNTHETIC_DISPOSABLE",
                "explicitly_tagged_disposable_substitute": True,
                "official_production_adapter_used": False,
                "variant": variant,
            }))
    return {
        "schema_version": "t29-standin-construction-v1",
        "artifact": "T29_STANDIN_CONSTRUCTION",
        "classification": "SYNTHETIC_DISPOSABLE",
        "real_shaped": real_shaped,
        "receipt_path": receipt_relative,
        "receipt": receipt,
        "seal_sha256": receipt["seal_sha256"],
        "manifest_sha256": receipt["manifest_sha256"],
        "construction_ledger_sha256": receipt["construction_ledger_sha256"],
        "construction_ledger_root": receipt["construction_ledger_root"],
        "freeze_sha256": freeze_document["freeze_sha256"],
        "blind_scenario_count": materialized["scenario_count"],
        "blind_gold_count": materialized["gold_count"],
        "fixture_count": materialized.get("fixture_count", 0),
        "store_disposable": store.disposable,
        "disposable_rehearsal_tagged": not real_shaped,
        "anchor_commitment_root": anchor_commitment_root,
    }


_WRAPPER_REFUSAL_CONTROLS = (
    "wrong_predecessor_report_schema", "missing_predecessor_anchor",
    "wrong_store_commitment", "wrong_candidate", "wrong_freeze",
    "public_leak", "missing_production_adapter", "wrong_environment_identity",
    "existing_evaluation_marker", "real_refuses_tagged_disposable",
    "rehearsal_refuses_untagged_official",
)
_WRAPPER_REFUSAL_PHASES = {
    "wrong_predecessor_report_schema": "historical_anchor_preflight",
    "missing_predecessor_anchor": "historical_anchor_preflight",
    "wrong_store_commitment": "store_commitment_cross_check",
    "wrong_candidate": "store_commitment_cross_check",
    "wrong_freeze": "store_commitment_cross_check",
    "public_leak": "public_leak_preflight",
    "missing_production_adapter": "model_hydration_preflight",
    "wrong_environment_identity": "environment_construction",
    "existing_evaluation_marker": "evaluation_absence_preflight",
    "real_refuses_tagged_disposable": "store_commitment_cross_check",
    "rehearsal_refuses_untagged_official": "store_commitment_cross_check",
}


def _standin_blind_reads(store: T29PrivateStore) -> int:
    return sum(1 for record in store.journal_records(0)
               if record.get("op") in {"read_bytes", "read_json"}
               and str(record.get("path", "")).startswith("blind/"))


def _assert_no_blind_exposure(store: T29PrivateStore) -> dict[str, Any]:
    one_shot_unspent = not store.has("markers/evaluation.one-shot") \
        and not store.has("evaluation/ledger.json")
    return {
        "evaluation_ledger_absent":
            not store.has("evaluation/ledger.json"),
        "evaluation_marker_absent":
            not store.has("markers/evaluation.one-shot"),
        "blind_rows_parsed": _standin_blind_reads(store),
        "evaluation_one_shot": "UNSPENT" if one_shot_unspent else "SPENT",
    }


def run_evaluation_rehearsals(root: Path) -> dict[str, Any]:
    """Two complete wrapper-driven disposable rehearsals (§17/§20).

    Each run drives the actual ``t29_protocol.evaluation:evaluate_official``
    wrapper in REAL_REHEARSAL mode against an independent mirror skeleton
    and a disposable stand-in store built by the real construction chain:
    sealed-store reverification, absence preflight, anchor preflight, store
    commitments, hydration preflight, leak preflight, frozen environment
    construction, STARTED ledger, blind input reads, gold reads, per-scenario
    workspaces, candidate executions, EXECUTED → SCORED → COMPLETE.
    """
    root = Path(root).resolve()
    leak = run_publication_leak_gate(root)
    if leak.get("blind_blob_count", 1) != 0:
        raise ValueError(
            "T29 wrapper rehearsal refused: repository publication leak")
    runs = []
    for variant in (1, 2):
        with _wrapper_rehearsal_skeleton(root, variant=variant,
                                         real_shaped=False) as context:
            skeleton, store, built = context
            result = evaluate_official(
                skeleton, store.base, EVALUATION_TOKEN, mode="REAL_REHEARSAL")
            ordering = result["ordering"]
            score = result["score"]
            semantic = {
                "state_sequence": [event["event_type"]
                                   for event in result["ledger"]["events"]],
                "scenario_count": score["scenario_count"],
                "designated_counts": score["designated_counts"],
                "denominators_nonzero": all(
                    metric["denominator"] > 0
                    for metric in score["metrics"].values()),
                "fail_nonvacuity_policy":
                    score["zero_denominator_policy"] == "FAIL_NONVACUITY",
                "ordering_binding_precedes_blind_reads":
                    ordering["ordering_binding_precedes_blind_reads"],
                "ordering_blind_inputs_before_gold":
                    ordering["ordering_blind_inputs_before_gold"],
                "ordering_reads_before_workspace":
                    ordering["ordering_reads_before_workspace"],
                "ordering_workspace_precedes_candidate_execution":
                    ordering[
                        "ordering_workspace_precedes_candidate_execution"],
                "ordering_strictly_increasing":
                    ordering["ordering_strictly_increasing"],
                "gold_firewall_projected_rows":
                    result["gold_firewall"]["projected_rows"],
                "post_ledger_store_verified":
                    store.verify()["status"] == "PASS",
                # fixture_count is a variant-identity field (variant 2 packs
                # one optional fixture; variant 1 runs fixture-free, §30
                # zero_fixtures_allowed) — it stays a run-level field and is
                # excluded from the compared semantic signature, which must
                # cover only semantics the two wrapper invocations share.
            }
            passed = result["status"] == "PASS" and all(
                value if isinstance(value, bool) else True
                for key, value in semantic.items()
                if key != "state_sequence")
            runs.append({
                "variant": variant,
                "wrapper_qualified_id":
                    "t29_protocol.evaluation:evaluate_official",
                "mode": "REAL_REHEARSAL",
                "status": "PASS" if passed else "FAIL",
                "fixture_count": built["fixture_count"],
                "semantic_signature": sha256_json(semantic),
                **semantic,
            })
    comparable = [{key: value for key, value in item.items()
                   if key not in {"variant", "fixture_count"}} for item in runs]
    equivalent = comparable[0] == comparable[1]
    passed = equivalent and all(item["status"] == "PASS" for item in runs)
    return {
        "schema_version": "t29-evaluation-rehearsals-v2",
        "artifact": "T29_DISPOSABLE_EVALUATION_REHEARSALS",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "public_leak_preflight": {"status": leak.get("status"),
                                  "blind_blob_count":
                                      leak.get("blind_blob_count"),
                                  "public_leak_scan_root": sha256_json(leak)},
        "runs": runs, "semantic_equivalence": equivalent,
        "official_real_evaluator_invocations": 0,
        "wrapper_invocations_on_disposable_standins": len(runs),
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_evaluation_attempts": 0,
    }


def _drift_rehearsal_identity(skeleton: Path) -> None:
    """Live-vs-staged environment-identity drift for one wrapper control.

    The staged identity document is a freeze component
    (``evaluations/t29/*.json``), so editing it is detected one phase
    earlier by the freeze repository re-verification.  The intended
    ``environment_construction`` drift must come from a live-identity
    input the freeze does not bind: the disposable search firewall module
    bytes are hashed inside ``environment_identity``'s ``firewall_stack``
    but are outside the freeze component set.
    """
    firewall = skeleton / "t25_protocol" / "firewall.py"
    firewall.write_bytes(firewall.read_bytes() + b"# drifted\n")


def run_wrapper_refusal_controls(root: Path) -> dict[str, Any]:
    """§21: nine §21 refusals + two §18 directional guards, wrapper-driven.

    Every control drives the actual ``evaluate_official`` wrapper and must
    refuse at its intended phase with no evaluation ledger, no marker, zero
    blind reads, and an UNSPENT store one-shot.
    """
    root = Path(root).resolve()
    controls: list[dict[str, Any]] = []

    def drive(name: str, *, variant: int, real_shaped: bool,
              mode: str | None = None,
              tamper: Callable[[Path, T29PrivateStore], None] | None = None
              ) -> None:
        with _wrapper_rehearsal_skeleton(root, variant=variant,
                                         real_shaped=real_shaped) as context:
            skeleton, store, _built = context
            if tamper is not None:
                tamper(skeleton, store)
            expected_phase = _WRAPPER_REFUSAL_PHASES[name]
            resolved_mode = mode or ("REAL" if real_shaped
                                     else "REAL_REHEARSAL")
            raised: OfficialEvaluationRefusal | None = None
            try:
                evaluate_official(skeleton, store.base, EVALUATION_TOKEN,
                                  mode=resolved_mode)
            except OfficialEvaluationRefusal as exc:
                raised = exc
            except Exception as exc:  # untagged refusal = control failure
                raised = exc  # type: ignore[assignment]
            if not isinstance(raised, OfficialEvaluationRefusal):
                controls.append({"control": name, "refused": False,
                                 "phase": None})
                return
            evidence = _assert_no_blind_exposure(store)
            record = {
                "control": name, "refused": True,
                "phase":raised.phase,
                "expected_phase": expected_phase,
                "phase_intended": raised.phase == expected_phase,
                "message": raised.__str__()[:300],
                **evidence,
            }
            # §21 invariants hold for every control; the marker control is
            # the exception that proves the rule: its planted stand-in
            # marker IS the trigger, so the record must bind SPENT with the
            # marker present (never the official T29 evaluation one-shot —
            # the planted bytes are a synthetic disposable stand-in).
            marker_control = name == "existing_evaluation_marker"
            record["passed"] = all((
                record["phase_intended"],
                record["evaluation_ledger_absent"],
                record["evaluation_marker_absent"] is not marker_control,
                record["blind_rows_parsed"] == 0,
                record["evaluation_one_shot"]
                == ("SPENT" if marker_control else "UNSPENT")))
            controls.append(record)

    def tamper_anchor_schema(skeleton: Path, _store: T29PrivateStore) -> None:
        from .historical_anchor import ANCHOR_FIELDS

        anchor = skeleton / ("evaluations/t29/rehearsal/"
                             "historical_anchor_t27.json")
        corrupt = json.loads(anchor.read_text(encoding="utf-8"))
        corrupt.pop(ANCHOR_FIELDS[0])
        anchor.write_bytes(_canonical_bytes(corrupt))

    def tamper_anchor_absent(skeleton: Path, _store: T29PrivateStore) -> None:
        (skeleton / ("evaluations/t29/rehearsal/"
                     "historical_anchor_t28.json")).unlink()

    def tamper_store_commitment(skeleton: Path, _store: T29PrivateStore
                                ) -> None:
        receipt_path = skeleton / T29_REHEARSAL_RECEIPT_STAGE
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["seal_sha256"] = "0" * 64
        receipt_path.write_bytes(_canonical_bytes(receipt))

    def tamper_candidate(skeleton: Path, _store: T29PrivateStore) -> None:
        identity = skeleton / "evaluations/t29/candidate_identity.json"
        document = json.loads(identity.read_text(encoding="utf-8"))
        document["candidate_commit"] = ("9" * 40)
        identity.write_bytes(_canonical_bytes(document))

    def tamper_freeze(skeleton: Path, _store: T29PrivateStore) -> None:
        staged = skeleton / T29_PRECONSTRUCTION_FREEZE_PATH
        frozen = json.loads(staged.read_text(encoding="utf-8"))
        frozen["freeze_sha256"] = "1" * 64
        staged.write_bytes(_canonical_bytes(frozen))

    def tamper_leak(skeleton: Path, _store: T29PrivateStore) -> None:
        leaked = skeleton / ("evaluations/t29/rehearsal/probe/"
                             "blind/inputs.json")
        leaked.parent.mkdir(parents=True, exist_ok=True)
        leaked.write_bytes(b"{}\n")
        # The publication-leak gate scans reachable repository objects
        # (git rev-list --objects --all), not untracked worktree files: the
        # leaked blob must be committed to a local ref to count as published.
        leaked_relative = "evaluations/t29/rehearsal/probe/blind/inputs.json"
        for git_args in (("add", leaked_relative),
                         ("commit", "-m", "T29 leak control blob", "-q")):
            subprocess.run(["git", *git_args], cwd=skeleton, check=True,
                           capture_output=True, text=True)

    def tamper_identity(skeleton: Path, _store: T29PrivateStore) -> None:
        """Live environment-identity drift via a non-freeze-component
        module input — the shared §21/§39 drift helper."""
        _drift_rehearsal_identity(skeleton)

    def tamper_marker(_skeleton: Path, store: T29PrivateStore) -> None:
        (store.base / NAMESPACE / "markers").mkdir(parents=True, exist_ok=True)
        (store.base / NAMESPACE / "markers" / "evaluation.one-shot"
         ).write_bytes(b"{}\n")

    def tamper_tagged(skeleton: Path, _store: T29PrivateStore) -> None:
        receipt_path = skeleton / T29_OFFICIAL_RECEIPT_STAGE
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["disposable_rehearsal"] = 99
        receipt_path.write_bytes(_canonical_bytes(receipt))

    def stage_official_untagged_rehearsal(skeleton: Path,
                                          _store: T29PrivateStore) -> None:
        """REAL_REHEARSAL drive on official material: anchors, untagged receipt."""
        from .historical_anchor import (build_historical_anchor_state,
                                        serialize_anchor)

        receipt = json.loads(
            (skeleton / T29_OFFICIAL_RECEIPT_STAGE).read_text(
                encoding="utf-8"))
        anchor_directory = skeleton / T29_REHEARSAL_ANCHOR_DIRECTORY
        anchor_directory.mkdir(parents=True, exist_ok=True)
        # Synthetic-disposable rehearsal anchors bind the explicitly
        # synthetic eligibility vocabulary (§16: the official terminal
        # eligibility pairings are bound only by REAL anchors).
        for predecessor in ("t27", "t28"):
            anchor = build_historical_anchor_state(
                experiment=predecessor,
                construction_state="SEALED",
                construction_attempt=1,
                evaluation_state="SYNTHETIC_SEALED_UNEVALUATED",
                evaluation_attempt=0,
                evaluation_eligibility="SYNTHETIC_DISPOSABLE",
                capability_status="NOT_MEASURED",
                private_rows_read=0, store_authenticated=True,
                commitment_root=receipt["seal_sha256"])
            (anchor_directory /
             f"historical_anchor_{predecessor}.json").write_bytes(
                serialize_anchor(anchor))
        rehearsal_receipt = {key: value for key, value in receipt.items()
                             if key != "disposable_rehearsal"}
        (skeleton / T29_REHEARSAL_RECEIPT_STAGE).parent.mkdir(
            parents=True, exist_ok=True)
        (skeleton / T29_REHEARSAL_RECEIPT_STAGE).write_bytes(
            _canonical_bytes(rehearsal_receipt))

    drive("wrong_predecessor_report_schema", variant=5, real_shaped=False,
          tamper=tamper_anchor_schema)
    drive("missing_predecessor_anchor", variant=6, real_shaped=False,
          tamper=tamper_anchor_absent)
    drive("wrong_store_commitment", variant=7, real_shaped=False,
          tamper=tamper_store_commitment)
    drive("wrong_candidate", variant=7, real_shaped=False,
          tamper=tamper_candidate)
    drive("wrong_freeze", variant=7, real_shaped=False,
          tamper=tamper_freeze)
    drive("public_leak", variant=7, real_shaped=False, tamper=tamper_leak)
    drive("missing_production_adapter", variant=7, real_shaped=True)
    drive("wrong_environment_identity", variant=7, real_shaped=False,
          tamper=tamper_identity)
    drive("existing_evaluation_marker", variant=7, real_shaped=False,
          tamper=tamper_marker)
    drive("real_refuses_tagged_disposable", variant=8, real_shaped=True,
          tamper=tamper_tagged)
    drive("rehearsal_refuses_untagged_official", variant=9, real_shaped=True,
          mode="REAL_REHEARSAL",
          tamper=stage_official_untagged_rehearsal)
    passed = all(item.get("passed") for item in controls)
    return {
        "schema_version": "t29-wrapper-refusal-controls-v1",
        "artifact": "T29_WRAPPER_REFUSAL_CONTROLS",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "controls": controls,
        "wrapper_entrypoint": "t29_protocol.evaluation:evaluate_official",
        "real_evaluation_attempts": 0,
    }


def run_evaluation_ledger_absence_rehearsal(root: Path) -> dict[str, Any]:
    """§39 pre-ledger failures: no ledger, no marker, no rows, one-shot intact."""
    root = Path(root).resolve()
    scenarios: list[dict[str, Any]] = []

    def scenario(name: str, *, variant: int, real_shaped: bool = False,
                 mode: str = "REAL_REHEARSAL",
                 tamper: Callable[[Path, T29PrivateStore], None] | None = None,
                 ) -> dict[str, Any]:
        with _wrapper_rehearsal_skeleton(root, variant=variant,
                                         real_shaped=real_shaped) as context:
            skeleton, store, _built = context
            if tamper is not None:
                tamper(skeleton, store)
            refused = None
            if mode == "HYDRATION_ONLY":
                try:
                    run_model_hydration_preflight(skeleton, mode="REAL")
                except OfficialEvaluationRefusal as exc:
                    refused = exc.phase
            else:
                try:
                    evaluate_official(skeleton, store.base, EVALUATION_TOKEN,
                                      mode=mode)
                except OfficialEvaluationRefusal as exc:
                    refused = exc.phase
                except Exception as exc:
                    refused = f"UNTAGGED:{type(exc).__name__}"
            evidence = _assert_no_blind_exposure(store)
            record = {
                "scenario": name, "refused": refused is not None,
                "refusal_phase": refused, **evidence,
            }
            record["passed"] = all((
                refused is not None,
                record["evaluation_ledger_absent"],
                record["evaluation_marker_absent"],
                record["blind_rows_parsed"] == 0,
                record["evaluation_one_shot"] == "UNSPENT",
            ))
            return record

    def corrupt_anchor(skeleton: Path, _store: T29PrivateStore) -> None:
        anchor = skeleton / T29_REHEARSAL_ANCHOR_DIRECTORY / \
            "historical_anchor_t27.json"
        document = json.loads(anchor.read_text(encoding="utf-8"))
        document["evaluation_attempt"] = 7
        anchor.write_bytes(_canonical_bytes(document))

    def corrupt_store(skeleton: Path, store: T29PrivateStore) -> None:
        blind_path = store.base / NAMESPACE / "blind" / "inputs.json"
        with blind_path.open("ab") as handle:
            handle.write(b" ")

    def commit_leak(skeleton: Path, _store: T29PrivateStore) -> None:
        leaked = skeleton / "evaluations/t29/rehearsal/probe/blind/gold.json"
        leaked.parent.mkdir(parents=True, exist_ok=True)
        leaked.write_bytes(b"[]\n")
        subprocess.run(["git", "add", "-A"], cwd=skeleton, check=True)
        subprocess.run(
            ["git", "-c", "user.name=T29 Probe",
             "-c", "user.email=t29-probe@invalid",
             "-c", "commit.gpgsign=false", "commit", "-m", "leak probe",
             "-q"],
            cwd=skeleton, check=True)

    scenarios.append(scenario("historical_anchor_schema_invalid", variant=11,
                              tamper=corrupt_anchor))
    scenarios.append(scenario("store_verification_failure", variant=12,
                              tamper=corrupt_store))
    scenarios.append(scenario("public_leak", variant=13, tamper=commit_leak))
    scenarios.append(scenario("model_hydration_failure", variant=14,
                              real_shaped=True, mode="HYDRATION_ONLY"))
    scenarios.append(scenario("environment_mismatch", variant=15,
                              tamper=lambda skeleton, _store:
                              _drift_rehearsal_identity(skeleton)))
    passed = all(item["passed"] for item in scenarios)
    return {
        "schema_version": "t29-evaluation-preledger-refusals-v1",
        "artifact": "T29_EVALUATION_PRELEDGER_REFUSAL_CONTROLS",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "scenarios": scenarios,
        "evaluation_ledger_absent_in_every_scenario": all(
            item["evaluation_ledger_absent"] for item in scenarios),
        "blind_rows_parsed": sum(item["blind_rows_parsed"]
                                 for item in scenarios),
        "one_shot": "UNSPENT",
    }


def run_evaluation_failure_rehearsal(root: Path) -> dict[str, Any]:
    """§38 post-ledger failure at four phases: FAILED, spent, retry refused."""
    root = Path(root).resolve()
    phases = []
    for index, failure_phase in enumerate(FAILURE_PHASES, start=1):
        with _wrapper_rehearsal_skeleton(root, variant=20 + index,
                                         real_shaped=False) as context:
            skeleton, store, built = context
            preparation = _prepare_official_evaluation(
                skeleton, store, mode="REAL_REHEARSAL")
            injected = False
            try:
                _evaluate_once(
                    store=store, bindings=preparation["bindings"],
                    token=EVALUATION_TOKEN,
                    build_runner=preparation["build_runner"],
                    expected_counts=preparation["expected_counts"],
                    clock=_fixed_clock_factory(70 + index),
                    inject_failure_phase=failure_phase)
            except RuntimeError:
                injected = True
            ledger = T29EvaluationLedger.load(store)
            retry_refused = False
            try:
                T29EvaluationLedger.create_exclusive(
                    store, preparation["bindings"], EVALUATION_TOKEN,
                    clock=_fixed_clock_factory(90 + index))
            except EvaluationLedgerError:
                retry_refused = True
            phases.append({
                "phase": failure_phase, "injected": injected,
                "ledger_state": ledger.document["state"],
                "retry_refused": retry_refused,
                "marker_spent": store.has("markers/evaluation.one-shot"),
                "standin_store_disposable": store.disposable,
            })
    passed = all(item["injected"] and item["ledger_state"] == "FAILED"
                 and item["retry_refused"] and item["marker_spent"]
                 for item in phases)
    return {
        "schema_version": "t29-evaluation-failure-rehearsal-v2",
        "artifact": "T29_EVALUATION_FAILURE_REHEARSAL",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "failure_phases": phases,
        "post_ledger_failure_recorded": True,
        "one_shot": "SPENT_ON_DISPOSABLE_STANDINS",
        "real_evaluation_attempts": 0,
    }


# --- §43 preconstruction contract + §44 evaluation-readiness gate -----------
#
# The preconstruction-layer contract and gate are separate artifacts from the
# construct-time construction contract (whose leaves bind ledger bindings
# inside ``construct_once``): §43 binds preconstruction-phase facts — staged
# public rehearsal/audit evidence plus live anchor and introspection checks —
# into stable, fail-closed leaves, and §44 consumes them in a gate that
# refuses real construction while any readiness item is not green.

READINESS_EVIDENCE_PATHS = (
    ("evaluation_wrapper_rehearsal",
     "evaluations/t29/evaluation_wrapper_rehearsal_evidence.json"),
    ("wrapper_refusal_controls",
     "evaluations/t29/wrapper_refusal_controls_evidence.json"),
    ("evaluation_preledger_refusals",
     "evaluations/t29/evaluation_preledger_refusals_evidence.json"),
    ("evaluation_failure_rehearsal",
     "evaluations/t29/evaluation_failure_rehearsal_evidence.json"),
    ("real_entrypoint_rehearsal",
     "evaluations/t29/real_entrypoint_rehearsal.json"),
    ("real_mode_oracle", "evaluations/t29/real_mode_oracle_evidence.json"),
    ("historical_anchor_controls",
     "evaluations/t29/historical_anchor_controls_evidence.json"),
)


def run_historical_anchor_control_rehearsal(root: Path) -> dict[str, Any]:
    """§13–§16 anchor evidence on the frozen official T27/T28 anchors.

    Schema exactness (both official anchors validate the exact
    ``t29-historical-anchor-state-v1`` field set), roundtrip exactness
    (serialize → deserialize → validate equality), the consumer chain (the
    staged public anchor bytes validate and equal the recomputed official
    anchors), and the nine producer/consumer shape mutation refusals.
    """
    from .historical_anchor import (deserialize_anchor, mutation_controls,
                                    serialize_anchor, t27_official_anchor,
                                    t28_official_anchor)

    root = Path(root).resolve()
    official = {"t27": t27_official_anchor(root), "t28": t28_official_anchor(root)}
    staged = {}
    for predecessor in official:
        path = root / f"evaluations/t29/historical_anchor_{predecessor}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        staged[predecessor] = deserialize_anchor(path.read_bytes())
    roundtrip_exact = all(
        deserialize_anchor(serialize_anchor(anchor)) == anchor
        for anchor in official.values())
    consumer_validated = all(staged[predecessor] == official[predecessor]
                             for predecessor in official)
    controls = mutation_controls()
    status = ("PASS" if roundtrip_exact and consumer_validated
              and controls["status"] == "PASS" else "FAIL")
    return {
        "schema_version": "t29-historical-anchor-control-rehearsal-v1",
        "artifact": "T29_HISTORICAL_ANCHOR_CONTROL_REHEARSAL",
        "classification": "PUBLIC_SAFE", "status": status,
        "schema_exact": {predecessor: True for predecessor in official},
        "roundtrip_exact": roundtrip_exact,
        "consumer_validated": consumer_validated,
        "official_anchor_commitment_roots": {
            predecessor: official[predecessor]["commitment_root"]
            for predecessor in official},
        "mutation_control_status": controls["status"],
        "mutation_refusals_failed": controls["mutation_refusals_failed"],
        "raw_indexing_consumers": 0,
        "t27_private_rows_read": 0, "t28_private_rows_read": 0,
    }


READINESS_EVIDENCE_SUITES = (
    "run_evaluation_rehearsals", "run_wrapper_refusal_controls",
    "run_evaluation_ledger_absence_rehearsal",
    "run_evaluation_failure_rehearsal",
    "run_real_mode_oracle_validation_rehearsal",
    "run_historical_anchor_control_rehearsal",
    "run_real_entrypoint_rehearsal",
)


def stage_readiness_evidence(root: Path) -> dict[str, Any]:
    """Run every preconstruction rehearsal/audit and stage its PUBLIC_SAFE
    evidence at the stable readiness path (§43/§44).  Fail-closed: any suite
    that does not report PASS is never staged and the staging refuses."""
    from .construction import run_real_mode_oracle_validation_rehearsal
    root = Path(root).resolve()
    staged_paths: list[str] = []
    suite_results = {
        "evaluation_wrapper_rehearsal": run_evaluation_rehearsals(root),
        "wrapper_refusal_controls": run_wrapper_refusal_controls(root),
        "evaluation_preledger_refusals":
            run_evaluation_ledger_absence_rehearsal(root),
        "evaluation_failure_rehearsal": run_evaluation_failure_rehearsal(root),
        "real_mode_oracle": run_real_mode_oracle_validation_rehearsal(root),
        "historical_anchor_controls": run_historical_anchor_control_rehearsal(
            root),
    }
    for key, relative in READINESS_EVIDENCE_PATHS:
        if key == "real_entrypoint_rehearsal":
            continue
        document = suite_results[key]
        if document.get("status") != "PASS" or document.get(
                "classification") != "PUBLIC_SAFE":
            raise ValueError("T29 readiness evidence suite not green: " + key)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_canonical_bytes(document))
        staged_paths.append(relative)
    # The construction real-wrapper rehearsal drives ``construct_real``
    # itself (the canonical freeze loader requires the staged freeze), so it
    # runs last after the evaluation-side evidence artifacts it excludes
    # from its own report are in place.  Those artifacts are freeze
    # components ("evaluations/t29/*.json"), so the provisional freeze at
    # the canonical path is regenerated over the freshly staged evidence
    # before the wrapper rehearsal verifies it through the loader.
    freeze_document = build_freeze(root)
    (root / T29_PRECONSTRUCTION_FREEZE_PATH).write_bytes(
        _canonical_bytes(freeze_document))
    from .construction import run_real_entrypoint_rehearsal
    document = run_real_entrypoint_rehearsal(root)
    if document.get("status") != "PASS" or document.get(
            "classification") != "PUBLIC_SAFE":
        raise ValueError("T29 readiness evidence suite not green: "
                         "real_entrypoint_rehearsal")
    entrypoint_relative = next(relative for key, relative
                               in READINESS_EVIDENCE_PATHS
                               if key == "real_entrypoint_rehearsal")
    (root / entrypoint_relative).parent.mkdir(parents=True, exist_ok=True)
    (root / entrypoint_relative).write_bytes(_canonical_bytes(document))
    staged_paths.append(entrypoint_relative)
    return {
        "schema_version": "t29-readiness-evidence-staging-v1",
        "artifact": "T29_READINESS_EVIDENCE",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "staged_paths": staged_paths,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
    }


PRECONSTRUCTION_CONTRACT_LEAF_IDS = (
    # §43 explicit leaves.
    "historical_anchor.schema_exact",
    "historical_anchor.roundtrip_exact",
    "historical_anchor.consumer_validated",
    "evaluation.real_wrapper_rehearsed",
    "evaluation.real_wrapper_preflight_chain_complete",
    "evaluation.ledger_first",
    "evaluation.no_preledger_blind_deserialization",
    "construction.real_wrapper_rehearsed",
    "t27_private_exclusion_ready",
    "t28_private_exclusion_ready",
    # Stable binding leaves for the staged evidence surface these facts
    # derive from (each staged PUBLIC_SAFE artifact is a freeze component;
    # the digest binding makes the leaf reproducible from repository bytes).
    "evidence.evaluation_wrapper_rehearsal_staged",
    "evidence.wrapper_refusal_controls_staged",
    "evidence.evaluation_preledger_refusals_staged",
    "evidence.evaluation_failure_rehearsal_staged",
    "evidence.real_entrypoint_rehearsal_staged",
    "evidence.real_mode_oracle_staged",
    "evidence.historical_anchor_controls_staged",
    # Underlying preconstruction public gates.
    "contract.construction_contract_clean",
    "qualification.public_qualified",
    "diagnostics.public_green",
    "defect.t28_key_shape_reproduced",
)


def _read_evidence(root: Path, relative: str) -> dict[str, Any] | None:
    """Fail-closed evidence read: an absent or unparsable artifact becomes a
    failing leaf, never a raising audit."""
    path = Path(root) / relative
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _sha256_file(root: Path, relative: str) -> str:
    try:
        return hashlib.sha256(
            (Path(root) / relative).read_bytes()).hexdigest()
    except OSError:
        return "0" * 64


def run_preconstruction_contract_audit(root: Path) -> dict[str, Any]:
    """§43 preconstruction contract: ten explicit leaves + stable evidence
    bindings.  FAIL = 0 and UNVERIFIABLE = 0 required."""
    from .construction import CONTRACT_LEAF_IDS
    from .historical_anchor import t27_official_anchor, t28_official_anchor

    root = Path(root).resolve()
    evidence: dict[str, dict[str, Any] | None] = {}
    for key, relative in READINESS_EVIDENCE_PATHS:
        evidence[key] = _read_evidence(root, relative)
    try:
        t27_anchor = t27_official_anchor(root)
        t28_anchor = t28_official_anchor(root)
    except Exception:  # refuse the anchor leaves closed, never raise
        t27_anchor = t28_anchor = None
    qualification = _read_evidence(
        root, "evaluations/t29/qualification_report.json")
    diagnostics = _read_evidence(root, "evaluations/t29/diagnostics_report.json")
    reproducer = _read_evidence(
        root, "evaluations/t29/T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json")
    entrypoint = evidence["real_entrypoint_rehearsal"]
    wrapper = evidence["evaluation_wrapper_rehearsal"]
    refusals = evidence["wrapper_refusal_controls"]
    preledger = evidence["evaluation_preledger_refusals"]
    anchors = evidence["historical_anchor_controls"]
    real_mode = evidence["real_mode_oracle"]
    checks: dict[str, Any] = {
        # §43 explicit leaves; each binds the staged fact, not a proxy.
        "historical_anchor.schema_exact": (
            t27_anchor is not None and t28_anchor is not None
            and anchors is not None and anchors["status"] == "PASS"),
        "historical_anchor.roundtrip_exact": (
            anchors is not None and anchors["roundtrip_exact"] is True
            and anchors["status"] == "PASS"),
        "historical_anchor.consumer_validated": (
            anchors is not None and anchors["consumer_validated"] is True
            and anchors["raw_indexing_consumers"] == 0
            and anchors["mutation_control_status"] == "PASS"),
        "evaluation.real_wrapper_rehearsed": (
            wrapper is not None and wrapper["status"] == "PASS"
            and wrapper.get("semantic_equivalence") is True
            and wrapper.get("wrapper_invocations_on_disposable_standins") == 2
            and wrapper.get("real_evaluation_attempts") == 0),
        "evaluation.real_wrapper_preflight_chain_complete": (
            refusals is not None and refusals["status"] == "PASS"
            and len(refusals.get("controls", [])) == 11
            and refusals.get("wrapper_entrypoint")
            == "t29_protocol.evaluation:evaluate_official"),
        "evaluation.ledger_first": (
            preledger is not None and preledger["status"] == "PASS"
            and preledger.get(
                "evaluation_ledger_absent_in_every_scenario") is True),
        "evaluation.no_preledger_blind_deserialization": (
            preledger is not None and preledger.get("blind_rows_parsed") == 0
            and preledger.get("one_shot") == "UNSPENT"
            and wrapper is not None and wrapper.get("real_blind_rows") == 0),
        "construction.real_wrapper_rehearsed": (
            entrypoint is not None and entrypoint["status"] == "PASS"
            and entrypoint.get("construct_once_reached") is True
            and entrypoint.get("oracle_mode") == "REAL_REHEARSAL"
            and entrypoint.get("one_shot") == "UNSPENT"
            and entrypoint.get("state_sequence")
            == ["LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS",
                "MANIFESTED", "SEALED"]
            and entrypoint.get("contract_leaf_count")
            == len(CONTRACT_LEAF_IDS)),
        "t27_private_exclusion_ready": (
            real_mode is not None and real_mode["status"] == "PASS"
            and real_mode.get("t27_store_authenticated") is True
            and real_mode.get("t27_commitments_exact") is True),
        "t28_private_exclusion_ready": (
            real_mode is not None and real_mode["status"] == "PASS"
            and real_mode.get("t28_store_authenticated") is True
            and real_mode.get("t28_commitments_exact") is True
            and real_mode.get("overall_prohibited_overlap") == 0
            and real_mode.get("real_mode_not_synthetic") is True
            and len(str(real_mode.get("dual_oracle_root"))) == 64),
        # Stable binding leaves for the staged evidence surface.
        **{
            f"evidence.{key}_staged": (
                evidence[key] is not None and evidence[key].get("status")
                in {"PASS", "SPENT_ON_DISPOSABLE_STANDINS"}
                and len(_sha256_file(
                    root, relative)) == 64)
            for key, relative in READINESS_EVIDENCE_PATHS
        },
        # Underlying preconstruction public gates.
        "contract.construction_contract_clean": (
            entrypoint is not None and entrypoint["status"] == "PASS"
            and entrypoint.get("contract_leaf_count")
            == len(CONTRACT_LEAF_IDS)
            and entrypoint.get("store_status") == "PASS"
            and entrypoint.get("leak_gate_status") == "PASS"
            and entrypoint.get("real_construction_attempts") == 0
            and entrypoint.get("real_evaluation_attempts") == 0
            and entrypoint.get("candidate_executions") == 0),
        "qualification.public_qualified": (
            qualification is not None and qualification.get("status")
            == "PASS"
            and int(qualification.get("scenario_count") or 0) >= 64),
        "diagnostics.public_green": (
            diagnostics is not None and all(
                (diagnostics.get(section) or {}).get("status") == "PASS"
                for section in ("terminal_matrix", "verification_matrix",
                                "completion_gate"))),
        "defect.t28_key_shape_reproduced": (
            reproducer is not None
            and reproducer.get("status")
            == "T28_FROZEN_PREFLIGHT_KEY_SHAPE_DEFECT_REPRODUCED"
            and reproducer.get("reproduced") is True),
    }
    if set(checks) != set(PRECONSTRUCTION_CONTRACT_LEAF_IDS):
        raise ValueError("preconstruction contract leaf enumerator drift")
    results = {name: "PASS" if value else "FAIL" for name, value in
               checks.items()}
    counts = {"PASS": 0, "FAIL": 0, "UNVERIFIABLE": 0}
    for value in results.values():
        counts[value] += 1
    core = {
        "schema_version": "t29-preconstruction-contract-v1",
        "artifact": "T29_PRECONSTRUCTION_CONTRACT",
        "classification": "PUBLIC_SAFE",
        "leaf_enumerator": "t29_protocol.evaluation:"
                           "PRECONSTRUCTION_CONTRACT_LEAF_IDS",
        "leaf_count": len(results), "leaf_ids": sorted(results),
        "results": dict(sorted(results.items())),
        # The contract binds the staged evidence bytes themselves: any
        # tampering with a staged artifact changes its digest here and
        # therefore the leaf root below.
        "evidence_sha256": {
            key: _sha256_file(root, relative)
            for key, relative in READINESS_EVIDENCE_PATHS},
        "PASS": counts["PASS"], "FAIL": counts["FAIL"],
        "UNVERIFIABLE": counts["UNVERIFIABLE"],
        "required_fail_count": 0, "required_unverifiable_count": 0,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
    }
    core["status"] = ("PASS" if core["FAIL"] == 0 and core["UNVERIFIABLE"] == 0
                      else "FAIL")
    return {**core, "leaf_root": sha256_json(core)}


EVALUATION_READINESS_ITEMS = (
    "wrapper_pass", "historical_anchor_roundtrip_pass",
    "shape_mutation_controls_pass", "ledger_first_pass",
    "caller_injection_impossible", "store_closure_pass",
    "public_leak_preflight_pass", "production_environment_pass",
    "model_hydration_pass", "gold_firewall_pass", "nonvacuity_pass",
    "failure_semantics_pass",
)


def run_evaluation_readiness_gate(root: Path) -> dict[str, Any]:
    """§44 evaluation-readiness gate, separate from the construction gate.

    Proves before any T29 real holdout exists that the exact
    ``evaluate_official`` wrapper rehearsal, the historical-anchor roundtrip,
    the shape mutation controls, ledger-first ordering, caller-injection
    impossibility, closure, leak, environment, hydration, firewall,
    nonvacuity, and failure-semantics readiness are green.  Any non-green
    item refuses with ``T29 REAL CONSTRUCTION UNAUTHORIZED``.
    """
    from .construction import CONTRACT_LEAF_IDS

    root = Path(root).resolve()
    contract = run_preconstruction_contract_audit(root)
    items: dict[str, Any] = {}
    wrapper = _read_evidence(root, READINESS_EVIDENCE_PATHS[0][1])
    failure = _read_evidence(root, READINESS_EVIDENCE_PATHS[3][1])
    refusals = _read_evidence(root, READINESS_EVIDENCE_PATHS[1][1])
    preledger = _read_evidence(root, READINESS_EVIDENCE_PATHS[2][1])
    anchors = _read_evidence(root, READINESS_EVIDENCE_PATHS[6][1])
    real_entrypoint = _read_evidence(root, READINESS_EVIDENCE_PATHS[4][1])
    items["wrapper_pass"] = (
        wrapper is not None and wrapper["status"] == "PASS"
        and wrapper.get("wrapper_invocations_on_disposable_standins") == 2
        and all(run.get("state_sequence")
                == ["STARTED", "EXECUTED", "SCORED", "COMPLETE"]
                for run in wrapper.get("runs", [])))
    items["historical_anchor_roundtrip_pass"] = (
        anchors is not None and anchors["roundtrip_exact"] is True)
    items["shape_mutation_controls_pass"] = (
        anchors is not None and anchors["mutation_control_status"] == "PASS"
        and anchors["mutation_refusals_failed"] == 0)
    items["ledger_first_pass"] = (
        preledger is not None and preledger["status"] == "PASS"
        and preledger.get("evaluation_ledger_absent_in_every_scenario")
        is True
        and wrapper is not None and wrapper["status"] == "PASS"
        and all(run.get("ordering_binding_precedes_blind_reads") is True
                and run.get("ordering_strictly_increasing") is True
                for run in wrapper.get("runs", [])))
    # §24 closed signature: the official entrypoint takes only
    # (root, private_store_root, token) positionally and admits no caller
    # injection of runner/provider/context/corpus/document roots/model/adapter
    # registry — the only keyword-only parameter is the §18 frozen mode
    # guard with its safe REAL default.  Every dependency is built inside
    # the wrapper, never passed in.
    parameters = inspect.signature(evaluate_official).parameters
    items["caller_injection_impossible"] = (
        list(parameters)[:3]
        == ["root", "private_store_root", "token"]
        and all(parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                for name, parameter in parameters.items()
                if name in {"root", "private_store_root", "token"})
        and all(name == "mode" and parameter.kind
                is inspect.Parameter.KEYWORD_ONLY
                and parameter.default == "REAL"
                for name, parameter in parameters.items()
                if name not in {"root", "private_store_root", "token"}))
    items["store_closure_pass"] = (
        real_entrypoint is not None
        and real_entrypoint.get("store_status") == "PASS"
        and wrapper is not None and wrapper["status"] == "PASS"
        and all(run.get("post_ledger_store_verified") is True
                for run in wrapper.get("runs", [])))
    items["public_leak_preflight_pass"] = (
        real_entrypoint is not None
        and real_entrypoint.get("leak_gate_status") == "PASS")
    # §26: actual environment roots only — no placeholders.  At the
    # preconstruction end state the REAL production environment is staged on
    # a production-capable host, so ``environment_root`` must be a real
    # 64-hex identity distinct from the disposable rehearsal root (the
    # rehearsal root is what REAL_REHEARSAL wrapper rehearsals bind).
    import re as _re
    _hex64 = _re.compile(r"[0-9a-f]{64}")
    environment_document = _read_evidence(
        root, "evaluations/t29/official_environment_identity.json")
    env_root = (environment_document or {}).get("environment_root")
    rehearsal_root = (environment_document or {}).get(
        "rehearsal_environment_root")
    items["production_environment_pass"] = (
        environment_document is not None
        and environment_document.get("experiment") == "t29"
        and environment_document.get("classification") == "PUBLIC_SAFE"
        and isinstance(env_root, str)
        and _hex64.fullmatch(env_root) is not None
        and isinstance(rehearsal_root, str)
        and _hex64.fullmatch(rehearsal_root) is not None
        and env_root != rehearsal_root
        and (environment_document.get("live_provider_identity_root")
             or "") != "0" * 64)
    # §25/§27: hydration is testable pre-ledger — prove the production stack
    # loadable with the exact adapter payload on this host (candidate
    # executions = 0, no real blind data), via the staged production-stack
    # preflight artifact.
    stack = _read_evidence(
        root, "evaluations/t29/production_stack_environment_preflight.json")
    hydration = (
        stack is not None
        and stack.get("status") == "PASS"
        and stack.get("real_environment") is True
        and stack.get("candidate_executions", 1) == 0
        and stack.get("checkpoints_written", 1) == 0
        and stack.get("runner_count", 1) == 0
        and stack.get("model_identity_verified") is True
        and stack.get("model_stack_loadable", 1) is True
        and (stack.get("model_identity_evidence", {}) or {}).get(
            "adapter_sha256") ==
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668"
        and (stack.get("model_identity_evidence", {}) or {}).get(
            "adapter_bytes") == 139512976
        and (stack.get("model_identity_evidence", {}) or {}).get(
            "base_revision") == "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e")
    items["model_hydration_pass"] = hydration
    items["gold_firewall_pass"] = (
        wrapper is not None and wrapper["status"] == "PASS"
        and wrapper.get("real_blind_rows") == 0
        and wrapper.get("real_gold_rows") == 0
        and all(run.get("gold_firewall_projected_rows") == 512
                for run in wrapper.get("runs", [])))
    metric_registry = _read_evidence(
        root, "evaluations/t29/metric_registry.json")
    items["nonvacuity_pass"] = bool(
        metric_registry is not None and metric_registry.get("metrics")
        and all(metric.get("zero_denominator_policy") == "FAIL_NONVACUITY"
                for metric in metric_registry["metrics"].values())
        and wrapper is not None and wrapper["status"] == "PASS"
        and all(run.get("denominators_nonzero") is True
                and run.get("fail_nonvacuity_policy") is True
                for run in wrapper.get("runs", [])))
    items["failure_semantics_pass"] = (
        failure is not None and failure["status"] == "PASS"
        and failure.get("post_ledger_failure_recorded") is True
        and len(failure.get("failure_phases", [])) == 4)
    missing = sorted(name for name in EVALUATION_READINESS_ITEMS
                     if not items.get(name))
    green = (contract["status"] == "PASS"
             and set(items) == set(EVALUATION_READINESS_ITEMS)
             and not missing)
    return {
        "schema_version": "t29-evaluation-readiness-gate-v1",
        "artifact": "T29_EVALUATION_READINESS_GATE",
        "classification": "PUBLIC_SAFE",
        "status": "GATE_GREEN" if green else "GATE_NOT_GREEN",
        "refusal": None if green else "T29 REAL CONSTRUCTION UNAUTHORIZED",
        "items": items, "items_failed": missing,
        "item_count": len(EVALUATION_READINESS_ITEMS),
        # §43: the gate binds the PRECONSTRUCTION contract (§43, audited at
        # readiness time) — not the 65-leaf construction contract that binds
        # later, at the separate real construction authorization.
        "construction_contract_leaf_count": contract["leaf_count"],
        "readiness_contract": {
            "leaf_count": contract["leaf_count"], "PASS": contract["PASS"],
            "FAIL": contract["FAIL"], "UNVERIFIABLE": contract["UNVERIFIABLE"],
            "leaf_root": contract["leaf_root"],
        },
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
    }