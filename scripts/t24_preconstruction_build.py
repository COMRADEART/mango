"""T24 preconstruction build: generate every public-safe evaluations/t24 artifact.

Writes (in dependency order) the author specification, capability registry,
candidate identity, publication policy, artifact classification, private-store
config, T23 exposed-sealed anchor, public qualification data, firewall
fingerprint sets, live-web firewall registry, exclusion-source registry,
preregistered floors, production metric registry, provider config, master
contract, evaluation graph, and author lock. No real T24 blind material exists
or is created anywhere; every artifact is hash/commitment/registry content.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.executive.router_v2 import route_request  # noqa: E402
from t21_protocol.util import sha256_file, sha256_json  # noqa: E402
from t23_protocol.author import GOLD_ONLY, INPUT_FIELDS, ROUTE_IDS, _row  # noqa: E402
from t23_protocol.contract import canonical  # noqa: E402

from t24_protocol import classification, freeze, policy, store  # noqa: E402
from t24_protocol import lock as lock_module  # noqa: E402
from t24_protocol.anchor_t23 import DIMENSIONS, build_anchor  # noqa: E402
from t24_protocol.author import load_spec  # noqa: E402
from t24_protocol.contract import (QUALIFICATION_NAMESPACE, T23_CONSTRUCTION_COMMIT,  # noqa: E402
                                   master_contract_document, validate_t24_contract)
from t24_protocol.firewall import build_firewall_document, text_fingerprint  # noqa: E402
from t24_protocol.graph import NODE_ROLES  # noqa: E402
from t24_protocol.scorer import production_registry  # noqa: E402

T24 = ROOT / "evaluations" / "t24"
T23 = ROOT / "evaluations" / "t23"
FIREPRINTS = T24 / "firewall_fingerprints"
QUALIFICATION = T24 / "qualification"
QUALIFICATION_LABEL_COUNT = 80
FINGERPRINT_SET_SCHEMA = "t24-fingerprint-set-v1"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, document: Any, *, sort: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, sort_keys=sort, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def _git_jsonl(path: str) -> list[dict[str, Any]]:
    out = subprocess.run(["git", "show", f"{T23_CONSTRUCTION_COMMIT}:{path}"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return [json.loads(line) for line in out.decode("utf-8").splitlines() if line.strip()]


def _binding(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}


def fingerprint_set_document(artifact: str, fingerprints: list[str],
                             *, note: str | None = None) -> dict[str, Any]:
    unique = sorted(set(fingerprints))
    for value in unique:
        if len(value) != 64:
            raise ValueError(f"non-fingerprint value in {artifact}")
    document = {"schema_version": FINGERPRINT_SET_SCHEMA, "artifact": artifact,
                "experiment": "t24", "raw_values_included": False,
                "fingerprint_count": len(unique), "fingerprints": unique}
    if note:
        document["note"] = note
    return document


def _author_specification() -> dict[str, Any]:
    spec = json.loads((T23 / "author_specification.json").read_text(encoding="utf-8"))
    spec["schema_version"] = "t24-author-spec-v1"
    spec["artifact"] = "T24_PROSPECTIVE_AUTHOR_SPECIFICATION"
    spec["experiment"] = "t24"
    spec["status"] = "PRECONSTRUCTION_ONLY"
    spec["construction_authorized"] = False
    spec["case_id_prefix"] = "t24"
    spec["taxonomy"]["case_id_pattern"] = r"^t24-[a-z_]+-[0-9]{4}$"
    spec["taxonomy"]["route_ids"] = list(ROUTE_IDS)
    spec["author_entry"] = "t24_protocol.author:author_cases"
    spec["blind_material_source"] = "t24-private://T24-STORE-01/t24/suites/inputs.jsonl"
    spec["shadow_material_source"] = \
        "t24-private://T24-REHEARSAL-STORE-01/t24-shadow-disposable/suites/inputs.jsonl"
    spec["historical_exclusions"] = sorted(set(
        spec["historical_exclusions"]) | {
        "T21R16_OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE",
        "T21R17_VALID_CAPABILITY_FAILURE",
        "T22_OFFICIAL_EVALUATION_PASS",
        "T23_SEALED_PUBLICATION_EXCLUDED"})
    pool = dict(spec["source_pool_constraints"])
    pool["no_t23_exposed_material"] = True
    pool["no_t24_public_qualification_reuse"] = True
    spec["source_pool_constraints"] = pool
    spec["storage_mode"] = "PRIVATE_ARTIFACT_STORE_OUTSIDE_PUBLIC_GIT"
    spec["privacy"]["real_blind_corpus"] = "PRIVATE_OFFLINE_STORE"
    spec["exact_design"]["total_rows"] = 1280
    if spec["case_id_prefix"] != "t24" or len(spec["families"]) != 16:
        raise ValueError("T24 author specification assembly failed")
    return spec


def _capability_registry() -> dict[str, Any]:
    registry = json.loads((T23 / "capability_registry.json").read_text(encoding="utf-8"))
    registry["artifact"] = "T24_CAPABILITY_REGISTRY"
    registry["experiment"] = "t24"
    registry["schema_version"] = "t24-capability-registry-v1"
    registry["frozen_from_t23"] = True
    core = {key: value for key, value in registry.items() if key != "registry_sha256"}
    registry["registry_sha256"] = sha256_json(core)
    registry["registry_sha256_basis"] = "sha256_json(document minus registry_sha256)"
    return registry


def _candidate_identity() -> dict[str, Any]:
    prior = json.loads((T23 / "candidate_identity.json").read_text(encoding="utf-8"))
    candidate = dict(prior["t23_candidate"])
    document = {"schema_version": "t24-candidate-identity-v1",
                "artifact": "T24_CANDIDATE_IDENTITY", "experiment": "t24",
                "t24_candidate": candidate,
                "unchanged_from_t23_candidate": True,
                "changed_from_t23_candidate": False,
                "candidate_changed": False,
                "source": "evaluations/t23/candidate_identity.json:t23_candidate",
                "t23_candidate_commit": prior["t23_candidate"]["candidate_commit"],
                "t23_candidate_tree": prior["t23_candidate"]["candidate_tree"]}
    return document


def _qualification() -> dict[str, Any]:
    from t23_protocol.author import author_cases

    spec = load_spec()
    labels = tuple(f"T24 public qualification record PQN-{index:04d}"
                   for index in range(QUALIFICATION_LABEL_COUNT))
    inputs, gold = author_cases(labels, namespace=QUALIFICATION_NAMESPACE, spec=spec,
                                attachment_path="evaluations/t24/qualification/qualification_document.txt")
    document = ("T24 public qualification document. Project-owned non-blind fixture, "
                "permanently excluded from all future T24 constructions.\n")
    QUALIFICATION.mkdir(parents=True, exist_ok=True)
    (QUALIFICATION / "qualification_document.txt").write_text(document, encoding="utf-8")
    _write_jsonl(QUALIFICATION / "qualification_inputs.jsonl", inputs)
    _write_jsonl(QUALIFICATION / "qualification_gold.jsonl", gold)
    _write_jsonl(QUALIFICATION / "qualification_exclusions.jsonl",
                 [{"case_id": row["case_id"], "query": row["candidate_input"]["query"]}
                  for row in inputs])
    mismatches = []
    reasons_matched = 0
    for row, expected in zip(inputs, gold):
        decision = route_request(row["candidate_input"])
        if decision["route_id"] != expected["expected_route"]:
            mismatches.append({"case_id": row["case_id"],
                               "expected": expected["expected_route"],
                               "observed": decision["route_id"]})
        if decision["reason_code"] == expected["expected_reason"]:
            reasons_matched += 1
    if mismatches:
        raise ValueError(f"T24 qualification routing mismatches: {mismatches[:5]}")
    report = {"schema_version": "t24-qualification-report-v1",
              "artifact": "T24_QUALIFICATION_REPORT", "experiment": "t24",
              "rows": len(inputs), "family_count": len({row["family"] for row in gold}),
              "route_agreement": 1.0, "route_mismatch_count": len(mismatches),
              "reason_agreement": round(reasons_matched / len(inputs), 6),
              "router_entry": "sciencemath.executive.router_v2:route_request",
              "material": "PUBLIC_SAFE_PERMANENTLY_EXCLUDED",
              "status": "PASS"}
    _write(QUALIFICATION / "qualification_report.json", report)
    return report


def _firewall_fingerprint_sets() -> dict[str, Path]:
    chunks = _git_jsonl("rag/gk_holdout_t23/chunks.jsonl")
    attachment = subprocess.run(
        ["git", "show", f"{T23_CONSTRUCTION_COMMIT}:documents/private_pool_attachment.txt"],
        cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    texts = [chunk["text"] for chunk in chunks] + [attachment]
    # The exposed T23 corpus carries no populated content_hash fields, so content
    # bindings are the sha256 of the exposed raw text itself — exactly what the
    # firewall's normalize() computes for a live result that reports no hash.
    content = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
    t23_content = fingerprint_set_document(
        "T23_CONTENT_FINGERPRINTS", content,
        note="sha256 of the exposed T23 chunk and attachment raw text (commitments, "
             "never the text itself)")
    t23_text = fingerprint_set_document(
        "T23_TEXT_FINGERPRINTS", [text_fingerprint(text) for text in texts],
        note="normalized text fingerprints of exposed T23 chunk and attachment text")
    historical = []
    prior = json.loads((ROOT / "evaluations/t22/prior_exclusion.json").read_text(encoding="utf-8"))
    for milestone in prior["milestones"].values():
        for dimension in milestone.get("dimensions", {}).values():
            historical.extend(dimension.get("fingerprints", []))
    anchor_t22 = json.loads((ROOT / "evaluations/t23/t22_exclusion_anchor.json")
                            .read_text(encoding="utf-8"))
    for dimension in anchor_t22.get("fingerprints", {}).values():
        historical.extend(dimension if isinstance(dimension, list) else
                          dimension.get("fingerprints", []))
    remediation = json.loads((ROOT / "evaluations/t22/remediation_exclusion.json")
                             .read_text(encoding="utf-8"))
    for dimension in remediation["dimensions"].values():
        historical.extend(dimension["fingerprints"] if isinstance(dimension, dict)
                          else dimension)
    historical_set = fingerprint_set_document(
        "T24_HISTORICAL_FINGERPRINTS", historical,
        note="union of T21/T22 milestone, T22 anchor, and remediation fingerprints")
    qualification = []
    for line in (T23 / "nonblind_qualification_inputs.jsonl").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            qualification.append(text_fingerprint(row["query"]))
    for line in (QUALIFICATION / "qualification_exclusions.jsonl").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            qualification.append(text_fingerprint(json.loads(line)["query"]))
    qualification_set = fingerprint_set_document(
        "T24_QUALIFICATION_FINGERPRINTS", qualification,
        note="normalized text fingerprints of T23 and T24 qualification queries")
    paths = {}
    for name, document in (("t23_content_fingerprints.json", t23_content),
                           ("t23_text_fingerprints.json", t23_text),
                           ("historical_fingerprints.json", historical_set),
                           ("qualification_fingerprints.json", qualification_set)):
        path = FIREPRINTS / name
        _write(path, document)
        paths[name] = path
    return paths


def _exclusion_registry(anchor_path: Path) -> dict[str, Any]:
    rehearsal_set = {"schema_version": "t24-dimension-fingerprint-set-v1",
                     "artifact": "T24_DISPOSABLE_REHEARSAL_FINGERPRINTS",
                     "experiment": "t24", "raw_values_included": False,
                     "dimensions": {}, "dimension_counts": {},
                     "note": "populated only after the two disposable rehearsals complete"}
    _write(T24 / "rehearsal_exclusion_fingerprints.json", rehearsal_set)
    document = {"schema_version": "t24-exclusion-sources-v2",
                "artifact": "T24_CONSTRUCTION_EXCLUSION_SOURCES", "experiment": "t24",
                "raw_values_included": False,
                "required_milestones": json.loads(
                    (ROOT / "evaluations/t22/prior_exclusion.json").read_text(
                        encoding="utf-8"))["milestone_order"],
                "additional_anchors": ["T22_SEALED", "T23_EXPOSED_SEALED"],
                "dimensions": list(DIMENSIONS),
                "sources": {
                    "t21_historical": {"kind": "milestone_registry",
                                       **_binding(ROOT / "evaluations/t22/prior_exclusion.json")},
                    "t22_anchor": {"kind": "hash_only_anchor",
                                   **_binding(ROOT / "evaluations/t23/t22_exclusion_anchor.json")},
                    "t23_exposed_sealed": {"kind": "exposed_sealed_anchor",
                                           **_binding(anchor_path)},
                    "open_development": {"kind": "remediation",
                                         **_binding(ROOT / "evaluations/t22/remediation_exclusion.json")},
                    "t24_public_qualification": {
                        "kind": "qualification_rows",
                        **_binding(QUALIFICATION / "qualification_exclusions.jsonl")},
                    "t24_disposable_rehearsal": {
                        "kind": "t24_fingerprint_set",
                        **_binding(T24 / "rehearsal_exclusion_fingerprints.json")},
                }}
    return document


def _evaluation_graph() -> dict[str, Any]:
    locator = "t24-private://T24-STORE-01/t24"
    private = {
        "construction_inputs": (f"{locator}/suites/inputs.jsonl", "PRIVATE_BLIND",
                                [], "t24_protocol.author:author_cases"),
        "construction_gold": (f"{locator}/suites/gold.jsonl", "PRIVATE_BLIND",
                              ["construction_inputs"], "t24_protocol.author:author_cases"),
        "construction_family_suites": (f"{locator}/suites/families", "PRIVATE_BLIND",
                                       ["construction_inputs", "construction_gold"],
                                       "t24_protocol.construction:write_suites"),
        "holdout_corpus": (f"{locator}/corpus", "PRIVATE_BLIND",
                           ["construction_inputs"],
                           "t24_protocol.construction:write_corpus"),
        "construction_ledger": (f"{locator}/construction_run_ledger", "PRIVATE_EVALUATION",
                                [], "t24_protocol.ledgers:T24ConstructionLedger"),
        "construction_audits": (f"{locator}/construction_audits", "PRIVATE_EVALUATION",
                                ["construction_family_suites", "holdout_corpus"],
                                "t24_protocol.construction:run_construction_audits"),
        "construction_gate_node": (f"{locator}/construction_gate", "PRIVATE_EVALUATION",
                                   ["construction_audits", "construction_ledger"],
                                   "t24_protocol.gates:run_construction_gate"),
        "construction_manifest": (f"{locator}/private_holdout_manifest", "PRIVATE_EVALUATION",
                                  ["construction_gate_node"],
                                  "t24_protocol.manifest:build_private_manifest"),
        "holdout_seal": (f"{locator}/holdout_seal", "PRIVATE_EVALUATION",
                         ["construction_manifest", "construction_ledger"],
                         "t24_protocol.seal:seal_holdout"),
        "gold_firewall_verification": (f"{locator}/gold_firewall_verification",
                                       "PRIVATE_EVALUATION",
                                       ["holdout_corpus", "construction_gold"],
                                       "t24_protocol.evaluation:verify_gold_firewall"),
        "router_decisions": (f"{locator}/evaluation/router_decisions.jsonl",
                             "PRIVATE_EVALUATION", ["holdout_seal", "construction_inputs"],
                             "t24_protocol.evaluation:evaluate_router"),
        "selected_capability_execution": (
            f"{locator}/evaluation/selected_capability_execution.jsonl", "PRIVATE_EVALUATION",
            ["holdout_seal", "construction_inputs"],
            "t24_protocol.evaluation:evaluate_capability"),
        "candidate_outputs": (f"{locator}/evaluation/candidate_outputs.jsonl",
                              "PRIVATE_EVALUATION",
                              ["router_decisions", "selected_capability_execution"],
                              "t24_protocol.provider:T24ProductionRouterProvider"),
        "router_evaluator": (f"{locator}/evaluation/router_evaluator.jsonl",
                             "PRIVATE_EVALUATION", ["candidate_outputs", "construction_gold"],
                             "t24_protocol.evaluation:evaluate_router"),
        "capability_evaluator": (f"{locator}/evaluation/capability_evaluator.jsonl",
                                 "PRIVATE_EVALUATION", ["candidate_outputs"],
                                 "t24_protocol.evaluation:evaluate_capability"),
        "raw_results": (f"{locator}/evaluation/raw_results.jsonl", "PRIVATE_EVALUATION",
                        ["candidate_outputs", "construction_gold", "router_evaluator",
                         "capability_evaluator"],
                        "t24_protocol.evaluation:combine_raw"),
        "protected_t22_metric_evidence": (
            f"{locator}/evaluation/protected_t22_metric_evidence.json", "PRIVATE_EVALUATION",
            ["construction_gold"],
            "t24_protocol.evaluation:protected_t22_metric_evidence"),
        "protected_t22_floor_evidence": (
            f"{locator}/evaluation/protected_t22_floor_evidence.json", "PRIVATE_EVALUATION",
            ["protected_t22_metric_evidence"],
            "t24_protocol.evaluation:protected_t22_floor_evidence"),
        "router_metric_evidence": (f"{locator}/evaluation/router_metric_evidence.json",
                                   "PRIVATE_EVALUATION", ["raw_results"],
                                   "t24_protocol.scorer:score_router"),
        "router_floor_evidence": (f"{locator}/evaluation/router_floor_evidence.json",
                                  "PRIVATE_EVALUATION", ["router_metric_evidence"],
                                  "t24_protocol.scorer:score_router"),
        "combined_holdout_results": (f"{locator}/evaluation/holdout_results.json",
                                     "PRIVATE_EVALUATION",
                                     ["router_floor_evidence", "capability_evaluator",
                                      "protected_t22_floor_evidence"],
                                     "t24_protocol.evaluation:combine_results"),
        "evaluation_provenance": (f"{locator}/evaluation/evaluation_provenance.json",
                                  "PRIVATE_EVALUATION", ["combined_holdout_results"],
                                  "t24_protocol.evaluation:build_provenance"),
        "evaluation_ledger": (f"{locator}/evaluation_run_ledger", "PRIVATE_EVALUATION",
                              ["holdout_seal"], "t24_protocol.ledgers:T24EvaluationLedger"),
    }
    public = {
        "public_construction_commitment": ("evaluations/t24/construction_public_commitment.json",
                                           ["holdout_seal", "construction_ledger"],
                                           "t24_protocol.manifest:build_public_construction_commitment"),
        "public_manifest_commitment": ("evaluations/t24/manifest_public_commitment.json",
                                       ["construction_manifest"],
                                       "t24_protocol.manifest:build_public_manifest_commitment"),
        "public_construction_receipt": ("evaluations/t24/construction_public_receipt.json",
                                        ["construction_ledger"],
                                        "t24_protocol.ledgers:build_construction_receipt"),
        "public_evaluation_receipt": ("evaluations/t24/evaluation_public_receipt.json",
                                      ["evaluation_ledger", "combined_holdout_results"],
                                      "t24_protocol.ledgers:build_evaluation_receipt"),
    }
    nodes = {}
    for name, (path, classification_value, inputs, producer) in private.items():
        nodes[name] = {"producer": producer, "inputs": inputs, "path": path,
                       "privacy": "PRIVATE", "classification": classification_value}
    for name, (path, inputs, producer) in public.items():
        nodes[name] = {"producer": producer, "inputs": inputs, "path": path,
                       "privacy": "PRIVATE", "classification": "PUBLIC_SAFE"}
    if set(nodes) != set(NODE_ROLES) | set(public):
        raise ValueError("T24 evaluation graph node set mismatch")
    return {"schema_version": "t24-evaluation-graph-v1",
            "artifact": "T24_PRODUCTION_EVALUATION_GRAPH", "experiment": "t24",
            "gates": {"evaluation_cannot_start_before": "SEALED",
                      "promotion_cannot_start_before": "EVALUATED",
                      "one_shot_attempt": 1, "no_retry": True},
            "nodes": dict(sorted(nodes.items()))}


def main() -> None:
    if T24.exists():
        shutil.rmtree(T24)
    T24.mkdir(parents=True)
    spec = _author_specification()
    _write(T24 / "author_specification.json", spec)
    load_spec()
    print("author specification written", flush=True)

    _write(T24 / "capability_registry.json", _capability_registry())
    _write(T24 / "candidate_identity.json", _candidate_identity())
    _write(T24 / "t24_publication_policy.json", policy.publication_policy_document())
    _write(T24 / "t24_artifact_classification.json",
           classification.classification_registry_document())
    _write(T24 / "t24_private_store_config.json", store.store_config_document())
    print("policy/classification/store artifacts written", flush=True)

    _qualification()
    print("public qualification data written (1280 rows, route agreement 1.0)", flush=True)

    anchor = build_anchor(ROOT)
    _write(T24 / "t23_exposed_sealed_anchor.json", anchor)
    print("T23 exposed-sealed anchor written", flush=True)

    sets = _firewall_fingerprint_sets()
    registry = build_firewall_document(
        ROOT,
        t23_anchor_record=_binding(T24 / "t23_exposed_sealed_anchor.json"),
        historical_records=[_binding(sets["historical_fingerprints.json"])],
        qualification_records=[_binding(sets["qualification_fingerprints.json"])],
        t23_content_records=[_binding(sets["t23_content_fingerprints.json"])],
        t23_text_records=[_binding(sets["t23_text_fingerprints.json"])])
    _write(T24 / "live_web_source_firewall_registry.json", registry)
    print("live-web firewall registry written", flush=True)

    _write(T24 / "t24_exclusion_sources.json", _exclusion_registry(T24 / "t23_exposed_sealed_anchor.json"))
    print("exclusion source registry written", flush=True)

    floors = json.loads((T23 / "router_metric_registry.json").read_text(encoding="utf-8"))
    floors["artifact"] = "T24_PREREGISTERED_ROUTER_METRIC_REGISTRY"
    floors["experiment"] = "t24"
    floors["schema_version"] = "t24-router-metric-registry-v1"
    floors["frozen_from_t23"] = True
    floors["t23_exposed_reuse_allowed"] = False
    _write(T24 / "router_metric_registry.json", floors)
    _write(T24 / "production_router_metric_registry.json", production_registry())
    print("router metric registries written", flush=True)

    provider = json.loads((T23 / "production_provider_config.json").read_text(encoding="utf-8"))
    provider["schema_version"] = "t24-production-provider-config-v1"
    provider["artifact"] = "T24_PRODUCTION_PROVIDER_CONFIG"
    provider["experiment"] = "t24"
    provider["provider_entry"] = "t24_protocol.provider:T24ProductionRouterProvider"
    provider["web_firewall_mandatory"] = True
    provider["firewall_registry"] = "evaluations/t24/live_web_source_firewall_registry.json"
    provider["web_real_policy"] = "LIVE_FREE_SOURCE_BACKED_ONLY_FIREWALL_FILTERED"
    provider["private_store_identity"] = "T24-STORE-01"
    _write(T24 / "production_provider_config.json", provider)
    print("production provider config written", flush=True)

    contract_document = master_contract_document()
    validate_t24_contract(contract_document)
    _write(T24 / "t24_master_contract.json", contract_document)
    print("master contract written", flush=True)

    graph = _evaluation_graph()
    _write(T24 / "production_evaluation_graph.json", graph)
    print("production evaluation graph written (27 nodes)", flush=True)

    _write(T24 / "author_lock.json", lock_module.expected_lock())
    print("author lock written", flush=True)

    import t24_protocol.graph as graph_module

    report = graph_module.validate_graph(graph)
    if report["status"] != "PASS":
        raise ValueError(f"T24 graph validation failed: {report}")
    lock_module.verify_lock()
    validate_t24_contract(json.loads((T24 / "t24_master_contract.json").read_text(encoding="utf-8")))
    print("BUILD COMPLETE: contract, graph, lock all verified", flush=True)


if __name__ == "__main__":
    main()