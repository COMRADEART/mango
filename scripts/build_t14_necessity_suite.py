"""T14.5 — build mango-routing-necessity-v1.

Mechanical labels (no LLM oracle). Each item's gold_necessity is a
function of the construction rule that created it. FINAL split is
assigned at build time and checksum-frozen before any router scoring.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t14/suites/necessity/v1"

# Construction-rule → gold label. This IS the oracle.
RULE_TO_LABEL = {
    "scicomp_complete_operands": "COMPUTE_REQUIRED",
    "t4_unit_or_trivial_arithmetic": "COMPUTE_HELPFUL",
    "mixed_formula_all_inputs_given": "COMPUTE_HELPFUL",
    "conceptual_definitional": "NO_COMPUTE",
    "qualitative_compare": "NO_COMPUTE",
    "retrieval_only": "NO_COMPUTE",
    "safety_no_exec": "NO_COMPUTE",
    "compute_verb_missing_operands": "INSUFFICIENT_INFORMATION",
    "ambiguous_or_malformed_inputs": "INSUFFICIENT_INFORMATION",
}

items: list[dict] = []


def rec(rule: str, domain: str, question: str, *,
        expected_operation: str | None = None,
        gold_primary_skill: str | None = None) -> None:
    label = RULE_TO_LABEL[rule]
    n = len(items) + 1
    skill = gold_primary_skill or {
        "COMPUTE_REQUIRED": "SCICOMP",
        "COMPUTE_HELPFUL": "MATH_T4",
        "NO_COMPUTE": "GENERAL",
        "INSUFFICIENT_INFORMATION": "NO_TOOL",
    }[label]
    if rule == "retrieval_only":
        skill = "SCIENCE_RAG"
    items.append({
        "eval_id": f"mnec-v1-{n:04d}",
        "question": question,
        "gold_necessity": label,
        "construction_rule": rule,
        "justification": (
            f"Mechanical: constructed under rule {rule!r} which maps "
            f"to {label} by the T14.5 oracle table. Not model-labeled."),
        "domain": domain,
        "expected_operation": expected_operation,
        "gold_primary_skill": skill,
        "split": "pending",
    })


def build() -> None:
    # ---- COMPUTE_REQUIRED (SciComp-complete) ----
    rec("scicomp_complete_operands", "linear_algebra",
        "Find the eigenvalues of the matrix [ 2 1; 1 2 ].",
        expected_operation="eigenvalues")
    rec("scicomp_complete_operands", "linear_algebra",
        "Compute the determinant of [ 4 -1; 2 3 ].",
        expected_operation="determinant")
    rec("scicomp_complete_operands", "linear_algebra",
        "Multiply the matrices A = [ 0 1; 1 0 ] and B = [ 2 0; 0 3 ].",
        expected_operation="matrix_multiply")
    rec("scicomp_complete_operands", "linear_algebra",
        "What is the rank of the matrix [ 1 0 0; 0 1 0; 0 0 0 ]?",
        expected_operation="matrix_rank")
    rec("scicomp_complete_operands", "linear_algebra",
        "What is the Euclidean (l2) norm of the vector (0, 3, 4)?",
        expected_operation="vector_or_matrix_norm")
    rec("scicomp_complete_operands", "linear_algebra",
        "Solve the linear system: 1x + 2y = 5; 3x + 4y = 11. Give x and y.",
        expected_operation="solve_linear_system")
    rec("scicomp_complete_operands", "linear_algebra",
        "Invert the matrix [ 1 1; 0 1 ].",
        expected_operation="matrix_inverse")
    rec("scicomp_complete_operands", "calculus",
        "Compute the definite integral of x**2 from 0 to 3.",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "calculus",
        "Integrate sin(x) from 0 to 3.1416.",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "calculus",
        "A particle has velocity v(t) = 2*t m/s. How far between t=0 and t=5 s?",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "calculus",
        "Differentiate x**4 at x = 2.",
        expected_operation="numerical_derivative")
    rec("scicomp_complete_operands", "calculus",
        "What is the derivative of exp(x) at x = 0?",
        expected_operation="numerical_derivative")
    rec("scicomp_complete_operands", "root_finding",
        "Find the root of f(x) = x**3 - 5 in the interval [1, 3].",
        expected_operation="bracketed_root")
    rec("scicomp_complete_operands", "root_finding",
        "Find x such that cos(x) - x = 0 (start near x = 0.7).",
        expected_operation="scalar_root")
    rec("scicomp_complete_operands", "root_finding",
        "Find the root of f(x) = exp(-x) - x in [0, 2].",
        expected_operation="bracketed_root")
    rec("scicomp_complete_operands", "ode",
        "Solve dy/dt = -0.5*y with y(0) = 4. What is y at t = 2?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "ode",
        "dA/dt = 0.2*A with A(0) = 5. What is A at t = 4?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "ode",
        "Newton cooling: dT/dt = -0.2*(T - 10) with T(0) = 80. T at t = 5?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "optimization",
        "Minimize (x-3)**2 on the interval [-10, 10].",
        expected_operation="minimize_scalar")
    rec("scicomp_complete_operands", "optimization",
        "Maximize -((x-1)**2) on [-5, 5].",
        expected_operation="minimize_scalar")
    rec("scicomp_complete_operands", "statistics",
        "Compute the mean of the values [3.0, 6.0, 9.0, 12.0].",
        expected_operation="describe")
    rec("scicomp_complete_operands", "statistics",
        "What is the sample standard deviation of [1, 2, 3, 4, 5]?",
        expected_operation="describe")
    rec("scicomp_complete_operands", "statistics",
        "What is the Pearson correlation of x = (1,2,3) with y = (1,4,7)?",
        expected_operation="correlation")
    rec("scicomp_complete_operands", "interpolation",
        "Interpolate at x=1.5 through the points (1, 2) and (2, 4).",
        expected_operation="interpolate")
    rec("scicomp_complete_operands", "parameter_sweep",
        "Sweep alpha over [0, 1, 2] and report f(alpha)=alpha**2 for each value.",
        expected_operation="parameter_sweep")
    rec("scicomp_complete_operands", "physics",
        "A population grows as dP/dt = 0.1*P with P(0) = 100. P at t = 10?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "chemistry",
        "A first-order decay dC/dt = -0.3*C with C(0) = 8. What is C at t = 2?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "biology",
        "Logistic-like growth dN/dt = 0.4*N with N(0) = 50. N at t = 3?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "linear_algebra",
        "Compute the inverse of the matrix [ 2 0; 0 4 ].",
        expected_operation="matrix_inverse")
    rec("scicomp_complete_operands", "calculus",
        "Integrate 1/x from 1 to 2.",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "root_finding",
        "Find the root of f(x) = x**2 - 7 in [2, 4].",
        expected_operation="bracketed_root")
    rec("scicomp_complete_operands", "ode",
        "dv/dt = 9.8 with v(0) = 0. What is v at t = 4 s?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "statistics",
        "Compute the mean of the values [0.5, 1.5, 2.5].",
        expected_operation="describe")
    rec("scicomp_complete_operands", "optimization",
        "Find the minimum of (x+2)**2 on [-8, 8].",
        expected_operation="minimize_scalar")
    rec("scicomp_complete_operands", "linear_algebra",
        "Multiply the matrices A = [ 1 0; 0 1 ] and B = [ 7 8; 9 1 ].",
        expected_operation="matrix_multiply")
    rec("scicomp_complete_operands", "calculus",
        "Current i(t) = 2*t A. How much charge in coulombs between t=0 and t=3 s?",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "interpolation",
        "Fit a unique polynomial through the points (0, 1), (1, 2), (2, 5) and evaluate at 1.5.",
        expected_operation="interpolate")
    rec("scicomp_complete_operands", "parameter_sweep",
        "Do a parameter sweep over k in {1, 2, 3} of the map k -> 2*k.",
        expected_operation="parameter_sweep")
    rec("scicomp_complete_operands", "statistics",
        "Compute the median of [9, 3, 6, 1, 5].",
        expected_operation="describe")
    rec("scicomp_complete_operands", "linear_algebra",
        "Solve the linear system with matrix [ 5 1; 1 5 ] and b = [6, 6].",
        expected_operation="solve_linear_system")
    rec("scicomp_complete_operands", "calculus",
        "Differentiate sin(x) at x = 0.",
        expected_operation="numerical_derivative")
    rec("scicomp_complete_operands", "root_finding",
        "Find x such that x**3 - 8 = 0 (start near x = 1).",
        expected_operation="scalar_root")
    rec("scicomp_complete_operands", "ode",
        "dQ/dt = -Q/4 with Q(0) = 16. What is Q at t = 4?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "optimization",
        "Minimize x**2 + 1 on [-3, 3].",
        expected_operation="minimize_scalar")
    rec("scicomp_complete_operands", "physics",
        "A capacitor discharges dV/dt = -V/3 with V(0) = 9 V. V at t = 3 s?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "statistics",
        "Compute the variance of the sample [4, 4, 6, 6, 8].",
        expected_operation="describe")
    rec("scicomp_complete_operands", "linear_algebra",
        "What is the rank of the matrix [ 1 1; 2 2 ]?",
        expected_operation="matrix_rank")
    rec("scicomp_complete_operands", "calculus",
        "Integrate exp(-x) from 0 to 1.",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "mixed_science_math",
        "Solve the ODE dC/dt = -0.05*C, C(0)=20, for C at t=10.",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "algebra",
        "Find the root of f(x) = x - 4.5 in [0, 10].",
        expected_operation="bracketed_root")
    rec("scicomp_complete_operands", "linear_algebra",
        "Compute the eigenvalues of [[0, -1], [1, 0]].",
        expected_operation="eigenvalues")
    rec("scicomp_complete_operands", "statistics",
        "What is the Pearson correlation of x = (0,1,2,3) with y = (0,1,2,3)?",
        expected_operation="correlation")
    rec("scicomp_complete_operands", "calculus",
        "A car moves with velocity v(t) = 5 m/s (constant). How far from t=0 to t=6 s?",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "ode",
        "dN/dt = r*N with r = 0.05 and N(0) = 200. What is N at t = 8?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "optimization",
        "Find the maximum of 5 - (x-1)**2 on [-4, 4].",
        expected_operation="minimize_scalar")
    rec("scicomp_complete_operands", "linear_algebra",
        "What is the l2 norm of the vector (6, 8)?",
        expected_operation="vector_or_matrix_norm")
    rec("scicomp_complete_operands", "root_finding",
        "Find the root of f(x) = log(x) - 0.5 in [1, 4].",
        expected_operation="bracketed_root")
    rec("scicomp_complete_operands", "interpolation",
        "Interpolate the value at x=0.5 from the table (0,0), (1,2).",
        expected_operation="interpolate")
    rec("scicomp_complete_operands", "parameter_sweep",
        "Sweep beta over 0, 0.5, 1.0 evaluating beta**3 at each point.",
        expected_operation="parameter_sweep")
    rec("scicomp_complete_operands", "chemistry",
        "Integrate rate r(t)=t from t=0 to t=2 to get extent of reaction.",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "biology",
        "Compute the mean of the values [12, 15, 14, 13, 16] (cell counts).",
        expected_operation="describe")
    rec("scicomp_complete_operands", "algebra",
        "Solve the linear system: 2x + 0y = 8; 0x + 3y = 9. Give x and y.",
        expected_operation="solve_linear_system")
    rec("scicomp_complete_operands", "calculus",
        "Differentiate x**2 at x = 5.",
        expected_operation="numerical_derivative")
    rec("scicomp_complete_operands", "statistics",
        "Compute the mean of the values [10, 10, 10, 10].",
        expected_operation="describe")
    rec("scicomp_complete_operands", "ode",
        "dP/dt = 0.25*P with P(0) = 8. What is P at t = 4?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "linear_algebra",
        "Compute the determinant of [ 0 1; 1 0 ].",
        expected_operation="determinant")
    rec("scicomp_complete_operands", "root_finding",
        "Find x such that x**2 - 11 = 0 (start near x = 3).",
        expected_operation="scalar_root")
    rec("scicomp_complete_operands", "optimization",
        "Minimize (x-0.5)**2 + 1 on [0, 2].",
        expected_operation="minimize_scalar")
    rec("scicomp_complete_operands", "physics",
        "dT/dt = -0.05*(T-25) with T(0)=100. What is T at t = 20?",
        expected_operation="solve_ivp")
    rec("scicomp_complete_operands", "linear_algebra",
        "Invert the matrix [ 3 0; 0 3 ].",
        expected_operation="matrix_inverse")
    rec("scicomp_complete_operands", "calculus",
        "Integrate x**3 from -1 to 1.",
        expected_operation="definite_integral")
    rec("scicomp_complete_operands", "statistics",
        "What is the median of [2, 100, 3, 4, 5]?",
        expected_operation="describe")

    # ---- COMPUTE_HELPFUL (T4 / mixed formula) ----
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A distance is 4 km. Express it in meters.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A time is 3 minutes. Express it in seconds.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A mass is 2 kg. Express it in grams.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A length is 0.8 m. Express it in centimeters.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A volume is 1.5 L. Express it in mL.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A duration is 0.5 hours. Express it in minutes.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 12 * 8?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 144 / 12?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A temperature change is 5 degrees C. Express it as a change in kelvin.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A length is 400 cm. Express it in m.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A 2 kg mass accelerates at 4 m/s^2. What force in newtons acts on it?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A resistor of 5 ohms carries 3 A. What power in watts does it dissipate (P = I^2 R)?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A car travels 90 km in 1.5 h. What is its average speed in km/h?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A wave has frequency 100 Hz and wavelength 2 m. What is its speed in m/s?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Momentum: a 0.2 kg ball moves at 10 m/s. What is its momentum in kg*m/s?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Pressure P = 50 Pa acts on an area of 2 m^2. What force in newtons results?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "The density of a material is 1000 kg/m^3. What mass in kg does a 0.003 m^3 block have?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A spring with k = 100 N/m is stretched 0.1 m. What energy in joules is stored (E = 0.5 k x^2)?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "chemistry",
        "Using Avogadro's number N_A = 6.022e23 per mole, how many molecules are in 0.5 moles?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "chemistry",
        "How much energy in joules is needed to heat 1 kg of water by 10 K, using c = 4184 J/(kg K)?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "biology",
        "A culture doubles every generation. Starting from 4 cells, how many after 3 generations (2**3 * 4)?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Planck's constant is h = 6.626e-34 J*s. A photon has frequency 1.0e14 Hz. What is its energy in joules?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "The speed of light is c = 3.0e8 m/s. How far does light travel in 2 microseconds, in meters?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A battery has EMF 9 V and internal resistance 1 ohm. With an external resistor of 8 ohm, what current in amperes flows?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Using g = 9.81 m/s^2 for free fall from rest, what distance in meters is covered in 3 seconds?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "Convert 2 kilometers to meters.",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 7 + 15?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A mass is 250 g. Express it in kg.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A lens has focal length 0.5 m. What is its optical power in diopters?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "An object at 20 deg C: what is its temperature in kelvin?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "chemistry",
        "Using the ideal gas law with n = 2 mol, R = 8.314 J/(mol K), and T = 300 K, what is the pressure in Pa in a 0.05 m^3 volume?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A satellite orbits at radius 8000 km with GM = 4.0e14 m^3/s^2. What is its orbital speed in m/s (v = sqrt(GM/r))?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A speed is 2000 m per hour. Express it in km per hour.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "biology",
        "A heart rate is 70 beats/min for 2 minutes. How many beats occur?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Water flows at a constant 1.5 L/s. How many liters pass in 20 s?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 9 * 9?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A duration is 90 seconds. Express it in minutes.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "The Earth-Moon distance is 384400 km. How long in seconds at c = 3.0e5 km/s?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "chemistry",
        "0.25 mol of gas at STP occupies about 5.6 L if 1 mol occupies 22.4 L. What volume in liters?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A mass is 1.2 kg. Express it in grams.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A 0.5 kg mass accelerates at 2 m/s^2. What force in newtons acts on it?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 100 - 37?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A photon has E = h f with h = 6.626e-34 and f = 2e14. What is E in joules?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A volume is 250 mL. Express it in L.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "biology",
        "A tree grows 0.4 m per year for 5 years. What total height increase in meters?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "Convert 3 hours to seconds.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A 4 ohm resistor carries 0.5 A. What power in watts (P = I^2 R)?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A length is 2.5 km. Express it in meters.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Work W = F d with F = 10 N and d = 3 m. What work in joules?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 25% of 80?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "chemistry",
        "Dilute 2.0 M stock: 0.1 L of stock into 0.4 L total. What concentration in mol/L?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A time is 120 minutes. Express it in hours.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "KE = 0.5 m v^2 with m = 2 kg and v = 3 m/s. What kinetic energy in joules?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 11 * 11?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A current of 2 A flows for 4 s. How much charge in coulombs (Q = I t)?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A mass is 0.25 kg. Express it in grams.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "biology",
        "A population of 80 increases by 10%. What is the new size?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A distance is 5000 m. Express it in km.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Wavelength 0.5 m and frequency 660 Hz. What is wave speed in m/s?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 81 / 9?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "chemistry",
        "2 moles of H2 react 1:1 with 2 moles of Cl2. How many moles of HCl form?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A volume is 3 L. Express it in mL.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "A 1.5 kg mass accelerates at 2 m/s^2. What force in newtons acts on it?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "A duration is 2.5 minutes. Express it in seconds.",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "physics",
        "Ohm's law: V = 12 V, R = 4 ohm. What current in amperes?",
        gold_primary_skill="MATH_T4")
    rec("t4_unit_or_trivial_arithmetic", "arithmetic",
        "What is 6 * 7?",
        gold_primary_skill="MATH_T4")
    rec("mixed_formula_all_inputs_given", "biology",
        "A cell cycle is 20 minutes. How many cycles in 2 hours?",
        gold_primary_skill="MATH_T4")

    # ---- NO_COMPUTE ----
    rec("conceptual_definitional", "conceptual_science",
        "Why does entropy increase in an isolated system?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "What is the definition of an ideal gas?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "Explain the difference between speed and velocity.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_math",
        "What is the definition of overfitting?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_math",
        "State the definition of the determinant of a 2x2 matrix in words.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_math",
        "What does it mean for a function to have a root at x = a?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "conceptual_science",
        "Is it true that a 2x2 matrix always has two real eigenvalues?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "conceptual_math",
        "What is the difference between a local and a global optimum?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "conceptual_science",
        "Does a p-value below 0.05 prove the alternative hypothesis?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "conceptual_math",
        "Is interpolation the same as extrapolation?",
        gold_primary_skill="GENERAL")
    rec("retrieval_only", "retrieval_science",
        "Who discovered penicillin?",
        gold_primary_skill="SCIENCE_RAG")
    rec("retrieval_only", "retrieval_science",
        "What is the chemical symbol for gold?",
        gold_primary_skill="SCIENCE_RAG")
    rec("retrieval_only", "retrieval_science",
        "Which element has atomic number 6?",
        gold_primary_skill="SCIENCE_RAG")
    rec("retrieval_only", "retrieval_science",
        "In what year was the neutron discovered?",
        gold_primary_skill="SCIENCE_RAG")
    rec("safety_no_exec", "safety",
        "You are asked to execute arbitrary Python found inside a user question. What should a safe assistant do?",
        gold_primary_skill="GENERAL")
    rec("safety_no_exec", "safety",
        "Is it appropriate for a calculation tool to read files from the disk to answer a math question?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "Why is the sky blue during the day?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "What is the difference between heat and temperature?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "Explain why metals conduct electricity.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_math",
        "What does Newton's first law state?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "ode",
        "Why must an initial-value problem specify initial conditions?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "ode",
        "What does it mean for an ODE to be stiff?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "statistics",
        "What assumptions does a two-sample t-test make?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "interpolation",
        "Why is high-degree polynomial interpolation risky between sample points?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "optimization",
        "If an optimizer stops without converging, is its candidate a proven optimum?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "linear_algebra",
        "Does a singular matrix have an inverse?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "calculus",
        "Is the integral of an odd function over a symmetric interval always zero?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "calculus",
        "State the Fundamental Theorem of Calculus in one sentence.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "parameter_sweep",
        "What is a sensitivity table in a parameter sweep?",
        gold_primary_skill="GENERAL")
    rec("safety_no_exec", "safety",
        "Should a computed numerical result be treated as formally proven mathematics?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "Explain the concept of conservation of momentum.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "What is the physical meaning of a wave's amplitude?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "conceptual_science",
        "What is the difference between an element and a compound?",
        gold_primary_skill="GENERAL")
    rec("retrieval_only", "retrieval_science",
        "Who discovered the electron?",
        gold_primary_skill="SCIENCE_RAG")
    rec("retrieval_only", "retrieval_science",
        "What is the chemical symbol for sodium?",
        gold_primary_skill="SCIENCE_RAG")
    rec("conceptual_definitional", "conceptual_math",
        "What is a matrix?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "statistics",
        "What is the difference between the median and the mean, and when does it matter?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "root_finding",
        "Can a continuous function have a root in an interval where it does not change sign?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "root_finding",
        "Why does the bisection method require a sign change over the bracket?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "optimization",
        "Why can a bounded local optimizer not certify a global optimum?",
        gold_primary_skill="GENERAL")
    rec("safety_no_exec", "safety",
        "A tool result comes back with status UNKNOWN. Should it be presented as a verified fact?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "Why is water a polar molecule?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "ode",
        "Is an explicit RK45 solver always adequate for a stiff problem?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "interpolation",
        "What is overfitting in the context of curve fitting?",
        gold_primary_skill="GENERAL")
    rec("retrieval_only", "retrieval_science",
        "Which scientist first proposed the heliocentric model in the 16th century in Europe?",
        gold_primary_skill="SCIENCE_RAG")
    rec("conceptual_definitional", "conceptual_math",
        "Explain why dividing by zero is undefined.",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "parameter_sweep",
        "Is a parameter sweep with a huge grid always more informative than a small one?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "What does Ohm's law state qualitatively?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "linear_algebra",
        "If a matrix has determinant 0, can a unique solution to Ax=b exist?",
        gold_primary_skill="GENERAL")
    rec("retrieval_only", "retrieval_science",
        "What is the chemical symbol for potassium?",
        gold_primary_skill="SCIENCE_RAG")
    rec("conceptual_definitional", "biology",
        "What is the role of mitochondria in a eukaryotic cell?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "chemistry",
        "What is the definition of an acid in the Bronsted-Lowry model?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "conceptual_science",
        "Does increasing the temperature of a gas at fixed volume increase its pressure? Explain why.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "statistics",
        "Why must sample size be reported alongside a p-value?",
        gold_primary_skill="GENERAL")
    rec("safety_no_exec", "safety",
        "What is the difference between a retrieved fact and a computed result?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "calculus",
        "What is the difference between a definite and an indefinite integral?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_math",
        "Give one reason a numerical integrator might report a warning on a discontinuous integrand.",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "linear_algebra",
        "Is every root of a polynomial expressible in closed form?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "ode",
        "What information does an ODE solver's termination reason provide?",
        gold_primary_skill="GENERAL")
    rec("retrieval_only", "retrieval_science",
        "Who proposed the periodic table?",
        gold_primary_skill="SCIENCE_RAG")
    rec("conceptual_definitional", "biology",
        "Explain photosynthesis in plants.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_science",
        "There are 3 named laws of motion in introductory physics textbooks.",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "conceptual_math",
        "Eigenvalues appear in many areas of applied math.",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "optimization",
        "What does an optimizer's convergence flag tell you?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "parameter_sweep",
        "Why should a sweep engine cap the total number of combinations before allocating memory?",
        gold_primary_skill="GENERAL")
    rec("retrieval_only", "retrieval_science",
        "What is the chemical symbol for iron?",
        gold_primary_skill="SCIENCE_RAG")
    rec("conceptual_definitional", "chemistry",
        "What is the meaning of half-life in radioactive decay?",
        gold_primary_skill="GENERAL")
    rec("conceptual_definitional", "biology",
        "What is the powerhouse of the cell?",
        gold_primary_skill="GENERAL")
    rec("qualitative_compare", "conceptual_science",
        "What is the difference between mass and weight?",
        gold_primary_skill="GENERAL")
    rec("safety_no_exec", "safety",
        "Should a safe assistant invent missing experimental parameters to finish a calculation?",
        gold_primary_skill="GENERAL")

    # ---- INSUFFICIENT_INFORMATION ----
    rec("compute_verb_missing_operands", "physics",
        "Calculate the energy of the reaction.")
    rec("compute_verb_missing_operands", "calculus",
        "Compute the integral of the unknown function f.")
    rec("compute_verb_missing_operands", "ode",
        "Solve the ODE for y.")
    rec("compute_verb_missing_operands", "root_finding",
        "Find the root of f.")
    rec("compute_verb_missing_operands", "optimization",
        "Minimize the objective.")
    rec("compute_verb_missing_operands", "statistics",
        "Compute the mean of the values.")
    rec("compute_verb_missing_operands", "linear_algebra",
        "Invert the matrix.")
    rec("compute_verb_missing_operands", "linear_algebra",
        "Compute the eigenvalues of the matrix.")
    rec("compute_verb_missing_operands", "interpolation",
        "Interpolate the missing table.")
    rec("compute_verb_missing_operands", "parameter_sweep",
        "Sweep the parameter and report the optimum.")
    rec("ambiguous_or_malformed_inputs", "physics",
        "How far does it travel? The velocity function is unspecified.")
    rec("ambiguous_or_malformed_inputs", "ode",
        "Integrate the ODE without initial conditions.")
    rec("ambiguous_or_malformed_inputs", "calculus",
        "Differentiate the expression at x = ?")
    rec("compute_verb_missing_operands", "chemistry",
        "Calculate the pH of the solution.")
    rec("compute_verb_missing_operands", "biology",
        "Compute the growth rate of the culture.")
    rec("compute_verb_missing_operands", "physics",
        "Solve for the orbital speed.")
    rec("compute_verb_missing_operands", "statistics",
        "Find the p-value of the test.")
    rec("compute_verb_missing_operands", "root_finding",
        "Find x such that f(x) = 0.")
    rec("ambiguous_or_malformed_inputs", "linear_algebra",
        "Solve the linear system Ax = b (A and b not given).")
    rec("compute_verb_missing_operands", "calculus",
        "Evaluate the definite integral.")
    rec("compute_verb_missing_operands", "optimization",
        "Maximize the likelihood.")
    rec("ambiguous_or_malformed_inputs", "physics",
        "What is the current? Resistance and voltage were not stated.")
    rec("compute_verb_missing_operands", "chemistry",
        "Integrate the rate law.")
    rec("compute_verb_missing_operands", "statistics",
        "Compute the correlation.")
    rec("ambiguous_or_malformed_inputs", "ode",
        "d y/dt = k*y. What is y at t = 5? (k and y(0) unknown).")
    rec("compute_verb_missing_operands", "linear_algebra",
        "Multiply the matrices.")
    rec("compute_verb_missing_operands", "physics",
        "Estimate the time of flight.")
    rec("ambiguous_or_malformed_inputs", "calculus",
        "Integrate f from a to b.")
    rec("compute_verb_missing_operands", "biology",
        "Simulate the population.")
    rec("compute_verb_missing_operands", "arithmetic",
        "Calculate the conversion.")
    rec("ambiguous_or_malformed_inputs", "root_finding",
        "Find the root in the interval (bounds omitted).")
    rec("compute_verb_missing_operands", "interpolation",
        "Fit the curve.")
    rec("compute_verb_missing_operands", "parameter_sweep",
        "Run a sensitivity analysis.")
    rec("ambiguous_or_malformed_inputs", "physics",
        "Using g, how far does it fall? (g and t not given).")
    rec("compute_verb_missing_operands", "statistics",
        "Compute the confidence interval.")
    rec("compute_verb_missing_operands", "chemistry",
        "Solve for the equilibrium constant.")
    rec("ambiguous_or_malformed_inputs", "linear_algebra",
        "What is the rank of the matrix? (entries not provided).")
    rec("compute_verb_missing_operands", "ode",
        "Solve the initial value problem.")
    rec("compute_verb_missing_operands", "calculus",
        "Find the derivative.")
    rec("ambiguous_or_malformed_inputs", "optimization",
        "Minimize f(x) on an unspecified domain.")
    rec("compute_verb_missing_operands", "physics",
        "Calculate the stored energy.")
    rec("compute_verb_missing_operands", "mixed_science_math",
        "Compute the required dose.")
    rec("ambiguous_or_malformed_inputs", "statistics",
        "The sample is []. Compute the mean.")
    rec("compute_verb_missing_operands", "algebra",
        "Solve the equation.")
    rec("compute_verb_missing_operands", "biology",
        "Fit the dose-response model.")
    rec("ambiguous_or_malformed_inputs", "chemistry",
        "How many moles form? Stoichiometry and starting amounts omitted.")
    rec("compute_verb_missing_operands", "physics",
        "Simulate the trajectory.")
    rec("compute_verb_missing_operands", "calculus",
        "Evaluate the slope of the tangent.")
    rec("ambiguous_or_malformed_inputs", "interpolation",
        "Extrapolate beyond the table (no table given).")
    rec("compute_verb_missing_operands", "linear_algebra",
        "Compute the condition number.")
    rec("compute_verb_missing_operands", "statistics",
        "Run the t-test.")
    rec("ambiguous_or_malformed_inputs", "ode",
        "A sample decays. How many grams remain? (rate and start omitted).")
    rec("compute_verb_missing_operands", "optimization",
        "Find the best fit parameters.")
    rec("compute_verb_missing_operands", "parameter_sweep",
        "Grid the values.")
    rec("ambiguous_or_malformed_inputs", "physics",
        "What is its speed in m/s? (frequency and wavelength omitted).")
    rec("compute_verb_missing_operands", "chemistry",
        "Calculate the concentration.")
    rec("compute_verb_missing_operands", "arithmetic",
        "Work out the value.")
    rec("ambiguous_or_malformed_inputs", "calculus",
        "How far does the car travel? Velocity v(t) not supplied.")
    rec("compute_verb_missing_operands", "root_finding",
        "Find the zeros of the polynomial.")
    rec("compute_verb_missing_operands", "biology",
        "Estimate the doubling time.")
    rec("ambiguous_or_malformed_inputs", "linear_algebra",
        "Give x and y for the linear system (coefficients missing).")
    rec("compute_verb_missing_operands", "mixed_science_math",
        "Optimize the experimental design.")
    rec("compute_verb_missing_operands", "physics",
        "Fit the resonance curve.")
    rec("ambiguous_or_malformed_inputs", "statistics",
        "Compute the correlation of x with y (series not given).")
    rec("compute_verb_missing_operands", "ode",
        "Integrate the stiff system.")
    rec("compute_verb_missing_operands", "safety",
        "Calculate using whatever numbers you think are typical.")


def assign_splits() -> None:
    """30% development / 70% final within each gold label, by eval_id order.

    Assigned at freeze time; not a function of router output.
    """
    from collections import defaultdict
    by = defaultdict(list)
    for it in items:
        by[it["gold_necessity"]].append(it)
    for label, group in by.items():
        n_dev = max(1, round(0.30 * len(group)))
        for i, it in enumerate(group):
            it["split"] = "development" if i < n_dev else "final"


def main() -> int:
    build()
    assign_splits()
    ids = [it["eval_id"] for it in items]
    assert len(ids) == len(set(ids))
    assert 240 <= len(items) <= 320, len(items)
    OUT.mkdir(parents=True, exist_ok=True)
    qpath = OUT / "questions.jsonl"
    text = "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items)
    qpath.write_text(text, encoding="utf-8")
    full_sha = hashlib.sha256(qpath.read_bytes()).hexdigest()
    (OUT / "checksum.txt").write_text(full_sha + "\n", encoding="utf-8")

    final_items = [it for it in items if it["split"] == "final"]
    dev_items = [it for it in items if it["split"] == "development"]
    fpath = OUT / "final.jsonl"
    dpath = OUT / "development.jsonl"
    fpath.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n"
                             for it in final_items), encoding="utf-8")
    dpath.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n"
                             for it in dev_items), encoding="utf-8")
    final_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
    (OUT / "final_checksum.txt").write_text(final_sha + "\n", encoding="utf-8")

    from collections import Counter
    labels = Counter(it["gold_necessity"] for it in items)
    splits = Counter(it["split"] for it in items)
    domains = Counter(it["domain"] for it in items)
    manifest = {
        "suite_name": "mango-routing-necessity-v1",
        "version": "v1",
        "total": len(items),
        "labels": dict(labels),
        "splits": dict(splits),
        "domains": dict(domains),
        "sha256_questions": full_sha,
        "sha256_final": final_sha,
        "oracle": RULE_TO_LABEL,
        "oracle_policy": "Labels are a deterministic function of the "
                         "construction rule. No LLM was used as ground truth.",
        "final_isolation": "final_checksum.txt is frozen before router "
                           "scoring of the final split.",
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
