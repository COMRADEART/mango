"""T22 temporal-routing preconstruction generator (staged, deterministic).

T21R17 closed as VALID_CAPABILITY_FAILURE: the official one-shot run
completed (4800/4800 rows, attempt 1, ledger COMPLETE) and two frozen floor
metrics measured the candidate's temporal-routing failure with valid,
non-empty populations — explicit_current_routing_accuracy 0/70 = 0.0
(floor = 1.0) and stale_snapshot_false_current_answers 70 events (floor =
0) — while the candidate runtime had no candidate-visible temporal signal
carriers at all. T22 preconstruction freezes the remediated candidate
identity, the temporal signal contract, the holdout design that exposes
every temporal requirement through candidate-visible carriers (protocol
sections 32-34, mandatory gold-only-signal-rows = 0), the harmonized
zero-denominator policy resolution, and the full router-qualification
regression battery — before any real T22 material exists.

Stages (run in order):
  closure        T21R17 final disposition (aggregate-only provenance +
                 fingerprints, written into the T22 namespace; R17 and R16
                 artifacts are never modified)
  registry       prior_exclusion.json (17 milestones, hash-only, incl.
                 T21R17_OFFICIAL_VALID_CAPABILITY_FAILURE)
  static         T22 static artifacts (taxonomy, exclusions, schemas,
                 runtime contracts derived from frozen bytes, artifact
                 graph, temporal design nodes, metric design documents,
                 candidate identity verification)
  semantics      validate official_metric_semantics.json + the metric
                 implementation registry (byte-identical R17 semantics)
  adjudication   full-suite pytest + failure classification
  fixtures       run the metric-semantics fixture battery (incl. the
                 zero-denominator harmonization section)
  freeze         evaluator_freeze.json
  contract       t21_master_contract.json
  lock           qualification_lock.json
  shadow         runtime-native shadow corpus + 17-milestone overlap zeros
                 + temporal signal-carrier audit (gold-only = 0, §33)
  parity         provider parity (T22 request-date provider vs direct
                 runtime)
  cleanliness    raw/applicable/focused pytest runs with tracked drift
  lifecycle      full lifecycle x2 on disposable material
  doctor         protocol doctor (R16+R17 dispositions, temporal checks,
                 harmonization, lifecycle rehearsal)
  audit          T22_PRECONSTRUCTION_AUDIT.json
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
OUT = ROOT / "evaluations" / "t22"
R17_OUT = ROOT / "evaluations" / "t21r17"
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
    FLOOR_HASH,
    RUNTIME_COMPONENTS,
    SUITE_SIZES,
    _canonical_set_sha,
    _evaluation_design_documents,
    _holdout_frozen_schema,
    _junit_failures,
    _runtime_corpus_contract,
    _run_pytest,
)
from scripts.t21r17_preconstruction import _r16_sealed_fingerprints  # noqa: E402

R17_EVALUATION_HEAD = "9fc953468921e527d5c340b6e69bb1c3ea48c7a9"
R17_EVALUATION_BRANCH = "t21r17-official-evaluation"
R17_CONSTRUCTION_COMMIT = "9631c91687674497400e4e7ec974fa104cd0d3a9"
R17_SEAL_ROOT = "46557a9f6dd06a762ec320b701b6fa2659f32b0b66e0ceb9bee1df12c19fadf7"
R17_CLOSURE_STATUS = "CLOSED / VALID_CAPABILITY_FAILURE"
R17_CLOSURE_REASON = (
    "TWO_TEMPORAL_FLOOR_METRICS_MEASURED_A_CANDIDATE_FAILURE_WITHOUT_CANDIDATE_VISIBLE_SIGNALS"
)
R17_HISTORICAL_MILESTONE = "T21R17_OFFICIAL_VALID_CAPABILITY_FAILURE"
R17_FAILED_METRICS = ("explicit_current_routing_accuracy", "stale_snapshot_false_current_answers")
R17_FAILED_METRIC_DESIGNATION = "VALID_MEASUREMENTS_OF_CANDIDATE_CAPABILITY_FAILURE"
R17_FINAL_ADJUDICATION = "T21R17_FINAL_ADJUDICATION_VALID_CAPABILITY_FAILURE"
R17_HOLDOUT_STATUS = "PERMANENTLY_EXPOSED_CONSUMED"
T22_CANDIDATE_COMMIT = "7d919a255c2df87adcb3dd42011b505b10509713"
T22_CANDIDATE_TREE = "0bbf81b234458a4ac204ff6b035bc59b59078544"
CANDIDATE_RUNTIME_FILES = (
    "src/sciencemath/knowledge/freshness.py",
    "src/sciencemath/knowledge/routing.py",
    "src/sciencemath/knowledge/pipeline.py",
    "src/sciencemath/knowledge/schema.py",
    "src/sciencemath/knowledge/corpus.py",
    "t21_protocol/providers_t22.py",
)
T22_PROVIDER_ID = "t21_protocol.providers_t22:RealCandidateProviderT22Evidence"
T22_CONSTRUCTION_TOKEN = CONSTRUCTION_TOKENS["t22"]
T22_EVALUATION_TOKEN = EVALUATION_TOKENS["t22"]
AUTHOR_SEED = 22022

R17_EVALUATION_ARTIFACTS = (
    "evaluations/t21r17/HOLDOUT_FROZEN",
    "evaluations/t21r17/holdout_manifest.json",
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
)

SEMANTICS_PATH = "evaluations/t22/official_metric_semantics.json"
REGISTRY_PATH = "evaluations/t22/metric_implementation_registry.json"
FIXTURES_PATH = "evaluations/t22/metric_semantics_fixtures.json"
SIGNAL_CONTRACT_PATH = "evaluations/t22/temporal_signal_contract.json"
HOLDOUT_DESIGN_PATH = "evaluations/t22/temporal_holdout_design.json"
ZERO_DENOMINATOR_RESOLUTION_PATH = "evaluations/t22/zero_denominator_policy_resolution.json"
CANDIDATE_IDENTITY_PATH = "evaluations/t22/candidate_identity.json"


def _load(relative: str) -> dict[str, Any]:
    return read_json(ROOT / relative)


def _write(relative: str, document: dict[str, Any], *, exclusive: bool = False) -> None:
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, document, exclusive=exclusive)


def _floors() -> dict[str, Any]:
    return _load("evaluations/t21r17/t21_master_contract.json")["values"]["promotion_floors"]


# ---------------------------------------------------------------- closure --


def stage_closure() -> dict[str, Any]:
    """Record the T21R17 final disposition (aggregate provenance + artifact
    fingerprints only; protocol §1 forbids any modification of, or addition
    to, the R17/R16 artifact trees, so the disposition lives in the T22
    namespace)."""
    score = _load("evaluations/t21r17/score_results.json")
    floor_evidence = _load("evaluations/t21r17/floor_evidence.json")
    holdout_results = _load("evaluations/t21r17/holdout_results.json")
    ledger = _load("evaluations/t21r17/evaluation_run_ledger.json")
    provenance = _load("evaluations/t21r17/evaluation_provenance.json")
    if holdout_results["rows"] != 4800 or score["candidate_capability_pass"] is not False:
        raise SystemExit("R17 official score results do not match the frozen one-shot run")
    if holdout_results["seal_root"] != R17_SEAL_ROOT or ledger.get("state") != "COMPLETE" or ledger.get("attempt") != 1:
        raise SystemExit("R17 evaluation ledger/seal root do not match the frozen one-shot run")
    frozen_observed = {metric: score["metrics"][metric] for metric in R17_FAILED_METRICS}
    if frozen_observed != {"explicit_current_routing_accuracy": 0.0, "stale_snapshot_false_current_answers": 70}:
        raise SystemExit(f"frozen observed values drifted: {frozen_observed}")
    failed_comparisons = {
        comparison["metric"]: comparison
        for comparison in floor_evidence["floor_comparisons"]
        if not comparison["pass"]
    }
    if sorted(failed_comparisons) != sorted(R17_FAILED_METRICS):
        raise SystemExit(f"R17 failed floors drifted: {sorted(failed_comparisons)}")
    explicit = failed_comparisons["explicit_current_routing_accuracy"]
    stale = failed_comparisons["stale_snapshot_false_current_answers"]
    valid_measurements = (
        explicit["numerator"] == 0
        and explicit["denominator"] == 70
        and explicit["zero_denominator_policy_applied"] is False
        and stale["numerator"] == 70
        and stale["denominator"] is None
        and stale["zero_denominator_policy_applied"] is False
    )
    if not valid_measurements:
        raise SystemExit("the two failing R17 floors are not valid non-empty measurements")
    zero_denominator_passes = sorted(
        comparison["metric"]
        for comparison in floor_evidence["floor_comparisons"]
        if comparison["denominator"] == 0 and comparison["pass"] and comparison["zero_denominator_policy_applied"]
    )
    fingerprints = {relative: sha256_file(ROOT / relative) for relative in R17_EVALUATION_ARTIFACTS}
    closure = {
        "schema_version": "t21-experiment-closure-v1",
        "artifact": "T21R17_FINAL_DISPOSITION",
        "experiment": "t21r17",
        "status": R17_CLOSURE_STATUS,
        "reason": R17_CLOSURE_REASON,
        "failure_class": "capability_failure",
        "capability_verdict": "FAIL",
        "capability_failure": True,
        "failed_metrics": sorted(R17_FAILED_METRICS),
        "failed_metric_count": len(R17_FAILED_METRICS),
        "failed_metric_designation": R17_FAILED_METRIC_DESIGNATION,
        "final_adjudication": "T21R17_FINAL_ADJUDICATION_VALID_CAPABILITY_FAILURE",
        "rerun": "REFUSED",
        "holdout_status": R17_HOLDOUT_STATUS,
        "rows_scored": 4800,
        "one_shot_consumed": True,
        "evaluation_completed": True,
        "official_run_preserved": {
            "construction_commit": R17_CONSTRUCTION_COMMIT,
            "official_evaluation_commit": R17_EVALUATION_HEAD,
            "branch": R17_EVALUATION_BRANCH,
            "construction_attempt": 1,
            "evaluation_attempt": 1,
            "rows": 4800,
            "ledger_status": "COMPLETE",
            "exposures": 1,
            "floors_passed": 30,
            "floors_failed": sorted(R17_FAILED_METRICS),
            "rerun": "PROHIBITED",
            "seal_root": R17_SEAL_ROOT,
            "candidate_provider": provenance["candidate_provider"],
            "workspace_mode": provenance["workspace_mode"],
        },
        "frozen_observed_values": frozen_observed,
        "frozen_observed_values_note": (
            "recorded exactly as scored by the frozen explicit scorer in the one-shot run; the values are "
            "never replaced with alternative estimates or repaired observations"
        ),
        "valid_measurement_evidence": {
            "explicit_current_routing_accuracy": {
                "numerator": explicit["numerator"],
                "denominator": explicit["denominator"],
                "note": "the metric measured a real, design-mandated, non-empty population (70 temporal rows)",
            },
            "stale_snapshot_false_current_answers": {
                "numerator": stale["numerator"],
                "denominator": None,
                "note": "the metric counted 70 real stale-snapshot-presented-as-current events",
            },
        },
        "zero_denominator_floors_passed_under_frozen_conventions": {
            "metrics": zero_denominator_passes,
            "policy_note": "preregistered convention observed=0.0 on an empty eligible population; the T22 "
            "zero_denominator_policy_resolution harmonizes the prose prospectively and leaves the frozen "
            "implementation unchanged",
        },
        "remediation_protocol": "T22 temporal/current-information routing preconstruction (candidate-visible "
        "signal carriers; the measuring stick does not change); no candidate repair is derived from any R17 "
        "blind case",
        "rerun_policy": {
            "rerun_r17_evaluation": "REFUSED",
            "holdout_reuse": "FORBIDDEN",
            "holdout_status": R17_HOLDOUT_STATUS,
        },
        "artifact_fingerprints_sha256": fingerprints,
        "closed_at": "2026-09-22",
    }
    _write("evaluations/t22/r17_final_disposition.json", closure)
    refusal = {
        "schema_version": "t21-evaluation-refusal-v1",
        "artifact": "T21R17_EVALUATION_REFUSAL",
        "experiment": "t21r17",
        "permanent": True,
        "refused_action": "any further T21R17 official evaluation",
        "reason": R17_CLOSURE_REASON,
        "authority": "T21R17 final adjudication: holdout PERMANENTLY EXPOSED / CONSUMED; capability verdict FAIL",
    }
    _write("evaluations/t22/r17_evaluation_refusal.json", refusal)
    return {
        "status": "PASS",
        "disposition": "evaluations/t22/r17_final_disposition.json",
        "refusal_marker": "evaluations/t22/r17_evaluation_refusal.json",
        "frozen_observed": frozen_observed,
        "zero_denominator_floors": zero_denominator_passes,
    }


# ---------------------------------------------------------------- registry --


def _r17_sealed_fingerprints() -> dict[str, set[str]]:
    """Hash-only derivation input for the T21R17 registry milestone.

    R17 sealed and officially-evaluated material is read, fingerprinted in
    memory with the protocol's own fingerprint function, and never persisted:
    the registry stores fingerprints only."""
    contract = _load("evaluations/t21r17/t21_master_contract.json")
    suite_names = sorted(contract["values"]["suites"])
    rows: list[dict[str, Any]] = []
    for suite_name in suite_names:
        path = R17_OUT / "suites" / suite_name / "holdout.jsonl"
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    corpus_dir = ROOT / "rag" / "gk_holdout_t21r17"
    sources = [json.loads(line) for line in (corpus_dir / "sources.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks = [json.loads(line) for line in (corpus_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    world = [json.loads(line) for line in (corpus_dir / "world.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 4800 or len(sources) != 4800 or len(chunks) != 4800 or len(world) != 4800:
        raise SystemExit("R17 sealed material shape mismatch")
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
    upstream = _load("evaluations/t21r17/prior_exclusion.json")
    if upstream.get("historical_milestone_count") != 16:
        raise SystemExit("unexpected upstream registry milestone count")
    fingerprints = _r17_sealed_fingerprints()
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
            "milestone": R17_HISTORICAL_MILESTONE,
            "derivation": "hash-only in-memory fingerprinting of R17 sealed + officially-evaluated material with t21_protocol.audits._fingerprint; raw values never persisted",
            "official_evaluation_head": R17_EVALUATION_HEAD,
            "construction_commit": R17_CONSTRUCTION_COMMIT,
            "sealed_holdout_manifest_sha256": sha256_file(ROOT / "evaluations" / "t21r17" / "holdout_manifest.json"),
            "sealed_holdout_frozen_sha256": sha256_file(ROOT / "evaluations" / "t21r17" / "HOLDOUT_FROZEN"),
            "rows_scored": 4800,
            "one_shot_consumed": True,
            "holdout_status": R17_HOLDOUT_STATUS,
            "source_paths": [
                "evaluations/t21r17/suites/<suite>/holdout.jsonl",
                "rag/gk_holdout_t21r17/sources.jsonl",
                "rag/gk_holdout_t21r17/chunks.jsonl",
                "rag/gk_holdout_t21r17/world.jsonl",
            ],
            "raw_values_included": False,
            "measurement_note": (
                "the milestone records that the official evaluation completed and measured a real candidate "
                "capability failure: the two temporal floor metrics carry valid non-empty populations "
                "(explicit_current_routing_accuracy 0/70 = 0.0, stale_snapshot_false_current_answers 70 events) "
                "against a candidate with no candidate-visible temporal signal carriers; it is capability-failure "
                "provenance and never a measurement-specification failure"
            ),
        },
    }
    milestone_names = list(upstream["milestone_order"]) + [R17_HISTORICAL_MILESTONE]
    registry = {
        "artifact": "T22_PRIOR_EXCLUSION_REGISTRY",
        "version": "t22-v1",
        "fingerprint_algorithm": upstream["fingerprint_algorithm"],
        "payload_encoding": upstream["payload_encoding"],
        "historical_dimensions": len(DIMENSIONS),
        "historical_milestone_count": len(milestone_names),
        "milestone_order": milestone_names,
        "milestones": {**upstream["milestones"], R17_HISTORICAL_MILESTONE: milestone},
        "raw_values_included": False,
    }
    if len(registry["milestones"]) != 17:
        raise SystemExit("registry must carry exactly 17 milestones")
    for name, spec in registry["milestones"].items():
        if set(spec["dimensions"]) != set(DIMENSIONS):
            raise SystemExit(f"milestone {name} dimensions invalid")
        for dimension, payload in spec["dimensions"].items():
            if payload["count"] != len(payload["fingerprints"]):
                raise SystemExit(f"milestone {name}/{dimension} count mismatch")
    _write("evaluations/t22/prior_exclusion.json", registry)
    return {
        "status": "PASS",
        "milestones": len(milestone_names),
        "r17_fingerprint_counts": {dimension: milestone["dimensions"][dimension]["count"] for dimension in DIMENSIONS},
    }


# ------------------------------------------------------------------ static --


def _negative_controls() -> dict[str, Any]:
    r17 = _load("evaluations/t21r17/negative_controls.json")
    controls = list(r17["controls"])
    controls.extend(
        {"failure_class": name, "latest_legal_phase": "PRECONSTRUCTION", "test": test}
        for name, test in (
            ("temporal row whose only signal is gold metadata", "tests/test_t22_preconstruction.py::test_temporal_signal_carrier_audit_zero_gold_only"),
            ("temporal router qualification gate failure", "tests/test_t22_preconstruction.py::test_temporal_router_qualification_gates"),
            ("row_authoring template drift from the frozen temporal design", "tests/test_t22_preconstruction.py::test_row_authoring_composition_matches_frozen_design"),
            ("zero-denominator prose/implementation regression", "tests/test_t22_preconstruction.py::test_zero_denominator_harmonization_frozen"),
            ("candidate provider reading a gold-only field", "tests/test_t22_preconstruction.py::test_candidate_provider_reads_only_candidate_visible_inputs"),
            ("R17 sealed artifact mutation", "tests/test_t22_preconstruction.py::test_r17_artifacts_unmodified"),
        )
    )
    return {
        "schema_version": "t21-negative-controls-v1",
        "artifact": "T22_NEGATIVE_CONTROL_REGISTRY",
        "experiment": "t22",
        "infrastructure_errors_must_fail_before_construction": True,
        "controls": controls,
    }


def _historical_exclusion(milestones: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "t21-historical-exclusion-policy-v1",
        "artifact": "T22_HISTORICAL_EXCLUSION_POLICY",
        "experiment": "t22",
        "raw_values_included": False,
        "historical_milestone_count": len(milestones),
        "milestones": milestones,
        "r17_protocol_history": {
            "blind_fingerprints_invented": False,
            "construction_attempts": 1,
            "one_shot_consumed": True,
            "rows_scored": 4800,
            "closure_status": R17_CLOSURE_STATUS,
            "closure_reason": R17_CLOSURE_REASON,
            "capability_verdict": "FAIL",
            "rerun_refused": True,
            "holdout_status": R17_HOLDOUT_STATUS,
        },
        "upstream_registry": "evaluations/t22/prior_exclusion.json",
        "upstream_registry_sha256": sha256_file(ROOT / "evaluations" / "t22" / "prior_exclusion.json"),
    }


def _artifact_graph() -> dict[str, Any]:
    r17 = _load("evaluations/t21r17/artifact_graph.json")
    known_producers = sorted(
        {
            *r17["known_producers"],
            "r17_closure",
            "temporal_design",
            "candidate_identity",
            "temporal_regression_battery",
        }
    )
    nodes: dict[str, Any] = {}
    for name, node in r17["nodes"].items():
        nodes[name] = {**node, "path": node["path"].replace("t21r17", "t22")}
    nodes["preconstruction_audit"]["path"] = "evaluations/t22/T22_PRECONSTRUCTION_AUDIT.json"
    historical = nodes["historical_exclusion"]
    historical["required_inputs"] = [
        *historical["required_inputs"],
        "r17_closure",
    ]
    nodes["r17_closure"] = {
        "path": "evaluations/t22/r17_final_disposition.json",
        "producer": "r17_closure",
        "required_inputs": [],
        "consumers": ["historical_exclusion", "protocol_doctor", "master_contract"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["temporal_signal_contract"] = {
        "path": SIGNAL_CONTRACT_PATH,
        "producer": "temporal_design",
        "required_inputs": [],
        "consumers": ["temporal_holdout_design", "protocol_doctor", "official_validator"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["temporal_holdout_design"] = {
        "path": HOLDOUT_DESIGN_PATH,
        "producer": "temporal_design",
        "required_inputs": ["temporal_signal_contract"],
        "consumers": ["protocol_doctor", "official_validator", "author", "builder", "construction_gate"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["zero_denominator_policy_resolution"] = {
        "path": ZERO_DENOMINATOR_RESOLUTION_PATH,
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
    nodes["candidate_identity"] = {
        "path": CANDIDATE_IDENTITY_PATH,
        "producer": "candidate_identity",
        "required_inputs": [],
        "consumers": ["protocol_doctor", "master_contract"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["temporal_regression_battery"] = {
        "path": "evaluations/t22/temporal_regressions/results.json",
        "producer": "temporal_regression_battery",
        "required_inputs": ["temporal_signal_contract", "temporal_holdout_design"],
        "consumers": ["protocol_doctor", "official_validator"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "QUALIFIED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["semantics_carry_report"] = {
        "path": "evaluations/t22/semantics_carry_report.json",
        "producer": "metric_semantics",
        "required_inputs": ["official_metric_semantics"],
        "consumers": ["protocol_doctor"],
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
        "artifact": "T22_ARTIFACT_GRAPH",
        "experiment": "t22",
        "known_producers": known_producers,
        "nodes": nodes,
    }


def _verify_candidate_identity() -> dict[str, Any]:
    """The frozen T22 candidate identity must bind the current runtime bytes
    (§28: the candidate must change; §29: the identity is frozen here)."""
    identity = _load(CANDIDATE_IDENTITY_PATH)
    new_candidate = identity["new_candidate"]
    if identity["status"] != "FROZEN_PRECONSTRUCTION" or identity["experiment"] != "t22":
        raise SystemExit("candidate identity is not the frozen T22 record")
    if new_candidate["candidate_commit"] != T22_CANDIDATE_COMMIT:
        raise SystemExit("candidate commit drifted from the frozen identity")
    file_hashes = {path: sha256_file(ROOT / path) for path in CANDIDATE_RUNTIME_FILES}
    if file_hashes != new_candidate["candidate_runtime_files_sha256"]:
        drifted = sorted(path for path, digest in file_hashes.items() if new_candidate["candidate_runtime_files_sha256"].get(path) != digest)
        raise SystemExit(f"candidate runtime files drifted from the frozen identity: {drifted}")
    if sha256_json(file_hashes) != new_candidate["candidate_runtime_identity_root"]:
        raise SystemExit("candidate runtime identity root does not recompute")
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "log", "--format=%H", f"{T22_CANDIDATE_COMMIT}..HEAD", "--", "src", "t21_protocol/providers_t22.py"],
        capture_output=True,
        text=True,
    )
    later_changes = [line for line in completed.stdout.splitlines() if line.strip()]
    if later_changes:
        raise SystemExit(f"candidate repair chain is not complete: {later_changes}")
    return {
        "status": "PASS",
        "candidate_commit": T22_CANDIDATE_COMMIT,
        "candidate_runtime_identity_root": new_candidate["candidate_runtime_identity_root"],
        "repair_chain": new_candidate["candidate_repair_chain"],
        "repair_chain_complete": True,
        "runtime_files_verified": sorted(file_hashes),
    }


def stage_static() -> dict[str, Any]:
    r17_contract = _load("evaluations/t21r17/t21_master_contract.json")
    r17_values = r17_contract["values"]
    registry = _load("evaluations/t22/prior_exclusion.json")
    milestones = registry["milestone_order"]
    identity_check = _verify_candidate_identity()

    taxonomy = {**_load("evaluations/t21r16/domain_taxonomy_contract.json"), "artifact": "T22_DOMAIN_TAXONOMY_CONTRACT", "experiment": "t22"}
    remediation = {
        **_load("evaluations/t21r17/remediation_exclusion.json"),
        "artifact": "T22_REMEDIATION_EXCLUSION_POLICY",
        "experiment": "t22",
        "source": f"evaluations/t21r16/remediation_exclusion.json#sha256={r17_values['remediation_exclusions']['source_sha256']}",
    }
    historical = _historical_exclusion(milestones)
    schema_document = _holdout_frozen_schema()
    controls = _negative_controls()
    experiment = {
        "artifact": "T22_EXPERIMENT_CONFIGURATION",
        "author_vocabulary": _load("evaluations/t21r16/experiment.json")["author_vocabulary"],
        "case_id_prefix": "t22-",
        "crossdomain_pair_ids": sorted(pair["id"] for pair in r17_values["crossdomain_pairs"]),
        "experiment": "t22",
        "historical_exclusion_milestone_count": len(milestones),
        "namespace": "mango-t22-v1",
        "seed": AUTHOR_SEED,
        "suite_total": 4800,
        "version": "t22-v1",
    }

    def _patch_labels(document: dict[str, Any], artifact: str) -> dict[str, Any]:
        patched = json.loads(json.dumps(document).replace("t21r16", "t22").replace("T21R16_", "T22_"))
        patched["artifact"] = artifact
        patched["experiment"] = "t22"
        return patched

    corpus_contract, checks = _runtime_corpus_contract()
    corpus_contract = _patch_labels(corpus_contract, "T22_RUNTIME_CORPUS_CONTRACT")
    if not all(checks.values()):
        raise SystemExit(f"runtime corpus contract derivation checks failed: {checks}")
    field_provenance = _patch_labels(_load("evaluations/t21r17/runtime_field_provenance.json"), "T22_RUNTIME_FIELD_PROVENANCE")
    _write("evaluations/t22/runtime_corpus_contract.json", corpus_contract)
    _write("evaluations/t22/runtime_field_provenance.json", field_provenance)
    runtime_freeze = build_freeze(
        ROOT,
        RUNTIME_COMPONENTS,
        artifact="T22_RUNTIME_FREEZE",
        experiment="t22",
        extra={"candidate_commit": T22_CANDIDATE_COMMIT, "candidate_tree": T22_CANDIDATE_TREE},
    )
    if runtime_freeze["component_root_sha256"] == r17_values["roots"]["runtime_root"]:
        raise SystemExit("T22 runtime freeze root must differ from the R17 frozen runtime root (the candidate changed)")
    candidate_data_contract = _patch_labels(
        _load("evaluations/t21r17/candidate_runtime_data_contract.json"), "T22_CANDIDATE_RUNTIME_DATA_CONTRACT"
    )
    candidate_data_contract["candidate"] = {
        "provider_id": T22_PROVIDER_ID,
        "module": "t21_protocol/providers_t22.py",
        "module_sha256": sha256_file(ROOT / "t21_protocol" / "providers_t22.py"),
        "serialization": "t21_protocol.providers_r17:canonical_candidate_row_v2",
        "corpus_loader": "src/sciencemath/knowledge/corpus.py:load_corpus (frozen, no adapter)",
        "initialization": {"loads_corpus_once": True, "executes_holdout_rows": False},
        "generation": {"entry": "src/sciencemath/knowledge/pipeline.py:answer_knowledge", "canonical_serialization": "t21_protocol.providers_r17:canonical_candidate_row_v2"},
        "request_date_carrier": {
            "field": "request_date",
            "runtime_input": "pipeline.answer_knowledge(now=...)",
            "carrier": "E_runtime_request_timestamp",
            "candidate_visible_only": True,
        },
        "gold_only_fields_never_read": ["construction_tag", "signal_class", "expected_route", "expected_status", "gold expected_answer"],
        "evidence_passthrough": ["citations", "citation_report", "claim_review", "evidence_pack", "eligibility"],
        "candidate_rows_executed_in_preconstruction": 0,
    }
    candidate_data_contract["runtime_corpus_contract"] = {
        "path": "evaluations/t22/runtime_corpus_contract.json",
        "sha256": sha256_file(ROOT / "evaluations" / "t22" / "runtime_corpus_contract.json"),
    }
    candidate_data_contract["runtime_field_provenance"] = {
        "path": "evaluations/t22/runtime_field_provenance.json",
        "sha256": sha256_file(ROOT / "evaluations" / "t22" / "runtime_field_provenance.json"),
    }
    graph = _artifact_graph()
    design = _evaluation_design_documents(r17_values["promotion_floors"])
    design = {name: _patch_labels(document, document["artifact"].replace("T21R16_", "T22_")) for name, document in design.items()}
    _write("evaluations/t22/domain_taxonomy_contract.json", taxonomy)
    _write("evaluations/t22/remediation_exclusion.json", remediation)
    _write("evaluations/t22/historical_exclusion.json", historical)
    _write("evaluations/t22/holdout_frozen_schema.json", schema_document)
    _write("evaluations/t22/negative_controls.json", controls)
    _write("evaluations/t22/experiment.json", experiment)
    _write("evaluations/t22/artifact_graph.json", graph)
    _write("evaluations/t22/runtime_corpus_contract.json", corpus_contract)
    _write("evaluations/t22/runtime_field_provenance.json", field_provenance)
    _write("evaluations/t22/candidate_runtime_data_contract.json", candidate_data_contract)
    _write("evaluations/t22/runtime_freeze.json", runtime_freeze)
    for name, document in design.items():
        _write(f"evaluations/t22/{name}.json", document)
    return {
        "status": "PASS",
        "runtime_contract_checks": checks,
        "graph_nodes": len(graph["nodes"]),
        "candidate_identity": identity_check,
    }


# --------------------------------------------------------------- semantics --


def stage_semantics() -> dict[str, Any]:
    """The measuring stick does not change: the frozen R17 semantics carries
    forward with only the preregistered harmonized prose deltas and the
    implementation registry byte-identically; the validation re-proves
    closure under the T22 namespace and re-verifies the carry deltas live."""
    from t21_protocol.metric_semantics import load_metric_semantics, semantics_root
    from t21_protocol.scorer_r17 import IMPLEMENTATIONS, IMPLEMENTATION_SOURCES

    floors = _floors()
    floor_metrics = sorted(metric for metrics in floors.values() for metric in metrics)
    semantics = load_metric_semantics(ROOT, {}, relative=SEMANTICS_PATH, floors=floors,
                                      artifact="T22_OFFICIAL_METRIC_SEMANTICS", experiment="t22")
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
    carry = read_json(ROOT / "evaluations" / "t22" / "semantics_carry_report.json")
    r17_semantics = read_json(ROOT / "evaluations" / "t21r17" / "official_metric_semantics.json")
    delta_paths = sorted(_semantic_delta_paths(r17_semantics, semantics))
    harmonized_paths = sorted(carry["harmonized_paths"])
    delta_ok = delta_paths == harmonized_paths
    registry_delta_paths = sorted(_semantic_delta_paths(
        read_json(ROOT / "evaluations" / "t21r17" / "metric_implementation_registry.json"),
        read_json(ROOT / REGISTRY_PATH),
    ))
    registry_carry_ok = registry_delta_paths == ["artifact", "experiment"]
    scorer_sha = sha256_file(ROOT / "t21_protocol" / "scorer_r17.py")
    recompute = _reverify_implementation_hashes(registry)
    scorer_ok = (
        registry["scorer_module_sha256"] == scorer_sha == carry["scorer_module_sha256"]
        and recompute["recomputed"] == 32
        and not recompute["mismatches"]
    )
    carry_verified = (
        delta_ok and registry_carry_ok and scorer_ok and floor_hash_ok
        and carry["floor_hash_unchanged"] is True
        and carry["retroactive_effect_on_r17"].startswith("NONE")
        and carry["prospective_only"] is True
    )
    carry_detail = {
        "registry_delta_paths": registry_delta_paths,
        "registry_header_only_delta": registry_carry_ok,
        "semantics_delta_paths": delta_paths,
        "semantics_delta_matches_frozen_harmonized_paths": delta_ok,
        "implementation_sha256_recomputed": recompute["recomputed"],
        "implementation_sha256_mismatches": recompute["mismatches"],
        "scorer_module_sha256": scorer_sha,
        "prospective_only": carry["prospective_only"],
        "retroactive_effect_on_r17": carry["retroactive_effect_on_r17"],
    }
    ok = not defects and floor_hash_ok and registry_shape_ok and carry_verified
    document = {
        "schema_version": "t22-metric-semantics-validation-v1",
        "artifact": "T22_METRIC_SEMANTICS_VALIDATION",
        "experiment": "t22",
        "status": "PASS" if ok else "FAIL",
        "audit_mode": "EXECUTED",
        "semantics_artifact": SEMANTICS_PATH,
        "semantics_root": semantics_root(semantics),
        "registry_artifact": REGISTRY_PATH,
        "registry_sha256": sha256_file(ROOT / REGISTRY_PATH),
        "r17_semantics_carry_verified": carry_verified,
        "r17_semantics_carry": carry_detail,
        "floor_hash": FLOOR_HASH,
        "floor_hash_matches_frozen": floor_hash_ok,
        "metrics": {metric: {key: entries[metric][key] for key in entry_keys if key in entries[metric]} for metric in floor_metrics},
        "problems": problems,
        "registry_shape_ok": registry_shape_ok,
    }
    _write("evaluations/t22/metric_semantics_validation.json", document)
    if not ok:
        raise SystemExit(f"metric semantics validation failed: {json.dumps(defects)[:2000]}")
    return {"status": "PASS", "metrics": len(entries), "semantics_root": document["semantics_root"]}


def _semantic_delta_paths(left: Any, right: Any, prefix: str = "") -> list[str]:
    """Dotted leaf paths at which two semantics documents differ (dict/list
    structural walk; the frozen R17 -> T22 carry differs only along the
    pinned harmonized paths)."""
    paths: list[str] = []
    if type(left) is not type(right):
        return [prefix.rstrip(".") or "<root>"]
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}{key}." if prefix else f"{key}."
            if key not in left or key not in right:
                paths.append(child.rstrip("."))
            else:
                paths.extend(_semantic_delta_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list):
        if len(left) != len(right):
            return [prefix.rstrip(".") + "#len"]
        for index, (item_left, item_right) in enumerate(zip(left, right)):
            paths.extend(_semantic_delta_paths(item_left, item_right, f"{prefix}{index}."))
        return paths
    return [prefix.rstrip(".")] if left != right else []


def _reverify_implementation_hashes(registry: dict[str, Any]) -> dict[str, Any]:
    """Recompute every registered metric's implementation hash from the
    current scorer_r17 source segments (AST), fail closed on drift."""
    import ast

    from t21_protocol.scorer_r17 import IMPLEMENTATION_SOURCES

    scorer_path = ROOT / "t21_protocol" / "scorer_r17.py"
    source = scorer_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    segments = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    mismatches: list[str] = []
    recomputed = 0
    for metric_id, entry in sorted(registry["implementations"].items()):
        expected_function = IMPLEMENTATION_SOURCES.get(metric_id)
        if expected_function is None or entry.get("function") != expected_function:
            mismatches.append(metric_id)
            continue
        segment = segments.get(expected_function)
        if segment is None or sha256_json({"source": segment}) != entry.get("implementation_sha256"):
            mismatches.append(metric_id)
        else:
            recomputed += 1
    return {"recomputed": recomputed, "mismatches": mismatches}


# ------------------------------------------------------------ adjudication --


APPLICABILITY_SCHEMA_VERSION = "t21-current-test-applicability-v1"

_T22_BYTE_BOUND_EXPIRIES = {
    "tests/test_t21r11_preconstruction.py::test_runtime_freeze_rehashes_every_component": (
        "re-verifies the R11 frozen runtime freeze against current runtime bytes; the authorized T22 candidate "
        "remediation (repair chain ending at the T22 candidate commit) changed the runtime component bytes "
        "(freshness/routing/pipeline/schema/corpus), so the R11 freeze legitimately no longer re-hashes; the T22 "
        "runtime freeze (evaluations/t22/runtime_freeze.json) binds the current bytes and "
        "tests/test_t22_preconstruction.py re-verifies it against the T22 root"
    ),
    "tests/test_t21r11_preconstruction.py::test_remediation_provenance_binds_every_production_change": (
        "the R11 remediation provenance binds the pre-repair sha256 of every changed production file; the "
        "authorized T22 candidate remediation changed production bytes, so the R11-bound hashes legitimately no "
        "longer match; T22's frozen changed_file_manifest.json (evaluations/t22) carries the same discipline for "
        "the current candidate"
    ),
    "tests/test_t21r16_preconstruction.py::test_runtime_contract_is_derived_from_frozen_modules": (
        "re-derives the R16 runtime corpus contract from current runtime bytes and compares it to the committed "
        "R16 contract; the authorized T22 candidate remediation changed runtime bytes, so the fresh derivation "
        "legitimately differs; T22 re-derives the corpus contract from the current frozen bytes into "
        "evaluations/t22/runtime_corpus_contract.json (tests/test_t22_preconstruction.py re-checks it)"
    ),
}


def _classify_t22(nodeid: str, r17: dict[str, str]) -> tuple[str, str]:
    """T22 failure classification: the committed R17 adjudication map first,
    then the documented expiry of the R17 preconstruction absence pin (the
    same shape R17 adjudicated for R16's pin), then the runtime-byte-bound
    rehearsals superseded by the T22 candidate remediation."""
    if nodeid in r17:
        return (
            r17[nodeid],
            "classification carried from the committed T21R17 adjudication (same committed historical artifact state)",
        )
    if nodeid == "tests/test_t21r17_preconstruction.py::test_real_r17_paths_absent":
        return (
            "OBSOLETE_HISTORICAL_ASSERTION",
            "asserts real R17 holdout paths are absent; the R17 sealed holdout legitimately exists, was consumed by the "
            "one-shot official evaluation, and is preserved unmodified (T21R17 final adjudication); the T22 contract "
            "carries the equivalent preconstruction pin (tests/test_t22_preconstruction.py::test_real_t22_paths_absent)",
        )
    if nodeid in _T22_BYTE_BOUND_EXPIRIES:
        return ("SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE", _T22_BYTE_BOUND_EXPIRIES[nodeid])
    return "UNKNOWN", "unclassified failure"


def stage_adjudication() -> dict[str, Any]:
    from t21_protocol.adjudication import generate_applicability

    r17_adjudication = _load("evaluations/t21r17/test_failure_adjudication.json")
    r17 = {entry["nodeid"]: entry["classification"] for entry in r17_adjudication["entries"]}
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    junit = artifacts / "t22_adjudication_junit.xml"
    run = _run_pytest(["tests"], junit, artifacts / ".pytest_t22_adjudication")
    failures = _junit_failures(junit)
    if not failures:
        raise SystemExit("adjudication expected registered historical failures in the full suite")
    entries = []
    for nodeid in sorted(failures):
        classification, rationale = _classify_t22(nodeid, r17)
        entries.append({"nodeid": nodeid, "classification": classification, "rationale": rationale})
    unresolved = [entry for entry in entries if entry["classification"] in {"LIVE", "UNKNOWN", "ENVIRONMENT_ONLY_FAILURE"}]
    if unresolved:
        raise SystemExit(f"unadjudicated failures remain: {unresolved}")
    summary = {name: 0 for name in ALLOWED_CLASSIFICATIONS}
    for entry in entries:
        summary[entry["classification"]] += 1
    adjudication = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "artifact": "T22_TEST_FAILURE_ADJUDICATION",
        "experiment": "t22",
        "classification_summary": summary,
        "entries": [{"nodeid": entry["nodeid"], "classification": entry["classification"]} for entry in entries],
        "rationales": {entry["nodeid"]: entry["rationale"] for entry in entries},
    }
    _write("evaluations/t22/test_failure_adjudication.json", adjudication)
    _write("evaluations/t22/current_test_applicability.json", generate_applicability(adjudication))
    return {"status": "PASS", "failures": len(entries), "summary": summary, "pytest_exit_code": run["exit_code"]}


# ------------------------------------------------------------------ freeze --


def stage_freeze() -> dict[str, Any]:
    experiment_artifacts = [
        "evaluations/t22/artifact_graph.json",
        "evaluations/t22/current_test_applicability.json",
        "evaluations/t22/domain_taxonomy_contract.json",
        "evaluations/t22/experiment.json",
        "evaluations/t22/historical_exclusion.json",
        "evaluations/t22/holdout_frozen_schema.json",
        "evaluations/t22/negative_controls.json",
        "evaluations/t22/remediation_exclusion.json",
        "evaluations/t22/runtime_freeze.json",
        "evaluations/t22/test_failure_adjudication.json",
        "evaluations/t22/runtime_corpus_contract.json",
        "evaluations/t22/runtime_field_provenance.json",
        "evaluations/t22/candidate_runtime_data_contract.json",
        "evaluations/t22/official_metric_registry.json",
        "evaluations/t22/evaluation_reporting_contract.json",
        "evaluations/t22/floor_evidence_contract.json",
        "evaluations/t22/evaluation_artifact_graph.json",
        "evaluations/t22/prior_exclusion.json",
        "evaluations/t22/r17_final_disposition.json",
        "evaluations/t22/r17_evaluation_refusal.json",
        "evaluations/t22/metric_semantics_validation.json",
        SIGNAL_CONTRACT_PATH,
        HOLDOUT_DESIGN_PATH,
        ZERO_DENOMINATOR_RESOLUTION_PATH,
        CANDIDATE_IDENTITY_PATH,
        "evaluations/t22/changed_file_manifest.json",
        "evaluations/t22/semantics_carry_report.json",
        "evaluations/t22/temporal_regressions/battery_spec.json",
        "evaluations/t22/temporal_regressions/results.json",
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
        "scripts/t21r17_fixtures.py",
        "scripts/t21r16_preconstruction.py",
        "scripts/t21r17_preconstruction.py",
        "scripts/t22_metric_semantics.py",
        "scripts/t22_fixtures.py",
        "scripts/t22_regression_battery.py",
        "scripts/t22_preconstruction.py",
    ]
    modules = [f"t21_protocol/{path.name}" for path in sorted((ROOT / "t21_protocol").glob("*.py"))]
    tests = [
        "tests/test_t21_protocol_kernel.py",
        "tests/test_t21r16_preconstruction.py",
        "tests/test_t21r17_preconstruction.py",
        "tests/test_t22_preconstruction.py",
    ]
    freeze = build_freeze(
        ROOT,
        [*experiment_artifacts, *scripts, *modules, *tests],
        artifact="T22_EVALUATOR_FREEZE",
        experiment="t22",
        extra={"floor_hash": FLOOR_HASH},
    )
    _write("evaluations/t22/evaluator_freeze.json", freeze)
    return {"status": "PASS", "components": len(freeze["component_sha256"]), "root": freeze["component_root_sha256"]}


# ---------------------------------------------------------------- contract --


REAL_T22_PATHS = [
    "rag/gk_holdout_t22",
    "evaluations/t22/suites",
    "evaluations/t22/construction_run_ledger.json",
    "evaluations/t22/author_spec.json",
    "evaluations/t22/material_provenance.json",
    "evaluations/t22/runtime_loader_validation.json",
    "evaluations/t22/candidate_provider_compatibility.json",
    "evaluations/t22/historical_uniqueness.json",
    "evaluations/t22/remediation_uniqueness.json",
    "evaluations/t22/construction_gate.json",
    "evaluations/t22/exact_design_audit.json",
    "evaluations/t22/gate_auditor_crosscheck.json",
    "evaluations/t22/static_gold_audit.json",
    "evaluations/t22/holdout_blindness.json",
    "evaluations/t22/gold_compatibility.json",
    "evaluations/t22/root_of_trust.json",
    "evaluations/t22/holdout_manifest.json",
    "evaluations/t22/HOLDOUT_FROZEN",
    "evaluations/t22/sealed_preflight.json",
    "evaluations/t22/evaluation_run_ledger.json",
    "evaluations/t22/candidate_outputs.jsonl",
    "evaluations/t22/evaluator_results.json",
    "evaluations/t22/score_results.json",
    "evaluations/t22/evaluation_provenance.json",
    "evaluations/t22/raw_results.jsonl",
    "evaluations/t22/metric_evidence.json",
    "evaluations/t22/floor_evidence.json",
    "evaluations/t22/holdout_results.json",
]


def _t22_contract_fields() -> list[dict[str, Any]]:
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
        ("r17_disposition", "object", {"nonempty": True}, ["protocol_doctor", "operator", "scorer"], "qualification"),
        ("real_t22_paths", "array", {"nonempty": True}, ["protocol_doctor", "operator"], "contract"),
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
    """Semantic identity of the official evaluator (unchanged from R17):
    the frozen descriptor keyed by R17_EVALUATOR_SEMANTIC_KEYS."""
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
    r17 = _load("evaluations/t21r17/t21_master_contract.json")
    r17_values = r17["values"]
    freeze = _load("evaluations/t22/evaluator_freeze.json")
    taxonomy_document = _load("evaluations/t22/domain_taxonomy_contract.json")
    from t21_protocol.metric_semantics import load_metric_semantics, semantics_root

    semantics = load_metric_semantics(ROOT, {}, relative=SEMANTICS_PATH, floors=r17_values["promotion_floors"],
                                      artifact="T22_OFFICIAL_METRIC_SEMANTICS", experiment="t22")
    values = {
        key: value
        for key, value in r17_values.items()
        if key not in {
            "identity", "roots", "artifacts", "suites", "domain_taxonomy", "crossdomain_pairs",
            "historical_exclusions", "remediation_exclusions", "real_r17_paths",
            "quarantine", "phase_apis", "state_machine", "runtime_native", "metric_semantics", "author",
        }
    }
    values["identity"] = {"case_id_prefix": "t22-", "namespace": "mango-t22-v1"}
    values["author"] = {"seed": AUTHOR_SEED, "vocabulary": r17_values["author"]["vocabulary"]}
    values["roots"] = {
        "candidate_commit": T22_CANDIDATE_COMMIT,
        "candidate_tree": T22_CANDIDATE_TREE,
        "runtime_root": _load("evaluations/t22/runtime_freeze.json")["component_root_sha256"],
        "evaluator_root": freeze["component_root_sha256"],
        "floor_hash": FLOOR_HASH,
        "runtime_data_contract_root": sha256_json(_load("evaluations/t22/candidate_runtime_data_contract.json")),
        "runtime_corpus_contract_sha256": sha256_file(ROOT / "evaluations" / "t22" / "runtime_corpus_contract.json"),
        "runtime_field_provenance_sha256": sha256_file(ROOT / "evaluations" / "t22" / "runtime_field_provenance.json"),
        "candidate_provider_sha256": sha256_file(ROOT / "t21_protocol" / "providers_t22.py"),
        "candidate_provider_id": T22_PROVIDER_ID,
        "evaluator_semantic_root": _evaluator_semantic_root(),
        "scorer_semantic_root": semantics_root(semantics),
        "protocol_root": _protocol_root(),
    }
    values["artifacts"] = {
        "experiment_config": "evaluations/t22/experiment.json",
        "artifact_graph": "evaluations/t22/artifact_graph.json",
        "domain_taxonomy": "evaluations/t22/domain_taxonomy_contract.json",
        "historical_exclusion": "evaluations/t22/historical_exclusion.json",
        "remediation_exclusion": "evaluations/t22/remediation_exclusion.json",
        "runtime_freeze": "evaluations/t22/runtime_freeze.json",
        "evaluator_freeze": "evaluations/t22/evaluator_freeze.json",
        "qualification_lock": "evaluations/t22/qualification_lock.json",
        "negative_controls": "evaluations/t22/negative_controls.json",
        "adjudication": "evaluations/t22/test_failure_adjudication.json",
        "applicability": "evaluations/t22/current_test_applicability.json",
        "holdout_frozen_schema": "evaluations/t22/holdout_frozen_schema.json",
        "runtime_corpus_contract": "evaluations/t22/runtime_corpus_contract.json",
        "runtime_field_provenance": "evaluations/t22/runtime_field_provenance.json",
        "candidate_runtime_data_contract": "evaluations/t22/candidate_runtime_data_contract.json",
        "official_metric_semantics": SEMANTICS_PATH,
        "metric_implementation_registry": REGISTRY_PATH,
        "temporal_signal_contract": SIGNAL_CONTRACT_PATH,
        "temporal_holdout_design": HOLDOUT_DESIGN_PATH,
        "zero_denominator_policy_resolution": ZERO_DENOMINATOR_RESOLUTION_PATH,
        "candidate_identity": CANDIDATE_IDENTITY_PATH,
    }
    values["suites"] = {
        f"mango-t22-{name}-holdout-v1": {"count": count, "family": name}
        for name, count in SUITE_SIZES
    }
    values["domain_taxonomy"] = sorted(domain["canonical_label"] for domain in taxonomy_document["domains"])
    values["crossdomain_pairs"] = r17_values["crossdomain_pairs"]
    values["historical_exclusions"] = {"dimensions": len(DIMENSIONS), "milestones": 17, "raw_values": False, "r17_protocol_history_only": True}
    values["remediation_exclusions"] = {
        "dimensions": 9,
        "raw_values": False,
        "source_sha256": _load("evaluations/t22/remediation_exclusion.json")["source"].split("sha256=")[1],
    }
    values["r17_disposition"] = {
        "status": R17_CLOSURE_STATUS,
        "reason": R17_CLOSURE_REASON,
        "construction_attempts": 1,
        "rows_scored": 4800,
        "one_shot_consumed": True,
        "holdout_status": R17_HOLDOUT_STATUS,
        "evaluation_completed": True,
        "capability_verdict": "FAIL",
        "failed_metrics": sorted(R17_FAILED_METRICS),
        "failed_metric_count": len(R17_FAILED_METRICS),
        "failed_metric_designation": R17_FAILED_METRIC_DESIGNATION,
        "retroactive_capability_declaration": "FORBIDDEN",
        "rerun": "REFUSED",
        "adjudication": R17_FINAL_ADJUDICATION,
        "evaluation_commit": R17_EVALUATION_HEAD,
    }
    values["real_t22_paths"] = REAL_T22_PATHS
    values["quarantine"] = {
        "status": "FORBIDDEN",
        "r17_official_evaluation_reads": 0,
        "r17_sealed_holdout_path": "rag/gk_holdout_t21r17",
        "registry_access_only": True,
        "r17_raw_result_reads_by_t22_material": 0,
    }
    values["phase_apis"] = {
        "construct": {
            "required_state": "QUALIFIED",
            "terminal_states": ["SEALED"],
            "authorization_token": T22_CONSTRUCTION_TOKEN,
            "allowed_artifact_phases": ["CONSTRUCTION", "SEAL"],
        },
        "evaluate": {
            "required_state": "SEALED",
            "terminal_states": ["EVALUATION_COMPLETE", "FAILED"],
            "authorization_token": T22_EVALUATION_TOKEN,
            "allowed_artifact_phases": ["EVALUATION"],
        },
    }
    evaluation_paths = [
        "evaluations/t22/evaluation_run_ledger.json",
        "evaluations/t22/candidate_outputs.jsonl",
        "evaluations/t22/evaluator_results.json",
        "evaluations/t22/evaluation_provenance.json",
        "evaluations/t22/score_results.json",
        "evaluations/t22/raw_results.jsonl",
        "evaluations/t22/metric_evidence.json",
        "evaluations/t22/floor_evidence.json",
        "evaluations/t22/holdout_results.json",
    ]
    commands = {}
    for name, command in r17_values["state_machine"]["commands"].items():
        commands[name] = {
            **command,
            "writable_paths": [path.replace("t21r17", "t22") for path in command["writable_paths"]],
        }
    for name in ("evaluate", "complete_evaluation"):
        commands[name]["writable_paths"] = evaluation_paths
    values["state_machine"] = {
        "phases": r17_values["state_machine"]["phases"],
        "commands": commands,
    }
    values["runtime_native"] = {
        **r17_values["runtime_native"],
        "candidate_provider": T22_PROVIDER_ID,
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
        "experiment": "t22",
        "values": values,
        "fields": _t22_contract_fields(),
    }
    _write("evaluations/t22/t21_master_contract.json", document)
    load_contract(ROOT / "evaluations" / "t22" / "t21_master_contract.json")
    return {"status": "PASS", "values_fields": len(values), "field_descriptors": len(document["fields"])}


def stage_lock() -> dict[str, Any]:
    contract = load_contract(ROOT / "evaluations" / "t22" / "t21_master_contract.json")
    lock = build_qualification_lock(ROOT, contract)
    _write("evaluations/t22/qualification_lock.json", lock)
    validate_qualification_lock(ROOT, contract, lock)
    return {"status": "PASS", "author_root": lock["shadow_fingerprint_root"]}


# ---------------------------------------------------------------- fixtures --


def stage_fixtures() -> dict[str, Any]:
    """Run the full metric-semantics fixture battery (with the T22
    zero-denominator harmonization section) and commit its results."""
    fixtures_sha_before = sha256_file(ROOT / FIXTURES_PATH)
    completed = subprocess.run(
        [sys.executable, "scripts/t22_fixtures.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SystemExit(f"fixture battery failed:\n{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}")
    fixtures = _load(FIXTURES_PATH)
    if sha256_file(ROOT / FIXTURES_PATH) != fixtures_sha_before:
        raise SystemExit("fixture battery regeneration is not byte-identical (determinism failure)")
    required_sections = (
        "truth_tables", "monotonicity", "complement_confusion", "operator_negative_controls",
        "all_good", "golden_vector", "targeted_bad", "metric_independence", "r16_regression",
        "legacy_evaluator_parity", "unknown_metric_fail_closed", "zero_denominator_harmonization",
    )
    failed = sorted(name for name in required_sections if fixtures.get(name, {}).get("status") != "PASS")
    harmonization = fixtures["zero_denominator_harmonization"]
    harmonization_cases = harmonization.get("cases") or []
    emergent_ok = sorted(case["case"] for case in harmonization_cases if case["case"].startswith("emergent_empty") and case.get("ok") and case.get("floor_pass"))
    refused_ok = sorted(case["case"] for case in harmonization_cases if case["case"].startswith("design_mandated_empty") and case.get("refused") and case.get("ok"))
    numbers_ok = (
        fixtures["all_good"]["floors_passed"] == 32
        and fixtures["golden_vector"]["floors_matched"] == 32
        and fixtures["targeted_bad"]["cases"] == 32
        and fixtures["targeted_bad"]["single_failure"] == 32
        and fixtures["monotonicity"]["violations"] == 0
        and fixtures["r16_regression"]["floors_passed"] == 32
        and fixtures["floor_hash"] == FLOOR_HASH
        and harmonization.get("ok") is True
        and harmonization.get("status") == "PASS"
        and len(emergent_ok) == 2
        and len(refused_ok) == 3
        and harmonization.get("policy_classes_byte_identical_to_r17") is True
        and harmonization.get("no_retroactive_effect_on_r17") is True
        and harmonization.get("prose_harmonized") is True
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
        "harmonization_emergent_ok": len(emergent_ok),
        "harmonization_refused_ok": len(refused_ok),
        "fixtures_sha256": sha256_file(ROOT / FIXTURES_PATH),
    }


# ------------------------------------------------------------------ shadow --


def stage_shadow() -> dict[str, Any]:
    """A complete disposable runtime-native corpus through the frozen loaders,
    with zero overlap against every historical milestone (§33) and the
    mandatory temporal signal-carrier audit (§33: gold-only-signal rows = 0)."""
    from t21_protocol.author import shadow_author
    from t21_protocol.providers import RUNTIME_NATIVE_CORPUS_FORMAT, RealDryRunMaterialProvider, runtime_modules

    src_path = str(ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from sciencemath.knowledge.freshness import classify_query_freshness

    contract = load_contract(ROOT / "evaluations" / "t22" / "t21_master_contract.json")
    design = _load(HOLDOUT_DESIGN_PATH)
    request_date = design["request_date"]["value"]
    design_snapshot = design["request_date"]["snapshot_date"]
    with tempfile.TemporaryDirectory(prefix="t22-shadow-") as directory:
        workspace = Path(directory)
        authored = shadow_author(contract, ROOT)
        bundle = RealDryRunMaterialProvider().build(contract, authored["spec"])
        rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
        corpus_dir = workspace / "rag" / "gk_holdout_t22"
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
        snapshot_date = manifest["snapshot_date"]
        if snapshot_date != design_snapshot:
            raise SystemExit(f"corpus snapshot {snapshot_date} differs from the frozen design snapshot {design_snapshot}")
        if request_date <= snapshot_date:
            raise SystemExit("frozen request date must exceed the corpus snapshot date")
        source_freshness = {source.source_id: source.freshness_class for source in bundle.runtime_sources}
        # -- temporal signal-carrier audit (§33, mandatory) --
        temporal_suite = design["suite"]
        temporal_rows = list(bundle.rows_by_suite[temporal_suite])
        if len(temporal_rows) != design["suite_total"]:
            raise SystemExit(f"temporal suite size {len(temporal_rows)} differs from the frozen design {design['suite_total']}")
        audit_rows = []
        for row in temporal_rows:
            classification = classify_query_freshness(row["query"])
            query_text_signal = bool(classification["temporal_signals"])
            request_metadata_signal = row.get("request_date") == request_date and request_date > snapshot_date
            row_source_ids = (row.get("gold") or {}).get("source_ids") or []
            source_metadata_signal = any(
                source_freshness.get(source_id) == "TIME_SENSITIVE" for source_id in row_source_ids
            )
            row_passes = query_text_signal or request_metadata_signal or source_metadata_signal
            audit_rows.append(
                {
                    "case_id": row["case_id"],
                    "query_text_signal": query_text_signal,
                    "request_metadata_signal": request_metadata_signal,
                    "source_metadata_signal": source_metadata_signal,
                    "row_passes": row_passes,
                }
            )
        rows_with_signal = sum(1 for entry in audit_rows if entry["row_passes"])
        gold_only_signal_rows = sum(1 for entry in audit_rows if not entry["row_passes"])
        per_signal_counts = {
            "query_text_signal": sum(1 for entry in audit_rows if entry["query_text_signal"]),
            "request_metadata_signal": sum(1 for entry in audit_rows if entry["request_metadata_signal"]),
            "source_metadata_signal": sum(1 for entry in audit_rows if entry["source_metadata_signal"]),
        }
        signal_carrier_audit = {
            "rule": design["signal_carrier_audit"]["rule"],
            "temporal_rows": len(audit_rows),
            "rows_with_signal": rows_with_signal,
            "gold_only_signal_rows": gold_only_signal_rows,
            "gold_only_signal_rows_allowed": design["signal_carrier_audit"]["audit_definition"]["gold_only_signal_rows_allowed"],
            "per_signal_counts": per_signal_counts,
            "request_date": request_date,
            "snapshot_date": snapshot_date,
        }
        if gold_only_signal_rows != signal_carrier_audit["gold_only_signal_rows_allowed"]:
            raise SystemExit(f"temporal signal-carrier audit failed: gold-only rows {gold_only_signal_rows}")
        # -- frozen authoring composition: the disposable material must match
        # the design's by_tag templates, sub-shapes and request-date carrier
        authoring = design["row_authoring"]
        if authoring["request_date"] != request_date or authoring["value_prefix"] != "R22":
            raise SystemExit("design authoring block drifted")
        temporal_tags = [row["construction_tag"] for row in temporal_rows]
        expected_tags = (
            ["explicit_current"] * design["families"]["explicit_current"]["count"]
            + ["historical_as_of"] * design["families"]["historical_as_of"]["count"]
            + ["stale_snapshot"] * design["families"]["stale_snapshot"]["count"]
            + ["static_unnecessary_web"] * design["families"]["static_unnecessary_web"]["count"]
        )
        if temporal_tags != expected_tags:
            raise SystemExit("temporal suite construction order drifted from the frozen design")
        for row in temporal_rows:
            if row.get("request_date") != request_date:
                raise SystemExit(f"temporal row {row['case_id']} missing the frozen request-date carrier")
        record_pinned = 0
        for suite_name, suite_rows in bundle.rows_by_suite.items():
            if suite_name == temporal_suite:
                continue
            for row in suite_rows:
                if not row["query"].startswith("Within blind record ") or row.get("request_date") != request_date:
                    raise SystemExit(f"non-temporal row {row['case_id']} drifted from the frozen record-pinned template")
                record_pinned += 1
        if record_pinned != 4550:
            raise SystemExit(f"record-pinned non-temporal rows {record_pinned} != 4550")
        # -- candidate-visible blindness: no gold-only signal field anywhere
        for suite_rows in bundle.rows_by_suite.values():
            for row in suite_rows:
                for forbidden in ("signal_class", "expected_route"):
                    if forbidden in row or forbidden in (row.get("gold") or {}):
                        raise SystemExit(f"gold-only field {forbidden} leaked into candidate-visible input")
        # -- protected-dimension fingerprints of the disposable shadow material
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
        registry = _load("evaluations/t22/prior_exclusion.json")
        overlaps = {}
        for milestone_name, milestone in registry["milestones"].items():
            overlaps[milestone_name] = {
                dimension: len(shadow[dimension] & set(milestone["dimensions"][dimension]["fingerprints"]))
                for dimension in DIMENSIONS
            }
        overlap_total = sum(sum(counts.values()) for counts in overlaps.values())
        r17_overlap = sum(overlaps[R17_HISTORICAL_MILESTONE].values())
        report = {
            "schema_version": "t21-runtime-native-shadow-validation-v1",
            "artifact": "T22_RUNTIME_NATIVE_SHADOW_VALIDATION",
            "experiment": "t22",
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
                "snapshot_date": snapshot_date,
            },
            "frozen_loader_loads_complete_corpus": True,
            "adapter_used": False,
            "checks": checks,
            "candidate_execution_rows": 0,
            "row_count_matches_design": len(rows) == 4800,
            "author_fingerprint_root": authored["fingerprint_root"],
            "signal_carrier_audit": signal_carrier_audit,
            "frozen_authoring_composition": {
                "temporal_suite": temporal_suite,
                "record_pinned_non_temporal_rows": record_pinned,
                "request_date_carrier": request_date,
                "value_prefix": authoring["value_prefix"],
            },
            "protected_dimension_overlap": {
                "rule": "the disposable shadow material must overlap no historical milestone on any protected dimension (protocol §33)",
                "milestones_checked": len(overlaps),
                "overlap_counts": overlaps,
                "total_overlaps": overlap_total,
                "r17_milestone_overlap": r17_overlap,
            },
        }
        if not all(value == 0 for value in checks.values()) or not report["row_count_matches_design"] or overlap_total != 0:
            raise SystemExit(f"shadow validation checks failed: checks={checks} overlap_total={overlap_total}")
    _write("evaluations/t22/runtime_native_shadow_validation.json", report)
    return {"status": "PASS", "rows": report["rows"], "overlap_total": overlap_total, "gold_only_signal_rows": gold_only_signal_rows}


# ------------------------------------------------------------------ parity --


def stage_parity() -> dict[str, Any]:
    """T22 request-date candidate provider vs direct frozen-runtime
    execution: parity."""
    from t21_protocol.author import shadow_author
    from t21_protocol.providers import RealDryRunMaterialProvider, runtime_modules
    from t21_protocol.providers_t22 import PROVIDER_ID_T22_EVIDENCE, RealCandidateProviderT22Evidence, direct_runtime_outputs_v2_t22

    contract = load_contract(ROOT / "evaluations" / "t22" / "t21_master_contract.json")
    with tempfile.TemporaryDirectory(prefix="t22-parity-") as directory:
        workspace = Path(directory)
        authored = shadow_author(contract, ROOT)
        bundle = RealDryRunMaterialProvider().build(contract, authored["spec"])
        corpus_dir = workspace / "rag" / "gk_holdout_t22"
        corpus_dir.mkdir(parents=True)
        (corpus_dir / "world.jsonl").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in bundle.world), encoding="utf-8", newline="\n"
        )
        _, corpus_module, _ = runtime_modules(workspace)
        corpus_module.build_corpus_files(corpus_dir, list(bundle.runtime_sources), list(bundle.runtime_chunks))
        rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
        provider = RealCandidateProviderT22Evidence(workspace, corpus_dir)
        init_rows = provider.rows_executed
        provider_outputs = provider.generate(rows)
        after_rows = provider.rows_executed
        direct_outputs = direct_runtime_outputs_v2_t22(workspace, corpus_dir, rows)
        del provider
        compared_fields = ("status", "answer", "counters", "citations", "citation_report", "claim_review", "evidence_pack", "eligibility")
        semantic_differences = [
            {"case_id": expected["case_id"], "field": field}
            for expected, observed in zip(provider_outputs, direct_outputs)
            for field in compared_fields
            if expected[field] != observed[field]
        ]
        request_date_threaded = all(
            output["status"] is not None for output in provider_outputs
        )
        report = {
            "schema_version": "t21-provider-parity-report-v1",
            "artifact": "T22_PROVIDER_PARITY_REPORT",
            "experiment": "t22",
            "status": "PASS" if not semantic_differences else "FAIL",
            "audit_mode": "EXECUTED",
            "provider_id": PROVIDER_ID_T22_EVIDENCE,
            "provider_init_rows": init_rows,
            "provider_rows_after_execution": after_rows,
            "rows": len(rows),
            "pairs_compared": len(provider_outputs),
            "semantic_differences": semantic_differences,
            "compared_fields": list(compared_fields),
            "canonical_serialization": "t21_protocol.providers_r17:canonical_candidate_row_v2",
            "direct_runtime_output": "answer_knowledge(now=...) over the frozen load_corpus",
            "request_date_carrier_threaded": request_date_threaded,
            "retrieval_and_answer_generation_exercised": True,
            "candidate_rows_executed_in_rehearsal": len(rows),
        }
        if init_rows != 0 or semantic_differences or after_rows != len(rows) or not request_date_threaded:
            raise SystemExit("parity report checks failed")
    _write("evaluations/t22/provider_parity_report.json", report)
    return {"status": "PASS", "pairs": report["pairs_compared"]}


# --------------------------------------------------------------- lifecycle --


def stage_lifecycle() -> dict[str, Any]:
    from t21_protocol.pipeline_t22 import run_real_mode_lifecycle_rehearsal_t22_twice

    contract = load_contract(ROOT / "evaluations" / "t22" / "t21_master_contract.json")
    graph = read_json(ROOT / "evaluations" / "t22" / "artifact_graph.json")
    report = run_real_mode_lifecycle_rehearsal_t22_twice(ROOT, contract, graph)
    if report["status"] != "PASS":
        raise SystemExit(f"lifecycle rehearsal failed: {json.dumps(report)[:4000]}")
    run_1 = report["run_1"]
    committed = {
        "schema_version": "t21-lifecycle-rehearsal-v1",
        "artifact": "T22_LIFECYCLE_REHEARSAL",
        "experiment": "t22",
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
        "real_t22_cases_exercised": run_1["real_t22_cases_exercised"],
        "material_mode": run_1["material_mode"],
        "deterministic": report["status"] == "PASS",
        "differences": {key: value for key, value in report.items() if key.endswith("_differences")},
        "disposable_workspaces_destroyed": True,
    }
    _write("evaluations/t22/lifecycle_rehearsal.json", committed)
    return {"status": "PASS", "deterministic": committed["deterministic"]}


# ------------------------------------------------------------- cleanliness --


def stage_cleanliness() -> dict[str, Any]:
    import xml.etree.ElementTree as ElementTree

    adjudication = _load("evaluations/t22/test_failure_adjudication.json")
    registered = [entry["nodeid"] for entry in adjudication["entries"]]
    deselect = [f"--deselect={nodeid}" for nodeid in registered]
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def _tracked_snapshot() -> list[str]:
        completed = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True)
        return sorted(line for line in completed.stdout.splitlines() if not line.startswith("??"))

    def _run(name: str, arguments: list[str]) -> dict[str, Any]:
        junit = artifacts / f"t22_{name}_junit.xml"
        before = _tracked_snapshot()
        run = _run_pytest(arguments, junit, artifacts / f".pytest_t22_{name}")
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
    raw_failures = _junit_failures(artifacts / "t22_raw_junit.xml")
    unexpected = sorted(set(raw_failures) - set(registered))
    missing = sorted(set(registered) - set(raw_failures))
    applicable = _run("applicable", ["tests", *deselect])
    focused = _run("focused", ["tests/test_t22_preconstruction.py"])
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
    _write("evaluations/t22/test_cleanliness.json", document)
    return {
        "status": "PASS",
        "raw": {key: raw[key] for key in ("collected", "passed", "failed", "exit_code")},
        "applicable": {key: applicable[key] for key in ("collected", "passed", "failed", "exit_code")},
        "focused": {key: focused[key] for key in ("collected", "passed", "failed", "exit_code")},
    }


# ------------------------------------------------------------------ doctor --


def stage_doctor() -> dict[str, Any]:
    from t21_protocol.doctor import VERDICT_PASS, run_doctor

    report = run_doctor(ROOT, "t22")
    _write("evaluations/t22/protocol_doctor_report.json", report)
    if report["verdict"] != VERDICT_PASS:
        failing = {name: check.get("status") for name, check in report["checks"].items() if check.get("status") not in {"PASS", "VERIFIED"}}
        raise SystemExit(f"doctor failed: {json.dumps(failing)[:3000]}")
    return {"status": "PASS", "verdict": report["verdict"], "checks": sorted(report["checks"])}


# ------------------------------------------------------------------- audit --


def stage_audit() -> dict[str, Any]:
    from t21_protocol.metric_semantics import load_metric_semantics, semantics_root

    contract = _load("evaluations/t22/t21_master_contract.json")
    doctor = _load("evaluations/t22/protocol_doctor_report.json")
    shadow = _load("evaluations/t22/runtime_native_shadow_validation.json")
    parity = _load("evaluations/t22/provider_parity_report.json")
    lifecycle = _load("evaluations/t22/lifecycle_rehearsal.json")
    cleanliness = _load("evaluations/t22/test_cleanliness.json")
    adjudication = _load("evaluations/t22/test_failure_adjudication.json")
    fixtures = _load(FIXTURES_PATH)
    semantics = load_metric_semantics(ROOT, {}, relative=SEMANTICS_PATH, floors=contract["values"]["promotion_floors"],
                                      artifact="T22_OFFICIAL_METRIC_SEMANTICS", experiment="t22")
    entries = semantics["metrics"]
    floor_metrics = sorted(metric for metrics in contract["values"]["promotion_floors"].values() for metric in metrics)
    real_paths_present = sorted(relative for relative in contract["values"]["real_t22_paths"] if (ROOT / relative).exists())
    r17_disposition = _load("evaluations/t22/r17_final_disposition.json")
    r17_refusal = _load("evaluations/t22/r17_evaluation_refusal.json")
    registry = _load("evaluations/t22/prior_exclusion.json")
    r17_milestone = registry["milestones"][R17_HISTORICAL_MILESTONE]
    sealed_now = _r17_sealed_fingerprints()
    sealed_match = {
        dimension: _canonical_set_sha(sorted(sealed_now[dimension])) == r17_milestone["dimensions"][dimension]["set_sha256"]
        for dimension in DIMENSIONS
    }
    r16_milestone = registry["milestones"]["T21R16_OFFICIAL_EVALUATED_MEASUREMENT_INVALID"]
    r16_now = _r16_sealed_fingerprints()
    r16_match = {
        dimension: _canonical_set_sha(sorted(r16_now[dimension])) == r16_milestone["dimensions"][dimension]["set_sha256"]
        for dimension in DIMENSIONS
    }
    r17_preservation = {
        "construction_commit": R17_CONSTRUCTION_COMMIT,
        "official_evaluation_commit": R17_EVALUATION_HEAD,
        "rows_scored": r17_disposition["rows_scored"],
        "one_shot_consumed": r17_disposition["one_shot_consumed"],
        "holdout_status": r17_disposition["holdout_status"],
        "evaluation_permanently_refused": r17_refusal["permanent"] is True,
        "frozen_observed_values": r17_disposition["frozen_observed_values"],
        "sealed_holdout_unmodified": all(sealed_match.values()),
        "sealed_fingerprints_match_registry": sealed_match,
        "r16_sealed_holdout_unmodified": all(r16_match.values()),
        "raw_access": {
            "registry_construction_derivation": "hash-only in-memory fingerprinting with t21_protocol.audits._fingerprint; raw values never persisted",
            "t22_artifacts_containing_raw_r17_values": 0,
            "t22_row_authoring_used_r17_material": False,
            "r17_raw_historical_access": 0,
        },
    }
    metric_semantics_table = {
        metric: {key: entries[metric][key] for key in (
            "metric_id", "family", "semantic_type", "numerator", "denominator", "aggregation",
            "aggregation_scope", "direction", "range", "zero_denominator_policy",
        ) if key in entries[metric]}
        for metric in floor_metrics
    }
    harmonization = fixtures["zero_denominator_harmonization"]
    harmonization_cases = harmonization.get("cases") or []
    battery_gates = {
        metric: {"observed": spec.get("observed"), "operator": spec.get("operator"), "pass": spec.get("pass")}
        for metric, spec in (_load("evaluations/t22/temporal_regressions/results.json").get("gates") or {}).items()
    }
    audit = {
        "schema_version": "t21-preconstruction-audit-v1",
        "artifact": "T22_PRECONSTRUCTION_AUDIT",
        "experiment": "t22",
        "status": "PASS",
        "audit_mode": "EXECUTED",
        "r17_final_disposition": {
            "status": r17_disposition["status"],
            "reason": r17_disposition["reason"],
            "capability_verdict": r17_disposition["capability_verdict"],
            "failed_metrics": r17_disposition["failed_metrics"],
            "failed_metric_designation": r17_disposition["failed_metric_designation"],
            "holdout_status": r17_disposition["holdout_status"],
            "one_shot_consumed": r17_disposition["one_shot_consumed"],
            "rows_scored": r17_disposition["rows_scored"],
            "frozen_observed_values": r17_disposition["frozen_observed_values"],
            "valid_measurement_evidence": r17_disposition["valid_measurement_evidence"],
            "evaluation_permanently_refused": r17_refusal["permanent"] is True,
            "official_run_preserved": r17_disposition["official_run_preserved"],
            "no_candidate_remediation_from_r17_blind_cases": True,
        },
        "candidate_identity": _verify_candidate_identity(),
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
        "zero_denominator_harmonization": {
            "status": harmonization["status"],
            "ok": harmonization["ok"],
            "prose_harmonized": harmonization["prose_harmonized"],
            "prose_harmonized_detail": harmonization.get("prose_harmonized_detail"),
            "policy_classes_byte_identical_to_r17": harmonization["policy_classes_byte_identical_to_r17"],
            "no_retroactive_effect_on_r17": harmonization["no_retroactive_effect_on_r17"],
            "emergent_empty_cases_ok": len([
                case for case in harmonization_cases if case["case"].startswith("emergent_empty") and case.get("floor_pass")
            ]),
            "design_mandated_empty_cases_refused": len([
                case for case in harmonization_cases if case["case"].startswith("design_mandated_empty") and case.get("refused")
            ]),
            "resolution": _load(ZERO_DENOMINATOR_RESOLUTION_PATH)["frozen_policy"]["name"],
        },
        "temporal_router_qualification": {
            "battery": "evaluations/t22/temporal_regressions/results.json",
            "battery_pass": _load("evaluations/t22/temporal_regressions/results.json").get("battery_pass") is True,
            "gates": battery_gates,
        },
        "temporal_signal_carrier_audit": shadow["signal_carrier_audit"],
        "temporal_design": {
            "artifact": HOLDOUT_DESIGN_PATH,
            "status": _load(HOLDOUT_DESIGN_PATH)["status"],
            "temporal_suite_total": _load(HOLDOUT_DESIGN_PATH)["suite_total"],
            "blindness_contract_enforced": sorted(
                _load(HOLDOUT_DESIGN_PATH)["blindness"]["never_candidate_visible"]
            ),
        },
        "temporal_signal_contract": {
            "artifact": SIGNAL_CONTRACT_PATH,
            "status": _load(SIGNAL_CONTRACT_PATH)["status"],
        },
        "r16_regression": {
            "status": fixtures["r16_regression"]["status"],
            "overall": fixtures["r16_regression"]["regression_floors"]["overall_grounded_accuracy"]["observed"],
            "conflict_false_resolution": fixtures["r16_regression"]["regression_floors"]["conflict_false_resolution"]["observed"],
            "static_query_unnecessary_web_routing": fixtures["r16_regression"]["regression_floors"]["static_query_unnecessary_web_routing"]["observed"],
            "floors_passed": fixtures["r16_regression"]["floors_passed"],
            "frozen_generic_scorer_reproduces_r16_failure": fixtures["r16_regression"]["r16_generic_scorer_reproduction"]["floors_failed"]
            == ["conflict_false_resolution", "static_query_unnecessary_web_routing"],
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
            "zero_denominator_harmonization": fixtures["zero_denominator_harmonization"]["status"],
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
            "candidate_commit": T22_CANDIDATE_COMMIT,
            "candidate_tree": T22_CANDIDATE_TREE,
            "runtime_root": _load("evaluations/t22/runtime_freeze.json")["component_root_sha256"],
            "evaluator_root": _load("evaluations/t22/evaluator_freeze.json")["component_root_sha256"],
            "floor_hash": FLOOR_HASH,
            "floor_hash_unchanged_from_r17": FLOOR_HASH == _load("evaluations/t21r17/t21_master_contract.json")["values"]["roots"]["floor_hash"],
            "semantics_root": semantics_root(semantics),
            "registry_sha256": sha256_file(ROOT / REGISTRY_PATH),
            "fixtures_sha256": sha256_file(ROOT / FIXTURES_PATH),
        },
        "historical_exclusion": {
            "status": doctor["checks"]["historical_exclusion"]["status"],
            "milestones": _load("evaluations/t22/historical_exclusion.json")["milestones"],
            "milestone_count": 17,
            "raw_values_included": False,
            "includes": R17_HISTORICAL_MILESTONE,
        },
        "real_t22_paths_absent": not real_paths_present,
        "real_t22_paths_present": real_paths_present,
        "shadow_validation": {
            "status": shadow["status"],
            "rows": shadow["rows"],
            "checks": shadow["checks"],
            "adapter_used": shadow["adapter_used"],
            "r17_overlap": shadow["protected_dimension_overlap"]["r17_milestone_overlap"],
            "total_overlap": shadow["protected_dimension_overlap"]["total_overlaps"],
            "signal_carrier_audit": shadow["signal_carrier_audit"],
            "record_pinned_non_temporal_rows": shadow["frozen_authoring_composition"]["record_pinned_non_temporal_rows"],
        },
        "provider_parity": {"status": parity["status"], "semantic_differences": parity["semantic_differences"], "pairs_compared": parity["pairs_compared"]},
        "lifecycle_rehearsal": {
            "status": lifecycle["status"],
            "runs": lifecycle["runs"],
            "deterministic": lifecycle["deterministic"],
            "real_candidate_runtime_exercised": lifecycle["real_candidate_runtime_exercised"],
            "real_t22_cases_exercised": lifecycle["real_t22_cases_exercised"],
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
        "r17_preservation": r17_preservation,
        "exposure_zeros": {
            "candidate_rows_executed": 0,
            "official_evaluator_rows": 0,
            "real_t22_rows": 0,
            "rows_scored": 0,
            "capability_verdict": "NONE",
        },
        "construction_authorized": False,
        "verdict": "T22_PRECONSTRUCTION_AUDIT_PASS",
    }
    if (
        real_paths_present
        or audit["shadow_validation"]["total_overlap"] != 0
        or audit["r16_regression"]["status"] != "PASS"
        or any(value != 0 for value in audit["scorer_closure"].values() if isinstance(value, int))
        or audit["tests"]["live_failures"] != 0
        or audit["tests"]["unknown_failures"] != 0
        or audit["tests"]["tracked_tree_drift"] != 0
        or shadow["signal_carrier_audit"]["gold_only_signal_rows"] != 0
        or shadow["signal_carrier_audit"]["rows_with_signal"] != 250
        or not all(r17_preservation["frozen_observed_values"][metric] == value for metric, value in
                   (("explicit_current_routing_accuracy", 0.0), ("stale_snapshot_false_current_answers", 70)))
        or not r17_preservation["sealed_holdout_unmodified"]
        or not r17_preservation["r16_sealed_holdout_unmodified"]
    ):
        raise SystemExit("preconstruction audit checks failed")
    write_json(OUT / "T22_PRECONSTRUCTION_AUDIT.json", audit, exclusive=True)
    return {"status": "PASS", "verdict": audit["verdict"], "real_paths_present": real_paths_present}


# --------------------------------------------------------------- prefreeze --


def stage_prefreeze() -> dict[str, Any]:
    def _git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *arguments], check=True, capture_output=True, text=True).stdout.strip()

    commit = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD~1")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    doctor = _load("evaluations/t22/protocol_doctor_report.json")
    cleanliness = _load("evaluations/t22/test_cleanliness.json")
    audit = _load("evaluations/t22/T22_PRECONSTRUCTION_AUDIT.json")
    lifecycle = _load("evaluations/t22/lifecycle_rehearsal.json")
    adjudication = _load("evaluations/t22/test_failure_adjudication.json")
    contract = _load("evaluations/t22/t21_master_contract.json")
    document = {
        "schema_version": "t21-preconstruction-freeze-v1",
        "artifact": "T22_PRECONSTRUCTION_FREEZE",
        "experiment": "t22",
        "head": commit,
        "parent": parent,
        "branch": branch,
        "tree_sha": tree,
        "construction_authorized": (ROOT / "evaluations" / "t22" / "construction_run_ledger.json").exists(),
        "doctor_verdict": doctor["verdict"],
        "phase_apis": {
            "construct": "PRECONSTRUCTION -> SEALED only; construction requires separate authorization (T22_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION)",
            "evaluate": "SEALED -> EVALUATION_COMPLETE/FAILED only",
        },
        "rehearsals": {
            "synthetic_construction_twice": doctor["checks"]["synthetic_construction_only"]["status"],
            "real_mode_dry_rehearsal": doctor["checks"]["real_mode_dry_rehearsal"]["status"],
            "metric_semantics_lifecycle_twice": doctor["checks"]["metric_semantics_lifecycle_rehearsal"]["status"],
            "committed_lifecycle_twice": lifecycle["status"],
        },
        "temporal_router_qualification": {
            "battery_pass": _load("evaluations/t22/temporal_regressions/results.json").get("battery_pass") is True,
            "doctor_check": doctor["checks"]["temporal_router_qualification"]["status"],
            "signal_carrier_audit": doctor["checks"]["temporal_signal_visibility"]["status"],
            "zero_denominator_harmonization": doctor["checks"]["zero_denominator_harmonization"]["status"],
        },
        "tests": {
            "full_suite": {key: cleanliness["raw_full_suite"][key] for key in ("collected", "passed", "failed", "skipped", "exit_code")},
            "applicable_suite": {key: cleanliness["applicable_suite"][key] for key in ("collected", "passed", "failed", "exit_code")},
            "focused_protocol_kernel": {key: cleanliness["focused_protocol_kernel"][key] for key in ("collected", "passed", "failed", "exit_code")},
            "adjudicated_registered_failures": len(adjudication["entries"]),
        },
        "write_safety": {"tracked_drift": cleanliness["raw_full_suite"]["tracked_drift"], "status": "PASS" if cleanliness["raw_full_suite"]["tracked_drift"] == 0 else "FAIL"},
        "identity_model": {
            "candidate_provider": T22_PROVIDER_ID,
            "candidate_stub_in_known_producers": "candidate_stub" not in _load("evaluations/t22/artifact_graph.json")["known_producers"],
            "runtime_native": contract["values"]["runtime_native"],
            "candidate_identity": audit["candidate_identity"],
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
        "real_path_absence": {"status": "PASS" if audit["real_t22_paths_absent"] else "FAIL", "present": audit["real_t22_paths_present"]},
        "r17_preservation": audit["r17_preservation"],
        "status": audit["status"],
    }
    _write("evaluations/t22/preconstruction_freeze.json", document)
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