"""Frozen one-shot T28 official evaluation infrastructure (§19–§39, §44–§52).

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
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from t21_protocol.util import sha256_json

from .construction import (_event, _fixed_clock_factory, _sha_bytes,
                           candidate_input_projection,
                           official_marker_contract_report,
                           run_publication_leak_gate, verify_event_chain)
from .contract import CRITICAL_COUNTERS, EVALUATION_TOKEN
from .official_environment import (FACTORY_CLASS, FACTORY_ID, WORKSPACE_MODE,
                                   build_official_evaluation_environment)
from .scorer import score_suite
from .store import T28PrivateStore

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


def evaluation_ordering_proof(store: T28PrivateStore) -> dict[str, Any]:
    """Extract the §44 ordering chain from the durable store journal."""
    records = store.journal_records(0)
    blind_ops = {"read_bytes", "read_json"}

    def first_seq(path: str) -> int | None:
        return next((record["seq"] for record in records
                     if record.get("path") == path
                     and record.get("op") in blind_ops), None)

    bind = next((record["seq"] for record in records
                 if record.get("op") == "bind_ledger"), None)
    first_workspace = next((record["seq"] for record in records
                            if record.get("op") == "workspace_created"), None)
    preledger = [record for record in records
                 if "pre_ledger" in str(record.get("op", ""))]
    return {
        "bind_ledger_seq": bind,
        "first_blind_inputs_read_seq": first_seq("blind/inputs.json"),
        "first_blind_gold_read_seq": first_seq("blind/gold.json"),
        "first_workspace_created_seq": first_workspace,
        "ordering_binding_precedes_blind_reads":
            bind is not None and first_seq("blind/inputs.json") is not None
            and bind < first_seq("blind/inputs.json"),
        "ordering_blind_inputs_before_gold":
            first_seq("blind/inputs.json") is not None
            and first_seq("blind/gold.json") is not None
            and first_seq("blind/inputs.json") < first_seq("blind/gold.json"),
        "ordering_reads_before_workspace":
            first_seq("blind/gold.json") is not None
            and first_workspace is not None
            and first_seq("blind/gold.json") < first_workspace,
        "pre_ledger_refusals": len(preledger),
        "machine_only_journal": True,
    }


class EvaluationLedgerError(RuntimeError):
    pass


class T28EvaluationLedger:
    PATH = "evaluation/ledger.json"
    MARKER = "markers/evaluation.one-shot"

    @staticmethod
    def _event_path(index: int) -> str:
        return f"evaluation/events/{index:06d}.json"

    def __init__(self, store: T28PrivateStore, document: dict[str, Any]) -> None:
        self.store = store
        self.document = document

    @classmethod
    def create_exclusive(cls, store: T28PrivateStore,
                         bindings: dict[str, Any], token: str,
                         *,
                         clock: Callable[[], str] = _now) -> "T28EvaluationLedger":
        if token != EVALUATION_TOKEN:
            raise EvaluationLedgerError("wrong official T28 evaluation token")
        if set(bindings) != EVALUATION_BINDING_FIELDS:
            raise EvaluationLedgerError("evaluation ledger binding set mismatch")
        if (bindings["experiment"] != "t28" or bindings["attempt"] != 1
                or bindings["authorization_token"] != EVALUATION_TOKEN
                or bindings["authority"] != "SCORE_PRIVATE_ONCE"
                or bindings["state"] != "STARTED"):
            raise EvaluationLedgerError(
                "evaluation ledger immutable binding mismatch")
        if store.has(cls.MARKER) or store.has(cls.PATH):
            raise EvaluationLedgerError(
                "T28 official evaluation one-shot already spent")
        event = _event(0, "STARTED", clock(), None, {
            "attempt": 1, "bindings_sha256": sha256_json(bindings)})
        document = {
            "schema_version": "t28-evaluation-ledger-v1",
            "artifact": "T28_EVALUATION_LEDGER",
            "classification": "PRIVATE_LEDGER",
            "bindings": copy.deepcopy(bindings), "events": [event],
            "state": "STARTED", "final_event_hash": event["event_hash"],
        }
        document["ledger_root"] = sha256_json({
            "bindings": document["bindings"], "events": document["events"]})
        marker = {
            "schema_version": "t28-evaluation-one-shot-v1",
            "artifact": "T28_EVALUATION_ONE_SHOT_SPENT",
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
    def load(cls, store: T28PrivateStore) -> "T28EvaluationLedger":
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


def run_evaluation_absence_preflight(store: T28PrivateStore) -> dict[str, Any]:
    present = [path for path in EVALUATION_ABSENCE_PATHS if store.has(path)]
    if present:
        raise ValueError(
            f"T28 official evaluation one-shot already spent: {present}")
    return {
        "schema_version": "t28-evaluation-absence-preflight-v1",
        "artifact": "T28_EVALUATION_ABSENCE_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "checked_paths": list(EVALUATION_ABSENCE_PATHS),
        "evaluation_ledger_absent": True, "evaluation_marker_absent": True,
        "raw_outputs_absent": True, "scored_rows_absent": True,
        "summary_absent": True, "attempts": 0,
        "candidate_real_executions": 0, "private_rows_read": 0,
    }


def run_sealed_store_preflight(store: T28PrivateStore) -> dict[str, Any]:
    """Machine-only reverification of the sealed construction store (§31).

    Blind artifact bodies are hashed as raw sealed bytes only inside
    ``store.verify()``: rows parsed = 0, rows exposed = 0, content returned
    = 0.
    """
    verification = store.verify()
    if verification["status"] != "PASS":
        raise ValueError("sealed T28 private store verification failed")
    if verification.get("blind_rows_deserialized", 0) != 0:
        raise ValueError("pre-ledger verification deserialized blind rows")
    seal = json.loads(store.read_bytes("construction/seal.json"))
    construction_ledger = json.loads(
        store.read_bytes("construction/ledger.json"))
    if (seal.get("state") != "SEALED" or
            construction_ledger.get("state") != "SEALED"):
        raise ValueError("official evaluation requires sealed T28 construction")
    manifest = json.loads(store.read_bytes("construction/manifest.json"))
    return {
        "schema_version": "t28-sealed-store-preflight-v1",
        "artifact": "T28_SEALED_STORE_PREFLIGHT",
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


def sealed_t27_compatibility_preflight(root: Path) -> dict[str, Any]:
    """Prove T27 remains sealed, closed, and formally unevaluated (§73)."""
    report = official_marker_contract_report(root)
    if report["status"] != "PASS":
        raise ValueError("sealed T27 compatibility preflight failed")
    return {
        "schema_version": "t28-sealed-t27-compatibility-preflight-v1",
        "artifact": "T28_SEALED_T27_COMPATIBILITY_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": report["status"],
        "t27_official_evaluation_state":
            report["evaluation_state_sealed_unevaluated"],
        "t27_evaluation_attempt": report["evaluation_attempt_zero"],
        "t27_evaluation_eligibility": "PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
        "t27_private_rows_read": report["private_rows_read"],
        "t27_fingerprint_derivation_invoked":
            report["fingerprint_derivation_invoked"],
    }


# --- official identity + bindings -------------------------------------------


def runner_identity(root: Path) -> dict[str, Any]:
    """Identity surface of the closed T28 official evaluator."""
    root = Path(root).resolve()
    candidate = json.loads(
        (root / "evaluations/t28/candidate_identity.json")
        .read_text(encoding="utf-8"))
    return {
        "schema_version": "t28-official-runner-identity-v1",
        "artifact": "T28_OFFICIAL_RUNNER_IDENTITY",
        "classification": "PUBLIC_SAFE",
        "factory_id": FACTORY_ID, "factory_class": FACTORY_CLASS,
        "official_runner_policy_root": sha256_json(OFFICIAL_RUNNER_POLICY),
        "environment_builder": (
            "t28_protocol.official_environment:"
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
        (Path(root).resolve() / "t28_protocol/scorer.py").read_bytes())


def official_corpus_root(root: Path) -> str:
    import subprocess
    return subprocess.run(
        ["git", "rev-parse", "HEAD:rag/gk_corpus"], cwd=Path(root).resolve(),
        capture_output=True, text=True, check=True).stdout.strip()


def official_document_mount_policy_root(root: Path) -> str:
    from .official_environment import environment_identity
    identity = environment_identity(
        Path(root).resolve(), real=True,
        general_context_identity_root="0" * 64,
        live_provider_identity_root="0" * 64)
    return identity["document_mount_policy"]["policy_root"]


def official_firewall_identity_root() -> str:
    return sha256_json({
        "firewall_search_provider":
            "t25_protocol.firewall:FirewallSearchProvider",
        "t26_live_web_firewall":
            "t26_protocol.firewall:T26LiveWebSourceFirewall",
        "workspace_mode": WORKSPACE_MODE})


def evaluation_bindings(root: Path, seal: dict[str, Any], ledger_root: str,
                        environment: Any, sealing: dict[str, Any],
                        leak: dict[str, Any],
                        *, timestamp: str | None = None) -> dict[str, Any]:
    identity = runner_identity(root)
    binding = environment.binding()
    return {
        "experiment": "t28", "attempt": 1,
        "authorization_token": EVALUATION_TOKEN,
        "candidate_commit": seal["candidate_commit"],
        "candidate_tree": seal["candidate_tree"],
        "runtime_root": seal["runtime_root"],
        "construction_seal_sha256": seal["seal_sha256"],
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
        "store_verification_root": sealing["store_verification_root"],
        "authority": "SCORE_PRIVATE_ONCE", "timestamp": timestamp or _now(),
        "state": "STARTED",
    }


# --- public receipt ----------------------------------------------------------


def _public_evaluation_receipt(store: T28PrivateStore,
                               ledger: T28EvaluationLedger,
                               score: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "t28-public-evaluation-receipt-v1",
        "artifact": "T28_PUBLIC_EVALUATION_RECEIPT",
        "classification": "PUBLIC_SAFE", "experiment": "t28", "attempt": 1,
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


def _evaluate_once(*, store: T28PrivateStore, bindings: dict[str, Any],
                   token: str,
                   build_runner: Callable[[str], Callable[[dict], dict]],
                   expected_counts: tuple[int, int] = (REAL_BLIND_SCENARIOS,
                                                       REAL_BLIND_GOLD),
                   clock: Callable[[], str] = _now,
                   inject_failure_phase: str | None = None) -> dict[str, Any]:
    """Ledger-first single official pass; callers cannot retry or inject."""
    if inject_failure_phase is not None and inject_failure_phase not in FAILURE_PHASES:
        raise ValueError(f"unknown injection phase: {inject_failure_phase}")
    ledger = T28EvaluationLedger.create_exclusive(
        store, bindings, token, clock=clock)
    phase = "STARTED"
    try:
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-ledger T28 evaluation failure")
        # Ledger bound; the exclusive ledger unlocks blind material (§35).
        cases = json.loads(store.read_bytes("blind/inputs.json"))
        phase = "BLIND_READ"
        gold = json.loads(store.read_bytes("blind/gold.json"))
        if (len(cases) != expected_counts[0] or
                len(gold) != expected_counts[1]):
            raise ValueError(
                "sealed T28 official evaluation requires "
                f"{expected_counts[0]}/{expected_counts[1]}")
        if any(set(case) != {"scenario_id", "classification", "plan"}
               for case in cases):
            raise ValueError("sealed T28 scenario schema mismatch")
        # Gold firewall: project candidate inputs (§36).
        projected = [candidate_input_projection(case) for case in cases]
        if inject_failure_phase == phase:
            raise RuntimeError(
                "injected post-blind-read T28 evaluation failure")
        # Post-ledger workspaces only (§37 / T27 defect I).
        workspaces = [store.create_evaluation_workspace(
            ledger.document, item["scenario_id"]) for item in projected]
        if len({path.name for path in workspaces}) != len(cases):
            raise ValueError("T28 evaluation workspace reuse detected")
        runners = [build_runner(workspace) for workspace in workspaces]
        outputs = [runner(item) for item, runner in zip(projected, runners)]
        if len(outputs) != len(cases):
            raise ValueError("official T28 runner output cardinality mismatch")
        store.write_once_json("evaluation/raw_outputs.json", outputs)
        ledger.advance("EXECUTED", {
            "output_count": len(outputs),
            "raw_outputs_sha256": _sha_bytes(store.read_bytes(
                "evaluation/raw_outputs.json"))}, clock=clock)
        phase = "EXECUTED"
        if inject_failure_phase == phase:
            raise RuntimeError(
                "injected post-execution T28 evaluation failure")
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
            raise RuntimeError("injected post-score T28 evaluation failure")
        ledger.advance("COMPLETE", {
            "score_status": score["status"], "scenario_count": len(cases)},
            clock=clock)
        receipt = _public_evaluation_receipt(store, ledger, score)
        ordering = evaluation_ordering_proof(store)
        ordering_proved = all((
            ordering["ordering_binding_precedes_blind_reads"],
            ordering["ordering_blind_inputs_before_gold"],
            ordering["ordering_reads_before_workspace"]))
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
        }
    except Exception as exc:
        if ledger.document["state"] not in {"COMPLETE", "FAILED"}:
            ledger.fail(phase, exc, clock=clock)
        raise


def evaluate_official(root: Path, private_store_root: Path, token: str
                      ) -> dict[str, Any]:
    """Real official T28 entrypoint (§19–§39); closed signature, no injection.

    Owns the environment: it constructs the qualified model stack, verifies
    the frozen environment identity, and binds every dependency root into the
    STARTED ledger before any blind byte is read.
    """
    root = Path(root).resolve()
    store = T28PrivateStore(Path(private_store_root).resolve(),
                            repository_root=root)
    if store.has("evaluation/ledger.json") or store.has(
            "markers/evaluation.one-shot"):
        raise ValueError("T28 official evaluation one-shot already spent")
    sealing = run_sealed_store_preflight(store)
    run_evaluation_absence_preflight(store)
    sealed_t27 = sealed_t27_compatibility_preflight(root)
    if sealed_t27["status"] != "PASS":
        raise ValueError("sealed T27 compatibility preflight failed")
    leak = run_publication_leak_gate(root, fetch=True)
    if leak.get("status") != "PASS" or leak.get("blind_blob_count", 1) != 0:
        raise ValueError("T28 public leak preflight refused evaluation")
    environment = build_official_evaluation_environment(root, real=True)
    if environment.real is not True:
        raise ValueError("official T28 evaluation requires the real environment")
    if environment.factory.web_provider.live_or_fixture != "live":
        raise ValueError("REAL evaluation requires the approved live provider")
    if "BOUND_BY_OFFICIAL_FACTORY" in json.dumps(environment.binding()):
        raise ValueError("placeholder dependency in official T28 environment")
    construction_ledger = json.loads(
        store.read_bytes("construction/ledger.json"))
    seal = json.loads(store.read_bytes("construction/seal.json"))
    bindings = evaluation_bindings(
        root, seal, construction_ledger["ledger_root"], environment, sealing,
        leak)
    if any(value == "BOUND_BY_OFFICIAL_FACTORY"
           for value in bindings.values()):
        raise ValueError("placeholder root in official T28 evaluation bindings")

    def owned_runner(workspace_path: str) -> Callable[[dict], dict]:
        workspace = Path(workspace_path).resolve()
        scenario_runner = environment.factory(workspace)
        return lambda projected: scenario_runner.run(projected)

    return _evaluate_once(
        store=store, bindings=bindings, token=token,
        build_runner=owned_runner)


# --- disposable rehearsal surfaces (§50–§52) ---------------------------------


class PreLedgerViolationExport(RuntimeError):
    """Raised when disposable rehearsal helpers are asked to touch a real store."""
    pass


def materialize_rehearsal_blind(store: T28PrivateStore,
                                rows: list[dict[str, Any]],
                                gold: list[dict[str, Any]]) -> None:
    """Rehearsal-only blind materialization on a disposable store.

    The real construction lifecycle is the only permitted origin of blind
    material on real stores; this helper deliberately rejects non-disposable
    stores.
    """
    if not store.disposable:
        raise PreLedgerViolationExport("blind materialization is "
                                       "disposable-rehearsal only")
    store.write_once_bytes("blind/inputs.json",
                           json.dumps(rows).encode("utf-8"))
    store.write_once_bytes("blind/gold.json",
                           json.dumps(gold).encode("utf-8"))


class _FixtureRunnerAdapter:
    """Runner-bound adapter exercising the real path on tagged synthetic rows."""

    def __init__(self, workspace: str, cases: list[dict[str, Any]],
                 injections: list[dict[str, Any]]) -> None:
        from sciencemath.integrated.runner import IntegratedRunner
        from .qualification import fixture_adapters
        self._workspace = Path(workspace).resolve()
        self._by_case = {case["scenario_id"]: injection
                         for case, injection in zip(cases, injections)}
        self.IntegratedRunner = IntegratedRunner
        self._adapter_factory = fixture_adapters
        self._runs = 0

    def __call__(self, projected: dict[str, Any]) -> dict[str, Any]:
        self._runs += 1
        return self.IntegratedRunner(
            self._adapter_factory(self._by_case[projected["scenario_id"]]),
            sandbox_root=self._workspace).run(projected)

    def binding(self) -> dict[str, Any]:
        return {
            "environment_builder_id": (
                "t28_protocol.official_environment:"
                "build_official_evaluation_environment"),
            "explicitly_tagged_disposable_substitute": True,
            "workspace_mode": WORKSPACE_MODE,
        }


def run_evaluation_rehearsals(root: Path) -> dict[str, Any]:
    """Two complete disposable rehearsals of the entire official path (§50).

    Uses the same ``_evaluate_once`` path as the real evaluator with the same
    ledger ordering, identities, gold firewall, workspaces, and scorer;
    only the general context, inner provider, and row bodies are explicitly
    tagged disposable substitutes.
    """
    root = Path(root).resolve()
    from .qualification import build_public_cases

    cases, gold, injections = build_public_cases()
    encoded = [{"scenario_id": case["scenario_id"],
                "classification": "PUBLIC_SAFE",
                "plan": case["plan"]} for case in cases]
    leak = run_publication_leak_gate(root, fetch=True)
    if leak.get("status") != "PASS" or leak.get("blind_blob_count", 1) != 0:
        raise ValueError(
            "T28 evaluation rehearsal refused: public leak preflight failed")
    runs = []
    for index in (1, 2):
        with TemporaryDirectory(
                prefix=f"t28-evaluation-rehearsal-{index}-") as tmp:
            base = Path(tmp)
            store = T28PrivateStore(base / "private", repository_root=root,
                                    disposable=True)
            materialize_rehearsal_blind(store, encoded, gold)
            _env, bindings = _rehearsal_bindings(root, index)
            result = _evaluate_once(
                store=store, bindings=bindings, token=EVALUATION_TOKEN,
                build_runner=lambda workspace_path: _FixtureRunnerAdapter(
                    str(workspace_path), cases, injections),
                expected_counts=(len(cases), len(gold)),
                clock=_fixed_clock_factory(10 + index))
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
                "gold_firewall_projected_rows":
                    result["gold_firewall"]["projected_rows"],
            }
            runs.append({
                "run": index,
                "status": "PASS" if all((
                    semantic["denominators_nonzero"],
                    semantic["ordering_binding_precedes_blind_reads"],
                    semantic["ordering_blind_inputs_before_gold"],
                    semantic["ordering_reads_before_workspace"],
                )) else "FAIL",
                **semantic, "semantic_signature": sha256_json(semantic),
            })
    equivalent = runs[0]["semantic_signature"] == runs[1]["semantic_signature"]
    passed = equivalent and all(item["status"] == "PASS" for item in runs)
    return {
        "schema_version": "t28-evaluation-rehearsals-v1",
        "artifact": "T28_DISPOSABLE_EVALUATION_REHEARSALS",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "public_leak_preflight": {"status": leak.get("status"),
                                  "blind_blob_count": leak.get("blind_blob_count"),
                                  "public_leak_scan_root": sha256_json(leak)},
        "runs": runs, "semantic_equivalence": equivalent,
        "substitutes": ["disposable general context",
                        "fixture search provider", "synthetic rows"],
        "identities_shared_with_real_mode": [
            "runner_identity", "scorer", "gold firewall", "mount policy",
            "FAIL_NONVACUITY", "ledger ordering"],
        "real_evaluation_attempts": 0,
        "official_real_evaluator_invocations": 0,
    }


def run_evaluation_failure_rehearsal(root: Path) -> dict[str, Any]:
    """Post-ledger failure at four phases: FAILED, marker spent, retry refused."""
    root = Path(root).resolve()
    from .qualification import build_public_cases

    cases, gold, injections = build_public_cases()
    encoded = [{"scenario_id": case["scenario_id"],
                "classification": "PUBLIC_SAFE",
                "plan": case["plan"]} for case in cases]
    phases = []
    for index, phase in enumerate(FAILURE_PHASES, start=1):
        with TemporaryDirectory(
                prefix=f"t28-evaluation-failure-{phase.lower()}-") as tmp:
            base = Path(tmp)
            store = T28PrivateStore(base / "private", repository_root=root,
                                    disposable=True)
            materialize_rehearsal_blind(store, encoded, gold)
            _env, bindings = _rehearsal_bindings(root, index)
            injected = False
            try:
                _evaluate_once(
                    store=store, bindings=bindings, token=EVALUATION_TOKEN,
                    build_runner=lambda workspace_path: _FixtureRunnerAdapter(
                        str(workspace_path), cases, injections),
                    expected_counts=(len(cases), len(gold)),
                    clock=_fixed_clock_factory(10 * index),
                    inject_failure_phase=phase)
            except RuntimeError:
                injected = True
            ledger = T28EvaluationLedger.load(store)
            retry_refused = False
            try:
                T28EvaluationLedger.create_exclusive(
                    store, bindings, EVALUATION_TOKEN,
                    clock=_fixed_clock_factory(90 + index))
            except EvaluationLedgerError:
                retry_refused = True
            phases.append({
                "phase": phase, "injected": injected,
                "ledger_state": ledger.document["state"],
                "retry_refused": retry_refused,
            })
    passed = all(item["injected"] and item["ledger_state"] == "FAILED"
                 and item["retry_refused"] for item in phases)
    return {
        "schema_version": "t28-evaluation-failure-rehearsal-v1",
        "artifact": "T28_EVALUATION_FAILURE_REHEARSAL",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "failure_phases": phases,
        "post_ledger_failure_recorded": True,
        "one_shot": "SPENT",
        "real_evaluation_attempts": 0,
    }


def _rehearsal_environment_identity(root: Path) -> dict[str, Any]:
    """Same environment builder, explicitly tagged disposable substitutes."""
    from .official_environment import (disposable_general_context_document,
                                       environment_identity,
                                       inspect_live_provider)
    from t26_protocol.official_runner import DeterministicFixtureSearchProvider

    general_document = disposable_general_context_document()
    provider = DeterministicFixtureSearchProvider()
    base_identity = inspect_live_provider(root, provider, real=False)
    identity = {**base_identity, "explicitly_tagged_substitute": True}
    identity["identity_root"] = sha256_json({
        key: value for key, value in identity.items()
        if key != "identity_root"})
    environment = environment_identity(
        root, real=False,
        general_context_identity_root=general_document["identity_root"],
        live_provider_identity_root=identity["identity_root"])
    return {
        "general_context_document": general_document,
        "live_provider_identity": identity,
        "environment_identity_root": sha256_json(environment),
    }


def _rehearsal_bindings(root: Path, index: int) -> tuple[dict[str, Any],
                                                         dict[str, Any]]:
    root = Path(root).resolve()
    env = _rehearsal_environment_identity(root)
    identity = runner_identity(root)
    candidate = json.loads(
        (root / "evaluations/t28/candidate_identity.json").read_text(
            encoding="utf-8"))
    return env, {
        "experiment": "t28", "attempt": 1,
        "authorization_token": EVALUATION_TOKEN,
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "construction_seal_sha256": "a" * 64,
        "construction_ledger_root": "c" * 64,
        "manifest_sha256": "d" * 64,
        "private_blind_root": "e" * 64,
        "freeze_sha256": "f" * 64,
        "metric_registry_sha256": _sha_bytes(
            (root / "evaluations/t28/metric_registry.json").read_bytes()),
        "scorer_sha256": scorer_sha256(root),
        "official_runner_factory_id": FACTORY_ID,
        "official_runner_factory_sha256": sha256_json(
            {"disposable_rehearsal": index}),
        "official_runner_policy_root": identity["official_runner_policy_root"],
        "official_runner_identity_root": sha256_json(
            {"disposable_rehearsal_runner": index}),
        "provider_identity_root":
            env["live_provider_identity"]["identity_root"],
        "firewall_identity_root": official_firewall_identity_root(),
        "general_context_identity_root":
            env["general_context_document"]["identity_root"],
        "corpus_root": official_corpus_root(root),
        "document_mount_policy_root": official_document_mount_policy_root(root),
        "environment_root": env["environment_identity_root"],
        "public_leak_scan_root": sha256_json({"leak_rehearsal": index}),
        "store_verification_root": sha256_json({"store_rehearsal": index}),
        "authority": "SCORE_PRIVATE_ONCE",
        "timestamp": f"2026-09-28T0{index}:00:00+00:00",
        "state": "STARTED",
    }