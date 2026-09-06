"""T6.1 — Mango capability taxonomy and capability matrix.

The taxonomy is a formal, versioned list of capability tracks. Every
curriculum level, every mango-eval-core item, and every mango-sft-v2
example references track ids from THIS module, so capability acquisition
and retention can be measured per track instead of per dataset.

The capability matrix is the per-track bookkeeping record:

  * baseline            — measured Mango-v0.1 score (None until measured)
  * best_checkpoint     — best checkpoint id seen so far
  * current_checkpoint  — checkpoint under evaluation
  * training_exposure   — list of {level, examples} entries
  * eval_exposure       — list of {suite, items} entries
  * regression_threshold_pp — absolute percentage points (declared BEFORE
                              results are observed; see gates.py)
  * status              — one of STATUS_* below

Versioning: changing the taxonomy invalidates cross-milestone comparisons;
the version must be bumped and the change recorded in the matrix manifest.
"""
from __future__ import annotations

from copy import deepcopy

TAXONOMY_VERSION = "1.0.0"

STATUS_NOT_MEASURED = "not_measured"
STATUS_ACQUIRED = "acquired"
STATUS_AT_RISK = "at_risk"
STATUS_REGRESSED = "regressed"
STATUS_ALL = (STATUS_NOT_MEASURED, STATUS_AT_RISK, STATUS_ACQUIRED,
              STATUS_REGRESSED)

# ---------------------------------------------------------------------------
# Track definition: (track_id, family, difficulty range on the 1..5 scale
# mango-eval-core samples from, requires_math_tool, requires_retrieval)
# difficulty: 1 elementary, 2 foundational, 3 intermediate, 4 advanced,
# 5 difficult (T6.7 scale).
# ---------------------------------------------------------------------------

_MATHEMATICS = {
    # Foundation
    "math_arithmetic":        (1, 2, False, False),
    "math_fractions":         (1, 3, False, False),
    "math_ratios":            (2, 3, False, False),
    "math_percentages":       (2, 3, False, False),
    "math_scientific_notation": (2, 3, True, False),
    # Algebra
    "math_linear_equations":  (2, 4, False, False),
    "math_systems":           (3, 4, False, False),
    "math_quadratics":        (3, 4, False, False),
    "math_inequalities":      (3, 4, False, False),
    "math_polynomials":       (3, 5, False, False),
    "math_functions":         (3, 4, False, False),
    # Geometry
    "geometry_euclidean":     (2, 5, False, False),
    "geometry_coordinate":    (3, 5, False, False),
    "geometry_area_volume":   (2, 4, False, False),
    "geometry_transformations": (3, 4, False, False),
    # Trigonometry
    "trig_identities":        (3, 5, False, False),
    "trig_triangles":         (2, 4, False, False),
    "trig_radians":           (2, 3, False, False),
    "trig_periodic":          (3, 5, False, False),
    # Calculus
    "calculus_limits":        (3, 5, False, False),
    "calculus_derivatives":   (3, 5, False, False),
    "calculus_integrals":     (3, 5, False, False),
    "calculus_series":        (4, 5, False, False),
    "calculus_intro_ode":     (4, 5, False, False),
    # Probability / Statistics
    "prob_basic":             (2, 4, False, False),
    "prob_distributions":     (3, 5, False, False),
    "stat_expectation":       (3, 5, False, False),
    "stat_variance":          (3, 4, False, False),
    "stat_hypothesis_reasoning": (4, 5, False, False),
    "stat_descriptive":       (2, 4, False, False),
    # Advanced
    "adv_linear_algebra":     (4, 5, False, False),
    "adv_number_theory":      (3, 5, False, False),
    "adv_combinatorics":      (3, 5, False, False),
    "adv_optimization":       (4, 5, False, False),
    "adv_discrete_math":      (3, 5, False, False),
}

_PHYSICS = {
    "phys_mechanics":           (2, 4, True, False),
    "phys_energy_momentum":     (2, 4, True, False),
    "phys_waves":               (2, 4, True, False),
    "phys_optics":              (2, 4, True, False),
    "phys_electromagnetism":    (3, 5, True, False),
    "phys_thermodynamics":      (3, 5, True, False),
    "phys_intro_relativity":    (3, 5, False, True),
    "phys_intro_quantum":       (3, 5, False, True),
    "phys_astronomy_related":   (2, 4, True, True),
}

_CHEMISTRY = {
    "chem_atomic_structure":    (2, 3, False, True),
    "chem_bonding":             (2, 4, False, True),
    "chem_stoichiometry":       (2, 4, True, False),
    "chem_reactions":           (2, 4, False, True),
    "chem_thermochemistry":     (3, 4, True, False),
    "chem_equilibrium":         (3, 5, True, False),
    "chem_acids_bases":         (2, 4, True, True),
    "chem_organic_foundations": (2, 4, False, True),
    "chem_physical_foundations": (3, 5, True, True),
}

_BIOLOGY = {
    "bio_cells":                (1, 3, False, True),
    "bio_genetics":             (2, 4, False, False),
    "bio_molecular_biology":    (2, 4, False, True),
    "bio_physiology":           (2, 4, False, True),
    "bio_evolution":            (2, 4, False, True),
    "bio_ecology":              (2, 4, False, True),
    "bio_microbiology":         (3, 4, False, True),
}

_EARTH_SPACE = {
    "earth_geology":            (2, 4, False, True),
    "earth_climate":            (2, 4, False, True),
    "earth_meteorology":        (2, 4, False, True),
    "earth_oceanography":       (2, 4, False, True),
    "space_planetary":          (2, 4, True, True),
    "space_stellar":            (3, 4, True, True),
    "space_cosmology":          (3, 5, False, True),
}

_SCIENTIFIC_REASONING = {
    "sci_hypothesis_formation":   (2, 4, False, True),
    "sci_experimental_variables": (2, 4, False, False),
    "sci_causality_correlation":  (2, 4, False, False),
    "sci_measurements":           (2, 4, True, False),
    "sci_error_uncertainty":      (3, 4, True, False),
    "sci_dimensional_reasoning":  (2, 4, True, False),
    "sci_graph_interpretation":   (2, 4, False, False),
    "sci_evidence_evaluation":    (3, 5, False, True),
}

_CROSS_DOMAIN = {
    "xd_math_physics":          (3, 5, True, False),
    "xd_chem_math":             (3, 5, True, False),
    "xd_bio_statistics":        (3, 5, True, False),
    "xd_astronomy_physics":     (3, 5, True, True),
    "xd_climate_statistics":    (3, 5, True, True),
    "xd_interdisciplinary_inference": (3, 5, False, True),
}

FAMILIES: dict[str, dict[str, tuple[int, int, bool, bool]]] = {
    "mathematics": _MATHEMATICS,
    "physics": _PHYSICS,
    "chemistry": _CHEMISTRY,
    "biology": _BIOLOGY,
    "earth_space": _EARTH_SPACE,
    "scientific_reasoning": _SCIENTIFIC_REASONING,
    "cross_domain": _CROSS_DOMAIN,
}

# The four capability macros reported in the T6 dashboard.
MACROS = ("math_macro", "science_macro", "cross_domain_macro",
          "generalization_macro")

_MATH_FAMILIES = ("mathematics",)
_SCIENCE_FAMILIES = ("physics", "chemistry", "biology", "earth_space",
                     "scientific_reasoning")


def track_ids() -> list[str]:
    return [tid for fam in FAMILIES.values() for tid in fam]


def track_spec(track_id: str) -> dict:
    """Full spec for one track; KeyError when the id is not in the taxonomy."""
    for family, tracks in FAMILIES.items():
        if track_id in tracks:
            diff_lo, diff_hi, tool, retrieval = tracks[track_id]
            return {"track_id": track_id, "family": family,
                    "difficulty_range": [diff_lo, diff_hi],
                    "requires_math_tool": tool,
                    "requires_retrieval": retrieval}
    raise KeyError(f"unknown capability track: {track_id}")


def tracks_by_family(family: str) -> list[str]:
    return list(FAMILIES[family])


def family_of(track_id: str) -> str:
    return track_spec(track_id)["family"]


def family_macro(family: str) -> str:
    if family in _MATH_FAMILIES:
        return "math_macro"
    if family in _SCIENCE_FAMILIES:
        return "science_macro"
    if family == "cross_domain":
        return "cross_domain_macro"
    raise ValueError(f"no macro for family {family!r}")


# ---------------------------------------------------------------------------
# Capability matrix (T6.1 bookkeeping record)
# ---------------------------------------------------------------------------

def default_regression_threshold_pp(family: str) -> float:
    """Pre-declared per-track sensitivity (see gates.py for the full gate
    set). Cross-domain tracks are the most fragile: a small absolute drop
    on few items is material, so their threshold is tighter."""
    if family == "cross_domain":
        return 5.0
    if family in _SCIENCE_FAMILIES:
        return 7.0
    return 8.0


def new_matrix() -> dict:
    """An empty matrix with one row per taxonomy track."""
    tracks = {}
    for family, fam_tracks in FAMILIES.items():
        for tid in fam_tracks:
            tracks[tid] = {
                "family": family,
                "baseline": None,          # measured Mango-v0.1 score
                "best_checkpoint": None,
                "best_score": None,
                "current_checkpoint": None,
                "current_score": None,
                "training_exposure": [],   # [{level, examples}]
                "eval_exposure": [],       # [{suite, items}]
                "regression_threshold_pp":
                    default_regression_threshold_pp(family),
                "status": STATUS_NOT_MEASURED,
            }
    return {
        "artifact": "mango-capability-matrix",
        "taxonomy_version": TAXONOMY_VERSION,
        "tracks": tracks,
    }


def validate_matrix(matrix: dict) -> list[str]:
    """Schema validation; empty list means valid."""
    errors: list[str] = []
    if matrix.get("artifact") != "mango-capability-matrix":
        errors.append("artifact: expected 'mango-capability-matrix'")
    expected_ids = set(track_ids())
    got = set(matrix.get("tracks", {}))
    if got != expected_ids:
        errors.append(f"tracks mismatch: missing={sorted(expected_ids - got)} "
                      f"extra={sorted(got - expected_ids)}")
    for tid, row in matrix.get("tracks", {}).items():
        if row.get("family") not in FAMILIES:
            errors.append(f"{tid}: unknown family {row.get('family')!r}")
        if row.get("status") not in STATUS_ALL:
            errors.append(f"{tid}: invalid status {row.get('status')!r}")
        thr = row.get("regression_threshold_pp")
        if not isinstance(thr, (int, float)) or not (0 < thr <= 25):
            errors.append(f"{tid}: regression_threshold_pp {thr!r} outside "
                          "0..25")
        for exp in row.get("training_exposure", []):
            if "level" not in exp or "examples" not in exp:
                errors.append(f"{tid}: training_exposure entry needs "
                              "level+examples")
    return errors


def update_track(matrix: dict, track_id: str, *, checkpoint: str,
                 score: float) -> dict:
    """Record a measurement; keeps best_checkpoint monotone (best = max)."""
    row = matrix["tracks"][track_id]
    row["current_checkpoint"] = checkpoint
    row["current_score"] = score
    if row["best_score"] is None or score >= row["best_score"]:
        row["best_checkpoint"] = checkpoint
        row["best_score"] = score
        row["status"] = STATUS_ACQUIRED
    elif (row["best_score"] - score) * 100 >= row["regression_threshold_pp"]:
        row["status"] = STATUS_REGRESSED
    elif score < row["best_score"]:
        row["status"] = STATUS_AT_RISK
    return row


def record_training_exposure(matrix: dict, track_id: str, level: int,
                             examples: int) -> None:
    matrix["tracks"][track_id]["training_exposure"].append(
        {"level": level, "examples": examples})


def record_eval_exposure(matrix: dict, track_id: str, suite: str,
                         items: int) -> None:
    matrix["tracks"][track_id]["eval_exposure"].append(
        {"suite": suite, "items": items})


def deep_copy_matrix(matrix: dict) -> dict:
    return deepcopy(matrix)


def macro_scores(matrix: dict, checkpoint: str | None = None) -> dict:
    """Macro-average of current_score over the tracks of each macro family.
    Only tracks with a measurement for the requested checkpoint count."""
    sums: dict[str, tuple[float, int]] = {}
    for tid, row in matrix["tracks"].items():
        if checkpoint is not None and row["current_checkpoint"] != checkpoint:
            continue
        if row["current_score"] is None:
            continue
        macro = family_macro(row["family"])
        s, n = sums.get(macro, (0.0, 0))
        sums[macro] = (s + row["current_score"], n + 1)
    out = {}
    for macro in MACROS[:3]:
        s, n = sums.get(macro, (0.0, 0))
        out[macro] = round(s / n, 4) if n else None
    return out