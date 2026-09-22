#!/usr/bin/env python3
"""T22 — metric-semantics carry + implementation-registry transform (§30/§31).

Carries the frozen T21R17 measurement semantics into T22 with ONLY:

1. the T22 identity fields (artifact / experiment),
2. the top-level lineage note recording the carry, and
3. the two prose claims superseded by the frozen zero-denominator
   resolution (evaluations/t22/zero_denominator_policy_resolution.json,
   rules 3 and 4).

Every other byte of the semantics document — all 32 metric entries with
their operators, thresholds, directions, ranges, populations, aggregation
semantics, and zero-denominator policy classes, plus the predicates and
status vocabularies — is asserted byte-identical to R17.  The floor hash
must remain the frozen 4656be72....  The implementation registry is
carried with identical implementation_sha256 values, each recomputed
against the live scorer module's AST segments, proving the T22 measuring
stick is the unchanged R17 scorer.
"""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from t21_protocol.metric_semantics import (  # noqa: E402
    SEMANTICS_ARTIFACT,
    SEMANTICS_EXPERIMENT,
    validate_metric_semantics,
)
from t21_protocol.scorer_r17 import IMPLEMENTATION_SOURCES, SCORER_ID  # noqa: E402
from t21_protocol.util import sha256_file, sha256_json  # noqa: E402

FLOOR_HASH = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"
R17_SEMANTICS = ROOT / "evaluations" / "t21r17" / "official_metric_semantics.json"
R17_REGISTRY = ROOT / "evaluations" / "t21r17" / "metric_implementation_registry.json"
R16_CONTRACT = ROOT / "evaluations" / "t21r16" / "t21_master_contract.json"
T22_SEMANTICS = ROOT / "evaluations" / "t22" / "official_metric_semantics.json"
T22_REGISTRY = ROOT / "evaluations" / "t22" / "metric_implementation_registry.json"

T22_ARTIFACT = "T22_OFFICIAL_METRIC_SEMANTICS"
T22_EXPERIMENT = "t22"
T22_REGISTRY_ARTIFACT = "T22_METRIC_IMPLEMENTATION_REGISTRY"
SCORER_MODULE = "t21_protocol/scorer_r17.py"

RESOLUTION = "evaluations/t22/zero_denominator_policy_resolution.json"

HARMONIZED_CAPABILITY_GUARD = (
    "SUPERSEDED by the frozen T22 zero-denominator resolution "
    "(DESIGN_MANDATED_POSITIVE_POPULATIONS_WITH_RESIDUAL_EMERGENT_CONVENTION, "
    f"{RESOLUTION}, prospective-only): design-mandated populations must be "
    "positive and an empty design-mandated population fails closed "
    "(ScorerConfigurationError); emergent behavioral populations apply this "
    "preregistered convention on emptiness - observed = convention, floor "
    "pass=true with zero_denominator_policy_applied=true and population "
    "counts recorded in the official floor evidence. The earlier claim that "
    "every higher-is-better metric using this convention fails its floor on "
    "an empty population no longer binds."
)

HARMONIZED_CONFLICT_NOTES = (
    "The R16-invalid generic derivation (overall accuracy) is replaced by "
    "this named quantity. SUPERSEDED by the frozen T22 zero-denominator "
    f"resolution (rule_3_superseded_prose, {RESOLUTION}): on an empty "
    "eligible-conflict population the preregistered convention applies - "
    "observed 0.0 with pass=true, zero_denominator_policy_applied=true, and "
    "population counts 0/0 recorded in the official floor evidence; the "
    "design-mandated conflict_detection population fails closed on the same "
    "emptiness, so a design violation remains visible to adjudication."
)

T22_LINEAGE_NOTE_SUFFIX = (
    " T22 carry: this frozen semantics is carried into T22 unchanged "
    "(the candidate changes, the measuring stick does not - T22 "
    "preconstruction plan section 30); the only edits are the two prose "
    "claims superseded by the frozen T22 zero-denominator resolution."
)

# The exact R17 paths the carry may edit, with the exact old values that
# must be present before patching (guards against silent drift).
WHITELIST = {
    "artifact": "T21R17_OFFICIAL_METRIC_SEMANTICS",
    "experiment": "t21r17",
    ("lineage", "notes"): None,  # old value verified from the loaded doc
    ("zero_denominator_conventions", "PREREGISTERED_CONVENTION_0.0",
     "capability_guard"): None,
    ("metrics", "conflict_false_resolution", "lineage", "notes"): None,
}

NEW_VALUES = {
    "artifact": T22_ARTIFACT,
    "experiment": T22_EXPERIMENT,
    ("lineage", "notes"): T22_LINEAGE_NOTE_SUFFIX,  # appended
    ("zero_denominator_conventions", "PREREGISTERED_CONVENTION_0.0",
     "capability_guard"): HARMONIZED_CAPABILITY_GUARD,
    ("metrics", "conflict_false_resolution", "lineage", "notes"):
        HARMONIZED_CONFLICT_NOTES,
}


def _diff_paths(old, new, prefix=()):
    """Leaf paths where old differs from new."""
    if isinstance(old, dict) and isinstance(new, dict):
        diffs = []
        for key in sorted(set(old) | set(new)):
            if key not in old or key not in new:
                diffs.append(prefix + (key,))
            else:
                diffs.extend(_diff_paths(old[key], new[key],
                                         prefix + (key,)))
        return diffs
    if old != new:
        return [prefix]
    return []


def _floors() -> dict:
    contract = json.loads(R16_CONTRACT.read_text(encoding="utf-8"))
    floors = contract["values"]["promotion_floors"]
    if sha256_json(floors) != FLOOR_HASH:
        raise SystemExit("frozen floor hash mismatch: promotion floors are "
                         "not the frozen 32-floor set")
    return floors


def build_semantics_carry() -> tuple[dict, dict, dict]:
    """Build and fully verify the T22 semantics + registry carry."""
    r17_semantics = json.loads(R17_SEMANTICS.read_text(encoding="utf-8"))
    floors = _floors()

    # The source must be the frozen R17 artifact.
    if r17_semantics["artifact"] != SEMANTICS_ARTIFACT or \
            r17_semantics["experiment"] != SEMANTICS_EXPERIMENT:
        raise SystemExit("R17 semantics artifact identity mismatch")
    if r17_semantics["floor_hash"] != FLOOR_HASH:
        raise SystemExit("R17 semantics floor hash is not the frozen "
                         "4656be72 root")
    # The R17 document still validates under the frozen defaults.
    if validate_metric_semantics(copy.deepcopy(r17_semantics), floors)[
            "status"] != "PASS":
        raise SystemExit("the frozen R17 semantics must still validate "
                         "under unchanged defaults")

    t22 = copy.deepcopy(r17_semantics)
    t22["artifact"] = T22_ARTIFACT
    t22["experiment"] = T22_EXPERIMENT
    t22["lineage"]["notes"] = (
        r17_semantics["lineage"]["notes"] + T22_LINEAGE_NOTE_SUFFIX)
    t22["zero_denominator_conventions"]["PREREGISTERED_CONVENTION_0.0"][
        "capability_guard"] = HARMONIZED_CAPABILITY_GUARD
    t22["metrics"]["conflict_false_resolution"]["lineage"]["notes"] = \
        HARMONIZED_CONFLICT_NOTES

    # Exact-diff proof: only the whitelisted leaves differ, each old leaf
    # carried the recorded R17 prose, and each new leaf is the frozen
    # harmonized text.
    diff_paths = {".".join(p): p for p in
                  _diff_paths(r17_semantics, t22)}
    expected_paths = {"artifact", "experiment", "lineage.notes",
                      "zero_denominator_conventions."
                      "PREREGISTERED_CONVENTION_0.0.capability_guard",
                      "metrics.conflict_false_resolution.lineage.notes"}
    if set(diff_paths) != expected_paths:
        raise SystemExit(
            "semantics carry diff exceeds the frozen whitelist: "
            f"unexpected={sorted(set(diff_paths) - expected_paths)} "
            f"missing={sorted(expected_paths - set(diff_paths))}")
    old_values = {
        "artifact": r17_semantics["artifact"],
        "experiment": r17_semantics["experiment"],
        "lineage.notes": r17_semantics["lineage"]["notes"],
        "zero_denominator_conventions."
        "PREREGISTERED_CONVENTION_0.0.capability_guard":
            r17_semantics["zero_denominator_conventions"][
                "PREREGISTERED_CONVENTION_0.0"]["capability_guard"],
        "metrics.conflict_false_resolution.lineage.notes":
            r17_semantics["metrics"]["conflict_false_resolution"][
                "lineage"]["notes"],
    }
    if old_values["zero_denominator_conventions."
                  "PREREGISTERED_CONVENTION_0.0.capability_guard"] != \
            "a vacuous 0.0 on an empty population can never fabricate a " \
            "capability pass: every higher-is-better metric using this " \
            "convention fails its floor, and conflict_false_resolution's " \
            "vacuous pass cannot coexist with a passing conflict_detection " \
            "because both share the same population":
        raise SystemExit("the R17 capability_guard prose drifted from the "
                         "adjudication record; refusing to patch blind")
    if "cannot fabricate a capability pass" not in \
            old_values["metrics.conflict_false_resolution.lineage.notes"]:
        raise SystemExit("the R17 conflict lineage notes drifted from the "
                         "adjudication record; refusing to patch blind")
    new_values = {
        "lineage.notes": t22["lineage"]["notes"],
        "zero_denominator_conventions."
        "PREREGISTERED_CONVENTION_0.0.capability_guard":
            t22["zero_denominator_conventions"][
                "PREREGISTERED_CONVENTION_0.0"]["capability_guard"],
        "metrics.conflict_false_resolution.lineage.notes":
            t22["metrics"]["conflict_false_resolution"]["lineage"]["notes"],
    }
    if new_values["zero_denominator_conventions."
                  "PREREGISTERED_CONVENTION_0.0.capability_guard"] != \
            HARMONIZED_CAPABILITY_GUARD or \
            new_values["metrics.conflict_false_resolution.lineage.notes"] != \
            HARMONIZED_CONFLICT_NOTES:
        raise SystemExit("harmonized prose constants mismatch")

    # Structural validation under the parameterized T22 identity.
    report = validate_metric_semantics(copy.deepcopy(t22), floors,
                                       artifact=T22_ARTIFACT,
                                       experiment=T22_EXPERIMENT)
    if report["status"] != "PASS":
        raise SystemExit(f"T22 semantics validation failed: "
                         f"{report['errors']}")

    # Per-metric numeric identity proof (verification requirement 2).
    differing_metrics = [
        metric for metric in r17_semantics["metrics"]
        if r17_semantics["metrics"][metric] != t22["metrics"][metric]
    ]
    if differing_metrics != ["conflict_false_resolution"]:
        raise SystemExit(
            "only conflict_false_resolution's lineage notes may differ; "
            f"differing={differing_metrics}")
    policy_classes_identical = all(
        r17_semantics["metrics"][m]["zero_denominator_policy"] ==
        t22["metrics"][m]["zero_denominator_policy"]
        for m in r17_semantics["metrics"])
    if not policy_classes_identical:
        raise SystemExit("zero-denominator policy classes must be carried "
                         "unchanged (rule_4_t22_boundedness)")

    # ---------------- implementation registry ----------------------------
    r17_registry = json.loads(R17_REGISTRY.read_text(encoding="utf-8"))
    scorer_path = ROOT / SCORER_MODULE
    live_module_sha = sha256_file(scorer_path)
    if live_module_sha != r17_registry["scorer_module_sha256"]:
        raise SystemExit(
            "the live scorer module bytes differ from the frozen R17 "
            "registry binding; the measuring stick changed without "
            "authorization")
    source = scorer_path.read_text(encoding="utf-8")
    segments = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef)
    }
    mismatches = []
    for metric_id, entry in r17_registry["implementations"].items():
        function_name = IMPLEMENTATION_SOURCES[metric_id]
        recomputed = sha256_json({"source": segments[function_name]})
        if recomputed != entry["implementation_sha256"]:
            mismatches.append(metric_id)
        if entry["callable"] != f"t21_protocol.scorer_r17:IMPLEMENTATIONS[{metric_id!r}]":
            mismatches.append(f"{metric_id}:callable")
    if mismatches:
        raise SystemExit(f"implementation registry no longer binds the "
                         f"live scorer: {mismatches}")

    t22_registry = copy.deepcopy(r17_registry)
    t22_registry["artifact"] = T22_REGISTRY_ARTIFACT
    t22_registry["experiment"] = T22_EXPERIMENT
    registry_diff = {".".join(p) for p in
                     _diff_paths(r17_registry, t22_registry)}
    if registry_diff != {"artifact", "experiment"}:
        raise SystemExit(f"registry carry diff exceeds the whitelist: "
                         f"{sorted(registry_diff)}")

    carry_report = {
        "schema_version": "t22-semantics-carry-report-v1",
        "artifact": "T22_SEMANTICS_CARRY_REPORT",
        "experiment": "t22",
        "rule": "the measuring stick does not change (plan section 30); the "
                "zero-denominator prose is harmonized per plan section 31 "
                "and the frozen resolution",
        "source_artifact": "T21R17_OFFICIAL_METRIC_SEMANTICS",
        "floor_hash": FLOOR_HASH,
        "floor_hash_unchanged": True,
        "metric_count": len(t22["metrics"]),
        "metrics_byte_identical_except": ["conflict_false_resolution"
                                          ".lineage.notes (harmonized)"],
        "harmonized_paths": sorted(expected_paths),
        "prospective_only": True,
        "retroactive_effect_on_r17": "NONE (R17 remains CLOSED/"
                                     "VALID_CAPABILITY_FAILURE)",
        "scorer": SCORER_ID,
        "scorer_module": SCORER_MODULE,
        "scorer_module_sha256": live_module_sha,
        "implementation_sha256_recomputed": len(
            r17_registry["implementations"]),
        "implementation_sha256_mismatches": [],
        "registry_byte_identical_except": [],
        "semantics_validation": "PASS",
    }
    return t22, t22_registry, carry_report


def main() -> int:
    t22_semantics, t22_registry, carry_report = build_semantics_carry()
    T22_SEMANTICS.write_text(json.dumps(t22_semantics, indent=2) + "\n",
                             encoding="utf-8")
    T22_REGISTRY.write_text(json.dumps(t22_registry, indent=2) + "\n",
                            encoding="utf-8")
    provenance = T22_SEMANTICS.parent / "semantics_carry_report.json"
    provenance.write_text(json.dumps(carry_report, indent=2) + "\n",
                          encoding="utf-8")
    print(f"T22 semantics carry: {len(t22_semantics['metrics'])} metrics "
          f"carried byte-identical (except the harmonized conflict "
          f"lineage note); floor_hash unchanged {carry_report['floor_hash'][:8]}")
    print(f"T22 registry carry: "
          f"{carry_report['implementation_sha256_recomputed']} "
          f"implementation_sha256 values recomputed against the live "
          f"scorer, 0 mismatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())