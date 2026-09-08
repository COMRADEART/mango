"""T12 tests — parameter fidelity, provenance, planner schema, adoption
contract, stale-answer defense, unit binding, necessity classifier.

The engine is frozen (T12.1): these tests exercise the fidelity and
adoption layers AROUND it, including the exact T11 mutation failures
they must eliminate (σ=−1→1, p=1.5→0.5, malformed-expression repair).
"""
from __future__ import annotations

import math

import pytest

from sciencemath.scicomp.adoption import (
    ADOPTED, NO_ADOPTION_EXPECTED, NOT_AUTHORITATIVE, RESULT_IGNORED,
    RESULT_MISREAD, STALE_PRECOMPUTE_ANSWER, UNIT_LOST, VERIFIED,
    WRONG_ROUNDING, classify_adoption, conflict_state, observe,
    verified_envelope)
from sciencemath.scicomp.executor import execute
from sciencemath.scicomp.fidelity import (
    DISALLOWED, FIDELITY_FAIL, FIDELITY_OK, NUMERIC_FORMATTING,
    P_MODEL_INVENTED, P_USER_GIVEN, SYMBOL_NORMALIZATION, UNIT_NORMALIZATION,
    WHITESPACE_NORMALIZATION, check_fidelity, classify_transformation,
    semantic_hash, validate_planner_request)
from sciencemath.scicomp.router import (
    NECESSITY_NOT_NEEDED, NECESSITY_OPTIONAL, NECESSITY_REQUIRED,
    compute_necessity)


# --------------------------------------------------------------------------
# T12.2 transformation classification
# --------------------------------------------------------------------------
def test_numeric_formatting_approved():
    r = classify_transformation(2, 2.0)
    assert r["class"] == NUMERIC_FORMATTING
    assert r["semantic_equivalence_verified"] is True


def test_numeric_value_change_disallowed():
    r = classify_transformation(-1, 1)
    assert r["class"] == DISALLOWED  # the σ = −1 → 1 mutation


def test_half_to_unit_mutation_disallowed():
    # T11: p = 1.5 silently became 0.5
    assert classify_transformation(1.5, 0.5)["class"] == DISALLOWED


def test_unit_normalization_approved_and_logged():
    r = classify_transformation("2 km", 2000)
    assert r["class"] == UNIT_NORMALIZATION
    assert r["semantic_equivalence_verified"] is True
    assert r["field_detail"]["from"] == "2 km"


def test_unverified_unit_conversion_disallowed():
    # "3 furlongs" -> 4828.032 is not in the approved unit table
    r = classify_transformation("3 furlongs", 4828.032)
    assert r["class"] == DISALLOWED


def test_value_under_unit_disguise_rejected():
    # claiming a unit normalization that changes the value
    assert classify_transformation("2 km", 3000)["class"] == DISALLOWED


def test_whitespace_normalization_approved():
    r = classify_transformation("x**2 + 1", "x**2+1")
    assert r["class"] == WHITESPACE_NORMALIZATION


def test_symbol_normalization_approved():
    r = classify_transformation("2x", "2*x")
    assert r["class"] == SYMBOL_NORMALIZATION
    assert r["semantic_equivalence_verified"] is True


def test_malformed_expression_repair_disallowed():
    # T11: model 'repaired' "2x +" into a valid expression — silent
    # repair of invalid input is exactly what T12.6 forbids
    assert classify_transformation("2x +", "2*x")["class"] == DISALLOWED


def test_expression_reordering_not_approved():
    assert classify_transformation("x**2 + 1", "1 + x**2")["class"] == \
        DISALLOWED


def test_nan_to_finite_disallowed():
    assert classify_transformation(float("nan"), 0.0)["class"] == DISALLOWED


def test_sweep_shrink_disallowed():
    assert classify_transformation([0.1, 0.5, 1.0], [0.1, 0.5])["class"] == \
        DISALLOWED
    assert classify_transformation(
        {"k": [0.1, 0.5, 1.0]}, {"k": [0.1, 0.5]})["class"] == DISALLOWED


def test_bounds_change_disallowed():
    assert classify_transformation([0, 1], [0, 10])["class"] == DISALLOWED


def test_matrix_entry_change_disallowed():
    assert classify_transformation([[4, 2], [2, 1]], [[4, 2], [2, 2]])[
        "class"] == DISALLOWED


# --------------------------------------------------------------------------
# T12.4 semantic hash
# --------------------------------------------------------------------------
def test_semantic_hash_unifies_int_float():
    assert semantic_hash({"a": 2}) == semantic_hash({"a": 2.0})
    assert semantic_hash({"a": 1, "b": 2}) == semantic_hash(
        {"b": 2.0, "a": 1.0})


def test_semantic_hash_detects_value_change():
    assert semantic_hash({"k": -1}) != semantic_hash({"k": 1})


# --------------------------------------------------------------------------
# T12.3 provenance / T12.7 planner schema
# --------------------------------------------------------------------------
def _req(**over):
    base = {
        "operation": "describe",
        "compute_required": True,
        "parameters": {"values": [1, 2, 3]},
        "source_inputs": {"values": [1, 2, 3]},
        "parameter_provenance": {"values": P_USER_GIVEN},
        "expected_result_type": "object",
        "reason_for_compute": "summary statistics requested",
    }
    base.update(over)
    return base


def test_valid_planner_request_passes():
    assert validate_planner_request(_req())["ok"] is True


def test_missing_required_fields_rejected():
    r = _req()
    del r["source_inputs"]
    out = validate_planner_request(r)
    assert out["ok"] is False
    assert "missing_field:source_inputs" in out["failures"]


def test_missing_provenance_rejected():
    out = validate_planner_request(_req(parameter_provenance={}))
    assert out["ok"] is False
    assert any(f.startswith("provenance_missing") for f in out["failures"])


def test_model_invented_on_protected_field_rejected():
    out = validate_planner_request(_req(parameter_provenance={
        "values": P_MODEL_INVENTED}))
    assert out["ok"] is False
    assert any(f.startswith("model_invented_on_protected")
               for f in out["failures"])


def test_model_selectable_field_may_be_model_chosen():
    r = {
        "operation": "vector_or_matrix_norm",
        "compute_required": True,
        "parameters": {"vector": [3, 4], "norm": "l2"},
        "source_inputs": {"vector": [3, 4]},
        "parameter_provenance": {"vector": P_USER_GIVEN,
                                 "norm": P_MODEL_INVENTED},
        "expected_result_type": "scalar",
        "reason_for_compute": "norm requested",
    }
    assert validate_planner_request(r)["ok"] is True


def test_code_smuggling_keys_rejected():
    out = validate_planner_request(_req(parameters={"values": [1], "code": "x"}))
    assert out["ok"] is False
    assert any(f.startswith("code_key") for f in out["failures"])


# --------------------------------------------------------------------------
# T12.4/T12.6 fidelity gate
# --------------------------------------------------------------------------
def test_fidelity_ok_request_produces_hash_and_envelope():
    q = "Find the mean of the values 1, 2, 3."
    r = check_fidelity(_req(), q)
    assert r.status == FIDELITY_OK
    assert r.envelope["source_parameter_hash"] == semantic_hash(
        {"values": [1, 2, 3]})


def test_fidelity_fails_on_mutation():
    q = "A normal distribution has sigma = -1. Compute its entropy."
    req = _req(operation="describe", parameters={"values": [1.0]},
               source_inputs={"values": [-1.0]})
    r = check_fidelity(req, q)
    assert r.status == FIDELITY_FAIL
    assert any("disallowed_transformation" in f for f in r.failures)


def test_fidelity_fails_on_value_not_in_question():
    # planner invents an initial condition the question never gave
    q = "Solve dy/dt = -2*y with initial condition y(0) = 1."
    req = {
        "operation": "describe",
        "compute_required": True,
        "parameters": {"values": [5.0]},
        "source_inputs": {"values": [5.0]},
        "parameter_provenance": {"values": P_USER_GIVEN},
        "expected_result_type": "object",
        "reason_for_compute": "summary",
    }
    r = check_fidelity(req, q)
    assert r.status == FIDELITY_FAIL
    assert any(f.startswith("value_not_in_question") for f in r.failures)


def test_fidelity_unit_normalization_logged():
    q = "A car travels 2 km. How far is that in meters?"
    req = {
        "operation": "describe",
        "compute_required": True,
        "parameters": {"values": [2000.0]},
        "source_inputs": {"values": ["2 km"]},
        "parameter_provenance": {"values": P_USER_GIVEN},
        "expected_result_type": "object",
        "reason_for_compute": "unit conversion requested",
    }
    r = check_fidelity(req, q)
    assert r.status == FIDELITY_OK
    assert r.normalization_log[0]["reason"] == UNIT_NORMALIZATION
    assert r.normalization_log[0]["semantic_equivalence_verified"] is True


def test_fidelity_derived_grid_allowed_with_log():
    q = "For k in 0.1, 0.5, 1.0 sweep f(k) = k**2."
    req = {
        "operation": "describe",
        "compute_required": True,
        "parameters": {"values": [0.1, 0.5, 1.0]},
        "source_inputs": {"values": [0.1, 0.5, 1.0]},
        "parameter_provenance": {"values": P_USER_GIVEN},
        "expected_result_type": "object",
        "reason_for_compute": "sweep",
    }
    r = check_fidelity(req, q)
    assert r.status == FIDELITY_OK


def test_fidelity_fails_when_protected_source_dropped():
    q = "Using a = 2 and b = 5, compute the determinant of [[a]]."
    req = _req(operation="describe",
               parameters={"values": [2]},
               source_inputs={"values": [2], "b": 5})
    r = check_fidelity(req, q)
    assert r.status == FIDELITY_FAIL
    assert any(f.startswith("source_input_dropped") for f in r.failures)


def test_fidelity_fail_means_do_not_execute():
    """T12.6: a fidelity FAIL must never reach the engine."""
    q = "A normal distribution has sigma = -1."
    req = _req(operation="describe",
               parameters={"values": [1.0]},
               source_inputs={"values": [-1.0]})
    r = check_fidelity(req, q)
    assert r.status == FIDELITY_FAIL
    # the pipeline contract: execute ONLY when fidelity ok
    executed = invoke_wrapper(req, r)
    assert executed is None


def invoke_wrapper(req, fidelity):
    from sciencemath.scicomp.executor import execute
    if not fidelity.ok:
        return None
    return execute({"operation": req["operation"],
                    "inputs": req["parameters"]})


# --------------------------------------------------------------------------
# T12.8/T12.9 necessity classifier
# --------------------------------------------------------------------------
def test_necessity_conceptual_not_needed():
    assert compute_necessity(
        "Why does entropy increase in an isolated system?")["necessity"] \
        == NECESSITY_NOT_NEEDED
    assert compute_necessity(
        "What is the definition of overfitting?")["necessity"] \
        == NECESSITY_NOT_NEEDED


def test_necessity_required_with_data():
    out = compute_necessity(
        "Compute the mean of the values [2.1, 3.4, 5.6].")
    assert out["necessity"] == NECESSITY_REQUIRED


def test_necessity_optional_verb_only():
    out = compute_necessity("Calculate the energy of the reaction.")
    assert out["necessity"] == NECESSITY_OPTIONAL


# --------------------------------------------------------------------------
# T12.11–T12.13 adoption contract
# --------------------------------------------------------------------------
def _verified_doc():
    return {"kind": "COMPUTE_RESULT_ENVELOPE", "status": "PASS",
            "result": 0.848, "diagnostics": {}, "warnings": [],
            "verified": True, "binding": VERIFIED, "result_type": "scalar",
            "units": "", "source_parameter_hash": "abc123",
            "hash_match": True}


def test_pass_envelope_is_verified():
    doc = verified_envelope({"status": "PASS", "result": 5}, "h1")
    assert doc["verified"] is True
    assert doc["binding"] == VERIFIED


def test_warning_envelope_never_authoritative():
    doc = verified_envelope({"status": "NUMERICAL_WARNING",
                             "result": None}, "h1")
    assert doc["binding"] == NOT_AUTHORITATIVE


def test_hash_mismatch_blocks_verification():
    doc = verified_envelope({"status": "PASS", "result": 5,
                             "source_parameter_hash": "other"}, "h1")
    assert doc["verified"] is False
    assert doc["hash_match"] is False


def test_observation_labels_binding():
    text = observe(_verified_doc())
    assert text.startswith("VERIFIED_COMPUTE_RESULT")
    bad = observe({**_verified_doc(), "verified": False,
                   "status": "INVALID_INPUT", "binding": NOT_AUTHORITATIVE,
                   "result": None})
    assert "NOT_AUTHORITATIVE" in bad


# --------------------------------------------------------------------------
# T12.14 taxonomy / T12.17 rounding policy
# --------------------------------------------------------------------------
def test_adopted_exact():
    assert classify_adoption(_verified_doc(), "FINAL ANSWER: 0.848") == \
        ADOPTED


def test_adopted_within_rounding_tolerance():
    doc = _verified_doc()
    assert classify_adoption(doc, "FINAL ANSWER: 0.8480", atol=1e-3) == \
        ADOPTED


def test_reasonable_rounding_not_failure_but_out_of_tol_is():
    doc = _verified_doc()
    # T11 misread case: 0.20012 -> 0.2001 with atol 1e-8: WRONG_ROUNDING
    doc2 = {**doc, "result": 0.20012}
    assert classify_adoption(doc2, "FINAL ANSWER: 0.2001",
                             atol=1e-8, rtol=0) == WRONG_ROUNDING
    assert classify_adoption(doc2, "FINAL ANSWER: 0.21",
                             atol=1e-8, rtol=0) == RESULT_MISREAD


def test_result_ignored_when_no_number():
    assert classify_adoption(_verified_doc(), "The computation succeeded.") \
        == RESULT_IGNORED


def test_result_misread_when_different_number():
    assert classify_adoption(_verified_doc(), "FINAL ANSWER: 1.2") == \
        RESULT_MISREAD


def test_stale_precompute_answer_detected():
    doc = _verified_doc()
    assert classify_adoption(doc, "FINAL ANSWER: 0.7", atol=0, rtol=0,
                             precompute_answer="I first estimated 0.7") \
        == STALE_PRECOMPUTE_ANSWER


def test_unit_lost_detected():
    doc = {**_verified_doc(), "units": "m/s", "result": 12.4}
    assert classify_adoption(doc, "The speed is 12.4 m",
                             atol=0, rtol=0) == UNIT_LOST


def test_unit_consistent_ok():
    doc = {**_verified_doc(), "units": "m/s", "result": 12.4}
    assert classify_adoption(doc, "The speed is 12.4 m/s",
                             atol=0, rtol=0) == ADOPTED


def test_non_pass_expects_rejection_not_adoption():
    doc = {**_verified_doc(), "status": "INVALID_INPUT", "result": None,
           "verified": False, "binding": NOT_AUTHORITATIVE}
    assert classify_adoption(doc, "I cannot compute this.") == \
        NO_ADOPTION_EXPECTED


# --------------------------------------------------------------------------
# T12.15 stale-answer defense
# --------------------------------------------------------------------------
def test_conflict_state_prefers_verified():
    st = conflict_state("about 0.7", "0.848")
    assert st["conflict"] is True
    assert st["policy"] == "PREFER_VERIFIED_RESULT"


def test_conflict_state_agreement_no_conflict():
    st = conflict_state("roughly 0.848", "FINAL: 0.848")
    assert st["conflict"] is False


# --------------------------------------------------------------------------
# engine untouched end-to-end: a fidelity-clean request still executes
# --------------------------------------------------------------------------
def test_clean_request_executes_through_frozen_engine():
    req = {
        "operation": "describe",
        "compute_required": True,
        "parameters": {"values": [1.0, 2.0, 3.0]},
        "source_inputs": {"values": [1.0, 2.0, 3.0]},
        "parameter_provenance": {"values": P_USER_GIVEN},
        "expected_result_type": "object",
        "reason_for_compute": "summary statistics",
    }
    fid = check_fidelity(req, "Describe the values 1.0, 2.0, 3.0.")
    assert fid.status == FIDELITY_OK
    env = execute({"operation": req["operation"],
                   "inputs": req["parameters"]})
    assert env["status"] == "PASS"
    doc = verified_envelope(env, fid.source_parameter_hash)
    assert doc["verified"] is True