"""T26 full historical exclusion model: frozen nine-dimensional hash-only engine.

Every real T26 blind scenario is fingerprinted across all nine established
exclusion dimensions and must have zero overlap with every registered
historical source. Unknown or missing dimensions fail closed. A dimension that
is structurally absent for a scenario class is recorded explicitly as
``applicable = false, population = 0`` - never silently omitted.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from t21_protocol.util import sha256_json

SCHEMA = "t26-historical-exclusions-v1"
ARTIFACT = "T26_HISTORICAL_EXCLUSIONS"

# The established nine-dimensional exclusion model (T24/T25 lineage).
DIMENSIONS = (
    "case_ids",
    "entity_identities",
    "source_ids",
    "chunk_ids",
    "exact_queries",
    "exact_answers",
    "exact_source_text",
    "verbatim_attack_wording",
    "relations",
)

# Sources covered by the historical exclusion model (authorization section 12).
REQUIRED_SOURCES = (
    "t21_historical_milestones",
    "t22_protected",
    "t23_exposed",
    "t24_sealed_evaluated",
    "t25_sealed_evaluated_public",
    "t26_public_qualification",
    "t26_disposable_rehearsals",
    "t26_native_smoke_fixtures",
)

T25_EXCLUSION_REGISTRY = "evaluations/t25/t25_exclusion_sources.json"
T26_QUALIFICATION_EXCLUSIONS = "evaluations/t26/qualification_exclusions.json"
T26_REHEARSAL_FINGERPRINTS = "evaluations/t26/rehearsal_exclusion_fingerprints.json"

HEX64 = "0123456789abcdef"


def fingerprint(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("exclusion fingerprints apply to string values only")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_hex64(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in HEX64 for char in value))


def _dimension_state(fingerprints: Iterable[str], *, applicable: bool) -> dict[str, Any]:
    values = sorted(set(fingerprints))
    for value in values:
        if not _is_hex64(value):
            raise ValueError("exclusion dimension carries a non-SHA-256 fingerprint")
    return {"applicable": bool(applicable),
            "population": len(values) if applicable else 0,
            "fingerprints": values if applicable else []}


def _load_json(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise ValueError(f"historical exclusion source missing: {relative}")
    return json.loads(path.read_text(encoding="utf-8"))


def t26_qualification_fingerprints(root: Path) -> dict[str, list[str]]:
    """Hash-only fingerprints of the permanently excluded public qualification."""
    document = _load_json(root, T26_QUALIFICATION_EXCLUSIONS)
    if (document.get("artifact") != "T26_QUALIFICATION_EXCLUSIONS"
            or document.get("permanently_excluded_from_real_t26") is not True
            or document.get("raw_content_included") is not False):
        raise ValueError("T26 qualification exclusion registry invalid")
    return {"case_ids": list(document["case_id_sha256"]),
            "exact_queries": list(document["router_query_sha256"]),
            "exact_answers": list(document["goal_sha256"])}


def native_smoke_fingerprints(root: Path) -> dict[str, list[str]]:
    """Hash-only fingerprints of the public T26 native smoke fixture."""
    from .native_smoke import native_case
    from .qualification import exclusion_fingerprints

    scenario, _gold = native_case()
    document = exclusion_fingerprints([scenario])
    return {"case_ids": list(document["case_id_sha256"]),
            "exact_queries": list(document["router_query_sha256"]),
            "exact_answers": list(document["goal_sha256"])}


def rehearsal_fingerprints_document(root: Path) -> dict[str, Any]:
    path = root / T26_REHEARSAL_FINGERPRINTS
    if not path.is_file():
        raise ValueError("T26 construction rehearsal exclusion fingerprints absent")
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("artifact") != "T26_CONSTRUCTION_REHEARSAL_EXCLUSION_FINGERPRINTS"
            or document.get("raw_content_included") is not False
            or document.get("material") != "DISPOSABLE_SYNTHETIC_PRIVATE"):
        raise ValueError("T26 rehearsal exclusion fingerprint document invalid")
    return document


def rehearsal_registration(cases: list[dict], gold: list[dict],
                           fixtures: list[dict]) -> dict[str, list[str]]:
    """Hash-only registration of a disposable synthetic construction rehearsal."""
    return observed_bundle_fingerprints(cases, gold, fixtures)


def build_historical_exclusion_document(
        root: Path, *, rehearsal_registrations: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """Assemble the nine-dimensional forbidden sets from every public source.

    T25 private material is intentionally NOT opened here; it is excluded by
    the separate hash-bound private overlap oracle at construction time.
    """
    from t25_protocol.exclusions import load_exclusion_sources

    root = Path(root)
    registry = _load_json(root, T25_EXCLUSION_REGISTRY)
    inherited = load_exclusion_sources(root, registry)
    qualification = t26_qualification_fingerprints(root)
    native = native_smoke_fingerprints(root)
    rehearsal_document = rehearsal_fingerprints_document(root)
    rehearsal = {name: list(rehearsal_document["dimensions"][name]["fingerprints"])
                 for name in DIMENSIONS if name in rehearsal_document["dimensions"]}
    merged: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    for name in DIMENSIONS:
        merged[name].extend(inherited.get(name, ()))
    for name, values in qualification.items():
        merged[name].extend(values)
    for name, values in native.items():
        merged[name].extend(values)
    for name, values in rehearsal.items():
        merged[name].extend(values)
    if rehearsal_registrations:
        for name, values in rehearsal_registrations.items():
            if name not in DIMENSIONS:
                raise ValueError("unknown rehearsal registration dimension")
            merged[name].extend(values)
    sources_present = {name: len(inherited.get(name, ())) for name in DIMENSIONS}
    dimensions = {}
    for name in DIMENSIONS:
        # A dimension is applicable when the historical corpus structurally
        # produces fingerprints for it; applicability follows from population.
        dimensions[name] = _dimension_state(merged[name],
                                            applicable=bool(merged[name]))
    registry_sha = hashlib.sha256((root / T25_EXCLUSION_REGISTRY)
                                  .read_bytes()).hexdigest()
    qualification_sha = hashlib.sha256((root / T26_QUALIFICATION_EXCLUSIONS)
                                       .read_bytes()).hexdigest()
    rehearsal_sha = hashlib.sha256((root / T26_REHEARSAL_FINGERPRINTS)
                                   .read_bytes()).hexdigest()
    core = {
        "schema_version": SCHEMA, "artifact": ARTIFACT, "experiment": "t26",
        "raw_values_included": False,
        "sources": {name: {"covered": True} for name in REQUIRED_SOURCES},
        "source_registry_sha256": registry_sha,
        "qualification_exclusions_sha256": qualification_sha,
        "rehearsal_fingerprints_sha256": rehearsal_sha,
        "inherited_population": sources_present,
        "t25_private_rows_opened": 0,
        "dimensions": dimensions,
    }
    core["exclusion_root"] = sha256_json({key: value for key, value in core.items()
                                          if key != "exclusion_root"})
    return core


def observed_bundle_fingerprints(cases: list[dict], gold: list[dict],
                                 fixtures: list[dict]) -> dict[str, list[str]]:
    """Observed nine-dimension fingerprints for a prospective private bundle."""
    observed: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    adversarial_families = {"adversarial_instruction_isolation"}
    for scenario in cases:
        observed["case_ids"].append(fingerprint(scenario["scenario_id"]))
        observed["exact_queries"].extend(
            fingerprint(step["router_input"]["query"])
            for step in scenario["plan"]["steps"])
        if scenario["family"] in adversarial_families:
            observed["verbatim_attack_wording"].extend(
                fingerprint(step["router_input"]["query"])
                for step in scenario["plan"]["steps"])
    for key in gold:
        observed["exact_answers"].append(fingerprint(json.dumps(
            {k: v for k, v in key.items() if k != "scenario_id"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True)))
    for fixture in fixtures:
        for entity in fixture.get("entity_identities", ()):
            observed["entity_identities"].append(fingerprint(entity))
        for source_id in fixture.get("source_ids", ()):
            observed["source_ids"].append(fingerprint(source_id))
        for chunk_id in fixture.get("chunk_ids", ()):
            observed["chunk_ids"].append(fingerprint(chunk_id))
        for text in fixture.get("exact_source_text", ()):
            observed["exact_source_text"].append(fingerprint(text))
        for relation in fixture.get("relations", ()):
            observed["relations"].append(fingerprint(
                json.dumps(relation, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)))
    return observed


def audit_nine_dimensions(observed: dict[str, list[str]],
                          historical: dict[str, Any]) -> dict[str, Any]:
    """Zero-overlap proof across all nine dimensions; unknown dimensions fail closed."""
    if (not isinstance(historical, dict)
            or historical.get("schema_version") != SCHEMA
            or historical.get("artifact") != ARTIFACT):
        raise ValueError("historical exclusion document invalid (unknown or missing)")
    if set(observed) != set(DIMENSIONS):
        raise ValueError("observed exclusion dimension set mismatch")
    forbidden = historical["dimensions"]
    if set(forbidden) != set(DIMENSIONS):
        raise ValueError("historical exclusion dimension set mismatch")
    from collections import Counter

    results: dict[str, dict[str, Any]] = {}
    overlaps = 0
    for name in DIMENSIONS:
        entries = observed[name]
        population = len(entries)
        duplicates = sum(count - 1 for count in Counter(entries).values() if count > 1)
        if population:
            overlap = len(set(entries) & set(forbidden[name]["fingerprints"]))
            results[name] = {"applicable": True, "population": population,
                             "overlap_count": overlap, "duplicate_count": duplicates}
        else:
            # Structurally absent for this scenario class: recorded explicitly.
            results[name] = {"applicable": False, "population": 0,
                             "overlap_count": 0, "duplicate_count": 0}
        overlaps += results[name]["overlap_count"] + results[name]["duplicate_count"]
    if overlaps:
        raise ValueError("T26 nine-dimension exclusion overlap detected: "
                         f"{overlaps} forbidden collisions")
    return {"schema_version": "t26-nine-dimension-exclusion-audit-v1",
            "artifact": "T26_NINE_DIMENSION_EXCLUSION_AUDIT", "experiment": "t26",
            "status": "PASS" if overlaps == 0 else "FAIL",
            "overlap_count": overlaps,
            "historical_exclusion_root": historical["exclusion_root"],
            "dimensions": results}
