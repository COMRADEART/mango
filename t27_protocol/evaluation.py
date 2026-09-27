"""Frozen one-shot T27 official evaluation infrastructure."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from t21_protocol.util import sha256_json

from .construction import (_event, _fixed_clock_factory, _sha_bytes,
                           candidate_input_projection, verify_event_chain)
from .contract import CRITICAL_COUNTERS, EVALUATION_TOKEN
from .scorer import score_suite
from .store import T27PrivateStore

EVALUATION_STATES = ("STARTED", "EXECUTED", "SCORED", "COMPLETE", "FAILED")
EVALUATION_TRANSITIONS = {
    "STARTED": {"EXECUTED", "FAILED"},
    "EXECUTED": {"SCORED", "FAILED"},
    "SCORED": {"COMPLETE", "FAILED"},
    "COMPLETE": set(), "FAILED": set(),
}
EVALUATION_BINDING_FIELDS = frozenset({
    "experiment", "attempt", "authorization_token", "candidate_commit",
    "candidate_tree", "runtime_root", "construction_seal_sha256",
    "construction_ledger_root", "manifest_sha256", "private_blind_root",
    "freeze_sha256", "metric_registry_sha256", "official_runner_factory_id",
    "official_runner_factory_sha256", "official_runner_policy_root",
    "provider_firewall_identity_root", "general_context_identity_root",
    "corpus_document_mount_root", "authority", "timestamp", "state",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def runner_identity(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    candidate = json.loads((root / "evaluations/t27/candidate_identity.json").read_text(
        encoding="utf-8"))
    components = {
        "runner_factory": _sha_bytes((root / "t27_protocol/evaluation.py").read_bytes()),
        "candidate_runtime": candidate["runtime_root"],
        "production_adapter_registry": _sha_bytes(
            (root / "t27_protocol/production.py").read_bytes()),
        "production_provider": "t25_protocol.provider:T25ProductionRouterProvider",
        "web_firewall_stack": "t26_protocol.firewall:T26LiveWebSourceFirewall",
        "general_context": "BOUND_BY_OFFICIAL_FACTORY",
        "corpus_document_mounts": "PRIVATE_MANIFEST_BOUND",
        "authority": "COORDINATE_INTERNAL_WORK_ONLY",
    }
    policy = {
        "arbitrary_caller_supplied_runner_allowed": False,
        "factory_owns_provider_construction": True,
        "candidate_gold_access": False,
        "synthetic_data_source_allowed_only_for_disposable_rehearsal": True,
        "real_mode_requires_sealed_store": True,
    }
    core = {
        "schema_version": "t27-official-runner-identity-v1",
        "artifact": "T27_OFFICIAL_RUNNER_IDENTITY", "classification": "PUBLIC_SAFE",
        "factory_id": "t27_protocol.evaluation:OfficialRunnerFactory",
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "components": components, "policy": policy,
        "provider_firewall_identity_root": sha256_json({
            "provider": components["production_provider"],
            "firewall": components["web_firewall_stack"]}),
        "general_context_identity_root": sha256_json(components["general_context"]),
        "corpus_document_mount_root": sha256_json(components["corpus_document_mounts"]),
    }
    core["official_runner_policy_root"] = sha256_json(policy)
    return {**core, "factory_sha256": sha256_json(core)}


class EvaluationLedgerError(RuntimeError):
    pass


class T27EvaluationLedger:
    PATH = "evaluation/ledger.json"
    MARKER = "markers/evaluation.one-shot"

    @staticmethod
    def _event_path(index: int) -> str:
        return f"evaluation/events/{index:06d}.json"

    def __init__(self, store: T27PrivateStore, document: dict[str, Any]) -> None:
        self.store = store
        self.document = document

    @classmethod
    def create_exclusive(cls, store: T27PrivateStore,
                         bindings: dict[str, Any], token: str,
                         *, clock: Callable[[], str] = _now) -> "T27EvaluationLedger":
        if token != EVALUATION_TOKEN:
            raise EvaluationLedgerError("wrong official evaluation token")
        if set(bindings) != EVALUATION_BINDING_FIELDS:
            raise EvaluationLedgerError("evaluation ledger binding set mismatch")
        if (bindings["experiment"] != "t27" or bindings["attempt"] != 1
                or bindings["authorization_token"] != EVALUATION_TOKEN
                or bindings["authority"] != "SCORE_PRIVATE_ONCE"
                or bindings["state"] != "STARTED"):
            raise EvaluationLedgerError("evaluation ledger immutable binding mismatch")
        if store.has(cls.MARKER) or store.has(cls.PATH):
            raise EvaluationLedgerError("T27 official evaluation one-shot already spent")
        event = _event(0, "STARTED", clock(), None, {
            "attempt": 1, "bindings_sha256": sha256_json(bindings)})
        document = {
            "schema_version": "t27-evaluation-ledger-v1",
            "artifact": "T27_EVALUATION_LEDGER", "classification": "PRIVATE_LEDGER",
            "bindings": copy.deepcopy(bindings), "events": [event],
            "state": "STARTED", "final_event_hash": event["event_hash"],
        }
        document["ledger_root"] = sha256_json({
            "bindings": document["bindings"], "events": document["events"]})
        marker = {
            "schema_version": "t27-evaluation-one-shot-v1",
            "artifact": "T27_EVALUATION_ONE_SHOT_SPENT",
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
        return cls(store, document)

    @classmethod
    def load(cls, store: T27PrivateStore) -> "T27EvaluationLedger":
        if not store.has(cls.MARKER) or not store.has(cls.PATH):
            raise EvaluationLedgerError("evaluation ledger or marker deleted")
        document = store.read_json(cls.PATH)
        marker = store.read_json(cls.MARKER)
        event_directory = store.path("evaluation/events")
        journals = ([json.loads(path.read_text(encoding="utf-8"))
                     for path in sorted(event_directory.glob("*.json"))]
                    if event_directory.is_dir() else [])
        if (marker.get("bindings_sha256") != sha256_json(document.get("bindings"))
                or marker.get("genesis_event_hash") != document.get("events", [{}])[0].get("event_hash")
                or journals != document.get("events")
                or not verify_event_chain(document)):
            raise EvaluationLedgerError("evaluation ledger/marker integrity failure")
        return cls(store, document)

    def advance(self, state: str, payload: dict[str, Any], *,
                clock: Callable[[], str] = _now) -> None:
        current = self.document["state"]
        if state not in EVALUATION_TRANSITIONS[current]:
            raise EvaluationLedgerError(f"invalid evaluation transition {current}->{state}")
        event = _event(len(self.document["events"]), state, clock(),
                       self.document["final_event_hash"], copy.deepcopy(payload))
        self.document["events"].append(event)
        self.document["state"] = state
        self.document["final_event_hash"] = event["event_hash"]
        self.document["ledger_root"] = sha256_json({
            "bindings": self.document["bindings"], "events": self.document["events"]})
        self.store.write_once_json(self._event_path(event["event_index"]), event)
        self.store.replace_ledger(self.PATH, self.document)

    def fail(self, phase: str, error: BaseException, *,
             clock: Callable[[], str] = _now) -> None:
        if self.document["state"] in {"COMPLETE", "FAILED"}:
            raise EvaluationLedgerError("terminal evaluation ledger cannot fail again")
        evidence = {
            "failure_phase": phase, "failure_class": type(error).__name__,
            "evidence_hash": sha256_json({
                "phase": phase, "class": type(error).__name__,
                "message_sha256": hashlib.sha256(str(error).encode()).hexdigest(),
            }),
        }
        self.advance("FAILED", evidence, clock=clock)


class OfficialRunnerFactory:
    """Sole runner factory; callers may select data, never inject a runner."""

    def __init__(self, root: Path, *, mode: str) -> None:
        if mode not in {"REAL", "SYNTHETIC_DISPOSABLE"}:
            raise ValueError("unknown T27 official runner mode")
        self.root = Path(root).resolve()
        self.mode = mode
        self.identity = runner_identity(self.root)

    def run_disposable(self, cases: list[dict[str, Any]],
                       injections: list[dict[str, Any]],
                       workspace: Path) -> list[dict[str, Any]]:
        if self.mode != "SYNTHETIC_DISPOSABLE":
            raise ValueError("synthetic source forbidden in real runner mode")
        from sciencemath.integrated.runner import IntegratedRunner
        from .qualification import fixture_adapters

        outputs = []
        for case, injection in zip(cases, injections):
            projected = candidate_input_projection(case)
            path = workspace / projected["scenario_id"]
            path.mkdir(parents=True, exist_ok=True)
            outputs.append(IntegratedRunner(
                fixture_adapters(injection), sandbox_root=path).run(projected))
        return outputs

    def build_real_runner(self, *, corpus_mount: Path, web_provider: Any,
                          general_context: Any, document_roots: tuple[Path, ...]
                          ) -> Callable[[dict[str, Any], Path], dict[str, Any]]:
        if self.mode != "REAL":
            raise ValueError("real runner requested in disposable mode")
        from sciencemath.integrated.runner import IntegratedRunner
        from t25_protocol.firewall import FirewallSearchProvider
        from t25_protocol.provider import T25ProductionRouterProvider
        from t26_protocol.firewall import T26LiveWebSourceFirewall
        from .production import build_adapters

        if (not isinstance(web_provider, FirewallSearchProvider)
                or not isinstance(web_provider.firewall, T26LiveWebSourceFirewall)):
            raise ValueError("official T27 live-web firewall stack mismatch")
        provider = T25ProductionRouterProvider(
            corpus_mount, web_provider=web_provider,
            general_context=general_context, document_roots=document_roots,
            workspace_mode="T27_OFFICIAL_EVALUATION", firewall_mandatory=True)
        adapters = build_adapters(provider)

        def run(case: dict[str, Any], workspace: Path) -> dict[str, Any]:
            projected = candidate_input_projection(case)
            workspace.mkdir(parents=True, exist_ok=True)
            return IntegratedRunner(adapters, sandbox_root=workspace).run(projected)
        return run


def evaluation_bindings(root: Path, seal: dict[str, Any],
                        ledger_root: str, *, timestamp: str | None = None
                        ) -> dict[str, Any]:
    identity = runner_identity(root)
    return {
        "experiment": "t27", "attempt": 1,
        "authorization_token": EVALUATION_TOKEN,
        "candidate_commit": seal["candidate_commit"],
        "candidate_tree": seal["candidate_tree"],
        "runtime_root": seal["runtime_root"],
        "construction_seal_sha256": seal.get("seal_sha256", "a" * 64),
        "construction_ledger_root": ledger_root,
        "manifest_sha256": seal["manifest_sha256"],
        "private_blind_root": seal["private_blind_root"],
        "freeze_sha256": seal["freeze_sha256"],
        "metric_registry_sha256": seal["metric_registry_sha256"],
        "official_runner_factory_id": identity["factory_id"],
        "official_runner_factory_sha256": identity["factory_sha256"],
        "official_runner_policy_root": identity["official_runner_policy_root"],
        "provider_firewall_identity_root": identity["provider_firewall_identity_root"],
        "general_context_identity_root": identity["general_context_identity_root"],
        "corpus_document_mount_root": identity["corpus_document_mount_root"],
        "authority": "SCORE_PRIVATE_ONCE", "timestamp": timestamp or _now(),
        "state": "STARTED",
    }


def _public_evaluation_receipt(store: T27PrivateStore,
                               ledger: T27EvaluationLedger,
                               score: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "t27-public-evaluation-receipt-v1",
        "artifact": "T27_PUBLIC_EVALUATION_RECEIPT",
        "classification": "PUBLIC_SAFE", "experiment": "t27", "attempt": 1,
        "state": "COMPLETE", "evaluation_ledger_sha256": _sha_bytes(
            store.read_bytes("evaluation/ledger.json")),
        "evaluation_ledger_root": ledger.document["ledger_root"],
        "scenario_count": score["scenario_count"], "status": score["status"],
        "metrics": {name: {key: metric[key] for key in (
            "numerator", "denominator", "observed", "floor", "pass",
            "zero_denominator_policy")}
                    for name, metric in score["metrics"].items()},
        "critical_counters": score["critical_counters"],
        "raw_outputs_included": False, "scored_rows_included": False,
        "gold_included": False,
    }


def _evaluate_once(*, store: T27PrivateStore,
                   bindings: dict[str, Any], token: str,
                   cases: list[dict[str, Any]], gold: list[dict[str, Any]],
                   execute: Callable[[], list[dict[str, Any]]],
                   clock: Callable[[], str] = _now,
                   inject_failure_phase: str | None = None) -> dict[str, Any]:
    if len(cases) != len(gold) or not cases:
        raise ValueError("T27 evaluation scenario/gold cardinality mismatch")
    # Firewall projection happens before the one-shot is spent.
    projected = [candidate_input_projection(case) for case in cases]
    if any(set(item) != {"scenario_id", "classification", "plan"}
           for item in projected):
        raise ValueError("T27 gold firewall projection mismatch")
    ledger = T27EvaluationLedger.create_exclusive(store, bindings, token, clock=clock)
    phase = "STARTED"
    try:
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-ledger evaluation failure")
        outputs = execute()
        if len(outputs) != len(cases):
            raise ValueError("official runner output cardinality mismatch")
        store.write_once_json("evaluation/raw_outputs.json", outputs)
        ledger.advance("EXECUTED", {
            "output_count": len(outputs),
            "raw_outputs_sha256": _sha_bytes(store.read_bytes(
                "evaluation/raw_outputs.json")),
        }, clock=clock)
        phase = "EXECUTED"
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-execution evaluation failure")
        plans = [case["plan"] for case in cases]
        score = score_suite(outputs, gold, plans)
        scored_rows = [{
            "scenario_id": case["scenario_id"],
            "expected_terminal": expected["expected_terminal"],
            "observed_terminal": output.get("terminal"),
            "terminal_correct": output.get("terminal") == expected["expected_terminal"],
        } for case, expected, output in zip(cases, gold, outputs)]
        store.write_once_json("evaluation/scored_rows.json", scored_rows)
        store.write_once_json("evaluation/summary.json", score)
        ledger.advance("SCORED", {
            "score_status": score["status"],
            "summary_sha256": _sha_bytes(store.read_bytes("evaluation/summary.json")),
            "scored_rows_sha256": _sha_bytes(store.read_bytes(
                "evaluation/scored_rows.json")),
        }, clock=clock)
        phase = "SCORED"
        if inject_failure_phase == phase:
            raise RuntimeError("injected post-score evaluation failure")
        ledger.advance("COMPLETE", {
            "score_status": score["status"], "scenario_count": len(cases),
        }, clock=clock)
        receipt = _public_evaluation_receipt(store, ledger, score)
        return {
            "status": "PASS", "ledger": ledger.document, "score": score,
            "receipt": receipt,
            "gold_firewall": {
                "status": "PASS", "projected_rows": len(projected),
                "gold_fields_in_candidate_input": 0,
                "candidate_gold_access_edges": 0,
            },
        }
    except Exception as exc:
        if ledger.document["state"] not in {"COMPLETE", "FAILED"}:
            ledger.fail(phase, exc, clock=clock)
        raise


def evaluate_official(*, root: Path, private_store_root: Path, token: str,
                      corpus_mount: Path, web_provider: Any,
                      general_context: Any,
                      document_roots: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Real official entrypoint; it owns runner/provider composition."""
    root = Path(root).resolve()
    store = T27PrivateStore(private_store_root, repository_root=root)
    seal = store.read_json("construction/seal.json")
    construction_ledger = store.read_json("construction/ledger.json")
    if seal.get("state") != "SEALED" or construction_ledger.get("state") != "SEALED":
        raise ValueError("official evaluation requires sealed T27 construction")
    if store.has("evaluation/ledger.json") or store.has("markers/evaluation.one-shot"):
        raise ValueError("T27 official evaluation one-shot already spent")
    cases = json.loads(store.read_bytes("blind/inputs.json"))
    gold = json.loads(store.read_bytes("blind/gold.json"))
    if len(cases) != 512 or len(gold) != 512:
        raise ValueError("sealed T27 official evaluation requires 512/512")
    factory = OfficialRunnerFactory(root, mode="REAL")
    run = factory.build_real_runner(
        corpus_mount=corpus_mount, web_provider=web_provider,
        general_context=general_context, document_roots=document_roots)
    workspace_root = store.path("evaluation/workspaces")
    workspace_root.mkdir(parents=True, exist_ok=True)

    def execute() -> list[dict[str, Any]]:
        return [run(case, workspace_root / case["scenario_id"]) for case in cases]

    seal_for_bindings = {**seal, "seal_sha256": _sha_bytes(
        store.read_bytes("construction/seal.json"))}
    bindings = evaluation_bindings(
        root, seal_for_bindings, construction_ledger["ledger_root"])
    return _evaluate_once(
        store=store, bindings=bindings, token=token, cases=cases, gold=gold,
        execute=execute)


def _synthetic_seal(root: Path) -> dict[str, Any]:
    candidate = json.loads((Path(root) / "evaluations/t27/candidate_identity.json").read_text(
        encoding="utf-8"))
    return {
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "seal_sha256": "1" * 64, "manifest_sha256": "2" * 64,
        "private_blind_root": "3" * 64, "freeze_sha256": "4" * 64,
        "metric_registry_sha256": _sha_bytes(
            (Path(root) / "evaluations/t27/metric_registry.json").read_bytes()),
    }


def run_evaluation_rehearsals(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    from .qualification import build_public_cases

    cases, gold, injections = build_public_cases()
    runs = []
    for index in (1, 2):
        with TemporaryDirectory(prefix=f"t27-evaluation-rehearsal-{index}-") as tmp:
            store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                    disposable=True)
            factory = OfficialRunnerFactory(root, mode="SYNTHETIC_DISPOSABLE")
            workspace = Path(tmp) / "workspaces"
            workspace.mkdir()
            bindings = evaluation_bindings(
                root, _synthetic_seal(root), "5" * 64,
                timestamp="2026-09-27T01:00:00+00:00")
            result = _evaluate_once(
                store=store, bindings=bindings, token=EVALUATION_TOKEN,
                cases=cases, gold=gold,
                execute=lambda f=factory, w=workspace: f.run_disposable(
                    cases, injections, w),
                clock=_fixed_clock_factory(10 + index))
            score = result["score"]
            denominators_nonzero = all(
                metric["denominator"] > 0 for metric in score["metrics"].values())
            floors_pass = all(metric["pass"] for metric in score["metrics"].values())
            critical_zero = all(score["critical_counters"].get(name) == 0
                                for name in CRITICAL_COUNTERS)
            semantic = {
                "state_sequence": [event["event_type"]
                                   for event in result["ledger"]["events"]],
                "scenario_count": score["scenario_count"],
                "denominators_nonzero": denominators_nonzero,
                "all_public_qualification_floors_pass": floors_pass,
                "critical_counters_zero": critical_zero,
                "gold_firewall": result["gold_firewall"]["status"],
            }
            runs.append({
                "run": index,
                "status": "PASS" if all((denominators_nonzero, floors_pass,
                                            critical_zero)) else "FAIL",
                **semantic, "semantic_signature": sha256_json(semantic),
            })
    equivalent = runs[0]["semantic_signature"] == runs[1]["semantic_signature"]
    passed = equivalent and all(item["status"] == "PASS" for item in runs)
    return {
        "schema_version": "t27-evaluation-rehearsals-v1",
        "artifact": "T27_DISPOSABLE_EVALUATION_REHEARSALS",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "runs": runs, "semantic_equivalence": equivalent,
        "real_evaluation_attempts": 0, "official_real_evaluator_invocations": 0,
    }


def run_evaluation_failure_rehearsal(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    from .qualification import build_public_cases

    cases, gold, _ = build_public_cases()
    with TemporaryDirectory(prefix="t27-evaluation-failure-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=root,
                                disposable=True)
        bindings = evaluation_bindings(
            root, _synthetic_seal(root), "6" * 64,
            timestamp="2026-09-27T02:00:00+00:00")
        injected = False
        try:
            _evaluate_once(
                store=store, bindings=bindings, token=EVALUATION_TOKEN,
                cases=cases, gold=gold, execute=lambda: [],
                clock=_fixed_clock_factory(20), inject_failure_phase="STARTED")
        except RuntimeError:
            injected = True
        ledger = T27EvaluationLedger.load(store)
        retry_refused = False
        try:
            T27EvaluationLedger.create_exclusive(
                store, bindings, EVALUATION_TOKEN, clock=_fixed_clock_factory(20))
        except EvaluationLedgerError:
            retry_refused = True
        passed = injected and ledger.document["state"] == "FAILED" and retry_refused
        return {
            "schema_version": "t27-evaluation-failure-rehearsal-v1",
            "artifact": "T27_EVALUATION_FAILURE_REHEARSAL",
            "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
            "post_ledger_failure_recorded": ledger.document["state"] == "FAILED",
            "retry_refused": retry_refused, "one_shot": "SPENT",
            "real_evaluation_attempts": 0,
        }
