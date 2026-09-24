"""T25 preconstruction build: generate every public-safe evaluations/t25 artifact.

Writes (in dependency order) the author specification, capability registry,
candidate identity (the NEW §18 candidate ba34f7b), publication policy,
artifact classification, private-store config, the T23 exposed-sealed anchor
copy, the T24 sealed-evaluated anchor, public qualification data, firewall
fingerprint sets, live-web firewall registry (T24 material included), exclusion-
source registry, preregistered floors, production metric registry, provider
config, master contract, evaluation graph, and author lock. No real T25 blind
material exists or is created anywhere; every artifact is hash/commitment/
registry content, and T24's private material is never opened (§3/§13).
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
from t23_protocol.author import GOLD_ONLY, INPUT_FIELDS, ROUTE_IDS  # noqa: E402

from t24_protocol.anchor_t23 import build_anchor as build_t23_anchor  # noqa: E402
from t25_protocol import classification, freeze, policy, store  # noqa: E402
from t25_protocol import lock as lock_module  # noqa: E402
from t25_protocol.anchor_t24 import build_anchor as build_t24_anchor  # noqa: E402
from t25_protocol.author import load_spec  # noqa: E402
from t25_protocol.contract import (CANDIDATE_COMMIT, QUALIFICATION_NAMESPACE,  # noqa: E402
                                   master_contract_document, validate_t25_contract)
from t25_protocol.firewall import build_firewall_document, text_fingerprint  # noqa: E402
from t25_protocol.scorer import production_registry  # noqa: E402

T25 = ROOT / "evaluations" / "t25"
T23 = ROOT / "evaluations" / "t23"
T24 = ROOT / "evaluations" / "t24"
FIREPRINTS = T25 / "firewall_fingerprints"
QUALIFICATION = T25 / "qualification"
QUALIFICATION_LABEL_COUNT = 80
FINGERPRINT_SET_SCHEMA = "t25-fingerprint-set-v1"


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


def _git_jsonl(commit: str, path: str) -> list[dict[str, Any]]:
    out = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT,
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
                "experiment": "t25", "raw_values_included": False,
                "fingerprint_count": len(unique), "fingerprints": unique}
    if note:
        document["note"] = note
    return document


def _candidate_identity() -> dict[str, Any]:
    """The NEW T25 candidate (§18): the authorized remediation commit ba34f7b."""
    from t25_protocol.contract import CANDIDATE_TREE, RUNTIME_ROOT

    full = subprocess.run(["git", "rev-parse", CANDIDATE_COMMIT], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    tree = subprocess.run(["git", "rev-parse", f"{CANDIDATE_COMMIT}^{{tree}}"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    parent = subprocess.run(["git", "rev-parse", f"{CANDIDATE_COMMIT}^"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    if (full != CANDIDATE_COMMIT or tree != CANDIDATE_TREE
            or parent != "d64160bf0ebb715a6a30647d06e420b7dde6b24e"):
        raise ValueError("T25 candidate commit identity drift")
    t22 = _read(ROOT / "evaluations/t22/runtime_freeze.json")
    components = sorted({"src/sciencemath/executive/router_v2.py",
                         "src/sciencemath/executive/skills.py",
                         "src/sciencemath/executive/runner.py",
                         *t22["component_sha256"]})
    mapping = {}
    for relative in components:
        working = (ROOT / relative).read_bytes()
        blob = subprocess.run(["git", "show", f"{full}:{relative}"], cwd=ROOT,
                              capture_output=True, check=True).stdout
        if working != blob:
            raise ValueError(f"T25 candidate runtime byte drift: {relative}")
        mapping[relative] = hashlib.sha256(working).hexdigest()
    if sha256_json(mapping) != RUNTIME_ROOT:
        raise ValueError("T25 candidate runtime_root drift")
    t24 = _read(T24 / "candidate_identity.json")["t24_candidate"]
    candidate = {"candidate_commit": full, "candidate_tree": tree,
                 "candidate_parent": parent, "runtime_root": RUNTIME_ROOT,
                 "runtime_component_sha256": mapping,
                 "runtime_component_count": len(mapping),
                 "unchanged_from_t23_candidate": False,
                 "unchanged_from_t24_candidate": False,
                 "new_candidate_authorized_by": "T25 authorization section 18",
                 "changed_runtime_components": ["src/sciencemath/executive/runner.py"]}
    if candidate["candidate_commit"] in {t24["candidate_commit"]}:
        raise ValueError("T25 candidate must differ from the frozen T24 candidate")
    return {"schema_version": "t25-candidate-identity-v1",
            "artifact": "T25_CANDIDATE_IDENTITY", "experiment": "t25",
            "t25_candidate": candidate,
            "unchanged_from_t23_candidate": False,
            "unchanged_from_t24_candidate": False,
            "candidate_changed": True,
            "source": "authorized §8 remediation commit on t25-preconstruction",
            "t24_candidate_commit": t24["candidate_commit"],
            "t24_candidate_tree": t24["candidate_tree"]}


def _author_specification() -> dict[str, Any]:
    spec = json.loads((T23 / "author_specification.json").read_text(encoding="utf-8"))
    spec["schema_version"] = "t25-author-spec-v1"
    spec["artifact"] = "T25_PROSPECTIVE_AUTHOR_SPECIFICATION"
    spec["experiment"] = "t25"
    spec["status"] = "PRECONSTRUCTION_ONLY"
    spec["construction_authorized"] = False
    spec["case_id_prefix"] = "t25"
    spec["taxonomy"]["case_id_pattern"] = r"^t25-[a-z_]+-[0-9]{4}$"
    spec["taxonomy"]["route_ids"] = list(ROUTE_IDS)
    spec["author_entry"] = "t25_protocol.author:author_cases"
    spec["blind_material_source"] = "t25-private://T25-STORE-01/t25/suites/inputs.jsonl"
    spec["shadow_material_source"] = \
        "t25-private://T25-REHEARSAL-STORE-01/t25-shadow-disposable/suites/inputs.jsonl"
    spec["historical_exclusions"] = sorted(set(
        spec["historical_exclusions"]) | {
        "T21R16_OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE",
        "T21R17_VALID_CAPABILITY_FAILURE",
        "T22_OFFICIAL_EVALUATION_PASS",
        "T23_SEALED_PUBLICATION_EXCLUDED",
        "T24_SEALED_EVALUATED"})
    pool = dict(spec["source_pool_constraints"])
    pool["no_t23_exposed_material"] = True
    pool["no_t24_sealed_material"] = True
    pool["no_t24_private_material_opened"] = True
    pool["no_t25_public_qualification_reuse"] = True
    spec["source_pool_constraints"] = pool
    spec["storage_mode"] = "PRIVATE_ARTIFACT_STORE_OUTSIDE_PUBLIC_GIT"
    spec["privacy"]["real_blind_corpus"] = "PRIVATE_OFFLINE_STORE"
    spec["exact_design"]["total_rows"] = 1280
    if spec["case_id_prefix"] != "t25" or len(spec["families"]) != 16:
        raise ValueError("T25 author specification assembly failed")
    return spec


def _capability_registry() -> dict[str, Any]:
    registry = json.loads((T23 / "capability_registry.json").read_text(encoding="utf-8"))
    registry["artifact"] = "T25_CAPABILITY_REGISTRY"
    registry["experiment"] = "t25"
    registry["schema_version"] = "t25-capability-registry-v1"
    registry["frozen_from_t23"] = True
    core = {key: value for key, value in registry.items() if key != "registry_sha256"}
    registry["registry_sha256"] = sha256_json(core)
    registry["registry_sha256_basis"] = "sha256_json(document minus registry_sha256)"
    return registry


def _qualification() -> dict[str, Any]:
    from t23_protocol.author import author_cases

    spec = load_spec()
    labels = tuple(f"T25 public qualification record PQN-{index:04d}"
                   for index in range(QUALIFICATION_LABEL_COUNT))
    inputs, gold = author_cases(labels, namespace=QUALIFICATION_NAMESPACE, spec=spec,
                                attachment_path="evaluations/t25/qualification/qualification_document.txt")
    document = ("T25 public qualification document. Project-owned non-blind fixture, "
                "permanently excluded from all future T25 constructions.\n")
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
        raise ValueError(f"T25 qualification routing mismatches: {mismatches[:5]}")
    report = {"schema_version": "t25-qualification-report-v1",
              "artifact": "T25_QUALIFICATION_REPORT", "experiment": "t25",
              "rows": len(inputs), "family_count": len({row["family"] for row in gold}),
              "route_agreement": 1.0, "route_mismatch_count": len(mismatches),
              "reason_agreement": round(reasons_matched / len(inputs), 6),
              "router_entry": "sciencemath.executive.router_v2:route_request",
              "material": "PUBLIC_SAFE_PERMANENTLY_EXCLUDED",
              "status": "PASS"}
    _write(QUALIFICATION / "qualification_report.json", report)
    return report


def _firewall_fingerprint_sets() -> dict[str, Path]:
    t23_construction = "aa613c30483f697295f6f993319e37fd45b07f12"
    chunks = _git_jsonl(t23_construction, "rag/gk_holdout_t23/chunks.jsonl")
    attachment = subprocess.run(
        ["git", "show", f"{t23_construction}:documents/private_pool_attachment.txt"],
        cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    texts = [chunk["text"] for chunk in chunks] + [attachment]
    content = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
    t23_content = fingerprint_set_document(
        "T23_CONTENT_FINGERPRINTS", content,
        note="sha256 of the exposed T23 chunk and attachment raw text (commitments, "
             "never the text itself)")
    t23_text = fingerprint_set_document(
        "T23_TEXT_FINGERPRINTS", [text_fingerprint(text) for text in texts],
        note="normalized text fingerprints of exposed T23 chunk and attachment text")
    historical = []
    prior = _read(ROOT / "evaluations/t22/prior_exclusion.json")
    for milestone in prior["milestones"].values():
        for dimension in milestone.get("dimensions", {}).values():
            historical.extend(dimension.get("fingerprints", []))
    anchor_t22 = _read(ROOT / "evaluations/t23/t22_exclusion_anchor.json")
    for dimension in anchor_t22.get("fingerprints", {}).values():
        historical.extend(dimension if isinstance(dimension, list) else
                          dimension.get("fingerprints", []))
    remediation = _read(ROOT / "evaluations/t22/remediation_exclusion.json")
    for dimension in remediation["dimensions"].values():
        historical.extend(dimension["fingerprints"] if isinstance(dimension, dict)
                          else dimension)
    historical_set = fingerprint_set_document(
        "T25_HISTORICAL_FINGERPRINTS", historical,
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
        "T25_QUALIFICATION_FINGERPRINTS", qualification,
        note="normalized text fingerprints of T23 and T25 qualification queries")
    paths = {}
    for name, document in (("t23_content_fingerprints.json", t23_content),
                           ("t23_text_fingerprints.json", t23_text),
                           ("historical_fingerprints.json", historical_set),
                           ("qualification_fingerprints.json", qualification_set)):
        path = FIREPRINTS / name
        _write(path, document)
        paths[name] = path
    return paths


def _exclusion_registry(t23_anchor_path: Path, t24_anchor_path: Path) -> dict[str, Any]:
    rehearsal_set = {"schema_version": "t25-dimension-fingerprint-set-v1",
                     "artifact": "T25_DISPOSABLE_REHEARSAL_FINGERPRINTS",
                     "experiment": "t25", "raw_values_included": False,
                     "dimensions": {}, "dimension_counts": {},
                     "note": "populated only after the two disposable rehearsals complete"}
    _write(T25 / "rehearsal_exclusion_fingerprints.json", rehearsal_set)
    document = {"schema_version": "t25-exclusion-sources-v2",
                "artifact": "T25_CONSTRUCTION_EXCLUSION_SOURCES", "experiment": "t25",
                "raw_values_included": False,
                "required_milestones": _read(
                    ROOT / "evaluations/t22/prior_exclusion.json")["milestone_order"],
                "additional_anchors": ["T22_SEALED", "T23_EXPOSED_SEALED",
                                       "T24_SEALED_EVALUATED"],
                "dimensions": ["case_ids", "entity_identities", "source_ids", "chunk_ids",
                               "exact_queries", "exact_answers", "exact_source_text",
                               "verbatim_attack_wording", "relations"],
                "sources": {
                    "t21_historical": {"kind": "milestone_registry",
                                       **_binding(ROOT / "evaluations/t22/prior_exclusion.json")},
                    "t22_anchor": {"kind": "hash_only_anchor",
                                   **_binding(ROOT / "evaluations/t23/t22_exclusion_anchor.json")},
                    "t23_exposed_sealed": {"kind": "exposed_sealed_anchor",
                                           **_binding(t23_anchor_path)},
                    "t24_sealed_evaluated": {"kind": "sealed_evaluated_anchor",
                                             **_binding(t24_anchor_path)},
                    "open_development": {"kind": "remediation",
                                         **_binding(ROOT / "evaluations/t22/remediation_exclusion.json")},
                    "t25_public_qualification": {
                        "kind": "qualification_rows",
                        **_binding(QUALIFICATION / "qualification_exclusions.jsonl")},
                    "t25_disposable_rehearsal": {
                        "kind": "t25_fingerprint_set",
                        **_binding(T25 / "rehearsal_exclusion_fingerprints.json")},
                }}
    return document


def _evaluation_graph() -> dict[str, Any]:
    from t25_protocol.graph import NODE_ROLES

    locator = "t25-private://T25-STORE-01/t25"
    private = {
        "construction_inputs": (f"{locator}/suites/inputs.jsonl", "PRIVATE_BLIND",
                                [], "t25_protocol.author:author_cases"),
        "construction_gold": (f"{locator}/suites/gold.jsonl", "PRIVATE_BLIND",
                              ["construction_inputs"], "t25_protocol.author:author_cases"),
        "construction_family_suites": (f"{locator}/suites/families", "PRIVATE_BLIND",
                                       ["construction_inputs", "construction_gold"],
                                       "t25_protocol.construction:write_suites"),
        "holdout_corpus": (f"{locator}/corpus", "PRIVATE_BLIND",
                           ["construction_inputs"],
                           "t25_protocol.construction:write_corpus"),
        "construction_ledger": (f"{locator}/construction_run_ledger", "PRIVATE_EVALUATION",
                                [], "t25_protocol.ledgers:T25ConstructionLedger"),
        "construction_audits": (f"{locator}/construction_audits", "PRIVATE_EVALUATION",
                                ["construction_family_suites", "holdout_corpus"],
                                "t25_protocol.construction:run_construction_audits"),
        "construction_gate_node": (f"{locator}/construction_gate", "PRIVATE_EVALUATION",
                                   ["construction_audits", "construction_ledger"],
                                   "t25_protocol.gates:run_construction_gate"),
        "construction_manifest": (f"{locator}/private_holdout_manifest", "PRIVATE_EVALUATION",
                                  ["construction_gate_node"],
                                  "t25_protocol.manifest:build_private_manifest"),
        "holdout_seal": (f"{locator}/holdout_seal", "PRIVATE_EVALUATION",
                         ["construction_manifest", "construction_ledger"],
                         "t25_protocol.seal:seal_holdout"),
        "gold_firewall_verification": (f"{locator}/gold_firewall_verification",
                                       "PRIVATE_EVALUATION",
                                       ["holdout_corpus", "construction_gold"],
                                       "t25_protocol.evaluation:verify_gold_firewall"),
        "router_decisions": (f"{locator}/evaluation/router_decisions.jsonl",
                             "PRIVATE_EVALUATION", ["holdout_seal", "construction_inputs"],
                             "t25_protocol.evaluation:evaluate_router"),
        "selected_capability_execution": (
            f"{locator}/evaluation/selected_capability_execution.jsonl", "PRIVATE_EVALUATION",
            ["holdout_seal", "construction_inputs"],
            "t25_protocol.evaluation:evaluate_capability"),
        "candidate_outputs": (f"{locator}/evaluation/candidate_outputs.jsonl",
                              "PRIVATE_EVALUATION",
                              ["router_decisions", "selected_capability_execution"],
                              "t25_protocol.provider:T25ProductionRouterProvider"),
        "router_evaluator": (f"{locator}/evaluation/router_evaluator.jsonl",
                             "PRIVATE_EVALUATION", ["candidate_outputs", "construction_gold"],
                             "t25_protocol.evaluation:evaluate_router"),
        "capability_evaluator": (f"{locator}/evaluation/capability_evaluator.jsonl",
                                 "PRIVATE_EVALUATION", ["candidate_outputs"],
                                 "t25_protocol.evaluation:evaluate_capability"),
        "raw_results": (f"{locator}/evaluation/raw_results.jsonl", "PRIVATE_EVALUATION",
                        ["candidate_outputs", "construction_gold", "router_evaluator",
                         "capability_evaluator"],
                        "t25_protocol.evaluation:combine_raw"),
        "protected_t22_metric_evidence": (
            f"{locator}/evaluation/protected_t22_metric_evidence.json", "PRIVATE_EVALUATION",
            ["construction_gold"],
            "t25_protocol.evaluation:protected_t22_metric_evidence"),
        "protected_t22_floor_evidence": (
            f"{locator}/evaluation/protected_t22_floor_evidence.json", "PRIVATE_EVALUATION",
            ["protected_t22_metric_evidence"],
            "t25_protocol.evaluation:protected_t22_floor_evidence"),
        "router_metric_evidence": (f"{locator}/evaluation/router_metric_evidence.json",
                                   "PRIVATE_EVALUATION", ["raw_results"],
                                   "t25_protocol.scorer:score_router"),
        "router_floor_evidence": (f"{locator}/evaluation/router_floor_evidence.json",
                                  "PRIVATE_EVALUATION", ["router_metric_evidence"],
                                  "t25_protocol.scorer:score_router"),
        "combined_holdout_results": (f"{locator}/evaluation/holdout_results.json",
                                     "PRIVATE_EVALUATION",
                                     ["router_floor_evidence", "capability_evaluator",
                                      "protected_t22_floor_evidence"],
                                     "t25_protocol.evaluation:combine_results"),
        "evaluation_provenance": (f"{locator}/evaluation/evaluation_provenance.json",
                                  "PRIVATE_EVALUATION", ["combined_holdout_results"],
                                  "t25_protocol.evaluation:build_provenance"),
        "evaluation_ledger": (f"{locator}/evaluation_run_ledger", "PRIVATE_EVALUATION",
                              ["holdout_seal"], "t25_protocol.ledgers:T25EvaluationLedger"),
    }
    public = {
        "public_construction_commitment": ("evaluations/t25/construction_public_commitment.json",
                                           ["holdout_seal", "construction_ledger"],
                                           "t25_protocol.manifest:build_public_construction_commitment"),
        "public_manifest_commitment": ("evaluations/t25/manifest_public_commitment.json",
                                       ["construction_manifest"],
                                       "t25_protocol.manifest:build_public_manifest_commitment"),
        "public_construction_receipt": ("evaluations/t25/construction_public_receipt.json",
                                        ["construction_ledger"],
                                        "t25_protocol.ledgers:build_construction_receipt"),
        "public_evaluation_receipt": ("evaluations/t25/evaluation_public_receipt.json",
                                      ["evaluation_ledger", "combined_holdout_results"],
                                      "t25_protocol.ledgers:build_evaluation_receipt"),
    }
    nodes = {}
    for name, (path, classification_value, inputs, producer) in private.items():
        nodes[name] = {"producer": producer, "inputs": inputs, "path": path,
                       "privacy": "PRIVATE", "classification": classification_value}
    for name, (path, inputs, producer) in public.items():
        nodes[name] = {"producer": producer, "inputs": inputs, "path": path,
                       "privacy": "PRIVATE", "classification": "PUBLIC_SAFE"}
    if set(nodes) != set(NODE_ROLES) | set(public):
        raise ValueError("T25 evaluation graph node set mismatch")
    return {"schema_version": "t25-evaluation-graph-v1",
            "artifact": "T25_PRODUCTION_EVALUATION_GRAPH", "experiment": "t25",
            "gates": {"evaluation_cannot_start_before": "SEALED",
                      "promotion_cannot_start_before": "EVALUATED",
                      "one_shot_attempt": 1, "no_retry": True},
            "nodes": dict(sorted(nodes.items()))}


def main() -> None:
    # The remediation surface (§4-§8) is a COMMIT 1 input, not a build output:
    # preserve its bytes across the stale-artifact wipe below.
    remediation_backup = {
        path.relative_to(ROOT): path.read_bytes()
        for path in sorted((T25 / "remediation").rglob("*")) if path.is_file()
    } if (T25 / "remediation").exists() else {}
    if T25.exists():
        shutil.rmtree(T25, ignore_errors=True)
    if T25.exists():
        for stale in sorted(T25.rglob("*"), reverse=True):
            if stale.is_file():
                stale.unlink()
        for stale in sorted(T25.rglob("*"), reverse=True):
            if stale.is_dir():
                stale.chmod(0o755)
                stale.rmdir()
    T25.mkdir(parents=True, exist_ok=True)
    (T25 / "remediation").mkdir(parents=True, exist_ok=True)
    for relative, payload in sorted(remediation_backup.items()):
        target = ROOT / relative
        target.write_bytes(payload)
    spec = _author_specification()
    _write(T25 / "author_specification.json", spec)
    load_spec()
    print("author specification written", flush=True)

    _write(T25 / "capability_registry.json", _capability_registry())
    _write(T25 / "candidate_identity.json", _candidate_identity())
    _write(T25 / "t25_publication_policy.json", policy.publication_policy_document())
    _write(T25 / "t25_artifact_classification.json",
           classification.classification_registry_document())
    _write(T25 / "t25_private_store_config.json", store.store_config_document())
    print("policy/classification/store artifacts written", flush=True)

    _qualification()
    print("public qualification data written (1280 rows, route agreement 1.0)", flush=True)

    t23_anchor = build_t23_anchor(ROOT)
    _write(T25 / "t23_exposed_sealed_anchor.json", t23_anchor)
    t24_anchor_copy = _read(T24 / "t23_exposed_sealed_anchor.json")
    if t24_anchor_copy != t23_anchor:
        raise ValueError("T23 anchor recomputation differs from the frozen T24 copy")
    print("T23 exposed-sealed anchor written (byte-identical to the frozen T24 copy)",
          flush=True)

    t24_anchor = build_t24_anchor(ROOT)
    _write(T25 / "t24_sealed_evaluated_anchor.json", t24_anchor)
    from t25_protocol.anchor_t24 import verify_anchor as verify_t24_anchor

    verify_t24_anchor(ROOT, T25 / "t24_sealed_evaluated_anchor.json")
    print("T24 sealed-evaluated anchor written and verified (hash-only, no T24 rows)",
          flush=True)

    sets = _firewall_fingerprint_sets()
    registry = build_firewall_document(
        ROOT,
        t23_anchor_record=_binding(T25 / "t23_exposed_sealed_anchor.json"),
        historical_records=[_binding(sets["historical_fingerprints.json"])],
        qualification_records=[_binding(sets["qualification_fingerprints.json"])],
        t23_content_records=[_binding(sets["t23_content_fingerprints.json"])],
        t23_text_records=[_binding(sets["t23_text_fingerprints.json"])],
        t24_anchor_record=_binding(T25 / "t24_sealed_evaluated_anchor.json"))
    _write(T25 / "live_web_source_firewall_registry.json", registry)
    print("live-web firewall registry written (T24 material denied via anchor)", flush=True)

    _write(T25 / "t25_exclusion_sources.json",
           _exclusion_registry(T25 / "t23_exposed_sealed_anchor.json",
                               T25 / "t24_sealed_evaluated_anchor.json"))
    from t25_protocol.exclusions import load_exclusion_sources

    forbidden = load_exclusion_sources(ROOT, _read(T25 / "t25_exclusion_sources.json"))
    print("exclusion source registry written; forbidden counts:",
          {name: len(values) for name, values in sorted(forbidden.items())}, flush=True)

    floors = json.loads((T23 / "router_metric_registry.json").read_text(encoding="utf-8"))
    floors["artifact"] = "T25_PREREGISTERED_ROUTER_METRIC_REGISTRY"
    floors["experiment"] = "t25"
    floors["schema_version"] = "t25-router-metric-registry-v1"
    floors["frozen_from_t23"] = True
    floors["t23_exposed_reuse_allowed"] = False
    floors["t24_sealed_reuse_allowed"] = False
    _write(T25 / "router_metric_registry.json", floors)
    _write(T25 / "production_router_metric_registry.json", production_registry())
    print("router metric registries written", flush=True)

    provider = json.loads((T23 / "production_provider_config.json").read_text(encoding="utf-8"))
    provider["schema_version"] = "t25-production-provider-config-v1"
    provider["artifact"] = "T25_PRODUCTION_PROVIDER_CONFIG"
    provider["experiment"] = "t25"
    provider["provider_entry"] = "t25_protocol.provider:T25ProductionRouterProvider"
    provider["web_firewall_mandatory"] = True
    provider["firewall_registry"] = "evaluations/t25/live_web_source_firewall_registry.json"
    provider["web_real_policy"] = "LIVE_FREE_SOURCE_BACKED_ONLY_FIREWALL_FILTERED"
    provider["private_store_identity"] = "T25-STORE-01"
    _write(T25 / "production_provider_config.json", provider)
    print("production provider config written", flush=True)

    contract_document = master_contract_document()
    validate_t25_contract(contract_document)
    _write(T25 / "t25_master_contract.json", contract_document)
    print("master contract written", flush=True)

    graph = _evaluation_graph()
    _write(T25 / "production_evaluation_graph.json", graph)
    print("production evaluation graph written (27 nodes)", flush=True)

    _write(T25 / "author_lock.json", lock_module.expected_lock())
    print("author lock written", flush=True)

    import t25_protocol.graph as graph_module

    report = graph_module.validate_graph(graph)
    if report["status"] != "PASS":
        raise ValueError(f"T25 graph validation failed: {report}")
    lock_module.verify_lock()
    validate_t25_contract(json.loads((T25 / "t25_master_contract.json").read_text(encoding="utf-8")))
    print("BUILD COMPLETE: contract, graph, lock all verified", flush=True)


if __name__ == "__main__":
    main()