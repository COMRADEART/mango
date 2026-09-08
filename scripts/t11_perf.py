"""T11.39 — scicomp engine CPU performance benchmark.

One representative request per approved operation, executed on CPU,
median of 5 runs. Records per-operation latency and envelope status.
Writes evaluations/t11/perf_engine.json.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp import execute  # noqa: E402

PROBES = {
    "solve_linear_system": {"operation": "solve_linear_system",
                            "inputs": {"matrix": [[4.0, 1.0], [2.0, 3.0]],
                                       "b": [9.0, 13.0]}},
    "matrix_multiply": {"operation": "matrix_multiply",
                        "inputs": {"a": [[1.0, 2.0], [3.0, 4.0]],
                                   "b": [[5.0, 6.0], [7.0, 8.0]]}},
    "determinant": {"operation": "determinant",
                    "inputs": {"matrix": [[2.0, 1.0], [1.0, 3.0]]}},
    "matrix_inverse": {"operation": "matrix_inverse",
                       "inputs": {"matrix": [[4.0, 1.0], [2.0, 3.0]]}},
    "eigen_decompose": {"operation": "eigen_decompose",
                        "inputs": {"matrix": [[5.0, 0.0], [0.0, 2.0]]}},
    "vector_or_matrix_norm": {"operation": "vector_or_matrix_norm",
                              "inputs": {"vector": [3.0, 4.0, 12.0],
                                         "norm": "l2"}},
    "matrix_rank": {"operation": "matrix_rank",
                    "inputs": {"matrix": [[1.0, 2.0], [2.0, 4.0]]}},
    "least_squares": {"operation": "least_squares",
                      "inputs": {"matrix": [[1.0, 0.0], [0.0, 1.0]],
                                 "b": [1.0, 2.0]}},
    "definite_integral": {"operation": "definite_integral",
                          "inputs": {"expression": "x**2", "lower": 0.0,
                                     "upper": 1.0}},
    "cumulative_integral": {"operation": "cumulative_integral",
                            "inputs": {"expression": "x", "x": [0.0, 1.0,
                                                               2.0, 3.0],
                                       "y": [0.0, 1.0, 2.0, 3.0]}},
    "numerical_derivative": {"operation": "numerical_derivative",
                             "inputs": {"expression": "x**3", "at": 2.0}},
    "bracketed_root": {"operation": "bracketed_root",
                       "inputs": {"expression": "x**2 - 2", "bracket_low": 0.0,
                                  "bracket_high": 5.0}},
    "scalar_root": {"operation": "scalar_root",
                    "inputs": {"expression": "x**2 - 3",
                               "initial_guess": 2.0}},
    "system_root": {"operation": "system_root",
                    "inputs": {"expressions": ["x0 - 1", "x1 - 2"],
                               "initial_guess": [0.5, 0.5]}},
    "solve_ode": {"operation": "solve_ode",
                  "inputs": {"equations": ["-k*y0"], "initial_state": [1.0],
                             "t_start": 0.0, "t_end": 1.0,
                             "parameters": {"k": 2.0}}},
    "minimize_scalar": {"operation": "minimize_scalar",
                        "inputs": {"expression": "(x-3)**2", "bound_low": -10.0,
                                   "bound_high": 10.0}},
    "minimize": {"operation": "minimize",
                 "inputs": {"expression": "(x0-1)**2 + (x1+3)**2",
                            "bounds": [[-10.0, 10.0], [-10.0, 10.0]]}},
    "describe": {"operation": "describe",
                 "inputs": {"values": [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0,
                                       9.0]}},
    "confidence_interval_mean": {"operation": "confidence_interval_mean",
                                 "inputs": {"values": [5.1, 4.9, 5.3, 5.0],
                                            "confidence": 0.95}},
    "correlation": {"operation": "correlation",
                    "inputs": {"x": [1.0, 2.0, 3.0, 4.0],
                               "y": [2.0, 4.0, 6.0, 8.0]}},
    "linear_regression": {"operation": "linear_regression",
                          "inputs": {"x": [1.0, 2.0, 3.0, 4.0],
                                     "y": [2.0, 4.0, 6.0, 8.0]}},
    "hypothesis_test": {"operation": "hypothesis_test",
                        "inputs": {"test": "ttest_1samp",
                                   "values": [5.1, 4.9, 5.3, 5.0],
                                   "null_value": 5.0}},
    "distribution_value": {"operation": "distribution_value",
                           "inputs": {"distribution": "normal",
                                      "parameters": {"mu": 0.0, "sigma": 1.0},
                                      "at": 1.96, "quantity": "cdf"}},
    "linear_interpolate": {"operation": "linear_interpolate",
                           "inputs": {"x": [0.0, 1.0, 2.0],
                                      "y": [0.0, 10.0, 20.0], "at": 1.5}},
    "polynomial_interpolate": {"operation": "polynomial_interpolate",
                               "inputs": {"x": [0.0, 1.0, 2.0],
                                          "y": [1.0, 3.0, 2.0], "at": 0.5}},
    "curve_fit": {"operation": "curve_fit",
                  "inputs": {"model": "p0 + p1*x",
                             "x": [0.0, 1.0, 2.0, 3.0, 4.0],
                             "y": [3.0, 5.0, 7.0, 9.0, 11.0],
                             "parameters": ["p0", "p1"]}},
    "parameter_sweep": {"operation": "parameter_sweep",
                        "inputs": {"expression": "a + b",
                                   "sweeps": {"a": [1.0, 2.0, 3.0],
                                              "b": [10.0, 20.0]}}},
}


def main() -> int:
    results = {}
    for name, payload in PROBES.items():
        statuses = set()
        latencies = []
        for _ in range(5):
            start = time.perf_counter()
            env = execute(payload)
            latencies.append((time.perf_counter() - start) * 1000.0)
            statuses.add(env["status"])
        results[name] = {
            "status": sorted(statuses)[0] if len(statuses) == 1
            else sorted(statuses),
            "median_ms": round(statistics.median(latencies), 3),
            "max_ms": round(max(latencies), 3),
        }
        print(f"{name:26s} {results[name]['status']:18s} "
              f"median {results[name]['median_ms']:8.3f} ms")

    # determinism re-check: same payload twice must give identical
    # RESULTS (runtime latency is wall-clock and excluded by design)
    det_payload = PROBES["solve_ode"]
    e1 = execute(det_payload)
    e2 = execute(det_payload)
    e1.pop("runtime", None)
    e2.pop("runtime", None)
    det = e1 == e2
    out = {
        "benchmark": "scicomp engine CPU performance (T11.39)",
        "device": "cpu",
        "runs_per_probe": 5,
        "determinism_spot_check": det,
        "operations": results,
    }
    (ROOT / "evaluations/t11/perf_engine.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("determinism:", det)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())