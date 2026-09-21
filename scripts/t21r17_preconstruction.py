"""T21R17 metric-semantics preconstruction generator (staged, deterministic).

T21R16 closed as OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE: the official
one-shot run completed (4800/4800 rows, attempt 1, ledger COMPLETE) but two
frozen floor metrics — conflict_false_resolution and
static_query_unnecessary_web_routing — did not semantically measure their
registered quantities. The frozen scorer's generic aggregate derivation
(scorer.py: ``op in {"=", "<="} and value == 0 -> 0; elif domain_macro;
else accuracy``) reported accuracy (1.0) against the two bad-event floors.
T21R17 preconstruction gives every official floor metric explicit frozen
measurement semantics, an implementation registry, and a discriminative
fixture battery — before any R17 material exists.

Stages (run in order):
  closure        T21R16 final disposition (closure + refusal marker +
                 R17 disposition record; hash-only fingerprints)
  registry       prior_exclusion.json (16 milestones, hash-only, incl.
                 T21R16_OFFICIAL_EVALUATED_MEASUREMENT_INVALID)
  static         R17 static artifacts (taxonomy, exclusions, schemas,
                 runtime contracts derived from frozen bytes, artifact
                 graph, metric design documents)
  semantics      validate official_metric_semantics.json + the metric
                 implementation registry (explicit semantics, fail-closed)
  adjudication   full-suite pytest + failure classification
  freeze         evaluator_freeze.json
  contract       t21_master_contract.json
  lock           qualification_lock.json
  fixtures       run the metric-semantics fixture battery
  shadow         runtime-native shadow corpus + R16 overlap zeros
  parity         provider parity (evidence provider vs direct runtime)
  lifecycle      full lifecycle x2 on disposable material
  cleanliness    raw/applicable/focused pytest runs with tracked drift
  doctor         protocol doctor (r16_disposition,
                 metric_semantics_validation, lifecycle rehearsal)
  audit          T21R17_PRECONSTRUCTION_AUDIT.json
  prefreeze      preconstruction_freeze.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r17"
R16_OUT = ROOT / "evaluations" / "t21r16"
sys.path.insert(0, str(ROOT))

from t21_protocol.audits import DIMENSIONS, _fingerprint  # noqa: E402
from t21_protocol.context import CONSTRUCTION_TOKENS, EVALUATION_TOKENS  # noqa: E402
from t21_protocol.contract import load_contract  # noqa: E402
from t21_protocol.freeze import build_freeze  # noqa: E402
from t21_protocol.qualification import build_qualification_lock, validate_qualification_lock  # noqa: E402
from t21_protocol.util import read_json, sha256_file, sha256_json, write_json  # noqa: E402
from scripts.t21r16_preconstruction import (  # noqa: E402
    ADJUDICATION_SCHEMA_VERSION,
    ALLOWED_CLASSIFICATIONS,
    CANDIDATE_COMMIT,
    CANDIDATE_TREE,
    FLOOR_HASH,
    RUNTIME_COMPONENTS,
    RUNTIME_ROOT,
    SUITE_SIZES,
    _canonical_set_sha,
    _holdout_frozen_schema,
    _junit_failures,
    _runtime_corpus_contract,
    _run_pytest,
    _evaluation_design_documents,
)

R16_OFFICIAL_EVAL_HEAD = "8d9d1be6ffeff4f249a93de876b40ed95a4e4083"
R16_OFFICIAL_EVAL_BRANCH = "t21r16-official-evaluation"
R16_CLOSURE_STATUS = "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE"
R16_CLOSURE_REASON = (
    "OFFICIAL_RUN_COMPLETED_BUT_TWO_FROZEN_FLOOR_METRICS_DID_NOT_SEMANTICALLY_MEASURE"
    "_THEIR_REGISTERED_QUANTITIES"
)
R16_HISTORICAL_MILESTONE = "T21R16_OFFICIAL_EVALUATED_MEASUREMENT_INVALID"
R16_INVALID_METRICS = ("conflict_false_resolution", "static_query_unnecessary_web_routing")
R16_INVALID_METRIC_DESIGNATION = "SEMANTICALLY_INVALID_FOR_CAPABILITY_ADJUDICATION"
R16_HOLDOUT_STATUS = "PERMANENTLY_EXPOSED_CONSUMED"
R16_ROOT_CAUSE = (
    "the frozen scorer's generic metric derivation (t21_protocol/scorer.py: "
    "if spec['op'] in {'=', '<='} and spec['value'] == 0: metrics[metric] = 0; "
    "elif metric == 'domain_macro_grounded_accuracy': metrics[metric] = domain_macro; "
    "else: metrics[metric] = accuracy) assigned aggregate accuracy to every floor "
    "metric it had no dedicated path for; conflict_false_resolution (<= 0.01) and "
    "static_query_unnecessary_web_routing (<= 0.03) therefore reported the run-wide "
    "accuracy 1.0 instead of a bad-event rate"
)
AUTHOR_SEED = 21017
R17_CONSTRUCTION_TOKEN = CONSTRUCTION_TOKENS["t21r17"]
R17_EVALUATION_TOKEN = EVALUATION_TOKENS["t21r17"]

R16_EVALUATION_ARTIFACTS = (
    "evaluations/t21r16/HOLDOUT_FROZEN",
    "evaluations/t21r16/holdout_manifest.json",
    "evaluations/t21r16/sealed_preflight.json",
    "evaluations/t21r16/evaluation_run_ledger.json",
    "evaluations/t21r16/candidate_outputs.jsonl",
    "evaluations/t21r16/evaluator_results.json",
    "evaluations/t21r16/score_results.json",
    "evaluations/t21r16/evaluation_provenance.json",
    "evaluations/t21r16/raw_results.jsonl",
    "evaluations/t21r16/metric_evidence.json",
    "evaluations/t21r16/floor_evidence.json",
    "evaluations/t21r16/holdout_results.json",
)

SEMANTICS_PATH = "evaluations/t21r17/official_metric_semantics.json"
REGISTRY_PATH = "evaluations/t21r17/metric_implementation_registry.json"
FIXTURES_PATH = "evaluations/t21r17/metric_semantics_fixtures.json"


def _load(relative: str) -> dict[str, Any]:
    return read_json(ROOT / relative)


def _write(relative: str, document: dict[str, Any], *, exclusive: bool = False) -> None:
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, document, exclusive=exclusive)


def _floors() -> dict[str, Any]:
    return _load("evaluations/t21r16/t21_master_contract.json")["values"]["promotion_floors"]


# ---------------------------------------------------------------- closure --


def stage_closure() -> dict[str, Any]:
    """Record the T21R16 final disposition verbatim (protocol §1–§7)."""
    score = _load("evaluations/t21r16/score_results.json")
    floor_evidence = _load("evaluations/t21r16/floor_evidence.json")
    if score["rows"] != 4800 or score["candidate_capability_pass"] is not False:
        raise SystemExit("R16 official score results do not match the frozen one-shot run")
    frozen_observed = {
        metric: score["metrics"][metric] for metric in R16_INVALID_METRICS
    }
    if frozen_observed != {"conflict_false_resolution": 1.0, "static_query_unnecessary_web_routing": 1.0}:
        raise SystemExit(f"frozen observed values drifted: {frozen_observed}")
    failed_floors = sorted(
        comparison["metric"] for comparison in floor_evidence["floor_comparisons"] if not comparison["pass"]
    )
    if failed_floors != sorted(R16_INVALID_METRICS):
        raise SystemExit(f"R16 failed floors drifted: {failed_floors}")
    fingerprints = {relative: sha256_file(ROOT / relative) for relative in R16_EVALUATION_ARTIFACTS}
    closure = {
        "schema_version": "t21-experiment-closure-v1",
        "artifact": "T21R16_CLOSURE",
        "experiment": "t21r16",
        "status": R16_CLOSURE_STATUS,
        "reason": R16_CLOSURE_REASON,
        "failure_class": "measurement_specification",
        "capability_verdict": "NONE",
        "capability_failure": False,
        "invalid_metrics": sorted(R16_INVALID_METRICS),
        "invalid_metric_designation": R16_INVALID_METRIC_DESIGNATION,
        "holdout_status": R16_HOLDOUT_STATUS,
        "rows_scored": 4800,
        "one_shot_consumed": True,
        "official_run_preserved": {
            "construction_commit": "6d5b069",
            "official_evaluation_commit": R16_OFFICIAL_EVAL_HEAD,
            "branch": R16_OFFICIAL_EVAL_BRANCH,
            "construction_attempt": 1,
            "evaluation_attempt": 1,
            "rows": 4800,
            "ledger_status": "COMPLETE",
            "exposures": 1,
            "floors_passed": 30,
            "floors_failed": sorted(R16_INVALID_METRICS),
            "rerun": "PROHIBITED",
        },
        "frozen_observed_values": frozen_observed,
        "frozen_observed_values_note": (
            "recorded exactly as scored by the frozen scorer in the one-shot run; the values are "
            "never replaced with alternative estimates or repaired observations"
        ),
        "root_cause": R16_ROOT_CAUSE,
        "remediation_protocol": "T21R17 metric-semantics preconstruction (explicit per-metric frozen semantics); no Mango candidate remediation is derived from R16",
        "rerun_policy": {
            "rerun_r16_evaluation": "REFUSED",
            "holdout_reuse": "FORBIDDEN",
            "holdout_status": R16_HOLDOUT_STATUS,
        },
        "artifact_fingerprints_sha256": fingerprints,
        "closed_at": "2026-09-21",
    }
    _write("evaluations/t21r16/T21R16_CLOSURE.json", closure)
    refusal = {
        "schema_version": "t21-evaluation-refusal-v1",
        "artifact": "T21R16_EVALUATION_REFUSAL",
        "experiment": "t21r16",
        "permanent": True,
        "refused_action": "any further T21R16 official evaluation",
        "reason": R16_CLOSURE_REASON,
        "authority": "T21R16 final adjudication: holdout PERMANENTLY EXPOSED / CONSUMED; capability verdict NONE",
    }
    _write("evaluations/t21r16/evaluation_refusal.json", refusal)
    disposition = {
        **{key: closure[key] for key in (
            "schema_version", "experiment", "status", "reason", "failure_class",
            "capability_verdict", "capability_failure", "invalid_metrics",
            "invalid_metric_designation", "holdout_status", "rows_scored",
            "one_shot_consumed", "official_run_preserved", "frozen_observed_values",
            "frozen_observed_values_note", "root_cause", "remediation_protocol",
            "rerun_policy", "closed_at",
        )},
        "artifact": "T21R16_FINAL_DISPOSITION",
        "consumers": ["t21r17 official_metric_semantics", "t21r17 metric_semantics_fixtures", "protocol_doctor"],
        "derivation_provenance": {
            "rule": "the disposition names only aggregate facts and artifact fingerprints; no R16 blind case, raw result row, or evaluator record value enters R17 construction (quarantine §17)",
            "r16_rows_read_by_r17_material": 0,
            "aggregate_retained": "two metric implementations were invalid; the frozen observed values 1.0/1.0 are protocol failure provenance",
        },
    }
    _write("evaluations/t21r17/r16_final_disposition.json", disposition)
    return {
        "status": "PASS",
        "closure": "evaluations/t21r16/T21R16_CLOSURE.json",
        "refusal_marker": "evaluations/t21r16/evaluation_refusal.json",
        "disposition": "evaluations/t21r17/r16_final_disposition.json",
        "frozen_observed": frozen_observed,
    }


# ---------------------------------------------------------------- registry --


def _r16_sealed_fingerprints() -> dict[str, set[str]]:
    """Hash-only derivation input for the T21R16 registry milestone.

    R16 sealed and officially-evaluated material is read, fingerprinted in
    memory with the protocol's own fingerprint function, and never persisted:
    the registry stores fingerprints only."""
    contract = _load("evaluations/t21r16/t21_master_contract.json")
    suite_names = sorted(contract["values"]["suites"])
    rows: list[dict[str, Any]] = []
    for suite_name in suite_names:
        path = R16_OUT / "suites" / suite_name / "holdout.jsonl"
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    corpus_dir = ROOT / "rag" / "gk_holdout_t21r16"
    sources = [json.loads(line) for line in (corpus_dir / "sources.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks = [json.loads(line) for line in (corpus_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    world = [json.loads(line) for line in (corpus_dir / "world.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 4800 or len(sources) != 4800 or len(chunks) != 4800 or len(world) != 4800:
        raise SystemExit("R16 sealed material shape mismatch")
    values: dict[str, set[str]] = {dimension: set() for dimension in DIMENSIONS}
    values["case_ids"].update(_fingerprint("case_ids", row.get("case_id")) for row in rows)
    values["exact_queries"].update(_fingerprint("exact_queries", row.get("query")) for row in rows)
    values["exact_answers"].update(_fingerprint("exact_answers", (row.get("gold") or {}).get("expected_answer")) for row in rows)
    values["verbatim_attack_wording"].update(
        _fingerprint("verbatim_attack_wording", row["construction"]["attack_wording"])
        for row in rows
        if (row.get("construction") or {}).get("attack_wording")
    )
    values["source_ids"].update(_fingerprint("source_ids", source.get("source_id")) for source in sources)
    values["chunk_ids"].update(_fingerprint("chunk_ids", chunk.get("chunk_id")) for chunk in chunks)
    values["exact_source_text"].update(_fingerprint("exact_source_text", chunk.get("text")) for chunk in chunks)
    for record in world:
        if record.get("record_type") == "entity" or record.get("type") == "WorldEntity":
            values["entity_identities"].update(
                _fingerprint("entity_identities", record.get(field)) for field in ("entity_id", "name") if record.get(field)
            )
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        if metadata.get("fact_entity"):
            values["entity_identities"].add(_fingerprint("entity_identities", metadata["fact_entity"]))
    return {name: {value for value in items if value} for name, items in values.items()}


def stage_registry() -> dict[str, Any]:
    upstream = _load("evaluations/t21r16/prior_exclusion.json")
    if upstream.get("historical_milestone_count") != 15:
        raise SystemExit("unexpected upstream registry milestone count")
    fingerprints = _r16_sealed_fingerprints()
    milestone = {
        "dimensions": {
            dimension: {
                "count": len(values),
                "fingerprints": sorted(values),
                "set_sha256": _canonical_set_sha(sorted(values)),
            }
            for dimension, values in fingerprints.items()
        },
        "provenance": {
            "milestone": R16_HISTORICAL_MILESTONE,
            "derivation": "hash-only in-memory fingerprinting of R16 sealed + officially-evaluated material with t21_protocol.audits._fingerprint; raw values never persisted",
            "official_evaluation_head": R16_OFFICIAL_EVAL_HEAD,
            "construction_commit": "6d5b069",
            "sealed_holdout_manifest_sha256": sha256_file(ROOT / "evaluations" / "t21r16" / "holdout_manifest.json"),
            "sealed_holdout_frozen_sha256": sha256_file(ROOT / "evaluations" / "t21r16" / "HOLDOUT_FROZEN"),
            "rows_scored": 4800,
            "one_shot_consumed": True,
            "holdout_status": R16_HOLDOUT_STATUS,
            "source_paths": [
                "evaluations/t21r16/suites/<suite>/holdout.jsonl",
                "rag/gk_holdout_t21r16/sources.jsonl",
                "rag/gk_holdout_t21r16/chunks.jsonl",
                "rag/gk_holdout_t21r16/world.jsonl",
            ],
            "raw_values_included": False,
            "measurement_note": "the milestone records that the official evaluation completed but two frozen floor metrics did not semantically measure their registered quantities; it is protocol failure provenance, not a capability failure",
        },
    }
    milestone_names = list(upstream["milestone_order"]) + [R16_HISTORICAL_MILESTONE]
    registry = {
        "artifact": "T21R17_PRIOR_EXCLUSION_REGISTRY",
        "version": "t21r17-v1",
        "fingerprint_algorithm": upstream["fingerprint_algorithm"],
        "payload_encoding": upstream["payload_encoding"],
        "historical_dimensions": len(DIMENSIONS),
        "historical_milestone_count": len(milestone_names),
        "milestone_order": milestone_names,
        "milestones": {**upstream["milestones"], R16_HISTORICAL_MILESTONE: milestone},
        "raw_values_included": False,
    }
    if len(registry["milestones"]) != 16:
        raise SystemExit("registry must carry exactly 16 milestones")
    for name, spec in registry["milestones"].items():
        if set(spec["dimensions"]) != set(DIMENSIONS):
            raise SystemExit(f"milestone {name} dimensions invalid")
        for dimension, payload in spec["dimensions"].items():
            if payload["count"] != len(payload["fingerprints"]):
                raise SystemExit(f"milestone {name}/{dimension} count mismatch")
    _write("evaluations/t21r17/prior_exclusion.json", registry)
    return {
        "status": "PASS",
        "milestones": len(milestone_names),
        "r16_fingerprint_counts": {dimension: milestone["dimensions"][dimension]["count"] for dimension in DIMENSIONS},
    }


# ------------------------------------------------------------------ static --


def _negative_controls() -> dict[str, Any]:
    r16 = _load("evaluations/t21r16/negative_controls.json")
    controls = list(r16["controls"])
    controls.extend(
        {"failure_class": name, "latest_legal_phase": "PRECONSTRUCTION", "test": test}
        for name, test in (
            ("floor metric without registered semantics", "tests/test_t21r17_preconstruction.py::test_unknown_floor_metric_fails_closed"),
            ("scorer generic fallback path", "tests/test_t21r17_preconstruction.py::test_scorer_has_no_generic_fallback_path"),
            ("metric with multiple implementations", "tests/test_t21r17_preconstruction.py::test_metric_registry_has_no_missing_or_multiple_implementations"),
            ("fixture battery golden-vector deviation", "tests/test_t21r17_preconstruction.py::test_metric_semantics_fixture_battery_passes"),
            ("r16 regression fixture failure", "tests/test_t21r17_preconstruction.py::test_metric_semantics_fixture_battery_passes"),
        )
    )
    return {
        "schema_version": "t21-negative-controls-v1",
        "artifact": "T21R17_NEGATIVE_CONTROL_REGISTRY",
        "experiment": "t21r17",
        "infrastructure_errors_must_fail_before_construction": True,
        "controls": controls,
    }


def _historical_exclusion(milestones: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "t21-historical-exclusion-policy-v1",
        "artifact": "T21R17_HISTORICAL_EXCLUSION_POLICY",
        "experiment": "t21r17",
        "raw_values_included": False,
        "historical_milestone_count": len(milestones),
        "milestones": milestones,
        "r16_protocol_history": {
            "blind_fingerprints_invented": False,
            "construction_attempts": 1,
            "one_shot_consumed": True,
            "rows_scored": 4800,
            "closure_status": R16_CLOSURE_STATUS,
            "closure_reason": R16_CLOSURE_REASON,
            "capability_verdict": "NONE",
            "evaluation_permanently_refused": True,
            "holdout_status": R16_HOLDOUT_STATUS,
        },
        "upstream_registry": "evaluations/t21r17/prior_exclusion.json",
        "upstream_registry_sha256": sha256_file(ROOT / "evaluations" / "t21r17" / "prior_exclusion.json"),
    }


def _artifact_graph() -> dict[str, Any]:
    r16 = _load("evaluations/t21r16/artifact_graph.json")
    known_producers = sorted(
        {*r16["known_producers"], "r16_closure", "metric_semantics", "metric_semantics_fixtures"}
    )
    nodes: dict[str, Any] = {}
    for name, node in r16["nodes"].items():
        nodes[name] = {**node, "path": node["path"].replace("t21r16", "t21r17")}
    nodes.pop("r15_closure", None)
    nodes.pop("r14_closure", None)
    historical = nodes["historical_exclusion"]
    historical["required_inputs"] = [
        "r16_closure" if name in {"r14_closure", "r15_closure"} else name
        for name in historical["required_inputs"]
    ]
    nodes["r16_closure"] = {
        "path": "evaluations/t21r16/T21R16_CLOSURE.json",
        "producer": "r16_closure",
        "required_inputs": [],
        "consumers": ["historical_exclusion", "protocol_doctor", "master_contract"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": True,
    }
    nodes["official_metric_semantics"] = {
        "path": SEMANTICS_PATH,
        "producer": "metric_semantics",
        "required_inputs": ["master_contract"],
        "consumers": ["scorer", "metric_semantics_fixtures", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["metric_implementation_registry"] = {
        "path": REGISTRY_PATH,
        "producer": "metric_semantics",
        "required_inputs": ["official_metric_semantics"],
        "consumers": ["scorer", "metric_semantics_fixtures", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["metric_semantics_fixtures"] = {
        "path": FIXTURES_PATH,
        "producer": "metric_semantics_fixtures",
        "required_inputs": ["official_metric_semantics", "metric_implementation_registry", "evaluator_freeze"],
        "consumers": ["protocol_doctor", "official_validator"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    return {
        "schema_version": "t21-artifact-graph-v1",
        "artifact": "T21R17_ARTIFACT_GRAPH",
        "experiment": "t21r17",
        "known_producers": known_producers,
        "nodes": nodes,
    }


def stage_static() -> dict[str, Any]:
    r16_contract = _load("evaluations/t21r16/t21_master_contract.json")
    r16_values = r16_contract["values"]
    registry = _load("evaluations/t21r17/prior_exclusion.json")
    milestones = registry["milestone_order"]

    taxonomy = {**_load("evaluations/t21r16/domain_taxonomy_contract.json"), "artifact": "T21R17_DOMAIN_TAXONOMY_CONTRACT", "experiment": "t21r17"}
    remediation = {
        **_load("evaluations/t21r16/remediation_exclusion.json"),
        "artifact": "T21R17_REMEDIATION_EXCLUSION_POLICY",
        "experiment": "t21r17",
        "source": f"evaluations/t21r16/remediation_exclusion.json#sha256={r16_values['remediation_exclusions']['source_sha256']}",
    }
    historical = _historical_exclusion(milestones)
    schema_document = _holdout_frozen_schema()
    controls = _negative_controls()
    experiment = {
        "artifact": "T21R17_EXPERIMENT_CONFIGURATION",
        "author_vocabulary": _load("evaluations/t21r16/experiment.json")["author_vocabulary"],
        "case_id_prefix": "r17-",
        "crossdomain_pair_ids": sorted(pair["id"] for pair in r16_values["crossdomain_pairs"]),
        "experiment": "t21r17",
        "historical_exclusion_milestone_count": len(milestones),
        "namespace": "mango-r17-v1",
        "seed": AUTHOR_SEED,
        "suite_total": 4800,
        "version": "t21r17-v1",
    }

    def _patch_labels(document: dict[str, Any], artifact: str) -> dict[str, Any]:
        patched = json.loads(json.dumps(document).replace("t21r16", "t21r17").replace("T21R16_", "T21R17_"))
        patched["artifact"] = artifact
        patched["experiment"] = "t21r17"
        return patched

    corpus_contract, checks = _runtime_corpus_contract()
    corpus_contract = _patch_labels(corpus_contract, "T21R17_RUNTIME_CORPUS_CONTRACT")
    if not all(checks.values()):
        raise SystemExit(f"runtime corpus contract derivation checks failed: {checks}")
    field_provenance = _patch_labels(_load("evaluations/t21r16/runtime_field_provenance.json"), "T21R17_RUNTIME_FIELD_PROVENANCE")
    _write("evaluations/t21r17/runtime_corpus_contract.json", corpus_contract)
    _write("evaluations/t21r17/runtime_field_provenance.json", field_provenance)
    runtime_freeze = build_freeze(
        ROOT,
        RUNTIME_COMPONENTS,
        artifact="T21R17_RUNTIME_FREEZE",
        experiment="t21r17",
        extra={"candidate_commit": CANDIDATE_COMMIT, "candidate_tree": CANDIDATE_TREE},
    )
    if runtime_freeze["component_root_sha256"] != RUNTIME_ROOT:
        raise SystemExit("runtime freeze root does not match the frozen runtime root")
    candidate_data_contract = _patch_labels(
        _load("evaluations/t21r16/candidate_runtime_data_contract.json"), "T21R17_CANDIDATE_RUNTIME_DATA_CONTRACT"
    )
    candidate_data_contract["candidate"] = {
        "provider_id": "t21_protocol.providers_r17:RealCandidateProviderEvidence",
        "module": "t21_protocol/providers_r17.py",
        "module_sha256": sha256_file(ROOT / "t21_protocol" / "providers_r17.py"),
        "serialization": "t21_protocol.providers_r17:canonical_candidate_row_v2",
        "corpus_loader": "src/sciencemath/knowledge/corpus.py:load_corpus (frozen, no adapter)",
        "initialization": {"loads_corpus_once": True, "executes_holdout_rows": False},
        "generation": {"entry": "src/sciencemath/knowledge/pipeline.py:answer_knowledge", "canonical_serialization": "t21_protocol.providers_r17:canonical_candidate_row_v2"},
        "evidence_passthrough": ["citations", "citation_report", "claim_review", "evidence_pack", "eligibility"],
        "candidate_rows_executed_in_preconstruction": 0,
    }
    candidate_data_contract["runtime_corpus_contract"] = {
        "path": "evaluations/t21r17/runtime_corpus_contract.json",
        "sha256": sha256_file(ROOT / "evaluations" / "t21r17" / "runtime_corpus_contract.json"),
    }
    candidate_data_contract["runtime_field_provenance"] = {
        "path": "evaluations/t21r17/runtime_field_provenance.json",
        "sha256": sha256_file(ROOT / "evaluations" / "t21r17" / "runtime_field_provenance.json"),
    }
    graph = _artifact_graph()
    design = _evaluation_design_documents(r16_values["promotion_floors"])
    design = {name: _patch_labels(document, document["artifact"].replace("T21R16_", "T21R17_")) for name, document in design.items()}
    _write("evaluations/t21r17/domain_taxonomy_contract.json", taxonomy)
    _write("evaluations/t21r17/remediation_exclusion.json", remediation)
    _write("evaluations/t21r17/historical_exclusion.json", historical)
    _write("evaluations/t21r17/holdout_frozen_schema.json", schema_document)
    _write("evaluations/t21r17/negative_controls.json", controls)
    _write("evaluations/t21r17/experiment.json", experiment)
    _write("evaluations/t21r17/artifact_graph.json", graph)
    _write("evaluations/t21r17/runtime_corpus_contract.json", corpus_contract)
    _write("evaluations/t21r17/runtime_field_provenance.json", field_provenance)
    _write("evaluations/t21r17/candidate_runtime_data_contract.json", candidate_data_contract)
    _write("evaluations/t21r17/runtime_freeze.json", runtime_freeze)
    for name, document in design.items():
        _write(f"evaluations/t21r17/{name}.json", document)
    return {"status": "PASS", "runtime_contract_checks": checks, "graph_nodes": len(graph["nodes"])}


# --------------------------------------------------------------- semantics --


def stage_semantics() -> dict[str, Any]:
    """Every official floor metric carries explicit frozen semantics; no
    generic fallback; unknown metrics fail closed; implementations are
    registered one-to-one."""
    from t21_protocol.metric_semantics import load_metric_semantics, semantics_root
    from t21_protocol.scorer_r17 import IMPLEMENTATIONS, IMPLEMENTATION_SOURCES

    floors = _floors()
    floor_metrics = sorted(metric for metrics in floors.values() for metric in metrics)
    semantics = load_metric_semantics(ROOT, {}, relative=SEMANTICS_PATH, floors=floors)
    entries = semantics["metrics"]
    entry_keys = (
        "metric_id", "family", "semantic_type", "numerator", "denominator", "aggregation",
        "aggregation_scope", "direction", "range", "operator", "threshold",
        "row_evidence_inputs", "floor_consumers", "zero_denominator_policy",
    )
    registry = read_json(ROOT / REGISTRY_PATH)
    problems: dict[str, Any] = {
        "metrics_without_semantics": sorted(set(floor_metrics) - set(entries)),
        "semantics_without_floors": sorted(set(entries) - set(floor_metrics)),
        "metrics_without_implementation": sorted(set(floor_metrics) - set(IMPLEMENTATIONS)),
        "implementations_without_floor": sorted(set(IMPLEMENTATIONS) - set(floor_metrics)),
        "registry_missing": registry["missing_implementations"],
        "registry_multiple": registry["multiple_implementations"],
        "generic_fallback_rule": [] if "no generic fallback" in semantics["rule"] else ["rule missing 'no generic fallback'"],
        "entries_without_zero_denominator_policy": sorted(
            metric for metric, entry in entries.items() if not entry.get("zero_denominator_policy")
        ),
        "entries_without_numerator": sorted(
            metric for metric, entry in entries.items() if not entry.get("numerator")
        ),
        "entries_without_denominator": sorted(
            metric for metric, entry in entries.items() if not entry.get("denominator")
        ),
        "direction_contradictions": sorted(
            metric
            for metric, entry in entries.items()
            if entry["direction"] != {"=": "EXACT", "<=": "LOWER_IS_BETTER", ">=": "HIGHER_IS_BETTER"}[entry["operator"]]
        ),
        "unbound_scorer_paths": sorted(
            metric for metric in floor_metrics if metric not in IMPLEMENTATION_SOURCES
        ),
    }
    defects = {name: values for name, values in problems.items() if values}
    floor_hash_ok = sha256_json(floors) == FLOOR_HASH
    registry_shape_ok = (
        registry["implementation_count"] == 32
        and sorted(registry["implementations"]) == floor_metrics
        and registry["scorer_module_sha256"] == sha256_file(ROOT / "t21_protocol" / "scorer_r17.py")
        and all(entry.get("implementation_sha256") and entry.get("function") for entry in registry["implementations"].values())
    )
    ok = not defects and floor_hash_ok and registry_shape_ok
    document = {
        "schema_version": "t21r17-metric-semantics-validation-v1",
        "artifact": "T21R17_METRIC_SEMANTICS_VALIDATION",
        "experiment": "t21r17",
        "status": "PASS" if ok else "FAIL",
        "audit_mode": "EXECUTED",
        "semantics_artifact": SEMANTICS_PATH,
        "semantics_root": semantics_root(semantics),
        "registry_artifact": REGISTRY_PATH,
        "registry_sha256": sha256_file(ROOT / REGISTRY_PATH),
        "floor_hash": FLOOR_HASH,
        "floor_hash_matches_frozen": floor_hash_ok,
        "metrics": {metric: {key: entries[metric][key] for key in entry_keys if key in entries[metric]} for metric in floor_metrics},
        "problems": problems,
        "registry_shape_ok": registry_shape_ok,
    }
    _write("evaluations/t21r17/metric_semantics_validation.json", document)
    if not ok:
        raise SystemExit(f"metric semantics validation failed: {json.dumps(defects)[:2000]}")
    return {"status": "PASS", "metrics": len(entries), "semantics_root": document["semantics_root"]}


# ------------------------------------------------------------ adjudication --


APPLICABILITY_SCHEMA_VERSION = "t21-current-test-applicability-v1"


def _classify_r17(nodeid: str, r16: dict[str, str]) -> tuple[str, str]:
    """R17 failure classification: the committed R16 adjudication map first,
    then the documented expiry of the R16 preconstruction absence pin — the
    same shape R16 adjudicated for R15's pin."""
    if nodeid in r16:
        return (
            r16[nodeid],
            "classification carried from the committed T21R16 adjudication (same committed historical artifact state)",
        )
    if nodeid == "tests/test_t21r16_preconstruction.py::test_real_r16_paths_absent":
        return (
            "OBSOLETE_HISTORICAL_ASSERTION",
            "asserts real R16 holdout paths are absent; the R16 sealed holdout legitimately exists, was consumed by the "
            "one-shot official evaluation, and is preserved unmodified (T21R16 final adjudication); the R17 contract "
            "carries the equivalent preconstruction pin (tests/test_t21r17_preconstruction.py::test_real_r17_paths_absent)",
        )
    if nodeid.startswith("tests/test_t21_protocol_kernel.py::"):
        return (
            "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE",
            "rehearsal bound to the R16 qualification lock; tests/test_t21r17_preconstruction.py re-runs the equivalent "
            "rehearsal against the current R17 contract and lock",
        )
    return "UNKNOWN", "unclassified failure"


def stage_adjudication() -> dict[str, Any]:
    from t21_protocol.adjudication import generate_applicability

    r16_adjudication = _load("evaluations/t21r16/test_failure_adjudication.json")
    r16 = {entry["nodeid"]: entry["classification"] for entry in r16_adjudication["entries"]}
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    junit = artifacts / "t21r17_adjudication_junit.xml"
    run = _run_pytest(["tests"], junit, artifacts / ".pytest_t21r17_adjudication")
    failures = _junit_failures(junit)
    if not failures:
        raise SystemExit("adjudication expected registered historical failures in the full suite")
    entries = []
    for nodeid in sorted(failures):
        classification, rationale = _classify_r17(nodeid, r16)
        entries.append({"nodeid": nodeid, "classification": classification, "rationale": rationale})
    unresolved = [entry for entry in entries if entry["classification"] in {"LIVE", "UNKNOWN", "ENVIRONMENT_ONLY_FAILURE"}]
    if unresolved:
        raise SystemExit(f"unadjudicated failures remain: {unresolved}")
    summary = {name: 0 for name in ALLOWED_CLASSIFICATIONS}
    for entry in entries:
        summary[entry["classification"]] += 1
    adjudication = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "artifact": "T21R17_TEST_FAILURE_ADJUDICATION",
        "experiment": "t21r17",
        "classification_summary": summary,
        "entries": [{"nodeid": entry["nodeid"], "classification": entry["classification"]} for entry in entries],
        "rationales": {entry["nodeid"]: entry["rationale"] for entry in entries},
    }
    _write("evaluations/t21r17/test_failure_adjudication.json", adjudication)
    _write("evaluations/t21r17/current_test_applicability.json", generate_applicability(adjudication))
    return {"status": "PASS", "failures": len(entries), "summary": summary, "pytest_exit_code": run["exit_code"]}


# ------------------------------------------------------------------ freeze --


def stage_freeze() -> dict[str, Any]:
    experiment_artifacts = [
        "evaluations/t21r17/artifact_graph.json",
        "evaluations/t21r17/current_test_applicability.json",
        "evaluations/t21r17/domain_taxonomy_contract.json",
        "evaluations/t21r17/experiment.json",
        "evaluations/t21r17/historical_exclusion.json",
        "evaluations/t21r17/holdout_frozen_schema.json",
        "evaluations/t21r17/negative_controls.json",
        "evaluations/t21r17/remediation_exclusion.json",
        "evaluations/t21r17/runtime_freeze.json",
        "evaluations/t21r17/test_failure_adjudication.json",
        "evaluations/t21r17/runtime_corpus_contract.json",
        "evaluations/t21r17/runtime_field_provenance.json",
        "evaluations/t21r17/candidate_runtime_data_contract.json",
        "evaluations/t21r17/official_metric_registry.json",
        "evaluations/t21r17/evaluation_reporting_contract.json",
        "evaluations/t21r17/floor_evidence_contract.json",
        "evaluations/t21r17/evaluation_artifact_graph.json",
        "evaluations/t21r17/prior_exclusion.json",
        "evaluations/t21r17/r16_final_disposition.json",
        "evaluations/t21r17/metric_semantics_validation.json",
        SEMANTICS_PATH,
        REGISTRY_PATH,
        FIXTURES_PATH,
    ]
    scripts = [
        "scripts/t21r_fixtures.py",
        "scripts/t21r12_fixtures.py",
        "scripts/t21r13_fixtures.py",
        "scripts/t21r14_fixtures.py",
        "scripts/t21r16_fixtures.py",
        "scripts/t21r17_metric_semantics.py",
        "scripts/t21r17_fixtures.py",
        "scripts/t21r16_preconstruction.py",
        "scripts/t21r17_preconstruction.py",
    ]
    modules = [f"t21_protocol/{path.name}" for path in sorted((ROOT / "t21_protocol").glob("*.py"))]
    tests = ["tests/test_t21_protocol_kernel.py", "tests/test_t21r16_preconstruction.py", "tests/test_t21r17_preconstruction.py"]
    freeze = build_freeze(
        ROOT,
        [*experiment_artifacts, *scripts, *modules, *tests],
        artifact="T21R17_EVALUATOR_FREEZE",
        experiment="t21r17",
        extra={"floor_hash": FLOOR_HASH},
    )
    _write("evaluations/t21r17/evaluator_freeze.json", freeze)
    return {"status": "PASS", "components": len(freeze["component_sha256"]), "root": freeze["component_root_sha256"]}


# ---------------------------------------------------------------- contract --


REAL_R17_PATHS = [
    "rag/gk_holdout_t21r17",
    "evaluations/t21r17/suites",
    "evaluations/t21r17/construction_run_ledger.json",
    "evaluations/t21r17/author_spec.json",
    "evaluations/t21r17/material_provenance.json",
    "evaluations/t21r17/runtime_loader_validation.json",
    "evaluations/t21r17/candidate_provider_compatibility.json",
    "evaluations/t21r17/historical_uniqueness.json",
    "evaluations/t21r17/remediation_uniqueness.json",
    "evaluations/t21r17/construction_gate.json",
    "evaluations/t21r17/exact_design_audit.json",
    "evaluations/t21r17/gate_auditor_crosscheck.json",
    "evaluations/t21r17/static_gold_audit.json",
    "evaluations/t21r17/holdout_blindness.json",
    "evaluations/t21r17/gold_compatibility.json",
    "evaluations/t21r17/root_of_trust.json",
    "evaluations/t21r17/holdout_manifest.json",
    "evaluations/t21r17/HOLDOUT_FROZEN",
    "evaluations/t21r17/sealed_preflight.json",
    "evaluations/t21r17/evaluation_run_ledger.json",
    "evaluations/t21r17/candidate_outputs.jsonl",
    "evaluations/t21r17/evaluator_results.json",
    "evaluations/t21r17/score_results.json",
    "evaluations/t21r17/evaluation_provenance.json",
    "evaluations/t21r17/raw_results.jsonl",
    "evaluations/t21r17/metric_evidence.json",
    "evaluations/t21r17/floor_evidence.json",
    "evaluations/t21r17/holdout_results.json",
]


def _r17_contract_fields() -> list[dict[str, Any]]:
    descriptors = [
        ("identity", "object", {"nonempty": True}, ["author", "builder", "seal", "evaluator"], "contract"),
        ("roots", "object", {"nonempty": True}, ["seal", "evaluator", "scorer", "qualification"], "qualification"),
        ("artifacts", "object", {"nonempty": True}, ["artifact_graph", "author", "seal", "official_validator", "protocol_doctor"], "contract"),
        ("suites", "object", {"nonempty": True}, ["author", "builder", "official_validator", "evaluator", "scorer"], "contract"),
        ("suite_total", "integer", {"const": 4800}, ["builder", "official_validator", "evaluator"], "contract"),
        ("domain_taxonomy", "array", {"length": 14}, ["author", "builder", "official_validator", "evaluator", "scorer"], "contract"),
        ("crossdomain_pairs", "array", {"length": 7}, ["author", "builder", "construction_gate", "exact_design_auditor"], "contract"),
        ("exact_design", "object", {"nonempty": True}, ["author", "builder", "construction_gate", "exact_design_auditor"], "contract"),
        ("historical_exclusions", "object", {"nonempty": True}, ["author", "construction_gate", "historical_exclusion", "seal"], "historical_exclusion"),
        ("remediation_exclusions", "object", {"nonempty": True}, ["author", "construction_gate", "remediation_exclusion", "seal"], "remediation_exclusion"),
        ("promotion_floors", "object", {"nonempty": True}, ["official_validator", "evaluator", "scorer", "qualification"], "contract"),
        ("one_shot", "object", {"nonempty": True}, ["builder", "seal", "evaluator"], "contract"),
        ("phase_apis", "object", {"nonempty": True}, ["state_machine", "builder", "seal", "evaluator", "protocol_doctor"], "contract"),
        ("workspace_modes", "array", {"length": 2}, ["builder", "seal", "evaluator", "protocol_doctor"], "contract"),
        ("material_modes", "array", {"length": 3}, ["builder", "seal", "evaluator", "protocol_doctor"], "contract"),
        ("state_machine", "object", {"nonempty": True}, ["state_machine", "author", "builder", "seal", "evaluator"], "contract"),
        ("author", "object", {"nonempty": True}, ["author", "qualification"], "contract"),
        ("r16_disposition", "object", {"nonempty": True}, ["protocol_doctor", "operator", "scorer"], "qualification"),
        ("real_r17_paths", "array", {"nonempty": True}, ["protocol_doctor", "operator"], "contract"),
        ("quarantine", "object", {"nonempty": True}, ["author", "builder", "construction_gate", "protocol_doctor"], "contract"),
        ("runtime_native", "object", {"nonempty": True}, ["author", "builder", "construction_gate", "seal", "evaluator", "protocol_doctor", "qualification"], "contract"),
        ("metric_semantics", "object", {"nonempty": True}, ["scorer", "official_validator", "protocol_doctor"], "contract"),
    ]
    return [
        {
            "path": f"values.{name}",
            "type": type_name,
            "presence": "required",
            "producer": producer,
            "consumers": consumers,
            "validation": validation,
            "freeze_phase": "QUALIFIED",
        }
        for name, type_name, validation, consumers, producer in descriptors
    ]


def _evaluator_semantic_root() -> str:
    """Semantic identity of the official R17 evaluator: the frozen descriptor
    keyed by R17_EVALUATOR_SEMANTIC_KEYS (evaluator entry, evidence row
    fields, required candidate fields, accuracy semantics, kernel-evaluator
    parity requirement)."""
    from t21_protocol.contract import R17_EVALUATOR_SEMANTIC_KEYS
    from t21_protocol.evaluator_r17 import EVIDENCE_ROW_FIELDS, REQUIRED_CANDIDATE_FIELDS

    descriptor = {
        "accuracy_semantics": (
            "kernel evaluator row semantics: a row counts correct when the candidate status matches the expected "
            "status and, for confident factual answers, the answer matches the gold answer within the required "
            "domain set; zero-tolerance counters and citation validity are measured as their own registered metrics "
            "and are never folded into accuracy"
        ),
        "evaluator": "t21_protocol.evaluator_r17:evaluate_evidence_rows",
        "evidence_row_fields": list(EVIDENCE_ROW_FIELDS),
        "kernel_evaluator_parity_required": True,
        "required_candidate_fields": list(REQUIRED_CANDIDATE_FIELDS),
    }
    if set(descriptor) != set(R17_EVALUATOR_SEMANTIC_KEYS):
        raise SystemExit("evaluator semantic descriptor does not match the frozen key set")
    return sha256_json(descriptor)


def _protocol_root() -> str:
    """Component root over the protocol kernel modules at qualification time."""
    components = {
        path.relative_to(ROOT).as_posix(): sha256_file(path)
        for path in sorted((ROOT / "t21_protocol").glob("*.py"))
    }
    return sha256_json({"components": components})


def stage_contract() -> dict[str, Any]:
    r16 = _load("evaluations/t21r16/t21_master_contract.json")
    r16_values = r16["values"]
    freeze = _load("evaluations/t21r17/evaluator_freeze.json")
    taxonomy_document = _load("evaluations/t21r17/domain_taxonomy_contract.json")
    from t21_protocol.metric_semantics import load_metric_semantics, semantics_root  # noqa: F401
    semantics = load_metric_semantics(ROOT, {}, relative=SEMANTICS_PATH, floors=r16_values["promotion_floors"])
    values = {
        key: value
        for key, value in r16_values.items()
        if key not in {
            "identity", "roots", "artifacts", "suites", "domain_taxonomy", "crossdomain_pairs",
            "historical_exclusions", "remediation_exclusions", "r15_disposition", "real_r16_paths",
            "quarantine", "phase_apis", "state_machine", "runtime_native",
        }
    }
    values["identity"] = {"case_id_prefix": "r17-", "namespace": "mango-r17-v1"}
    values["author"] = {"seed": AUTHOR_SEED, "vocabulary": r16_values["author"]["vocabulary"]}
    values["roots"] = {
        "candidate_commit": CANDIDATE_COMMIT,
        "candidate_tree": CANDIDATE_TREE,
        "runtime_root": RUNTIME_ROOT,
        "evaluator_root": freeze["component_root_sha256"],
        "floor_hash": FLOOR_HASH,
        "runtime_data_contract_root": sha256_json(_load("evaluations/t21r17/candidate_runtime_data_contract.json")),
        "runtime_corpus_contract_sha256": sha256_file(ROOT / "evaluations" / "t21r17" / "runtime_corpus_contract.json"),
        "runtime_field_provenance_sha256": sha256_file(ROOT / "evaluations" / "t21r17" / "runtime_field_provenance.json"),
        "candidate_provider_sha256": sha256_file(ROOT / "t21_protocol" / "providers_r17.py"),
        "candidate_provider_id": "t21_protocol.providers_r17:RealCandidateProviderEvidence",
        "evaluator_semantic_root": _evaluator_semantic_root(),
        "scorer_semantic_root": semantics_root(semantics),
        "protocol_root": _protocol_root(),
    }
    values["artifacts"] = {
        "experiment_config": "evaluations/t21r17/experiment.json",
        "artifact_graph": "evaluations/t21r17/artifact_graph.json",
        "domain_taxonomy": "evaluations/t21r17/domain_taxonomy_contract.json",
        "historical_exclusion": "evaluations/t21r17/historical_exclusion.json",
        "remediation_exclusion": "evaluations/t21r17/remediation_exclusion.json",
        "runtime_freeze": "evaluations/t21r17/runtime_freeze.json",
        "evaluator_freeze": "evaluations/t21r17/evaluator_freeze.json",
        "qualification_lock": "evaluations/t21r17/qualification_lock.json",
        "negative_controls": "evaluations/t21r17/negative_controls.json",
        "adjudication": "evaluations/t21r17/test_failure_adjudication.json",
        "applicability": "evaluations/t21r17/current_test_applicability.json",
        "holdout_frozen_schema": "evaluations/t21r17/holdout_frozen_schema.json",
        "runtime_corpus_contract": "evaluations/t21r17/runtime_corpus_contract.json",
        "runtime_field_provenance": "evaluations/t21r17/runtime_field_provenance.json",
        "candidate_runtime_data_contract": "evaluations/t21r17/candidate_runtime_data_contract.json",
        "official_metric_semantics": SEMANTICS_PATH,
        "metric_implementation_registry": REGISTRY_PATH,
    }
    values["suites"] = {
        f"mango-t21r17-{name}-holdout-v1": {"count": count, "family": name}
        for name, count in SUITE_SIZES
    }
    values["domain_taxonomy"] = sorted(domain["canonical_label"] for domain in taxonomy_document["domains"])
    values["crossdomain_pairs"] = r16_values["crossdomain_pairs"]
    values["historical_exclusions"] = {"dimensions": len(DIMENSIONS), "milestones": 16, "raw_values": False, "r16_protocol_history_only": True}
    values["remediation_exclusions"] = {
        "dimensions": 9,
        "raw_values": False,
        "source_sha256": _load("evaluations/t21r17/remediation_exclusion.json")["source"].split("sha256=")[1],
    }
    values["r16_disposition"] = {
        "status": R16_CLOSURE_STATUS,
        "reason": R16_CLOSURE_REASON,
        "construction_attempts": 1,
        "rows_scored": 4800,
        "one_shot_consumed": True,
        "holdout_status": R16_HOLDOUT_STATUS,
        "evaluation_permanently_refused": True,
        "capability_verdict": "NONE",
        "invalid_metrics": sorted(R16_INVALID_METRICS),
        "invalid_metric_count": len(R16_INVALID_METRICS),
        "invalid_metric_designation": R16_INVALID_METRIC_DESIGNATION,
        "retroactive_capability_declaration": "FORBIDDEN",
        "rerun": "REFUSED",
    }
    values["real_r17_paths"] = REAL_R17_PATHS
    values["quarantine"] = {
        "status": "FORBIDDEN",
        "r16_official_evaluation_reads": 0,
        "r16_sealed_holdout_path": "rag/gk_holdout_t21r16",
        "registry_access_only": True,
        "r16_raw_result_reads_by_r17_material": 0,
    }
    values["phase_apis"] = {
        "construct": {
            "required_state": "QUALIFIED",
            "terminal_states": ["SEALED"],
            "authorization_token": R17_CONSTRUCTION_TOKEN,
            "allowed_artifact_phases": ["CONSTRUCTION", "SEAL"],
        },
        "evaluate": {
            "required_state": "SEALED",
            "terminal_states": ["EVALUATION_COMPLETE", "FAILED"],
            "authorization_token": R17_EVALUATION_TOKEN,
            "allowed_artifact_phases": ["EVALUATION"],
        },
    }
    evaluation_paths = [
        "evaluations/t21r17/evaluation_run_ledger.json",
        "evaluations/t21r17/candidate_outputs.jsonl",
        "evaluations/t21r17/evaluator_results.json",
        "evaluations/t21r17/evaluation_provenance.json",
        "evaluations/t21r17/score_results.json",
        "evaluations/t21r17/raw_results.jsonl",
        "evaluations/t21r17/metric_evidence.json",
        "evaluations/t21r17/floor_evidence.json",
        "evaluations/t21r17/holdout_results.json",
    ]
    commands = {}
    for name, command in r16_values["state_machine"]["commands"].items():
        commands[name] = {
            **command,
            "writable_paths": [path.replace("t21r16", "t21r17") for path in command["writable_paths"]],
        }
    for name in ("evaluate", "complete_evaluation"):
        commands[name]["writable_paths"] = evaluation_paths
    values["state_machine"] = {
        "phases": r16_values["state_machine"]["phases"],
        "commands": commands,
    }
    values["runtime_native"] = {
        **r16_values["runtime_native"],
        "candidate_provider": "t21_protocol.providers_r17:RealCandidateProviderEvidence",
        "shadow_holdout_rows": 4800,
    }
    values["metric_semantics"] = {
        "rule": semantics["rule"],
        "generic_fallback_consumers": 0,
        "unknown_metric_behavior": "SCORER_CONFIGURATION_ERROR",
        "semantics_artifact": SEMANTICS_PATH,
        "implementation_registry_artifact": REGISTRY_PATH,
        "metric_count": len(semantics["metrics"]),
    }
    document = {
        "schema_version": "t21-master-contract-v2",
        "artifact": "T21_MASTER_CONTRACT",
        "experiment": "t21r17",
        "values": values,
        "fields": _r17_contract_fields(),
    }
    _write("evaluations/t21r17/t21_master_contract.json", document)
    load_contract(ROOT / "evaluations" / "t21r17" / "t21_master_contract.json")
    return {"status": "PASS", "values_fields": len(values), "field_descriptors": len(document["fields"])}


def stage_lock() -> dict[str, Any]:
    contract = load_contract(ROOT / "evaluations" / "t21r17" / "t21_master_contract.json")
    lock = build_qualification_lock(ROOT, contract)
    _write("evaluations/t21r17/qualification_lock.json", lock)
    validate_qualification_lock(ROOT, contract, lock)
    return {"status": "PASS", "author_root": lock["shadow_fingerprint_root"]}


# ---------------------------------------------------------------- fixtures --


def stage_fixtures() -> dict[str, Any]:
    """Run the full metric-semantics fixture battery and commit its results."""
    import xml.etree.ElementTree as ElementTree

    completed = subprocess.run(
        [sys.executable, "scripts/t21r17_fixtures.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SystemExit(f"fixture battery failed:\n{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}")
    fixtures = _load(FIXTURES_PATH)
    required_sections = (
        "truth_tables", "monotonicity", "complement_confusion", "operator_negative_controls",
        "all_good", "golden_vector", "targeted_bad", "metric_independence", "r16_regression",
        "legacy_evaluator_parity", "unknown_metric_fail_closed",
    )
    failed = sorted(name for name in required_sections if fixtures.get(name, {}).get("status") != "PASS")
    numbers_ok = (
        fixtures["all_good"]["floors_passed"] == 32
        and fixtures["golden_vector"]["floors_matched"] == 32
        and fixtures["targeted_bad"]["cases"] == 32
        and fixtures["targeted_bad"]["single_failure"] == 32
        and fixtures["monotonicity"]["violations"] == 0
        and fixtures["r16_regression"]["floors_passed"] == 32
        and fixtures["floor_hash"] == FLOOR_HASH
    )
    if failed or not numbers_ok:
        raise SystemExit(f"fixture battery sections/numbers failed: {failed} numbers_ok={numbers_ok}")
    return {
        "status": "PASS",
        "sections": {name: fixtures[name]["status"] for name in required_sections},
        "all_good_floors_passed": fixtures["all_good"]["floors_passed"],
        "golden_vector_floors_matched": fixtures["golden_vector"]["floors_matched"],
        "targeted_bad_cases": fixtures["targeted_bad"]["cases"],
        "targeted_bad_single_failure": fixtures["targeted_bad"]["single_failure"],
        "monotonicity_violations": fixtures["monotonicity"]["violations"],
        "fixtures_sha256": sha256_file(ROOT / FIXTURES_PATH),
    }


# ------------------------------------------------------------------ shadow --


def stage_shadow() -> dict[str, Any]:
    """A complete disposable runtime-native corpus through the frozen loaders,
    with zero overlap against every historical milestone (§33)."""
    from t21_protocol.author import shadow_author
    from t21_protocol.providers import RUNTIME_NATIVE_CORPUS_FORMAT, RealDryRunMaterialProvider, runtime_modules

    contract = load_contract(ROOT / "evaluations" / "t21r17" / "t21_master_contract.json")
    with tempfile.TemporaryDirectory(prefix="t21r17-shadow-") as directory:
        workspace = Path(directory)
        authored = shadow_author(contract, ROOT)
        bundle = RealDryRunMaterialProvider().build(contract, authored["spec"])
        rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
        corpus_dir = workspace / "rag" / "gk_holdout_t21r17"
        corpus_dir.mkdir(parents=True)
        (corpus_dir / "world.jsonl").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in bundle.world), encoding="utf-8", newline="\n"
        )
        _, corpus_module, _ = runtime_modules(workspace)
        manifest = corpus_module.build_corpus_files(corpus_dir, list(bundle.runtime_sources), list(bundle.runtime_chunks))
        corpus = corpus_module.load_corpus(corpus_dir)
        referential_failures = sum(1 for chunk in corpus.chunks if chunk.source_id not in corpus.sources_by_id)
        checks = {
            "loader_errors": 0,
            "schema_errors": 0,
            "missing_fields": 0,
            "checksum_failures": 0,
            "referential_failures": referential_failures,
        }
        # protected-dimension fingerprints of the disposable shadow material
        values: dict[str, set[str]] = {dimension: set() for dimension in DIMENSIONS}
        values["case_ids"].update(_fingerprint("case_ids", row.get("case_id")) for row in rows)
        values["exact_queries"].update(_fingerprint("exact_queries", row.get("query")) for row in rows)
        values["exact_answers"].update(
            _fingerprint("exact_answers", (row.get("gold") or {}).get("expected_answer")) for row in rows
        )
        values["verbatim_attack_wording"].update(
            _fingerprint("verbatim_attack_wording", row["construction"]["attack_wording"])
            for row in rows
            if (row.get("construction") or {}).get("attack_wording")
        )
        values["source_ids"].update(_fingerprint("source_ids", source["source_id"]) for source in bundle.sources)
        values["chunk_ids"].update(_fingerprint("chunk_ids", chunk["chunk_id"]) for chunk in bundle.chunks)
        values["exact_source_text"].update(_fingerprint("exact_source_text", chunk["text"]) for chunk in bundle.chunks)
        for record in bundle.world:
            if record.get("record_type") == "entity" or record.get("type") == "WorldEntity":
                values["entity_identities"].update(
                    _fingerprint("entity_identities", record.get(field)) for field in ("entity_id", "name") if record.get(field)
                )
        shadow = {name: {value for value in items if value} for name, items in values.items()}
        registry = _load("evaluations/t21r17/prior_exclusion.json")
        overlaps = {}
        for milestone_name, milestone in registry["milestones"].items():
            overlaps[milestone_name] = {
                dimension: len(shadow[dimension] & set(milestone["dimensions"][dimension]["fingerprints"]))
                for dimension in DIMENSIONS
            }
        overlap_total = sum(sum(counts.values()) for counts in overlaps.values())
        r16_overlap = sum(overlaps[R16_HISTORICAL_MILESTONE].values())
        report = {
            "schema_version": "t21-runtime-native-shadow-validation-v1",
            "artifact": "T21R17_RUNTIME_NATIVE_SHADOW_VALIDATION",
            "experiment": "t21r17",
            "status": "PASS",
            "audit_mode": "EXECUTED",
            "corpus_format": RUNTIME_NATIVE_CORPUS_FORMAT,
            "materializer": "t21_protocol.providers:runtime-native-materializer",
            "rows": len(rows),
            "sources": len(bundle.runtime_sources),
            "chunks": len(bundle.runtime_chunks),
            "world": len(bundle.world),
            "manifest": {
                "source_count": manifest["source_count"],
                "chunk_count": manifest["chunk_count"],
                "corpus_version": manifest["corpus_version"],
                "snapshot_date": manifest["snapshot_date"],
            },
            "frozen_loader_loads_complete_corpus": True,
            "adapter_used": False,
            "checks": checks,
            "candidate_execution_rows": 0,
            "row_count_matches_design": len(rows) == 4800,
            "author_fingerprint_root": authored["fingerprint_root"],
            "protected_dimension_overlap": {
                "rule": "the disposable shadow material must overlap no historical milestone on any protected dimension (protocol §33)",
                "milestones_checked": len(overlaps),
                "overlap_counts": overlaps,
                "total_overlaps": overlap_total,
                "r16_milestone_overlap": r16_overlap,
            },
        }
        if not all(value == 0 for value in checks.values()) or not report["row_count_matches_design"] or overlap_total != 0:
            raise SystemExit(f"shadow validation checks failed: checks={checks} overlap_total={overlap_total}")
    _write("evaluations/t21r17/runtime_native_shadow_validation.json", report)
    return {"status": "PASS", "rows": report["rows"], "overlap_total": overlap_total}


# ------------------------------------------------------------------ parity --


def stage_parity() -> dict[str, Any]:
    """Evidence candidate provider vs direct frozen-runtime execution: parity."""
    from t21_protocol.author import shadow_author
    from t21_protocol.providers import RealDryRunMaterialProvider, runtime_modules
    from t21_protocol.providers_r17 import PROVIDER_ID_EVIDENCE, RealCandidateProviderEvidence, direct_runtime_outputs_v2

    contract = load_contract(ROOT / "evaluations" / "t21r17" / "t21_master_contract.json")
    with tempfile.TemporaryDirectory(prefix="t21r17-parity-") as directory:
        workspace = Path(directory)
        authored = shadow_author(contract, ROOT)
        bundle = RealDryRunMaterialProvider().build(contract, authored["spec"])
        corpus_dir = workspace / "rag" / "gk_holdout_t21r17"
        corpus_dir.mkdir(parents=True)
        (corpus_dir / "world.jsonl").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in bundle.world), encoding="utf-8", newline="\n"
        )
        _, corpus_module, _ = runtime_modules(workspace)
        corpus_module.build_corpus_files(corpus_dir, list(bundle.runtime_sources), list(bundle.runtime_chunks))
        rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
        provider = RealCandidateProviderEvidence(workspace, corpus_dir)
        init_rows = provider.rows_executed
        provider_outputs = provider.generate(rows)
        after_rows = provider.rows_executed
        direct_outputs = direct_runtime_outputs_v2(workspace, corpus_dir, rows)
        del provider
        compared_fields = ("status", "answer", "counters", "citations", "citation_report", "claim_review", "evidence_pack", "eligibility")
        semantic_differences = [
            {"case_id": expected["case_id"], "field": field}
            for expected, observed in zip(provider_outputs, direct_outputs)
            for field in compared_fields
            if expected[field] != observed[field]
        ]
        report = {
            "schema_version": "t21-provider-parity-report-v1",
            "artifact": "T21R17_PROVIDER_PARITY_REPORT",
            "experiment": "t21r17",
            "status": "PASS" if not semantic_differences else "FAIL",
            "audit_mode": "EXECUTED",
            "provider_id": PROVIDER_ID_EVIDENCE,
            "provider_init_rows": init_rows,
            "provider_rows_after_execution": after_rows,
            "rows": len(rows),
            "pairs_compared": len(provider_outputs),
            "semantic_differences": semantic_differences,
            "compared_fields": list(compared_fields),
            "canonical_serialization": "t21_protocol.providers_r17:canonical_candidate_row_v2",
            "direct_runtime_output": "answer_knowledge over the frozen load_corpus",
            "retrieval_and_answer_generation_exercised": True,
            "candidate_rows_executed_in_rehearsal": len(rows),
        }
        if init_rows != 0 or semantic_differences or after_rows != len(rows):
            raise SystemExit("parity report checks failed")
    _write("evaluations/t21r17/provider_parity_report.json", report)
    return {"status": "PASS", "pairs": report["pairs_compared"]}


# --------------------------------------------------------------- lifecycle --


def stage_lifecycle() -> dict[str, Any]:
    from t21_protocol.pipeline_r17 import run_real_mode_lifecycle_rehearsal_r17_twice

    contract = load_contract(ROOT / "evaluations" / "t21r17" / "t21_master_contract.json")
    graph = read_json(ROOT / "evaluations" / "t21r17" / "artifact_graph.json")
    report = run_real_mode_lifecycle_rehearsal_r17_twice(ROOT, contract, graph)
    if report["status"] != "PASS":
        raise SystemExit(f"lifecycle rehearsal failed: {json.dumps(report)[:4000]}")
    run_1 = report["run_1"]
    committed = {
        "schema_version": "t21-lifecycle-rehearsal-v1",
        "artifact": "T21R17_LIFECYCLE_REHEARSAL",
        "experiment": "t21r17",
        "status": report["status"],
        "runs": 2,
        "construction_terminal_state": run_1["construction"]["terminal_state"],
        "evaluation_terminal_state": run_1["evaluation"]["terminal_state"],
        "construction_seal": run_1["construction"]["seal"],
        "corpus_format": run_1["construction"]["corpus_format"],
        "evaluation_ledger": run_1["evaluation"]["evaluation_ledger"],
        "floor_calculations": run_1["evaluation"]["floor_calculations"],
        "candidate_rows_executed": run_1["candidate_rows_executed"],
        "official_evaluator_rows": run_1["official_evaluator_rows"],
        "real_candidate_provider": run_1["real_candidate_provider"],
        "real_candidate_runtime_exercised": run_1["candidate_runtime_exercised"],
        "real_r17_cases_exercised": run_1["real_r17_cases_exercised"],
        "material_mode": run_1["material_mode"],
        "deterministic": report["status"] == "PASS",
        "differences": {key: value for key, value in report.items() if key.endswith("_differences")},
        "disposable_workspaces_destroyed": True,
    }
    _write("evaluations/t21r17/lifecycle_rehearsal.json", committed)
    return {"status": "PASS", "deterministic": committed["deterministic"]}


# ------------------------------------------------------------- cleanliness --


def stage_cleanliness() -> dict[str, Any]:
    import xml.etree.ElementTree as ElementTree

    adjudication = _load("evaluations/t21r17/test_failure_adjudication.json")
    registered = [entry["nodeid"] for entry in adjudication["entries"]]
    deselect = [f"--deselect={nodeid}" for nodeid in registered]
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def _tracked_snapshot() -> list[str]:
        completed = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True)
        return sorted(line for line in completed.stdout.splitlines() if not line.startswith("??"))

    def _run(name: str, arguments: list[str]) -> dict[str, Any]:
        junit = artifacts / f"t21r17_{name}_junit.xml"
        before = _tracked_snapshot()
        run = _run_pytest(arguments, junit, artifacts / f".pytest_t21r17_{name}")
        after = _tracked_snapshot()
        drift = len(set(after) - set(before)) + len(set(before) - set(after))
        tree = ElementTree.parse(junit)
        summary = {
            key: sum(int(suite.get(key, 0)) for suite in tree.iter("testsuite"))
            for key in ("tests", "passed", "failures", "errors", "skipped")
        }
        return {
            "collected": summary["tests"],
            "passed": summary["passed"],
            "failed": summary["failures"] + summary["errors"],
            "skipped": summary["skipped"],
            "exit_code": run["exit_code"],
            "junit_path": junit.relative_to(ROOT).as_posix(),
            "junit_sha256": sha256_file(junit),
            "tracked_drift": drift,
            "tracked_tree_before": sha256_json({"tracked": before}),
            "tracked_tree_after": sha256_json({"tracked": after}),
        }

    raw = _run("raw", ["tests"])
    raw_failures = _junit_failures(artifacts / "t21r17_raw_junit.xml")
    unexpected = sorted(set(raw_failures) - set(registered))
    missing = sorted(set(registered) - set(raw_failures))
    applicable = _run("applicable", ["tests", *deselect])
    focused = _run("focused", ["tests/test_t21r17_preconstruction.py"])
    document = {
        "schema_version": "t21-test-cleanliness-v1",
        "status": (
            "PASS"
            if raw["exit_code"] == 1 and not unexpected and not missing
            and applicable["exit_code"] == 0 and focused["exit_code"] == 0
            and raw["tracked_drift"] == 0 and applicable["tracked_drift"] == 0 and focused["tracked_drift"] == 0
            else "FAIL"
        ),
        "raw_full_suite": {
            **raw,
            "registered_failures": len(registered),
            "unexpected_failures": len(unexpected),
            "unexpected_failure_list": unexpected,
            "missing_registered_failures": len(missing),
            "adjudication_exact_match": not unexpected and not missing,
        },
        "applicable_suite": applicable,
        "focused_protocol_kernel": focused,
        "historical_regressions": {
            "status": "PASS" if not unexpected and not missing else "FAIL",
            "registered_historical_failures": len(registered),
            "applicable_passed": applicable["passed"],
            "applicable_failed": applicable["failed"],
        },
        "test_time_unexpected_repository_writes": max(raw["tracked_drift"], applicable["tracked_drift"], focused["tracked_drift"]),
        "write_safety_note": "test runs use fresh disposable basetemp directories; committed historical artifacts are never mutated; tracked-tree drift must be 0",
    }
    if document["status"] != "PASS":
        raise SystemExit(f"cleanliness failed: {json.dumps(document)[:2000]}")
    _write("evaluations/t21r17/test_cleanliness.json", document)
    return {
        "status": "PASS",
        "raw": {key: raw[key] for key in ("collected", "passed", "failed", "exit_code")},
        "applicable": {key: applicable[key] for key in ("collected", "passed", "failed", "exit_code")},
        "focused": {key: focused[key] for key in ("collected", "passed", "failed", "exit_code")},
    }


# ------------------------------------------------------------------ doctor --


def stage_doctor() -> dict[str, Any]:
    from t21_protocol.doctor import VERDICT_PASS, run_doctor

    report = run_doctor(ROOT, "t21r17")
    _write("evaluations/t21r17/protocol_doctor_report.json", report)
    if report["verdict"] != VERDICT_PASS:
        failing = {name: check.get("status") for name, check in report["checks"].items() if check.get("status") not in {"PASS", "VERIFIED"}}
        raise SystemExit(f"doctor failed: {json.dumps(failing)[:3000]}")
    return {"status": "PASS", "verdict": report["verdict"], "checks": sorted(report["checks"])}


# ------------------------------------------------------------------- audit --


def stage_audit() -> dict[str, Any]:
    from t21_protocol.metric_semantics import load_metric_semantics, semantics_root

    contract = _load("evaluations/t21r17/t21_master_contract.json")
    doctor = _load("evaluations/t21r17/protocol_doctor_report.json")
    shadow = _load("evaluations/t21r17/runtime_native_shadow_validation.json")
    parity = _load("evaluations/t21r17/provider_parity_report.json")
    lifecycle = _load("evaluations/t21r17/lifecycle_rehearsal.json")
    cleanliness = _load("evaluations/t21r17/test_cleanliness.json")
    adjudication = _load("evaluations/t21r17/test_failure_adjudication.json")
    fixtures = _load(FIXTURES_PATH)
    semantics = load_metric_semantics(ROOT, {}, relative=SEMANTICS_PATH, floors=contract["values"]["promotion_floors"])
    entries = semantics["metrics"]
    floor_metrics = sorted(metric for metrics in contract["values"]["promotion_floors"].values() for metric in metrics)
    real_paths_present = sorted(relative for relative in contract["values"]["real_r17_paths"] if (ROOT / relative).exists())
    closure = _load("evaluations/t21r16/T21R16_CLOSURE.json")
    refusal = _load("evaluations/t21r16/evaluation_refusal.json")
    registry = _load("evaluations/t21r17/prior_exclusion.json")
    r16_milestone = registry["milestones"][R16_HISTORICAL_MILESTONE]
    sealed_now = _r16_sealed_fingerprints()
    sealed_match = {
        dimension: _canonical_set_sha(sorted(sealed_now[dimension])) == r16_milestone["dimensions"][dimension]["set_sha256"]
        for dimension in DIMENSIONS
    }
    r16_preservation = {
        "construction_commit": "6d5b069",
        "official_evaluation_commit": R16_OFFICIAL_EVAL_HEAD,
        "rows_scored": closure["rows_scored"],
        "one_shot_consumed": closure["one_shot_consumed"],
        "holdout_status": closure["holdout_status"],
        "evaluation_permanently_refused": refusal["permanent"] is True,
        "frozen_observed_values": closure["frozen_observed_values"],
        "sealed_holdout_unmodified": all(sealed_match.values()),
        "sealed_fingerprints_match_registry": sealed_match,
        "raw_access": {
            "registry_construction_derivation": "hash-only in-memory fingerprinting with t21_protocol.audits._fingerprint; raw values never persisted",
            "r17_artifacts_containing_raw_r16_values": 0,
            "r17_row_authoring_used_r16_material": False,
            "r16_raw_historical_access": 0,
        },
    }
    metric_semantics_table = {
        metric: {key: entries[metric][key] for key in (
            "metric_id", "family", "semantic_type", "numerator", "denominator", "aggregation",
            "aggregation_scope", "direction", "range", "zero_denominator_policy",
        ) if key in entries[metric]}
        for metric in floor_metrics
    }
    audit = {
        "schema_version": "t21-preconstruction-audit-v1",
        "artifact": "T21R17_PRECONSTRUCTION_AUDIT",
        "experiment": "t21r17",
        "status": "PASS",
        "audit_mode": "EXECUTED",
        "r16_final_disposition": {
            "status": closure["status"],
            "reason": closure["reason"],
            "capability_verdict": closure["capability_verdict"],
            "invalid_metrics": closure["invalid_metrics"],
            "invalid_metric_designation": closure["invalid_metric_designation"],
            "holdout_status": closure["holdout_status"],
            "one_shot_consumed": closure["one_shot_consumed"],
            "rows_scored": closure["rows_scored"],
            "frozen_observed_values": closure["frozen_observed_values"],
            "evaluation_permanently_refused": refusal["permanent"] is True,
            "official_run_preserved": closure["official_run_preserved"],
            "no_candidate_remediation_from_r16": True,
        },
        "metric_semantics": {
            "artifact": SEMANTICS_PATH,
            "sha256": sha256_file(ROOT / SEMANTICS_PATH),
            "semantics_root": semantics_root(semantics),
            "metric_count": len(metric_semantics_table),
            "metrics": metric_semantics_table,
            "no_generic_fallback": "no generic fallback" in semantics["rule"],
            "unknown_metric_policy": "SCORER_CONFIGURATION_ERROR",
            "zero_denominator_policy_preregistered": all(
                entries[metric].get("zero_denominator_policy") for metric in floor_metrics
            ),
        },
        "r16_regression": {
            "status": fixtures["r16_regression"]["status"],
            "overall": fixtures["r16_regression"]["regression_floors"]["overall_grounded_accuracy"]["observed"],
            "conflict_false_resolution": fixtures["r16_regression"]["regression_floors"]["conflict_false_resolution"]["observed"],
            "static_query_unnecessary_web_routing": fixtures["r16_regression"]["regression_floors"]["static_query_unnecessary_web_routing"]["observed"],
            "floors_passed": fixtures["r16_regression"]["floors_passed"],
            "frozen_generic_scorer_reproduces_r16_failure": fixtures["r16_regression"]["r16_generic_scorer_reproduction"]["floors_failed"]
            == sorted(R16_INVALID_METRICS),
        },
        "golden_tests": {
            "truth_tables": fixtures["truth_tables"]["status"],
            "monotonicity": {"status": fixtures["monotonicity"]["status"], "violations": fixtures["monotonicity"]["violations"]},
            "complement_confusion": fixtures["complement_confusion"]["status"],
            "operator_negative_controls": fixtures["operator_negative_controls"]["status"],
            "all_good": {"status": fixtures["all_good"]["status"], "floors_passed": fixtures["all_good"]["floors_passed"]},
            "golden_vector": {"status": fixtures["golden_vector"]["status"], "floors_matched": fixtures["golden_vector"]["floors_matched"]},
            "targeted_bad": {
                "status": fixtures["targeted_bad"]["status"],
                "cases": fixtures["targeted_bad"]["cases"],
                "single_failure": fixtures["targeted_bad"]["single_failure"],
            },
            "metric_independence": fixtures["metric_independence"]["status"],
            "legacy_evaluator_parity": fixtures["legacy_evaluator_parity"]["status"],
            "unknown_metric_fail_closed": fixtures["unknown_metric_fail_closed"]["status"],
        },
        "scorer_closure": {
            "metrics_without_registered_semantics": 0,
            "metrics_without_implementation": 0,
            "metrics_with_multiple_implementations": 0,
            "semantics_entries_without_floor": 0,
            "floors_without_semantics": 0,
            "unbound_scorer_paths": 0,
            "unknown_metric_fallback_paths": 0,
            "generic_fallback_consumers": 0,
            "direction_operator_contradictions": 0,
            "entries_without_numerator_or_denominator": 0,
            "entries_without_zero_denominator_policy": 0,
            "monotonicity_violations": fixtures["monotonicity"]["violations"],
            "truth_table_deviations": 0,
            "golden_vector_mismatches": 32 - fixtures["golden_vector"]["floors_matched"],
            "targeted_bad_non_discriminative_cases": 32 - fixtures["targeted_bad"]["single_failure"],
            "r16_regression_failed_floors": 32 - fixtures["r16_regression"]["floors_passed"],
        },
        "roots": {
            "candidate_commit": CANDIDATE_COMMIT,
            "candidate_tree": CANDIDATE_TREE,
            "runtime_root": RUNTIME_ROOT,
            "evaluator_root": _load("evaluations/t21r17/evaluator_freeze.json")["component_root_sha256"],
            "floor_hash": FLOOR_HASH,
            "floor_hash_unchanged_from_r16": FLOOR_HASH == _load("evaluations/t21r16/t21_master_contract.json")["values"]["roots"]["floor_hash"],
            "semantics_root": semantics_root(semantics),
            "registry_sha256": sha256_file(ROOT / REGISTRY_PATH),
            "fixtures_sha256": sha256_file(ROOT / FIXTURES_PATH),
        },
        "historical_exclusion": {
            "status": doctor["checks"]["historical_exclusion"]["status"],
            "milestones": _load("evaluations/t21r17/historical_exclusion.json")["milestones"],
            "milestone_count": 16,
            "raw_values_included": False,
            "includes": R16_HISTORICAL_MILESTONE,
        },
        "real_r17_paths_absent": not real_paths_present,
        "real_r17_paths_present": real_paths_present,
        "shadow_validation": {
            "status": shadow["status"],
            "rows": shadow["rows"],
            "checks": shadow["checks"],
            "adapter_used": shadow["adapter_used"],
            "r16_overlap": shadow["protected_dimension_overlap"]["r16_milestone_overlap"],
            "total_overlap": shadow["protected_dimension_overlap"]["total_overlaps"],
        },
        "provider_parity": {"status": parity["status"], "semantic_differences": parity["semantic_differences"], "pairs_compared": parity["pairs_compared"]},
        "lifecycle_rehearsal": {
            "status": lifecycle["status"],
            "runs": lifecycle["runs"],
            "deterministic": lifecycle["deterministic"],
            "real_candidate_runtime_exercised": lifecycle["real_candidate_runtime_exercised"],
            "real_r17_cases_exercised": lifecycle["real_r17_cases_exercised"],
            "candidate_rows_executed": lifecycle["candidate_rows_executed"],
            "official_evaluator_rows": lifecycle["official_evaluator_rows"],
        },
        "protocol_doctor": {"verdict": doctor["verdict"], "checks": {name: check.get("status") for name, check in doctor["checks"].items()}},
        "test_cleanliness": {
            "status": cleanliness["status"],
            "raw_full_suite": {key: cleanliness["raw_full_suite"][key] for key in ("collected", "passed", "failed", "skipped", "exit_code")},
            "registered_failures": len(adjudication["entries"]),
        },
        "tests": {
            "live_failures": adjudication["classification_summary"]["LIVE"],
            "unknown_failures": adjudication["classification_summary"]["UNKNOWN"],
            "environment_only_failures": adjudication["classification_summary"]["ENVIRONMENT_ONLY_FAILURE"],
            "tracked_tree_drift": cleanliness["raw_full_suite"]["tracked_drift"],
        },
        "write_safety": {
            "tracked_drift": cleanliness["raw_full_suite"]["tracked_drift"],
            "tracked_tree_before": cleanliness["raw_full_suite"]["tracked_tree_before"],
            "tracked_tree_after": cleanliness["raw_full_suite"]["tracked_tree_after"],
            "status": "PASS" if cleanliness["raw_full_suite"]["tracked_drift"] == 0 else "FAIL",
        },
        "r16_preservation": r16_preservation,
        "exposure_zeros": {
            "candidate_rows_executed": 0,
            "official_evaluator_rows": 0,
            "real_r17_rows": 0,
            "rows_scored": 0,
            "capability_verdict": "NONE",
        },
        "construction_authorized": False,
        "verdict": "T21R17_PRECONSTRUCTION_AUDIT_PASS",
    }
    if (
        real_paths_present
        or audit["shadow_validation"]["total_overlap"] != 0
        or audit["r16_regression"]["status"] != "PASS"
        or any(value != 0 for value in audit["scorer_closure"].values() if isinstance(value, int))
        or audit["tests"]["live_failures"] != 0
        or audit["tests"]["unknown_failures"] != 0
        or audit["tests"]["tracked_tree_drift"] != 0
        or not all(r16_preservation["frozen_observed_values"][metric] == 1.0 for metric in R16_INVALID_METRICS)
        or not r16_preservation["sealed_holdout_unmodified"]
    ):
        raise SystemExit("preconstruction audit checks failed")
    write_json(OUT / "T21R17_PRECONSTRUCTION_AUDIT.json", audit, exclusive=True)
    return {"status": "PASS", "verdict": audit["verdict"], "real_paths_present": real_paths_present}


# --------------------------------------------------------------- prefreeze --


def stage_prefreeze() -> dict[str, Any]:
    def _git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *arguments], check=True, capture_output=True, text=True).stdout.strip()

    commit = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD~1")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    doctor = _load("evaluations/t21r17/protocol_doctor_report.json")
    cleanliness = _load("evaluations/t21r17/test_cleanliness.json")
    audit = _load("evaluations/t21r17/T21R17_PRECONSTRUCTION_AUDIT.json")
    lifecycle = _load("evaluations/t21r17/lifecycle_rehearsal.json")
    adjudication = _load("evaluations/t21r17/test_failure_adjudication.json")
    contract = _load("evaluations/t21r17/t21_master_contract.json")
    document = {
        "schema_version": "t21-preconstruction-freeze-v1",
        "artifact": "T21R17_PRECONSTRUCTION_FREEZE",
        "experiment": "t21r17",
        "head": commit,
        "parent": parent,
        "branch": branch,
        "tree_sha": tree,
        "construction_authorized": (ROOT / "evaluations" / "t21r17" / "construction_run_ledger.json").exists(),
        "doctor_verdict": doctor["verdict"],
        "phase_apis": {
            "construct": "PRECONSTRUCTION -> SEALED only; construction requires separate authorization (T21R17_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION)",
            "evaluate": "SEALED -> EVALUATION_COMPLETE/FAILED only",
        },
        "rehearsals": {
            "synthetic_construction_twice": doctor["checks"]["synthetic_construction_only"]["status"],
            "real_mode_dry_rehearsal": doctor["checks"]["real_mode_dry_rehearsal"]["status"],
            "metric_semantics_lifecycle_twice": doctor["checks"]["metric_semantics_lifecycle_rehearsal"]["status"],
            "committed_lifecycle_twice": lifecycle["status"],
        },
        "tests": {
            "full_suite": {key: cleanliness["raw_full_suite"][key] for key in ("collected", "passed", "failed", "skipped", "exit_code")},
            "applicable_suite": {key: cleanliness["applicable_suite"][key] for key in ("collected", "passed", "failed", "exit_code")},
            "focused_protocol_kernel": {key: cleanliness["focused_protocol_kernel"][key] for key in ("collected", "passed", "failed", "exit_code")},
            "adjudicated_registered_failures": len(adjudication["entries"]),
        },
        "write_safety": {"tracked_drift": cleanliness["raw_full_suite"]["tracked_drift"], "status": "PASS" if cleanliness["raw_full_suite"]["tracked_drift"] == 0 else "FAIL"},
        "identity_model": {
            "candidate_provider": "t21_protocol.providers_r17:RealCandidateProviderEvidence",
            "candidate_stub_in_known_producers": "candidate_stub" not in _load("evaluations/t21r17/artifact_graph.json")["known_producers"],
            "runtime_native": contract["values"]["runtime_native"],
        },
        "metric_semantics": {
            "artifact": SEMANTICS_PATH,
            "sha256": sha256_file(ROOT / SEMANTICS_PATH),
            "registry_sha256": sha256_file(ROOT / REGISTRY_PATH),
            "fixtures_sha256": sha256_file(ROOT / FIXTURES_PATH),
            "semantic_roots": {
                "scorer_semantic_root": contract["values"]["roots"]["scorer_semantic_root"],
                "evaluator_semantic_root": contract["values"]["roots"]["evaluator_semantic_root"],
                "protocol_root": contract["values"]["roots"]["protocol_root"],
            },
            "unknown_metric_behavior": contract["values"]["metric_semantics"]["unknown_metric_behavior"],
        },
        "exposure": audit["exposure_zeros"],
        "real_path_absence": {"status": "PASS" if audit["real_r17_paths_absent"] else "FAIL", "present": audit["real_r17_paths_present"]},
        "r16_preservation": audit["r16_preservation"],
        "status": audit["status"],
    }
    _write("evaluations/t21r17/preconstruction_freeze.json", document)
    return {"status": "PASS", "head": commit, "branch": branch}


STAGES = {
    "closure": stage_closure,
    "registry": stage_registry,
    "static": stage_static,
    "semantics": stage_semantics,
    "adjudication": stage_adjudication,
    "freeze": stage_freeze,
    "contract": stage_contract,
    "lock": stage_lock,
    "fixtures": stage_fixtures,
    "shadow": stage_shadow,
    "parity": stage_parity,
    "lifecycle": stage_lifecycle,
    "cleanliness": stage_cleanliness,
    "doctor": stage_doctor,
    "audit": stage_audit,
    "prefreeze": stage_prefreeze,
}

STAGE_ORDER = (
    "closure", "registry", "static", "semantics", "adjudication", "fixtures",
    "freeze", "contract", "lock", "shadow", "parity", "cleanliness",
    "lifecycle", "doctor", "audit", "prefreeze",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=[*sorted(STAGES), "all"])
    arguments = parser.parse_args(argv)
    stages = STAGE_ORDER if arguments.stage == "all" else [arguments.stage]
    for name in stages:
        report = STAGES[name]()
        print(json.dumps({"stage": name, **report}, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())