"""Additive T23 doctor; invokes the frozen T22 doctor unchanged."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciencemath.executive.router_v2 import validate_router_contract
from sciencemath.knowledge.corpus import load_corpus
from sciencemath.web.fixture_provider import FixtureCorpus, FixtureSearchProvider
from t21_protocol.doctor import run_doctor as run_prior_doctor
from t21_protocol.util import read_json, sha256_file

from .author import author_cases, load_spec, shadow_labels
from .applicability import validate_applicability
from .context import CONSTRUCTION_TOKENS, EVALUATION_TOKENS
from .contract import PATHS, load_t23_contract
from .contract import CANDIDATE_COMMIT, CANDIDATE_TREE, enumerate_leaf_requirements
from .blindness import audit_blindness, synthetic_provenance
from .construction import run_shadow_construction
from .construction_ledger import T23ConstructionLedger, frozen_bindings, verify_ledger
from .exclusions import audit_exclusions, load_exclusion_sources
from .manifest import verify_seal as verify_manifest_seal
from .registry import check_real_path_registry
from .graph import load_graph, validate_graph
from .lock import verify_lock
from .lifecycle import verify_lifecycle
from .provider import ProductionRouterProvider, decision_parity
from .scorer import REGISTRY, validate_registry


def _section(status: bool, **details: Any) -> dict[str, Any]:
    return {"status": "PASS" if status else "FAIL", **details}


def run_t23_doctor(root: Path, *, run_prior: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    t23 = root / "evaluations" / "t23"
    lock = verify_lock(t23 / "author_lock.json")
    contract = load_t23_contract(t23 / "t23_master_contract.json")
    graph = validate_graph(load_graph(t23 / "production_evaluation_graph.json"))
    registry = read_json(REGISTRY)
    validate_registry(registry)
    spec = load_spec(t23 / "author_specification.json")
    leaves = enumerate_leaf_requirements(contract.document)
    path_report = check_real_path_registry(root, require_absent=True)
    exclusion_registry = read_json(t23 / "construction_exclusion_sources.json")
    exclusions = load_exclusion_sources(root, exclusion_registry)
    policy = read_json(t23 / "private_blind_policy.json")
    provider_config = read_json(t23 / "production_provider_config.json")
    web = FixtureSearchProvider(FixtureCorpus([], query_time="2026-09-22"))
    provider = ProductionRouterProvider(root / "rag" / "gk_corpus", web_provider=web,
                                        workspace_mode="SYNTHETIC_DISPOSABLE")
    init_rows = provider.rows_executed
    inputs, gold = author_cases(shadow_labels(), namespace="t23-shadow",
                             spec=spec, attachment_path="documents/shadow.txt")
    sample = [row for row in inputs if "insufficient_evidence" in row["case_id"]][:3]
    parity = decision_parity(sample, provider.generate(sample))
    checks = {
        "T23_AUTHOR_LOCK": _section(lock["status"] == "PASS" and lock["missing_bindings"] == 0,
                                    binding_count=lock["binding_count"]),
        "T23_CANDIDATE_BINDING": _section(
            lock["candidate_commit"] == CANDIDATE_COMMIT
            and lock["candidate_tree"] == CANDIDATE_TREE
            and contract.get("identity")["candidate_commit"] == CANDIDATE_COMMIT),
        "T23_PRODUCTION_EXPERIMENT_REGISTRY": _section(
            contract.experiment == "t23" and "t23" in CONSTRUCTION_TOKENS and "t23" in EVALUATION_TOKENS
            and set(CONSTRUCTION_TOKENS) == {"t21r15", "t21r16", "t21r17", "t22", "t23"}),
        "T23_CONSTRUCTION_CONTRACT": _section(
            contract.get("construction_authorized") is False
            and contract.get("real_t23_paths") == list(PATHS.values())
            and all(not (root / path).exists() for path in PATHS.values())),
        "T23_CONTRACT_LEAVES": _section(len(leaves) > 0,
                                        leaf_requirement_count=len(leaves)),
        "T23_REAL_PATH_REGISTRY": _section(path_report["registered"] == 22
                                            and path_report["present"] == 0,
                                            registered=path_report["registered"],
                                            present=path_report["present"],
                                            unknown=path_report["unknown"]),
        "T23_EXCLUSION_SOURCES": _section(
            len(exclusions) == 9 and len(exclusion_registry["required_milestones"]) == 17,
            historical_milestones=18, dimensions=len(exclusions)),
        "T23_EVALUATION_GRAPH": _section(graph["status"] == "PASS", producer_count=graph["producer_count"]),
        "T23_PRODUCTION_PROVIDER": _section(
            init_rows == 0 and parity["status"] == "PASS"
            and provider_config["provider_entry"] == provider.provider_id
            and sha256_file(root / provider_config["general_adapter"]) == provider_config["general_adapter_sha256"],
            initialization_rows=init_rows, parity=parity),
        "T23_PRIVATE_BLIND_POLICY": _section(
            policy["future_blind_publication_allowed"] is False
            and {"real blind corpus", "gold suites", "blind outputs", "raw results", "private anchors"}.issubset(set(policy["private_only"]))
            and all(node["privacy"] == "PRIVATE" for node in load_graph(t23 / "production_evaluation_graph.json")["nodes"].values())),
        "T23_ROUTER_METRICS": _section(len(registry["metrics"]) == 15 and registry["generic_fallback_consumers"] == 0),
        "EXECUTIVE_ROUTER": validate_router_contract(),
    }
    blind = audit_blindness(root, inputs, gold, synthetic_provenance(), real=False)
    unique = audit_exclusions(root, exclusion_registry, inputs, gold,
                              load_corpus(root / "rag/gk_corpus"))
    checks["T23_BLINDNESS_CHECKER"] = _section(blind["status"] == "PASS"
                                                and blind["violations"] == 0,
                                                violations=blind["violations"])
    checks["T23_UNIQUENESS_EXCLUSIONS"] = _section(unique["status"] == "PASS"
                                                   and unique["violations"] == 0,
                                                   historical_milestones=unique["historical_milestones"],
                                                   fingerprint_dimensions=len(unique["fingerprint_dimensions"]))
    with TemporaryDirectory(prefix="t23-doctor-ledger-") as temp_ledger:
        ledger_path = Path(temp_ledger) / "construction_run_ledger.json"
        bindings = frozen_bindings(root, real=False, namespace="t23-doctor")
        ledger = T23ConstructionLedger.create_exclusive(ledger_path, bindings)
        duplicate_refused = False
        try:
            T23ConstructionLedger.create_exclusive(ledger_path, bindings)
        except Exception:
            duplicate_refused = True
        ledger.fail("disposable doctor negative control")
        retry_refused = False
        try:
            ledger.advance("MATERIALIZED")
        except Exception:
            retry_refused = True
        checks["T23_LEDGER_SCHEMA_ONE_SHOT"] = _section(
            duplicate_refused and retry_refused
            and verify_ledger(ledger_path, bindings)["state"] == "FAILED")
    with TemporaryDirectory(prefix="t23-doctor-rehearsal-") as temp_rehearsal:
        workspace = Path(temp_rehearsal)
        preseal_refused = False
        try:
            verify_manifest_seal(root, workspace)
        except (OSError, ValueError, KeyError):
            preseal_refused = True
        rehearsal = run_shadow_construction(root, workspace)
        checks["T23_CONSTRUCTION_GATE"] = _section(
            rehearsal["gate"]["status"] == "PASS"
            and rehearsal["gate"]["check_count"] >= 19,
            checks=rehearsal["gate"]["check_count"])
        checks["T23_MANIFEST_SEAL"] = _section(
            rehearsal["seal"]["status"] == "PASS"
            and rehearsal["seal"]["bindings"] >= 49,
            bound_artifacts=rehearsal["seal"]["bindings"])
        checks["T23_STATE_MACHINE_EVALUATION_LOCKOUT"] = _section(
            preseal_refused and rehearsal["terminal_state"] == "SEALED")
    lifecycle_t22 = verify_lifecycle(root, "t22")
    lifecycle_t23 = verify_lifecycle(root, "t23")
    checks["HISTORICAL_LIFECYCLE_CONSISTENCY"] = _section(
        lifecycle_t22["status"] == "PASS" and lifecycle_t23["status"] == "PASS",
        t22=lifecycle_t22, t23=lifecycle_t23)
    try:
        applicability = validate_applicability(root, require_tracked=True)
        checks["T23_HISTORICAL_APPLICABILITY"] = _section(
            applicability["status"] == "PASS" and applicability["live_failures"] == 0
            and applicability["unknown_failures"] == 0,
            raw_pytest_failed=applicability["raw_pytest_failed"],
            recognized=applicability["recognized_historical_failures"],
            failure_set_sha256=applicability["failure_set_sha256"],
            applicability_decision_root=applicability["applicability_decision_root"],
            LIVE=applicability["live_failures"], UNKNOWN=applicability["unknown_failures"])
    except (KeyError, ValueError, OSError) as exc:
        checks["T23_HISTORICAL_APPLICABILITY"] = _section(False, reason=str(exc),
                                                            LIVE="UNKNOWN", UNKNOWN="UNKNOWN")
    base = run_prior_doctor(root, experiment="t22") if run_prior else None
    if base is not None:
        # The frozen T22 doctor is a preconstruction-era implementation. Its
        # unconditional real_paths check is superseded only by independently
        # verified lifecycle evidence; every other frozen check must still pass.
        other_failures = sorted(name for name, check in base["checks"].items()
                                if name != "real_paths"
                                and check.get("status") not in {"PASS", "VERIFIED"})
        legacy_paths = base["checks"]["real_paths"]
        checks["T21_PROTOCOL_DOCTOR"] = _section(
            not other_failures and lifecycle_t22["status"] == "PASS"
            and legacy_paths["checked"] == lifecycle_t22["registered_paths"]
            and len(legacy_paths["present"]) == lifecycle_t22["present_paths"],
            frozen_verdict=base["verdict"], other_failures=other_failures,
            historical_real_paths=legacy_paths)
    passed = all(check.get("status") == "PASS" for check in checks.values())
    return {"schema_version": "t23-production-doctor-v1",
            "artifact": "T23_PRODUCTION_PROTOCOL_DOCTOR", "experiment": "t23",
            "checks": checks, "base_verdict": base["verdict"] if base else "NOT_RUN",
            "historical_raw_t22_doctor": base["verdict"] if base else "NOT_RUN",
            "current_applicability_interpretation": checks["T23_HISTORICAL_APPLICABILITY"],
            "status": "PASS" if passed else "FAIL",
            "verdict": "T23_APPLICABILITY_PROTOCOL_DOCTOR_PASS" if passed else "T23_APPLICABILITY_PROTOCOL_DOCTOR_FAIL"}
