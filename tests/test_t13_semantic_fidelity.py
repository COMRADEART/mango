"""T13 required test battery — semantic fidelity classifier.

Covers the T13 final-report test matrix:
int/float equivalence, tuple/list, strict fidelity, empty container,
null vs zero, vector length, matrix shape, unit conversion, provenance
mismatch, information insertion/removal, reordered state vectors,
non-crash (T12-DEF-1), T12-DEF-2 restatement recovery, false-acceptance
discipline, and positive faithful cases.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp import semantic as sem
from sciencemath.scicomp.fidelity import (
    FIDELITY_FAIL, FIDELITY_OK, P_MODEL_INVENTED, P_USER_GIVEN,
    check_fidelity, classify_transformation, semantic_hash,
    validate_planner_request)

N = sem.ROLE_NUMBER
NL = sem.ROLE_NUMBER_LIST
NM = sem.ROLE_NUMBER_MATRIX


def _req(op, params, srcs=None, prov=None, question="Q"):
    request = {
        "operation": op,
        "compute_required": True,
        "parameters": params,
        "source_inputs": srcs if srcs is not None else dict(params),
        "parameter_provenance": prov or {k: P_USER_GIVEN
                                         for k in params},
        "expected_result_type": "scalar",
        "reason_for_compute": "test",
    }
    return request, question


# ---------------------------------------------------------------------------
# transform-level classification
# ---------------------------------------------------------------------------
def test_int_float_equivalence():
    v = classify_transformation(2, 2.0, N)
    assert v["semantic_equivalence_verified"]
    assert v["t13_class"] == "REPRESENTATION_EQUIVALENT"


def test_tuple_list_equivalence():
    v = classify_transformation((1, 2), [1.0, 2.0], NL)
    assert v["semantic_equivalence_verified"]
    assert v["t13_class"] in ("EXACT", "REPRESENTATION_EQUIVALENT")


def test_numeric_string_source_is_representation_equivalent():
    v = classify_transformation("3.5", 3.5, N)
    assert v["semantic_equivalence_verified"]
    assert v["t13_class"] == "REPRESENTATION_EQUIVALENT"


def test_structured_numeric_string_is_schema_type_violation():
    # rule 3: the structured (compute) side is the schema-typed side;
    # a numeric STRING there is a TYPE_SEMANTICS_CHANGED, never parsed.
    v = classify_transformation(3.5, "3.5", N)
    assert not v["semantic_equivalence_verified"]
    assert v["t13_class"] == "TYPE_SEMANTICS_CHANGED"


def test_beyond_representation_drift_is_value_changed():
    v = classify_transformation(2.0, 2.0001, N)
    assert not v["semantic_equivalence_verified"]
    assert v["t13_class"] == "VALUE_CHANGED"


def test_unit_conversion_canonical():
    v = classify_transformation("2 km", 2000.0, N)
    assert v["semantic_equivalence_verified"]
    assert v["t13_class"] == "UNIT_EQUIVALENT"


def test_unit_value_mismatch_rejected():
    v = classify_transformation("2 km", 3000.0, N)
    assert not v["semantic_equivalence_verified"]
    assert v["t13_class"] == "VALUE_CHANGED"


def test_matrix_literal_structure_equivalent():
    v = classify_transformation("[ 2 1; 1 3 ]", [[2, 1], [1, 3]], NM)
    assert v["semantic_equivalence_verified"]
    assert v["t13_class"] == "STRUCTURE_EQUIVALENT"


def test_matrix_shape_change_rejected():
    v = classify_transformation("[ 1 2; 3 4 ]", [[1, 2, 3], [4, 5, 6]], NM)
    assert not v["semantic_equivalence_verified"]


def test_vector_length_change_rejected():
    v = classify_transformation([1, 2, 3], [1, 2], NL)
    assert not v["semantic_equivalence_verified"]
    assert v["t13_class"] in ("TYPE_SEMANTICS_CHANGED", "VALUE_CHANGED")


def test_null_is_not_zero():
    assert not sem.cross_kind_classify(None, 0.0, N)[
        "semantic_equivalence_verified"]
    assert sem.cross_kind_classify(None, 0.0, N)["t13_class"] == \
        "VALUE_CHANGED"


def test_empty_is_not_zero():
    v = sem.cross_kind_classify([], 0.0, NL)
    assert not v["semantic_equivalence_verified"]


def test_invalid_normalization():
    v = classify_transformation("many", 7.0, N)
    assert not v["semantic_equivalence_verified"]
    assert v["t13_class"] == "INVALID_NORMALIZATION"


def test_reordered_state_vector_rejected():
    # order is semantic for state vectors
    v = classify_transformation([1.0, 2.0], [2.0, 1.0], NL)
    assert not v["semantic_equivalence_verified"]


# ---------------------------------------------------------------------------
# request-level fidelity
# ---------------------------------------------------------------------------
def test_ode_restatement_resolvers_cover_renamed_forms():
    req, q = _req(
        "solve_ode",
        {"equations": ["-2*y0"], "initial_state": [1.0],
         "t_start": 0.0, "t_end": 1.0, "parameters": {"k": 2.0}},
        srcs={"equations": "dy/dt = -2*y", "y(0)": 1, "k": 2, "t": 1},
        question="Solve the ODE dy/dt = -2*y with y(0) = 1, k = 2, t = 1.")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_OK


def test_scalar_bounds_restatement():
    req, q = _req(
        "minimize_scalar",
        {"expression": "(x - 3)**2", "bound_low": -10.0,
         "bound_high": 10.0},
        srcs={"expression": "f(x) = (x - 3)**2", "x": "in [-10, 10]"},
        question="Minimize f(x) = (x - 3)**2 over x in [-10, 10].")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_OK


def test_empty_container_request_no_crash_and_ok():
    # T12-DEF-1 / mfid-v1-0020: empty container must classify, not crash
    req, q = _req("solve_ode",
                  {"equations": ["3*y0"], "initial_state": [],
                   "t_start": 0.0, "t_end": 1.0},
                  question="Solve dy/dt = 3*y with no initial condition "
                           "given, from t = 0 to t = 1.")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_OK


def test_null_vs_zero_request():
    req, q = _req("solve_ode",
                  {"equations": ["3*y0"], "initial_state": [0.0],
                   "t_start": 0.0, "t_end": 1.0},
                  srcs={"equations": ["3*y0"], "initial_state": [None],
                        "t_start": 0.0, "t_end": 1.0},
                  question="y(0) unset")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_FAIL


def test_information_removed_rejected():
    # the question never states an initial condition, yet the structured
    # request carries initial_state — a given value would be invented
    req, q = _req(
        "solve_ode",
        {"equations": ["-2*y0"], "initial_state": [1.0],
         "t_start": 0.0, "t_end": 1.0},
        srcs={"equations": "dy/dt = -2*y", "t": 1},
        question="Solve the ODE dy/dt = -2*y from t = 0 to t = 1.")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_FAIL


def test_information_added_rejected():
    req, q = _req(
        "solve_ode",
        {"equations": ["-2*y0"], "initial_state": [1.0],
         "t_start": 0.0, "t_end": 1.0},
        srcs={"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1,
              "k": 3},
        question="Solve the ODE dy/dt = -2*y with initial condition "
                 "y(0) = 1 and parameter k = 3 from t = 0 to t = 1.")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_FAIL


def test_provenance_mismatch_rejected_at_schema_gate():
    request, q = _req("determinant", {"matrix": [[2, 1], [1, 3]]})
    request["parameter_provenance"] = {"matrix": P_MODEL_INVENTED}
    schema = validate_planner_request(request)
    assert not schema["ok"]
    assert any("MODEL_INVENTED" in f or "protected" in f
               for f in schema["failures"])


def test_silent_value_mutation_rejected_false_acceptance_zero():
    # T13.12 discipline: a silent repair must never be accepted
    req, q = _req("determinant",
                  {"matrix": [[4, 2], [2, 2]]},
                  srcs={"matrix": [[4, 2], [2, 1]]},
                  question="entries 4, 2, 2, 1")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_FAIL


def test_semantic_hash_inf_safe():
    # T13.16 regression: inf must not raise OverflowError
    h = semantic_hash({"values": [1.0, float("inf"), 3.0]})
    assert isinstance(h, str) and len(h) == 64
    assert semantic_hash({"values": [1.0, float("inf"), 3.0]}) == h


def test_t12_def2_matrix_literal_recovery():
    # T12-DEF-2 canonical row msc-v1-0009
    req, q = _req("determinant", {"matrix": [[2, 1], [1, 3]]},
                  srcs={"matrix": "[ 2 1; 1 3 ]"},
                  question="What is the determinant of the 2x2 matrix "
                           "[ 2 1; 1 3 ]?")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_OK


def test_schema_typed_numeric_string_still_rejected():
    # structured side carries a numeric STRING for initial_state
    # (T12-DEF-2 rows 0075/0080): values faithful, types schema-invalid.
    req, q = _req(
        "solve_ode",
        {"equations": ["-2*y0"], "initial_state": ["1"],
         "t_start": 0.0, "t_end": 1.0},
        srcs={"equations": "dy/dt = -2*y", "y(0)": "1", "t": 1},
        question="Solve the ODE dy/dt = -2*y with initial condition "
                 "y(0) = 1 from t = 0 to t = 1.")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_FAIL
    assert any("SCHEMA_TYPE_STRING_FOR_NUMBER" in f
               for f in fid.failures)


def test_strict_fidelity_rejects_partial_drift_in_map():
    req, q = _req("solve_ode",
                  {"equations": ["k*-2*y0"], "initial_state": [1.0],
                   "t_start": 0.0, "t_end": 1.0,
                   "parameters": {"k": 2.5}},
                  srcs={"equations": "dy/dt = k*-2*y", "y(0)": 1,
                        "t": 1, "k": 2},
                  question="Solve the ODE dy/dt = k*-2*y with initial "
                           "condition y(0) = 1, parameter k = 2, from "
                           "t = 0 to t = 1.")
    fid = check_fidelity(req, q)
    assert fid.status == FIDELITY_FAIL


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))