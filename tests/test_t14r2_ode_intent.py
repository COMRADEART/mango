"""T14R2 — unit tests for the deterministic ODE intent layer
(src/sciencemath/scicomp/ode_intent.py).

Covers the milestone's contract requirements:
  T14R2.4  IVP recognition only when ALL required info is present
  T14R2.5  ODE_IVP separated from other operations by structure
  T14R2.6  required-field validation; null/missing/zero distinct
  T14R2.7  deterministic operation selection (no LLM)
  T14R2.8  no parameter invention (fail-closed on undeclared symbols)
  T14R2.9  explicit state ordering; fail-closed on ambiguity
  T14R2.10 second-order -> first-order-system conversion only
"""
from __future__ import annotations

import math

import pytest

from sciencemath.scicomp.ode_intent import (
    _eval_literal, construct_solve_ode_request, recognize_ode_ivp,
    select_ode_operation)

Q0081 = ("A population grows as dP/dt = 0.3*P with P(0) = 2 "
         "(in hundreds). What is P at t = 5 (in hundreds)?")
Q0082 = ("A radioactive sample decays with rate constant 0.02 per year. "
         "Starting from 10 grams, how many grams remain after 100 years?")
Q0083 = "dQ/dt = -Q/3 with Q(0) = 9. What is Q at t = 6?"
Q0084 = ("A capacitor discharges: dV/dt = -V/RC with RC = 2 s and "
         "V(0) = 12 V. What is V at t = 4 s?")
Q0085 = ("For d2x/dt2 = -4*x with x(0)=1 and dx/dt(0)=0, what is x at "
         "t = pi/2 (use the exact analytic solution)?")
Q0087 = ("A ball dropped from rest accelerates at g = 9.8 m/s^2: "
         "dv/dt = 9.8, v(0) = 0. What is its velocity at t = 3 s?")
Q0088 = ("dN/dt = r*N with r = 0.07 per year and N(0) = 1000. What is N "
         "after 10 years (to the nearest integer)?")

SIX = [Q0081, Q0082, Q0083, Q0084, Q0087, Q0088]


# --------------------------------------------------------------------------
# T14R2.4 / T14R2.5 — recognition
# --------------------------------------------------------------------------
def test_six_frozen_failures_are_recognized_as_ivps():
    for q in SIX:
        ivp = recognize_ode_ivp(q)
        assert ivp is not None, q


def test_second_order_audit_row_recognized():
    ivp = recognize_ode_ivp(Q0085)
    assert ivp is not None and ivp.order == 2
    assert ivp.equations == ["y1", "-4*y0"]
    assert ivp.initial_state == [1.0, 0.0]
    assert math.isclose(ivp.t_end, math.pi / 2, rel_tol=1e-12)


def test_recognition_extracts_verbatim_values():
    ivp = recognize_ode_ivp(Q0081)
    assert ivp.equations == ["0.3*y0"]
    assert ivp.initial_state == [2.0]
    assert ivp.t_start == 0.0 and ivp.t_end == 5.0
    assert ivp.t_start_provenance == "USER_GIVEN"
    assert ivp.t_end_provenance == "USER_GIVEN"


def test_declared_parameter_is_captured_not_invented():
    ivp = recognize_ode_ivp(Q0084)
    assert ivp.parameters == {"RC": 2.0}
    assert ivp.equations == ["-y0/RC"]


def test_verbal_decay_rate_law():
    ivp = recognize_ode_ivp(Q0082)
    assert ivp is not None
    assert ivp.source_kind == "verbal_rate_law"
    assert ivp.initial_state == [10.0]
    assert ivp.t_end == 100.0
    assert ivp.equations == ["-0.02*y0"]


# --------------------------------------------------------------------------
# T14R2.4 / T14R2.6 — fail-closed on incomplete IVP information
# --------------------------------------------------------------------------
def test_missing_initial_condition_refuses():
    assert recognize_ode_ivp(
        "dP/dt = 0.3*P. What is P at t = 5?") is None


def test_missing_evaluation_time_refuses():
    assert recognize_ode_ivp(
        "dP/dt = 0.3*P with P(0) = 2. What is the growth rate?") is None


def test_undeclared_symbol_refuses_never_invents():
    # k never has a value in the question -> fail closed (T14R2.8)
    assert recognize_ode_ivp(
        "dP/dt = k*P with P(0) = 2. What is P at t = 5?") is None


def test_boundary_value_shape_refuses():
    # conditions at two different times: not an IVP (T14R2.5)
    assert recognize_ode_ivp(
        "dP/dt = 0.3*P with P(0) = 2 and P(10) = 5. What is P at t = 20?"
    ) is None


def test_degenerate_span_refuses():
    assert recognize_ode_ivp(
        "dP/dt = 0.3*P with P(0) = 2. What is P at t = 0?") is None


def test_second_order_with_one_ic_refuses():
    assert recognize_ode_ivp(
        "d2x/dt2 = -4*x with x(0)=1. What is x at t = 2?") is None


def test_algebraic_equation_is_not_an_ivp():
    assert recognize_ode_ivp(
        "Solve 3*x + 2 = 14 for x.") is None


def test_definite_integral_question_is_not_an_ivp():
    assert recognize_ode_ivp(
        "What is the integral of 0.3*t from t = 0 to t = 5?") is None


def test_zero_initial_condition_is_distinct_from_missing():
    # v(0) = 0 is a real zero value, not a missing field (T14R2.6)
    ivp = recognize_ode_ivp(Q0087)
    assert ivp is not None and ivp.initial_state == [0.0]


# --------------------------------------------------------------------------
# T14R2.7 / T14R2.8 — deterministic request construction
# --------------------------------------------------------------------------
def test_constructed_request_shape_and_provenance():
    req = construct_solve_ode_request(recognize_ode_ivp(Q0081), Q0081)
    assert req["operation"] == "solve_ode"
    assert req["parameters"] == {"equations": ["0.3*y0"],
                                 "initial_state": [2.0],
                                 "t_start": 0.0, "t_end": 5.0}
    assert req["source_inputs"] == req["parameters"]
    prov = req["parameter_provenance"]
    assert prov["equations"] == "DETERMINISTIC_DERIVATION"
    assert prov["initial_state"] == "USER_GIVEN"
    assert "MODEL_INVENTED" not in json_dumps(prov)


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj)


def test_constructed_request_is_deterministic():
    a = construct_solve_ode_request(recognize_ode_ivp(Q0088), Q0088)
    b = construct_solve_ode_request(recognize_ode_ivp(Q0088), Q0088)
    assert a == b


def test_verbal_t_start_is_derived_not_invented():
    req = construct_solve_ode_request(recognize_ode_ivp(Q0082), Q0082)
    assert req["parameter_provenance"]["t_start"] == \
        "DETERMINISTIC_DERIVATION"
    assert req["parameter_provenance"]["t_end"] == "USER_GIVEN"


# --------------------------------------------------------------------------
# T14R2.9 — state ordering
# --------------------------------------------------------------------------
def test_two_state_system_preserves_appearance_order():
    q = ("dx/dt = y with x(0) = 1 and dy/dt = -x with y(0) = 0. "
         "What is x at t = 2?")
    ivp = recognize_ode_ivp(q)
    assert ivp is not None
    assert ivp.dep_vars == ["x", "y"]
    # dx/dt = y -> y1 ; dy/dt = -x -> -y0 (rename by appearance order)
    assert ivp.equations == ["y1", "-y0"]
    assert ivp.initial_state == [1.0, 0.0]
    req = construct_solve_ode_request(ivp, q)
    assert req["expected_result_type"] == "vector"
    assert req["parameters"]["equations"] == ["y1", "-y0"]
    assert req["parameters"]["initial_state"] == [1.0, 0.0]


def test_three_state_system_refuses_out_of_scope():
    q = ("dx/dt = 1 with x(0) = 0 and dy/dt = 1 with y(0) = 0 and "
         "dz/dt = 1 with z(0) = 0. What is x at t = 2?")
    assert recognize_ode_ivp(q) is None


# --------------------------------------------------------------------------
# firing rule (pipeline entry)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("q", SIX)
def test_fires_on_wrong_operation(q):
    wrong = {"operation": "definite_integral",
             "parameters": {}, "source_inputs": {}}
    out = select_ode_operation(wrong, q)
    assert out is not None
    assert out["request"]["operation"] == "solve_ode"
    assert out["meta"]["reason"] == "WRONG_OPERATION_REMAPPED"


def test_no_fire_on_first_order_solve_ode_request():
    # minimal intervention: the existing path handles these (0075-0080,
    # 0086, 0195 in the frozen suite)
    req = {"operation": "solve_ode",
           "parameters": {"equations": ["-y0"], "initial_state": [1.0],
                          "t_start": 0, "t_end": 1},
           "source_inputs": {"equations": ["-y0"], "initial_state": [1.0],
                             "t_start": 0, "t_end": 1}}
    assert select_ode_operation(req, Q0083) is None


def test_fires_second_order_conversion_on_solve_ode_request():
    bad = {"operation": "solve_ode",
           "parameters": {"equations": ["d2x/dt2 + 4*x = 0"],
                          "initial_state": [1.0], "t_start": 0,
                          "t_end": "pi/2"},
           "source_inputs": {}}
    out = select_ode_operation(bad, Q0085)
    assert out is not None
    assert out["meta"]["reason"] == "SECOND_ORDER_SYSTEM_CONVERSION"
    assert out["request"]["parameters"]["equations"] == ["y1", "-4*y0"]


def test_no_fire_when_recognition_refuses():
    wrong = {"operation": "definite_integral", "parameters": {}}
    assert select_ode_operation(
        wrong, "What is the integral of t^2 from 0 to 3?") is None


def test_no_fire_on_adversarial_blowup_row_shape():
    # 0182: planner already chose solve_ode (first order) -> untouched
    req = {"operation": "solve_ode",
           "parameters": {"equations": ["y0 - y*y"],
                          "initial_state": [1.0], "t_start": 0,
                          "t_end": 100},
           "source_inputs": {}}
    assert select_ode_operation(
        req, "Solve dy/dt = y*y with y(0) = 1 up to t = 100.") is None


# --------------------------------------------------------------------------
# bounded literal evaluation
# --------------------------------------------------------------------------
def test_eval_literal_bounded_family():
    assert math.isclose(_eval_literal("pi/2"), math.pi / 2, rel_tol=1e-12)
    assert math.isclose(_eval_literal("2*pi"), 2 * math.pi, rel_tol=1e-12)
    assert _eval_literal("1e6") == 1e6
    assert _eval_literal("sqrt(2)") is None      # functions not allowed
    assert _eval_literal("__import__('os')") is None
    assert _eval_literal("x") is None
    assert _eval_literal("pi ** 2") is not None