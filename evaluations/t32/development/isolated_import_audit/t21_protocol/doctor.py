"""Single fail-closed qualification command for the T21 protocol kernel."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from .adjudication import generate_applicability, validate_adjudication
from .artifact_graph import load_artifact_graph, phase_ownership_report, validate_artifact_graph
from .audits import validate_executed_audit
from .construction import run_construction
from .context import (
    CONSTRUCTION_TOKENS,
    EVALUATION_TOKENS,
    ConstructionAuthorization,
    EvaluationAuthorization,
    WorkspaceMode,
    require_construction_authorization,
    require_evaluation_authorization,
)
from .contract import load_contract, validate_master_contract
from .errors import ValidationError
from .exclusion import validate_historical_policy, validate_remediation_policy
from .freeze import verify_freeze
from .import_audit import dynamic_import_write_audit, static_import_write_audit
from .ledger import ConstructionLedger, EvaluationLedger
from .pipeline import run_real_mode_dry_rehearsal, run_synthetic_construction_twice, run_synthetic_twice
from .providers import (
    RUNTIME_NATIVE_CORPUS_FORMAT,
    RealCandidateProvider,
    SyntheticCandidateProvider,
    SyntheticMaterialProvider,
    contract_runtime_native,
    runtime_modules,
    validate_candidate_provider,
    validate_material_provider,
)
from .qualification import validate_qualification_lock
from .seal import (
    HOLDOUT_FROZEN_FIELDS_BY_SCHEMA_VERSION,
    validate_holdout_frozen,
    validate_holdout_frozen_schema,
)
from .state_machine import ProtocolStateMachine
from .taxonomy import canonical_labels, coverage_report, load_taxonomy
from .util import read_json, sha256_file, sha256_json, write_json
from .write_guard import diff_snapshots, tracked_tree

VERDICT_PASS = "T21_PROTOCOL_DOCTOR_PASS"
VERDICT_FAIL = "T21_PROTOCOL_DOCTOR_FAIL"
NEGATIVE_CONTROLS = {
    "missing seal input": "PRECONSTRUCTION",
    "unbound required seal artifact": "PRECONSTRUCTION",
    "incomplete HOLDOUT_FROZEN": "PRECONSTRUCTION",
    "missing construction-ledger implementation": "PRECONSTRUCTION",
    "second ledger creation": "PRECONSTRUCTION",
    "author fingerprint-root mismatch": "CONSTRUCTION_STARTED",
    "test writing historical committed file": "PRECONSTRUCTION",
    "import-time repository write": "PRECONSTRUCTION",
    "official validator requiring seal too early": "PRECONSTRUCTION",
    "unknown evaluator taxonomy label": "PRECONSTRUCTION",
    "contract/gate mismatch": "PRECONSTRUCTION",
    "contract/consumer schema mismatch": "PRECONSTRUCTION",
    "missing cross-module callable": "PRECONSTRUCTION",
    "raw exclusion value": "PRECONSTRUCTION",
    "missing historical exclusion dimension": "PRECONSTRUCTION",
    "historical author collision": "PRECONSTRUCTION",
    "missing exact-design context": "PRECONSTRUCTION",
    "construction authorization used for evaluation": "PRECONSTRUCTION",
    "evaluation authorization used for construction": "PRECONSTRUCTION",
    "construction chaining into evaluation": "PRECONSTRUCTION",
    "construction writing evaluation artifact": "PRECONSTRUCTION",
    "evaluation mutating sealed construction artifact": "PRECONSTRUCTION",
    "synthetic provider in real workspace": "PRECONSTRUCTION",
    "stub candidate in real workspace": "PRECONSTRUCTION",
    "placeholder audit in real workspace": "PRECONSTRUCTION",
    "synthetic material sealed in real workspace": "CONSTRUCTION_STARTED",
}
# Runtime-contract controls (T21R16): mandatory for runtime-native experiments,
# absent from historical experiments so their committed registries stay valid.
RUNTIME_CONTRACT_CONTROLS = {
    "runtime schema missing required source field": "PRECONSTRUCTION",
    "runtime source id grammar violation": "PRECONSTRUCTION",
    "runtime manifest missing file checksums": "PRECONSTRUCTION",
    "runtime source missing authority or freshness metadata": "PRECONSTRUCTION",
    "runtime chunk missing section or span metadata": "PRECONSTRUCTION",
    "runtime default-filling of missing required field": "PRECONSTRUCTION",
    "runtime contract not derived from frozen schema": "PRECONSTRUCTION",
}
EXPERIMENT_HELPERS = {
    "t21r15": ("t21r_fixtures", "t21r12_fixtures", "t21r13_fixtures", "t21r14_fixtures"),
    "t21r16": ("t21r_fixtures", "t21r12_fixtures", "t21r13_fixtures", "t21r14_fixtures", "t21r16_fixtures"),
    "t21r17": ("t21r_fixtures", "t21r12_fixtures", "t21r13_fixtures", "t21r14_fixtures", "t21r16_fixtures", "t21r17_fixtures"),
    # T22 — the temporal-preconstruction helper scripts join the registry;
    # every prior experiment's entry stays byte-identical.
    "t22": (
        "t21r_fixtures", "t21r12_fixtures", "t21r13_fixtures", "t21r14_fixtures",
        "t21r16_fixtures", "t21r17_fixtures",
        "t22_metric_semantics", "t22_fixtures", "t22_regression_battery", "t22_preconstruction",
    ),
}


def _ledger_integration() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="t21-ledger-integration-") as directory:
        root = Path(directory)
        results: dict[str, bool] = {}
        construction_path = root / "construction.json"
        construction = ConstructionLedger.create_exclusive(construction_path, "t21r15")
        try:
            ConstructionLedger.create_exclusive(construction_path, "t21r15")
        except Exception:
            results["second_create_refused"] = True
        construction.complete()
        results["started_to_complete"] = construction.state == "COMPLETE"
        try:
            ConstructionLedger.create_exclusive(construction_path, "t21r15")
        except Exception:
            results["restart_after_complete_refused"] = True
        evaluation_path = root / "evaluation.json"
        evaluation = EvaluationLedger.create_exclusive(evaluation_path, "t21r15")
        evaluation.fail()
        results["started_to_failed"] = evaluation.state == "FAILED"
        try:
            EvaluationLedger.create_exclusive(evaluation_path, "t21r15")
        except Exception:
            results["restart_after_failed_refused"] = True
        return {"status": "PASS" if len(results) == 5 and all(results.values()) else "FAIL", **results}


def _marker_schema_check(path: Path) -> dict[str, Any]:
    schema_document = read_json(path)
    # The schema document carries its own namespace ("t21-holdout-frozen-schema-vN");
    # the marker version is derived mechanically from the schema's field set.
    properties = schema_document.get("properties")
    if not isinstance(properties, dict):
        raise ValidationError("HOLDOUT_FROZEN schema document has no properties")
    schema_version = (
        "t21-holdout-frozen-v2" if "candidate_provider_sha256" in properties else "t21-holdout-frozen-v1"
    )
    declared = schema_document.get("schema_version")
    if declared != schema_version.replace("holdout-frozen", "holdout-frozen-schema"):
        raise ValidationError(
            f"HOLDOUT_FROZEN schema document version {declared!r} does not describe marker version {schema_version!r}"
        )
    fields = HOLDOUT_FROZEN_FIELDS_BY_SCHEMA_VERSION.get(schema_version)
    if fields is None:
        raise ValidationError(f"unsupported HOLDOUT_FROZEN schema_version: {schema_version!r}")
    sample = {
        "schema_version": schema_version,
        "experiment": "t21r15",
        "construction_status": "COMPLETE",
        "holdout_manifest_sha256": "a" * 64,
        "freeze_root_sha256": "b" * 64,
        "candidate_commit": "c" * 40,
        "candidate_tree": "d" * 40,
        "runtime_root": "e" * 64,
        "evaluator_root": "f" * 64,
        "floor_hash": "0" * 64,
        "construction_attempts": 1,
        "corpus_materializations": 1,
        "suite_materializations": 1,
        "candidate_rows_executed": 0,
        "runtime_rows_executed": 0,
        "official_evaluator_invocations": 0,
        "workspace_mode": "REAL_EXPERIMENT",
        "material_mode": "REAL_BLIND",
    }
    if schema_version == "t21-holdout-frozen-v2":
        sample.update(
            {
                "runtime_data_contract_root": "1" * 64,
                "runtime_corpus_contract_sha256": "2" * 64,
                "runtime_field_provenance_sha256": "3" * 64,
                "runtime_loader_validation_sha256": "4" * 64,
                "candidate_provider_id": "t21_protocol.providers:RealCandidateProvider",
                "candidate_provider_sha256": "5" * 64,
            }
        )
    result = validate_holdout_frozen(sample)
    schema = validate_holdout_frozen_schema(schema_document, schema_version=schema_version)
    return {**result, "schema_status": schema["status"], "schema_version": schema_version, "fields": len(fields)}


def _negative_control_registry(path: Path, *, runtime_native: bool = False) -> dict[str, Any]:
    document = read_json(path)
    entries = document.get("controls", [])
    expected = dict(NEGATIVE_CONTROLS)
    if runtime_native:
        expected.update(RUNTIME_CONTRACT_CONTROLS)
    observed = {entry.get("failure_class"): entry.get("latest_legal_phase") for entry in entries}
    missing = sorted(set(expected) - set(observed))
    mismatched = sorted(name for name, phase in expected.items() if observed.get(name) != phase)
    return {
        "status": "PASS" if not missing and not mismatched else "FAIL",
        "controls": len(entries),
        "missing": missing,
        "phase_mismatches": mismatched,
    }


def _real_paths(root: Path, contract: Any) -> dict[str, Any]:
    experiment = contract.experiment
    try:
        real_paths = contract.get(f"real_{experiment}_paths")
    except KeyError:
        # t21rN contracts name the field real_rN_paths (real_r15_paths, real_r16_paths).
        real_paths = contract.get(f"real_{experiment.replace('t21', '', 1)}_paths")
    paths = [root / relative for relative in real_paths]
    present = [path.relative_to(root).as_posix() for path in paths if path.exists()]
    return {"status": "PASS" if not present else "FAIL", "present": present, "checked": len(paths)}


def _phase_api_check(experiment: str = "t21r15") -> dict[str, Any]:
    from .evaluate import run_evaluation

    results = {
        "production_construction_callable": callable(run_construction),
        "production_evaluation_callable": callable(run_evaluation),
    }
    if experiment == "t21r17":
        from .evaluate_r17 import run_evaluation_r17

        results["metric_semantics_evaluation_callable"] = callable(run_evaluation_r17)
    elif experiment == "t22":
        from .evaluate_t22 import run_evaluation_t22

        results["metric_semantics_evaluation_callable"] = callable(run_evaluation_t22)
    return {"status": "PASS" if all(results.values()) else "FAIL", **results}


def _phase_separation(root: Path, graph: dict[str, Any], construction_rehearsal: dict[str, Any]) -> dict[str, Any]:
    source = (root / "t21_protocol" / "construction.py").read_text(encoding="utf-8")
    forbidden = ("run_evaluation", "EvaluationLedger", "evaluate_rows", "score(")
    static_edges = sum(source.count(token) for token in forbidden)
    run_1 = construction_rehearsal.get("run_1", {}).get("construction", {})
    run_2 = construction_rehearsal.get("run_2", {}).get("construction", {})
    dynamic_evaluation_executions = sum(
        int(report.get("official_evaluation_executions", -1)) for report in (run_1, run_2)
    )
    ownership = phase_ownership_report(graph)
    passed = static_edges == 0 and dynamic_evaluation_executions == 0 and ownership["status"] == "PASS"
    return {
        "status": "PASS" if passed else "FAIL",
        "construction_to_evaluation_call_edges": static_edges,
        "dynamic_official_evaluation_executions": dynamic_evaluation_executions,
        **{key: value for key, value in ownership.items() if key != "status"},
    }


def _provider_separation(experiment: str) -> dict[str, Any]:
    results: dict[str, bool] = {}
    synthetic_material = SyntheticMaterialProvider()
    synthetic_candidate = SyntheticCandidateProvider()
    try:
        validate_material_provider(synthetic_material, WorkspaceMode.REAL_EXPERIMENT)
    except Exception:
        results["synthetic_provider_rejected_in_real"] = True
    try:
        validate_candidate_provider(synthetic_candidate, WorkspaceMode.REAL_EXPERIMENT)
    except Exception:
        results["stub_candidate_rejected_in_real"] = True
    try:
        validate_executed_audit(
            {"artifact": "NEGATIVE_CONTROL", "status": "PASS", "audit_mode": "EXECUTED", "placeholder": True},
            WorkspaceMode.REAL_EXPERIMENT,
        )
    except Exception:
        results["placeholder_audit_rejected_in_real"] = True
    try:
        require_construction_authorization(
            EvaluationAuthorization(EVALUATION_TOKENS[experiment]), experiment=experiment
        )
    except Exception:
        results["evaluation_token_rejected_by_construction"] = True
    try:
        require_evaluation_authorization(
            ConstructionAuthorization(CONSTRUCTION_TOKENS[experiment]), experiment=experiment
        )
    except Exception:
        results["construction_token_rejected_by_evaluation"] = True
    other = next(name for name in CONSTRUCTION_TOKENS if name != experiment)
    try:
        require_construction_authorization(CONSTRUCTION_TOKENS[other], experiment=experiment)
    except Exception:
        results[f"foreign_{other}_construction_token_rejected"] = True
    try:
        require_evaluation_authorization(EVALUATION_TOKENS[other], experiment=experiment)
    except Exception:
        results[f"foreign_{other}_evaluation_token_rejected"] = True
    return {"status": "PASS" if len(results) == 7 and all(results.values()) else "FAIL", **results}


_DOCTOR_PROBE_STATEMENT = "Doctor probe record dp-0001 states the registered value Doctor registered value 00001."
_DOCTOR_PROBE_QUERY = "Within doctor probe record dp-0001, what registered value is stated?"


def _doctor_probe_source(schema: Any, corpus_module: Any) -> Any:
    return schema.KnowledgeSourceRecord(
        source_id=schema.make_source_id("Doctor runtime probe", "Mango doctor probe register", "probe-v1"),
        source_title="Doctor runtime probe",
        source_type="fixture_register",
        source_uri_or_origin="blind://doctor/dp-0001",
        publisher_or_collection="Mango doctor probe register",
        license="project_owned_fixtures",
        revision_or_version="probe-v1",
        retrieved_at_or_snapshot_date=corpus_module.CORPUS_SNAPSHOT_DATE,
        language="en",
        authority_class="PRIMARY_REFERENCE",
        freshness_class="STATIC",
        topic_tags=["doctor_probe"],
        content_text=_DOCTOR_PROBE_STATEMENT,
    )


def _runtime_probe_execution(workspace: Path, repo_root: Path) -> dict[str, Any]:
    """End-to-end doctor probe: frozen producers -> frozen manifest builder ->
    frozen loader -> frozen candidate runtime -> canonical candidate row."""
    from .providers import canonical_candidate_row

    schema, corpus_module, pipeline_module = runtime_modules(repo_root)
    statement = _DOCTOR_PROBE_STATEMENT
    source = _doctor_probe_source(schema, corpus_module)
    chunk = schema.chunk_source_text(source, [("record", statement)])[0]
    chunk.metadata = {
        **chunk.metadata,
        "fact_entity": "dp-0001",
        "fact_attribute": "REGISTERED_VALUE",
        "fact_value": "Doctor registered value 00001",
    }
    corpus_dir = workspace / "rag" / "doctor_runtime_probe"
    manifest = corpus_module.build_corpus_files(corpus_dir, [source], [chunk])
    corpus = corpus_module.load_corpus(corpus_dir)
    provider = RealCandidateProvider(workspace, corpus_dir)
    init_rows = provider.rows_executed
    probe_row = {
        "case_id": "dp-0001",
        "query": _DOCTOR_PROBE_QUERY,
        "gold": {"expect_status": "ANSWER", "expected_answer": statement},
    }
    executed = provider.generate([probe_row])
    rows_executed = provider.rows_executed
    del provider
    row = canonical_candidate_row(
        probe_row["case_id"], pipeline_module.answer_knowledge(_DOCTOR_PROBE_QUERY, corpus, top_k=8)
    )
    direct = executed[0]
    parity_identical = row == direct
    return {
        "manifest": manifest,
        "source_id": source.source_id,
        "chunk_id": chunk.chunk_id,
        "corpus_loaded": corpus is not None,
        "provider_init_rows": init_rows,
        "provider_rows_after_execution": rows_executed,
        "status": direct["status"],
        "answer": direct["answer"],
        "answer_matches_statement": direct["answer"] == statement,
        "counters": direct["counters"],
        "direct_vs_provider_identical": parity_identical,
    }


def _write_fixture_corpus(
    directory: Path,
    corpus_module: Any,
    *,
    source_row: dict[str, Any],
    chunk_row: dict[str, Any],
    omit_file_checksums: bool = False,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    sources_path = directory / "sources.jsonl"
    chunks_path = directory / "chunks.jsonl"

    def _write(path: Path, rows: list[dict[str, Any]]) -> None:
        path.write_text(
            "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
            newline="\n",
        )

    _write(sources_path, [source_row])
    _write(chunks_path, [chunk_row])
    manifest: dict[str, Any] = {
        "corpus_version": RUNTIME_NATIVE_CORPUS_FORMAT,
        "snapshot_date": corpus_module.CORPUS_SNAPSHOT_DATE,
        "source_count": 1,
        "chunk_count": 1,
        "domains": sorted({tag for tag in source_row.get("topic_tags", [])}),
        "license_summary": {"project_owned_fixtures": 1, "notes": "doctor fixture"},
    }
    if not omit_file_checksums:
        manifest["file_checksums"] = {
            "sources.jsonl": corpus_module._sha256_lf(sources_path),
            "chunks.jsonl": corpus_module._sha256_lf(chunks_path),
        }
    manifest["manifest_checksum"] = sha256_json({key: value for key, value in manifest.items()})
    (directory / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def _valid_fixture_source(schema: Any, corpus_module: Any) -> dict[str, Any]:
    source = _doctor_probe_source(schema, corpus_module)
    row = dict(source.to_dict())
    row["content_text"] = source.content_text
    return row


def _valid_fixture_chunk(schema: Any, corpus_module: Any) -> dict[str, Any]:
    source = _doctor_probe_source(schema, corpus_module)
    chunk = schema.chunk_source_text(source, [("record", _DOCTOR_PROBE_STATEMENT)])[0]
    return chunk.to_dict()


def _runtime_regression_fixtures(
    workspace: Path, contract: Any, corpus_contract_binding: dict[str, Any], *, repo_root: Path
) -> dict[str, Any]:
    """Reproduce the exact R15 runtime-contract failure modes; each must fail
    closed in preconstruction (never load, never fill defaults)."""
    schema, corpus_module, _ = runtime_modules(repo_root)
    fixtures: dict[str, Any] = {}

    def _fixture(name: str, build) -> None:
        directory = workspace / name.replace(" ", "_")
        failure = None
        try:
            build(directory)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        fixtures[name] = {
            "status": "PASS" if failure else "FAIL",
            "failed_closed": bool(failure),
            "failure": failure,
        }

    def _load(directory: Path) -> None:
        corpus_module.load_corpus(directory)

    def _missing_source_field(directory: Path) -> None:
        row = _valid_fixture_source(schema, corpus_module)
        row.pop("source_title")
        chunk_row = _valid_fixture_chunk(schema, corpus_module)
        _write_fixture_corpus(directory, corpus_module, source_row=row, chunk_row=chunk_row)
        _load(directory)

    def _source_id_grammar_violation(directory: Path) -> None:
        row = _valid_fixture_source(schema, corpus_module)
        row["source_id"] = "r15-src-00001"
        chunk_row = _valid_fixture_chunk(schema, corpus_module)
        _write_fixture_corpus(directory, corpus_module, source_row=row, chunk_row=chunk_row)
        _load(directory)

    def _manifest_missing_file_checksums(directory: Path) -> None:
        source_row = _valid_fixture_source(schema, corpus_module)
        chunk_row = _valid_fixture_chunk(schema, corpus_module)
        _write_fixture_corpus(
            directory, corpus_module, source_row=source_row, chunk_row=chunk_row, omit_file_checksums=True
        )
        _load(directory)

    def _missing_authority_or_freshness(directory: Path) -> None:
        row = _valid_fixture_source(schema, corpus_module)
        row.pop("authority_class")
        chunk_row = _valid_fixture_chunk(schema, corpus_module)
        _write_fixture_corpus(directory, corpus_module, source_row=row, chunk_row=chunk_row)
        _load(directory)

    def _missing_section_or_span(directory: Path) -> None:
        source_row = _valid_fixture_source(schema, corpus_module)
        chunk_row = _valid_fixture_chunk(schema, corpus_module)
        chunk_row.pop("span")
        _write_fixture_corpus(directory, corpus_module, source_row=source_row, chunk_row=chunk_row)
        _load(directory)

    def _default_filling_missing_field(directory: Path) -> None:
        row = _valid_fixture_source(schema, corpus_module)
        row.pop("revision_or_version")
        chunk_row = _valid_fixture_chunk(schema, corpus_module)
        _write_fixture_corpus(directory, corpus_module, source_row=row, chunk_row=chunk_row)
        _load(directory)

    _fixture("runtime schema missing required source field", _missing_source_field)
    _fixture("runtime source id grammar violation", _source_id_grammar_violation)
    _fixture("runtime manifest missing file checksums", _manifest_missing_file_checksums)
    _fixture("runtime source missing authority or freshness metadata", _missing_authority_or_freshness)
    _fixture("runtime chunk missing section or span metadata", _missing_section_or_span)
    _fixture("runtime default-filling of missing required field", _default_filling_missing_field)
    fixtures["runtime contract not derived from frozen schema"] = {
        "status": "PASS" if corpus_contract_binding["module_hashes_match"] else "FAIL",
        "failed_closed": not corpus_contract_binding["module_hashes_match"],
        "failure": None if corpus_contract_binding["module_hashes_match"] else corpus_contract_binding["mismatch"],
    }
    return fixtures


def _runtime_corpus_contract_binding(root: Path, contract: Any) -> dict[str, Any]:
    """Re-derive the frozen-module binding from the committed runtime contract."""
    out = root / "evaluations" / contract.experiment
    corpus_contract = read_json(root / contract.get("artifacts.runtime_corpus_contract"))
    bound = corpus_contract.get("bound_modules") or {}
    mismatches = []
    for relative, expected in sorted(bound.items()):
        path = root / relative
        if not path.is_file() or sha256_file(path) != expected:
            mismatches.append(relative)
    if not bound:
        mismatches.append("bound_modules empty")
    return {
        "module_hashes_match": not mismatches,
        "mismatch": f"frozen module binding mismatch: {sorted(mismatches)}" if mismatches else None,
        "bound_modules": sorted(bound),
    }


def _runtime_contract_compatibility(root: Path, contract: Any) -> dict[str, Any]:
    """Mandatory doctor section: the frozen candidate runtime and the authored
    material share one corpus contract (T21R16)."""
    out = root / "evaluations" / contract.experiment
    runtime_native = contract.get("runtime_native")
    binding = _runtime_corpus_contract_binding(root, contract)
    with tempfile.TemporaryDirectory(prefix=f"{contract.experiment}-runtime-contract-") as directory:
        workspace = Path(directory)
        probe = _runtime_probe_execution(workspace, root)
        fixtures = _runtime_regression_fixtures(workspace, contract, binding, repo_root=root)
    shadow_path = out / "runtime_native_shadow_validation.json"
    parity_path = out / "provider_parity_report.json"
    shadow = read_json(shadow_path) if shadow_path.is_file() else {"status": "MISSING"}
    parity = read_json(parity_path) if parity_path.is_file() else {"status": "MISSING"}
    fixture_failures = sorted(name for name, fixture in fixtures.items() if fixture["status"] != "PASS")
    probe_pass = (
        probe["corpus_loaded"]
        and probe["provider_init_rows"] == 0
        and probe["provider_rows_after_execution"] == 1
        and probe["status"] == "ANSWER"
        and probe["answer_matches_statement"]
        and probe["direct_vs_provider_identical"]
        and all(value == 0 for value in probe["counters"].values())
    )
    documents_pass = shadow.get("status") == "PASS" and parity.get("status") == "PASS"
    loader_entry_ok = runtime_native.get("loader_entry") == "src/sciencemath/knowledge/corpus.py:load_corpus"
    corpus_format_ok = runtime_native.get("corpus_format") == RUNTIME_NATIVE_CORPUS_FORMAT
    passed = fixture_failures == [] and probe_pass and documents_pass and loader_entry_ok and corpus_format_ok
    return {
        "schema_version": "t21-runtime-contract-compatibility-v1",
        "artifact": f"{contract.experiment.upper()}_RUNTIME_CONTRACT_COMPATIBILITY",
        "status": "PASS" if passed else "FAIL",
        "audit_mode": "EXECUTED",
        "corpus_format": runtime_native.get("corpus_format"),
        "loader_entry": runtime_native.get("loader_entry"),
        "frozen_module_binding": binding,
        "probe": {
            "source_id": probe["source_id"],
            "chunk_id": probe["chunk_id"],
            "provider_init_rows": probe["provider_init_rows"],
            "provider_rows_after_execution": probe["provider_rows_after_execution"],
            "status": probe["status"],
            "answer_matches_statement": probe["answer_matches_statement"],
            "direct_vs_provider_identical": probe["direct_vs_provider_identical"],
            "counters": probe["counters"],
        },
        "regression_fixtures": fixtures,
        "fixture_failures": fixture_failures,
        "committed_shadow_validation": shadow.get("status"),
        "committed_provider_parity": parity.get("status"),
    }


def _r15_disposition_check(root: Path) -> dict[str, Any]:
    closure = read_json(root / "evaluations" / "t21r15" / "T21R15_CLOSURE.json")
    status_ok = closure.get("status") == "CLOSED / SEALED_HOLDOUT_RUNTIME_CONTRACT_INCOMPATIBILITY"
    reason_ok = closure.get("reason") == "SEALED_CORPUS_NOT_LOADABLE_BY_FROZEN_CANDIDATE_RUNTIME"
    capability_ok = closure.get("capability_failure") is False
    # The durable refusal record lives in the closure's evaluation_refusal
    # block and its marker artifact (evaluations/t21r15/evaluation_refusal.json),
    # which t21_protocol.evaluate._refuse_if_permanent enforces fail-closed.
    refusal = closure.get("evaluation_refusal") or {}
    refusal_ok = (
        refusal.get("designated") is True
        and refusal.get("designation") == "T21R15_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED"
    )
    refusal_marker = root / "evaluations" / "t21r15" / "evaluation_refusal.json"
    marker_ok = refusal_marker.is_file() and read_json(refusal_marker).get("permanent") is True
    return {
        "status": "PASS" if status_ok and reason_ok and capability_ok and refusal_ok and marker_ok else "FAIL",
        "closed_status": closure.get("status"),
        "capability_failure": closure.get("capability_failure"),
        "evaluation_refusal": refusal.get("designation"),
        "evaluation_refusal_marker_permanent": marker_ok,
    }


def _r16_disposition_check(root: Path) -> dict[str, Any]:
    """T21R17 preconstruction requires the R16 disposition committed verbatim:
    closed as a measurement-specification failure, capability verdict NONE,
    holdout consumed, evaluation permanently refused, both invalid metrics
    designated semantically invalid for capability adjudication."""
    closure = read_json(root / "evaluations" / "t21r16" / "T21R16_CLOSURE.json")
    status_ok = closure.get("status") == "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE"
    reason_ok = (
        closure.get("reason")
        == "OFFICIAL_RUN_COMPLETED_BUT_TWO_FROZEN_FLOOR_METRICS_DID_NOT_SEMANTICALLY_MEASURE_THEIR_REGISTERED_QUANTITIES"
    )
    capability_ok = closure.get("capability_verdict") == "NONE" and closure.get("capability_failure") is False
    invalid_metrics = set(closure.get("invalid_metrics") or [])
    invalid_ok = invalid_metrics == {
        "conflict_false_resolution",
        "static_query_unnecessary_web_routing",
    } and closure.get("invalid_metric_designation") == "SEMANTICALLY_INVALID_FOR_CAPABILITY_ADJUDICATION"
    holdout_ok = closure.get("holdout_status") == "PERMANENTLY_EXPOSED_CONSUMED"
    rows_ok = closure.get("rows_scored") == 4800 and closure.get("one_shot_consumed") is True
    refusal_marker = root / "evaluations" / "t21r16" / "evaluation_refusal.json"
    marker_ok = refusal_marker.is_file() and read_json(refusal_marker).get("permanent") is True
    passed = status_ok and reason_ok and capability_ok and invalid_ok and holdout_ok and rows_ok and marker_ok
    return {
        "status": "PASS" if passed else "FAIL",
        "closed_status": closure.get("status"),
        "capability_verdict": closure.get("capability_verdict"),
        "holdout_status": closure.get("holdout_status"),
        "invalid_metrics": sorted(invalid_metrics),
        "evaluation_refusal_marker_permanent": marker_ok,
    }


def _metric_semantics_validation(root: Path, contract: Any) -> dict[str, Any]:
    """Mandatory doctor section (T21R17): every official floor metric carries
    explicit frozen measurement semantics; the scorer has no generic fallback
    path; the discriminative fixture battery proves each metric measures its
    own registered quantity."""
    from .metric_semantics import (
        SEMANTICS_ARTIFACT,
        SEMANTICS_EXPERIMENT,
        load_metric_semantics,
        semantics_root,
    )
    from .scorer_r17 import IMPLEMENTATION_SOURCES, IMPLEMENTATIONS

    floors = contract.get("promotion_floors")
    floor_metrics = {metric for group in floors.values() for metric in group}
    identity = {
        "t22": ("T22_OFFICIAL_METRIC_SEMANTICS", "t22"),
    }.get(contract.experiment, (SEMANTICS_ARTIFACT, SEMANTICS_EXPERIMENT))
    semantics = load_metric_semantics(root, contract, artifact=identity[0], experiment=identity[1])
    entries = semantics["metrics"]
    registered = set(entries)
    contradictions = sorted(
        metric
        for metric, entry in entries.items()
        if entry["direction"] != {"=": "EXACT", "<=": "LOWER_IS_BETTER", ">=": "HIGHER_IS_BETTER"}[entry["operator"]]
    )
    missing_policies = sorted(
        metric
        for metric, entry in entries.items()
        if not entry["numerator"] or not entry["denominator"] or not entry["zero_denominator_policy"]
    )
    unknown_paths = sorted(
        metric for metric in floor_metrics if metric not in IMPLEMENTATIONS or metric not in IMPLEMENTATION_SOURCES
    )
    fixture_doc = read_json(root / "evaluations" / contract.experiment / "metric_semantics_fixtures.json")
    fixture_sections = {
        name: fixture_doc.get(name, {}).get("status")
        for name in (
            "truth_tables",
            "monotonicity",
            "complement_confusion",
            "operator_negative_controls",
            "all_good",
            "targeted_bad",
            "metric_independence",
            "r16_regression",
            "legacy_evaluator_parity",
            "unknown_metric_fail_closed",
        )
    }
    all_good = fixture_doc.get("all_good") or {}
    targeted_bad = fixture_doc.get("targeted_bad") or {}
    monotonicity = fixture_doc.get("monotonicity") or {}
    checks = {
        "registered_floors_with_semantics": len(floor_metrics & registered),
        "explicit_metric_implementations": len(IMPLEMENTATIONS),
        "semantics_entries": len(entries),
        "generic_fallback_consumers": 0 if "no generic fallback" in semantics["rule"] else 1,
        "direction_operator_contradictions": len(contradictions),
        "missing_numerator_denominator_policies": len(missing_policies),
        "unknown_scorer_paths": len(unknown_paths),
        "all_good_floors_passed": all_good.get("floors_passed"),
        "targeted_bad_cases": targeted_bad.get("cases"),
        "targeted_bad_single_failure": targeted_bad.get("single_failure"),
        "monotonicity_violations": monotonicity.get("violations"),
    }
    fixture_pass = all(status == "PASS" for status in fixture_sections.values())
    numbers_pass = (
        len(floor_metrics & registered) == 32
        and len(IMPLEMENTATIONS) == 32
        and len(entries) == 32
        and not contradictions
        and not missing_policies
        and not unknown_paths
        and all_good.get("floors_passed") == 32
        and targeted_bad.get("cases") == 32
        and targeted_bad.get("single_failure") == 32
        and monotonicity.get("violations") == 0
    )
    return {
        "schema_version": "t21-metric-semantics-validation-v1",
        "artifact": f"{contract.experiment.upper()}_METRIC_SEMANTICS_VALIDATION",
        "status": "PASS" if fixture_pass and numbers_pass else "FAIL",
        "audit_mode": "EXECUTED",
        "semantics_root": semantics_root(semantics),
        "rule": semantics["rule"],
        "fixture_sections": fixture_sections,
        "checks": checks,
    }


def _r17_disposition_check(root: Path) -> dict[str, Any]:
    """T22 preconstruction requires the R17 disposition committed in the T22
    artifact namespace (R17 itself is permanently closed and must not gain
    new files): closed as a valid capability failure, capability verdict
    FAIL, holdout consumed, the two temporal failures recorded as valid
    measurements, rerun refused, and the permanent refusal marker present."""
    disposition = read_json(root / "evaluations" / "t22" / "r17_final_disposition.json")
    status_ok = disposition.get("status") == "CLOSED / VALID_CAPABILITY_FAILURE"
    reason_ok = (
        disposition.get("reason")
        == "TWO_TEMPORAL_FLOOR_METRICS_MEASURED_A_CANDIDATE_FAILURE_WITHOUT_CANDIDATE_VISIBLE_SIGNALS"
    )
    capability_ok = disposition.get("capability_verdict") == "FAIL" and disposition.get("capability_failure") is True
    rows_ok = disposition.get("rows_scored") == 4800 and disposition.get("one_shot_consumed") is True
    holdout_ok = disposition.get("holdout_status") == "PERMANENTLY_EXPOSED_CONSUMED"
    failed_ok = set(disposition.get("failed_metrics") or []) == {
        "explicit_current_routing_accuracy",
        "stale_snapshot_false_current_answers",
    } and disposition.get("failed_metric_designation") == "VALID_MEASUREMENTS_OF_CANDIDATE_CAPABILITY_FAILURE"
    adjudication_ok = disposition.get("final_adjudication") == "T21R17_FINAL_ADJUDICATION_VALID_CAPABILITY_FAILURE"
    rerun_ok = disposition.get("rerun") == "REFUSED"
    marker = root / "evaluations" / "t22" / "r17_evaluation_refusal.json"
    marker_ok = marker.is_file() and read_json(marker).get("permanent") is True
    passed = status_ok and reason_ok and capability_ok and rows_ok and holdout_ok and failed_ok and adjudication_ok and rerun_ok and marker_ok
    return {
        "status": "PASS" if passed else "FAIL",
        "closed_status": disposition.get("status"),
        "capability_verdict": disposition.get("capability_verdict"),
        "failed_metrics": sorted(disposition.get("failed_metrics") or []),
        "final_adjudication": disposition.get("final_adjudication"),
        "evaluation_refusal_marker_permanent": marker_ok,
    }


def _temporal_signal_visibility_check(root: Path, contract: Any) -> dict[str, Any]:
    """T22 section-41 check (protocol sections 32-34): the frozen temporal
    design exposes every temporal requirement through at least one
    candidate-visible signal carrier; the executed preconstruction audit
    proved gold-only-signal rows = 0; no gold-only field is ever exposed to
    the candidate; the candidate provider reads only query + request_date."""
    out = root / "evaluations" / contract.experiment
    design = read_json(root / contract.get("artifacts.temporal_holdout_design"))
    shadow = read_json(out / "runtime_native_shadow_validation.json")
    carriers = shadow.get("signal_carrier_audit") or {}
    temporal_rows = carriers.get("temporal_rows")
    rows_with_signal = carriers.get("rows_with_signal")
    gold_only = carriers.get("gold_only_signal_rows")
    request_date = (design.get("request_date") or {}).get("value")
    snapshot_date = (design.get("request_date") or {}).get("snapshot_date")
    request_ok = (
        isinstance(request_date, str)
        and isinstance(snapshot_date, str)
        and request_date > snapshot_date
        and carriers.get("request_date") == request_date
    )
    blindness_ok = set(
        (design.get("blindness") or {}).get("never_candidate_visible") or []
    ) == {"construction_tag", "signal_class", "expected_route", "expected_status", "gold expected_answer"}
    provider_source = (root / "t21_protocol" / "providers_t22.py").read_text(encoding="utf-8")
    # The provider must read only the candidate-visible row inputs (the
    # case id, the query text and the request-date carrier); every
    # gold-only field must be absent as a row-indexing pattern (a docstring
    # mention is documentation, an indexed read is an access).
    forbidden_accessors = tuple(
        f"row[\"{field}\"" if bracket else f"row.get(\"{field}\""
        for field in ("construction_tag", "signal_class", "expected_route", "expected_status")
        for bracket in (True, False)
    )
    provider_ok = (
        "row[\"query\"]" in provider_source
        and "row.get(\"request_date\"" in provider_source
        and not any(accessor in provider_source for accessor in forbidden_accessors)
        and "row[\"gold\"]" not in provider_source
    )
    passed = (
        shadow.get("status") == "PASS"
        and shadow.get("audit_mode") == "EXECUTED"
        and temporal_rows == 250
        and rows_with_signal == 250
        and gold_only == 0
        and request_ok
        and blindness_ok
        and provider_ok
    )
    return {
        "schema_version": "t22-temporal-signal-visibility-validation-v1",
        "artifact": "T22_TEMPORAL_SIGNAL_VISIBILITY_VALIDATION",
        "status": "PASS" if passed else "FAIL",
        "audit_mode": "EXECUTED",
        "temporal_rows": temporal_rows,
        "rows_with_signal": rows_with_signal,
        "gold_only_signal_rows": gold_only,
        "request_date": request_date,
        "snapshot_date": snapshot_date,
        "carriers": carriers.get("per_signal_counts"),
        "blindness_contract_enforced": blindness_ok,
        "candidate_provider_visibility_clean": provider_ok,
    }


def _temporal_router_qualification_check(root: Path, contract: Any) -> dict[str, Any]:
    """T22 section-41 check (protocol section 38): the frozen temporal
    regression battery — run on non-blind, project-owned fixture material
    with the actual remediated candidate — meets all four qualification
    gates: explicit-current routing accuracy = 1.0, stale-snapshot false
    current answers = 0, static unnecessary web routing <= 0.03, historical
    as-of handling >= 0.98."""
    from t21_protocol.util import sha256_file as _sha256_file

    results = read_json(root / "evaluations" / "t22" / "temporal_regressions" / "results.json")
    gates = results.get("gates") or {}
    spec_path = root / "evaluations" / "t22" / "temporal_regressions" / "battery_spec.json"
    spec_ok = spec_path.is_file() and results.get("spec_sha256") == _sha256_file(spec_path)
    expected = {
        "explicit_current_routing_accuracy": {"observed": 1.0, "operator": "="},
        "stale_snapshot_false_current_answers": {"observed": 0, "operator": "="},
        "static_query_unnecessary_web_routing": {"observed": 0.0, "operator": "<="},
        "historical_as_of_handling": {"observed": 1.0, "operator": ">="},
    }
    observed_ok = all(
        gate in gates
        and gates[gate].get("observed") == spec["observed"]
        and gates[gate].get("operator") == spec["operator"]
        and gates[gate].get("pass") is True
        for gate, spec in expected.items()
    )
    blindness = results.get("blindness") or {}
    blindness_ok = blindness.get("forbidden_gold_only_keys_present") == [] and blindness.get(
        "candidate_runtime_inputs"
    ) == ["query", "now (request_date)"]
    passed = results.get("battery_pass") is True and spec_ok and observed_ok and blindness_ok
    return {
        "schema_version": "t22-temporal-router-qualification-validation-v1",
        "artifact": "T22_TEMPORAL_ROUTER_QUALIFICATION_VALIDATION",
        "status": "PASS" if passed else "FAIL",
        "audit_mode": "EXECUTED",
        "battery_pass": results.get("battery_pass"),
        "gates": {name: {"observed": gate.get("observed"), "pass": gate.get("pass")} for name, gate in gates.items()},
        "spec_sha256_pinned": spec_ok,
        "blindness_audit_clean": blindness_ok,
    }


def _zero_denominator_harmonization_check(root: Path, contract: Any) -> dict[str, Any]:
    """T22 section-31 closure: the contradictory zero-denominator prose is
    harmonized against the frozen resolution; numeric semantics stay
    byte-identical to R17; the emergent-empty convention and the
    design-mandated fail-closed refusal are both proven by fixtures."""
    fixtures = read_json(root / "evaluations" / contract.experiment / "metric_semantics_fixtures.json")
    resolution = read_json(root / contract.get("artifacts.zero_denominator_policy_resolution"))
    r17_semantics = read_json(root / "evaluations" / "t21r17" / "official_metric_semantics.json")
    t22_semantics = read_json(root / contract.get("artifacts.official_metric_semantics"))
    r17_policies = {
        metric: entry.get("zero_denominator_policy")
        for metric, entry in (r17_semantics.get("metrics") or {}).items()
    }
    t22_policies = {
        metric: entry.get("zero_denominator_policy")
        for metric, entry in (t22_semantics.get("metrics") or {}).items()
    }
    policies_identical = r17_policies == t22_policies and len(t22_policies) == 32
    section = fixtures.get("zero_denominator_harmonization") or {}
    cases = section.get("cases") or []
    emergent_ok = sum(1 for case in cases if case.get("case", "").startswith("emergent_empty") and case.get("ok") is True)
    refused_ok = sum(1 for case in cases if case.get("case", "").startswith("design_mandated_empty") and case.get("refused") is True and case.get("ok") is True)
    harmonized = (
        fixtures.get("status") == "PASS"
        and section.get("status") == "PASS"
        and section.get("ok") is True
        and emergent_ok == 2
        and refused_ok == 3
        and section.get("policy_classes_byte_identical_to_r17") is True
        and section.get("no_retroactive_effect_on_r17") is True
        and section.get("prose_harmonized") is True
    )
    frozen_policy = (resolution.get("frozen_policy") or {}).get("name")
    policy_ok = (
        resolution.get("status") == "FROZEN_PRECONSTRUCTION"
        and frozen_policy == "DESIGN_MANDATED_POSITIVE_POPULATIONS_WITH_RESIDUAL_EMERGENT_CONVENTION"
        and (resolution.get("protocol_debt") or {}).get("resolution_authorization").startswith(
            "T22 preconstruction plan section 31"
        )
    )
    return {
        "schema_version": "t22-zero-denominator-harmonization-validation-v1",
        "artifact": "T22_ZERO_DENOMINATOR_HARMONIZATION_VALIDATION",
        "status": "PASS" if policies_identical and harmonized and policy_ok else "FAIL",
        "audit_mode": "EXECUTED",
        "policy_classes_identical_to_r17": policies_identical,
        "fixture_section": section.get("status"),
        "emergent_empty_cases": emergent_ok,
        "design_mandated_fail_closed_cases": refused_ok,
        "frozen_policy": frozen_policy,
        "resolution_status": resolution.get("status"),
    }


def run_doctor(root: Path, experiment: str = "t21r15") -> dict[str, Any]:
    before = tracked_tree(root)
    out = root / "evaluations" / experiment
    contract = load_contract(out / "t21_master_contract.json")
    runtime_native = contract_runtime_native(contract) is not None
    experiment_tag = experiment.upper()
    graph = load_artifact_graph(out / "artifact_graph.json")
    taxonomy = load_taxonomy(out / "domain_taxonomy_contract.json")
    canonical = canonical_labels(taxonomy)
    author_labels = set(contract.get("author.vocabulary"))
    taxonomy_report = coverage_report(
        taxonomy,
        {
            "author": author_labels,
            "suite_builder": canonical,
            "gold_validator": canonical,
            "evaluator": canonical,
            "scorer": canonical,
            "domain_macro_aggregator": canonical,
        },
    )
    adjudication = read_json(out / "test_failure_adjudication.json")
    applicability = generate_applicability(adjudication)
    committed_applicability = read_json(out / "current_test_applicability.json")
    checks: dict[str, Any] = {
        "master_contract": validate_master_contract(contract.document, raise_on_error=False),
        "artifact_graph": validate_artifact_graph(graph, raise_on_error=False),
        "state_machine": ProtocolStateMachine.from_contract(contract).validate(),
        "ledgers": _ledger_integration(),
        "holdout_frozen_schema": _marker_schema_check(root / contract.get("artifacts.holdout_frozen_schema")),
        "taxonomy": taxonomy_report,
        "historical_exclusion": validate_historical_policy(read_json(out / "historical_exclusion.json"), root),
        "remediation_exclusion": validate_remediation_policy(read_json(out / "remediation_exclusion.json")),
        "runtime_freeze": verify_freeze(root, out / "runtime_freeze.json", artifact=f"{experiment_tag}_RUNTIME_FREEZE"),
        "evaluator_freeze": verify_freeze(root, out / "evaluator_freeze.json", artifact=f"{experiment_tag}_EVALUATOR_FREEZE"),
        "qualification_lock": validate_qualification_lock(root, contract, read_json(out / "qualification_lock.json")),
        "adjudication": validate_adjudication(adjudication),
        "applicability": {
            "status": "PASS" if committed_applicability.get("deselect_nodeids") == applicability["deselect_nodeids"] else "FAIL",
            "registered_failures": applicability["registered_failures"],
        },
        "negative_controls": _negative_control_registry(out / "negative_controls.json", runtime_native=runtime_native),
        "real_paths": _real_paths(root, contract),
        "production_phase_apis": _phase_api_check(experiment),
        "provider_separation": _provider_separation(experiment),
    }
    if experiment == "t21r17":
        checks["r16_disposition"] = _r16_disposition_check(root)
        checks["metric_semantics_validation"] = _metric_semantics_validation(root, contract)
    elif experiment == "t22":
        checks["r16_disposition"] = _r16_disposition_check(root)
        checks["r17_disposition"] = _r17_disposition_check(root)
        checks["metric_semantics_validation"] = _metric_semantics_validation(root, contract)
        # T22 section-41 checks: temporal signal visibility (sections 32-34),
        # router qualification on non-blind material (section 38), and the
        # frozen zero-denominator harmonization (section 31).
        checks["temporal_signal_visibility"] = _temporal_signal_visibility_check(root, contract)
        checks["temporal_router_qualification"] = _temporal_router_qualification_check(root, contract)
        checks["zero_denominator_harmonization"] = _zero_denominator_harmonization_check(root, contract)
    else:
        checks["r15_disposition"] = _r15_disposition_check(root)
    if runtime_native:
        checks["runtime_contract_compatibility"] = _runtime_contract_compatibility(root, contract)
    module_paths = sorted((root / "t21_protocol").glob("*.py"))
    helper_names = EXPERIMENT_HELPERS.get(experiment, EXPERIMENT_HELPERS["t21r15"])
    helper_paths = [root / "scripts" / f"{name}.py" for name in helper_names]
    test_globs = ("test_t21*.py",) if experiment != "t22" else ("test_t21*.py", "test_t22*.py")
    test_paths = sorted(path for pattern in test_globs for path in (root / "tests").glob(pattern))
    checks["static_import_audit"] = static_import_write_audit([*module_paths, *helper_paths, *test_paths])
    checks["dynamic_import_audit"] = dynamic_import_write_audit(
        root,
        [f"t21_protocol.{path.stem}" for path in module_paths if path.stem not in {"__init__", "doctor"}]
        + list(helper_names),
    )
    construction_rehearsal = run_synthetic_construction_twice(root, contract, graph)
    checks["synthetic_construction_only"] = construction_rehearsal
    checks["phase_separation"] = _phase_separation(root, graph, construction_rehearsal)
    checks["real_mode_dry_rehearsal"] = run_real_mode_dry_rehearsal(root, contract, graph)
    if experiment == "t21r17":
        # Metric-semantics experiments replace the synthetic full-protocol
        # rehearsal (whose evaluation driver is R15/R16-scoped) with the full
        # production lifecycle ×2 on disposable material: real frozen runtime,
        # v2 evidence candidate provider, explicit per-metric scorer, no stub
        # candidate anywhere in the E2E.
        from .pipeline_r17 import run_real_mode_lifecycle_rehearsal_r17_twice

        checks["metric_semantics_lifecycle_rehearsal"] = run_real_mode_lifecycle_rehearsal_r17_twice(root, contract, graph)
    elif experiment == "t22":
        # T22 runs the same full production lifecycle ×2 with the T22
        # request-date candidate provider and the T22 evaluation driver
        # (protocol section 40: the actual remediated candidate, no stub).
        from .pipeline_t22 import run_real_mode_lifecycle_rehearsal_t22_twice

        checks["metric_semantics_lifecycle_rehearsal"] = run_real_mode_lifecycle_rehearsal_t22_twice(root, contract, graph)
    else:
        checks["synthetic_full_protocol"] = run_synthetic_twice(root, contract, graph)
    cleanliness_path = out / "test_cleanliness.json"
    checks["test_cleanliness"] = read_json(cleanliness_path) if cleanliness_path.is_file() else {"status": "FAIL", "reason": "missing test cleanliness evidence"}
    r14 = read_json(root / "evaluations" / "t21r14" / "T21R14_CLOSURE.json")
    checks["r14_disposition"] = {
        "status": "PASS" if r14.get("status") == "CLOSED / PRECONSTRUCTION_PROTOCOL_INTEGRATION_FAILURE" and r14.get("construction_attempts") == 0 and r14.get("one_shot_consumed") is False else "FAIL"
    }
    after = tracked_tree(root)
    drift = diff_snapshots(before, after)
    checks["doctor_cleanliness"] = {
        "status": "PASS" if not any(drift.values()) else "FAIL",
        "tracked_tree_before": sha256_json(before),
        "tracked_tree_after": sha256_json(after),
        "tracked_drift": sum(len(value) for value in drift.values()),
    }
    passed = all(check.get("status") in {"PASS", "VERIFIED"} for check in checks.values())
    return {
        "schema_version": "t21-protocol-doctor-report-v1",
        "artifact": "T21_PROTOCOL_DOCTOR_REPORT",
        "experiment": experiment,
        "checks": checks,
        "status": "PASS" if passed else "FAIL",
        "verdict": VERDICT_PASS if passed else VERDICT_FAIL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="t21r15")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--write-report", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = run_doctor(arguments.root.resolve(), arguments.experiment)
    except Exception as exc:
        report = {
            "schema_version": "t21-protocol-doctor-report-v1",
            "artifact": "T21_PROTOCOL_DOCTOR_REPORT",
            "experiment": arguments.experiment,
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "verdict": VERDICT_FAIL,
        }
    if arguments.write_report:
        write_json(arguments.root / "evaluations" / arguments.experiment / "protocol_doctor_report.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "verdict"}, indent=2, sort_keys=True))
    print(report["verdict"])
    return 0 if report["verdict"] == VERDICT_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
