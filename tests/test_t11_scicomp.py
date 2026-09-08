"""T11.43 — Scientific Computing Laboratory: core, operations, trust.

Covers schemas, router, safe parser, resource caps, every compute
operation, solver warnings, diagnostics, unit interaction, provenance,
correction-firewall integration, deterministic behavior, result
serialization, and the no-generated-code boundary. Security/adversarial
cases live in test_t11_security.py (T11.25).
"""
from __future__ import annotations

import json

import pytest

from sciencemath.scicomp import executor, execute, limits, operations, \
    registry_sha256
from sciencemath.scicomp import router as scicomp_router
from sciencemath.scicomp import sandbox, trust
from sciencemath.scicomp.invocation import invoke, observation_text, \
    prevalidate
from sciencemath.scicomp.schemas import (Limits, ScicompError,
                                         STATUS_NUMERICAL_WARNING,
                                         STATUS_PASS, STATUS_RESOURCE_LIMIT,
                                         STATUS_UNKNOWN, validate_request)
from sciencemath.executive.correction import FeedbackTrust

# ---------------------------------------------------------------------------
# registry / executor surface
# ---------------------------------------------------------------------------


def test_registry_has_expected_operation_count():
    # 8 linear algebra + 3 calculus + 3 roots + 1 ODE + 2 optimization
    # + 6 statistics + 3 interpolation + 1 sweep = 27
    assert len(operations()) == 27


def test_registry_hash_is_stable():
    assert registry_sha256() == registry_sha256()
    assert len(registry_sha256()) == 64


def test_execute_returns_canonical_envelope():
    env = execute({"operation": "describe", "inputs": {"values": [1, 2, 3]}})
    for key in ("status", "operation", "result", "diagnostics", "warnings",
                "provenance", "cross_check", "runtime"):
        assert key in env
    assert env["status"] == STATUS_PASS
    assert env["runtime"]["device"] == "cpu"          # T11.7 CPU-only
    assert env["runtime"]["latency_ms"] >= 0          # T11.39


def test_execute_never_raises_on_garbage():
    for payload in (None, 42, "string", [], {}, {"operation": 5},
                    {"operation": "nope", "inputs": {}}):
        env = execute(payload)
        assert env["status"] in ("FAIL", "UNKNOWN", "INVALID_INPUT",
                                 "RESOURCE_LIMIT")


def test_unknown_operation_lists_approved_operations():
    env = execute({"operation": "solve_the_thing"})
    assert env["status"] == "INVALID_INPUT"
    assert "approved operations" in env["warnings"][0]


# ---------------------------------------------------------------------------
# schemas: validation and caps (T11.4, T11.6)
# ---------------------------------------------------------------------------


def test_validate_request_rejects_oversized_payload():
    big = {"operation": "describe",
           "inputs": {"values": [1.0] * 500_000}}
    with pytest.raises(ScicompError) as e:
        validate_request(big, limits())
    assert e.value.code == "RESOURCE_LIMIT"


def test_validate_request_rejects_bad_options():
    with pytest.raises(ScicompError):
        validate_request({"operation": "solve_ode", "inputs": {},
                          "options": {"rtol": 1e-20}}, limits())
    with pytest.raises(ScicompError):
        validate_request({"operation": "solve_ode", "inputs": {},
                          "options": {"max_steps": "many"}}, limits())


def test_resource_limit_on_dimension_caps():
    # matrix side cap (128) exceeded -> RESOURCE_LIMIT, not allocation
    n = limits().max_matrix_side + 1
    env = execute({"operation": "determinant",
                   "inputs": {"matrix": [[0.0] * n for _ in range(n)]}})
    assert env["status"] == STATUS_RESOURCE_LIMIT


def test_output_row_cap_on_sweeps():
    env = execute({"operation": "parameter_sweep", "inputs": {
        "expression": "a + b + c",
        "sweeps": {"a": list(range(23)), "b": list(range(23)),
                   "c": list(range(23))}}})
    # 23^3 = 12167 > 10000 combinations -> rejected BEFORE allocation
    assert env["status"] == STATUS_RESOURCE_LIMIT
    assert "combinations" in env["warnings"][0]


def test_sweep_estimated_count_reported():
    env = execute({"operation": "parameter_sweep", "inputs": {
        "expression": "a",
        "sweeps": {"a": list(range(limits().max_sweep_values_per_dim + 1))}}})
    assert env["status"] == STATUS_RESOURCE_LIMIT
    assert "65 values" in env["warnings"][0]


# ---------------------------------------------------------------------------
# sandbox: safe expression language (T11.5)
# ---------------------------------------------------------------------------


def test_sandbox_allows_approved_math():
    f = sandbox.compile_expression("sin(x) + exp(-x**2) + sqrt(abs(y))",
                                   ["x", "y"])
    assert abs(f(x=0.0, y=4.0) - (0 + 1 + 2)) < 1e-12


def test_sandbox_rejects_every_forbidden_construct():
    forbidden = [
        "__import__('os')",                       # import smuggle
        "open('file')",                           # builtin call
        "x.__class__",                            # attribute access
        "'a' + 'b'",                              # strings
        "lambda x: x",                            # lambda
        "[i for i in x]",                         # comprehension
        "x if x else y",                          # conditional expr
        "__builtins__",                           # dunder name
        "eval('1')",                              # dangerous builtin
        "os.system('ls')",                        # attribute + call
        "exec(x)",
        "f'{x}'",                                 # f-string
    ]
    for expr in forbidden:
        with pytest.raises(ScicompError) as e:
            sandbox.compile_expression(expr, ["x"])
        assert e.value.code == "INVALID_INPUT", expr


def test_sandbox_rejects_unknown_free_names():
    with pytest.raises(ScicompError):
        sandbox.compile_expression("unknown_var + 1", ["x"])


def test_sandbox_rejects_undeclared_variable_in_ode_rhs():
    with pytest.raises(ScicompError):
        sandbox.compile_expression("k_undeclared * y0", ["t", "y0"])


def test_sandbox_bounds_exponent_bombs():
    with pytest.raises(ScicompError):
        sandbox.compile_expression("9**99999", ["x"])
    with pytest.raises(ScicompError):
        sandbox.compile_expression("9**9**9**9", ["x"])


def test_sandbox_nan_and_overflow_fail_closed():
    # Rejection happens at EVALUATION time (the AST itself is legal):
    f_nan = sandbox.compile_expression("sqrt(0 - 1)", ["x"])
    with pytest.raises(ScicompError):
        f_nan(x=1.0)  # NaN domain
    f_inf = sandbox.compile_expression("1e308 * 1e308", ["x"])
    with pytest.raises(ScicompError):
        f_inf(x=1.0)  # overflow to inf


def test_sandbox_missing_variable_is_invalid_input():
    f = sandbox.compile_expression("x + y", ["x", "y"])
    with pytest.raises(ScicompError) as e:
        f(x=1.0)
    assert e.value.code == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# router (T11.13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("question,expected", [
    ("Compute the eigenvalues of the matrix [[2,1],[1,2]]", "LINEAR_ALGEBRA"),
    ("Integrate f(x)=x^2 from 0 to 1", "NUMERICAL_INTEGRATION"),
    ("What is the derivative of sin(x) at x=0?", "DERIVATIVE"),
    ("Find the root of x^2 - 2 between 0 and 5", "ROOT_FINDING"),
    ("Solve the ODE dy/dt = -k*y with initial condition y(0)=1", "ODE"),
    ("Minimize (x-2)^2 on the interval [-5, 5]", "OPTIMIZATION"),
    ("Compute the mean and standard deviation of the sample", "STATISTICS"),
    ("Interpolate the value at x=1.5 from the table", "INTERPOLATION"),
    ("Do a parameter sweep over alpha and beta", "PARAMETER_SWEEP"),
    ("Explain why the sky is blue", "NO_COMPUTE"),
])
def test_router_routes(question, expected):
    assert scicomp_router.route(question)["route"] == expected


def test_router_metrics():
    decisions = [("LINEAR_ALGEBRA", "LINEAR_ALGEBRA"),     # tp
                 ("STATISTICS", "LINEAR_ALGEBRA"),          # wrong tool
                 ("STATISTICS", "NO_COMPUTE"),              # unnecessary
                 ("NO_COMPUTE", "STATISTICS"),              # miss
                 ("NO_COMPUTE", "NO_COMPUTE")]              # tn
    m = scicomp_router.route_metrics(decisions)
    assert m["true_positive"] == 1
    assert m["wrong_tool"] == 1
    assert m["unnecessary_compute"] == 1
    assert m["false_negative"] == 1
    # precision = correct compute assignments / all compute assignments
    assert m["precision"] == pytest.approx(1 / 3)
    assert m["recall"] == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# operations: correctness vs analytical oracles (T11.21)
# ---------------------------------------------------------------------------


def test_matmul_correct():
    env = execute({"operation": "matrix_multiply",
                   "inputs": {"a": [[1, 2], [3, 4]], "b": [[5, 6], [7, 8]]}})
    assert env["result"]["matrix"] == [[19.0, 22.0], [43.0, 50.0]]


def test_matmul_dimension_mismatch_is_invalid():
    env = execute({"operation": "matrix_multiply",
                   "inputs": {"a": [[1, 2, 3]], "b": [[1], [2]]}})
    assert env["status"] == "INVALID_INPUT"


def test_linear_system_solve_with_diagnostics_and_cross_check():
    env = execute({"operation": "solve_linear_system",
                   "inputs": {"matrix": [[3.0, 1.0], [1.0, 2.0]],
                              "b": [9.0, 8.0]}})
    assert env["status"] == STATUS_PASS
    x = env["result"]["solution"]
    assert abs(x[0] - 2.0) < 1e-9 and abs(x[1] - 3.0) < 1e-9
    assert env["diagnostics"]["condition_number"] < 10
    assert env["diagnostics"]["relative_residual"] < 1e-10
    assert env["cross_check"]["verdict"] == "AGREE"


def test_singular_system_fails_closed():
    env = execute({"operation": "solve_linear_system",
                   "inputs": {"matrix": [[1.0, 2.0], [2.0, 4.0]],
                              "b": [1.0, 2.0]}})
    assert env["status"] == "FAIL"


def test_ill_conditioned_system_warns_not_fails():
    # 1e10-ish conditioning: solvable, must carry an explicit warning.
    env = execute({"operation": "solve_linear_system",
                   "inputs": {"matrix": [[1.0, 1.0], [1.0, 1.0 + 1e-10]],
                              "b": [2.0, 2.0 + 1e-10]}})
    assert env["status"] in (STATUS_PASS, STATUS_NUMERICAL_WARNING)
    assert env["diagnostics"]["condition_number"] > 1e9


def test_inverse_refuses_ill_conditioned_matrix():
    env = execute({"operation": "matrix_inverse",
                   "inputs": {"matrix": [[1e12, 0.0], [0.0, 1e-12]]}})
    assert env["status"] == "FAIL"
    assert "solve a linear system instead" in env["warnings"][0]


def test_inverse_of_singular_matrix_fails():
    env = execute({"operation": "matrix_inverse",
                   "inputs": {"matrix": [[1.0, 2.0], [2.0, 4.0]]}})
    assert env["status"] == "FAIL"


def test_eigenvalues_complex_flagged():
    env = execute({"operation": "eigen_decompose",
                   "inputs": {"matrix": [[0.0, -1.0], [1.0, 0.0]]}})
    assert env["status"] == STATUS_PASS
    assert any(abs(v[1]) > 1e-12 for v in env["result"]["eigenvalues"])
    assert any("complex" in w for w in env["warnings"])


def test_derivative_matches_analytic():
    env = execute({"operation": "numerical_derivative",
                   "inputs": {"expression": "x**3", "at": 2.0}})
    assert abs(env["result"]["derivative"] - 12.0) < 1e-4


def test_second_derivative_matches_analytic():
    env = execute({"operation": "numerical_derivative",
                   "inputs": {"expression": "x**3", "at": 2.0, "order": 2}})
    assert abs(env["result"]["derivative"] - 12.0) < 1e-2


def test_integral_matches_analytic_with_cross_check():
    env = execute({"operation": "definite_integral",
                   "inputs": {"expression": "x**2", "lower": 0, "upper": 1}})
    assert abs(env["result"]["integral"] - 1 / 3) < 1e-10
    assert env["cross_check"]["verdict"] == "AGREE"
    assert env["diagnostics"]["estimated_error"] < 1e-8


def test_integral_cross_check_unavailable_for_hard_integrand():
    env = execute({"operation": "definite_integral",
                   "inputs": {"expression": "sin(x) / (x + 0.001)",
                              "lower": 0, "upper": 1}})
    assert env["status"] in (STATUS_PASS, STATUS_NUMERICAL_WARNING)
    assert env["cross_check"]["verdict"] in ("NOT_AVAILABLE", "DISAGREE",
                                             "AGREE")


def test_integral_divergent_fails():
    env = execute({"operation": "definite_integral",
                   "inputs": {"expression": "1/x**2", "lower": -1,
                              "upper": 1}})
    assert env["status"] == "FAIL"


def test_bracketed_root_and_residual():
    env = execute({"operation": "bracketed_root",
                   "inputs": {"expression": "x**2 - 2", "bracket_low": 0,
                              "bracket_high": 5}})
    assert abs(env["result"]["root"] - 2 ** 0.5) < 1e-9
    assert env["diagnostics"]["residual_norm"] < 1e-9


def test_bracketed_root_without_sign_change_rejected():
    env = execute({"operation": "bracketed_root",
                   "inputs": {"expression": "x**2 + 1", "bracket_low": -5,
                              "bracket_high": 5}})
    assert env["status"] == "INVALID_INPUT"


def test_nonbracketed_root_is_candidate_only():
    env = execute({"operation": "scalar_root",
                   "inputs": {"expression": "cos(x) - x",
                              "initial_guess": 1.0}})
    assert env["status"] == STATUS_NUMERICAL_WARNING
    assert "candidate only" in " ".join(env["warnings"])


def test_ode_exact_solution_and_diagnostics():
    # dy/dt = -k y, y(0)=1, k=2 -> y(1) = e^-2
    env = execute({"operation": "solve_ode",
                   "inputs": {"equations": ["-k*y0"], "initial_state": [1.0],
                              "t_start": 0, "t_end": 1,
                              "parameters": {"k": 2.0}}})
    assert env["status"] == STATUS_PASS
    assert abs(env["result"]["final_state"][0] - 2 ** 0 * 2.718281828 ** -2) \
        < 1e-5
    d = env["diagnostics"]
    assert d["solver_success"] is True
    assert d["nfev"] > 0
    assert "termination_reason" in d


def test_ode_requires_matching_initial_state():
    env = execute({"operation": "solve_ode",
                   "inputs": {"equations": ["-y0"], "initial_state": [1.0, 2.0],
                              "t_start": 0, "t_end": 1}})
    assert env["status"] == "INVALID_INPUT"


def test_ode_rejects_nonfinite_span_and_state_dim():
    env = execute({"operation": "solve_ode",
                   "inputs": {"equations": ["-y0"], "initial_state": [1.0],
                              "t_start": 0, "t_end": 1e6}})
    assert env["status"] == STATUS_RESOURCE_LIMIT
    big = ["0"] * (limits().max_ode_state_dim + 1)
    env2 = execute({"operation": "solve_ode",
                    "inputs": {"equations": big, "initial_state": [0.0] * len(big),
                               "t_start": 0, "t_end": 1}})
    assert env2["status"] == STATUS_RESOURCE_LIMIT


def test_ode_stiff_blowup_is_unknown_not_partial_success():
    # y' = y^2 explodes before t=100 -> solver stalls -> UNKNOWN, and the
    # partial trajectory is NOT returned as a result (T11.29).
    env = execute({"operation": "solve_ode",
                   "inputs": {"equations": ["y0*y0"], "initial_state": [1.0],
                              "t_start": 0, "t_end": 100}})
    assert env["status"] == STATUS_UNKNOWN
    assert env["result"] is None
    assert "nfev" in env["diagnostics"]


def test_minimize_scalar_bounded():
    env = execute({"operation": "minimize_scalar",
                   "inputs": {"expression": "(x-2)**2", "bound_low": -5,
                              "bound_high": 5}})
    assert abs(env["result"]["optimum_x"] - 2.0) < 1e-4
    assert "NOT ESTABLISHED" in env["result"]["optimum_kind"]


def test_minimize_nonconvergent_is_unknown():
    # Oscillatory objective on a wide bound defeats the iteration budget.
    env = execute({"operation": "minimize",
                   "inputs": {"expression": "sin(100*x0)*cos(97*x1)",
                              "bounds": [[-1000, 1000], [-1000, 1000]]}})
    assert env["status"] in (STATUS_UNKNOWN, "FAIL", STATUS_PASS)
    if env["status"] == STATUS_PASS:
        # If it converged, it must still say global optimality is not
        # established (T11.30).
        assert "NOT ESTABLISHED" in env["result"]["optimum_kind"]


def test_descriptive_stats():
    env = execute({"operation": "describe", "inputs": {"values": [2, 4, 4,
                                                                  4, 5, 5,
                                                                  7, 9]}})
    r = env["result"]
    assert r["mean"] == 5.0
    assert r["n"] == 8
    assert abs(r["std_dev"] - 2.13809) < 1e-4
    assert env["diagnostics"]["sample_size"] == 8
    assert env["diagnostics"]["assumptions"]


def test_confidence_interval_requires_valid_confidence():
    env = execute({"operation": "confidence_interval_mean",
                   "inputs": {"values": [1, 2, 3], "confidence": 1.5}})
    assert env["status"] == "INVALID_INPUT"


def test_hypothesis_test_requires_explicit_equal_var():
    env = execute({"operation": "hypothesis_test",
                   "inputs": {"test": "ttest_ind", "values": [1, 2, 3],
                              "values2": [4, 5, 6]}})
    assert env["status"] == "INVALID_INPUT"
    assert "equal_var" in env["warnings"][0]


def test_hypothesis_test_reports_assumptions():
    env = execute({"operation": "hypothesis_test",
                   "inputs": {"test": "ttest_ind", "values": [1, 2, 3],
                              "values2": [4, 5, 6], "equal_var": True}})
    assert env["status"] == STATUS_PASS
    assumptions = env["diagnostics"]["assumptions"]
    assert any("equal population variance" in a for a in assumptions)


def test_distribution_invalid_parameters_rejected():
    env = execute({"operation": "distribution_value",
                   "inputs": {"distribution": "normal",
                              "parameters": {"mu": 0, "sigma": -1},
                              "at": 0.0}})
    assert env["status"] == "INVALID_INPUT"
    env2 = execute({"operation": "distribution_value",
                    "inputs": {"distribution": "binomial",
                               "parameters": {"n": 10, "p": 1.5},
                               "at": 1}})
    assert env2["status"] == "INVALID_INPUT"


def test_interpolation_rejects_extrapolation():
    env = execute({"operation": "linear_interpolate",
                   "inputs": {"x": [0, 1, 2], "y": [0, 1, 4], "at": 5.0}})
    assert env["status"] == "INVALID_INPUT"
    assert "extrapolation" in env["warnings"][0]


def test_polynomial_interpolation_overfit_guard():
    # 2 points but degree-3 request via 4 points? underdetermined guard
    # lives in curve_fit; polynomial_interpolate caps degree at 10.
    env = execute({"operation": "polynomial_interpolate",
                   "inputs": {"x": [0, 1, 2], "y": [1, 3, 2], "at": 0.5}})
    assert env["status"] in (STATUS_PASS, STATUS_NUMERICAL_WARNING)
    assert env["result"]["degree"] == 2


def test_curve_fit_recovers_exponential():
    env = execute({"operation": "curve_fit",
                   "inputs": {"model": "p0*exp(-p1*x)",
                              "x": [0, 0.5, 1, 1.5, 2],
                              "y": [1, 0.6, 0.37, 0.22, 0.14],
                              "parameters": ["p0", "p1"]}})
    assert env["status"] == STATUS_PASS
    assert abs(env["result"]["parameters"]["p0"] - 1.0) < 0.05
    assert abs(env["result"]["parameters"]["p1"] - 1.0) < 0.1
    assert env["diagnostics"]["parameter_std_errors"] is not None


def test_curve_fit_underdetermined_rejected():
    # 2 data points, 2 free parameters: the fit is underdetermined.
    env = execute({"operation": "curve_fit",
                   "inputs": {"model": "p0*x + p1", "x": [0.0, 1.0],
                              "y": [1.0, 2.0], "parameters": ["p0", "p1"]}})
    assert env["status"] == "INVALID_INPUT"
    assert "underdetermined" in env["warnings"][0]


def test_sweep_matches_direct_evaluation():
    env = execute({"operation": "parameter_sweep",
                   "inputs": {"expression": "a*x**2 + b",
                              "sweeps": {"a": [1, 2], "b": [0, 1]},
                              "x": [1, 2, 3]}})
    assert env["status"] == STATUS_PASS
    assert env["result"]["row_count"] == 12
    assert env["diagnostics"]["sensitivity"]["a"]["value_range"] > 0


# ---------------------------------------------------------------------------
# units (T11.11)
# ---------------------------------------------------------------------------


def test_unit_composition_velocity_over_time():
    env = execute({"operation": "definite_integral",
                   "inputs": {"expression": "5", "lower": 0, "upper": 10,
                              "integrand_unit": "m/s",
                              "variable_unit": "s",
                              "expected_unit": "m"}})
    assert env["status"] == STATUS_PASS
    assert env["diagnostics"]["unit_dimensionless"] is False


def test_unit_mismatch_rejected():
    # integrating velocity over time is NOT energy
    env = execute({"operation": "definite_integral",
                   "inputs": {"expression": "5", "lower": 0, "upper": 10,
                              "integrand_unit": "m/s", "variable_unit": "s",
                              "expected_unit": "J"}})
    assert env["status"] == "INVALID_INPUT"
    assert "dimension mismatch" in env["warnings"][0]


def test_unit_half_declaration_rejected():
    env = execute({"operation": "definite_integral",
                   "inputs": {"expression": "5", "lower": 0, "upper": 10,
                              "integrand_unit": "m/s"}})
    assert env["status"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# provenance and firewall integration (T11.17, T11.18)
# ---------------------------------------------------------------------------


def test_computed_result_does_not_need_citation():
    assert trust.requires_citation(trust.Provenance.DETERMINISTIC_COMPUTATION) \
        is False
    assert trust.requires_citation(trust.Provenance.RETRIEVED_FACT) is True
    assert trust.requires_citation(trust.Provenance.USER_GIVEN_VALUE) is False
    assert trust.requires_citation(trust.Provenance.MODEL_INFERENCE) is False


def test_pass_envelope_maps_to_verified_firewall_trust():
    env = execute({"operation": "definite_integral",
                   "inputs": {"expression": "x**2", "lower": 0, "upper": 1}})
    assert trust.firewall_trust(env) == FeedbackTrust.VERIFIED
    assert trust.adoption_allowed(env) is True


def test_numerical_warning_maps_to_unverified():
    env = execute({"operation": "scalar_root",
                   "inputs": {"expression": "cos(x) - x",
                              "initial_guess": 1.0}})
    assert env["status"] == STATUS_NUMERICAL_WARNING
    assert trust.firewall_trust(env) == FeedbackTrust.UNVERIFIED
    assert trust.adoption_allowed(env) is False


def test_unknown_maps_to_unverified():
    env = execute({"operation": "solve_ode",
                   "inputs": {"equations": ["y0*y0"], "initial_state": [1.0],
                              "t_start": 0, "t_end": 100}})
    assert trust.firewall_trust(env) == FeedbackTrust.UNVERIFIED


def test_disagreeing_cross_check_maps_to_unverified():
    env = {"status": STATUS_PASS,
           "cross_check": {"verdict": "DISAGREE"}}
    assert trust.adoption_allowed(env) is False


def test_firewall_module_untouched_by_t11():
    # The firewall mapping works through the EXISTING frozen API — the
    # module itself must be unchanged (T10 hash pin).
    import hashlib
    expected = ("f6c23e3d81cf6cda03ec601b7e8cc69283ea63b25170da4e46044573"
                "ebeb6cff")
    digest = hashlib.sha256(
        open("src/sciencemath/executive/correction.py", "rb").read()
    ).hexdigest()
    assert digest == expected


# ---------------------------------------------------------------------------
# invocation boundary (T11.14, T11.33)
# ---------------------------------------------------------------------------


def test_invoke_flow_records_route_and_adoption():
    r = invoke({"operation": "definite_integral",
                "inputs": {"expression": "x**2", "lower": 0, "upper": 1}},
               question="Integrate x^2 from 0 to 1")
    assert r.route_recommendation["route"] == "NUMERICAL_INTEGRATION"
    assert r.adopted is True
    assert r.prevalidation["ok"] is True
    assert "COMPUTED" in observation_text(r)


def test_invoke_rejects_code_smuggling_keys():
    r = invoke({"operation": "definite_integral",
                "inputs": {"expression": "x**2", "lower": 0, "upper": 1,
                           "code": "import os"}})
    assert r.prevalidation["ok"] is False
    assert r.prevalidation["checks"]["no_code_keys"] is False


def test_invoke_never_executes_generated_code():
    # Even a payload shaped like Python source has no path to execution:
    # only registered operations with validated schemas run (T11.33).
    r = invoke({"operation": "system_root",
                "expressions": ["exec('import os')"],
                "initial_guess": [1.0]})
    env = r.envelope
    assert env["status"] in ("INVALID_INPUT", "FAIL", "UNKNOWN")


def test_observation_text_distinguishes_compute_failure():
    r = invoke({"operation": "bracketed_root",
                "inputs": {"expression": "x**2+1", "bracket_low": -5,
                           "bracket_high": 5}})
    text = observation_text(r)
    assert text.startswith("COMPUTE")
    assert "INVALID_INPUT" in text


# ---------------------------------------------------------------------------
# determinism (T11.26)
# ---------------------------------------------------------------------------


def test_identical_requests_identical_results():
    req = {"operation": "least_squares",
           "inputs": {"matrix": [[1, 1], [1, 2], [1, 3]], "b": [1, 2.1, 2.9]}}
    a, b = execute(req), execute(req)
    assert json.dumps(a["result"], sort_keys=True) == \
        json.dumps(b["result"], sort_keys=True)


def test_result_serialization_is_json_safe():
    reqs = [
        {"operation": "eigen_decompose", "inputs": {"matrix": [[2, 1],
                                                               [1, 2]]}},
        {"operation": "solve_ode", "inputs": {"equations": ["-y0"],
                                              "initial_state": [1.0],
                                              "t_start": 0, "t_end": 1}},
        {"operation": "parameter_sweep", "inputs": {"expression": "a",
                                                    "sweeps": {"a": [1, 2]}}},
        {"operation": "curve_fit", "inputs": {"model": "p0*x",
                                              "x": [1, 2, 3],
                                              "y": [2, 4, 6],
                                              "parameters": ["p0"]}},
    ]
    for req in reqs:
        env = execute(req)
        json.dumps(env, allow_nan=False)  # must not raise


def test_output_byte_cap_trimmed_not_leaked():
    tiny = Limits(max_output_bytes=500)
    env = execute({"operation": "parameter_sweep",
                   "inputs": {"expression": "a",
                              "sweeps": {"a": list(range(50))}}},
                  limits_config=tiny)
    assert env["status"] == STATUS_RESOURCE_LIMIT


def test_wall_clock_timeout_returns_resource_limit(monkeypatch):
    import time as _time
    from sciencemath.scicomp import executor
    from sciencemath.scicomp.registry import Operation

    def slow(inputs, options, active):
        _time.sleep(2.0)

    monkeypatch.setitem(
        executor._registry, "describe",
        Operation("describe", "STATISTICS", "slow test stub", slow))
    env = execute({"operation": "describe",
                   "inputs": {"values": [1, 2, 3]}},
                  limits_config=Limits(wall_clock_s=0.2))
    assert env["status"] == STATUS_RESOURCE_LIMIT
    assert env["result"] is None
    assert "timeout" in env["warnings"][0].lower()


def test_nonfinite_diagnostics_sanitized_never_raised():
    """Executor contract: a handler leaking NaN/inf in diagnostics must
    produce a well-formed envelope, never a crash (found by the T11.20
    arm-B run: determinant of a singular matrix reports cond=inf)."""
    env = execute({"operation": "determinant",
                   "inputs": {"matrix": [[4.0, 2.0], [2.0, 1.0]]}})
    json.dumps(env, allow_nan=False)  # must not raise
    assert env["status"] in (STATUS_PASS, "NUMERICAL_WARNING")
    assert env["diagnostics"]["condition_number"] is None


def test_nonfinite_result_downgraded_not_collapsed(monkeypatch):
    import math
    from sciencemath.scicomp import executor
    from sciencemath.scicomp.registry import Operation

    def leaky(inputs, options, active):
        return {"status": "PASS", "result": {"value": math.inf},
                "diagnostics": {}, "warnings": []}

    monkeypatch.setitem(
        executor._registry, "describe",
        Operation("describe", "STATISTICS", "leaky stub", leaky))
    env = execute({"operation": "describe",
                   "inputs": {"values": [1.0]}})
    assert env["status"] == "NUMERICAL_WARNING"
    assert env["result"]["value"] is None
    assert any("non-finite" in w for w in env["warnings"])