"""T14A — necessity taxonomy, routing features, T4/SciComp precedence.

Does not reopen the T13 fidelity classifier. Labels are deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciencemath.scicomp.router import (
    COMPUTE_HELPFUL, COMPUTE_REQUIRED, INSUFFICIENT_INFORMATION,
    NO_COMPUTE, auto_routes_scicomp, blocks_scicomp_invocation,
    compute_necessity, extract_routing_features, route_precedence,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "evaluations/t14/t13_router_failure_freeze.json"


def nec(q: str) -> str:
    return compute_necessity(q)["necessity"]


class TestTaxonomy:
    def test_labels_are_the_four_t14_names(self):
        assert {COMPUTE_REQUIRED, COMPUTE_HELPFUL, NO_COMPUTE,
                INSUFFICIENT_INFORMATION} == {
            "COMPUTE_REQUIRED", "COMPUTE_HELPFUL", "NO_COMPUTE",
            "INSUFFICIENT_INFORMATION"}

    def test_only_required_auto_routes(self):
        assert auto_routes_scicomp(COMPUTE_REQUIRED)
        assert not auto_routes_scicomp(COMPUTE_HELPFUL)
        assert not auto_routes_scicomp(NO_COMPUTE)
        assert not auto_routes_scicomp(INSUFFICIENT_INFORMATION)

    def test_blocks_never_invent(self):
        assert blocks_scicomp_invocation(NO_COMPUTE)
        assert blocks_scicomp_invocation(INSUFFICIENT_INFORMATION)
        assert not blocks_scicomp_invocation(COMPUTE_REQUIRED)
        assert not blocks_scicomp_invocation(COMPUTE_HELPFUL)


class TestComputeRequired:
    @pytest.mark.parametrize("question", [
        "Find the root of f(x) = x**2 - 2 in the interval [0, 5].",
        "Find x such that x**2 - 3 = 0 (start near x = 2).",
        "Multiply the matrices A = [ 1 2; 3 4 ] and B = [ 5 6; 7 8 ].",
        "What is the Euclidean (l2) norm of the vector (3, 4, 12)?",
        "What is the rank of the matrix [ 1 2 3; 2 4 6; 1 1 1 ]?",
        "A car moves with velocity v(t) = 3*t m/s. How far does it "
        "travel between t=0 s and t=4 s?",
        "A population grows as dP/dt = 0.3*P with P(0) = 2. What is P "
        "at t = 5?",
        "What is the Pearson correlation of x = (1,2,3,4,5) with "
        "y = (2,4,6,8,10)?",
        "Compute the mean of the values [2, 4, 6, 8].",
    ])
    def test_required(self, question):
        assert nec(question) == COMPUTE_REQUIRED

    @pytest.mark.parametrize("question", [
        "A spring with k = 200 N/m is stretched 0.05 m. What energy in "
        "joules is stored (E = 0.5 k x^2)?",
        "A wave has frequency 50 Hz and wavelength 4 m. What is its "
        "speed in m/s?",
        "A 5 kg mass accelerates at 3 m/s^2. What force in newtons "
        "acts on it?",
    ])
    def test_mixed_formula_unblocked(self, question):
        label = nec(question)
        assert label in (COMPUTE_REQUIRED, COMPUTE_HELPFUL)
        assert not blocks_scicomp_invocation(label)

    def test_numbers_alone_do_not_route(self):
        assert nec("There are 3 named laws of motion in introductory "
                   "physics textbooks.") == NO_COMPUTE

    def test_keyword_alone_does_not_route(self):
        assert nec("Eigenvalues appear in many areas of applied math.") \
            == NO_COMPUTE


class TestNoCompute:
    @pytest.mark.parametrize("question", [
        "Why does entropy increase in an isolated system?",
        "What is the definition of overfitting?",
        "Explain why the sky is blue",
        "Is it true that a 2x2 matrix always has two real eigenvalues?",
        "State the definition of the determinant of a 2x2 matrix in words.",
        "What is the difference between a local and a global optimum?",
        "Who discovered the electron?",
    ])
    def test_no_compute(self, question):
        assert nec(question) == NO_COMPUTE


class TestInsufficientInformation:
    @pytest.mark.parametrize("question", [
        "Calculate the energy of the reaction.",
        "Compute the integral of the unknown function f.",
        "Solve the ODE for y.",
        "Find the root of f.",
        "Minimize the objective.",
    ])
    def test_insufficient(self, question):
        out = compute_necessity(question)
        assert out["necessity"] == INSUFFICIENT_INFORMATION
        assert blocks_scicomp_invocation(out["necessity"])


class TestT4VsSciComp:
    def test_unit_conversion_is_helpful_not_scicomp(self):
        q = "A distance is 2 km. Express it in meters."
        assert nec(q) == COMPUTE_HELPFUL
        prec = route_precedence(q)
        assert prec["primary"] == "MATH_T4"
        assert not auto_routes_scicomp(nec(q))

    def test_trivial_arithmetic_is_t4(self):
        q = "What is 17 * 23?"
        prec = route_precedence(q)
        assert prec["primary"] in ("MATH_T4", "NO_TOOL")
        assert nec(q) != COMPUTE_REQUIRED or prec["primary"] == "MATH_T4"

    def test_linear_system_is_scicomp_required(self):
        q = ("Solve the linear system: 4x + 1y = 9; 2x + 3y = 13. "
             "Give x and y.")
        assert nec(q) == COMPUTE_REQUIRED
        assert route_precedence(q)["primary"] == "SCICOMP"


class TestRagVsSciComp:
    def test_retrieval_only_science(self):
        q = "Who discovered penicillin?"
        assert nec(q) == NO_COMPUTE
        assert route_precedence(q)["primary"] in (
            "SCIENCE_RAG", "NO_TOOL")

    def test_mixed_named_constant_and_compute(self):
        q = ("The speed of light is c = 3.0e8 m/s. How far does light "
             "travel in 1 microsecond, in meters?")
        label = nec(q)
        assert label in (COMPUTE_REQUIRED, COMPUTE_HELPFUL)
        assert not blocks_scicomp_invocation(label)
        assert route_precedence(q)["primary"] in (
            "MIXED_RAG_SCICOMP", "SCICOMP", "MATH_T4")


class TestFeatures:
    def test_matrix_feature(self):
        f = extract_routing_features(
            "Multiply the matrices A = [ 1 2; 3 4 ] and B = [ 5 6; 7 8 ].")
        assert f["has_matrix_or_vector"]
        assert f["compute_request"]

    def test_ode_and_ic(self):
        f = extract_routing_features(
            "dQ/dt = -Q/3 with Q(0) = 9. What is Q at t = 6?")
        assert f["has_ode_state_or_span"]
        assert f["has_initial_conditions"] or f["has_equation"]


@pytest.mark.skipif(not FREEZE.exists(), reason="T14.1 freeze missing")
def test_t13_guard_blocked_numeric_replay_required_or_justified():
    """T14.7 helper: frozen guard-blocked numeric rows must not stay
    NO_COMPUTE unless evidence says compute is not required."""
    doc = json.loads(FREEZE.read_text(encoding="utf-8"))
    blocked = [r for r in doc["records"]
               if r["guard_blocked"]
               and r["numeric_conceptual_adversarial_class"]
               in ("numeric_oracle", "mixed")]
    assert len(blocked) == 45
    still_blocked = []
    recovered_required = []
    recovered_helpful = []
    for r in blocked:
        label = nec(r["question"])
        if label == COMPUTE_REQUIRED:
            recovered_required.append(r["id"])
        elif label == COMPUTE_HELPFUL:
            recovered_helpful.append(r["id"])
        elif blocks_scicomp_invocation(label):
            still_blocked.append(r["id"])
    # SciComp-native rows recover as COMPUTE_REQUIRED. Mixed formula
    # rows may be COMPUTE_HELPFUL (T4-level) — that still unblocks them.
    assert still_blocked == []
    assert len(recovered_required) >= 30
    assert len(recovered_required) + len(recovered_helpful) == 45


def test_t13_fidelity_classifier_bytes_unchanged():
    import hashlib
    root = Path(__file__).resolve().parents[1]
    fid = hashlib.sha256(
        (root / "src/sciencemath/scicomp/fidelity.py").read_bytes()
    ).hexdigest()
    sem = hashlib.sha256(
        (root / "src/sciencemath/scicomp/semantic.py").read_bytes()
    ).hexdigest()
    assert fid == "052689077a2545e7012fe613d245024480567aa572f30440501d9789db2e2146"
    assert sem == "537c17ee13846133c3f4975bd00aa90b34e196d0890f3f36926b7c584d3dbec8"
