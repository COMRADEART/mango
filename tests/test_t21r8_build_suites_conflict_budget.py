"""Regression controls for deterministic T21R8 conflict composition.

These tests use synthetic dictionaries only.  They do not read or generate
the preserved R8 blind world and execute no Mango runtime path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from t21r8_build_suites import compose_conflict_suite  # noqa: E402


PARTIAL_TAG = "partial_path_ie_stress"


def _row(index: int, partial: bool, flavor: str = "alpha") -> dict:
    return {
        "synthetic_index": index,
        "construction_tags": [PARTIAL_TAG] if partial else [],
        "arbitrary_payload": {
            "entity": f"{flavor}-entity-{index}",
            "query": f"{flavor} query wording {index}",
        },
    }


def test_preregistered_conflict_shape_composes_exactly() -> None:
    partial_positions = set(range(0, 552, 2))  # exactly 276 positions
    existing = [_row(index, index in partial_positions)
                for index in range(750)]
    generated = [{"generated_index": index} for index in range(90)]

    result = compose_conflict_suite(existing, generated, 800)

    expected_existing: list[dict] = []
    optional_kept = 0
    for row in existing:
        if PARTIAL_TAG in row["construction_tags"]:
            expected_existing.append(row)
        elif optional_kept < 434:
            expected_existing.append(row)
            optional_kept += 1

    kept_existing = result[:-len(generated)]
    assert len(result) == 800
    assert kept_existing == expected_existing
    assert sum(PARTIAL_TAG in row["construction_tags"]
               for row in kept_existing) == 276
    assert sum(PARTIAL_TAG not in row["construction_tags"]
               for row in kept_existing) == 434
    assert result[-len(generated):] == generated


def test_generated_plus_mandatory_over_target_fails_explicitly() -> None:
    existing = [_row(index, partial=True) for index in range(3)]
    generated = [{"generated_index": index} for index in range(3)]
    with pytest.raises(
        AssertionError,
        match=r"generated IE \+ mandatory partial rows exceed target",
    ):
        compose_conflict_suite(existing, generated, 5)


def test_insufficient_optional_material_fails_explicitly() -> None:
    existing = [_row(0, partial=True), _row(1, partial=False)]
    generated = [{"generated_index": 0}]
    with pytest.raises(AssertionError, match="insufficient conflict material"):
        compose_conflict_suite(existing, generated, 5)


def test_exact_target_requires_no_unnecessary_trimming() -> None:
    existing = [
        _row(0, partial=False),
        _row(1, partial=True),
        _row(2, partial=False),
        _row(3, partial=True),
    ]
    generated = [{"generated_index": 0}]
    assert compose_conflict_suite(existing, generated, 5) == (
        existing + generated)


def test_composition_is_independent_of_row_entity_and_query_content() -> None:
    partial_positions = {1, 4}
    alpha = [_row(index, index in partial_positions, "alpha")
             for index in range(6)]
    omega = [_row(index, index in partial_positions, "totally-different")
             for index in range(6)]
    generated_alpha = [{"generated": "alpha"}]
    generated_omega = [{"generated": "omega"}]

    selected_alpha = compose_conflict_suite(alpha, generated_alpha, 5)
    selected_omega = compose_conflict_suite(omega, generated_omega, 5)

    assert [row["synthetic_index"] for row in selected_alpha[:-1]] == [
        row["synthetic_index"] for row in selected_omega[:-1]]
    assert selected_alpha[-1:] == generated_alpha
    assert selected_omega[-1:] == generated_omega
