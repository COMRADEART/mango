"""T6.5 — Curriculum level definitions for Mango.

Eight declared levels. A level is a *declaration*, not a run: whether it
trains is decided by the promotion gates after the previous level's
evaluation (T6.10). Every level definition declares:

  * capability tracks covered (ids from capabilities.py)
  * difficulty range (1..5, T6.7) — training must not start a level with
    items harder than the range
  * target example counts and macro-domain token-mixture targets (T6.8)
  * replay fraction from earlier stages (T6.9)
  * training profile (epochs / lr) — conservative 6 GB VRAM contract from
    T3 stays in force (micro-batch 1, seq 1024)

Levels may be attempted in order only. A level that fails its gate stops
the curriculum until the architecture is fixed.
"""
from __future__ import annotations

from sciencemath.curriculum.capabilities import FAMILIES, track_ids

CURRICULUM_VERSION = "1.0.0"

LEVELS: dict[int, dict] = {
    1: {
        "name": "foundations",
        "objective": "high reliability on fundamentals; concise answers",
        "tracks": [
            "math_arithmetic", "math_fractions", "math_ratios",
            "math_percentages", "math_linear_equations",
            "phys_mechanics", "phys_energy_momentum",
            "chem_stoichiometry", "bio_cells",
            "sci_dimensional_reasoning", "sci_measurements",
        ],
        "difficulty_range": [1, 2],
        "target_examples": 900,
        "macro_token_targets": {"mathematics": 0.50, "sciences": 0.35,
                                "cross_domain": 0.00, "general": 0.15},
        "replay_fraction": 0.15,
        "epochs": 2,
        "learning_rate": 5e-5,
        "max_new_tokens_note": "short answers; no long traces on easy items",
    },
    2: {
        "name": "core_problem_solving",
        "objective": "separate reasoning from calculation; tool eligibility",
        "tracks": [
            "math_linear_equations", "math_systems", "math_quadratics",
            "math_inequalities", "math_functions", "geometry_area_volume",
            "phys_mechanics", "phys_energy_momentum", "chem_stoichiometry",
            "chem_acids_bases", "bio_genetics",
            "sci_graph_interpretation",
        ],
        "difficulty_range": [2, 3],
        "target_examples": 800,
        "macro_token_targets": {"mathematics": 0.45, "sciences": 0.40,
                                "cross_domain": 0.00, "general": 0.15},
        "replay_fraction": 0.15,
        "epochs": 2,
        "learning_rate": 5e-5,
    },
    3: {
        "name": "structural_reasoning",
        "objective": "knowns/unknowns/assumptions/constraints before solving",
        "tracks": [
            "geometry_euclidean", "geometry_coordinate", "geometry_area_volume",
            "prob_basic", "stat_descriptive", "stat_expectation",
            "sci_experimental_variables", "sci_causality_correlation",
            "sci_graph_interpretation", "xd_interdisciplinary_inference",
            "xd_bio_statistics",
        ],
        "difficulty_range": [2, 3],
        "target_examples": 700,
        "macro_token_targets": {"mathematics": 0.40, "sciences": 0.40,
                                "cross_domain": 0.05, "general": 0.15},
        "replay_fraction": 0.15,
        "epochs": 2,
        "learning_rate": 5e-5,
    },
    4: {
        "name": "advanced_foundations",
        "objective": "longer problems with controlled answer length",
        "tracks": [
            "calculus_limits", "calculus_derivatives", "calculus_integrals",
            "phys_thermodynamics", "phys_electromagnetism",
            "bio_molecular_biology", "bio_genetics", "chem_equilibrium",
            "chem_thermochemistry", "space_planetary", "space_stellar",
        ],
        "difficulty_range": [3, 4],
        "target_examples": 700,
        "macro_token_targets": {"mathematics": 0.40, "sciences": 0.45,
                                "cross_domain": 0.05, "general": 0.10},
        "replay_fraction": 0.15,
        "epochs": 2,
        "learning_rate": 4e-5,
    },
    5: {
        "name": "hard_math_physics",
        "objective": "competition-style problems with verifiable answers",
        "tracks": [
            "math_polynomials", "adv_number_theory", "adv_combinatorics",
            "adv_discrete_math", "calculus_derivatives", "calculus_integrals",
            "trig_identities", "geometry_euclidean", "phys_mechanics",
            "phys_energy_momentum", "phys_electromagnetism",
        ],
        "difficulty_range": [3, 5],
        "target_examples": 600,
        "macro_token_targets": {"mathematics": 0.55, "sciences": 0.35,
                                "cross_domain": 0.05, "general": 0.05},
        "replay_fraction": 0.20,
        "epochs": 2,
        "learning_rate": 4e-5,
    },
    6: {
        "name": "research_style_science",
        "objective": "evidence interpretation; distinguish fact from "
                     "uncertainty; no fake certainty",
        "tracks": [
            "sci_evidence_evaluation", "sci_hypothesis_formation",
            "sci_error_uncertainty", "xd_interdisciplinary_inference",
            "phys_intro_relativity", "phys_intro_quantum", "space_cosmology",
            "earth_climate", "earth_geology", "bio_evolution",
            "chem_physical_foundations",
        ],
        "difficulty_range": [3, 5],
        "target_examples": 600,
        "macro_token_targets": {"mathematics": 0.20, "sciences": 0.55,
                                "cross_domain": 0.15, "general": 0.10},
        "replay_fraction": 0.20,
        "epochs": 2,
        "learning_rate": 4e-5,
    },
    7: {
        "name": "interdisciplinary_intelligence",
        "objective": "compositional transfer across domains",
        "tracks": [
            "xd_math_physics", "xd_chem_math", "xd_bio_statistics",
            "xd_astronomy_physics", "xd_climate_statistics",
            "xd_interdisciplinary_inference",
            "calculus_derivatives", "phys_thermodynamics", "chem_equilibrium",
        ],
        "difficulty_range": [3, 5],
        "target_examples": 600,
        "macro_token_targets": {"mathematics": 0.30, "sciences": 0.35,
                                "cross_domain": 0.30, "general": 0.05},
        "replay_fraction": 0.20,
        "epochs": 2,
        "learning_rate": 4e-5,
    },
    8: {
        "name": "tool_retrieval_aware_reasoning",
        "objective": "route: internal reasoning / math tool / retrieval / "
                     "both / insufficient evidence — never fabricated "
                     "tool output",
        "tracks": [
            "math_scientific_notation", "sci_measurements",
            "sci_dimensional_reasoning", "phys_astronomy_related",
            "chem_acids_bases", "chem_physical_foundations",
            "xd_astronomy_physics", "xd_climate_statistics",
            "xd_chem_math", "xd_bio_statistics",
        ],
        "difficulty_range": [3, 5],
        "target_examples": 600,
        "macro_token_targets": {"mathematics": 0.30, "sciences": 0.40,
                                "cross_domain": 0.25, "general": 0.05},
        "replay_fraction": 0.20,
        "epochs": 2,
        "learning_rate": 4e-5,
    },
}

# Difficulty label scale (T6.7)
DIFFICULTY_LABELS = {1: "elementary", 2: "foundational", 3: "intermediate",
                     4: "advanced", 5: "difficult"}


def level_def(level: int) -> dict:
    return LEVELS[level]


def validate_level_def(level: int) -> list[str]:
    d = LEVELS[level]
    errors = []
    if not (1 <= level <= 8):
        errors.append(f"level {level} outside 1..8")
    unknown = set(d["tracks"]) - set(track_ids())
    if unknown:
        errors.append(f"L{level}: unknown track ids {sorted(unknown)}")
    lo, hi = d["difficulty_range"]
    if not (1 <= lo <= hi <= 5):
        errors.append(f"L{level}: bad difficulty range {d['difficulty_range']}")
    total = sum(d["macro_token_targets"].values())
    if abs(total - 1.0) > 0.01:
        errors.append(f"L{level}: macro_token_targets sum {total} != 1.0")
    if not (0.0 <= d["replay_fraction"] <= 0.5):
        errors.append(f"L{level}: replay_fraction out of 0..0.5")
    return errors


def tracks_covered_through(level: int) -> set[str]:
    """Union of tracks declared by levels 1..level."""
    covered: set[str] = set()
    for lv in range(1, level + 1):
        covered.update(LEVELS[lv]["tracks"])
    return covered


def replay_source_levels(level: int) -> list[int]:
    """Levels whose examples may feed the replay buffer for `level`."""
    return list(range(1, level))