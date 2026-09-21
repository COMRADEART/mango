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

    if document["schema_version"] != "t21-master-contract-v1":
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

    errors.extend(_validate_semantics(document["values"]))

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


def _validate_semantics(values: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_fields = {
        "identity", "roots", "artifacts", "suites", "suite_total", "domain_taxonomy",
        "crossdomain_pairs", "exact_design", "historical_exclusions", "remediation_exclusions",
        "promotion_floors", "one_shot", "state_machine", "author", "r14_disposition",
        "real_r15_paths", "quarantine",
    }
    if set(values) != expected_fields:
        errors.append(f"values fields differ: expected={sorted(expected_fields)}, actual={sorted(values)}")
        return errors
    if _closed(values["identity"], {"namespace", "case_id_prefix"}, "identity", errors):
        if not values["identity"]["namespace"] or not values["identity"]["case_id_prefix"]:
            errors.append("identity values must be non-empty")
    if _closed(values["roots"], {"candidate_commit", "candidate_tree", "runtime_root", "evaluator_root", "floor_hash"}, "roots", errors):
        for name, digest in values["roots"].items():
            length = 40 if name in {"candidate_commit", "candidate_tree"} else 64
            if not isinstance(digest, str) or len(digest) != length or any(c not in "0123456789abcdef" for c in digest):
                errors.append(f"roots.{name} is not a {length}-character hex digest")
    if _closed(values["artifacts"], {"experiment_config", "artifact_graph", "domain_taxonomy", "historical_exclusion", "remediation_exclusion", "runtime_freeze", "evaluator_freeze", "qualification_lock", "negative_controls", "adjudication", "applicability", "holdout_frozen_schema"}, "artifacts", errors):
        if any(not isinstance(path, str) or not path.startswith("evaluations/t21r15/") for path in values["artifacts"].values()):
            errors.append("artifact paths must be R15 repository-relative paths")
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
    if _closed(values["r14_disposition"], {"status", "reason", "construction_attempts", "corpus_materialized", "suites_materialized", "candidate_rows", "official_evaluator_rows", "one_shot_consumed"}, "r14_disposition", errors):
        if values["r14_disposition"]["status"] != "CLOSED / PRECONSTRUCTION_PROTOCOL_INTEGRATION_FAILURE" or values["r14_disposition"]["one_shot_consumed"] is not False:
            errors.append("R14 disposition invalid")
    for name in ("historical_exclusions", "remediation_exclusions", "quarantine"):
        if not isinstance(values[name], dict) or not values[name]:
            errors.append(f"{name} must be a non-empty object")
    if not isinstance(values["real_r15_paths"], list) or not values["real_r15_paths"]:
        errors.append("real_r15_paths must be a non-empty array")
    return errors


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
