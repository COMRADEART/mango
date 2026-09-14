"""T14R.23 — the 13 mandated behaviors of the T14R repair layers.

1.  provenance auto-binding
2.  unknown provenance fail-closed
3.  verified result envelope
4.  result type binding
5.  rounding explicit decimals
6.  rounding significant figures
7.  default precision
8.  no benchmark leakage
9.  unit preservation
10. stale answer invalidation
11. diagnostic/result distinction
12. vector/matrix adoption
13. scientific notation
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from sciencemath.scicomp.adoption import (
    NOT_AUTHORITATIVE, VERIFIED, classify_adoption, verified_envelope)
from sciencemath.scicomp.planner_repair import (
    PROVENANCE_UNKNOWN, repair_planner_request)
from sciencemath.scicomp.result_contract import (
    NOT_CONTRACTABLE, display_value, format_policy, observe_contract,
    result_contract, unit_guard)


def _env(status="PASS", result=None, units="", binding=None):
    if binding is None:
        binding = VERIFIED if status == "PASS" else NOT_AUTHORITATIVE
    return {"binding": binding, "status": status, "result": result,
            "units": units, "warnings": [],
            "source_parameter_hash": "hash-000"}


def _req(op, params=None, srcs=None, prov=None, ert=None):
    return {"operation": op, "compute_required": True,
            "parameters": params or {}, "source_inputs": srcs or {},
            "parameter_provenance": prov or {},
            "expected_result_type": ert or "SCALAR",
            "reason_for_compute": "test"}


# 1. provenance auto-binding ------------------------------------------------
def test_provenance_auto_binding():
    r = repair_planner_request(
        _req("definite_integral",
             {"expression": "2*x", "lower": 0, "upper": 3},
             {"lower": 0, "upper": 3}, {"upper": "USER_GIVEN"}),
        "integrate 2*x from 0 to 3")
    prov = r["request"]["parameter_provenance"]
    # lower was not given provenance but IS a question-given number
    assert prov["lower"] in ("USER_GIVEN", "RETRIEVED_VERIFIED",
                             "DETERMINISTIC_DERIVATION")
    assert prov["upper"] == "USER_GIVEN"
    # every bound parameter carries value + provenance + source span +
    # semantic hash in the bindings audit metadata
    assert r["bindings"], "binding metadata must be recorded"


# 2. unknown provenance fail-closed -----------------------------------------
def test_unknown_provenance_fail_closed():
    from sciencemath.scicomp.fidelity import (
        FIDELITY_FAIL, validate_planner_request, check_fidelity)
    q = "integrate 2*x from 0 to 3"
    r = repair_planner_request(
        _req("definite_integral",
             {"expression": "2*x", "lower": 0, "upper": 3},
             {"lower": 0, "upper": 3}, {"upper": PROVENANCE_UNKNOWN}), q)
    # PROVENANCE_UNKNOWN is not an allowed provenance constant: the
    # repair either fails closed (keeps unknown and records it) and the
    # frozen gates reject, or replaces it with a verifiable origin.
    assert r["unknown_provenance"] or all(
        v != PROVENANCE_UNKNOWN
        for v in r["request"]["parameter_provenance"].values())
    # whichever way: a value that cannot establish provenance must never
    # be labeled USER_GIVEN
    for k, v in r["request"]["parameter_provenance"].items():
        if v == "USER_GIVEN":
            assert r["request"]["source_inputs"].get(k) is not None
    # a model-invented value must not be relabeled USER_GIVEN by repair
    r2 = repair_planner_request(
        _req("definite_integral",
             {"expression": "2*x", "lower": 0, "upper": 12345.678},
             {"upper": 12345.678}, {"upper": "MODEL_INVENTED"}), q)
    assert r2["request"]["parameter_provenance"]["upper"] \
        != "USER_GIVEN"


# 3. verified result envelope ------------------------------------------------
def test_verified_result_envelope():
    doc = verified_envelope(
        {"status": "PASS", "result": {"integral": 3.0}, "units": "",
         "warnings": []}, "abc")
    assert doc["binding"] == VERIFIED
    doc2 = verified_envelope(
        {"status": "FAIL", "result": None, "units": "", "warnings": []},
        "abc")
    assert doc2["binding"] == NOT_AUTHORITATIVE
    c = result_contract(doc2, {"operation": "definite_integral"}, "q")
    assert c["binding"] == NOT_AUTHORITATIVE
    assert "not present" in observe_contract(c).lower() or \
        "DO NOT" in observe_contract(c)


# 4. result type binding -----------------------------------------------------
def test_result_type_binding():
    env = _env(result={"optimum_x": 1.5, "optimum_value": -2.25,
                       "optimum_kind": "local"})
    # OPTIMUM_LOCATION binds optimum_x, never optimum_value
    c = result_contract(env, {"operation": "minimize_scalar",
                              "expected_result_type": "OPTIMUM_LOCATION"},
                        "where is the minimum?")
    assert c["authoritative_field"] == "optimum_x"
    assert c["authoritative_value"] == 1.5
    c2 = result_contract(env, {"operation": "minimize_scalar",
                               "expected_result_type": "OPTIMUM_VALUE"},
                         "what is the minimum value?")
    assert c2["authoritative_field"] == "optimum_value"
    # fine-grained mismatch fail-closes
    c3 = result_contract(_env(result={"root": [1.0, 2.0]}),
                         {"operation": "scalar_root",
                          "expected_result_type": "ROOT"}, "q")
    assert c3["binding"] == NOT_CONTRACTABLE


# 5. rounding explicit decimals ----------------------------------------------
def test_rounding_explicit_decimals():
    pol = format_policy("round the result to 3 decimal places")
    assert pol == {"policy": "DECIMAL_PLACES", "decimals": 3}
    d = display_value(3.14159265, pol)
    assert d["raw_value"] == 3.14159265
    assert d["display_value"] == 3.142
    assert d["rounding_rule"] == "ROUND_HALF_EVEN_3dp"


# 6. rounding significant figures -------------------------------------------
def test_rounding_significant_figures():
    pol = format_policy("report with 2 significant figures")
    assert pol["policy"] == "SIGNIFICANT_FIGURES"
    d = display_value(0.0034567, pol)
    assert d["display_value"] == 0.0035
    assert d["rounding_rule"] == "ROUND_2_SIGNIFICANT_FIGURES"


# 7. default precision -------------------------------------------------------
def test_default_precision():
    pol = format_policy("what is the integral?")
    assert pol["policy"] == "DEFAULT_SAFE_DISPLAY"
    d = display_value(3.141592653589793, pol)
    assert d["display_value"] == d["raw_value"]  # raw preserved
    assert "DEFAULT_SAFE_DISPLAY" in d["rounding_rule"]


# 8. no benchmark leakage ----------------------------------------------------
def test_no_benchmark_leakage():
    # the policy is a pure function of question text: an expected-answer
    # value present in a caller-provided 'expected' string can never
    # influence it because format_policy has no expected parameter
    import inspect
    from sciencemath.scicomp.result_contract import format_policy as fp
    assert "expected" not in inspect.signature(fp).parameters
    # and result_contract reads precision only from the question text
    env = _env(result={"integral": 3.14159265})
    c = result_contract(env, {"operation": "definite_integral"},
                        "compute it. expected: 3.1")
    assert c["display"]["rounding_rule"].endswith("RAW_AS_COMPUTED")


# 9. unit preservation -------------------------------------------------------
def test_unit_preservation():
    g = unit_guard("m/s", "the speed is 12 m")
    assert g["violation"] is True
    assert unit_guard("m/s", "12 m/s")["violation"] is False
    d = classify_adoption(_env(result={"integral": 12.5}, units="m/s"),
                          "FINAL ANSWER: 12.5 m")
    assert d == "UNIT_LOST"
    d2 = classify_adoption(_env(result={"integral": 12.5}, units="m/s"),
                           "FINAL ANSWER: 12.5 m/s")
    assert d2 == "ADOPTED"


# 10. stale answer invalidation ---------------------------------------------
def test_stale_answer_invalidation():
    env = _env(result={"integral": 42.0})
    # retention: verified absent, stale present
    assert classify_adoption(env, "FINAL ANSWER: 40",
                             precompute_answer="40") \
        == "STALE_PRECOMPUTE_ANSWER"
    # supersession: the verified value in the final answer wins
    assert classify_adoption(env, "FINAL ANSWER: 42.0",
                             precompute_answer="40") == "ADOPTED"
    c = result_contract(env, {"operation": "definite_integral"},
                        "integrate")
    assert c["stale_policy"] == "PREFER_VERIFIED_RESULT"
    assert "superseded" in observe_contract(c)


# 11. diagnostic/result distinction -----------------------------------------
def test_diagnostic_result_distinction():
    # padded payload: residual/estimate siblings must not be selected
    env = _env(result={"optimum_x": 1.5, "optimum_value": -2.25,
                       "residual_norm": 0.001, "iterations": 12})
    c = result_contract(env, {"operation": "minimize",
                              "expected_result_type": "OPTIMUM_LOCATION"},
                        "argmin?")
    assert c["authoritative_field"] == "optimum_x"
    assert c["authoritative_value"] == 1.5
    # a NON-PASS envelope is never authoritative even with a result body
    c2 = result_contract(
        _env(status="NUMERICAL_WARNING",
             result={"root": 0.2526802}),
        {"operation": "scalar_root"}, "q")
    assert c2["binding"] == NOT_AUTHORITATIVE
    obs = observe_contract(c2)
    assert "NOT_USABLE" in obs or "not present" in obs.lower()


# 12. vector/matrix adoption -------------------------------------------------
def test_vector_matrix_adoption():
    env = _env(result={"final_state": [1.35335283, 0.0],
                       "final_time": 2.0})
    c = result_contract(env, {"operation": "solve_ode",
                              "expected_result_type": "ODE_FINAL_STATE"},
                        "final state?")
    assert c["binding"] == VERIFIED
    assert c["authoritative_value"] == [1.35335283, 0.0]
    assert c["policy"] == "ADOPT_VERIFIED_SEQUENCE"
    cls = classify_adoption(env, "FINAL ANSWER: [1.35335283, 0.0]",
                            authoritative_field="final_state")
    assert cls == "ADOPTED"
    m = result_contract(_env(result={"inverse": [[2.0, 0.0], [0.0, 0.5]]}),
                        {"operation": "matrix_inverse",
                         "expected_result_type": "MATRIX"}, "inverse?")
    assert m["binding"] == VERIFIED
    assert m["authoritative_value"] == [[2.0, 0.0], [0.0, 0.5]]


# 13. scientific notation ----------------------------------------------------
def test_scientific_notation():
    # very small values survive display + adoption intact
    env = _env(result={"root": 2.997602166487923e-16})
    c = result_contract(env, {"operation": "scalar_root",
                              "expected_result_type": "ROOT"},
                        "root?")
    assert c["binding"] == VERIFIED
    assert c["display"]["raw_value"] == 2.997602166487923e-16
    d = display_value(2.997602166487923e-16,
                      {"policy": "SIGNIFICANT_FIGURES", "sig_figs": 4})
    assert d["display_value"] == 2.998e-16
    assert classify_adoption(
        env, "FINAL ANSWER: 2.997602166487923e-16",
        authoritative_field="root") == "ADOPTED"
    # scientific-notation input values survive canonicalization
    r = repair_planner_request(
        _req("definite_integral",
             {"expression": "3.0e8", "lower": 0, "upper": 1},
             {"lower": 0, "upper": 1}, {"upper": "USER_GIVEN"}),
        "integrate the speed of light 3.0e8")
    assert r["request"]["parameters"]["expression"] == "3.0e8"


# planner-repair mutation safety regression guard ----------------------------
def test_repair_keeps_frozen_gates_rejecting_mutations():
    from sciencemath.scicomp.fidelity import (
        FIDELITY_FAIL, check_fidelity, validate_planner_request)
    q = "compute the integral of x**2 from 0 to 3"
    mutated = _req("definite_integral",
                   {"expression": "x**3", "lower": 0, "upper": 3},
                   {"lower": 0, "upper": 3},
                   {"lower": "USER_GIVEN", "upper": "USER_GIVEN"})
    rep = repair_planner_request(mutated, q)
    sch = validate_planner_request(rep["request"])
    if sch["ok"]:
        assert check_fidelity(rep["request"], q).status == FIDELITY_FAIL

# T14R.14 replay finding: string-source rewrites must be verifiably
# semantics-preserving — a broken source ("2x +") must NOT be silently
# repaired into an executable expression ("2x") by the numbers check.
def test_string_source_rewrite_never_masks_broken_input():
    q = "Integrate the expression '2x +' (syntactically broken) from 0 to 1."
    req = _req("definite_integral",
               {"expression": "2x", "lower": 0, "upper": 1},
               {"expression": "2x +", "lower": 0, "upper": 1},
               {"expression": "USER_GIVEN", "lower": "USER_GIVEN",
                "upper": "USER_GIVEN"})
    r = repair_planner_request(req, q)
    # the verbatim broken source must stay in place...
    assert r["request"]["source_inputs"]["expression"] == "2x +"
    # ...no alignment binding may claim the rewrite preserved value...
    assert not any(b.get("field") == "expression"
                   for b in r["bindings"]), \
        "no SOURCE_ALIGNED binding for an unverifiable string rewrite"
    # ...and the frozen fidelity gate must reject the mismatch (fail
    # closed), so the engine never executes an input the question did
    # not give.
    from sciencemath.scicomp.fidelity import FIDELITY_FAIL, check_fidelity
    assert check_fidelity(r["request"], q).status == FIDELITY_FAIL


def test_string_definition_strip_still_aligned():
    # legitimate normalization: "f(x) = BODY" -> BODY is a verifiable
    # semantics-preserving representation fix (replay row msc-v1-0094)
    q = "integrate f(x) = (x - 3)**2 from 0 to 3"
    req = _req("definite_integral",
               {"expression": "(x - 3)**2", "lower": 0, "upper": 3},
               {"expression": "f(x) = (x - 3)**2", "lower": 0, "upper": 3},
               {"lower": "USER_GIVEN", "upper": "USER_GIVEN"})
    r = repair_planner_request(req, q)
    from sciencemath.scicomp.fidelity import check_fidelity, FIDELITY_OK
    assert check_fidelity(r["request"], q).status == FIDELITY_OK
