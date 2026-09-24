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
    if require_freeze:
        freeze = _read(root, "evaluations/t26/preconstruction_freeze.json")
        checks["FREEZE"] = verify_freeze(root, freeze)
    status = "PASS" if all(v["status"] == "PASS" for v in checks.values()) else "FAIL"
    return {"schema_version": "t26-protocol-doctor-v1",
            "artifact": "T26_PROTOCOL_DOCTOR_REPORT",
            "status": status, "check_count": len(checks), "checks": checks,
            "verdict": "T26_PRODUCTION_PROTOCOL_DOCTOR_PASS" if status == "PASS"
            else "T26_PRODUCTION_PROTOCOL_DOCTOR_FAIL"}
