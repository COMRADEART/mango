"""Prove real zero-overlap is satisfiable for T28 under the inherited policy.

Builds a disposable PUBLIC/SYNTHETIC, real-shaped 512-package (16 families
x 32, 3-12 steps, all 12 registered capabilities, frozen fallback
semantics, all nonvacuity minimums met) from an entirely new synthetic
namespace, verifies value-level disjointness from the public generated
material (no lucky hashes), and proves overall prohibited overlap == 0
against the authenticated public historical index.

The witness material is disposable proof only and is never valid as real
T28 blind material.  It never touches T27 private rows, the sealed T27
oracle, the T28 construction ledger, or any one-shot.
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
from sciencemath.integrated.runner import (AUTHORITY, validate_plan)  # noqa: E402
from t21_protocol.util import sha256_json  # noqa: E402
from t28_protocol.contract import (FAMILIES, NONVACUITY_MINIMUMS,  # noqa: E402
                                   REPLAN_TRIGGERS)
from t28_protocol.construction import (  # noqa: E402
    fingerprint_root, fingerprint_sets)
from t28_protocol.exclusion import (  # noqa: E402
    GENERATED_PUBLIC_POLICY_SCHEMA, build_authenticated_public_historical_index,
    generated_public_dimension_policy)
from t28_protocol.qualification import (SAFE_TERMINALS, build_public_cases,  # noqa: E402
                                        _scenario)

FROZEN_FALLBACK_CONDITION = {"on_failure": "SAFE_ABSTAIN",
                             "on_insufficient_evidence": "INSUFFICIENT_EVIDENCE"}
WITNESS_SEED_BASE = 5000
WITNESS_ANSWER_BASE = 120000
ABSTENTION_SENTINEL_PREFIX = "t28-witness-no-answer-"


def _witness_step(step_id: str, capability: str, predecessor: str | None,
                  seed: int, delta: int,
                  fallback: str | None = None) -> dict[str, Any]:
    return {
        "step_id": step_id, "capability": capability,
        "depends_on": [predecessor] if predecessor else [],
        "router_input": {
            "query": f"T28 witness synthetic operation {step_id} via {capability}",
            "requested_capability": capability,
            "available_capabilities": list(SKILL_IDS),
            "permission_grants": ["network", "code_exec"],
        },
        "input": ({"op": "t28_witness_seed", "seed": seed} if predecessor is None
                  else {"op": "t28_witness_add", "delta": delta}),
        "input_from": {} if predecessor is None else {"previous": predecessor},
        "preconditions": ["t28 witness synthetic data", "dependencies verified"],
        "expected_output": {
            "required_fields": ["status", "value", "evidence", "provenance",
                                "classification", "confidence"],
            "classification": "PUBLIC_SAFE",
        },
        "verification": {
            "kind": "evidence" if predecessor is None else "numeric",
            "required": True,
            "parameters": ({} if predecessor is None else
                           {"operation": "t28_witness_add", "tolerance": 0}),
        },
        "fallback_capability": fallback,
    }


def _public_generated_values() -> dict[str, set]:
    """Value-level public generated namespaces (no hashing involved)."""
    cases, gold, _ = build_public_cases()
    scenarios = [case["scenario_id"] for case in cases]
    goals = [case["plan"]["goal"] for case in cases]
    inputs = [step["input"] for case in cases for step in case["plan"]["steps"]]
    pairs = [(case["scenario_id"], step["step_id"])
             for case in cases for step in case["plan"]["steps"]]
    answers = [item["expected_answer"] for item in gold]
    specifications = (
        ("COMPLETE", 1, 3), ("PARTIAL", 1, 3), ("INSUFFICIENT_EVIDENCE", 1, 3),
        ("BLOCKED", 1, 3), ("BUDGET_EXHAUSTED", 0, 0),
        ("UNAVAILABLE_CAPABILITY", 1, 3), ("SECURITY_REFUSAL", 1, 3),
        ("ERROR", 1, 3),
    )
    for index, (terminal, step_retry, total_retry) in enumerate(specifications):
        scenario = _scenario(
            f"t28-terminal-{terminal.lower()}",
            ("MATH_T4", "SCICOMP", "GENERAL"), base=711 + index,
            max_step_retries=step_retry, max_total_retries=total_retry)
        scenarios.append(scenario["scenario_id"])
        goals.append(scenario["plan"]["goal"])
        inputs.extend(step["input"] for step in scenario["plan"]["steps"])
        pairs.extend((scenario["scenario_id"], step["step_id"])
                     for step in scenario["plan"]["steps"])
        answers.append(terminal)
    return {"scenario_ids": set(scenarios), "goals": set(goals),
            "inputs": {json.dumps(item, sort_keys=True) for item in inputs},
            "answers": set(answers), "pairs": set(pairs)}


def build_witness_package() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic real-shaped 512/512 witness package."""
    cases: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for family_index, family in enumerate(FAMILIES):
        for variant in range(32):
            index = family_index * 32 + variant
            case_id = f"t28-witness-{family}-{variant + 1:02d}"
            length = 3 + (variant % 10)
            kind = variant % 4
            caps = [SKILL_IDS[(j + family_index * 5) % 12]
                    for j in range(length)]
            fallback = None
            trigger = None
            if kind == 2:
                fallback = SKILL_IDS[(family_index * 5 + length + 3) % 12]
                trigger = REPLAN_TRIGGERS[family_index % len(REPLAN_TRIGGERS)]
            steps = []
            for j, capability in enumerate(caps):
                step_id = f"st{j + 1}"
                predecessor = f"st{j}" if j else None
                steps.append(_witness_step(
                    step_id, capability, predecessor,
                    WITNESS_SEED_BASE + index, j,
                    fallback if j == length - 1 else None))
            required = [step["step_id"] for step in steps]
            plan = {
                "plan_id": f"plan-{case_id}", "version": 1,
                "goal": (f"T28 structural satisfiability witness workflow "
                         f"{case_id}"),
                "steps": steps,
                "budgets": {"max_steps": max(8, length),
                            "max_step_retries": 1, "max_total_retries": 3,
                            "max_replans": 2, "max_wall_seconds": 30},
                "completion_condition": {"required_steps": required,
                                         "final_step": required[-1],
                                         "final_verification": True},
                "fallback_condition": dict(FROZEN_FALLBACK_CONDITION),
                "authority": AUTHORITY,
            }
            scenario = {"scenario_id": case_id,
                        "classification": "SYNTHETIC_DISPOSABLE",
                        "plan": plan}
            expected_terminal = (SAFE_TERMINALS[family_index % len(SAFE_TERMINALS)]
                                 if kind == 3 else "COMPLETE")
            answer = (f"{ABSTENTION_SENTINEL_PREFIX}{index}" if kind == 3
                      else WITNESS_ANSWER_BASE + index)
            gold.append({
                "scenario_id": case_id, "family": family,
                "expected_terminal": expected_terminal,
                "expected_answer": answer,
                "expected_verified_steps": length if kind != 3 else length - 1,
                "designated_recoverable": kind == 1,
                "designated_abstention": kind == 3,
                "expected_replan_trigger": trigger,
                "expected_fallback_capability": fallback,
                "metric_designations": {
                    "successful_completion": kind != 3,
                    "recoverable": kind == 1, "replan_required": kind == 2,
                    "safe_abstention": kind == 3,
                    "handoff": length >= 2, "verification": True,
                },
            })
            cases.append(scenario)
    return cases, gold


def main() -> int:
    cases, gold = build_witness_package()
    public = _public_generated_values()

    static: dict[str, Any] = {
        "scenario_count_512": len(cases) == 512 and len(gold) == 512,
        "family_count_16": all(
            sum(item["family"] == family for item in gold) == 32
            for family in FAMILIES),
        "step_range_3_12": all(3 <= len(item["plan"]["steps"]) <= 12
                               for item in cases),
        "plans_validate": True,
        "all_capabilities_exercised": None,
        "fallback_semantics_frozen": all(
            item["plan"]["fallback_condition"] == FROZEN_FALLBACK_CONDITION
            for item in cases),
        "abstention_semantics": all(
            (not expected["designated_abstention"])
            or (expected["expected_terminal"] in SAFE_TERMINALS
                and isinstance(expected["expected_answer"], str)
                and expected["expected_answer"].startswith(
                    ABSTENTION_SENTINEL_PREFIX))
            for expected in gold),
    }
    for item in cases:
        try:
            validate_plan(item["plan"])
        except Exception:
            static["plans_validate"] = False
            break
    designated = {
        "successful_completion_cases": sum(
            item["expected_terminal"] == "COMPLETE" for item in gold),
        "recoverable_cases": sum(item["designated_recoverable"] for item in gold),
        "replan_required_cases": sum(
            bool(item["expected_replan_trigger"]) for item in gold),
        "safe_abstention_cases": sum(
            item["designated_abstention"] for item in gold),
        "handoff_cases": sum(
            item["metric_designations"]["handoff"] for item in gold),
        "verification_cases": sum(
            item["metric_designations"]["verification"] for item in gold),
    }
    nonvacuity_pass = all(designated[name] >= minimum
                          for name, minimum in NONVACUITY_MINIMUMS.items())
    exercised = sorted({step["capability"] for item in cases
                        for step in item["plan"]["steps"]})
    static["all_capabilities_exercised"] = set(exercised) == set(SKILL_IDS)

    witness_scenario_ids = [item["scenario_id"] for item in cases]
    witness_goals = [item["plan"]["goal"] for item in cases]
    witness_inputs = [step["input"] for item in cases
                      for step in item["plan"]["steps"]]
    witness_answers = [item["expected_answer"] for item in gold]
    witness_pairs = [(item["scenario_id"], step["step_id"])
                     for item in cases for step in item["plan"]["steps"]]
    disjointness = {
        "scenario_ids_disjoint": set(witness_scenario_ids).isdisjoint(
            public["scenario_ids"]),
        "goals_disjoint": set(witness_goals).isdisjoint(public["goals"]),
        "inputs_disjoint": {
            json.dumps(item, sort_keys=True) for item in witness_inputs
        }.isdisjoint(public["inputs"]),
        "answers_disjoint": set(witness_answers).isdisjoint(public["answers"]),
        "step_pairs_disjoint": set(witness_pairs).isdisjoint(public["pairs"]),
    }

    sets = fingerprint_sets(cases, gold)
    index = build_authenticated_public_historical_index(ROOT)
    index_sources = {source["source_class"]: source
                     for source in index["sources"]}
    aggregate_overlap = {
        name: sorted(set(sets[name])
                     & set(index["aggregate_dimensions"][name]["fingerprints"]))
        for name in sets}
    overall = sum(len(values) for values in aggregate_overlap.values())
    per_source_overlap_zero = all(
        not (set(sets[name]) & set(index_sources[source_class]
                                   ["dimensions"][name]["fingerprints"]))
        for source_class in index_sources
        for name in sets)
    deterministic_second = fingerprint_root(fingerprint_sets(
        *build_witness_package()))
    deterministic = deterministic_second == fingerprint_root(sets)
    policy = generated_public_dimension_policy()

    witness = {
        "schema_version": "t28-structural-satisfiability-witness-v1",
        "artifact": "T28_STRUCTURAL_SATISFIABILITY_WITNESS",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if (
            all(static.values()) and nonvacuity_pass
            and all(disjointness.values()) and overall == 0
            and per_source_overlap_zero and deterministic) else "FAIL",
        "scenario_count": len(cases),
        "family_count": len(FAMILIES),
        "cases_per_family": 32,
        "step_range": [3, 12],
        "capabilities_exercised": len(exercised),
        "static_checks": static,
        "designated_counts": designated,
        "nonvacuity_minimums": dict(NONVACUITY_MINIMUMS),
        "nonvacuity_pass": nonvacuity_pass,
        "value_level_disjointness": disjointness,
        "overall_prohibited_overlap": overall,
        "aggregate_overlap_by_dimension": {
            name: len(values) for name, values in aggregate_overlap.items()},
        "per_source_overlap_zero": per_source_overlap_zero,
        "deterministic": deterministic,
        "fingerprint_root": fingerprint_root(sets),
        "compared_index_schema": index["schema_version"],
        "compared_index_root": index["public_historical_index_root"],
        "generated_public_dimension_policy_schema": GENERATED_PUBLIC_POLICY_SCHEMA,
        "dimension_policy_root": policy["dimension_policy_root"],
        "reused_public_blind_material": False,
        "witness_material_is_not_real_blind_material": True,
        "witness_material_retired_after_proof": True,
        "authoring_constraints_recorded_for_real_construction": [
            "abstention gold rows must carry a non-None expected_answer "
            "sentinel (the frozen scorer never reads expected_answer for "
            "designated_abstention rows; None would collide with the single "
            "None fingerprint retained in the public qualification "
            "exact_answers dimension)",
            "expected_answer values must avoid the public qualification "
            "numeric answers and terminal strings in every historical "
            "namespace, including T27's",
            "scenario ids, plan goals and step inputs must use a fresh "
            "namespace disjoint from ALL public generated material, in T28 "
            "and every predecessor namespace",
            "plan fallback_condition must equal the frozen validate_plan "
            "dict for every scenario",
        ],
        "t27_private_rows_opened": 0,
        "t28_private_rows_opened": 0,
        "t28_candidate_reruns": 0,
        "real_blind_rows_authored": 0,
        "real_gold_rows_authored": 0,
        "construction_one_shot_spent": False,
        "t28_construction_ledger_created": False,
    }

    target = ROOT / "evaluations/t28/structural_satisfiability_witness.json"
    target.write_text(json.dumps(witness, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "status": witness["status"],
        "overall_prohibited_overlap": overall,
        "aggregate_overlap_by_dimension": witness["aggregate_overlap_by_dimension"],
        "designated_counts": designated,
        "capabilities_exercised": len(exercised),
        "disjointness": disjointness,
        "deterministic": deterministic,
        "artifact": target.as_posix(),
    }, indent=2, sort_keys=True))
    return 0 if witness["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())