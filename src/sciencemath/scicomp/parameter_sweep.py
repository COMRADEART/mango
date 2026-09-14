"""scicomp parameter_sweep — bounded Cartesian parameter sweeps (T11.2,
T11.27).

A sweep evaluates a sandboxed expression over finite grids of parameter
values. Safety contract (T11.27):

* the combination count is computed BEFORE any allocation and compared
  against the hard cap — explosive products are rejected up front, with
  the estimated count in the error message;
* dimensions (sweep axes), values per dimension, and output rows are all
  capped;
* an oversized sweep is never partially executed silently — it is a
  RESOURCE_LIMIT result with the count that caused the rejection.
"""
from __future__ import annotations

import itertools

import numpy as np

from sciencemath.scicomp import sandbox
from sciencemath.scicomp.schemas import (Limits, invalid_input,
                                         resource_limit)


def sweep(inputs: dict, options: dict, limits: Limits) -> dict:
    """Cartesian sweep of an expression over named parameter grids.

    inputs:
      expression: string in the parameter names (and optional free
        variable x)
      sweeps: {"param_name": [v1, v2, ...], ...}
      x: optional shared grid for a free variable x
    """
    expression = inputs.get("expression")
    if not isinstance(expression, str):
        raise invalid_input("'expression' must be a string")
    grids_raw = inputs.get("sweeps")
    if not isinstance(grids_raw, dict) or not grids_raw:
        raise invalid_input("'sweeps' must be a non-empty object of "
                            "parameter -> value-list grids")
    if len(grids_raw) > limits.max_sweep_dims:
        raise resource_limit(
            f"sweep has {len(grids_raw)} dimensions "
            f"(max {limits.max_sweep_dims})")
    grids: dict[str, list[float]] = {}
    for name, values in grids_raw.items():
        if not isinstance(name, str) or not name.isidentifier() or \
                name == "x":
            raise invalid_input(f"invalid sweep parameter name {name!r}")
        if not isinstance(values, list) or not values:
            raise invalid_input(
                f"sweep '{name}' must be a non-empty list of values")
        if len(values) > limits.max_sweep_values_per_dim:
            raise resource_limit(
                f"sweep '{name}' has {len(values)} values (max "
                f"{limits.max_sweep_values_per_dim})")
        checked = []
        for i, v in enumerate(values):
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or v != v or v in (float("inf"), float("-inf")):
                raise invalid_input(
                    f"sweep '{name}'[{i}] must be a finite number")
            checked.append(float(v))
        grids[name] = checked

    # Shared x grid (optional): a free variable evaluated on the same
    # row axis.
    x_grid = inputs.get("x")
    include_x = x_grid is not None
    if include_x:
        if not isinstance(x_grid, list) or not x_grid:
            raise invalid_input("'x' must be a non-empty list of values")
        if len(x_grid) > limits.max_sweep_values_per_dim:
            raise resource_limit(
                f"'x' grid has {len(x_grid)} values (max "
                f"{limits.max_sweep_values_per_dim})")
        x_checked = []
        for i, v in enumerate(x_grid):
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or v != v or v in (float("inf"), float("-inf")):
                raise invalid_input(f"'x'[{i}] must be a finite number")
            x_checked.append(float(v))
        x_grid = x_checked

    # Cap the product BEFORE any allocation (T11.27).
    combos = 1
    for name, values in grids.items():
        combos *= len(values)
    if include_x:
        combos *= len(x_grid)
    if combos > limits.max_sweep_combinations:
        raise resource_limit(
            f"sweep would produce {combos} combinations (max "
            f"{limits.max_sweep_combinations}); shrink grids or split the "
            "sweep")
    rows_expected = combos

    names = list(grids.keys())
    var_names = (["x"] if include_x else []) + names
    expr = sandbox.compile_expression(expression, var_names)

    rows = []
    names_iter = [grids[n] for n in names]
    for values in itertools.product(*names_iter):
        kwargs = dict(zip(names, values))
        if include_x:
            for x_val in x_grid:
                value = expr(x=x_val, **kwargs)
                rows.append({"x": x_val, **kwargs,
                             "value": float(value)})
        else:
            value = expr(**kwargs)
            rows.append({**kwargs, "value": float(value)})
        if len(rows) > limits.max_output_rows:
            raise resource_limit(
                f"sweep output exceeded {limits.max_output_rows} rows")
    if len(rows) > limits.max_output_rows:
        raise resource_limit("sweep output exceeds row cap")

    # Sensitivity table: value range per parameter level (first axis only
    # when multi-dimensional — a compact view, not a full analysis).
    sensitivity = _sensitivity_table(rows, names)

    return {
        "result": {"rows": rows, "row_count": len(rows),
                   "estimated_combinations": rows_expected},
        "diagnostics": {"dimensions": {n: len(grids[n]) for n in names},
                        "x_grid": len(x_grid) if include_x else 0,
                        **sensitivity},
        "provenance": {"engine": "scicomp", "method": "cartesian-sweep"},
    }


def _sensitivity_table(rows: list[dict], names: list[str]) -> dict:
    """Range of output per parameter (min/max value across levels)."""
    table: dict[str, dict] = {}
    for name in names:
        by_level: dict[float, list[float]] = {}
        for row in rows:
            level = row[name]
            by_level.setdefault(level, []).append(row["value"])
        if len(by_level) < 2:
            table[name] = {"value_range": 0.0}
            continue
        level_means = {level: float(np.mean(vs))
                       for level, vs in by_level.items()}
        spread = max(level_means.values()) - min(level_means.values())
        table[name] = {"value_range": spread,
                       "min_level_mean": min(level_means.values()),
                       "max_level_mean": max(level_means.values())}
    return {"sensitivity": table}