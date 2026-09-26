"""Fail-closed T26 preconstruction protocol doctor."""
from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import tempfile
from pathlib import Path

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import (AUTHORITY, ExecutionError,
                                           IntegratedRunner, validate_plan)
from t21_protocol.util import sha256_json
from .contract import (CRITICAL_COUNTERS, FAMILIES, authority_graph,
                       design, execution_contract, live_web_firewall_registry,
                       metric_registry,
                       production_graph, storage_policy)
from .firewall import negative_controls
from .freeze import verify_freeze
from .lifecycle import T26PrivateStore, require_token
from .native_smoke import native_case
from .qualification import build_public_cases, exclusion_fingerprints
from .sandbox_controls import code_controls, memory_controls

T26 = Path("evaluations/t26")
T25_PROMOTION = "8940d96aacb08d8acf110e5f3e45e9ce84f03577"


def _read(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()


def _candidate(root: Path) -> dict:
    record = _read(root, "evaluations/t26/candidate_identity.json")
    commit = record["candidate_commit"]
    expected_tree = record["candidate_tree"]
    actual_tree = _git(root, "rev-parse", f"{commit}^{{tree}}")
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor",
                               T25_PROMOTION, commit], cwd=root).returncode == 0
    head_ancestry = subprocess.run(["git", "merge-base", "--is-ancestor",
                                    commit, "HEAD"], cwd=root).returncode == 0
    drift = []
    mapping = record["runtime_component_sha256"]
    for relative, expected in mapping.items():
        path = root / relative
        if not path.is_file() or _sha(path) != expected:
            drift.append(relative)
    runtime_root = sha256_json(mapping)
    passed = (actual_tree == expected_tree and ancestry and head_ancestry
              and not drift and runtime_root == record["runtime_root"]
              and record["changed_from_t25"] is True
              and record["parent_candidate"] ==
              "ba34f7b2cc46158a5064a8e1c217f53e4d2dbf83")
    return {"status": "PASS" if passed else "FAIL", "candidate_commit": commit,
            "candidate_tree": actual_tree, "runtime_root": runtime_root,
            "runtime_components": len(mapping), "drift": drift,
            "t25_ancestor": ancestry, "candidate_ancestor_of_head": head_ancestry}


def _graph(document: dict) -> dict:
    nodes = document["nodes"]
    errors = []
    for name, node in nodes.items():
        reference = node.get("producer", "")
        if ":" not in reference:
            errors.append(f"{name}:missing_producer")
            continue
        module, attr = reference.split(":", 1)
        try:
            value = importlib.import_module(module)
            for part in attr.split("."):
                value = getattr(value, part)
            if not callable(value):
                errors.append(f"{name}:noncallable_producer")
        except Exception:
            errors.append(f"{name}:unresolved_producer")
        if node.get("classification") not in {"PUBLIC_SAFE", "PRIVATE_BLIND",
                                               "PRIVATE_EVALUATION"}:
            errors.append(f"{name}:unclassified")
        for parent in node.get("inputs", []):
            if parent not in nodes:
                errors.append(f"{name}:dangling:{parent}")
    visiting: set[str] = set()
    seen: set[str] = set()
    def visit(name: str) -> None:
        if name in visiting:
            errors.append(f"cycle:{name}")
            return
        if name in seen:
            return
        visiting.add(name)
        for parent in nodes[name]["inputs"]:
            if parent in nodes:
                visit(parent)
        visiting.remove(name)
        seen.add(name)
    for name in nodes:
        visit(name)
    required = {"planner", "plan_validator", "orchestrator", "executive_router",
                "capability_dispatcher", "capabilities", "handoff_validator",
                "verification_layer", "checkpoint_manager", "replan_controller",
                "budget_controller", "completion_gate", "evaluator", "scorer",
                "publication_gate"}
    if not required <= set(nodes):
        errors.append("required_nodes_missing")
    return {"status": "PASS" if not errors else "FAIL",
            "node_count": len(nodes), "errors": errors}


def _private_storage_controls(root: Path) -> dict:
    results = {}
    with tempfile.TemporaryDirectory(prefix="t26-store-doctor-") as tmp:
        store_root = Path(tmp) / "T26-STORE-01"
        store = T26PrivateStore(store_root, root)
        results["locator"] = store.locator("control/value.json").startswith(
            "t26-private://T26-STORE-01/t26/")
        try:
            require_token("T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION-v2",
                          "construction")
            results["alias_refused"] = False
        except PermissionError:
            results["alias_refused"] = True
        try:
            store.path("../escape")
            results["escape_refused"] = False
        except ValueError:
            results["escape_refused"] = True
        store.write_once("control/value.json", {"synthetic": True})
        try:
            store.write_once("control/value.json", {"synthetic": False})
            results["overwrite_refused"] = False
        except FileExistsError:
            results["overwrite_refused"] = True
    return {"status": "PASS" if all(results.values()) else "FAIL",
            "controls": results, "real_store_created": False}


def _gold_and_handoff_controls() -> dict:
    cases, _, _ = build_public_cases()
    sample = cases[0]
    rejected = {}
    bad = json.loads(json.dumps(sample["plan"]))
    bad["secret_gold"] = 1
    try:
        validate_plan(bad)
        rejected["unknown_plan_field"] = False
    except ExecutionError:
        rejected["unknown_plan_field"] = True
    bad = json.loads(json.dumps(sample["plan"]))
    bad["authority"] = "PERFORM_EXTERNAL_ACTION"
    try:
        validate_plan(bad)
        rejected["authority_escalation"] = False
    except ExecutionError:
        rejected["authority_escalation"] = True
    producer, consumer = sample["plan"]["steps"][:2]
    output = {"classification": "PUBLIC_SAFE", "provenance": {"source_id": "fixture"},
              "confidence": "HIGH", "status": "OK", "value": 1,
              "evidence": []}
    rejected["valid_handoff_accepted"] = IntegratedRunner._handoff_valid(
        producer, consumer, output, "PUBLIC_SAFE")
    rejected["unclassified_handoff_refused"] = not IntegratedRunner._handoff_valid(
        producer, consumer, {**output, "classification": "UNKNOWN"}, "PUBLIC_SAFE")
    rejected["unknown_producer_refused"] = not IntegratedRunner._handoff_valid(
        {**producer, "capability": "UNREGISTERED"}, consumer, output, "PUBLIC_SAFE")
    return {"status": "PASS" if all(rejected.values()) else "FAIL",
            "controls": rejected}


def _leak_scan(root: Path) -> dict:
    tracked = _git(root, "ls-files").splitlines()
    t26_tracked = [p.replace("\\", "/") for p in tracked if p.startswith("evaluations/t26/")]
    forbidden_fragments = ("/real_blind/", "/private/", "/suites/",
                           "/construction/", "/evaluation/", "/raw_outputs/")
    violating = [p for p in t26_tracked if any(fragment in p for fragment in forbidden_fragments)]
    local = root / "evaluations/t26"
    real_paths = [] if not local.exists() else [p.relative_to(root).as_posix()
                   for p in local.rglob("*") if p.is_file() and
                   any(fragment in p.relative_to(root).as_posix() for fragment in forbidden_fragments)]
    return {"status": "PASS" if not violating and not real_paths else "FAIL",
            "public_blind_blob_count": len(violating),
            "forbidden_local_paths": real_paths,
            "tracked_t26_paths": len(t26_tracked)}


def run_doctor(root: Path, *, require_freeze: bool = True) -> dict:
    root = Path(root).resolve()
    checks = {}
    promotion = _read(root, "evaluations/t25/T25_FINAL_PROMOTION_RECORD.json")
    checks["T25_PROMOTION_ANCHOR"] = {
        "status": "PASS" if promotion.get("verdict") ==
        "MANGO_EXECUTIVE_ROUTER_AND_CAPABILITY_DISPATCH_PROMOTED" and
        _git(root, "rev-parse", T25_PROMOTION) == T25_PROMOTION else "FAIL"}
    checks["CANDIDATE_IDENTITY"] = _candidate(root)
    expected = {
        "SCENARIO_TAXONOMY": ("prospective_design.json", design()),
        "EXECUTION_CONTRACT": ("t26_execution_contract.json", execution_contract()),
        "METRIC_REGISTRY": ("metric_registry.json", metric_registry()),
        "AUTHORITY_GRAPH": ("authority_graph.json", authority_graph()),
        "PRODUCTION_GRAPH": ("production_graph.json", production_graph()),
        "PRIVATE_STORAGE_POLICY": ("private_storage_policy.json", storage_policy()),
    }
    for name, (filename, document) in expected.items():
        actual = _read(root, f"evaluations/t26/{filename}")
        checks[name] = {"status": "PASS" if actual == document else "FAIL",
                        "sha256": _sha(root / "evaluations/t26" / filename)}
    cases, gold, _ = build_public_cases()
    exclusions = _read(root, "evaluations/t26/qualification_exclusions.json")
    qualification = _read(root, "evaluations/t26/qualification_report.json")
    checks["PUBLIC_QUALIFICATION"] = {
        "status": "PASS" if qualification["status"] == "PASS" and
        qualification["scenario_count"] == 64 and
        qualification["family_count"] == len(FAMILIES) == 16 and
        qualification["dispatch_unmatched"] == 0 and
        qualification["unexpected_unknown_terminal"] == 0 and
        exclusions == exclusion_fingerprints(cases + [native_case()[0]]) else "FAIL",
        "cases": qualification["scenario_count"],
        "families": qualification["family_count"]}
    checks["LIVE_WEB_FIREWALL_REGISTRY"] = {
        "status": "PASS" if _read(root, "evaluations/t26/live_web_firewall_registry.json")
        == live_web_firewall_registry(root) else "FAIL"}
    checks["PLAN_HANDOFF_GOLD_FIREWALL"] = _gold_and_handoff_controls()
    graph = _read(root, "evaluations/t26/production_graph.json")
    graph_check = _graph(graph)
    checks["PRODUCTION_DAG"] = graph_check
    authority = _read(root, "evaluations/t26/authority_graph.json")
    nodes = authority["nodes"]
    candidate_gold = [name for name in ("planner", "orchestrator", "executive_router",
                                         "capability_dispatcher", "capabilities",
                                         "verification_layer", "completion_gate")
                      if nodes[name]["gold_access"]]
    checks["AUTHORITY_EDGES"] = {
        "status": "PASS" if set(nodes) == set(graph["nodes"]) and
        not candidate_gold and all(not node["may_perform_external_action"]
                                   for node in nodes.values()) else "FAIL",
        "external_action_authority": False,
        "candidate_gold_edges": candidate_gold}
    checks["PRIVATE_STORE_CONTROLS"] = _private_storage_controls(root)
    checks["MEMORY_SCOPE_ISOLATION"] = memory_controls()
    checks["CODE_DISPOSABLE_SANDBOX"] = code_controls()
    from t25_protocol.doctor import _live_web_controls
    t25_web = _live_web_controls(root)
    t26_web = negative_controls(root, exclusions)
    checks["LIVE_WEB_FIREWALL"] = {
        "status": "PASS" if t25_web["all_denied"] and
        t25_web["control_count"] >= 10 and t26_web["status"] == "PASS" else "FAIL",
        "t25_inherited_controls": t25_web["control_count"],
        "t26_controls": t26_web["controls"],
        "pre_candidate_filtering": True}
    checks["GIT_LEAK_SCAN"] = _leak_scan(root)
    from t25_protocol.exclusions import load_exclusion_sources
    inherited = load_exclusion_sources(
        root, _read(root, "evaluations/t25/t25_exclusion_sources.json"))
    checks["HISTORICAL_EXCLUSIONS"] = {
        "status": "PASS" if design()["historical_private_rows_accessed"] == 0 and
        len(inherited["case_ids"]) > 0 and len(inherited["exact_queries"]) > 0 and
        (root / "evaluations/t25/t23_exposed_sealed_anchor.json").is_file() and
        (root / "evaluations/t25/t24_sealed_evaluated_anchor.json").is_file()
        else "FAIL", "t22_raw_blind_rows_accessed": 0,
        "t23_exposed_rows_used": 0, "t24_private_rows_accessed": 0,
        "t25_private_rows_accessed": 0,
        "inherited_hash_only_case_ids": len(inherited["case_ids"]),
        "inherited_hash_only_queries": len(inherited["exact_queries"])}
    for name, filename in (("NATIVE_INTEGRATION", "native_smoke_report.json"),
                           ("REHEARSALS", "rehearsal_report.json"),
                           ("PROTECTION", "protection_report.json"),
                           ("TEST_GATE", "test_gate_report.json")):
        report = _read(root, f"evaluations/t26/{filename}")
        checks[name] = {"status": report["status"]}
    checks["TOKENS"] = {"status": "PASS" if
        design()["construction_token"] == "T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION" and
        design()["evaluation_token"] == "T26_ONE_SHOT_OFFICIAL_EVALUATION" else "FAIL"}
    checks.update(_construction_readiness_checks(root))
    if require_freeze:
        freeze = _read(root, "evaluations/t26/preconstruction_freeze.json")
        checks["FREEZE"] = verify_freeze(root, freeze)
    status = "PASS" if all(v["status"] == "PASS" for v in checks.values()) else "FAIL"
    return {"schema_version": "t26-protocol-doctor-v3",
            "artifact": "T26_PROTOCOL_DOCTOR_REPORT",
            "status": status, "check_count": len(checks), "checks": checks,
            "verdict": "T26_PRODUCTION_PROTOCOL_DOCTOR_PASS" if status == "PASS"
            else "T26_PRODUCTION_PROTOCOL_DOCTOR_FAIL"}


def _construction_readiness_checks(root: Path) -> dict:
    """Expanded construction-readiness checks (authorization sections 7-32)."""
    root = Path(root)
    checks: dict[str, dict] = {}
    try:
        from .construction import (LEDGER_BINDING_FIELDS,
                                   protocol_hashes as _protocol_hashes)
        from .exclusion import build_historical_exclusion_document

        historical = build_historical_exclusion_document(root)
        checks["CONSTRUCTION_EXCLUSION_MODEL"] = {
            "status": "PASS" if len(historical["dimensions"]) == 9
            and all(entry["population"] >= 0 for entry in
                    historical["dimensions"].values()) else "FAIL",
            "dimension_count": len(historical["dimensions"]),
            "exclusion_root": historical["exclusion_root"]}
        hashes = _protocol_hashes(root)
        checks["LEDGER_BINDINGS"] = {
            "status": "PASS" if len(hashes) == 7 and
            len(LEDGER_BINDING_FIELDS) == 24 and
            all(len(value) == 64 for value in hashes.values()) else "FAIL",
            "ledger_binding_count": len(LEDGER_BINDING_FIELDS),
            "protocol_identity_count": len(hashes)}
    except Exception as exc:
        for name in ("CONSTRUCTION_EXCLUSION_MODEL", "LEDGER_BINDINGS"):
            if name not in checks:
                checks[name] = {"status": "FAIL", "error": type(exc).__name__}
    checks["T25_PRIVATE_ORACLE_INTERFACE"] = _oracle_interface_check(root)
    checks["FIXTURE_OPTIONALITY_POLICY"] = _fixture_optionality_policy_check(root)
    checks["ZERO_FIXTURE_CONTRACT_CONTROLS"] = _zero_fixture_contract_check(root)
    checks["CONSTRUCTION_CONTRACT_ENUMERATOR"] = _contract_enumerator_check(root)
    checks["NEGATIVE_GATE_CONTROLS"] = _negative_controls_check(root)
    checks["PRIVATE_MANIFEST_AND_SEAL_REHEARSAL"] = _manifest_seal_rehearsal_check(root)
    checks["POST_LEDGER_FAILURE_SEMANTICS"] = _failure_semantics_check(root)
    checks["ONE_SHOT_CONTROLS"] = _one_shot_controls_check(root)
    checks["CONSTRUCTION_LIFECYCLE_REHEARSALS"] = _lifecycle_rehearsal_check(root)
    checks["REAL_ENTRYPOINT_FIXTURE_POLICY_BINDING"] = (
        _real_entrypoint_fixture_policy_check(root))
    checks["ZERO_FIXTURE_LIFECYCLE"] = _zero_fixture_lifecycle_check(root)
    checks["FIXTURE_BEARING_LIFECYCLE"] = _fixture_bearing_lifecycle_check(root)
    checks["PRODUCTION_GRAPH_CONSTRUCTION_NODES"] = _production_graph_nodes_check(root)
    return checks


def _oracle_interface_check(root: Path) -> dict:
    from .construction import _synthetic_oracle_result, synthetic_private_bundle
    from .oracle import verify_oracle_result

    cases, gold, fixtures = synthetic_private_bundle(0)
    result = _synthetic_oracle_result(root, cases, gold, fixtures)
    verification = verify_oracle_result(result)
    tampered = dict(result)
    tampered["overall_overlap_count"] = 1
    try:
        verify_oracle_result(tampered)
        tamper_refused = False
    except ValueError:
        tamper_refused = True
    return {"status": "PASS" if verification["status"] == "PASS" and
            tamper_refused and verification["t25_private_rows_exposed_to_t26"] == 0
            else "FAIL", "t25_private_rows_exposed": 0,
            "tamper_refused": tamper_refused,
            "dimensions_bound": len(result["dimensions"])}


def _contract_enumerator_check(root: Path) -> dict:
    from .construction import CONTRACT_LEAF_REQUIREMENTS

    leaf_count = len(CONTRACT_LEAF_REQUIREMENTS)
    stable = len(set(CONTRACT_LEAF_REQUIREMENTS)) == leaf_count
    return {"status": "PASS" if stable and leaf_count >= 50 else "FAIL",
            "leaf_count": leaf_count, "enumerator_frozen": stable}


def _fixture_optionality_policy_check(root: Path) -> dict:
    from .construction import load_fixture_policy, protocol_hashes
    from .freeze import build_freeze

    try:
        policy = load_fixture_policy(root)
        frozen = build_freeze(root)
        component = next((entry for entry in frozen["components"]
                          if entry["path"] ==
                          "evaluations/t26/private_storage_policy.json"), None)
        identities = protocol_hashes(root)
        ok = (policy["auxiliary_private_fixtures_required"] is False
              and policy["auxiliary_private_fixtures_optional"] is True
              and component is not None
              and component["sha256"] ==
              policy["private_storage_policy_sha256"]
              and identities["private_storage_policy_sha256"] ==
              policy["private_storage_policy_sha256"])
        return {
            "status": "PASS" if ok else "FAIL",
            "auxiliary_private_fixtures_required":
                policy["auxiliary_private_fixtures_required"],
            "auxiliary_private_fixtures_optional":
                policy["auxiliary_private_fixtures_optional"],
            "policy_frozen": component is not None,
            "policy_sha256": policy["private_storage_policy_sha256"],
        }
    except Exception as exc:
        return {"status": "FAIL", "error": type(exc).__name__}


def _zero_fixture_contract_check(root: Path) -> dict:
    from .construction import run_zero_fixture_contract_controls

    report = run_zero_fixture_contract_controls(root)
    return {
        "status": report["status"],
        "leaf_count": report["positive"]["total_leaves"],
        "pass_count": report["positive"]["pass_count"],
        "fail_count": report["positive"]["fail_count"],
        "unverifiable_count": report["positive"]["unverifiable_count"],
        "fixture_leaf": report["positive"]["fixture_leaf"],
        "negative_fixture_leaf": report["negative"]["fixture_leaf"],
        "negative_failed_leaves": report["negative"]["failed_leaves"],
    }


def _negative_controls_check(root: Path) -> dict:
    from .construction import run_negative_gate_controls

    report = run_negative_gate_controls(root)
    return {"status": report["status"], "control_count": report["control_count"],
            "not_refused": report["not_refused"],
            "material": report["material"]}


def _manifest_seal_rehearsal_check(root: Path) -> dict:
    from .construction import recompute_manifest_roots

    manifest_probe = {
        "construction_ledger_identity": {
            "ledger_sha256": "2" * 64,
            "ledger_root": "3" * 64,
            "ledger_semantic_sha256": "4" * 64,
            "ledger_state_at_manifest": "GATE_PASS",
            "attempt": 1,
        },
        "artifacts": [
            {"logical_id": "probe/inputs", "classification": "REAL_BLIND_INPUT",
             "sha256": "0" * 64, "byte_size": 1, "schema": "probe-v1"},
            {"logical_id": "probe/gold", "classification": "REAL_BLIND_GOLD",
             "sha256": "1" * 64, "byte_size": 1, "schema": "probe-v1"}],
        "counts_by_class": {"REAL_BLIND_GOLD": 1, "REAL_BLIND_INPUT": 1},
    }
    roots = recompute_manifest_roots(manifest_probe)
    independent = recompute_manifest_roots(manifest_probe)
    roots_match = roots == independent and len(roots) == 4
    import tempfile

    from .lifecycle import T26PrivateStore

    with tempfile.TemporaryDirectory(prefix="t26-doctor-manifest-") as tmp:
        store_root = Path(tmp) / "T26-STORE-01"
        store = T26PrivateStore(store_root, root)
        meta = store.write_once("probe/artifact.json", {"probe": True})
        verify = store.verify()
        tamper_detected = False
        (store.path("probe/artifact.json")).write_text("{}\n", encoding="utf-8")
        try:
            store.verify()
        except ValueError:
            tamper_detected = True
        ok = (roots_match and verify["missing_artifacts"] == 0 and
              verify["hash_mismatches"] == 0 and
              verify["classification_mismatches"] == 0 and
              verify["root_mismatches"] == 0 and tamper_detected)
        return {"status": "PASS" if ok else "FAIL",
                "root_count": len(roots), "store_verify_artifacts": verify["artifact_count"],
                "store_tamper_detected": tamper_detected}


def _failure_semantics_check(root: Path) -> dict:
    import tempfile

    from .construction import (CONSTRUCTION_TOKEN, ConstructionLedgerError,
                               T26ConstructionLedger)
    from .freeze import build_freeze

    with tempfile.TemporaryDirectory(prefix="t26-doctor-failure-") as tmp:
        store_root = Path(tmp) / "T26-STORE-01"
        from .lifecycle import T26PrivateStore

        store = T26PrivateStore(store_root, root)
        frozen = build_freeze(root)
        bindings = {
            "experiment": "t26", "attempt": 1, "authorization": CONSTRUCTION_TOKEN,
            "material_mode": "REAL_BLIND", "namespace": "t26",
            "store_identity": "T26-STORE-01",
            "execution_checkout_commit": "e" * 64,
            "execution_checkout_tree": "f" * 64,
            "candidate_commit": frozen["candidate_commit"],
            "candidate_tree": frozen["candidate_tree"],
            "runtime_root": frozen["runtime_root"],
            "preconstruction_freeze_sha256": frozen["freeze_sha256"],
            "freeze_component_count": frozen["component_count"],
            "freeze_component_root": frozen["component_root"],
            "freeze_root": frozen["freeze_root"],
            "execution_contract_sha256": "0" * 64,
            "authority_graph_sha256": "0" * 64,
            "production_graph_sha256": "0" * 64,
            "metric_registry_sha256": "0" * 64,
            "private_storage_policy_sha256": "0" * 64,
            "qualification_exclusion_sha256": "0" * 64,
            "live_web_firewall_registry_sha256": "0" * 64,
            "historical_exclusion_identity": "T26_HISTORICAL_EXCLUSIONS",
            "historical_exclusion_root": "1" * 64,
        }
        try:
            ledger = T26ConstructionLedger.create_exclusive(store, bindings,
                                                            CONSTRUCTION_TOKEN)
            chain = ledger.verify_event_chain()
            ledger.fail("LEDGER_CREATED", "RehearsalInjectedFailure", {"probe": True})
            failed_chain = ledger.verify_event_chain()
            second_refused = False
            try:
                T26ConstructionLedger.create_exclusive(store, bindings,
                                                       CONSTRUCTION_TOKEN)
            except ConstructionLedgerError:
                second_refused = True
            retry_refused = False
            try:
                ledger.advance("MATERIALIZED")
            except ConstructionLedgerError:
                retry_refused = True
            ok = (chain["event_chain_valid"] and failed_chain["event_chain_valid"]
                  and ledger.state == "FAILED" and second_refused and retry_refused
                  and ledger.document["attempt"] == 1)
            return {"status": "PASS" if ok else "FAIL",
                    "ledger_final_state": ledger.state,
                    "attempt_count": ledger.document["attempt"],
                    "retry_count": 0, "second_attempt_refused": second_refused,
                    "retry_refused": retry_refused}
        except Exception as exc:
            return {"status": "FAIL", "error": type(exc).__name__}


def _one_shot_controls_check(root: Path) -> dict:
    from .construction import ATTEMPT, CONSTRUCTION_TOKEN, NAMESPACE, STORE_ID

    alias_refused = False
    try:
        require_token(CONSTRUCTION_TOKEN + "-v2", "construction")
    except PermissionError:
        alias_refused = True
    return {"status": "PASS" if alias_refused and ATTEMPT == 1 and
            NAMESPACE == "t26" and STORE_ID == "T26-STORE-01" else "FAIL",
            "token_alias_refused": alias_refused,
            "real_construction_authorized": False}


def _lifecycle_rehearsal_check(root: Path) -> dict:
    report_path = root / "evaluations/t26/construction_rehearsal_report.json"
    if not report_path.is_file():
        return {"status": "FAIL", "error": "construction_rehearsal_report absent"}
    report = _read(root, "evaluations/t26/construction_rehearsal_report.json")
    return {"status": report.get("status", "FAIL"),
            "runs": report.get("run_count", 0),
            "semantic_diffs": report.get("semantic_diffs", {})}


def _real_entrypoint_fixture_policy_check(root: Path) -> dict:
    report_path = root / "evaluations/t26/construction_rehearsal_report.json"
    if not report_path.is_file():
        return {"status": "FAIL", "error": "construction_rehearsal_report absent"}
    report = _read(root, "evaluations/t26/construction_rehearsal_report.json")
    zero = report.get("zero_fixture_lifecycle", {})
    policy = report.get("zero_fixture_contract_controls", {}).get("policy", {})
    ok = (zero.get("status") == "PASS"
          and zero.get("fixture_count") == 0
          and zero.get("contract_leaf_total") == 62
          and zero.get("contract_leaf_pass_count") == 62
          and policy.get("auxiliary_private_fixtures_optional") is True)
    return {"status": "PASS" if ok else "FAIL",
            "zero_fixture_real_entrypoint_sealed": zero.get("status") == "PASS",
            "fixtures_optional_bound":
                policy.get("auxiliary_private_fixtures_optional") is True}


def _zero_fixture_lifecycle_check(root: Path) -> dict:
    report = _read(root, "evaluations/t26/construction_rehearsal_report.json")
    zero = report.get("zero_fixture_lifecycle", {})
    ok = (zero.get("status") == "PASS"
          and zero.get("fixture_count") == 0
          and zero.get("ledger_state") == "SEALED"
          and zero.get("ledger_event_count") == 6
          and zero.get("contract_leaf_total") == 62
          and zero.get("contract_leaf_pass_count") == 62
          and zero.get("gate_check_count") == 24
          and zero.get("store_verify") == "PASS"
          and zero.get("publication_leak_gate") == "PASS")
    return {"status": "PASS" if ok else "FAIL", **zero}


def _fixture_bearing_lifecycle_check(root: Path) -> dict:
    report = _read(root, "evaluations/t26/construction_rehearsal_report.json")
    fixture = report.get("fixture_bearing_lifecycle", {})
    ok = fixture.get("status") == "PASS" and fixture.get("run_count") == 2
    return {"status": "PASS" if ok else "FAIL",
            "run_count": fixture.get("run_count", 0)}


def _production_graph_nodes_check(root: Path) -> dict:
    from .contract import production_graph

    graph = production_graph()
    present = set(graph["nodes"])
    required_any = {"authoring_validation", "historical_exclusion_oracle",
                    "construction_ledger", "private_materialization",
                    "construction_audit", "construction_gate", "private_manifest",
                    "holdout_seal", "publication_leak_gate",
                    "public_construction_receipt", "evaluation_ledger",
                    "evaluator", "scorer", "public_evaluation_receipt"}
    return {"status": "PASS" if graph["missing_producers"] == 0 and
            graph["dangling_edges"] == 0 and graph["production_stubs"] == 0
            and graph["unclassified_artifacts"] == 0 and
            required_any <= present else "FAIL",
            "node_count": len(present)}
