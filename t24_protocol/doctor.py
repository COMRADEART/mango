"""T24 production protocol doctor (section 33): fail-closed verification battery.

Covers the author lock, contract, publication policy, classification, private
store, evaluation graph, provider, live-web firewall, T23 anchor, exclusions,
one-shot state machines, Git blind-blob scanning, freeze, qualification,
rehearsals, and the historical lifecycle. Every negative control must refuse.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciencemath.executive.router_v2 import validate_router_contract
from sciencemath.knowledge.corpus import load_corpus
from sciencemath.web.fixture_provider import FixtureCorpus, FixtureSearchProvider
from t21_protocol.doctor import run_doctor as run_prior_doctor
from t21_protocol.util import read_json, sha256_file
from t23_protocol.lifecycle import verify_lifecycle

from . import freeze as freeze_module
from .anchor_t23 import verify_anchor
from .author import author_cases, load_spec
from .classification import load_classification_registry, validate_classification_registry
from .context import CONSTRUCTION_TOKENS, EVALUATION_TOKENS
from .contract import CANDIDATE_COMMIT, CANDIDATE_TREE, enumerate_leaf_requirements
from .contract import load_t24_contract
from .construction import audit_blindness, audit_uniqueness
from .exclusions import audit_exclusions, load_exclusion_sources
from .firewall import (FirewallSearchProvider, LiveWebSourceFirewall, load_registry,
                       text_fingerprint)
from .gates import run_publication_gate
from .graph import load_graph, validate_graph
from .leakscan import scan_public_git
from .lock import verify_lock
from .policy import load_policy, path_forbidden
from .provider import T24ProductionRouterProvider, decision_parity
from .scorer import REGISTRY, production_registry
from .store import PrivateArtifactStore, store_config_document

ROOT = Path(__file__).resolve().parents[1]
T23_CONSTRUCTION_COMMIT = "aa613c30483f697295f6f993319e37fd45b07f12"


def _section(status: bool, **details: Any) -> dict[str, Any]:
    return {"status": "PASS" if status else "FAIL", **details}


def _git_show(commit: str, path: str) -> bytes:
    import subprocess

    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT,
                          capture_output=True, check=True).stdout


def _private_storage_controls(root: Path) -> dict[str, Any]:
    """Section 28: twelve private-storage negative controls; every one must refuse."""
    from .ledgers import T24ConstructionLedger, T24EvaluationLedger
    from .manifest import build_private_manifest

    results: dict[str, bool] = {}

    def must_refuse(name: str, action) -> None:
        try:
            action()
        except Exception:
            results[name] = True
        else:
            results[name] = False

    base = Path(TemporaryDirectory(prefix="t24-doctor-").name)
    must_refuse("store_inside_public_git_refused",
                lambda: PrivateArtifactStore(Path(root) / "inside-doctor-store",
                                             store_identity="T24-DOCTOR-X",
                                             namespace="t24-shadow-disposable"))
    store = PrivateArtifactStore(base / "s1", store_identity="T24-DOCTOR-STORE",
                                 namespace="t24-shadow-disposable")
    must_refuse("unknown_role_fail_closed",
                lambda: store.write("demo1", {"a": 1}, role="definitely_unknown_role",
                                    schema_version="x-v1"))
    store.write("demo2", {"b": 2}, role="suite_inputs", schema_version="t24-blind-suite-v1")
    must_refuse("duplicate_write_refused",
                lambda: store.write("demo2", {"b": 3}, role="suite_inputs",
                                    schema_version="t24-blind-suite-v1"))
    artifact = store.root / "artifacts" / "demo2.artifact"
    original = artifact.read_bytes()
    artifact.write_bytes(original.replace(b"2", b"9"))
    must_refuse("blind_blob_mutation_refused", lambda: store.read("demo2"))
    artifact.write_bytes(original)
    artifact.write_bytes(original + b"\n")
    must_refuse("byte_size_drift_refused", lambda: store.read("demo2"))
    artifact.write_bytes(original)
    must_refuse("real_namespace_requires_token",
                lambda: PrivateArtifactStore(base / "s2", store_identity="T24-DOCTOR-STORE",
                                             namespace="t24"))
    ledger_store = PrivateArtifactStore(base / "s3", store_identity="T24-DOCTOR-STORE",
                                        namespace="t24-shadow-disposable")
    bindings = {
        "material_mode": "SYNTHETIC_DISPOSABLE", "real_namespace": "t24-shadow-disposable",
        "starting_preconstruction_commit": "0" * 64,
        "starting_preconstruction_tree": "0" * 64,
        "candidate_commit": "1" * 64, "candidate_tree": "1" * 64,
        "preconstruction_freeze_sha256": "2" * 64, "component_root": "2" * 64,
        "freeze_root": "2" * 64, "construction_contract_sha256": "3" * 64,
        "author_lock_sha256": "4" * 64}

    def two_ledgers() -> None:
        T24ConstructionLedger.create_exclusive(
            store=ledger_store, bindings=bindings,
            authorization="T24_SYNTHETIC_DISPOSABLE_CONSTRUCTION")
        T24ConstructionLedger.create_exclusive(
            store=ledger_store, bindings=bindings,
            authorization="T24_SYNTHETIC_DISPOSABLE_CONSTRUCTION")

    must_refuse("ledger_duplicate_creation_refused", two_ledgers)
    ledger_store = PrivateArtifactStore(base / "s6", store_identity="T24-DOCTOR-STORE",
                                        namespace="t24-shadow-disposable")
    ledger = T24ConstructionLedger.create_exclusive(
        store=ledger_store, bindings=bindings,
        authorization="T24_SYNTHETIC_DISPOSABLE_CONSTRUCTION")
    must_refuse("ledger_state_skip_refused", lambda: ledger.advance("GATE_PASS"))
    must_refuse("ledger_advance_after_fail_refused",
                lambda: (ledger.fail("doctor control"), ledger.advance("MATERIALIZED")))
    must_refuse("seal_before_gate_refused",
                lambda: build_private_manifest(
                    ledger_store, identity={"candidate_commit": "x"},
                    audit_hashes={"blindness": "5" * 64, "exclusion": "6" * 64,
                                  "uniqueness": "7" * 64}))
    eval_store = PrivateArtifactStore(base / "s4", store_identity="T24-DOCTOR-STORE",
                                      namespace="t24-shadow-disposable")

    def two_eval_ledgers() -> None:
        for _ in range(2):
            T24EvaluationLedger.create_exclusive(
                store=eval_store, material_mode="SYNTHETIC",
                seal_commitment_sha256="0" * 64, private_artifact_root="1" * 64,
                gold_firewall_verified=True)

    must_refuse("evaluation_ledger_duplicate_creation_refused", two_eval_ledgers)
    must_refuse("immutable_replace_refused",
                lambda: store.replace("demo2", {"b": 4}))

    workspace_proven = None
    if freeze_module.FREEZE_PATH.is_file():
        probe_store = PrivateArtifactStore(base / "s5", store_identity="T24-DOCTOR-STORE",
                                           namespace="t24-shadow-disposable")
        probe_store.write("suite_probe", {"x": 1}, role="suite_inputs",
                          schema_version="t24-blind-suite-v1")
        from .workspace import create_private_workspace, dispose_workspace

        workspace, report = create_private_workspace(root, probe_store, purpose="doctor")
        workspace_proven = {"outside_repository": report["outside_repository"],
                            "mounted_count": report["mounted_count"]}
        dispose_workspace(workspace)
    return {"control_count": len(results),
            "all_refused": all(results.values()) and len(results) == 12,
            "controls": results, "workspace_outside_repository": workspace_proven}


def _live_web_controls(root: Path) -> dict[str, Any]:
    """Section 29: live-web negative controls against the frozen firewall registry."""
    registry = load_registry()
    firewall = LiveWebSourceFirewall(registry, root)
    results: dict[str, Any] = {}

    def denied(name: str, query: str, result: Any, rules: set[str]) -> None:
        filtered = firewall.filter(query, [result])
        normalized = firewall.normalize(result)
        allowed, fired = firewall.evaluate(query, normalized)
        results[name] = (not filtered and not allowed and fired in rules)

    t23_inputs = [json.loads(line) for line in
                  _git_show(T23_CONSTRUCTION_COMMIT, "evaluations/t23/suites/inputs.jsonl")
                  .decode("utf-8").splitlines() if line.strip()]
    t23_chunks = [json.loads(line) for line in
                  _git_show(T23_CONSTRUCTION_COMMIT, "rag/gk_holdout_t23/chunks.jsonl")
                  .decode("utf-8").splitlines() if line.strip()]
    denied("t23_exposed_query_denied", t23_inputs[0]["candidate_input"]["query"],
           {"url": "https://example.org/a", "title": "x", "text": "unrelated"},
           {"QUERY_FINGERPRINT_T23_EXPOSED"})
    denied("t23_repo_url_denied", "safe query",
           {"url": "https://github.com/COMRADEART/mango/blob/main/evaluations/t23/suites/inputs.jsonl",
            "title": "x", "text": "unrelated"}, {"REPOSITORY_IDENTITY"})
    denied("t23_raw_url_denied", "safe query",
           {"url": "https://raw.githubusercontent.com/COMRADEART/mango/main/x.txt",
            "title": "x", "text": "unrelated"}, {"REPOSITORY_IDENTITY", "URI_PREFIX"})
    denied("t23_chunk_text_denied", "safe query",
           {"url": "https://example.org/b", "title": "x", "text": t23_chunks[0]["text"]},
           {"T23_CONTENT_HASH", "T23_TEXT_FINGERPRINT"})
    denied("t23_content_hash_denied", "safe query",
           {"url": "https://example.org/c", "title": "x", "text": "unrelated",
            "content_hash": hashlib.sha256(t23_chunks[0]["text"].encode("utf-8")).hexdigest()},
           {"T23_CONTENT_HASH"})
    qualification = (root / "evaluations" / "t23" / "nonblind_qualification_inputs.jsonl")
    rows = [json.loads(line) for line in qualification.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    first = rows[0]
    qualification_query = first.get("query", first.get("candidate_input", {}).get("query", ""))
    if not qualification_query:
        raise ValueError("T23 qualification row carries no query")
    denied("qualification_text_denied", "safe query",
           {"url": "https://example.org/d", "title": "x",
            "text": qualification_query},
           {"QUALIFICATION_FINGERPRINT"})
    results["historical_fingerprint_denied"] = _historical_rule_control(registry, root)
    results["unfirewalled_web_provider_refused"] = _provider_firewall_mandatory_control()
    return {"control_count": len(results), "all_denied": all(results.values()),
            "controls": results, "firewall_counters": dict(firewall.counters)}


def _historical_rule_control(registry: dict[str, Any], root: Path) -> bool:
    """Prove HISTORICAL_FINGERPRINT fires via a temporary synthetic binding."""
    with TemporaryDirectory(prefix="t24-doctor-hist-") as temp:
        temp_root = Path(temp)
        fingerprint_set = {"schema_version": "t24-fingerprint-set-v1",
                           "artifact": "T24_DOCTOR_SYNTHETIC_SET", "raw_values_included": False,
                           "fingerprints": [text_fingerprint("doctor historical control text")]}
        path = temp_root / "synthetic_fingerprints.json"
        path.write_text(json.dumps(fingerprint_set, sort_keys=True) + "\n", encoding="utf-8")
        modified = json.loads(json.dumps(registry))
        for binding in ("t23_content_bindings", "t23_text_bindings", "t23_query_bindings",
                        "qualification_bindings"):
            modified[binding] = []
        modified["historical_bindings"] = [{"path": str(path), "sha256": sha256_file(path)}]
        firewall = LiveWebSourceFirewall(modified, temp_root)
        allowed, fired = firewall.evaluate("safe query", firewall.normalize(
            {"url": "https://example.org/e", "title": "x",
             "text": "Doctor historical control text"}))
        return not allowed and fired == "HISTORICAL_FINGERPRINT"


def _provider_firewall_mandatory_control() -> bool:
    from t23_protocol.provider import ProductionDispatchError

    try:
        T24ProductionRouterProvider(
            ROOT / "rag" / "gk_corpus",
            web_provider=FixtureSearchProvider(FixtureCorpus([], query_time="2026-09-23")),
            workspace_mode="SYNTHETIC_DISPOSABLE")
    except ProductionDispatchError:
        return True
    except Exception:
        return False
    return False


def doctor_labels() -> tuple[str, ...]:
    """Doctor-local labels: distinct from rehearsal and qualification labels so the
    exclusion audit stays collision-free once rehearsal fingerprints are registered."""
    return tuple(f"T24 doctor parity record DCT-{index:04d}" for index in range(80))


def _t23_terminal_lifecycle(root: Path) -> dict[str, Any]:
    """Interpret T23's terminal lifecycle from T23's own committed artifacts.

    T23's registry entry is frozen at PRECONSTRUCTION: the shared registry was
    last committed at the T23 preconstruction milestone and T23's post-
    preconstruction phases were never recorded in it. T23 must not be
    evaluated, so the entry stays as the authenticated historical record. The
    frozen verify_lifecycle therefore refuses, because T23's registered real
    paths exist at HEAD — placed there by the adjudicated post-seal publication
    event (construction commit aa613c3, merged to main). This check grounds
    that terminal state independently: the refusal must be exactly the
    adjudicated publication state (registry binding intact, real paths fully
    present, publication commit an ancestor of HEAD), T23's own construction
    and manifest records must be intact, and the contract's exclusion
    adjudication must agree with the exposed-sealed anchor.
    """
    import subprocess

    root = root.resolve()
    try:
        registry = read_json(root / "evaluations/t23/experiment_lifecycle_registry.json")
        entry = registry["experiments"]["t23"]
        if entry["state"] != "PRECONSTRUCTION":
            raise ValueError(f"unexpected t23 registry state: {entry['state']}")
        t23_contract = read_json(root / entry["contract"])
        values = t23_contract["values"]
        real_paths = values["real_t23_paths"]
        if not real_paths or not all(isinstance(p, str) for p in real_paths):
            raise ValueError("t23 registered real paths missing or malformed")

        t24_contract = load_t24_contract(
            root / "evaluations/t24/t24_master_contract.json")
        exclusion = t24_contract.get("values.t23_exclusion")
        anchor = read_json(root / exclusion["anchor_artifact"])
        published = anchor["t23_construction"]
        adjudication_agrees = (
            exclusion["t23_must_not_be_evaluated"] is True
            and exclusion["reuse_allowed"] is False
            and exclusion["exposed_construction_commit"] == published["commit"]
            and exclusion["exposed_construction_tree"] == published["tree"])

        graph = read_json(root / entry["evaluation_graph"])
        graph_paths = [node["path"] for node in graph["nodes"].values()]
        registered = sorted(set(real_paths) | set(graph_paths))
        present = [relative for relative in registered
                   if (root / relative).exists()]
        absent = [relative for relative in registered
                  if not (root / relative).exists()]

        # The adjudicated publication event introduced exactly the 30 blind
        # files of construction commit aa613c3 (construction-side artifacts:
        # corpus, suites, manifest, ledger, audits, HOLDOUT_FROZEN). The
        # present registered paths must be exactly the registered subset of
        # that commit's introduced set, byte-unchanged since, and the absent
        # registered paths (evaluation-side outputs, never produced because
        # T23's evaluation was refused) must all remain absent.
        published_files = subprocess.run(
            ["git", "diff-tree", "-r", "--name-only", "--no-commit-id",
             published["commit"]], cwd=root, capture_output=True, text=True,
            check=True).stdout.splitlines()
        # Some registered paths are directories (suites, the corpus root); a
        # registered path counts as published when it is, or contains, one of
        # the commit's introduced files.
        published_set = set(published_files)
        expected_present = sorted(
            relative for relative in registered
            if relative in published_set
            or any(file.startswith(relative + "/") for file in published_files))
        rewritten = subprocess.run(
            ["git", "diff", "--name-only", published["commit"], "HEAD", "--",
            *expected_present], cwd=root, capture_output=True, text=True,
            check=True).stdout.splitlines()
        fully_present = (sorted(present) == expected_present
                         and not rewritten
                         and absent == sorted(set(registered) - set(expected_present)))

        # The only failing disjunct in verify_lifecycle's PRECONSTRUCTION
        # branch must be the present real paths; the freeze binding itself
        # stays intact (artifact name + preconstruction zero-exposure value).
        t23_freeze = read_json(root / entry["preconstruction_freeze"])
        freeze_binding_intact = (t23_freeze.get("artifact") == "T23_PRECONSTRUCTION_FREEZE"
                                 and t23_freeze.get("real_t23_exposure") == 0)

        t23_ledger = read_json(root / "evaluations/t23/construction_run_ledger.json")
        ledger_states = [event.get("state") for event in t23_ledger["events"]]
        construction_record_intact = (
            t23_ledger["artifact"] == "T23_CONSTRUCTION_LEDGER"
            and t23_ledger["state"] == "GATE_PASS"
            and ledger_states[-1] == "GATE_PASS")
        t23_manifest = read_json(root / "evaluations/t23/holdout_manifest.json")
        manifest_intact = t23_manifest["artifact"] == "T23_HOLDOUT_MANIFEST"

        tree = subprocess.run(["git", "show", "--quiet", "--format=%T",
                               published["commit"]], cwd=root,
                              capture_output=True, text=True, check=True).stdout.strip()
        commit_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", published["commit"], "HEAD"],
            cwd=root, capture_output=True, text=True).returncode == 0
        publication_event_verified = (commit_ancestor and tree == published["tree"])

        passed = (freeze_binding_intact and fully_present
                  and construction_record_intact and manifest_intact
                  and adjudication_agrees and publication_event_verified)
        return {"status": "PASS" if passed else "FAIL",
                "interpretation": "SEALED_THEN_PUBLICATION_EXPOSED",
                "registered_paths": len(registered), "present_paths": len(present),
                "absent_evaluation_paths": len(absent),
                "freeze_binding_intact": freeze_binding_intact,
                "construction_record_intact": construction_record_intact,
                "manifest_intact": manifest_intact,
                "adjudication_agrees": adjudication_agrees,
                "publication_event_verified": publication_event_verified}
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        return {"status": "FAIL", "interpretation": "SEALED_THEN_PUBLICATION_EXPOSED",
                "reason": str(exc)}


def run_t24_doctor(root: Path, *, run_prior: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    t24 = root / "evaluations" / "t24"
    lock = verify_lock(t24 / "author_lock.json")
    contract = load_t24_contract(t24 / "t24_master_contract.json")
    graph = validate_graph(load_graph(t24 / "production_evaluation_graph.json"))
    if read_json(REGISTRY) != production_registry():
        raise ValueError("T24 production router metric registry drift")
    spec = load_spec()
    leaves = enumerate_leaf_requirements(contract.document)
    policy_document = load_policy()
    classification_document = load_classification_registry()
    store_config = read_json(t24 / "t24_private_store_config.json")
    if store_config != store_config_document():
        raise ValueError("T24 private store config drift")
    exclusion_registry = read_json(t24 / "t24_exclusion_sources.json")
    forbidden = load_exclusion_sources(root, exclusion_registry)
    anchor_report = verify_anchor(root)
    web = FirewallSearchProvider(FixtureSearchProvider(FixtureCorpus([], query_time="2026-09-23")),
                                 LiveWebSourceFirewall(load_registry(), root))
    provider = T24ProductionRouterProvider(root / "rag" / "gk_corpus", web_provider=web,
                                           workspace_mode="SYNTHETIC_DISPOSABLE")
    init_rows = provider.rows_executed
    labels = doctor_labels()
    inputs, gold = author_cases(labels, namespace="t24-doctor",
                                spec=spec, attachment_path="documents/private_attachment")
    sample = [row for row in inputs if "insufficient_evidence" in row["case_id"]][:3]
    parity = decision_parity(sample, provider.generate(sample))
    provider_config = read_json(t24 / "production_provider_config.json")
    blind = audit_blindness(real=False, namespace="t24-doctor", labels=labels,
                            inputs=inputs, private_provenance=None)
    unique = audit_uniqueness(inputs)
    corpus = load_corpus(root / "rag" / "gk_corpus")
    exclusion_report = audit_exclusions(root, exclusion_registry, inputs, gold, corpus)
    private_controls = _private_storage_controls(root)
    live_controls = _live_web_controls(root)
    freeze_report = None
    if freeze_module.FREEZE_PATH.is_file():
        freeze_report = _freeze_identity(root)
    checks = {
        "T24_AUTHOR_LOCK": _section(lock["status"] == "PASS" and lock["missing_bindings"] == 0,
                                    binding_count=lock["binding_count"]),
        "T24_CANDIDATE_BINDING": _section(
            lock["candidate_commit"] == CANDIDATE_COMMIT
            and lock["candidate_tree"] == CANDIDATE_TREE
            and contract.get("values.candidate_identity.unchanged_from_t23_candidate") is True),
        "T24_PRODUCTION_EXPERIMENT_REGISTRY": _section(
            contract.get("values.authorization") == "T24_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
            and "t24" in CONSTRUCTION_TOKENS and "t24" in EVALUATION_TOKENS),
        "T24_CONSTRUCTION_CONTRACT": _section(
            spec["construction_authorized"] is False and spec["status"] == "PRECONSTRUCTION_ONLY"
            and contract.get("values.t23_exclusion.t23_must_not_be_evaluated") is True),
        "T24_CONTRACT_LEAVES": _section(
            len(leaves) > 0 and all(leaf["requirement_id"].startswith("T24-CON-")
                                    for leaf in leaves),
            leaf_requirement_count=len(leaves)),
        "T24_PUBLICATION_POLICY": _section(
            policy_document["frozen_policy"]["REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION"] is False
            and policy_document["frozen_policy"]["PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED"] == 0),
        "T24_ARTIFACT_CLASSIFICATION": _section(
            validate_classification_registry(classification_document)),
        "T24_PRIVATE_STORE_CONFIG": _section(
            store_config["real_namespace_requires_construction_token"] is True
            and private_controls["all_refused"] and private_controls["control_count"] == 12,
            controls=private_controls),
        "T24_EVALUATION_GRAPH": _section(graph["status"] == "PASS",
                                         producer_count=graph["producer_count"]),
        "T24_PRODUCTION_PROVIDER": _section(
            init_rows == 0 and parity["status"] == "PASS"
            and provider_config["provider_entry"] == provider.provider_id,
            initialization_rows=init_rows, parity=parity),
        "T24_LIVE_WEB_FIREWALL": _section(
            live_controls["all_denied"] and live_controls["control_count"] >= 7,
            controls=live_controls),
        "T23_EXPOSED_SEALED_ANCHOR": _section(anchor_report["status"] == "PASS",
                                              anchor=anchor_report),
        "T24_EXCLUSION_SOURCES": _section(
            len(forbidden) == 9 and exclusion_report["status"] == "PASS",
            violations=exclusion_report["violations"],
            forbidden_counts=exclusion_report["forbidden_counts"]),
        "T24_BLINDNESS_CHECKER": _section(
            blind["status"] == "PASS" and unique["status"] == "PASS"),
        "T24_GIT_BLIND_BLOB_SCAN": _section(
            scan_public_git(root, blind_hashes=set())["status"] == "PASS"
            and not any(path_forbidden(path) for path in _tracked_paths(root))),
        "T24_STATE_MACHINE_ONE_SHOT": _section(
            all(private_controls["controls"][name] for name in (
                "ledger_duplicate_creation_refused", "ledger_state_skip_refused",
                "ledger_advance_after_fail_refused",
                "evaluation_ledger_duplicate_creation_refused",
                "immutable_replace_refused"))),
        "T24_PRECONSTRUCTION_FREEZE": _section(
            freeze_report is not None and freeze_report["status"] == "PASS",
            freeze=freeze_report),
        "T24_QUALIFICATION_DATA": _section(
            (t24 / "qualification" / "qualification_inputs.jsonl").is_file()
            and read_json(t24 / "qualification" / "qualification_report.json")["status"] == "PASS"),
        "T24_SHADOW_LIFECYCLE": _shadow_lifecycle_check(root),
        "EXECUTIVE_ROUTER": validate_router_contract(),
    }
    lifecycle_t22 = verify_lifecycle(root, "t22")
    lifecycle_t23 = verify_lifecycle(root, "t23")
    t23_terminal = _t23_terminal_lifecycle(root)
    checks["HISTORICAL_LIFECYCLE_CONSISTENCY"] = _section(
        lifecycle_t22["status"] == "PASS" and t23_terminal["status"] == "PASS",
        t22=lifecycle_t22["status"],
        t23_terminal=t23_terminal, t23_frozen_verifier=lifecycle_t23)
    base = run_prior_doctor(root, experiment="t22") if run_prior else None
    if base is not None:
        other_failures = sorted(name for name, check in base["checks"].items()
                                if name != "real_paths"
                                and check.get("status") not in {"PASS", "VERIFIED"})
        legacy_paths = base["checks"]["real_paths"]
        checks["T21_PROTOCOL_DOCTOR"] = _section(
            not other_failures and lifecycle_t22["status"] == "PASS"
            and len(legacy_paths["present"]) == lifecycle_t22["present_paths"],
            frozen_verdict=base["verdict"], other_failures=other_failures)
    publication_gate = run_publication_gate(root, blind_hashes=set())
    checks["T24_PUBLICATION_GATE"] = _section(
        publication_gate["official_evaluation_allowed"] is True,
        scan_status=publication_gate["status"],
        blind_blob_count=publication_gate["blind_blob_count"])
    passed = all(check.get("status") == "PASS" for check in checks.values())
    return {"schema_version": "t24-production-doctor-v1",
            "artifact": "T24_PRODUCTION_PROTOCOL_DOCTOR", "experiment": "t24",
            "checks": checks, "base_verdict": base["verdict"] if base else "NOT_RUN",
            "status": "PASS" if passed else "FAIL",
            "verdict": "T24_PRODUCTION_PROTOCOL_DOCTOR_PASS" if passed
            else "T24_PRODUCTION_PROTOCOL_DOCTOR_FAIL"}


def _tracked_paths(root: Path) -> list[str]:
    import subprocess

    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def _freeze_identity(root: Path) -> dict[str, Any]:
    from .freeze import load_freeze

    freeze = load_freeze()
    drifted = []
    for component in freeze["components"]:
        path = root / component["path"]
        if not path.is_file() or sha256_file(path) != component["sha256"]:
            drifted.append(component["path"])
    return {"status": "PASS" if not drifted else "FAIL",
            "component_count": freeze["component_count"], "drifted": drifted[:5],
            "frozen_policy": freeze["frozen_policy"]}


def _shadow_lifecycle_check(root: Path) -> dict[str, Any]:
    path = root / "evaluations" / "t24" / "production_shadow_lifecycle_report.json"
    if not path.is_file():
        return _section(False, reason="rehearsal report absent")
    report = read_json(path)
    return _section(report["status"] == "PASS"
                    and len(report["runs"]) == 2
                    and not any(report["comparisons"].values()),
                    comparisons=report["comparisons"])