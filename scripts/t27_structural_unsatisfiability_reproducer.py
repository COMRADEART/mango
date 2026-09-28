"""Reproduce the V4 pre-exposure structural historical-exclusion refusal.

Public-only, deterministic.  Reconstructs the pre-remediation (V4-era)
generated-public structural fingerprint aggregates from the public
generators, derives the hash sets that the frozen construction contract
forces every contract-complete 512-package to contain, and proves the
old semantics made the required zero-overlap condition unsatisfiable
(minimum >= 33).  It then shows the remediated policy removes the forcing
(structural overlap 0) and defers overall satisfiability to the witness
artifact.  Never touches real T27 material, the T26 overlap oracle, the
construction ledger, or the construction one-shot.
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
from t27_protocol.construction import (  # noqa: E402
    fingerprint_sets, synthetic_private_bundle)
from t27_protocol.contract import FAMILIES  # noqa: E402
from t27_protocol.exclusion import (  # noqa: E402
    DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA, GENERATED_PUBLIC_SOURCES,
    SUPERSEDED_INDEX_ROOT, _t27_generated_fingerprints,
    build_authenticated_public_historical_index,
    generated_public_dimension_policy)
from t27_protocol.qualification import _scenario  # noqa: E402

STRUCTURAL_DIMENSIONS = (
    "entity_identities", "source_ids", "verbatim_attack_wording", "relations")
NON_FORCED_DIMENSIONS = tuple(
    name for name in DIMENSIONS if name not in STRUCTURAL_DIMENSIONS)
# validate_plan enforces exactly this fallback_condition dict for every
# T27 plan (src/sciencemath/integrated/runner.py), and the construction
# contract leaf schema.plan requires every plan to validate.
FROZEN_FALLBACK_CONDITION = {"on_failure": "SAFE_ABSTAIN",
                             "on_insufficient_evidence": "INSUFFICIENT_EVIDENCE"}


def _old_generated_structural_aggregate() -> dict[str, list[str]]:
    """Pre-remediation generated-public aggregate (all nine dimensions).

    Exactly the fingerprints the V4-era authenticated public historical
    index carried for the four generated-public source classes.
    """
    loaders = ("T27_QUALIFICATION", "T27_TERMINAL_MATRIX", "T27_RECOVERY_REPLAN")
    aggregate: dict[str, set[str]] = {name: set() for name in DIMENSIONS}
    for loader in loaders:
        full = _t27_generated_fingerprints(loader)
        for name in DIMENSIONS:
            aggregate[name].update(full[name])
    return {name: sorted(values) for name, values in aggregate.items()}


def _validate_plan_mechanism_probe() -> dict[str, Any]:
    """Prove validate_plan contractually pins the frozen fallback dict."""
    base = _scenario(
        "t27-reproducer-mechanism-probe", ("MATH_T4", "GENERAL", "CODE"),
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
    old_aggregate = _old_generated_structural_aggregate()
    structural_populations = {
        name: len(old_aggregate[name]) for name in STRUCTURAL_DIMENSIONS}

    # Contract-forced hash sets for any contract-complete 512-package.
    forced_entity = sorted(sha256_json(family) for family in FAMILIES)
    forced_verbatim = sorted(
        sha256_json((family, FROZEN_FALLBACK_CONDITION)) for family in FAMILIES)
    registered_capabilities = sorted(sha256_json(capability)
                                     for capability in SKILL_IDS)
    capability_hashes_in_generated_public = sorted(
        capability for capability in SKILL_IDS
        if sha256_json(capability) in set(old_aggregate["source_ids"]))

    entity_overlap = sorted(set(forced_entity) & set(old_aggregate["entity_identities"]))
    verbatim_overlap = sorted(
        set(forced_verbatim) & set(old_aggregate["verbatim_attack_wording"]))

    # Direct measurement: a contract-shaped disposable package (3-12 steps,
    # all 16 families, frozen fallback semantics) against the old aggregate.
    cases, gold, _ = synthetic_private_bundle(2025)
    package_sets = fingerprint_sets(cases, gold)
    package_structural_overlap = {
        name: sorted(set(package_sets[name]) & set(old_aggregate[name]))
        for name in STRUCTURAL_DIMENSIONS}
    package_all_dimensions_overlap = {
        name: len(set(package_sets[name]) & set(old_aggregate[name]))
        for name in DIMENSIONS}

    # Remediated semantics: the four generated-public source classes now
    # carry EMPTY structural dimensions under the frozen dimension policy.
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
    capability_overlap_all_exercised = len(capability_hashes_in_generated_public)
    all_exercised = entity_forced + verbatim_forced + (
        capability_overlap_all_exercised)
    contract_forced_structural_overlap = (
        entity_forced == len(FAMILIES) and verbatim_forced == len(FAMILIES))

    artifact = {
        "schema_version": "t27-structural-unsatisfiability-reproducer-v1",
        "artifact": "T27_STRUCTURAL_UNSATISFIABILITY_REPRODUCER",
        "classification": "PUBLIC_SAFE",
        "status": "REPRODUCED" if (
            mechanism["frozen_fallback_condition_accepted"]
            and mechanism["mutated_fallback_condition_refused"]
            and remediated_structural_overlap == 0) else "FAIL",
        "reproduces_state":
            "T27_REAL_CONSTRUCTION_REFUSED_HISTORICAL_EXCLUSION_"
            "STRUCTURALLY_UNSATISFIABLE",
        "classification_of_defect": "PRE_EXPOSURE_STRUCTURAL_HISTORICAL_"
                                    "EXCLUSION_SEMANTICS_DEFECT",
        "root_cause":
            "Generated-public fingerprints under the V4-era semantics "
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
                    len(capability_hashes_in_generated_public),
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
        "old_semantics_minimum_overlap": minimum,
        "old_semantics_capability_overlap_all_exercised": (
            capability_overlap_all_exercised),
        "old_semantics_minimum_overlap_all_exercised": all_exercised,
        "contract_forced_structural_overlap": contract_forced_structural_overlap,
        "overclaim_guard":
            "capability overlap is exact 12 only if all 12 registered "
            "capabilities are exercised; the machine-readable lower bound is "
            "33 (16 entity + 16 verbatim + >=1 capability)",
        "overall_prohibited_overlap_required": 0,
        "contradiction": f"{minimum} > 0 -> UNSATISFIABLE",
        "remediated_semantics": True,
        "generated_public_dimension_policy_schema": GENERATED_PUBLIC_POLICY_SCHEMA,
        "dimension_policy_root": policy["dimension_policy_root"],
        "remediated_structural_populations": remediated_structural_populations,
        "remediated_structural_overlap": remediated_structural_overlap,
        "remediated_index_schema": index["schema_version"],
        "remediated_index_root": index["public_historical_index_root"],
        "satisfiability_witness_reference":
            "evaluations/t27/structural_satisfiability_witness.json",
        "witness_material_is_not_real_blind_material": True,
        "t26_private_rows_opened": 0,
        "t26_candidate_reruns": 0,
        "real_blind_rows_authored": 0,
        "real_gold_rows_authored": 0,
        "construction_one_shot_spent": False,
        "t27_construction_ledger_created": False,
    }
    if entity_forced != len(FAMILIES) or verbatim_forced != len(FAMILIES):
        artifact["status"] = "FAIL"

    target = root / "evaluations/t27/structural_unsatisfiability_reproducer.json"
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "status": artifact["status"],
        "old_semantics_minimum_overlap": minimum,
        "entity_overlap": entity_forced,
        "verbatim_overlap": verbatim_forced,
        "capability_hashes_in_generated_public":
            len(capability_hashes_in_generated_public),
        "package_structural_overlap": {
            name: len(values) for name, values in package_structural_overlap.items()},
        "remediated_structural_overlap": remediated_structural_overlap,
        "artifact": target.as_posix(),
    }, indent=2, sort_keys=True))
    return 0 if artifact["status"] == "REPRODUCED" else 1


if __name__ == "__main__":
    raise SystemExit(main())