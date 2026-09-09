"""T13.10 — build mango-scicomp-fidelity-transform-v1.

A fidelity-layer micro-benchmark for the T13 semantic classifier:
balanced across the nine T13.2 transformation classes plus the
empty/null discipline cases (T13.7/T13.8/T13.15).  Two case levels:

* ``transform`` — one source→compute value pair, measured through
  ``classify_transformation(source, compute, role)``;
* ``request``   — a full planner request, measured through
  ``check_fidelity(request, question)`` (information added/removed,
  provenance-coupled cases).

Oracle labels are DECLARED here (hand-reviewed), never computed from
the classifier under test.  The FINAL split is frozen by checksum
before any tuning against it (T13.10); only dev cases may inform
iteration.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t13/suites/fidelity-transform/v1"

# schema roles used at transform level (must mirror semantic.py table)
N, NL, NM = "NUMBER", "NUMBER_LIST", "NUMBER_MATRIX"

cases: list[dict] = []


def add(case_id, level, expected_class, *, operation="determinant",
        role=None, source=None, compute=None, request=None, question="",
        split="final", note=""):
    cases.append({
        "case_id": case_id, "level": level, "operation": operation,
        "role": role, "source": source, "compute": compute,
        "request": request, "question": question,
        "expected": expected_class, "split": split, "note": note,
    })


# --------------------------------------------------------------------------
# EXACT — identical value and representation
# --------------------------------------------------------------------------
_exact = [
    ("t-ex-01", N, 2.0, 2.0),
    ("t-ex-02", N, -3, -3),
    ("t-ex-03", NL, [1.0, 2.0], [1.0, 2.0]),
    ("t-ex-04", NM, [[4, 1], [2, 3]], [[4, 1], [2, 3]]),
    ("t-ex-05", "EXPRESSION", "x**2 + 1", "x**2 + 1"),
    ("t-ex-06", N, 0.5, 0.5),
    ("t-ex-07", NL, [7, -2], [7, -2]),
    ("t-ex-08", NM, [[0]], [[0]]),
    ("t-ex-09", N, 1e3, 1e3),
    ("t-ex-10", NL, [0.1], [0.1]),
    ("t-ex-11", N, -0.25, -0.25),
    ("t-ex-12", NL, [3, 4, 5], [3, 4, 5]),
]
for cid, role, s, c in _exact:
    add(cid, "transform", "EXACT", role=role, source=s, compute=c,
        note="identical value and representation")

# --------------------------------------------------------------------------
# REPRESENTATION_EQUIVALENT — different representation, same meaning
# --------------------------------------------------------------------------
_repr = [
    ("t-rp-01", N, 2, 2.0, "int -> float"),
    ("t-rp-02", N, 2.0, 2, "float -> int (exact)"),
    ("t-rp-03", NL, [1, 2], [1.0, 2.0], "int list -> float list"),
    ("t-rp-04", N, "3.5", 3.5, "numeric string source -> number"),
    ("t-rp-05", N, "2", 2.0, "integer string source -> float"),
    ("t-rp-06", N, "-4.25", -4.25, "negative decimal string"),
    ("t-rp-07", N, "1.2e3", 1200.0, "scientific notation string"),
    ("t-rp-08", N, 1200.0, 1.2e3, "plain -> scientific notation (same float)"),
    ("t-rp-09", N, "7/5", 1.4, "simple fraction source"),
    ("t-rp-10", NL, [0.5, 1], [0.5, 1.0], "mixed int/float list"),
    ("t-rp-11", N, 0.1, 0.1, "identical binary float (EXACT)"),
    ("t-rp-12", N, "  5  ", 5.0, "padded numeric string"),
    ("t-rp-13", N, 1000000, 1e6, "int vs exponent float"),
    ("t-rp-14", N, "2.5e-2", 0.025, "negative exponent string"),
    ("t-rp-15", NM, [[1, 0]], [[1.0, 0.0]], "int matrix -> float matrix"),
    ("t-rp-16", N, 3, 3.0, "small int -> float"),
    ("t-rp-17", N, "+8", 8.0, "explicit sign string"),
    ("t-rp-18", NL, [-1, 0, 1], [-1.0, 0.0, 1.0], "signed int list"),
]
for cid, role, s, c, note in _repr:
    # t-rp-08/t-rp-11 are value-identical floats (1.2e3 == 1200.0) — the
    # classifier's strict numeric equality makes them EXACT, not a reformat.
    exp = ("EXACT" if cid in ("t-rp-08", "t-rp-11")
           else "REPRESENTATION_EQUIVALENT")
    add(cid, "transform", exp, role=role, source=s, compute=c, note=note)

# --------------------------------------------------------------------------
# UNIT_EQUIVALENT — verified canonical unit conversion
# --------------------------------------------------------------------------
_unit = [
    ("t-un-01", "2 km", 2000.0),
    ("t-un-02", "2000 m", 2000.0),
    ("t-un-03", "3 kg", 3.0),
    ("t-un-04", "500 g", 0.5),
    ("t-un-05", "2 min", 120.0),
    ("t-un-06", "1 hour", 3600.0),
    ("t-un-07", "5 cm", 0.05),
    ("t-un-08", "250 ms", 0.25),
    ("t-un-09", "2 L", 2.0),
    ("t-un-10", "1500 ml", 1.5),
    ("t-un-11", "10 mm", 0.01),
    ("t-un-12", "90 min", 5400.0),
]
for cid, s, c in _unit:
    add(cid, "transform", "UNIT_EQUIVALENT", role=N, source=s, compute=c,
        note="canonical SI conversion from the approved unit table")

# --------------------------------------------------------------------------
# STRUCTURE_EQUIVALENT — structured form differs, semantics preserved
# --------------------------------------------------------------------------
_struct = [
    ("t-st-01", NM, "[ 2 1; 1 3 ]", [[2, 1], [1, 3]], "T12-DEF-2 matrix literal"),
    ("t-st-02", NM, "[ 4 2; 2 1 ]", [[4.0, 2.0], [2.0, 1.0]], "matrix literal float"),
    ("t-st-03", NM, "[[4, 1], [2, 3]]", [[4, 1], [2, 3]], "nested-bracket literal"),
    ("t-st-04", NM, "[ 1 2 3; 0 1 4; 5 6 0 ]", [[1, 2, 3], [0, 1, 4], [5, 6, 0]], "3x3 literal"),
    ("t-st-05", NM, "[ -1 0; 0 -1 ]", [[-1, 0], [0, -1]], "negative entries literal"),
    ("t-st-06", NL, "[1, 2, 3]", [1.0, 2.0, 3.0], "list literal string"),
    ("t-st-07", NM, "[ 0.5 0; 0 0.25 ]", [[0.5, 0], [0, 0.25]], "decimal literal matrix"),
    ("t-st-08", NL, "[ -2, 7 ]", [-2.0, 7.0], "signed list literal"),
    ("t-st-09", NM, "[ 1 0 0; 0 1 0; 0 0 1 ]", [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "identity literal"),
    ("t-st-10", NL, "[0.1 0.5 1.0]", [0.1, 0.5, 1.0], "sweep literal"),
    ("t-st-11", NM, "[[2, 1], [1, 3]]", [[2.0, 1.0], [1.0, 3.0]], "nested list reformat"),
    ("t-st-12", NL, "[5, 10]", [5.0, 10.0], "comma row vector"),
    ("t-st-13", NM, "[ 2 1; 1 3 ]", [[2, 1], [1, 3.0]], "literal vs mixed int/float"),
    ("t-st-14", NM, "[ 6 ]", [[6.0]], "1x1 matrix literal"),
    ("t-st-15", NL, "[1 2]", [1.0, 2.0], "space-separated literal"),
    ("t-st-16", NM, "[ 1.5 2.5 ]", [[1.5, 2.5]], "row matrix literal"),
    ("t-st-17", NL, "[3, 3, 3]", [3, 3, 3], "repeated constant literal"),
    ("t-st-18", NM, "[ 0 -1; 1 0 ]", [[0.0, -1.0], [1.0, 0.0]], "rotation literal"),
]
for cid, role, s, c, note in _struct:
    add(cid, "transform", "STRUCTURE_EQUIVALENT", role=role,
        source=s, compute=c, note=note)

# --------------------------------------------------------------------------
# VALUE_CHANGED — scientific value mutated (T13.12)
# --------------------------------------------------------------------------
_value = [
    ("t-vc-01", N, 2.0, 3.0, "plain value change"),
    ("t-vc-02", N, -1, 1, "sign flip (T11 sigma mutation)"),
    ("t-vc-03", N, 1.5, 0.5, "T11 p mutation"),
    ("t-vc-04", N, 2.0, 2.0001, "beyond-representation drift"),
    ("t-vc-05", N, "2 km", 3000.0, "unit value under disguise"),
    ("t-vc-06", NM, [[4, 2], [2, 1]], [[4, 2], [2, 2]], "matrix element change"),
    ("t-vc-07", NL, [1, 2, 3], [1, 2, 4], "last element change"),
    ("t-vc-08", N, 1e3, 1e4, "exponent change"),
    ("t-vc-09", N, "3.5", 4.5, "string source value change"),
    ("t-vc-10", NL, [0.1, 0.5, 1.0], [0.1, 0.5], "sweep shrink"),
    ("t-vc-11", N, 0.0, 1.0, "zero to one"),
    ("t-vc-12", NM, [[1, 0], [0, 1]], [[1, 0], [0, -1]], "identity to reflection"),
    ("t-vc-13", N, -7, 7, "sign flip large"),
    ("t-vc-14", NL, [10, 20], [10, 21], "small drift in list"),
    ("t-vc-15", N, "7/5", 1.5, "fraction mis-resolved"),
    ("t-vc-16", N, 100, 1000, "magnitude change"),
    ("t-vc-17", NM, [[2, 1], [1, 3]], [[2, 1], [1, 4]], "determinant-relevant change"),
    ("t-vc-18", N, 0.5, 0.4999, "truncation mutation"),
]
for cid, role, s, c, note in _value:
    add(cid, "transform", "VALUE_CHANGED", role=role, source=s, compute=c,
        note=note)

# null/zero/empty discipline (T13.7) — all rejections
_null = [
    ("t-vc-19", N, None, 0.0, "null -> zero", "VALUE_CHANGED"),
    ("t-vc-20", N, 0.0, None, "zero -> null", "VALUE_CHANGED"),
    ("t-vc-21", NL, None, [], "null -> empty list", "TYPE_SEMANTICS_CHANGED"),
    ("t-vc-22", NL, [], [0.0], "empty -> default singleton", "TYPE_SEMANTICS_CHANGED"),
    ("t-vc-23", NL, [], [1, 2], "empty -> populated", "TYPE_SEMANTICS_CHANGED"),
    ("t-vc-24", N, None, None, "null -> null", "EXACT"),
    ("t-vc-25", NL, [], [], "empty -> empty (DEF-1)", "EXACT"),
    ("t-vc-26", N, 0, 0.0, "zero int vs zero float", "REPRESENTATION_EQUIVALENT"),
]
for cid, role, s, c, note, exp in _null:
    add(cid, "transform", exp, role=role, source=s, compute=c, note=note)

# --------------------------------------------------------------------------
# TYPE_SEMANTICS_CHANGED — type change alters meaning (T13.3/T13.8)
# --------------------------------------------------------------------------
_type = [
    ("t-ty-01", N, 2.0, [2.0], "scalar -> singleton vector"),
    ("t-ty-02", NL, [2.0], 2.0, "vector -> scalar"),
    ("t-ty-03", NL, [1, 2, 3], [[1, 2, 3]], "vector -> row matrix"),
    ("t-ty-04", NM, [[1, 2]], [1, 2], "matrix -> vector"),
    ("t-ty-05", NL, [1, 2], [1, 2, 3], "vector length mismatch (T13.8)"),
    ("t-ty-06", NL, [1, 2, 3], [3, 2, 1], "reordered state vector"),
    ("t-ty-07", NM, [[1, 2], [3, 4]], [[1, 3], [2, 4]], "transposed matrix"),
    ("t-ty-08", NL, [1, 2, 2], [1, 2], "duplicate collapsed"),
    ("t-ty-09", N, "2 km", "2000", "unit label dropped without conversion", ),
    ("t-ty-10", NL, [1, 2], [1.0, 2.0, 1.0], "length + reorder"),
    ("t-ty-11", NM, [[1, 2], [3, 4]], [[1, 2, 3], [4, 5, 6]], "matrix shape change"),
    ("t-ty-12", N, 5, "five", "number -> word"),
]
for cid, role, s, c, note in _type:
    add(cid, "transform", "TYPE_SEMANTICS_CHANGED", role=role,
        source=s, compute=c, note=note)

# --------------------------------------------------------------------------
# INVALID_NORMALIZATION — equivalence cannot be proved / schema-type rule
# --------------------------------------------------------------------------
_inv = [
    ("t-in-01", N, "x + 1", 3.0, "expression where number required"),
    ("t-in-02", N, "3 furlongs", 4828.032, "unverified unit"),
    ("t-in-03", N, "about 5", 5.0, "prose number"),
    ("t-in-04", N, "1/0", 0.0, "degenerate fraction"),
    ("t-in-05", NM, "[ a b; c d ]", [[1, 2], [3, 4]], "symbolic matrix literal"),
    ("t-in-06", N, "3.", 3.0, "trailing-dot literal (parse ok)", ),
    ("t-in-07", NL, "[1, x]", [1.0, 2.0], "symbol in list literal"),
    ("t-in-08", "EXPRESSION", "2x +", "2*x", "malformed repair attempt"),
    ("t-in-09", "EXPRESSION", "x**2 + 1", "1 + x**2", "reordering is not identity"),
    ("t-in-10", N, "nan", 0.0, "nan literal"),
    ("t-in-11", N, "1e", 1.0, "broken exponent"),
    ("t-in-12", N, "2 km/h", 2.0, "compound unit unverified"),
]
for cid, role, s, c, note in _inv:
    exp = "REPRESENTATION_EQUIVALENT" if cid == "t-in-06" \
        else "INVALID_NORMALIZATION"
    add(cid, "transform", exp, role=role, source=s, compute=c, note=note)

# structured-side numeric strings where the schema requires numbers
_schematype = [
    ("t-in-13", N, 5.0, "5", "structured string for number"),
    ("t-in-14", NL, [1, 2], ["1", "2"], "structured numeric strings in list"),
    ("t-in-15", NM, [[1, 2]], [["1", "2"]], "structured strings in matrix"),
    ("t-in-16", N, 1.0, "1.0", "structured decimal string"),
]
for cid, role, s, c, note in _schematype:
    add(cid, "transform", "TYPE_SEMANTICS_CHANGED", role=role,
        source=s, compute=c, note=note)

# --------------------------------------------------------------------------
# REQUEST level — information added / removed (T13.12), provenance kept
# --------------------------------------------------------------------------
def _req(op, params, srcs, prov=None):
    return {"operation": op, "compute_required": True, "parameters": params,
            "source_inputs": srcs,
            "parameter_provenance": prov or {k: "USER_GIVEN" for k in params},
            "expected_result_type": "scalar",
            "reason_for_compute": "benchmark request"}


_req_cases = [
    # INFORMATION_ADDED — planner invents a scientific value
    ("t-ia-01", "INFORMATION_ADDED", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0},
          {"equations": "dy/dt = -2*y", "t": 1}),
     "Solve the ODE dy/dt = -2*y from t = 0 to t = 1."),
    ("t-ia-02", "INFORMATION_ADDED", "minimize_scalar",
     _req("minimize_scalar", {"expression": "(x-3)**2",
                              "bound_low": -10.0, "bound_high": 10.0},
          {"expression": "(x-3)**2"}),
     "Minimize f(x) = (x - 3)**2."),
    ("t-ia-03", "INFORMATION_ADDED", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0 + k"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0, "parameters": {"k": 2.0}},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 from t = 0 to t = 1."),
    ("t-ia-04", "INFORMATION_ADDED", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [1.0, 2.0],
                        "t_start": 0.0, "t_end": 1.0},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 from t = 0 to t = 1."),
    ("t-ia-05", "INFORMATION_ADDED", "minimize_scalar",
     _req("minimize_scalar", {"expression": "(x-3)**2 + w",
                              "bound_low": -10.0, "bound_high": 10.0,
                              "parameters": {"w": 5.0}},
          {"expression": "(x-3)**2", "x": "in [-10, 10]"}),
     "Minimize f(x) = (x - 3)**2 over x in [-10, 10]."),
    ("t-ia-06", "FIDELITY_OK", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0, "t_eval": [0.0, 0.5, 1.0]},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1},
          prov={"equations": "USER_GIVEN", "initial_state": "USER_GIVEN",
                "t_start": "USER_GIVEN", "t_end": "USER_GIVEN",
                "t_eval": "DETERMINISTIC_DERIVATION"}),
     "declared derived grid is NOT information added"),
    # INFORMATION_REMOVED — a given value is dropped
    ("t-ir-01", "INFORMATION_REMOVED", "solve_ode",
     _req("solve_ode", {"equations": ["k*-2*y0"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0, "parameters": {"k": 2.0}},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "k": 2, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1, parameter k = 2, from t = 0 to t = 1."),
    ("t-ir-02", "INFORMATION_REMOVED", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "k": 2, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1, parameter k = 2, from t = 0 to t = 1."),
    ("t-ir-03", "INFORMATION_REMOVED", "minimize_scalar",
     _req("minimize_scalar", {"expression": "(x-3)**2",
                              "bound_low": -10.0, "bound_high": 10.0},
          {"expression": "(x-3)**2", "x": "in [-10, 10]", "tol": 1e-6}),
     "Minimize f(x) = (x - 3)**2 over x in [-10, 10] with tolerance 1e-6."),
    ("t-ir-04", "INFORMATION_REMOVED", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1, "t_stop": 2.0}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 from t = 0 to t = 1, and also stop early at t_stop = 2.0."),
    ("t-ir-05", "INFORMATION_REMOVED", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "t_start": 0.0, "t_end": 1.0},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 from t = 0 to t = 1."),
    ("t-ir-06", "INFORMATION_REMOVED", "minimize_scalar",
     _req("minimize_scalar", {"expression": "(x-3)**2",
                              "bound_low": -10.0, "bound_high": 10.0},
          {"expression": "(x-3)**2", "x": "in [-10, 10]",
           "constraint": "x**2 <= 4"}),
     "Minimize f(x) = (x - 3)**2 over x in [-10, 10] subject to the constraint x**2 <= 4."),
]
for cid, exp, op, req, note in _req_cases:
    split = "dev" if "derived grid" in note else "final"
    add(cid, "request", exp, operation=op, request=req,
        question=note, split=split, note=note)

# faithful request-level restatements (approved) — T13.11
_req_ok = [
    ("t-fa-01", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0, "parameters": {"k": 2.0}},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "k": 2, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 and parameter k = 2 from t = 0 to t = 1."),
    ("t-fa-02", "solve_ode",
     _req("solve_ode", {"equations": ["-3*y0"], "initial_state": [2.0],
                        "t_start": 0.0, "t_end": 0.5, "parameters": {"k": 3.0}},
          {"equations": "dy/dt = -3*y", "y(0)": 2, "k": 3, "t": 0.5}),
     "Solve the ODE dy/dt = -3*y with initial condition y(0) = 2 and parameter k = 3 from t = 0 to t = 0.5."),
    ("t-fa-03", "minimize_scalar",
     _req("minimize_scalar", {"expression": "(x - 3)**2",
                              "bound_low": -10.0, "bound_high": 10.0},
          {"expression": "f(x) = (x - 3)**2", "x": "in [-10, 10]"}),
     "Minimize f(x) = (x - 3)**2 over x in [-10, 10]."),
    ("t-fa-04", "minimize",
     _req("minimize", {"expression": "x0**2 + (x1 - 2)**2 + 3",
                       "bounds": [[-5.0, 5.0], [-5.0, 5.0]]},
          {"expression": "x0**2 + (x1 - 2)**2 + 3",
           "bounds": "[[-5, 5], [-5, 5]]"}),
     "Minimize x0**2 + (x1 - 2)**2 + 3 subject to bounds [[-5, 5], [-5, 5]]."),
    ("t-fa-05", "determinant",
     _req("determinant", {"matrix": [[2, 1], [1, 3]]},
          {"matrix": "[ 2 1; 1 3 ]"}),
     "What is the determinant of the 2x2 matrix [ 2 1; 1 3 ]?"),
    ("t-fa-06", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [3.0],
                        "t_start": 0.0, "t_end": 1.5},
          {"equations": "dy/dt = -2*y", "y(0)": 3, "t": 1.5}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 3 from t = 0 to t = 1.5."),
]
for cid, op, req, note in _req_ok:
    add(cid, "request", "FIDELITY_OK", operation=op, request=req,
        question=note, split="final", note=note)

# request-level mutation: silent value change must FAIL
_req_mut = [
    ("t-mu-01", "determinant",
     _req("determinant", {"matrix": [[4, 2], [2, 2]]},
          {"matrix": [[4, 2], [2, 1]]}),
     "What is the determinant of the matrix with entries 4, 2, 2, 1?"),
    ("t-mu-02", "solve_ode",
     _req("solve_ode", {"equations": ["-3*y0"], "initial_state": [1.0],
                        "t_start": 0.0, "t_end": 1.0},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 from t = 0 to t = 1."),
    ("t-mu-03", "solve_ode",
     _req("solve_ode", {"equations": ["-2*y0"], "initial_state": [2.0],
                        "t_start": 0.0, "t_end": 1.0},
          {"equations": "dy/dt = -2*y", "y(0)": 1, "t": 1}),
     "Solve the ODE dy/dt = -2*y with initial condition y(0) = 1 from t = 0 to t = 1."),
    ("t-mu-04", "minimize_scalar",
     _req("minimize_scalar", {"expression": "(x-4)**2",
                              "bound_low": -10.0, "bound_high": 10.0},
          {"expression": "f(x) = (x - 3)**2", "x": "in [-10, 10]"}),
     "Minimize f(x) = (x - 3)**2 over x in [-10, 10]."),
    ("t-mu-05", "determinant",
     _req("determinant", {"matrix": [[3, 1], [1, 2]]},
          {"matrix": "[ 2 1; 1 3 ]"}),
     "What is the determinant of the 2x2 matrix [ 2 1; 1 3 ]?"),
]
for cid, op, req, note in _req_mut:
    add(cid, "request", "FIDELITY_FAIL", operation=op, request=req,
        question=note, split="final", note=note)

# provenance mismatch at request level (T13.9)
add("t-pv-01", "request", "FIDELITY_FAIL", operation="determinant",
    request=_req("determinant", {"matrix": [[2, 1], [1, 3]]},
                 {"matrix": [[2, 1], [1, 3]]},
                 prov={"matrix": "MODEL_INVENTED"}),
    question="What is the determinant of the 2x2 matrix [ 2 1; 1 3 ]?",
    split="final", note="same value labeled MODEL_INVENTED on protected field")

# empty-container discipline at request level (T13.15, mfid-v1-0020)
add("t-em-01", "request", "FIDELITY_OK", operation="solve_ode",
    request=_req("solve_ode", {"equations": ["3*y0"], "initial_state": [],
                               "t_start": 0.0, "t_end": 1.0},
                 {"equations": ["3*y0"], "initial_state": [],
                  "t_start": 0.0, "t_end": 1.0}),
    question="Solve the ODE dy/dt = 3*y from t = 0 to t = 1.",
    split="final", note="no classifier exception; engine INVALID_INPUT by design")

# --------------------------------------------------------------------------
# dev split (may inform iteration; excluded from gate metrics)
# --------------------------------------------------------------------------
_dev = [
    ("d-ex-01", "transform", "EXACT", dict(role=N, source=1.5, compute=1.5)),
    ("d-rp-01", "transform", "REPRESENTATION_EQUIVALENT",
     dict(role=N, source="6", compute=6.0)),
    ("d-st-01", "transform", "STRUCTURE_EQUIVALENT",
     dict(role=NM, source="[ 1 2; 3 4 ]", compute=[[1, 2], [3, 4]])),
    ("d-vc-01", "transform", "VALUE_CHANGED", dict(role=N, source=2, compute=5)),
    ("d-ty-01", "transform", "TYPE_SEMANTICS_CHANGED",
     dict(role=NL, source=[1], compute=[1, 2])),
    ("d-un-01", "transform", "UNIT_EQUIVALENT",
     dict(role=N, source="3 km", compute=3000.0)),
    ("d-in-01", "transform", "INVALID_NORMALIZATION",
     dict(role=N, source="many", compute=7.0)),
    ("d-fa-01", "request", "FIDELITY_OK", dict(
        operation="determinant",
        request=_req("determinant", {"matrix": [[1]]}, {"matrix": [[1.0]]}))),
    ("d-mu-01", "request", "FIDELITY_FAIL", dict(
        operation="determinant",
        request=_req("determinant", {"matrix": [[9]]}, {"matrix": [[1]]}))),
    ("d-em-01", "transform", "EXACT", dict(role=NL, source=[], compute=[])),
]
for cid, level, exp, kw in _dev:
    add(cid, level, exp, split="dev", note="dev", **kw)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # sanity: unique ids, declared expectations from the legal set
    legal = {"EXACT", "REPRESENTATION_EQUIVALENT", "UNIT_EQUIVALENT",
             "STRUCTURE_EQUIVALENT", "VALUE_CHANGED",
             "TYPE_SEMANTICS_CHANGED", "INFORMATION_ADDED",
             "INFORMATION_REMOVED", "INVALID_NORMALIZATION",
             "FIDELITY_OK", "FIDELITY_FAIL"}
    ids = [c["case_id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in cases:
        assert c["expected"] in legal, c["case_id"]
    payload = "".join(json.dumps(c, sort_keys=True) + "\n" for c in cases)
    (OUT / "questions.jsonl").write_text(payload, encoding="utf-8",
                                         newline="\n")
    digest = hashlib.sha256((OUT / "questions.jsonl").read_bytes()) \
        .hexdigest()
    (OUT / "checksum.txt").write_text(digest + "\n", encoding="utf-8")
    n_final = sum(1 for c in cases if c["split"] == "final")
    by_cls: dict[str, int] = {}
    for c in cases:
        if c["split"] == "final":
            by_cls[c["expected"]] = by_cls.get(c["expected"], 0) + 1
    manifest = {
        "suite_name": "mango-scicomp-fidelity-transform-v1",
        "version": "v1", "frozen_at": "2026-09-09", "sha256": digest,
        "total_cases": len(cases),
        "split_counts": {"final": n_final, "dev": len(cases) - n_final},
        "by_expected_class_final": by_cls,
        "split_policy": "dev cases may inform classifier iteration; "
                        "gate metrics (T13.13) are computed on FINAL "
                        "only, frozen by this checksum before tuning.",
        "oracle_policy": "expected classes are hand-declared oracle "
                         "labels written BEFORE classifier tuning; the "
                         "classifier under test never sees them.",
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"frozen {len(cases)} cases ({n_final} final) sha256={digest}")
    print(json.dumps(by_cls, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())