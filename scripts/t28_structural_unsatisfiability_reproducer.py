"""Reproduce the T27-era structural historical-exclusion impossibility for T28.

Public-only, deterministic.  Reconstructs the pre-remediation (T27 V4-era)
generated-public structural fingerprint aggregates from the public
generators, derives the hash sets the frozen T28 construction contract would
force every contract-complete 512-package to contain, and proves the old
semantics made the required zero-overlap condition unsatisfiable
(minimum >= 33).  It then shows the inherited remediated policy removes the
forcing for T28's own generated-public sources (structural overlap 0) and
defers overall satisfiability to the witness artifact.  Never touches T27
private material, the sealed T27 oracle, the T28 construction ledger, or any
one-shot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from sciencemath.executive.skills import SKILL_IDS  # noqa: E402
from sciencemath.integrated.runner import validate_plan  # noqa: E402
from t21_protocol.util import sha256_json  # noqa: E402
from t28_protocol.construction import (  # noqa: E402
    fingerprint_sets, synthetic_private_bundle)
from t28_protocol.contract import FAMILIES  # noqa: E402
from t28_protocol.exclusion import (  # noqa: E402
    DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA, GENERATED_PUBLIC_SOURCES,
    SUPERSEDED_INDEX_ROOT, _t28_generated_fingerprints,
    build_authenticated_public_historical_index,
    generated_public_dimension_policy)
from t28_protocol.qualification import _scenario  # noqa: E402

STRUCTURAL_DIMENSIONS = (
    "entity_identities", "source_ids", "verbatim_attack_wording", "relations")
NON_FORCED_DIMENSIONS = tuple(
    name for name in DIMENSIONS if name not in STRUCTURAL_DIMENSIONS)
FROZEN_FALLBACK_CONDITION = {"on_failure": "SAFE_ABSTAIN",
                             "on_insufficient_evidence": "INSUFFICIENT_EVIDENCE"}


def _t27_generated_structural_aggregate() -> dict[str, list[str]]:
    """Pre-remediation T27 generated-public aggregate (all nine dimensions)."""
    loaders = ("T27_QUALIFICATION", "T27_TERMINAL_MATRIX", "T27_RECOVERY_REPLAN")
    aggregate: dict[str, set[str]] = {name: set() for name in DIMENSIONS}
    for loader in loaders:
        full = _t28_generated_fingerprints(loader)
        for name in DIMENSIONS:
            aggregate[name].update(full[name])
    return {name: sorted(values) for name, values in aggregate.items()}


def _validate_plan_mechanism_probe() -> dict[str, Any]:
    base = _scenario(
        "t28-reproducer-mechanism-probe", ("MATH_T4", "GENERAL", "CODE"),
        base=999)
    try:
        validate_plan(base["plan"])
        frozen_accepted = True
    except Exception:
        frozen_accepted = False
    mutated = json.loads(json.dumps(base["plan"]))
    mutated["fallback_condition"]["on_failure"] = "CONTINUE_ANYWAY"
    mutated_refused = False
    try:
        validate_plan(mutated)
    except Exception:
        mutated_refused = True
    return {"frozen_fallback_condition_accepted": frozen_accepted,
            "mutated_fallback_condition_refused": mutated_refused,
            "frozen_fallback_condition": FROZEN_FALLBACK_CONDITION,
            "forcing_leaf": "schema.plan",
            "forcing_mechanism": "sciencemath.integrated.runner:validate_plan"}


def main() -> int:
    root = ROOT
    t27_aggregate = _t27_generated_structural_aggregate()
    structural_populations = {
        name: len(t27_aggregate[name]) for name in STRUCTURAL_DIMENSIONS}

    # Contract-forced hash sets for any T28 contract-complete 512-package.
    forced_entity = sorted(sha256_json(family) for family in FAMILIES)
    forced_verbatim = sorted(
        sha256_json((family, FROZEN_FALLBACK_CONDITION)) for family in FAMILIES)
    capability_hashes_in_t27_generated_public = sorted(
        capability for capability in SKILL_IDS
        if sha256_json(capability) in set(t27_aggregate["source_ids"]))

    entity_overlap = sorted(
        set(forced_entity) & set(t27_aggregate["entity_identities"]))
    verbatim_overlap = sorted(
        set(forced_verbatim) & set(t27_aggregate["verbatim_attack_wording"]))

    # Direct measurement: a T28 contract-shaped disposable package (3-12
    # steps, all 16 families, frozen fallback semantics) against the old
    # T27 aggregate, exactly as the T27 construction refusal observed.
    cases, gold, _ = synthetic_private_bundle(2025)
    package_sets = fingerprint_sets(cases, gold)
    package_structural_overlap = {
        name: sorted(set(package_sets[name]) & set(t27_aggregate[name]))
        for name in STRUCTURAL_DIMENSIONS}
    package_all_dimensions_overlap = {
        name: len(set(package_sets[name]) & set(t27_aggregate[name]))
        for name in DIMENSIONS}

    # Inherited remediation: the T27 generated-public source classes now
    # carry EMPTY structural dimensions under the frozen dimension policy,
    # and T28's generated-public sources were authored under the same policy.
    index = build_authenticated_public_historical_index(root)
    sources = {source["source_class"]: source for source in index["sources"]}
    remediated_structural_populations = {
        name: sum(sources[source_class]["dimensions"][name]
                  ["historical_population"]
                  for source_class in GENERATED_PUBLIC_SOURCES)
        for name in STRUCTURAL_DIMENSIONS}
    remediated_structural_overlap = sum(
        remediated_structural_populations.values())

    mechanism = _validate_plan_mechanism_probe()
    policy = generated_public_dimension_policy()

    entity_forced = len(entity_overlap)
    verbatim_forced = len(verbatim_overlap)
    unconditional_capability_minimum = 1  # >=1 registered-capability step
    minimum = entity_forced + verbatim_forced + unconditional_capability_minimum
    capability_overlap_all_exercised = len(
        capability_hashes_in_t27_generated_public)
    all_exercised = entity_forced + verbatim_forced + (
        capability_overlap_all_exercised)
    contract_forced_structural_overlap = (
        entity_forced == len(FAMILIES) and verbatim_forced == len(FAMILIES))

    artifact = {
        "schema_version": "t28-structural-unsatisfiability-reproducer-v1",
        "artifact": "T28_STRUCTURAL_UNSATISFIABILITY_REPRODUCER",
        "classification": "PUBLIC_SAFE",
        "status": "REPRODUCED" if (
            mechanism["frozen_fallback_condition_accepted"]
            and mechanism["mutated_fallback_condition_refused"]
            and remediated_structural_overlap == 0) else "FAIL",
        "reproduces_state":
            "T27_REAL_CONSTRUCTION_REFUSED_HISTORICAL_EXCLUSION_"
            "STRUCTURALLY_UNSATISFIABLE",
        "classification_of_defect": "T27_PRE_EXPOSURE_STRUCTURAL_HISTORICAL_"
                                    "EXCLUSION_SEMANTICS_DEFECT",
        "root_cause":
            "Generated-public fingerprints under the T27 V4-era semantics "
            "encoded frozen structural vocabulary: entity_identities = "
            "sha256(family), source_ids = sha256(step.capability), "
            "verbatim_attack_wording = sha256((family, fallback_condition)) "
            "with the fallback dict contractually fixed, and relations = "
            "sha256((step_id, depends_on)) generic chain topology.  Any "
            "contract-complete 512-package therefore forced structural "
            "overlap against the authenticated public historical index, "
            "making overall_prohibited_overlap_required == 0 unsatisfiable.",
        "old_semantics": {
            "index_schema": "t27-authenticated-public-historical-index-v1",
            "generated_public_sources": list(GENERATED_PUBLIC_SOURCES),
            "structural_aggregate_populations": structural_populations,
            "old_public_history_root": SUPERSEDED_INDEX_ROOT,
        },
        "contract_forcing": {
            "entity_identities": {
                "forcing_leaf": "design.families_16",
                "forced_hash_count": len(FAMILIES),
                "overlap_measured": entity_forced,
            },
            "verbatim_attack_wording": {
                "forcing_leaf": "schema.plan",
                "mechanism":
                    "validate_plan refuses every fallback_condition other "
                    "than the frozen dict, so sha256((family, "
                    "fallback_condition)) is contractually fixed per family",
                "forced_hash_count": len(FAMILIES),
                "overlap_measured": verbatim_forced,
            },
            "source_ids": {
                "forcing_leaf": "schema.plan",
                "mechanism":
                    "every step must carry a registered capability, so any "
                    "package contributes at least one capability hash",
                "capability_hashes_in_generated_public":
                    len(capability_hashes_in_t27_generated_public),
                "unconditional_minimum": unconditional_capability_minimum,
            },
            "relations": {
                "forced": False,
                "reason":
                    "depends_on topology is author-chosen; chain topology "
                    "hashes are avoidable with a non-chain DAG",
            },
            "non_forced_dimensions": list(NON_FORCED_DIMENSIONS),
        },
        "mechanism_probe": mechanism,
        "contract_complete_package_overlap_measured": {
            "package": "synthetic_private_bundle(variant=2025) (disposable)",
            "structural_overlap": {
                name: len(package_structural_overlap[name])
                for name in STRUCTURAL_DIMENSIONS},
            "all_dimensions_overlap": package_all_dimensions_overlap,
        },
        "t27_old_semantics_minimum_overlap": minimum,
        "t27_old_semantics_capability_overlap_all_exercised": (
            capability_overlap_all_exercised),
        "t27_old_semantics_minimum_overlap_all_exercised": all_exercised,
        "contract_forced_structural_overlap": contract_forced_structural_overlap,
        "overclaim_guard":
            "capability overlap is exact 12 only if all 12 registered "
            "capabilities are exercised; the machine-readable lower bound is "
            "33 (16 entity + 16 verbatim + >=1 capability)",
        "overall_prohibited_overlap_required": 0,
        "contradiction": f"{minimum} > 0 -> UNSATISFIABLE",
        "remediated_semantics_inherited_for_t28": True,
        "generated_public_dimension_policy_schema": GENERATED_PUBLIC_POLICY_SCHEMA,
        "dimension_policy_root": policy["dimension_policy_root"],
        "remediated_structural_populations": remediated_structural_populations,
        "remediated_structural_overlap": remediated_structural_overlap,
        "remediated_index_schema": index["schema_version"],
        "remediated_index_root": index["public_historical_index_root"],
        "satisfiability_witness_reference":
            "evaluations/t28/structural_satisfiability_witness.json",
        "witness_material_is_not_real_blind_material": True,
        "t27_private_rows_opened": 0,
        "t28_private_rows_opened": 0,
        "t28_candidate_reruns": 0,
        "real_blind_rows_authored": 0,
        "real_gold_rows_authored": 0,
        "construction_one_shot_spent": False,
        "t28_construction_ledger_created": False,
    }
    if entity_forced != len(FAMILIES) or verbatim_forced != len(FAMILIES):
        artifact["status"] = "FAIL"

    target = root / "evaluations/t28/structural_unsatisfiability_reproducer.json"
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "status": artifact["status"],
        "t27_old_semantics_minimum_overlap": minimum,
        "entity_overlap": entity_forced,
        "verbatim_overlap": verbatim_forced,
        "capability_hashes_in_generated_public":
            len(capability_hashes_in_t27_generated_public),
        "package_structural_overlap": {
            name: len(values) for name, values in package_structural_overlap.items()},
        "remediated_structural_overlap": remediated_structural_overlap,
        "artifact": target.as_posix(),
    }, indent=2, sort_keys=True))
    return 0 if artifact["status"] == "REPRODUCED" else 1


if __name__ == "__main__":
    raise SystemExit(main())