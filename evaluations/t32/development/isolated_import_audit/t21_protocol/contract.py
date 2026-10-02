"""Typed T21 master-contract loader and fail-closed validator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import ContractError
from .util import read_json, sha256_json

ROOT_KEYS = frozenset({"schema_version", "artifact", "experiment", "values", "fields"})
FIELD_KEYS = frozenset(
    {"path", "type", "presence", "producer", "consumers", "validation", "freeze_phase"}
)
JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}
KNOWN_COMPONENTS = frozenset(
    {
        "contract",
        "artifact_graph",
        "state_machine",
        "author",
        "builder",
        "construction_gate",
        "exact_design_auditor",
        "historical_exclusion",
        "remediation_exclusion",
        "seal",
        "official_validator",
        "evaluator",
        "scorer",
        "qualification",
        "protocol_doctor",
        "operator",
        "runtime_contract",
        "field_provenance",
        "metric_registry",
        "evidence_contract",
        "real_candidate_provider",
        "official_evaluator",
        "r15_closure",
        "shadow_runtime_validator",
    }
)
PHASES = frozenset(
    {
        "PRECONSTRUCTION",
        "QUALIFIED",
        "CONSTRUCTION_STARTED",
        "CONSTRUCTED",
        "SEALED",
        "EVALUATION_STARTED",
        "EVALUATION_COMPLETE",
        "FAILED",
    }
)


def _leaf_paths(value: Any, prefix: str = "values") -> Iterator[tuple[str, Any]]:
    """Yield the contract's named semantic fields.

    Composite fields use closed, domain-specific validation below.  This keeps
    each field's type/producer/consumer/freeze metadata readable instead of
    repeating metadata for every scalar inside a structured policy.
    """
    if prefix == "values" and isinstance(value, dict):
        for key in sorted(value):
            yield f"values.{key}", value[key]
    else:
        yield prefix, value


def value_at_path(document: dict[str, Any], dotted: str) -> Any:
    value: Any = document
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value


def _type_matches(value: Any, declared: str) -> bool:
    expected = JSON_TYPES.get(declared)
    if expected is None:
        return False
    if declared in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _validation_matches(value: Any, validation: dict[str, Any]) -> bool:
    allowed = frozenset({"const", "enum", "minimum", "maximum", "length", "sha256", "nonempty"})
    if set(validation) - allowed:
        return False
    if "const" in validation and value != validation["const"]:
        return False
    if "enum" in validation and value not in validation["enum"]:
        return False
    if "minimum" in validation and value < validation["minimum"]:
        return False
    if "maximum" in validation and value > validation["maximum"]:
        return False
    if "length" in validation and len(value) != validation["length"]:
        return False
    if validation.get("sha256") is True and (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        return False
    if validation.get("nonempty") is True and not value:
        return False
    return True


def validate_master_contract(document: dict[str, Any], *, raise_on_error: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    unknown_top = sorted(set(document) - ROOT_KEYS)
    missing_top = sorted(ROOT_KEYS - set(document))
    errors.extend(f"unknown top-level field: {name}" for name in unknown_top)
    errors.extend(f"missing top-level field: {name}" for name in missing_top)
    if errors:
        report = _report(errors, 0, 0, 0, len(unknown_top))
        if raise_on_error:
            raise ContractError("; ".join(errors))
        return report

    if document["schema_version"] != "t21-master-contract-v2":
        errors.append("unsupported schema_version")
    if document["artifact"] != "T21_MASTER_CONTRACT":
        errors.append("artifact identity mismatch")
    if not isinstance(document["experiment"], str) or not document["experiment"]:
        errors.append("experiment must be a non-empty string")
    if not isinstance(document["values"], dict):
        errors.append("values must be an object")
    if not isinstance(document["fields"], list):
        errors.append("fields must be an array")
    if errors:
        report = _report(errors, 0, 0, 0, 0)
        if raise_on_error:
            raise ContractError("; ".join(errors))
        return report

    descriptor_by_path: dict[str, dict[str, Any]] = {}
    unknown_consumers = 0
    type_disagreements = 0
    for index, descriptor in enumerate(document["fields"]):
        if not isinstance(descriptor, dict):
            errors.append(f"fields[{index}] is not an object")
            continue
        unknown_keys = set(descriptor) - FIELD_KEYS
        missing_keys = FIELD_KEYS - set(descriptor)
        if unknown_keys:
            errors.append(f"fields[{index}] unknown keys: {sorted(unknown_keys)}")
        if missing_keys:
            errors.append(f"fields[{index}] missing keys: {sorted(missing_keys)}")
        if unknown_keys or missing_keys:
            continue
        path = descriptor["path"]
        if not isinstance(path, str) or not path.startswith("values."):
            errors.append(f"fields[{index}] has invalid path")
            continue
        if path in descriptor_by_path:
            errors.append(f"duplicate field descriptor: {path}")
            continue
        descriptor_by_path[path] = descriptor
        if descriptor["type"] not in JSON_TYPES:
            errors.append(f"{path}: unknown type {descriptor['type']!r}")
        if descriptor["presence"] not in {"required", "optional"}:
            errors.append(f"{path}: presence must be required or optional")
        if descriptor["producer"] not in KNOWN_COMPONENTS:
            errors.append(f"{path}: unknown producer {descriptor['producer']!r}")
        consumers = descriptor["consumers"]
        if not isinstance(consumers, list) or not consumers:
            errors.append(f"{path}: consumers must be a non-empty list")
        else:
            bad = [consumer for consumer in consumers if consumer not in KNOWN_COMPONENTS]
            unknown_consumers += len(bad)
            errors.extend(f"{path}: unknown consumer {consumer!r}" for consumer in bad)
        if not isinstance(descriptor["validation"], dict):
            errors.append(f"{path}: validation must be an object")
        if descriptor["freeze_phase"] not in PHASES:
            errors.append(f"{path}: unknown freeze phase")

    leaves = dict(_leaf_paths(document["values"]))
    untyped = sorted(set(leaves) - set(descriptor_by_path))
    unknown_descriptors = sorted(set(descriptor_by_path) - set(leaves))
    errors.extend(f"untyped field: {path}" for path in untyped)
    errors.extend(f"descriptor has no value: {path}" for path in unknown_descriptors)
    for path in sorted(set(leaves) & set(descriptor_by_path)):
        descriptor = descriptor_by_path[path]
        value = leaves[path]
        if not _type_matches(value, descriptor["type"]):
            type_disagreements += 1
            errors.append(f"{path}: value disagrees with declared type {descriptor['type']}")
        elif not _validation_matches(value, descriptor["validation"]):
            errors.append(f"{path}: validation failed")

    errors.extend(_validate_semantics(document["values"], document["experiment"]))

    report = _report(
        errors,
        len(untyped),
        unknown_consumers,
        type_disagreements,
        len(unknown_top) + len(unknown_descriptors),
    )
    if errors and raise_on_error:
        raise ContractError("; ".join(errors))
    return report


def _closed(value: Any, keys: set[str] | frozenset[str], context: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return False
    if set(value) != set(keys):
        errors.append(f"{context} fields differ: expected={sorted(keys)}, actual={sorted(value)}")
        return False
    return True


R15_ROOT_KEYS = frozenset({"candidate_commit", "candidate_tree", "runtime_root", "evaluator_root", "floor_hash"})
R16_ROOT_DIGEST_KEYS = frozenset(
    {
        "candidate_commit",
        "candidate_tree",
        "runtime_root",
        "evaluator_root",
        "floor_hash",
        "runtime_data_contract_root",
        "runtime_corpus_contract_sha256",
        "runtime_field_provenance_sha256",
        "candidate_provider_sha256",
    }
)
R15_CONSTRUCT_POLICY = {
    "required_state": "QUALIFIED",
    "terminal_states": ["SEALED"],
    "authorization_token": "T21R15_REAL_BLIND_CONSTRUCTION_AUTHORIZED",
    "allowed_artifact_phases": ["CONSTRUCTION", "SEAL"],
}
R15_EVALUATE_POLICY = {
    "required_state": "SEALED",
    "terminal_states": ["EVALUATION_COMPLETE", "FAILED"],
    "authorization_token": "T21R15_ONE_SHOT_OFFICIAL_EVALUATION",
    "allowed_artifact_phases": ["EVALUATION"],
}
R16_CONSTRUCT_POLICY = {
    "required_state": "QUALIFIED",
    "terminal_states": ["SEALED"],
    "authorization_token": "T21R16_REAL_BLIND_CONSTRUCTION_AUTHORIZED",
    "allowed_artifact_phases": ["CONSTRUCTION", "SEAL"],
}
R16_EVALUATE_POLICY = {
    "required_state": "SEALED",
    "terminal_states": ["EVALUATION_COMPLETE", "FAILED"],
    "authorization_token": "T21R16_ONE_SHOT_OFFICIAL_EVALUATION",
    "allowed_artifact_phases": ["EVALUATION"],
}
R17_CONSTRUCT_POLICY = {
    "required_state": "QUALIFIED",
    "terminal_states": ["SEALED"],
    "authorization_token": "T21R17_REAL_BLIND_CONSTRUCTION_AUTHORIZED",
    "allowed_artifact_phases": ["CONSTRUCTION", "SEAL"],
}
R17_EVALUATE_POLICY = {
    "required_state": "SEALED",
    "terminal_states": ["EVALUATION_COMPLETE", "FAILED"],
    "authorization_token": "T21R17_ONE_SHOT_OFFICIAL_EVALUATION",
    "allowed_artifact_phases": ["EVALUATION"],
}
T22_CONSTRUCT_POLICY = {
    "required_state": "QUALIFIED",
    "terminal_states": ["SEALED"],
    "authorization_token": "T22_REAL_BLIND_CONSTRUCTION_AUTHORIZED",
    "allowed_artifact_phases": ["CONSTRUCTION", "SEAL"],
}
T22_EVALUATE_POLICY = {
    "required_state": "SEALED",
    "terminal_states": ["EVALUATION_COMPLETE", "FAILED"],
    "authorization_token": "T22_ONE_SHOT_OFFICIAL_EVALUATION",
    "allowed_artifact_phases": ["EVALUATION"],
}
R17_EVALUATOR_SEMANTIC_KEYS = frozenset(
    {"evaluator", "evidence_row_fields", "required_candidate_fields", "accuracy_semantics", "kernel_evaluator_parity_required"}
)
RUNTIME_NATIVE_KEYS = frozenset(
    {
        "corpus_format",
        "loader_entry",
        "runtime_materializer",
        "candidate_provider",
        "source_id_grammar",
        "manifest_format",
        "shadow_holdout_rows",
        "holdout_frozen_schema_version",
    }
)


def _validate_semantics(values: dict[str, Any], experiment: str = "t21r15") -> list[str]:
    errors: list[str] = []
    if experiment == "t21r15":
        expected_fields = {
            "identity", "roots", "artifacts", "suites", "suite_total", "domain_taxonomy",
            "crossdomain_pairs", "exact_design", "historical_exclusions", "remediation_exclusions",
            "promotion_floors", "one_shot", "state_machine", "author", "r14_disposition",
            "real_r15_paths", "quarantine", "phase_apis", "workspace_modes", "material_modes",
        }
        if set(values) != expected_fields:
            errors.append(f"values fields differ: expected={sorted(expected_fields)}, actual={sorted(values)}")
            return errors
    elif experiment == "t21r16":
        expected_fields = {
            "identity", "roots", "artifacts", "suites", "suite_total", "domain_taxonomy",
            "crossdomain_pairs", "exact_design", "historical_exclusions", "remediation_exclusions",
            "promotion_floors", "one_shot", "state_machine", "author", "r15_disposition",
            "real_r16_paths", "quarantine", "phase_apis", "workspace_modes", "material_modes",
            "runtime_native",
        }
        if set(values) != expected_fields:
            errors.append(f"values fields differ: expected={sorted(expected_fields)}, actual={sorted(values)}")
            return errors
    elif experiment == "t21r17":
        expected_fields = {
            "identity", "roots", "artifacts", "suites", "suite_total", "domain_taxonomy",
            "crossdomain_pairs", "exact_design", "historical_exclusions", "remediation_exclusions",
            "promotion_floors", "one_shot", "state_machine", "author", "r16_disposition",
            "real_r17_paths", "quarantine", "phase_apis", "workspace_modes", "material_modes",
            "runtime_native", "metric_semantics",
        }
        if set(values) != expected_fields:
            errors.append(f"values fields differ: expected={sorted(expected_fields)}, actual={sorted(values)}")
            return errors
    elif experiment == "t22":
        # T22 carries the R17 field set forward: the R16 disposition is
        # joined by the R17 closure, and the real-blind paths rename to
        # the T22 namespace.  All design values (suites, floors, taxonomy)
        # stay the frozen set.
        expected_fields = {
            "identity", "roots", "artifacts", "suites", "suite_total", "domain_taxonomy",
            "crossdomain_pairs", "exact_design", "historical_exclusions", "remediation_exclusions",
            "promotion_floors", "one_shot", "state_machine", "author", "r16_disposition",
            "r17_disposition", "real_t22_paths", "quarantine", "phase_apis", "workspace_modes",
            "material_modes", "runtime_native", "metric_semantics",
        }
        if set(values) != expected_fields:
            errors.append(f"values fields differ: expected={sorted(expected_fields)}, actual={sorted(values)}")
            return errors
    else:
        return [f"unsupported experiment: {experiment}"]
    _validate_shared_design(values, errors)
    _validate_artifact_paths(values, experiment, errors)
    if experiment == "t21r15":
        _validate_roots_r15(values, errors)
        _validate_phase_apis_r15(values, errors)
        _validate_r14_disposition(values, errors)
        if not isinstance(values["real_r15_paths"], list) or not values["real_r15_paths"]:
            errors.append("real_r15_paths must be a non-empty array")
    elif experiment == "t21r16":
        _validate_roots_r16(values, errors)
        _validate_phase_apis_r16(values, errors)
        _validate_r15_disposition(values, errors)
        _validate_runtime_native(values, errors)
        if not isinstance(values["real_r16_paths"], list) or not values["real_r16_paths"]:
            errors.append("real_r16_paths must be a non-empty array")
    elif experiment == "t21r17":
        _validate_roots_r17(values, errors)
        _validate_phase_apis_r17(values, errors)
        _validate_r16_disposition(values, errors)
        _validate_runtime_native(values, errors)
        _validate_metric_semantics_block(values, errors)
        if not isinstance(values["real_r17_paths"], list) or not values["real_r17_paths"]:
            errors.append("real_r17_paths must be a non-empty array")
    else:
        _validate_roots_r17(values, errors)
        _validate_phase_apis_r22(values, errors)
        _validate_r16_disposition(values, errors)
        _validate_r17_disposition(values, errors)
        _validate_runtime_native(
            values, errors,
            candidate_provider="t21_protocol.providers_t22:RealCandidateProviderT22Evidence")
        _validate_metric_semantics_block(values, errors)
        if not isinstance(values["real_t22_paths"], list) or not values["real_t22_paths"]:
            errors.append("real_t22_paths must be a non-empty array")
    return errors


def _validate_shared_design(values: dict[str, Any], errors: list[str]) -> None:
    if _closed(values["identity"], {"namespace", "case_id_prefix"}, "identity", errors):
        if not values["identity"]["namespace"] or not values["identity"]["case_id_prefix"]:
            errors.append("identity values must be non-empty")
    suites = values["suites"]
    if not isinstance(suites, dict) or len(suites) != 8:
        errors.append("suites must define exactly eight suites")
        suites = {}
    family_counts: dict[str, int] = {}
    for name, spec in suites.items():
        if not _closed(spec, {"family", "count"}, f"suites.{name}", errors):
            continue
        if not isinstance(spec["count"], int) or isinstance(spec["count"], bool) or spec["count"] <= 0:
            errors.append(f"suites.{name}.count invalid")
        family_counts[spec["family"]] = spec["count"]
    if values["suite_total"] != sum(spec.get("count", 0) for spec in suites.values() if isinstance(spec, dict)):
        errors.append("suite_total differs from suite counts")
    if values["suite_total"] != 4800:
        errors.append("suite_total must remain 4800")
    taxonomy = values["domain_taxonomy"]
    if not isinstance(taxonomy, list) or len(taxonomy) != 14 or taxonomy != sorted(set(taxonomy)):
        errors.append("domain_taxonomy must contain 14 sorted unique labels")
    pairs = values["crossdomain_pairs"]
    if not isinstance(pairs, list) or len(pairs) != 7:
        errors.append("crossdomain_pairs must contain seven entries")
        pairs = []
    for index, pair in enumerate(pairs):
        if _closed(pair, {"id", "domain_a", "domain_b"}, f"crossdomain_pairs[{index}]", errors):
            if pair["domain_a"] not in taxonomy or pair["domain_b"] not in taxonomy:
                errors.append(f"crossdomain_pairs[{index}] uses unknown taxonomy label")
    design = values["exact_design"]
    if not isinstance(design, dict) or len(design) != 6:
        errors.append("exact_design must define six exact-design families")
        design = {}
    leaves = 0
    for family, requirements in design.items():
        if not isinstance(requirements, dict) or not requirements:
            errors.append(f"exact_design.{family} must be a non-empty object")
            continue
        if family != "crossdomain" and any(not isinstance(count, int) or isinstance(count, bool) or count <= 0 for count in requirements.values()):
            errors.append(f"exact_design.{family} has invalid count")
        if family == "crossdomain":
            if requirements != {"novel_pair_families": 7, "prior_exact_pair_templates_forbidden": True, "rows_per_pair": 100}:
                errors.append("exact_design.crossdomain policy invalid")
        elif family_counts.get(family) != sum(requirements.values()):
            errors.append(f"exact_design.{family} does not cover its suite")
        leaves += len(requirements)
    if leaves != 38:
        errors.append("exact_design must define exactly 38 requirements")
    floors = values["promotion_floors"]
    floor_count = 0
    if not isinstance(floors, dict):
        errors.append("promotion_floors must be an object")
        floors = {}
    for group, metrics in floors.items():
        if not isinstance(metrics, dict):
            errors.append(f"promotion_floors.{group} must be an object")
            continue
        for metric, spec in metrics.items():
            if not _closed(spec, {"op", "value"}, f"promotion_floors.{group}.{metric}", errors):
                continue
            if spec["op"] not in {"=", "<=", ">="} or not isinstance(spec["value"], (int, float)):
                errors.append(f"promotion_floors.{group}.{metric} invalid")
            floor_count += 1
    if floor_count != 32 or sha256_json(floors) != values["roots"]["floor_hash"]:
        errors.append("promotion floors do not match the frozen 32-floor hash")
    if _closed(values["one_shot"], {"construction", "evaluation", "retry", "existing_ledger"}, "one_shot", errors):
        if set(values["one_shot"].values()) != {"ONE_SHOT", "FORBIDDEN", "REFUSE"}:
            errors.append("one_shot policy values invalid")
    if values["workspace_modes"] != ["SYNTHETIC_DISPOSABLE", "REAL_EXPERIMENT"]:
        errors.append("workspace_modes policy invalid")
    if values["material_modes"] != ["SYNTHETIC", "REAL_BLIND", "REAL_DRY_RUN"]:
        errors.append("material_modes policy invalid")
    machine = values["state_machine"]
    if not _closed(machine, {"phases", "commands"}, "state_machine", errors):
        machine = {"phases": [], "commands": {}}
    if machine["phases"] != [phase for phase in ("PRECONSTRUCTION", "QUALIFIED", "CONSTRUCTION_STARTED", "CONSTRUCTED", "SEALED", "EVALUATION_STARTED", "EVALUATION_COMPLETE", "FAILED")]:
        errors.append("state_machine phases invalid")
    if not isinstance(machine["commands"], dict):
        errors.append("state_machine.commands must be an object")
    else:
        for name, spec in machine["commands"].items():
            if not _closed(spec, {"required_state", "next_state", "writable_paths"}, f"state_machine.commands.{name}", errors):
                continue
            if spec["required_state"] not in machine["phases"] or spec["next_state"] not in machine["phases"]:
                errors.append(f"state_machine.commands.{name} uses unknown phase")
            if not isinstance(spec["writable_paths"], list) or not spec["writable_paths"]:
                errors.append(f"state_machine.commands.{name} has no write allowlist")
    if _closed(values["author"], {"seed", "vocabulary"}, "author", errors):
        if not isinstance(values["author"]["seed"], int) or not isinstance(values["author"]["vocabulary"], list):
            errors.append("author configuration invalid")
    for name in ("historical_exclusions", "remediation_exclusions", "quarantine"):
        if not isinstance(values[name], dict) or not values[name]:
            errors.append(f"{name} must be a non-empty object")


def _validate_artifact_paths(values: dict[str, Any], experiment: str, errors: list[str]) -> None:
    prefix = f"evaluations/{experiment}/"
    artifact_keys = {
        "experiment_config", "artifact_graph", "domain_taxonomy", "historical_exclusion",
        "remediation_exclusion", "runtime_freeze", "evaluator_freeze", "qualification_lock",
        "negative_controls", "adjudication", "applicability", "holdout_frozen_schema",
    }
    if experiment == "t21r16":
        # Runtime-native preconstruction inputs materialized before construction.
        artifact_keys |= {"runtime_corpus_contract", "runtime_field_provenance", "candidate_runtime_data_contract"}
    if experiment == "t21r17":
        # Runtime-native preconstruction inputs plus the frozen measurement
        # semantics contract and implementation registry.
        artifact_keys |= {
            "runtime_corpus_contract",
            "runtime_field_provenance",
            "candidate_runtime_data_contract",
            "official_metric_semantics",
            "metric_implementation_registry",
        }
    if experiment == "t22":
        # The R17 set plus the T22 temporal design artifacts (the frozen
        # signal contract, holdout design, zero-denominator resolution and
        # the candidate identity record).
        artifact_keys |= {
            "runtime_corpus_contract",
            "runtime_field_provenance",
            "candidate_runtime_data_contract",
            "official_metric_semantics",
            "metric_implementation_registry",
            "temporal_signal_contract",
            "temporal_holdout_design",
            "zero_denominator_policy_resolution",
            "candidate_identity",
        }
    if _closed(values["artifacts"], artifact_keys, "artifacts", errors):
        if any(not isinstance(path, str) or not path.startswith(prefix) for path in values["artifacts"].values()):
            errors.append(f"artifact paths must be {experiment} repository-relative paths")


def _validate_roots_r15(values: dict[str, Any], errors: list[str]) -> None:
    if _closed(values["roots"], R15_ROOT_KEYS, "roots", errors):
        for name, digest in values["roots"].items():
            length = 40 if name in {"candidate_commit", "candidate_tree"} else 64
            if not isinstance(digest, str) or len(digest) != length or any(c not in "0123456789abcdef" for c in digest):
                errors.append(f"roots.{name} is not a {length}-character hex digest")


def _validate_roots_r16(values: dict[str, Any], errors: list[str]) -> None:
    expected = R16_ROOT_DIGEST_KEYS | {"candidate_provider_id"}
    if not isinstance(values["roots"], dict) or set(values["roots"]) != expected:
        errors.append(f"roots fields differ: expected={sorted(expected)}, actual={sorted(values['roots']) if isinstance(values['roots'], dict) else values['roots']}")
        return
    for name, digest in values["roots"].items():
        if name == "candidate_provider_id":
            if not isinstance(digest, str) or not digest:
                errors.append("roots.candidate_provider_id must be a non-empty string")
            continue
        length = 40 if name in {"candidate_commit", "candidate_tree"} else 64
        if not isinstance(digest, str) or len(digest) != length or any(c not in "0123456789abcdef" for c in digest):
            errors.append(f"roots.{name} is not a {length}-character hex digest")


R17_ROOT_DIGEST_KEYS = R16_ROOT_DIGEST_KEYS | {
    "evaluator_semantic_root",
    "scorer_semantic_root",
    "protocol_root",
}


def _validate_roots_r17(values: dict[str, Any], errors: list[str]) -> None:
    expected = R17_ROOT_DIGEST_KEYS | {"candidate_provider_id"}
    if not isinstance(values["roots"], dict) or set(values["roots"]) != expected:
        errors.append(f"roots fields differ: expected={sorted(expected)}, actual={sorted(values['roots']) if isinstance(values['roots'], dict) else values['roots']}")
        return
    for name, digest in values["roots"].items():
        if name == "candidate_provider_id":
            if not isinstance(digest, str) or not digest:
                errors.append("roots.candidate_provider_id must be a non-empty string")
            continue
        length = 40 if name in {"candidate_commit", "candidate_tree"} else 64
        if not isinstance(digest, str) or len(digest) != length or any(c not in "0123456789abcdef" for c in digest):
            errors.append(f"roots.{name} is not a {length}-character hex digest")


def _validate_phase_apis_r15(values: dict[str, Any], errors: list[str]) -> None:
    phase_apis = values["phase_apis"]
    if _closed(phase_apis, {"construct", "evaluate"}, "phase_apis", errors):
        construct = phase_apis["construct"]
        evaluate = phase_apis["evaluate"]
        api_keys = {"required_state", "terminal_states", "authorization_token", "allowed_artifact_phases"}
        if _closed(construct, api_keys, "phase_apis.construct", errors):
            if construct != R15_CONSTRUCT_POLICY:
                errors.append("phase_apis.construct policy invalid")
        if _closed(evaluate, api_keys, "phase_apis.evaluate", errors):
            if evaluate != R15_EVALUATE_POLICY:
                errors.append("phase_apis.evaluate policy invalid")


def _validate_phase_apis_r16(values: dict[str, Any], errors: list[str]) -> None:
    phase_apis = values["phase_apis"]
    if _closed(phase_apis, {"construct", "evaluate"}, "phase_apis", errors):
        construct = phase_apis["construct"]
        evaluate = phase_apis["evaluate"]
        api_keys = {"required_state", "terminal_states", "authorization_token", "allowed_artifact_phases"}
        if _closed(construct, api_keys, "phase_apis.construct", errors):
            if construct != R16_CONSTRUCT_POLICY:
                errors.append("phase_apis.construct policy invalid")
        if _closed(evaluate, api_keys, "phase_apis.evaluate", errors):
            if evaluate != R16_EVALUATE_POLICY:
                errors.append("phase_apis.evaluate policy invalid")


def _validate_phase_apis_r17(values: dict[str, Any], errors: list[str]) -> None:
    phase_apis = values["phase_apis"]
    if _closed(phase_apis, {"construct", "evaluate"}, "phase_apis", errors):
        construct = phase_apis["construct"]
        evaluate = phase_apis["evaluate"]
        api_keys = {"required_state", "terminal_states", "authorization_token", "allowed_artifact_phases"}
        if _closed(construct, api_keys, "phase_apis.construct", errors):
            if construct != R17_CONSTRUCT_POLICY:
                errors.append("phase_apis.construct policy invalid")
        if _closed(evaluate, api_keys, "phase_apis.evaluate", errors):
            if evaluate != R17_EVALUATE_POLICY:
                errors.append("phase_apis.evaluate policy invalid")


def _validate_phase_apis_r22(values: dict[str, Any], errors: list[str]) -> None:
    phase_apis = values["phase_apis"]
    if _closed(phase_apis, {"construct", "evaluate"}, "phase_apis", errors):
        construct = phase_apis["construct"]
        evaluate = phase_apis["evaluate"]
        api_keys = {"required_state", "terminal_states", "authorization_token", "allowed_artifact_phases"}
        if _closed(construct, api_keys, "phase_apis.construct", errors):
            if construct != T22_CONSTRUCT_POLICY:
                errors.append("phase_apis.construct policy invalid")
        if _closed(evaluate, api_keys, "phase_apis.evaluate", errors):
            if evaluate != T22_EVALUATE_POLICY:
                errors.append("phase_apis.evaluate policy invalid")


def _validate_r14_disposition(values: dict[str, Any], errors: list[str]) -> None:
    if _closed(values["r14_disposition"], {"status", "reason", "construction_attempts", "corpus_materialized", "suites_materialized", "candidate_rows", "official_evaluator_rows", "one_shot_consumed"}, "r14_disposition", errors):
        if values["r14_disposition"]["status"] != "CLOSED / PRECONSTRUCTION_PROTOCOL_INTEGRATION_FAILURE" or values["r14_disposition"]["one_shot_consumed"] is not False:
            errors.append("R14 disposition invalid")


def _validate_r15_disposition(values: dict[str, Any], errors: list[str]) -> None:
    required = {
        "status", "reason", "construction_attempts", "corpus_materialized", "suites_materialized",
        "candidate_rows", "official_evaluator_rows", "one_shot_consumed", "evaluation_permanently_refused",
    }
    if _closed(values["r15_disposition"], required, "r15_disposition", errors):
        disposition = values["r15_disposition"]
        if disposition["status"] != "CLOSED / SEALED_HOLDOUT_RUNTIME_CONTRACT_INCOMPATIBILITY":
            errors.append("R15 disposition status invalid")
        if disposition["reason"] != "SEALED_CORPUS_NOT_LOADABLE_BY_FROZEN_CANDIDATE_RUNTIME":
            errors.append("R15 disposition reason invalid")
        if disposition["construction_attempts"] != 1:
            errors.append("R15 disposition construction_attempts must be 1")
        if disposition["corpus_materialized"] is not True or disposition["suites_materialized"] is not True:
            errors.append("R15 disposition materialization record invalid")
        if disposition["candidate_rows"] != 0 or disposition["official_evaluator_rows"] != 0:
            errors.append("R15 disposition must record zero candidate/evaluator rows")
        if disposition["one_shot_consumed"] is not False:
            errors.append("R15 disposition one_shot_consumed must be false")
        if disposition["evaluation_permanently_refused"] is not True:
            errors.append("R15 disposition must record the permanent evaluation refusal")


def _validate_runtime_native(
    values: dict[str, Any],
    errors: list[str],
    candidate_provider: str | None = None,
) -> None:
    if not _closed(values["runtime_native"], RUNTIME_NATIVE_KEYS, "runtime_native", errors):
        return
    runtime_native = values["runtime_native"]
    if runtime_native["corpus_format"] != "mango-general-knowledge-corpus-v1":
        errors.append("runtime_native.corpus_format invalid")
    if runtime_native["loader_entry"] != "src/sciencemath/knowledge/corpus.py:load_corpus":
        errors.append("runtime_native.loader_entry invalid")
    if runtime_native["runtime_materializer"] != "t21_protocol.providers:runtime-native-materializer":
        errors.append("runtime_native.runtime_materializer invalid")
    if candidate_provider is not None:
        expected_provider = candidate_provider
    else:
        expected_provider = (
            "t21_protocol.providers_r17:RealCandidateProviderEvidence"
            if "metric_semantics" in values
            else "t21_protocol.providers:RealCandidateProvider"
        )
    if runtime_native["candidate_provider"] != expected_provider:
        errors.append("runtime_native.candidate_provider invalid")
    if runtime_native["source_id_grammar"] != "gk-<sha1(title|publisher|revision)[:12]>":
        errors.append("runtime_native.source_id_grammar invalid")
    if runtime_native["manifest_format"] != "runtime_build_corpus_files":
        errors.append("runtime_native.manifest_format invalid")
    if runtime_native["shadow_holdout_rows"] != values["suite_total"]:
        errors.append("runtime_native.shadow_holdout_rows must equal the suite total")
    if runtime_native["holdout_frozen_schema_version"] != "t21-holdout-frozen-v2":
        errors.append("runtime_native.holdout_frozen_schema_version invalid")


def _validate_r16_disposition(values: dict[str, Any], errors: list[str]) -> None:
    required = {
        "status", "reason", "construction_attempts", "rows_scored", "one_shot_consumed",
        "holdout_status", "evaluation_permanently_refused", "capability_verdict",
        "invalid_metric_count", "invalid_metrics", "invalid_metric_designation",
        "retroactive_capability_declaration", "rerun",
    }
    if not _closed(values["r16_disposition"], required, "r16_disposition", errors):
        return
    disposition = values["r16_disposition"]
    if disposition["status"] != "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE":
        errors.append("R16 disposition status invalid")
    if disposition["reason"] != "OFFICIAL_RUN_COMPLETED_BUT_TWO_FROZEN_FLOOR_METRICS_DID_NOT_SEMANTICALLY_MEASURE_THEIR_REGISTERED_QUANTITIES":
        errors.append("R16 disposition reason invalid")
    if disposition["construction_attempts"] != 1:
        errors.append("R16 disposition construction_attempts must be 1")
    if disposition["rows_scored"] != 4800:
        errors.append("R16 disposition rows_scored must be 4800")
    if disposition["one_shot_consumed"] is not True:
        errors.append("R16 disposition one_shot_consumed must be true")
    if disposition["holdout_status"] != "PERMANENTLY_EXPOSED_CONSUMED":
        errors.append("R16 disposition holdout_status invalid")
    if disposition["evaluation_permanently_refused"] is not True:
        errors.append("R16 disposition must record the permanent evaluation refusal")
    if disposition["capability_verdict"] != "NONE":
        errors.append("R16 disposition capability verdict must be NONE")
    if set(disposition["invalid_metrics"]) != {"conflict_false_resolution", "static_query_unnecessary_web_routing"}:
        errors.append("R16 disposition invalid_metrics set invalid")
    if disposition["invalid_metric_count"] != 2:
        errors.append("R16 disposition invalid_metric_count must be 2")
    if disposition["invalid_metric_designation"] != "SEMANTICALLY_INVALID_FOR_CAPABILITY_ADJUDICATION":
        errors.append("R16 disposition invalid metric designation invalid")
    if disposition["retroactive_capability_declaration"] != "FORBIDDEN":
        errors.append("R16 disposition forbids retroactive capability declaration")
    if disposition["rerun"] != "REFUSED":
        errors.append("R16 disposition rerun must be REFUSED")


def _validate_r17_disposition(values: dict[str, Any], errors: list[str]) -> None:
    required = {
        "status", "reason", "construction_attempts", "rows_scored", "one_shot_consumed",
        "holdout_status", "evaluation_completed", "capability_verdict",
        "failed_metric_count", "failed_metrics", "failed_metric_designation",
        "retroactive_capability_declaration", "rerun", "adjudication", "evaluation_commit",
    }
    if not _closed(values["r17_disposition"], required, "r17_disposition", errors):
        return
    disposition = values["r17_disposition"]
    if disposition["status"] != "CLOSED / VALID_CAPABILITY_FAILURE":
        errors.append("R17 disposition status invalid")
    if disposition["reason"] != "TWO_TEMPORAL_FLOOR_METRICS_MEASURED_A_CANDIDATE_FAILURE_WITHOUT_CANDIDATE_VISIBLE_SIGNALS":
        errors.append("R17 disposition reason invalid")
    if disposition["construction_attempts"] != 1:
        errors.append("R17 disposition construction_attempts must be 1")
    if disposition["rows_scored"] != 4800:
        errors.append("R17 disposition rows_scored must be 4800")
    if disposition["one_shot_consumed"] is not True:
        errors.append("R17 disposition one_shot_consumed must be true")
    if disposition["holdout_status"] != "PERMANENTLY_EXPOSED_CONSUMED":
        errors.append("R17 disposition holdout_status invalid")
    if disposition["evaluation_completed"] is not True:
        errors.append("R17 disposition must record the completed official evaluation")
    if disposition["capability_verdict"] != "FAIL":
        errors.append("R17 disposition capability verdict must be FAIL")
    if set(disposition["failed_metrics"]) != {
        "explicit_current_routing_accuracy", "stale_snapshot_false_current_answers",
    }:
        errors.append("R17 disposition failed_metrics set invalid")
    if disposition["failed_metric_count"] != 2:
        errors.append("R17 disposition failed_metric_count must be 2")
    if disposition["failed_metric_designation"] != "VALID_MEASUREMENTS_OF_CANDIDATE_CAPABILITY_FAILURE":
        errors.append("R17 disposition failed metric designation invalid")
    if disposition["retroactive_capability_declaration"] != "FORBIDDEN":
        errors.append("R17 disposition forbids retroactive capability declaration")
    if disposition["rerun"] != "REFUSED":
        errors.append("R17 disposition rerun must be REFUSED")
    if disposition["adjudication"] != "T21R17_FINAL_ADJUDICATION_VALID_CAPABILITY_FAILURE":
        errors.append("R17 disposition must record the final adjudication")
    if not isinstance(disposition["evaluation_commit"], str) or len(
            disposition["evaluation_commit"]) != 40:
        errors.append("R17 disposition evaluation_commit must be a full commit sha")


def _validate_metric_semantics_block(values: dict[str, Any], errors: list[str]) -> None:
    block = values["metric_semantics"]
    required = {
        "rule", "generic_fallback_consumers", "unknown_metric_behavior",
        "semantics_artifact", "implementation_registry_artifact", "metric_count",
    }
    if not _closed(block, required, "metric_semantics", errors):
        return
    if block["generic_fallback_consumers"] != 0:
        errors.append("metric_semantics.generic_fallback_consumers must be 0")
    if block["unknown_metric_behavior"] != "SCORER_CONFIGURATION_ERROR":
        errors.append("metric_semantics.unknown_metric_behavior must fail closed")
    if block["metric_count"] != 32:
        errors.append("metric_semantics.metric_count must be 32")
    registered_artifacts = {
        "semantics_artifact": "official_metric_semantics",
        "implementation_registry_artifact": "metric_implementation_registry",
    }
    for key, artifact_key in registered_artifacts.items():
        if block[key] != values["artifacts"].get(artifact_key):
            errors.append(f"metric_semantics.{key} must reference the registered artifact path")


def _report(errors: list[str], untyped: int, consumers: int, disagreements: int, unknown: int) -> dict[str, Any]:
    return {
        "status": "PASS" if not errors else "FAIL",
        "untyped_fields": untyped,
        "unknown_fields": unknown,
        "unknown_consumers": consumers,
        "type_disagreements": disagreements,
        "errors": errors,
    }


@dataclass(frozen=True)
class Contract:
    path: Path
    document: dict[str, Any]

    @property
    def values(self) -> dict[str, Any]:
        return self.document["values"]

    @property
    def hash(self) -> str:
        return sha256_json(self.document)

    @property
    def experiment(self) -> str:
        return self.document["experiment"]

    def get(self, dotted: str) -> Any:
        prefix = dotted if dotted.startswith("values.") else f"values.{dotted}"
        return value_at_path(self.document, prefix)


def load_contract(path: Path) -> Contract:
    document = read_json(path)
    if not isinstance(document, dict):
        raise ContractError("master contract must be a JSON object")
    validate_master_contract(document)
    return Contract(path=path.resolve(), document=document)
