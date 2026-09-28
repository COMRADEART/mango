"""Authenticated historical-exclusion provenance for T27.

Public history is rebuilt from a frozen source registry. Private experiments
are represented by public commitments here and by sealed private oracles; raw
private values never enter this module's output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

DIMENSIONS = (
    "case_ids", "entity_identities", "source_ids", "chunk_ids",
    "exact_queries", "exact_answers", "exact_source_text",
    "verbatim_attack_wording", "relations",
)

REQUIRED_HISTORICAL_SOURCES = (
    "T21_T21R_HISTORICAL", "T22_PROTECTED", "T23_EXPOSED",
    "T24_PRIVATE_EVALUATED", "T25_PRIVATE_EVALUATED",
    "T26_SEALED_EVALUATED", "T27_PUBLIC_QUALIFICATION",
    "T27_DIAGNOSTICS", "T27_PUBLIC_REPRODUCER",
    "T27_SYNTHETIC_TERMINAL_MATRIX",
    "T27_SYNTHETIC_RECOVERY_REPLAN_EXAMPLES",
)

PUBLIC_HISTORY_BUILDER = (
    "t27_protocol.exclusion:build_authenticated_public_historical_index"
)
SYNTHETIC_HISTORY_BUILDER = (
    "t27_protocol.exclusion:build_synthetic_historical_index"
)

# Fixed repository evidence. Private classes contribute commitments only;
# their row-level comparison remains inside a sealed private boundary.
SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "T21_T21R_HISTORICAL": {
        "source_id": "t21r17-public-history",
        "paths": ("evaluations/t21r17/historical_exclusion.json",
                  "evaluations/t21r17/prior_exclusion.json"),
        "representation": "PUBLIC_HASH_REGISTRY",
        "fingerprint_loader": "MILESTONE_REGISTRY",
    },
    "T22_PROTECTED": {
        "source_id": "t22-public-protected-history",
        "paths": ("evaluations/t22/T22_FINAL_PROMOTION_RECORD.json",
                  "evaluations/t23/t22_exclusion_anchor.json"),
        "representation": "PUBLIC_HASH_ONLY_ANCHOR",
        "fingerprint_loader": "FINGERPRINT_MAP",
    },
    "T23_EXPOSED": {
        "source_id": "t23-public-exposed-history",
        "paths": ("evaluations/t23/historical_exclusion.json",
                  "evaluations/t24/t23_exposed_sealed_anchor.json"),
        "representation": "PUBLIC_EXPOSED_HASH_ONLY_ANCHOR",
        "fingerprint_loader": "DIMENSION_MAP",
    },
    "T24_PRIVATE_EVALUATED": {
        "source_id": "t24-sealed-public-commitment",
        "paths": ("evaluations/t24/evaluation/T24_EVALUATION_PUBLIC_RECEIPT.json",
                  "evaluations/t25/t24_sealed_evaluated_anchor.json"),
        "representation": "SEALED_HASH_BOUND_ORACLE_OUTPUT",
        "fingerprint_loader": "DIMENSION_MAP",
    },
    "T25_PRIVATE_EVALUATED": {
        "source_id": "t25-sealed-public-commitment",
        "paths": ("evaluations/t25/t25_private_store_config.json",
                  "evaluations/t25/T25_FINAL_PROMOTION_RECORD.json"),
        "representation": "SEALED_PRIVATE_COMMITMENT_ONLY",
        "fingerprint_loader": "NONE",
    },
    "T26_SEALED_EVALUATED": {
        "source_id": "t26-sealed-public-commitment",
        "paths": ("evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json",
                  "evaluations/t26/T26_EVALUATION_PROTOCOL_ADDENDUM_V3.json"),
        "representation": "SEALED_PRIVATE_ORACLE_REQUIRED",
        "fingerprint_loader": "NONE",
    },
    "T27_PUBLIC_QUALIFICATION": {
        "source_id": "t27-public-qualification",
        "paths": ("evaluations/t27/qualification_report.json",
                  "t27_protocol/qualification.py"),
        "representation": "PUBLIC_GENERATED_CASES",
        "fingerprint_loader": "T27_QUALIFICATION",
    },
    "T27_DIAGNOSTICS": {
        "source_id": "t27-public-diagnostics",
        "paths": ("evaluations/t27/diagnostics_report.json",
                  "t27_protocol/qualification.py"),
        "representation": "PUBLIC_GENERATED_TERMINAL_MATRIX",
        "fingerprint_loader": "T27_TERMINAL_MATRIX",
    },
    "T27_PUBLIC_REPRODUCER": {
        "source_id": "t27-public-reproducer",
        "paths": ("evaluations/t27/T27_PUBLIC_ROOT_CAUSE_REPRODUCTION.json",),
        "representation": "PUBLIC_AGGREGATE_COMMITMENT_ONLY",
        "fingerprint_loader": "NONE",
    },
    "T27_SYNTHETIC_TERMINAL_MATRIX": {
        "source_id": "t27-synthetic-terminal-matrix",
        "paths": ("evaluations/t27/diagnostics_report.json",
                  "t27_protocol/qualification.py"),
        "representation": "PUBLIC_GENERATED_TERMINAL_MATRIX",
        "fingerprint_loader": "T27_TERMINAL_MATRIX",
    },
    "T27_SYNTHETIC_RECOVERY_REPLAN_EXAMPLES": {
        "source_id": "t27-synthetic-recovery-replan",
        "paths": ("evaluations/t27/qualification_report.json",
                  "t27_protocol/qualification.py"),
        "representation": "PUBLIC_GENERATED_RECOVERY_REPLAN_CASES",
        "fingerprint_loader": "T27_RECOVERY_REPLAN",
    },
}


def _repository_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n") if b"\0" not in data else data


def _builder_sha256() -> str:
    return hashlib.sha256(_repository_bytes(Path(__file__))).hexdigest()


def _fingerprint_map(document: dict[str, Any], container: str
                     ) -> dict[str, list[str]]:
    dimensions = document.get(container, {})
    result = {name: [] for name in DIMENSIONS}
    if not isinstance(dimensions, dict):
        raise ValueError("historical fingerprint container invalid")
    for name in DIMENSIONS:
        value = dimensions.get(name)
        if value is None:
            continue
        values = value if isinstance(value, list) else value.get("fingerprints", [])
        if not isinstance(values, list):
            raise ValueError("historical dimension fingerprint set invalid")
        result[name].extend(values)
    return result


def _milestone_fingerprints(document: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {name: set() for name in DIMENSIONS}
    milestones = document.get("milestones", {})
    if not isinstance(milestones, dict) or not milestones:
        raise ValueError("historical milestone registry absent")
    for milestone in milestones.values():
        dimensions = milestone.get("dimensions", {})
        for name in DIMENSIONS:
            value = dimensions.get(name)
            if value is not None:
                result[name].update(value.get("fingerprints", []))
    return {name: sorted(values) for name, values in result.items()}


def _bundle_fingerprints(
        triples: list[tuple[dict[str, Any], dict[str, Any], str]]
) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {name: set() for name in DIMENSIONS}
    for scenario, expected, family in triples:
        plan = scenario["plan"]
        result["case_ids"].add(sha256_json(scenario["scenario_id"]))
        result["entity_identities"].add(sha256_json(family))
        result["source_ids"].update(
            sha256_json(step["capability"]) for step in plan["steps"])
        result["chunk_ids"].update(
            sha256_json((scenario["scenario_id"], step["step_id"]))
            for step in plan["steps"])
        result["exact_queries"].add(sha256_json(plan["goal"]))
        result["exact_answers"].add(sha256_json(expected["expected_answer"]))
        result["exact_source_text"].update(
            sha256_json(step["input"]) for step in plan["steps"])
        result["verbatim_attack_wording"].add(
            sha256_json((family, plan["fallback_condition"])))
        result["relations"].update(
            sha256_json((step["step_id"], step["depends_on"]))
            for step in plan["steps"])
    return {name: sorted(values) for name, values in result.items()}


def _t27_generated_fingerprints(loader: str) -> dict[str, list[str]]:
    from .contract import FAMILIES
    from .qualification import _scenario, build_public_cases

    if loader in {"T27_QUALIFICATION", "T27_RECOVERY_REPLAN"}:
        cases, gold, _ = build_public_cases()
        triples = [(case, expected, FAMILIES[index // 4])
                   for index, (case, expected) in enumerate(zip(cases, gold))]
        if loader == "T27_RECOVERY_REPLAN":
            selected = {"tool_failure_recovery", "plan_replan_resume",
                        "conflicting_evidence", "insufficient_evidence"}
            triples = [item for item in triples if item[2] in selected]
        return _bundle_fingerprints(triples)
    if loader == "T27_TERMINAL_MATRIX":
        specifications = (
            ("COMPLETE", 1, 3), ("PARTIAL", 1, 3),
            ("INSUFFICIENT_EVIDENCE", 1, 3), ("BLOCKED", 1, 3),
            ("BUDGET_EXHAUSTED", 0, 0),
            ("UNAVAILABLE_CAPABILITY", 1, 3),
            ("SECURITY_REFUSAL", 1, 3), ("ERROR", 1, 3),
        )
        triples = []
        for index, (terminal, step_retry, total_retry) in enumerate(specifications):
            scenario = _scenario(
                f"t27-terminal-{terminal.lower()}",
                ("MATH_T4", "SCICOMP", "GENERAL"), base=301 + index,
                max_step_retries=step_retry,
                max_total_retries=total_retry)
            triples.append((scenario, {"expected_answer": terminal},
                            "synthetic_terminal_matrix"))
        return _bundle_fingerprints(triples)
    raise ValueError("unknown T27 historical fingerprint loader")


def _load_dimension_fingerprints(loader: str, documents: list[Any]
                                 ) -> dict[str, list[str]]:
    if loader == "NONE":
        return {name: [] for name in DIMENSIONS}
    if loader == "MILESTONE_REGISTRY":
        registry = next((value for value in documents
                         if isinstance(value, dict)
                         and isinstance(value.get("milestones"), dict)), None)
        if registry is None:
            raise ValueError("milestone fingerprint registry absent")
        return _milestone_fingerprints(registry)
    if loader in {"FINGERPRINT_MAP", "DIMENSION_MAP"}:
        container = "fingerprints" if loader == "FINGERPRINT_MAP" else "dimensions"
        document = next((value for value in documents
                         if isinstance(value, dict)
                         and isinstance(value.get(container), dict)), None)
        if document is None:
            raise ValueError("dimension fingerprint registry absent")
        return _fingerprint_map(document, container)
    if loader.startswith("T27_"):
        return _t27_generated_fingerprints(loader)
    raise ValueError("unknown historical fingerprint loader")


def _dimension_record(values: list[str], *, applicable: bool,
                      empty_contract: str | None = None) -> dict[str, Any]:
    ordered = sorted(set(values)) if applicable else []
    record: dict[str, Any] = {
        "applicable": applicable,
        "historical_population": len(ordered),
        "dimension_root": sha256_json(ordered),
        "fingerprints": ordered,
    }
    if not applicable:
        record["empty_contract"] = empty_contract
    return record


def _source_record(root: Path, source_class: str,
                   specification: dict[str, Any]) -> dict[str, Any]:
    files = []
    documents = []
    for relative in specification["paths"]:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"required historical source absent: {relative}")
        data = _repository_bytes(path)
        files.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                      "byte_size": len(data)})
        try:
            documents.append(json.loads(data.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            documents.append({"path": relative, "sha256": files[-1]["sha256"]})
    representation = specification["representation"]
    source_commitment = sha256_json(files)
    values = _load_dimension_fingerprints(
        specification["fingerprint_loader"], documents)
    dimensions = {
        name: _dimension_record(
            values[name], applicable=bool(values[name]),
            empty_contract=(None if values[name] else
                            f"{source_class}:{name}:{representation}:FROZEN_EMPTY"))
        for name in DIMENSIONS
    }
    core = {
        "source_id": specification["source_id"],
        "source_class": source_class,
        "source_commitment": source_commitment,
        "representation": representation,
        "dimension_populations": {
            name: dimensions[name]["historical_population"] for name in DIMENSIONS},
        "dimension_roots": {
            name: dimensions[name]["dimension_root"] for name in DIMENSIONS},
        "dimensions": dimensions,
        "builder_implementation_identity": PUBLIC_HISTORY_BUILDER,
        "builder_implementation_sha256": _builder_sha256(),
    }
    return {**core, "overall_source_root": sha256_json(core)}


def build_authenticated_public_historical_index(root: Path) -> dict[str, Any]:
    """Build the authoritative source-aware index from fixed repository bytes."""
    root = Path(root).resolve()
    if set(SOURCE_REGISTRY) != set(REQUIRED_HISTORICAL_SOURCES):
        raise ValueError("historical source registry drift")
    sources = [_source_record(root, name, SOURCE_REGISTRY[name])
               for name in REQUIRED_HISTORICAL_SOURCES]
    aggregate_dimensions = {}
    for name in DIMENSIONS:
        values = sorted({value for source in sources
                         for value in source["dimensions"][name]["fingerprints"]})
        aggregate_dimensions[name] = _dimension_record(
            values, applicable=bool(values),
            empty_contract=None if values else "FROZEN_PUBLIC_REGISTRY_EMPTY")
    core = {
        "schema_version": "t27-authenticated-public-historical-index-v1",
        "artifact": "T27_AUTHENTICATED_PUBLIC_HISTORICAL_INDEX",
        "classification": "PUBLIC_SAFE",
        "mode": "REAL_AUTHENTICATED",
        "builder_implementation_identity": PUBLIC_HISTORY_BUILDER,
        "builder_implementation_sha256": _builder_sha256(),
        "required_source_count": len(REQUIRED_HISTORICAL_SOURCES),
        "required_source_classes": list(REQUIRED_HISTORICAL_SOURCES),
        "sources": sources,
        "aggregate_dimensions": aggregate_dimensions,
    }
    return {**core, "public_historical_index_root": sha256_json(core)}


def build_synthetic_historical_index(variant: int = 0) -> dict[str, Any]:
    """Explicit disposable index. It is never accepted by real construction."""
    sources = []
    for source_class in REQUIRED_HISTORICAL_SOURCES:
        values = {name: [sha256_json(("synthetic-history", variant,
                                      source_class, name))]
                  for name in DIMENSIONS}
        dimensions = {name: _dimension_record(values[name], applicable=True)
                      for name in DIMENSIONS}
        core = {
            "source_id": f"synthetic-{variant}-{source_class.lower()}",
            "source_class": source_class,
            "source_commitment": sha256_json(("synthetic-source", variant,
                                                source_class)),
            "representation": "SYNTHETIC_DISPOSABLE_HASHES",
            "dimension_populations": {name: 1 for name in DIMENSIONS},
            "dimension_roots": {name: dimensions[name]["dimension_root"]
                                for name in DIMENSIONS},
            "dimensions": dimensions,
            "builder_implementation_identity": SYNTHETIC_HISTORY_BUILDER,
            "builder_implementation_sha256": sha256_json(SYNTHETIC_HISTORY_BUILDER),
        }
        sources.append({**core, "overall_source_root": sha256_json(core)})
    aggregate_dimensions = {}
    for name in DIMENSIONS:
        values = sorted({value for source in sources
                         for value in source["dimensions"][name]["fingerprints"]})
        aggregate_dimensions[name] = _dimension_record(values, applicable=True)
    core = {
        "schema_version": "t27-synthetic-historical-index-v1",
        "artifact": "T27_SYNTHETIC_HISTORICAL_INDEX",
        "classification": "SYNTHETIC_DISPOSABLE",
        "mode": "SYNTHETIC_DISPOSABLE",
        "builder_implementation_identity": SYNTHETIC_HISTORY_BUILDER,
        "builder_implementation_sha256": sha256_json(SYNTHETIC_HISTORY_BUILDER),
        "required_source_count": len(REQUIRED_HISTORICAL_SOURCES),
        "required_source_classes": list(REQUIRED_HISTORICAL_SOURCES),
        "sources": sources,
        "aggregate_dimensions": aggregate_dimensions,
    }
    return {**core, "public_historical_index_root": sha256_json(core)}


def _validate_structure(index: dict[str, Any]) -> None:
    if not isinstance(index, dict):
        raise ValueError("historical index absent")
    sources = index.get("sources")
    if not isinstance(sources, list) or len(sources) != len(REQUIRED_HISTORICAL_SOURCES):
        raise ValueError("required historical source registry absent or incomplete")
    if [item.get("source_class") for item in sources] != list(REQUIRED_HISTORICAL_SOURCES):
        raise ValueError("required historical source class missing")
    for source in sources:
        required = {"source_id", "source_class", "source_commitment",
                    "representation", "dimension_populations", "dimension_roots",
                    "dimensions", "builder_implementation_identity",
                    "builder_implementation_sha256", "overall_source_root"}
        if set(source) != required:
            raise ValueError("historical source provenance fields missing")
        if not isinstance(source["source_commitment"], str) or len(
                source["source_commitment"]) != 64:
            raise ValueError("historical source commitment invalid")
        if set(source["dimensions"]) != set(DIMENSIONS):
            raise ValueError("historical source dimension missing")
        for name in DIMENSIONS:
            dimension = source["dimensions"][name]
            required_dimension = {"applicable", "historical_population",
                                  "dimension_root", "fingerprints"}
            if not dimension.get("applicable"):
                required_dimension.add("empty_contract")
            if set(dimension) != required_dimension:
                raise ValueError("historical source dimension provenance incomplete")
            values = dimension["fingerprints"]
            if (not isinstance(values, list) or len(values) != len(set(values))
                    or any(not isinstance(value, str) or len(value) != 64
                           for value in values)):
                raise ValueError("historical source fingerprint set invalid")
            if dimension["historical_population"] != len(values):
                raise ValueError("historical source dimension population mismatch")
            if dimension["applicable"] and not values:
                raise ValueError("applicable historical dimension unexpectedly empty")
            if not dimension["applicable"] and dimension.get("empty_contract") is None:
                raise ValueError("inapplicable historical dimension lacks empty contract")
            if dimension["dimension_root"] != sha256_json(values):
                raise ValueError("historical source dimension root mismatch")
        if source["dimension_populations"] != {
                name: source["dimensions"][name]["historical_population"]
                for name in DIMENSIONS}:
            raise ValueError("historical source population summary mismatch")
        if source["dimension_roots"] != {
                name: source["dimensions"][name]["dimension_root"]
                for name in DIMENSIONS}:
            raise ValueError("historical source root summary mismatch")
        source_core = {key: value for key, value in source.items()
                       if key != "overall_source_root"}
        if source["overall_source_root"] != sha256_json(source_core):
            raise ValueError("historical source root mismatch")
    if set(index.get("aggregate_dimensions", {})) != set(DIMENSIONS):
        raise ValueError("aggregate historical dimension set incomplete")
    for name in DIMENSIONS:
        values = sorted({value for source in sources
                         for value in source["dimensions"][name]["fingerprints"]})
        aggregate = index["aggregate_dimensions"][name]
        required_aggregate = {"applicable", "historical_population",
                              "dimension_root", "fingerprints"}
        if not aggregate.get("applicable"):
            required_aggregate.add("empty_contract")
        if (set(aggregate) != required_aggregate or aggregate["fingerprints"] != values
                or aggregate["historical_population"] != len(values)
                or aggregate["dimension_root"] != sha256_json(values)):
            raise ValueError("aggregate historical dimension mismatch")
    core = {key: value for key, value in index.items()
            if key != "public_historical_index_root"}
    if index.get("public_historical_index_root") != sha256_json(core):
        raise ValueError("aggregate public historical root mismatch")


def verify_historical_index(index: dict[str, Any], *, root: Path | None,
                            mode: str) -> dict[str, Any]:
    _validate_structure(index)
    if mode == "REAL":
        if root is None or index != build_authenticated_public_historical_index(root):
            raise ValueError("public historical index is not repository-authenticated")
        authenticated = True
    elif mode == "SYNTHETIC":
        if (index.get("schema_version") != "t27-synthetic-historical-index-v1"
                or index.get("mode") != "SYNTHETIC_DISPOSABLE"
                or index.get("builder_implementation_identity") !=
                SYNTHETIC_HISTORY_BUILDER):
            raise ValueError("synthetic historical index not explicitly marked")
        authenticated = False
    else:
        raise ValueError("unknown historical index verification mode")
    return {
        "status": "PASS", "source_count": len(index["sources"]),
        "source_classes_complete": True,
        "repository_authenticated": authenticated,
        "explicit_synthetic": mode == "SYNTHETIC",
        "public_historical_index_root": index["public_historical_index_root"],
    }


def public_index_report(index: dict[str, Any]) -> dict[str, Any]:
    """Public-safe provenance report without the already-hashed value sets."""
    _validate_structure(index)
    return {
        "schema_version": "t27-public-historical-index-report-v1",
        "artifact": "T27_PUBLIC_HISTORICAL_INDEX_REPORT",
        "classification": "PUBLIC_SAFE",
        "builder_implementation_identity": index["builder_implementation_identity"],
        "builder_implementation_sha256": index["builder_implementation_sha256"],
        "required_source_count": index["required_source_count"],
        "sources": [{key: source[key] for key in (
            "source_id", "source_class", "source_commitment", "representation",
            "dimension_populations", "dimension_roots", "overall_source_root")}
            for source in index["sources"]],
        "aggregate_dimension_populations": {
            name: index["aggregate_dimensions"][name]["historical_population"]
            for name in DIMENSIONS},
        "aggregate_dimension_roots": {
            name: index["aggregate_dimensions"][name]["dimension_root"]
            for name in DIMENSIONS},
        "public_historical_index_root": index["public_historical_index_root"],
        "private_rows_included": False,
    }


def policy() -> dict:
    return {
        "schema_version": "t27-historical-exclusion-policy-v1",
        "artifact": "T27_HISTORICAL_EXCLUSION_POLICY",
        "classification": "PUBLIC_SAFE", "dimensions": list(DIMENSIONS),
        "historical_source": "T26_SEALED_HASH_OVERLAP_ORACLE_ONLY",
        "oracle_contract": {
            "input": "dimension-tagged candidate SHA-256 sets",
            "output": "dimension-tagged overlap counts plus signed root",
            "raw_historical_values_returned": False,
            "row_identity_returned": False,
            "required_overlap": 0,
        },
        "t26_private_rows_opened": 0,
        "candidate_executions_on_t26_rows": 0,
        "required_at_real_construction": True,
    }


def validate_oracle_receipt(receipt: dict) -> bool:
    return (isinstance(receipt, dict) and
            receipt.get("dimensions") == {name: 0 for name in DIMENSIONS} and
            isinstance(receipt.get("oracle_root"), str) and
            len(receipt["oracle_root"]) == 64 and
            receipt.get("raw_historical_values_returned") is False)


def construction_ready_policy() -> dict:
    """Historical V2 policy retained byte-for-byte by its artifact."""
    return {
        "schema_version": "t27-historical-exclusion-policy-v2",
        "artifact": "T27_CONSTRUCTION_READY_HISTORICAL_EXCLUSION_POLICY",
        "classification": "PUBLIC_SAFE", "dimensions": list(DIMENSIONS),
        "historical_sources": list(REQUIRED_HISTORICAL_SOURCES),
        "t26_boundary": {
            "implementation": "t26_protocol.t27_private_oracle:compare_hashes",
            "result_artifact": "T26_TO_T27_OVERLAP_ORACLE_RESULT",
            "input_values": "SHA256_ONLY", "output_values": "COUNTS_AND_ROOTS_ONLY",
            "private_rows_returned": 0,
        },
        "per_dimension_fields": [
            "applicable", "prospective_population", "historical_population",
            "overlap_count",
        ],
        "overall_prohibited_overlap_required": 0,
        "candidate_execution_on_historical_rows": False,
        "historical_private_row_exposure_to_author": 0,
        "required_before_real_construction_ledger": True,
    }


def authenticated_construction_policy() -> dict[str, Any]:
    return {
        "schema_version": "t27-historical-exclusion-policy-v3",
        "artifact": "T27_AUTHENTICATED_HISTORICAL_EXCLUSION_POLICY",
        "classification": "PUBLIC_SAFE",
        "dimensions": list(DIMENSIONS),
        "required_sources": list(REQUIRED_HISTORICAL_SOURCES),
        "public_history_builder": PUBLIC_HISTORY_BUILDER,
        "public_history_schema": "t27-authenticated-public-historical-index-v1",
        "real_empty_default_allowed": False,
        "private_source_representation": "SEALED_HASH_BOUND_ORACLE_ONLY",
        "t26_boundary": {
            "implementation":
                "t26_protocol.t27_private_oracle:run_sealed_t26_to_t27_overlap_oracle",
            "result_artifact": "T26_TO_T27_OVERLAP_ORACLE_RESULT",
            "official_commitments_exact": True,
            "store_authenticated": True,
            "input_values": "SHA256_ONLY",
            "output_values": "COUNTS_AND_ROOTS_ONLY",
            "private_rows_returned": 0,
        },
        "synthetic_real_schema_separation": True,
        "combined_roots_required_before_ledger": [
            "public_historical_index_root", "T26_overlap_oracle_result_sha256",
            "combined_historical_exclusion_root"],
        "overall_prohibited_overlap_required": 0,
        "candidate_execution_on_historical_rows": False,
        "historical_private_row_exposure_to_author": 0,
    }
