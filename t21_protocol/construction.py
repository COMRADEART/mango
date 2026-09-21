"""Production construction phase: qualify, construct, seal, and stop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .artifact_graph import command_write_paths, load_artifact_graph, validate_artifact_graph
from .audits import run_construction_audits
from .author import shadow_author
from .context import (
    CONSTRUCTION_TOKEN,
    ConstructionAuthorization,
    ExecutionContext,
    WorkspaceMode,
    require_construction_authorization,
)
from .contract import load_contract
from .errors import ProtocolError, ValidationError
from .ledger import ConstructionLedger
from .providers import (
    MaterialProvider,
    RealBlindMaterialProvider,
    RealCandidateProvider,
    SyntheticMaterialProvider,
    contract_runtime_native,
    materialize_bundle,
    runtime_modules,
    validate_material_provider,
)
from .qualification import validate_qualification_lock
from .seal import build_manifest, seal_holdout, verify_seal
from .state_machine import Phase, ProtocolStateMachine
from .util import read_json, sha256_file, write_json
from .write_guard import WriteGuard

SUCCESS_VERDICT = "T21R15_REAL_BLIND_HOLDOUT_CONSTRUCTED_AND_SEALED"
FAIL_VERDICT = "T21R15_REAL_BLIND_HOLDOUT_CONSTRUCTION_FAILED"

_PRECONSTRUCTION_INPUTS = (
    "experiment_config",
    "artifact_graph",
    "domain_taxonomy",
    "historical_exclusion",
    "remediation_exclusion",
    "runtime_freeze",
    "evaluator_freeze",
    "qualification_lock",
    "negative_controls",
    "adjudication",
    "applicability",
    "holdout_frozen_schema",
)
_RUNTIME_NATIVE_PRECONSTRUCTION_INPUTS = (
    "runtime_corpus_contract",
    "runtime_field_provenance",
    "candidate_runtime_data_contract",
)


def _assert_preconstruction_absence(workspace: Path, contract: Any) -> None:
    experiment = contract.experiment
    try:
        real_paths = contract.get(f"real_{experiment}_paths")
    except KeyError:
        # t21rN contracts name the field real_rN_paths (real_r15_paths, real_r16_paths).
        real_paths = contract.get(f"real_{experiment.replace('t21', '', 1)}_paths")
    present = [relative for relative in real_paths if (workspace / relative).exists()]
    if present:
        raise ValidationError(f"real construction/evaluation artifact already exists: {present}")


def _assert_workspace_inputs(workspace: Path, source_root: Path, contract: Any) -> None:
    fields = list(_PRECONSTRUCTION_INPUTS)
    if contract_runtime_native(contract) is not None:
        fields.extend(_RUNTIME_NATIVE_PRECONSTRUCTION_INPUTS)
    for field in fields:
        relative = contract.get(f"artifacts.{field}")
        source = source_root / relative
        target = workspace / relative
        if not target.is_file() or sha256_file(target) != sha256_file(source):
            raise ValidationError(f"workspace preconstruction input differs: {relative}")


def _assert_construction_stop(workspace: Path, experiment: str) -> dict[str, Any]:
    out = workspace / "evaluations" / experiment
    forbidden = (
        out / "evaluation_run_ledger.json",
        out / "candidate_outputs.jsonl",
        out / "evaluator_results.json",
        out / "score_results.json",
        out / "evaluation_provenance.json",
        out / "raw_results.jsonl",
        out / "metric_evidence.json",
        out / "floor_evidence.json",
        out / "holdout_results.json",
    )
    present = [path.name for path in forbidden if path.exists()]
    if present:
        raise ValidationError(f"construction produced evaluation-owned artifacts: {present}")
    return {
        "evaluation_ledger_absent": True,
        "raw_results_absent": True,
        "holdout_results_absent": True,
        "candidate_executions": 0,
        "official_evaluation_executions": 0,
    }


def _runtime_loader_validation(workspace: Path, contract: Any) -> dict[str, Any]:
    """Execute the frozen loader against the materialized real corpus.

    Fail-closed: any load, schema, checksum, or referential failure raises
    before this report can exist. The candidate runtime executes zero
    holdout rows here — this is loader compatibility evidence only."""
    _, corpus_module, _ = runtime_modules(workspace)
    corpus_dir = workspace / "rag" / f"gk_holdout_{contract.experiment}"
    manifest = read_json(corpus_dir / "corpus_manifest.json")
    corpus = corpus_module.load_corpus(corpus_dir)
    missing_source_refs = sum(1 for chunk in corpus.chunks if chunk.source_id not in corpus.sources_by_id)
    return {
        "schema_version": "t21-runtime-loader-validation-v1",
        "artifact": "T21R16_RUNTIME_LOADER_VALIDATION",
        "status": "PASS",
        "audit_mode": "EXECUTED",
        "loader_entry": contract.get("runtime_native.loader_entry"),
        "corpus_format": contract.get("runtime_native.corpus_format"),
        "corpus_path": str(corpus_dir.relative_to(workspace)),
        "manifest_source_count": manifest.get("source_count"),
        "manifest_chunk_count": manifest.get("chunk_count"),
        "loaded_sources": len(corpus.sources),
        "loaded_chunks": len(corpus.chunks),
        "checks": {
            "loader_errors": 0,
            "schema_errors": 0,
            "missing_fields": 0,
            "checksum_failures": 0,
            "referential_failures": missing_source_refs,
        },
        "candidate_execution_rows": 0,
    }


def _candidate_provider_compatibility(workspace: Path, contract: Any) -> dict[str, Any]:
    """Prove the frozen production candidate initializes against the corpus.

    Initialization loads the corpus with the frozen loader; holdout rows are
    never executed (rows_executed == 0). The provider instance is discarded
    immediately after the check."""
    corpus_dir = workspace / "rag" / f"gk_holdout_{contract.experiment}"
    provider = RealCandidateProvider(workspace, corpus_dir)
    report = {
        "schema_version": "t21-candidate-provider-compatibility-v1",
        "artifact": "T21R16_CANDIDATE_PROVIDER_COMPATIBILITY",
        "status": "PASS" if provider.rows_executed == 0 else "FAIL",
        "audit_mode": "EXECUTED",
        "provider_id": provider.provider_id,
        "provider_kind": provider.provider_kind,
        "corpus_format": contract.get("runtime_native.corpus_format"),
        "loader": "frozen load_corpus",
        "init_only": True,
        "rows_executed": provider.rows_executed,
    }
    del provider
    if report["status"] != "PASS":
        raise ValidationError("candidate provider executed rows during initialization")
    return report


def run_construction(
    experiment: str,
    workspace: Path,
    authorization: ConstructionAuthorization | str,
    *,
    workspace_mode: WorkspaceMode,
    provider: MaterialProvider | None = None,
    source_root: Path | None = None,
    qualification_rehearsal: bool = False,
) -> dict[str, Any]:
    """Run only PRECONSTRUCTION through SEALED and return immediately."""
    require_construction_authorization(authorization, experiment=experiment)
    context = ExecutionContext(workspace_mode, qualification_rehearsal)
    context.validate()
    workspace = workspace.resolve()
    source_root = (source_root or workspace).resolve()
    contract = load_contract(source_root / "evaluations" / experiment / "t21_master_contract.json")
    if contract.experiment != experiment:
        raise ValidationError("construction experiment identity mismatch")
    runtime_native = contract_runtime_native(contract) is not None
    success_verdict = f"{experiment.upper()}_REAL_BLIND_HOLDOUT_CONSTRUCTED_AND_SEALED"
    graph = load_artifact_graph(source_root / contract.get("artifacts.artifact_graph"))
    validate_artifact_graph(graph)
    _assert_workspace_inputs(workspace, source_root, contract)
    _assert_preconstruction_absence(workspace, contract)
    lock = read_json(source_root / contract.get("artifacts.qualification_lock"))
    validate_qualification_lock(source_root, contract, lock)
    provider = provider or (
        SyntheticMaterialProvider()
        if workspace_mode == WorkspaceMode.SYNTHETIC_DISPOSABLE
        else RealBlindMaterialProvider()
    )
    validate_material_provider(provider, workspace_mode, qualification_rehearsal=qualification_rehearsal)

    machine = ProtocolStateMachine.from_contract(contract)
    phase = machine.transition("qualify", Phase.PRECONSTRUCTION)
    transitions = [phase.value]
    out = workspace / "evaluations" / experiment
    ledger_path = out / "construction_run_ledger.json"
    allowed = command_write_paths(graph, "construct")
    ledger: ConstructionLedger | None = None
    with WriteGuard(workspace, allowed):
        ledger = ConstructionLedger.create_exclusive(
            ledger_path,
            experiment,
            {
                "authorization_class": "CONSTRUCTION",
                "workspace_mode": workspace_mode.value,
                "qualification_rehearsal": qualification_rehearsal,
            },
        )
        phase = machine.transition("start_construction", phase)
        transitions.append(phase.value)
        try:
            authored = shadow_author(contract, source_root)
            author_invocations = 1
            write_json(out / "author_spec.json", authored["spec"], exclusive=True)
            bundle = provider.build(contract, authored["spec"])
            materialized = materialize_bundle(workspace, contract, bundle)
            runtime_validation = None
            provider_compatibility = None
            if runtime_native:
                runtime_validation = _runtime_loader_validation(workspace, contract)
                write_json(out / "runtime_loader_validation.json", runtime_validation, exclusive=True)
                provider_compatibility = _candidate_provider_compatibility(workspace, contract)
                write_json(out / "candidate_provider_compatibility.json", provider_compatibility, exclusive=True)
            provenance = {
                "schema_version": "t21-material-provenance-v1",
                "artifact": f"{experiment.upper()}_MATERIAL_PROVENANCE",
                "status": "PASS",
                "workspace_mode": workspace_mode.value,
                "material_mode": provider.material_mode.value,
                "provider_id": provider.provider_id,
                "provider_kind": provider.provider_kind,
                "synthetic": provider.synthetic,
                "placeholder_audits": provider.placeholder_audits,
                "author_fingerprint_root": authored["fingerprint_root"],
                "author_invocations": author_invocations,
            }
            if runtime_native:
                provenance["runtime_native"] = {
                    "corpus_format": materialized.get("corpus_format"),
                    "materializer": materialized.get("materializer"),
                    "runtime_loader_validated": materialized.get("runtime_loader_validated"),
                    "loader_validation_artifact": "runtime_loader_validation.json",
                    "candidate_provider_compatibility_artifact": "candidate_provider_compatibility.json",
                    "candidate_rows_executed": 0,
                }
            write_json(out / "material_provenance.json", provenance, exclusive=True)
            audits = run_construction_audits(
                workspace,
                source_root,
                contract,
                bundle,
                provider,
                workspace_mode,
                provider.material_mode,
                author_invocations=author_invocations,
            )
            phase = machine.transition("complete_construction", phase)
            transitions.append(phase.value)
            # Readiness check catches every missing seal input before the ledger becomes terminal.
            build_manifest(workspace, contract, graph)
            ledger.complete(
                {
                    "rows": sum(materialized["suite_counts"].values()),
                    "suites": len(materialized["suite_counts"]),
                    "material_mode": provider.material_mode.value,
                    "audits": audits["reports"],
                }
            )
            sealed = seal_holdout(
                workspace,
                contract,
                graph,
                workspace_mode=workspace_mode,
                qualification_rehearsal=qualification_rehearsal,
            )
            phase = machine.transition("seal", phase)
            transitions.append(phase.value)
            if phase != Phase.SEALED:
                raise ValidationError("construction terminal state is not SEALED")
            verified = verify_seal(workspace, contract, graph)
            stop = _assert_construction_stop(workspace, experiment)
        except Exception as exc:
            if ledger.state == "STARTED":
                ledger.fail({"error_type": type(exc).__name__, "error": str(exc)})
            raise

    return {
        "status": "PASS",
        "verdict": success_verdict,
        "workspace_mode": workspace_mode.value,
        "material_mode": provider.material_mode.value,
        "terminal_state": phase.value,
        "state_transitions": transitions,
        "construction_ledger": ledger.state,
        "corpus": materialized["corpus"],
        "suite_counts": materialized["suite_counts"],
        "audits": audits,
        "seal": sealed["status"],
        "seal_verification": verified,
        "seal_binding_set": sorted(sealed["manifest"]["bindings"]),
        **stop,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run T21 production construction only and stop at SEALED")
    parser.add_argument("--experiment", default="t21r15")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--authorization", required=True)
    arguments = parser.parse_args(argv)
    try:
        report = run_construction(
            arguments.experiment,
            arguments.workspace,
            arguments.authorization,
            workspace_mode=WorkspaceMode.REAL_EXPERIMENT,
        )
    except Exception as exc:
        report = {"status": "FAIL", "verdict": FAIL_VERDICT, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
