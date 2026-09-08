"""Build the two frozen T12 suites (T12.18–T12.20):

  mango-scicomp-fidelity-v1    — parameter-fidelity adversarial cases.
    Two item kinds:
      REJECT — the question states invalid/malformed/degenerate inputs
        whose FAITHFUL transmission produces the declared non-PASS
        engine status (verified against the frozen engine at build
        time; 0 mismatches tolerated).
      FLAG   — the inputs are physically invalid, ambiguous, or
        unit-conflicting even though the unit-blind engine would
        return PASS; the pipeline must flag the specification and
        NOT assert a numeric answer.
    A subset carries an explicit ``mutating_inputs`` (the silent
    repair the T11 reasoner actually performed) verified at build to
    be rejected by the fidelity gate.

  mango-scicomp-conceptual-v1  — routing/conceptual discipline:
    conceptual science/math, factual retrieval, qualitative
    comparison, computation-required (numeric oracles), and
    computation-optional items, each labeled with expected necessity
    (REQUIRED/OPTIONAL/NOT_NEEDED) and gold route.

Both suites carry a deterministic dev/final split (T12.20): dev items
may inform prompt work; FINAL items are frozen (checksum) before any
planner/interface tuning and gate metrics are computed on FINAL only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sympy as sp  # noqa: E402

fid_items: list[dict] = []
con_items: list[dict] = []


def fidrec(kind, category, question, op, faithful, *, expected_status,
           mutating=None, dev=False):
    fid_items.append({
        "eval_id": f"mfid-v1-{len(fid_items) + 1:04d}",
        "kind": kind,                       # REJECT | FLAG | CONTROL
        "category": category,
        "question": question,
        "answer_type": "abstain",
        "operation": op,
        "faithful_inputs": faithful,
        "expected_engine_status": expected_status,
        "mutating_inputs": mutating,
        "split": "dev" if dev else "final",
    })


def conrec(category, question, *, necessity, gold_route, expected=None,
           atol=1e-6, rtol=1e-6, dev=False, oracle=""):
    con_items.append({
        "eval_id": f"mcon-v1-{len(con_items) + 1:04d}",
        "category": category,
        "question": question,
        "expected_necessity": necessity,
        "gold_route": gold_route,
        "answer_type": "abstain" if expected is None else "number",
        "expected": expected,
        "atol": atol,
        "rtol": rtol,
        "oracle_method": oracle,
        "split": "dev" if dev else "final",
    })


# ===========================================================================
# FIDELITY SUITE
# ===========================================================================

def build_fidelity():
    # ---- invalid distribution parameters (9, REJECT) ----
    bad_stats = [
        ("A normal distribution has mean 0 and standard deviation -1. "
         "Compute its differential entropy.",
         {"distribution": "normal",
          "parameters": {"mu": 0.0, "sigma": -1.0}, "at": 0.0},
         {"parameters": {"mu": 0.0, "sigma": 1.0}, "at": 0.0}),
        ("A normal distribution has mean 2 and standard deviation 0. "
         "Compute the pdf at x = 2.",
         {"distribution": "normal",
          "parameters": {"mu": 2.0, "sigma": 0.0}, "at": 2.0},
         {"parameters": {"mu": 2.0, "sigma": 1.0}, "at": 2.0}),
        ("A binomial distribution has n = 10 trials and success "
         "probability p = 1.5. Compute P(X = 5).",
         {"distribution": "binomial", "parameters": {"n": 10.0, "p": 1.5},
          "at": 5.0},
         {"parameters": {"n": 10.0, "p": 0.5}, "at": 5.0}),
        ("A binomial distribution has n = 10 trials and success "
         "probability p = -0.2. Compute P(X = 3).",
         {"distribution": "binomial", "parameters": {"n": 10.0, "p": -0.2},
          "at": 3.0}, None),
        ("A Poisson distribution has rate lambda = -2. Compute P(X = 1).",
         {"distribution": "poisson", "parameters": {"lambda": -2.0},
          "at": 1.0},
         {"parameters": {"lambda": 2.0}, "at": 1.0}),
        ("A normal distribution has mean 0 and standard deviation "
         "-0.01. Compute the cdf at x = 0.",
         {"distribution": "normal",
          "parameters": {"mu": 0.0, "sigma": -0.01}, "at": 0.0}, None),
        ("A binomial distribution has n = -5 trials and success "
         "probability p = 0.5. Compute P(X = 1).",
         {"distribution": "binomial", "parameters": {"n": -5.0, "p": 0.5},
          "at": 1.0}, None),
        ("A normal distribution has mean 0 and standard deviation -100. "
         "Compute the pdf at x = 1.",
         {"distribution": "normal",
          "parameters": {"mu": 0.0, "sigma": -100.0}, "at": 1.0}, None),
        ("A Poisson distribution has rate lambda = -0.5. Compute "
         "P(X = 0).",
         {"distribution": "poisson", "parameters": {"lambda": -0.5},
          "at": 0.0}, None),
        ("A Poisson distribution has rate lambda = -1. Compute "
         "P(X = 3).",
         {"distribution": "poisson", "parameters": {"lambda": -1.0},
          "at": 3.0},
         {"parameters": {"lambda": 1.0}, "at": 3.0}),
    ]
    for q, inputs, mut in bad_stats:
        fidrec("REJECT", "INVALID_PARAMS", q, "distribution_value",
               inputs, expected_status="INVALID_INPUT", mutating=mut)

    # ---- singular / degenerate linear systems (8, REJECT: FAIL) ----
    sing = [
        ("Invert the matrix [ 4 2; 2 1 ].", "matrix_inverse",
         {"matrix": [[4.0, 2.0], [2.0, 1.0]]},
         {"matrix": [[4.0, 2.0], [2.0, 2.0]]}),
        ("Invert the matrix [ 1 2 3; 4 5 6; 7 8 9 ].", "matrix_inverse",
         {"matrix": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]},
         None),
        ("Invert the matrix [ 0 0; 0 0 ].", "matrix_inverse",
         {"matrix": [[0.0, 0.0], [0.0, 0.0]]}, None),
        ("Solve the linear system 2x + 4y = 8 and 1x + 2y = 4.",
         "solve_linear_system",
         {"matrix": [[2.0, 4.0], [1.0, 2.0]], "b": [8.0, 4.0]}, None),
        ("Solve the linear system 1x + 1y = 2 and 2x + 2y = 4.",
         "solve_linear_system",
         {"matrix": [[1.0, 1.0], [2.0, 2.0]], "b": [2.0, 4.0]}, None),
        ("Invert the matrix [ 3 6; 1 2 ].", "matrix_inverse",
         {"matrix": [[3.0, 6.0], [1.0, 2.0]]}, None),
        ("Solve the linear system 0x + 0y = 1 and 1x + 1y = 3.",
         "solve_linear_system",
         {"matrix": [[0.0, 0.0], [1.0, 1.0]], "b": [1.0, 3.0]}, None),
        ("Invert the matrix [ 5 10; 2 4 ].", "matrix_inverse",
         {"matrix": [[5.0, 10.0], [2.0, 4.0]]}, None),
    ]
    for q, op, inputs, mut in sing:
        fidrec("REJECT", "SINGULAR_MATRIX", q, op, inputs,
               expected_status="FAIL", mutating=mut)

    # ---- malformed ODE specification (8, REJECT) ----
    odes = [
        ("Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 "
         "and y(1) = 4 (two initial values for a first-order equation).",
         {"equations": ["-2*y0"], "initial_state": [1.0, 4.0],
          "t_start": 0.0, "t_end": 1.0}, "INVALID_INPUT", None),
        ("Solve the ODE dy/dt = 3*y with no initial condition given, "
         "from t = 0 to t = 1.",
         {"equations": ["3*y0"], "initial_state": [],
          "t_start": 0.0, "t_end": 1.0}, "INVALID_INPUT", None),
        ("Solve the ODE dy/dt = k*y with initial condition y(0) = 2 to "
         "t = 1, where k is never given.",
         {"equations": ["k*y0"], "initial_state": [2.0],
          "t_start": 0.0, "t_end": 1.0}, "INVALID_INPUT", None),
        ("Solve dy/dt = y*y with y(0) = 1 up to t = 100.",
         {"equations": ["y0*y0"], "initial_state": [1.0],
          "t_start": 0.0, "t_end": 100.0}, "UNKNOWN", None),
        ("Solve dy/dt = -y from t = 0 to t = 1000000 with y(0) = 1.",
         {"equations": ["-y0"], "initial_state": [1.0],
          "t_start": 0.0, "t_end": 1000000.0}, "RESOURCE_LIMIT", None),
        ("Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 "
         "and report the state at t = 1 (the equation field is left "
         "empty).",
         {"equations": [], "initial_state": [1.0],
          "t_start": 0.0, "t_end": 1.0}, "INVALID_INPUT", None),
        ("Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 "
         "and y(0) = 2 (two conflicting initial values).",
         {"equations": ["-2*y0"], "initial_state": [1.0, 2.0],
          "t_start": 0.0, "t_end": 1.0}, "INVALID_INPUT", None),
        ("Solve dy/dt = -y from t = 0 to t = 2000000 with y(0) = 1.",
         {"equations": ["-y0"], "initial_state": [1.0],
          "t_start": 0.0, "t_end": 2000000.0}, "RESOURCE_LIMIT", None),
    ]
    for q, inputs, status, mut in odes:
        fidrec("REJECT", "MALFORMED_ODE", q, "solve_ode", inputs,
               expected_status=status, mutating=mut)

    # ---- negative physical quantities (8, FLAG: engine is unit-blind) ----
    neg = [
        ("A spring has stiffness k = -50 N/m. Compute the oscillation "
         "period of a 1 kg mass attached to it.", [-50.0, 1.0]),
        ("A projectile is launched with speed -20 m/s upward. Compute "
         "the maximum height, using g = 9.8.", [-20.0, 9.8]),
        ("A rod of length -2 m has linear density 3 kg/m. Compute its "
         "mass.", [-2.0, 3.0]),
        ("A capacitor has capacitance -0.000001 F and the circuit "
         "resistance is 1000 ohm. Compute the RC time constant.",
         [-0.000001, 1000.0]),
        ("A sample has variance -4 and mean 2. Compute its standard "
         "deviation.", [-4.0, 2.0]),
        ("Gas occupies volume -3 L at temperature 300 K and pressure 1 "
         "atm. Compute the amount in mol.", [-3.0, 300.0]),
        ("A wave has frequency -10 Hz and amplitude 2 m. Compute its "
         "period.", [-10.0, 2.0]),
        ("A concentration is -0.5 mol/L in a 2 L solution. Compute the "
         "moles of solute.", [-0.5, 2.0]),
        ("A radioactive sample has decay constant -0.1 per second. "
         "Compute its mean lifetime.", [-0.1, 1.0]),
    ]
    for q, vals in neg:
        fidrec("FLAG", "NEGATIVE_QUANTITY", q, "describe",
               {"values": vals}, expected_status="PASS")

    # ---- impossible optimization bounds (5, REJECT) ----
    bounds = [
        ("Minimize f(x) = x**2 on the bound x in [5, -5] (lower bound "
         "above upper bound).",
         {"expression": "x**2", "bound_low": 5.0, "bound_high": -5.0},
         {"expression": "x**2", "bound_low": -5.0, "bound_high": 5.0}),
        ("Minimize f(x) = (x - 1)**2 on the degenerate bound x in "
         "[3, 3].",
         {"expression": "(x - 1)**2", "bound_low": 3.0,
          "bound_high": 3.0}, None),
        ("Minimize f(x) = x**2 on the bound x in [2, 1].",
         {"expression": "x**2", "bound_low": 2.0, "bound_high": 1.0},
         None),
        ("Minimize f(x) = exp(x) on the bound x in [1000000, 100000].",
         {"expression": "exp(x)", "bound_low": 1000000.0,
          "bound_high": 100000.0}, None),
        ("Minimize f(x) = x**2 on the bound x in [0.5, 0.1].",
         {"expression": "x**2", "bound_low": 0.5, "bound_high": 0.1},
         None),
    ]
    for q, inputs, mut in bounds:
        fidrec("REJECT", "IMPOSSIBLE_BOUNDS", q, "minimize_scalar",
               inputs, expected_status="INVALID_INPUT", mutating=mut)

    # ---- NaN / Inf inputs (6, REJECT) ----
    for q, inputs in [
        ("A dataset is [1, Infinity, 3]. Compute its mean.",
         {"values": [1.0, 1e400, 3.0]}),
        ("Compute the mean of 1e400 (an infinite value).",
         {"values": [1e400]}),
        ("A dataset is [Infinity]. Compute its standard deviation.",
         {"values": [1e400]}),
        ("Compute the median of the values [2, 1e400, 4].",
         {"values": [2.0, 1e400, 4.0]}),
    ]:
        fidrec("REJECT", "NAN_INF", q, "describe", inputs,
               expected_status="INVALID_INPUT")
    fidrec("REJECT", "NAN_INF",
           "Find the root of sqrt(0 - 1) between 0 and 1 (the objective "
           "is complex everywhere).",
           "bracketed_root",
           {"expression": "sqrt(0 - 1)", "bracket_low": 0.0,
            "bracket_high": 1.0}, expected_status="FAIL")
    fidrec("REJECT", "NAN_INF",
           "Compute the correlation of x = [1, 2] with y = [1, 1e400].",
           "correlation", {"x": [1.0, 2.0], "y": [1.0, 1e400]},
           expected_status="INVALID_INPUT")

    # ---- oversized sweeps / resource limits (3, REJECT) ----
    fidrec("REJECT", "OVERSIZED_SWEEP",
           "Sweep the expression a + b + c + d over 64 values each of "
           "a, b, c and d.",
           "parameter_sweep",
           {"expression": "a + b + c + d",
            "sweeps": {k: [float(v) for v in range(64)] for k in "abcd"}},
           expected_status="RESOURCE_LIMIT")
    for n in (100000, 150000):
        fidrec("REJECT", "OVERSIZED_SWEEP",
               f"Sweep the expression x over an x-grid of {n} points "
               "from 0 to 1.",
               "parameter_sweep",
               {"expression": "x", "x": [i / (n - 1) for i in range(n)]},
               expected_status="RESOURCE_LIMIT")

    # ---- invalid root brackets (4, REJECT) ----
    brackets = [
        ("Find a root of f(x) = x**2 + 1 in the bracket [0, 2] (f is "
         "positive throughout).", "x**2 + 1", 0.0, 2.0,
         "INVALID_INPUT"),
        ("Find a root of f(x) = exp(x) in the bracket [0, 1].",
         "exp(x)", 0.0, 1.0, "INVALID_INPUT"),
        ("Find a root of f(x) = x**2 + 4 in the bracket [-1, 1].",
         "x**2 + 4", -1.0, 1.0, "INVALID_INPUT"),
        ("Find a root of f(x) = 1/x in the bracket [-1, 1] (the "
         "objective is undefined at 0).", "1/x", -1.0, 1.0, "FAIL"),
        ("Find a root of f(x) = cos(x) - x in the bracket [2, 1] "
         "(reversed bracket bounds).", "cos(x) - x", 2.0, 1.0,
         "INVALID_INPUT"),
    ]
    for q, expr, lo, hi, status in brackets:
        fidrec("REJECT", "INVALID_BRACKET", q, "bracketed_root",
               {"expression": expr, "bracket_low": lo,
                "bracket_high": hi}, expected_status=status)

    # ---- missing required parameters (6, REJECT) ----
    missing = [
        ("Compute the t-statistic for the values [1] against the null "
         "hypothesis.",
         "hypothesis_test",
         {"test": "ttest_1samp", "values": [1.0], "null_value": 0.0},
         None, None, "REJECT"),
        ("Fit a 2-parameter model p0 + p1*x to the single point (1, 3).",
         "curve_fit",
         {"model": "p0 + p1*x", "x": [1.0], "y": [3.0],
          "parameters": ["p0", "p1"]}, None, None, "REJECT"),
        ("Extrapolate the points (0, 1), (1, 2) linearly to x = 100.",
         "linear_interpolate",
         {"x": [0.0, 1.0], "y": [1.0, 2.0], "at": 100.0}, None, None,
         "REJECT"),
        ("Compute the correlation of x = [1, 2, 3] with y = [2, 4].",
         "correlation", {"x": [1.0, 2.0, 3.0], "y": [2.0, 4.0]}, None,
         None, "REJECT"),
        ("Compute the t-statistic for the sample [1, 2, 3] against a "
         "null value that is not provided.",
         "hypothesis_test",
         {"test": "ttest_1samp", "values": [1.0, 2.0, 3.0]}, None,
         None, "FLAG"),
        ("Interpolate the value at x = 2.5 from the points (1, 1) and "
         "(3, ?) where the second y-value is missing.",
         "linear_interpolate", {"x": [1.0, 3.0], "y": [1.0], "at": 2.5},
         None, None, "REJECT"),
    ]
    for q, op, inputs, mut, mut2, kind in missing:
        fidrec(kind, "MISSING_PARAM", q, op, inputs,
               expected_status=("PASS" if kind == "FLAG"
                                else "INVALID_INPUT"), mutating=mut)

    # ---- malicious / adversarial expressions (6, REJECT) ----
    malicious = [
        ("Integrate __import__('os').system('echo pwned') from 0 to 1.",
         {"expression": "__import__('os').system('echo pwned')",
          "lower": 0.0, "upper": 1.0}, "definite_integral", None),
        ("Integrate open('C:/Windows/win.ini') from 0 to 1.",
         {"expression": "open('C:/Windows/win.ini')", "lower": 0.0,
          "upper": 1.0}, "definite_integral", None),
        ("Find the root of x.__class__ between 0 and 1.",
         {"expression": "x.__class__", "bracket_low": 0.0,
          "bracket_high": 1.0}, "bracketed_root", None),
        ("Differentiate 9**9**9**9 at x = 1.",
         {"expression": "9**9**9**9", "at": 1.0},
         "numerical_derivative", None),
        ("Integrate eval(input()) from 0 to 1.",
         {"expression": "eval(input())", "lower": 0.0, "upper": 1.0},
         "definite_integral", None),
        ("Integrate the expression '2x +' (syntactically broken) from "
         "0 to 1.",
         {"expression": "2x +", "lower": 0.0, "upper": 1.0},
         "definite_integral",
         {"expression": "2*x", "lower": 0.0, "upper": 1.0}),
    ]
    for q, inputs, op, mut in malicious:
        fidrec("REJECT", "MALICIOUS_EXPR", q, op, inputs,
               expected_status="INVALID_INPUT", mutating=mut)

    # ---- ambiguous parameters (8, FLAG) ----
    ambiguous = [
        ("A normal distribution has 'parameter' 2 and mean 0. Compute "
         "P(X < 1).", [2.0, 0.0]),
        ("A dataset has spread 3 and mean 5. Compute its variance.",
         [3.0, 5.0]),
        ("The reaction rate is 2 (units unspecified) at temperature "
         "300 K. Compute the time constant.", [2.0, 300.0]),
        ("The distribution has scale 4 and location 1. Compute the "
         "median.", [4.0, 1.0]),
        ("A fit has R2 = 0.9 over 10 points. Compute the correlation "
         "coefficient.", [0.9, 10.0]),
        ("The signal has amplitude 5 and frequency 2 Hz. Compute its "
         "power.", [5.0, 2.0]),
        ("A growth factor of 3 per step is given over 4 steps. Compute "
         "the growth rate constant.", [3.0, 4.0]),
        ("The column has mean 7 across 9 rows. Compute the standard "
         "error.", [7.0, 9.0]),
    ]
    for q, vals in ambiguous:
        fidrec("FLAG", "AMBIGUOUS_PARAM", q, "describe",
               {"values": vals}, expected_status="PASS")

    # ---- conflicting units (6, FLAG) ----
    conflict = [
        ("A car travels 100 km in 1 hour; its speed is also recorded as "
         "50 miles/hour. Compute the distance traveled in meters using "
         "both records.", [100.0, 50.0]),
        ("A tank fills at 10 L/min and drains at 0.002 cubic meters per "
         "second. Compute the net rate in L/s (check the units).",
         [10.0, 0.002]),
        ("The drug dose is 500 mg; the concentration is 0.5 g/L. "
         "Compute the volume in mL.", [500.0, 0.5]),
        ("A force of 2 N acts on 500 g. Compute the acceleration in "
         "m/s2 using F = ma with F in kg*m/s2.", [2.0, 500.0]),
        ("A rod is 2 m long and also listed as 150 cm. Compute its "
         "density given a mass of 30 kg, using both lengths.",
         [2.0, 150.0, 30.0]),
        ("The wave travels 1 km in 2 s; the frequency is 500 per "
         "minute. Compute the wavelength in m.", [1.0, 2.0, 500.0]),
    ]
    for q, vals in conflict:
        fidrec("FLAG", "CONFLICTING_UNITS", q, "describe",
               {"values": vals}, expected_status="PASS")

    # ---- numerical warning (1, REJECT) ----
    fidrec("REJECT", "NUMERICAL_WARNING",
           "Integrate f(x) = sin(1/x) from x = 0 to x = 1.",
           "definite_integral",
           {"expression": "sin(1/x)", "lower": 0.0, "upper": 1.0},
           expected_status="NUMERICAL_WARNING")

    # ---- control: reversed integration limits are LEGAL math (dev) ----
    x = sp.symbols("x")
    fidrec("CONTROL", "CONTROL_REVERSED_LIMITS",
           "Integrate f(x) = x**2 from 1 to 0 (reversed limits).",
           "definite_integral",
           {"expression": "x**2", "lower": 1.0, "upper": 0.0},
           expected_status="PASS", dev=True)


# ===========================================================================
# CONCEPTUAL SUITE
# ===========================================================================

def build_conceptual():
    # ---- conceptual science (24) ----
    sci = [
        "Why does entropy increase in an isolated system?",
        "What is the definition of an ideal gas?",
        "Explain the difference between speed and velocity.",
        "What does Newton's first law state?",
        "Why is the sky blue during the day?",
        "What is the difference between heat and temperature?",
        "Explain why metals conduct electricity.",
        "What is the meaning of half-life in radioactive decay?",
        "Does increasing the temperature of a gas at fixed volume "
        "increase its pressure? Explain why.",
        "What is the definition of an acid in the Bronsted-Lowry model?",
        "Why do heavier elements generally have more neutrons than "
        "protons?",
        "Explain the concept of electrical resistance.",
        "What does the second law of thermodynamics imply about heat "
        "flow direction?",
        "What is the difference between an element and a compound?",
        "Explain why friction converts kinetic energy into heat.",
        "What is the physical meaning of a wave's amplitude?",
        "Why is water a polar molecule?",
        "What does Ohm's law state qualitatively?",
        "Explain the concept of conservation of momentum.",
        "What is the difference between mass and weight?",
        "Why does ice float on liquid water?",
        "What is the definition of electric field strength?",
        "Explain why sound travels faster in water than in air.",
        "What does pH measure qualitatively?",
    ]
    for i, q in enumerate(sci):
        conrec("CONCEPTUAL_SCIENCE", q, necessity="NOT_NEEDED",
               gold_route="NO_COMPUTE", oracle="conceptual prose",
               dev=i >= 18)

    # ---- conceptual math (20) ----
    mathq = [
        "What is overfitting in model fitting?",
        "What is the definition of a derivative?",
        "Explain the difference between interpolation and extrapolation.",
        "What does the determinant of a matrix represent geometrically?",
        "What is the definition of a confidence interval?",
        "Explain what a p-value means (not how to compute it).",
        "What is the difference between correlation and causation?",
        "What does linear independence of vectors mean?",
        "What is the definition of a limit in calculus?",
        "Explain the central limit theorem in words.",
        "What is the difference between a population and a sample?",
        "What does the rank of a matrix tell you about its null space?",
        "What is over- versus under-damping in an oscillating system?",
        "Explain what standard deviation measures.",
        "What is the definition of an eigenvalue?",
        "What is the difference between precision and accuracy?",
        "Explain the law of large numbers in words.",
        "What does it mean for a numerical method to be stable?",
        "What is the role of a unit test in scientific software, in "
        "words?",
        "Explain the bias-variance tradeoff.",
    ]
    for i, q in enumerate(mathq):
        conrec("CONCEPTUAL_MATH", q, necessity="NOT_NEEDED",
               gold_route="NO_COMPUTE", oracle="conceptual prose",
               dev=i >= 15)

    # ---- factual retrieval (16) ----
    fact = [
        "What is the speed of light in vacuum?",
        "What is the gravitational acceleration on Earth (standard "
        "value)?",
        "What is Avogadro's number?",
        "What is the boiling point of water at 1 atm in Celsius?",
        "What is the universal gas constant R?",
        "What is Planck's constant?",
        "What is the melting point of iron in Celsius?",
        "What is the elementary charge?",
        "What is the molar mass of carbon-12?",
        "What is the density of pure water at 4 degrees Celsius?",
        "What is the Stefan-Boltzmann constant?",
        "What is the Faraday constant?",
        "What is the speed of sound in air at room temperature?",
        "What is the atomic number of oxygen?",
        "What is the SI unit of magnetic field strength?",
        "What is the value of absolute zero in Celsius?",
    ]
    for i, q in enumerate(fact):
        conrec("FACTUAL_RETRIEVAL", q, necessity="NOT_NEEDED",
               gold_route="NO_COMPUTE", oracle="retrieved fact",
               dev=i >= 12)

    # ---- qualitative comparison (12) ----
    qual = [
        "Is interpolation always more reliable than extrapolation? "
        "Give one reason.",
        "Is a larger sample size always better for a study? Explain.",
        "Does a higher p-value prove the null hypothesis is true?",
        "Is a stiffer spring always faster at oscillating than a soft "
        "one for the same mass? Explain.",
        "Does more data always reduce overfitting? Explain briefly.",
        "Is the arithmetic mean always larger than the geometric mean? "
        "Explain.",
        "Can correlation be negative while a causal effect is positive? "
        "Explain.",
        "Is an exact method always preferable to a numerical "
        "approximation? Explain.",
        "Does a narrow confidence interval always mean the estimate is "
        "unbiased? Explain.",
        "Is a numeric answer with many digits necessarily more "
        "accurate? Explain.",
        "Can a model with higher training accuracy generalize worse? "
        "Explain.",
        "Is the median always equal to the mean for symmetric "
        "distributions? Explain.",
    ]
    for i, q in enumerate(qual):
        conrec("QUALITATIVE_COMPARE", q, necessity="NOT_NEEDED",
               gold_route="NO_COMPUTE", oracle="conceptual prose",
               dev=i >= 9)

    # ---- computation truly required (18, numeric oracles) ----
    x = sp.symbols("x")
    comp: list[tuple[str, str, dict, object, float, float, str]] = []
    data_sets = [([2.0, 4.0, 6.0, 8.0], 5.0),
                 ([1.5, 2.5, 3.5], 2.5),
                 ([10.0, 20.0, 30.0, 40.0, 50.0], 30.0),
                 ([0.1, 0.2, 0.3, 0.4], 0.25)]
    for vals, mean in data_sets:
        xs = ", ".join(f"{v:g}" for v in vals)
        comp.append((f"Compute the mean of the values [{xs}].",
                     "describe", {"values": vals}, mean, 1e-9, 1e-9,
                     "exact arithmetic"))
    integrals = [("x**2", 0.0, 1.0), ("sin(x)", 0.0, float(sp.pi / 2)),
                 ("exp(x)", 0.0, 1.0), ("x**3 - 2*x", 0.0, 2.0)]
    for expr, lo, hi in integrals:
        exact = float(sp.integrate(sp.sympify(expr), (x, lo, hi))
                      .evalf(15))
        comp.append((f"Compute the definite integral of {expr} from "
                     f"{lo:g} to {hi:g}.",
                     "definite_integral",
                     {"expression": expr, "lower": lo, "upper": hi},
                     exact, 1e-8, 1e-8, "sympy exact"))
    roots = [("x**2 - 2", 0.0, 2.0), ("cos(x) - x", 0.0, 1.0),
             ("exp(x) - 5", 0.0, 3.0), ("x**3 - x - 2", 1.0, 2.0)]
    for expr, lo, hi in roots:
        r = float(sp.nsolve(sp.sympify(expr), (lo + hi) / 2).evalf(15))
        comp.append((f"Find the root of f(x) = {expr} in [{lo:g}, "
                     f"{hi:g}].", "bracketed_root",
                     {"expression": expr, "bracket_low": lo,
                      "bracket_high": hi}, r, 1e-8, 1e-8, "sympy exact"))
    derivs = [("x**3", 2.0), ("sin(x)", float(sp.pi / 6)),
              ("exp(2*x)", 0.5), ("x**2", -1.0)]
    for expr, at in derivs:
        want = float(sp.diff(sp.sympify(expr), x)
                     .subs(x, sp.nsimplify(at)).evalf(15))
        comp.append((f"Differentiate {expr} at x = {at:g}.",
                     "numerical_derivative",
                     {"expression": expr, "at": at},
                     want, 1e-6, 1e-6, "sympy exact"))
    lins = [([[2.0, 1.0], [1.0, 3.0]], [3.0, 5.0]),
            ([[4.0, -1.0], [2.0, 2.0]], [1.0, 8.0])]
    for m, b in lins:
        sol = [float(v) for v in sp.Matrix(m).inv() * sp.Matrix(b)]
        comp.append((f"Solve the linear system with matrix "
                     f"[ {m[0][0]:g} {m[0][1]:g}; {m[1][0]:g} "
                     f"{m[1][1]:g} ] and b = [{b[0]:g}, {b[1]:g}].",
                     "solve_linear_system", {"matrix": m, "b": b},
                     sol[0], 1e-8, 1e-8, "sympy exact"))
    for q, op, inputs, expected, atol, rtol, oracle in comp:
        conrec("COMPUTE_REQUIRED", q, necessity="REQUIRED",
               gold_route=_gold_route_for(op), expected=expected,
               atol=atol, rtol=rtol, oracle=oracle)

    # ---- computation optional (10, exact trivial arithmetic) ----
    opt = [
        ("A distance is 2 km. Express it in meters.", 2000.0),
        ("A time is 5 minutes. Express it in seconds.", 300.0),
        ("A mass is 3 kg. Express it in grams.", 3000.0),
        ("A length is 1.5 m. Express it in centimeters.", 150.0),
        ("A volume is 2 L. Express it in mL.", 2000.0),
        ("A duration is 0.25 hours. Express it in minutes.", 15.0),
        ("A speed is 1000 m per hour. Express it in km per hour.", 1.0),
        ("A temperature change is 2 degrees C. Express it as a change "
         "in kelvin.", 2.0),
        ("A length is 250 cm. Express it in m.", 2.5),
        ("A mass is 0.5 kg. Express it in mg (1 kg = 1000000 mg).",
         500000.0),
    ]
    for i, (q, expected) in enumerate(opt):
        conrec("COMPUTE_OPTIONAL", q, necessity="OPTIONAL",
               gold_route="NO_COMPUTE", expected=expected, atol=1e-9,
               rtol=1e-9, oracle="exact unit arithmetic (T4-level "
                                 "trivial)", dev=i >= 7)


def _gold_route_for(op: str) -> str:
    return {
        "describe": "STATISTICS",
        "definite_integral": "NUMERICAL_INTEGRATION",
        "bracketed_root": "ROOT_FINDING",
        "numerical_derivative": "DERIVATIVE",
        "solve_linear_system": "LINEAR_ALGEBRA",
    }[op]


# ===========================================================================
# build-time verification + freeze
# ===========================================================================

def main() -> int:
    build_fidelity()
    build_conceptual()

    from sciencemath.scicomp.executor import execute
    from sciencemath.scicomp.fidelity import (
        FIDELITY_FAIL, P_USER_GIVEN, check_fidelity)

    # --- 1. verify faithful requests against the FROZEN engine ---
    status_mismatch: list[str] = []
    for it in fid_items:
        env = execute({"operation": it["operation"],
                       "inputs": it["faithful_inputs"]})
        actual = env["status"]
        it["verified_engine_status"] = actual
        if it["kind"] in ("REJECT", "CONTROL") and \
                actual != it["expected_engine_status"]:
            status_mismatch.append(
                f"{it['eval_id']} [{it['category']}]: got {actual}, "
                f"declared {it['expected_engine_status']}")
        elif it["kind"] == "FLAG" and actual != "PASS":
            status_mismatch.append(
                f"{it['eval_id']} [FLAG]: engine returned {actual}, "
                "expected PASS (unit-blind)")

    # --- 2. verify mutating requests are rejected by the fidelity gate ---
    mutation_gate_fail: list[str] = []
    n_mutations = 0
    for it in fid_items:
        if not it["mutating_inputs"]:
            continue
        n_mutations += 1
        request = {
            "operation": it["operation"],
            "compute_required": True,
            "parameters": it["mutating_inputs"],
            "source_inputs": it["faithful_inputs"],
            "parameter_provenance": {k: P_USER_GIVEN
                                     for k in it["mutating_inputs"]},
            "expected_result_type": "scalar",
            "reason_for_compute": "build-time mutation verification",
        }
        r = check_fidelity(request, it["question"])
        if r.status != FIDELITY_FAIL:
            mutation_gate_fail.append(
                f"{it['eval_id']}: gate returned {r.status} "
                f"(failures={r.failures}) — silent repair NOT rejected")

    out = ROOT / "evaluations/t12/suites"
    for name, items in (("fidelity", fid_items),
                        ("conceptual", con_items)):
        d = out / name / "v1"
        d.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(it, sort_keys=True) + "\n"
                          for it in items)
        (d / "questions.jsonl").write_text(payload, encoding="utf-8",
                                           newline="\n")
        digest = hashlib.sha256(
            (d / "questions.jsonl").read_bytes()).hexdigest()
        (d / "checksum.txt").write_text(digest + "\n", encoding="utf-8")
        dev = sum(1 for it in items if it["split"] == "dev")
        by_cat: dict[str, dict] = {}
        for it in items:
            c = by_cat.setdefault(it["category"], {"final": 0, "dev": 0})
            c["dev" if it["split"] == "dev" else "final"] += 1
        manifest = {
            "suite_name": f"mango-scicomp-{name}-v1",
            "version": "v1",
            "frozen_at": "2026-09-08",
            "sha256": digest,
            "total_questions": len(items),
            "split_counts": {"final": len(items) - dev, "dev": dev},
            "by_category": by_cat,
            "split_policy": "dev items may inform prompt work; FINAL "
                            "items were frozen before planner/interface "
                            "tuning; gate metrics are computed on FINAL "
                            "only (T12.20).",
        }
        if name == "fidelity":
            manifest["oracle_policy"] = (
                "REJECT items: expected_engine_status verified against "
                "the FROZEN T11 engine at build time on the faithful "
                "request (0 mismatches tolerated). FLAG items: the "
                "unit-blind engine returns PASS but the specification "
                "is physically invalid/ambiguous/unit-conflicting — the "
                "pipeline must flag it and NOT assert a number. "
                "Grading: an item is handled correctly iff the final "
                "answer asserts NO numeric answer AND no mutated "
                "request was executed to a PASS envelope (T12.24).")
            manifest["mutation_verification"] = {
                "mutating_cases": n_mutations,
                "gate_rejections": n_mutations - len(mutation_gate_fail),
                "failures": mutation_gate_fail,
            }
        (d / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"{name}: {len(items)} items (final {len(items) - dev}, "
              f"dev {dev}); sha {digest[:12]}…")

    ok = True
    if status_mismatch:
        ok = False
        print(f"ENGINE STATUS MISMATCHES ({len(status_mismatch)}):")
        for m in status_mismatch:
            print(" ", m)
    if mutation_gate_fail:
        ok = False
        print(f"MUTATION GATE FAILURES ({len(mutation_gate_fail)}):")
        for m in mutation_gate_fail:
            print(" ", m)
    if ok:
        print(f"FIDELITY_SUITE_VERIFIED: engine statuses match, "
              f"{n_mutations}/{n_mutations} mutations rejected by gate")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())