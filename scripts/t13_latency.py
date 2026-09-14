"""T13.26 — fidelity classifier latency measurement.

The fidelity layer sits on the planner→engine critical path of every
compute request; its cost must be negligible next to model generation
(seconds).  Measures classify_transformation and the full
check_fidelity request path (incl. schema validation and resolver) over
representative frozen-benchmark workloads, deterministic, no model.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (  # noqa: E402
    check_fidelity, classify_transformation)
from sciencemath.scicomp import semantic as sem  # noqa: E402

N = sem.ROLE_NUMBER
NL = sem.ROLE_NUMBER_LIST
NM = sem.ROLE_NUMBER_MATRIX

TRANSFORM_CASES = [
    (2, 2.0, N), ("3.5", 3.5, N), ("2 km", 2000.0, N),
    ("[ 2 1; 1 3 ]", [[2, 1], [1, 3]], NM),
    ([1.0, 2.0, 3.0], [1.0, 2.0, 3.5], NL),
    ("dy/dt = -2*y", ["-2*y0"], None),
    ("many", 7.0, N), (0.1, 0.1, N),
]

REQUEST = {
    "operation": "solve_ode",
    "compute_required": True,
    "parameters": {"equations": ["k*-2*y0"], "initial_state": [1.0],
                   "t_start": 0.0, "t_end": 1.0,
                   "parameters": {"k": 2.0}},
    "source_inputs": {"equations": "dy/dt = -2*y", "y(0)": 1, "k": 2,
                      "t": 1},
    "parameter_provenance": {k: "USER_GIVEN" for k in
                             ("equations", "initial_state", "t_start",
                              "t_end", "parameters")},
    "expected_result_type": "series",
    "reason_for_compute": "T13.26 latency measurement",
}
QUESTION = ("Solve the ODE dy/dt = -2*y with initial condition y(0) = 1, "
            "parameter k = 2, from t = 0 to t = 1.")


def bench(fn, cases, n=200):
    times = []
    for _ in range(n):
        for c in cases:
            t0 = time.perf_counter()
            fn(*c)
            times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return {
        "n": len(times),
        "median_ms": round(statistics.median(times), 4),
        "p95_ms": round(times[int(0.95 * len(times))], 4),
        "max_ms": round(times[-1], 4),
        "mean_ms": round(statistics.fmean(times), 4),
    }


def main() -> int:
    res = {
        "milestone": "T13.26 classifier latency",
        "classify_transform": bench(classify_transformation,
                                    TRANSFORM_CASES),
        "check_fidelity_request": bench(check_fidelity,
                                        [(REQUEST, QUESTION)], n=200),
        "note": "single core, warm process; the layer runs once per "
                "planner request, cost must be negligible vs "
                "multi-second model generation",
    }
    out = ROOT / "evaluations/t13/classifier_latency.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())