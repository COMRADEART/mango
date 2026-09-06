"""numerical_math — deterministic statistics, combinatorics, matrices.

No symbolic input here: values are JSON numbers (or a JSON list of
numbers / nested lists for matrices). All outputs are JSON-safe floats
with NaN/inf guarded at the boundary.
"""
from __future__ import annotations

import math
from statistics import fmean, median

from sciencemath.tools.base import Tool, ToolError, ToolResult, \
    run_with_timeout


def _clean(x: float) -> float:
    if isinstance(x, complex):
        raise ToolError("NOT_JSON_SAFE", "complex result not supported")
    if x != x or x in (float("inf"), float("-inf")):
        raise ToolError("DOMAIN_ERROR", "non-finite result")
    return x


def _numbers(arguments: dict, key: str = "values") -> list[float]:
    values = arguments.get(key)
    if not isinstance(values, list) or not values:
        raise ToolError("INVALID_INPUT", f"'{key}' must be a non-empty list")
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ToolError("INVALID_INPUT", f"'{key}' must contain numbers")
        fv = float(v)
        if fv != fv or fv in (float("inf"), float("-inf")):
            raise ToolError("INVALID_INPUT", f"'{key}' must be finite")
        out.append(fv)
    if len(out) > 10_000:
        raise ToolError("INVALID_INPUT", "too many values (max 10000)")
    return out


def _matrix(arguments: dict, key: str = "matrix",
            max_side: int = 10) -> list[list[float]]:
    m = arguments.get(key)
    if (not isinstance(m, list) or not m
            or not all(isinstance(row, list) for row in m)):
        raise ToolError("INVALID_INPUT", f"'{key}' must be a list of lists")
    n = len(m)
    if n > max_side or any(len(row) != n for row in m):
        raise ToolError("INVALID_INPUT",
                        f"'{key}' must be square with side <= {max_side}")
    return [[float(v) for v in row] for row in m]


def _matmul(a, b):
    n, k, m = len(a), len(b), len(b[0])
    if len(a[0]) != k:
        raise ToolError("INVALID_INPUT", "dimension mismatch for multiply")
    return [[sum(a[i][t] * b[t][j] for t in range(k)) for j in range(m)]
            for i in range(n)]


def _determinant(m: list[list[float]]) -> float:
    n = len(m)
    if n == 1:
        return m[0][0]
    if n == 2:
        return m[0][0] * m[1][1] - m[0][1] * m[1][0]
    total = 0.0
    for j in range(n):
        minor = [row[:j] + row[j + 1:] for row in m[1:]]
        total += ((-1) ** j) * m[0][j] * _determinant(minor)
    return total


class NumericalMathTool(Tool):
    name = "numerical_math"
    description = (
        "Deterministic numerical operations on JSON numbers. operations: "
        "describe (mean/median/min/max/sum/std/variance), percentile "
        "(values+q), ncr/npr (n, k), factorial, determinant, inverse, "
        "multiply, transpose (matrix). No symbolic algebra, no execution."
    )
    input_schema = {"type": "object",
                    "required": ["operation"],
                    "properties": {
                        "operation": {"type": "string", "enum": [
                            "describe", "percentile", "ncr", "npr",
                            "factorial", "determinant", "inverse",
                            "multiply", "transpose"]},
                        "values": {"type": "array"},
                        "q": {"type": "number"},
                        "n": {"type": "integer"},
                        "k": {"type": "integer"},
                        "matrix": {"type": "array"},
                        "matrix_b": {"type": "array"}}}
    output_schema = {"type": "object"}

    def _checked_run(self, arguments: dict) -> ToolResult:
        operation = self._require_str(arguments, "operation")

        if operation == "describe":
            values = _numbers(arguments)
            mean = fmean(values)
            var_pop = sum((v - mean) ** 2 for v in values) / len(values)
            var_samp = (sum((v - mean) ** 2 for v in values) / (len(values) - 1)
                        if len(values) > 1 else None)
            return ToolResult(tool=self.name, status="ok", result={
                "n": len(values), "sum": _clean(sum(values)),
                "mean": _clean(mean), "median": _clean(median(values)),
                "min": _clean(min(values)), "max": _clean(max(values)),
                "variance_population": _clean(var_pop),
                "variance_sample": None if var_samp is None
                else _clean(var_samp),
                "std_population": _clean(math.sqrt(var_pop)),
                "std_sample": None if var_samp is None
                else _clean(math.sqrt(var_samp))})

        if operation == "percentile":
            values = _numbers(arguments)
            q = self._require_number(arguments, "q")
            if not 0 <= q <= 100:
                raise ToolError("INVALID_INPUT", "q must be in [0, 100]")
            ordered = sorted(values)
            pos = (len(ordered) - 1) * q / 100.0
            lo, hi = math.floor(pos), math.ceil(pos)
            val = ordered[lo] if lo == hi else \
                ordered[lo] + (pos - lo) * (ordered[hi] - ordered[lo])
            return ToolResult(tool=self.name, status="ok",
                              result={"q": q, "value": _clean(val)})

        if operation in ("ncr", "npr"):
            n = arguments.get("n")
            k = arguments.get("k")
            for v in (n, k):
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ToolError("INVALID_INPUT", "'n'/'k' must be integers")
            if not (0 <= k <= n) or n > 10_000:
                raise ToolError("INVALID_INPUT",
                                "need 0 <= k <= n (n <= 10000)")
            import math as _m
            if operation == "ncr":
                val = _m.comb(n, k)
                # guard huge results for JSON float conversion
                if val > 1e308:
                    raise ToolError("OVERFLOW", "result too large")
                return ToolResult(tool=self.name, status="ok",
                                  result={"n": n, "k": k, "value": float(val)})
            if k * math.log10(max(n, 1)) > 300:
                raise ToolError("OVERFLOW", "result too large")
            val = _m.perm(n, k)
            if val > 1e308:
                raise ToolError("OVERFLOW", "result too large")
            return ToolResult(tool=self.name, status="ok",
                              result={"n": n, "k": k, "value": float(val)})

        if operation == "factorial":
            n = arguments.get("n")
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                raise ToolError("INVALID_INPUT", "'n' must be a non-negative int")
            if n > 500:
                raise ToolError("INVALID_INPUT", "'n' too large (max 500)")
            try:
                val = float(math.factorial(n))
            except OverflowError:
                raise ToolError("OVERFLOW",
                                f"factorial({n}) exceeds float range "
                                f"(max 170)")
            return ToolResult(tool=self.name, status="ok",
                              result={"n": n, "value": val})

        if operation == "determinant":
            m = _matrix(arguments)
            if len(m) > 8:
                raise ToolError("INVALID_INPUT",
                                "determinant by cofactor limited to 8x8")
            return ToolResult(tool=self.name, status="ok",
                              result={"determinant": _clean(_determinant(m))})

        if operation == "inverse":
            m = _matrix(arguments)
            # adjugate inverse is O(n!) — same 8x8 ceiling as determinant
            # (a 10x10 inverse took ~17s in review); plus a wall-clock cap.
            if len(m) > 8:
                raise ToolError("INVALID_INPUT",
                                "inverse by cofactor limited to 8x8")
            det = run_with_timeout(lambda: _determinant(m),
                                   self.default_timeout_s, "inverse")
            if abs(det) < 1e-12:
                raise ToolError("SINGULAR_MATRIX",
                                "matrix is singular (determinant ~ 0)")
            inv = run_with_timeout(lambda: _adjugate_inverse(m, det),
                                   self.default_timeout_s, "inverse")
            return ToolResult(tool=self.name, status="ok",
                              result={"inverse": [[_clean(x) for x in row]
                                                  for row in inv]})

        if operation == "multiply":
            a = _matrix(arguments, "matrix")
            b = _matrix(arguments, "matrix_b")
            if len(a[0]) != len(b):
                raise ToolError("INVALID_INPUT", "dimension mismatch")
            return ToolResult(tool=self.name, status="ok",
                              result={"product": [[_clean(x) for x in row]
                                                  for row in _matmul(a, b)]})

        if operation == "transpose":
            m = _matrix(arguments)
            return ToolResult(tool=self.name, status="ok",
                              result={"transpose": [list(col) for col
                                                    in zip(*m)]})

        raise ToolError("INVALID_INPUT", f"unknown operation {operation!r}")


def _adjugate_inverse(m, det):
    n = len(m)
    if n == 1:
        return [[1.0 / m[0][0]]]
    cof = [[((-1) ** (i + j)) * _determinant(
        [row[:j] + row[j + 1:] for r2, row in enumerate(m) if r2 != i])
        for j in range(n)] for i in range(n)]
    # adjugate = transpose of cofactor matrix; inverse = adjugate / det
    return [[cof[j][i] / det for j in range(n)] for i in range(n)]