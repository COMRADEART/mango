"""T14R2.11 — build the ODE planner microbench `mango-ode-planner-v1`.

100-160 deterministic cases covering the milestone's required coverage:
scalar IVPs, systems of ODEs, explicit time dependence, autonomous
equations, valid and INVALID initial conditions (missing IC, BVP shape,
mixed-time ICs), missing interval, malformed derivative notation,
conceptual ODE questions, operation distractors (definite integral,
root finding, optimization, equation solving, parameter sweeps), and
insufficient-information cases.

The suite is written ONCE with a recorded sha256 (dev + frozen final
split, assignment derived from the case id) BEFORE any tuning pass; the
metrics runner (t14r2_run_ode_microbench.py) evaluates the deterministic
ODE intent layer fully offline — no LLM, no GPU.

Oracle independence: expected constructed fields are computed by the
template literals below (hand-written strings), NOT by calling the
layer under test.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations/t14r2/ode_microbench"
OUT_SUITE = OUT_DIR / "suite_v1.jsonl"
OUT_MANIFEST = OUT_DIR / "manifest.json"

WRONG_OPS = ["definite_integral", "minimize"]


def mk(cid: str, family: str, question: str, positive: bool,
       expected: dict | None) -> dict:
    case = {"eval_id": cid, "family": family, "question": question,
            "is_ivp_positive": positive}
    if positive:
        assert expected is not None, cid
        case["expected"] = expected
    return case


cases: list[dict] = []
n = 0


def add(family: str, question: str, positive: bool, expected=None) -> None:
    global n
    n += 1
    cases.append(mk(f"ode-bench-{family}-{n:03d}", family, question,
                    positive, expected))


def exp(equations, initial_state, t_start, t_end, shape, order,
        t_end_prov="USER_GIVEN", t_start_prov="USER_GIVEN",
        parameters=None) -> dict:
    e = {"equations": equations, "initial_state": initial_state,
         "t_start": t_start, "t_end": t_end,
         "expected_result_type": shape, "order": order,
         "t_end_provenance": t_end_prov, "t_start_provenance": t_start_prov}
    if parameters is not None:
        e["parameters"] = parameters
    return e


# ---- F1 first-order exponential growth (explicit notation) ----
for i, (v, k, y0, t) in enumerate([
        ("P", 0.3, 2, 5), ("N", 0.07, 1000, 10), ("x", 1.5, 5, 3),
        ("Q", 2.0, 1, 0.5), ("B", 0.11, 250, 4), ("W", 0.05, 80, 12)]):
    add("growth", f"d{v}/dt = {k}*{v} with {v}(0) = {y0}. "
        f"What is {v} at t = {t}?", True,
        exp([f"{k!r}*y0"], [float(y0)], 0.0, float(t), "scalar", 1))
for v, k, y0, t in [("P", 0.3, 2, 5), ("M", 0.4, 3, 2)]:
    add("growth", f"The variable {v} obeys d{v}/dt = {k}*{v} with "
        f"{v}(0) = {y0}. Find {v} at t = {t}.", True,
        exp([f"{k!r}*y0"], [float(y0)], 0.0, float(t), "scalar", 1))

# ---- F2 first-order exponential decay (explicit notation) ----
for v, k, y0, t in [("Q", 1 / 3, 9, 6), ("V", 0.5, 12, 4),
                    ("A", 0.02, 10, 100), ("C", 0.1, 50, 20),
                    ("T", 0.25, 4, 8), ("S", 0.9, 7, 1),
                    ("H", 0.03, 1000, 30), ("G", 0.6, 2, 5),
                    ("L", 0.15, 40, 7), ("R", 0.7, 1, 2),
                    ("E", 0.01, 500, 50), ("Z", 0.45, 22, 3)]:
    add("decay", f"d{v}/dt = -{k:.6g}*{v} with {v}(0) = {y0}. "
        f"What is {v} at t = {t}?", True,
        exp([f"-{k:.6g}*y0"], [float(y0)], 0.0, float(t), "scalar", 1))

# ---- F3 decay via declared parameter (RC-style) ----
add("param_decay", "A capacitor discharges: dV/dt = -V/RC with "
    "RC = 2 s and V(0) = 12 V. What is V at t = 4 s?", True,
    exp(["-y0/RC"], [12.0], 0.0, 4.0, "scalar", 1,
        parameters={"RC": 2.0}))
add("param_decay", "dV/dt = -V/RC with RC = 5 s and V(0) = 20 V. "
    "What is V at t = 10 s?", True,
    exp(["-y0/RC"], [20.0], 0.0, 10.0, "scalar", 1,
        parameters={"RC": 5.0}))
add("param_decay", "dY/dt = -Y/tau with tau = 0.5 and Y(0) = 8. "
    "What is Y at t = 1?", True,
    exp(["-y0/tau"], [8.0], 0.0, 1.0, "scalar", 1,
        parameters={"tau": 0.5}))

# ---- F4 constant-RHS (autonomous linear-in-t) ----
add("constant_rhs", "A ball dropped from rest accelerates at "
    "g = 9.8 m/s^2: dv/dt = 9.8, v(0) = 0. What is its velocity at "
    "t = 3 s?", True,
    exp(["9.8"], [0.0], 0.0, 3.0, "scalar", 1))
add("constant_rhs", "Water flows into a tank at 4 L/min: dV/dt = 4, "
    "V(0) = 10. What is V at t = 5?", True,
    exp(["4"], [10.0], 0.0, 5.0, "scalar", 1))
add("constant_rhs", "dv/dt = 9.8, v(0) = 0. What is v at t = 2?", True,
    exp(["9.8"], [0.0], 0.0, 2.0, "scalar", 1))
add("linear_rhs", "dx/dt = 5 - 0.5*x with x(0) = 20. What is x at "
    "t = 4?", True,
    exp(["5 - 0.5*y0"], [20.0], 0.0, 4.0, "scalar", 1))

# ---- F5 coupled two-state systems ----
add("system2", "dx/dt = y with x(0) = 1 and dy/dt = -x with y(0) = 0. "
    "What is x at t = 2?", True,
    exp(["y1", "-y0"], [1.0, 0.0], 0.0, 2.0, "vector", 1))
add("system2", "dx/dt = y with x(0) = 2 and dy/dt = -x with y(0) = 0. "
    "What is x at t = 1.5?", True,
    exp(["y1", "-y0"], [2.0, 0.0], 0.0, 1.5, "vector", 1))
add("system2", "dU/dt = V with U(0) = 3 and dV/dt = -U with V(0) = 1. "
    "What is U at t = 0.7?", True,
    exp(["y1", "-y0"], [3.0, 1.0], 0.0, 0.7, "vector", 1))
add("system2", "dA/dt = 2*B with A(0) = 0 and dB/dt = -A with B(0) = 4. "
    "What is A at t = 1?", True,
    exp(["2*y1", "-y0"], [0.0, 4.0], 0.0, 1.0, "vector", 1))
add("system2", "dP/dt = Q with P(0) = 1 and dQ/dt = P with Q(0) = 1. "
    "What is P at t = 2?", True,
    exp(["y1", "y0"], [1.0, 1.0], 0.0, 2.0, "vector", 1))
add("system2", "dx/dt = -2*y with x(0) = 5 and dy/dt = 2*x with "
    "y(0) = 0. What is x at t = 3?", True,
    exp(["-2*y1", "2*y0"], [5.0, 0.0], 0.0, 3.0, "vector", 1))

# ---- F6 second-order with BOTH initial conditions ----
add("second_order", "For d2x/dt2 = -4*x with x(0)=1 and dx/dt(0)=0, "
    "what is x at t = pi/2 (use the exact analytic solution)?", True,
    exp(["y1", "-4*y0"], [1.0, 0.0], 0.0, "PI/2", "scalar", 2,
        t_end_prov="DETERMINISTIC_DERIVATION"))
add("second_order", "d2y/dt2 = -9*y with y(0) = 2 and dy/dt(0) = 0. "
    "What is y at t = 1?", True,
    exp(["y1", "-9*y0"], [2.0, 0.0], 0.0, 1.0, "scalar", 2))
add("second_order", "An oscillator: d2x/dt2 = -16*x with x(0) = 0.5, "
    "x'(0) = 0. What is x at t = 0.4?", True,
    exp(["y1", "-16*y0"], [0.5, 0.0], 0.0, 0.4, "scalar", 2))
add("second_order", "d2s/dt2 = 3 with s(0) = 0 and ds/dt(0) = 2. "
    "What is s at t = 4?", True,
    exp(["y1", "3"], [0.0, 2.0], 0.0, 4.0, "scalar", 2))
add("second_order", "d2u/dt2 = -u with u(0) = 1 and du/dt(0) = 1. "
    "What is u at t = pi (use the exact analytic solution)?", True,
    exp(["y1", "-y0"], [1.0, 1.0], 0.0, "PI", "scalar", 2,
        t_end_prov="DETERMINISTIC_DERIVATION"))

# ---- F7 verbal linear rate laws ----
add("verbal_decay", "A radioactive sample decays with rate constant "
    "0.02 per year. Starting from 10 grams, how many grams remain after "
    "100 years?", True,
    exp(["-0.02*y0"], [10.0], 0.0, 100.0, "scalar", 1,
        t_start_prov="DETERMINISTIC_DERIVATION"))
add("verbal_decay", "A substance decays with rate constant 0.05 per "
    "day. Starting from 200 units, how much remains after 30 days?", True,
    exp(["-0.05*y0"], [200.0], 0.0, 30.0, "scalar", 1,
        t_start_prov="DETERMINISTIC_DERIVATION"))
add("verbal_decay", "A population of bacteria decays with rate constant "
    "0.5 per hour. Starting from 1000 cells, how many remain after "
    "6 hours?", True,
    exp(["-0.5*y0"], [1000.0], 0.0, 6.0, "scalar", 1,
        t_start_prov="DETERMINISTIC_DERIVATION"))
add("verbal_growth", "A culture grows with rate constant 0.1 per hour. "
    "Starting from 500 cells, how many cells are there after 8 hours?",
    True, exp(["0.1*y0"], [500.0], 0.0, 8.0, "scalar", 1,
               t_start_prov="DETERMINISTIC_DERIVATION"))
add("verbal_growth", "An investment grows with rate constant 0.08 per "
    "year. Starting from 10000 dollars, what is the balance after "
    "5 years?", True,
    exp(["0.08*y0"], [10000.0], 0.0, 5.0, "scalar", 1,
        t_start_prov="DETERMINISTIC_DERIVATION"))
add("verbal_decay", "A voltage discharges with rate constant 0.4 per "
    "second. Starting from 9 volts, what is the voltage after 2 seconds?",
    True, exp(["-0.4*y0"], [9.0], 0.0, 2.0, "scalar", 1,
               t_start_prov="DETERMINISTIC_DERIVATION"))

# ---- F8 evaluation-time phrasing variants ----
add("eval_time", "dP/dt = 0.3*P with P(0) = 2. What is P up to "
    "t = 5?", True, exp(["0.3*y0"], [2.0], 0.0, 5.0, "scalar", 1))
add("eval_time", "dP/dt = 0.3*P with P(0) = 2. What is P when "
    "t = 5?", True, exp(["0.3*y0"], [2.0], 0.0, 5.0, "scalar", 1))
add("eval_time", "dQ/dt = -Q/3 with Q(0) = 9. What is Q after "
    "6 seconds?", True, exp(["-0.333333*y0"], [9.0], 0.0, 6.0,
                            "scalar", 1))
add("eval_time", "dT/dt = -0.1*T with T(0) = 100. What is T after "
    "10 minutes?", True, exp(["-0.1*y0"], [100.0], 0.0, 10.0,
                             "scalar", 1))
add("eval_time", "dx/dt = x with x(0) = 1. What is x to t = 2?", True,
    exp(["y0"], [1.0], 0.0, 2.0, "scalar", 1))

# ---- N1 missing initial condition ----
for q in ["dP/dt = 0.3*P. What is P at t = 5?",
          "dy/dt = -0.5*y. What is y at t = 4?",
          "The equation dN/dt = 0.07*N holds. What is N at t = 10?",
          "dx/dt = 2*x. Find x at t = 3."]:
    add("missing_ic", q, False, None)

# ---- N2 missing evaluation time / interval ----
for q in ["dP/dt = 0.3*P with P(0) = 2. What is the growth rate?",
          "dy/dt = -0.5*y with y(0) = 4. Describe the behavior of y.",
          "dx/dt = -x with x(0) = 1. Is the solution increasing or "
          "decreasing?",
          "dQ/dt = -Q/3 with Q(0) = 9. What type of equation is this?"]:
    add("missing_eval_time", q, False, None)

# ---- N3 undeclared parameter (never invent) ----
for q in ["dP/dt = k*P with P(0) = 2. What is P at t = 5?",
          "dy/dt = -a*y with y(0) = 4. What is y at t = 2?",
          "dx/dt = r*x - s with x(0) = 10. What is x at t = 5?",
          "dC/dt = -lambda*C with C(0) = 1. What is C at t = 3?"]:
    add("undeclared_param", q, False, None)

# ---- N4 boundary-value shape ----
for q in ["dP/dt = 0.3*P with P(0) = 2 and P(10) = 5. What is P at "
          "t = 20?",
          "dy/dt = -y with y(0) = 4 and y(5) = 1. What is y at t = 10?",
          "Solve dT/dt = -0.1*T with T(0) = 100 and T(20) = 10. Find T "
          "at t = 40."]:
    add("bvp_shape", q, False, None)

# ---- N5 mixed-time initial conditions ----
for q in ["dP/dt = 0.3*P with P(0) = 2 and P(5) = 4. What is P at "
          "t = 2?",
          "dx/dt = y with x(0) = 1 and dy/dt = -x with y(3) = 2. What is "
          "x at t = 1?"]:
    add("mixed_time_ics", q, False, None)

# ---- N6 second-order with only one initial condition ----
for q in ["d2x/dt2 = -4*x with x(0)=1. What is x at t = 2?",
          "d2y/dt2 = -9*y with dy/dt(0) = 0. What is y at t = 1?",
          "An oscillator: d2x/dt2 = -16*x with x(0) = 0.5. What is x at "
          "t = 0.4?"]:
    add("second_order_one_ic", q, False, None)

# ---- N7 conceptual ODE questions (no compute) ----
add("conceptual", "Explain the difference between an ordinary "
    "differential equation and a partial differential equation.", False,
    None)
add("conceptual", "What is an integrating factor and when is it used?",
    False, None)
add("conceptual", "Describe what a steady state means for the equation "
    "dy/dt = f(y).", False, None)
add("conceptual", "What does it mean for a solution of dy/dt = -k*y to "
    "have a half-life?", False, None)
add("conceptual", "Why does an initial-value problem need exactly one "
    "initial condition per first-order state variable?", False, None)
add("conceptual", "In words, what is the difference between the "
    "accumulated change integral of a rate and the solution of the "
    "corresponding differential equation?", False, None)

# ---- N8 operation distractors ----
add("distractor_integral", "What is the integral of 0.3*t from t = 0 "
    "to t = 5?", False, None)
add("distractor_integral", "Compute the definite integral of "
    "t^2 from 0 to 3.", False, None)
add("distractor_root", "Find the root of f(x) = x^2 - 4 in [0, 5].",
    False, None)
add("distractor_optimize", "Minimize f(x) = (x - 3)^2 on [0, 10].",
    False, None)
add("distractor_equation", "Solve 2*x + 3 = 11 for x.", False, None)
add("distractor_sweep", "Sweep the growth rate k from 0.1 to 1.0 in "
    "steps of 0.1 and report the final population P(10) for P(0) = 1 "
    "for each k.", False, None)
add("distractor_integral", "What is the accumulated change of "
    "dP/dt = 0.3*P from t = 0 to t = 5 (that is, the integral of the "
    "rate 0.3*P over [0, 5])?", False, None)
add("distractor_derivative", "What is the derivative of f(x) = x^3 at "
    "x = 2?", False, None)

# ---- N9 insufficient information ----
add("insufficient", "A population decays exponentially. What is it "
    "after 10 years?", False, None)
add("insufficient", "Solve dy/dt = -k*y with y(0) = 5. What is y at "
    "t = 10?", False, None)
add("insufficient", "A sample decays over time. How much remains "
    "eventually?", False, None)
add("insufficient", "dP/dt = 0.3*P with P(0) = 2. How long until the "
    "population doubles?", False, None)
add("insufficient", "A tank drains at a rate proportional to its "
    "volume. What is the volume after one hour?", False, None)

# ---- N10 malformed / unsupported notation ----
add("malformed", "dP/dt 0.3*P with P(0) = 2. What is P at t = 5?",
    False, None)
add("malformed", "P'(t) = 0.3*P with P(0) = 2, what is P at t = 5?",
    False, None)
add("malformed", "The rate equation is dP/dt equals 0.3 P with P(0) = "
    "2. What is P at t = 5?", False, None)
add("malformed", "ddt P = 0.3*P with P(0) = 2. What is P at t = 5?",
    False, None)

# ---- extra growth / decay coverage ----
for v, k, y0, t in [("F", 0.2, 15, 6), ("D", 0.25, 8, 9)]:
    add("growth", f"d{v}/dt = {k}*{v} with {v}(0) = {y0}. "
        f"What is {v} at t = {t}?", True,
        exp([f"{k!r}*y0"], [float(y0)], 0.0, float(t), "scalar", 1))
add("system2", "dx/dt = -y with x(0) = 2 and dy/dt = x with y(0) = 2. "
    "What is x at t = 0.5?", True,
    exp(["-y1", "y0"], [2.0, 2.0], 0.0, 0.5, "vector", 1))
add("system2", "dX/dt = 3*Y with X(0) = 1 and dY/dt = 0 with Y(0) = 2. "
    "What is X at t = 1?", True,
    exp(["3*y1", "0"], [1.0, 2.0], 0.0, 1.0, "vector", 1))
add("second_order", "d2x/dt2 = -25*x with x(0) = 1 and dx/dt(0) = 0. "
    "What is x at t = 0.2?", True,
    exp(["y1", "-25*y0"], [1.0, 0.0], 0.0, 0.2, "scalar", 2))
add("eval_time", "dM/dt = -0.2*M with M(0) = 50. What is M up to "
    "t = 15?", True, exp(["-0.2*y0"], [50.0], 0.0, 15.0, "scalar", 1))
add("param_decay", "dR/dt = -R/k with k = 4 and R(0) = 100. What is R "
    "at t = 8?", True, exp(["-y0/k"], [100.0], 0.0, 8.0, "scalar", 1,
                            parameters={"k": 4.0}))
add("missing_ic", "dy/dt = y*y. What is y at t = 1?", False, None)
add("missing_eval_time", "dx/dt = 5 - 0.5*x with x(0) = 20. What is "
    "the steady state?", False, None)
add("undeclared_param", "d2x/dt2 = -omega*x with x(0) = 1 and "
    "dx/dt(0) = 0. What is x at t = 2?", False, None)
add("bvp_shape", "dx/dt = y with x(0) = 1 and dy/dt = -x with y(4) = 0. "
    "What is x at t = 8?", False, None)
add("conceptual", "Explain what numerical stiffness means for an "
    "initial-value problem.", False, None)
add("insufficient", "A bacteria colony grows exponentially. What is its "
    "size after 12 hours?", False, None)
add("distractor_sweep", "For dP/dt = k*P with P(0) = 2, evaluate the "
    "final population P(5) for each k in the list [0.1, 0.2, 0.3].",
    False, None)
add("distractor_equation", "Solve the equation y^2 - 3*y + 2 = 0.",
    False, None)
add("distractor_optimize", "What value of t in [0, 10] maximizes "
    "f(t) = 10*t - t^2?", False, None)

assert 100 <= len(cases) <= 160, len(cases)
n_pos = sum(1 for c in cases if c["is_ivp_positive"])

# ---- dev / frozen-final split by case-id hash (deterministic) ----
for c in cases:
    h = hashlib.sha256(c["eval_id"].encode()).hexdigest()
    c["split"] = "dev" if int(h[:2], 16) % 5 < 2 else "final"

OUT_DIR.mkdir(parents=True, exist_ok=True)
body = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
OUT_SUITE.write_text(body, encoding="utf-8")

import hashlib as _h
sha = _h.sha256(body.encode("utf-8")).hexdigest()
manifest = {
    "milestone": "T14R2.11 — ODE planner microbench suite",
    "bench": "mango-ode-planner-v1",
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "suite_file": "evaluations/t14r2/ode_microbench/suite_v1.jsonl",
    "suite_sha256": sha,
    "total_cases": len(cases),
    "positive_cases": n_pos,
    "negative_cases": len(cases) - n_pos,
    "split_counts": {
        "dev": sum(1 for c in cases if c["split"] == "dev"),
        "final": sum(1 for c in cases if c["split"] == "final")},
    "family_counts": {},
    "checksum_frozen_before_tuning": True,
}
for c in cases:
    manifest["family_counts"].setdefault(c["family"], 0)
    manifest["family_counts"][c["family"]] += 1
OUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n",
                        encoding="utf-8")
print(json.dumps(manifest, indent=2))