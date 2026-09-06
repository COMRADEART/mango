"""equation_solver — solve equations and systems symbolically.

Input: one equation ("2*x + 3 = 7") or several separated by ';' or '|'
in a "system", plus optional variables (auto-detected when omitted). Both
sides pass through the safeparse gate before sympy.solve. Solutions are
returned as deterministic strings + numeric approximations, JSON-safe.
Complex solutions are reported only when requested (real default).
"""
from __future__ import annotations

import sympy
from sympy import Symbol

from sciencemath.tools.base import Tool, ToolError, ToolResult, \
    run_with_timeout
from sciencemath.tools.symbolic_math import (DEFAULT_TIMEOUT_S,
                                             expression_to_string,
                                             numeric_value, safe_parse)


class EquationSolverTool(Tool):
    name = "equation_solver"
    description = (
        "Solve one equation or a ';'/'|'-separated system for given "
        "variables. Syntax: python-style, e.g. x**2 - 5*x + 6 = 0. "
        "Returns symbolic solutions (as strings) and decimal approximations."
    )
    input_schema = {"type": "object",
                    "required": ["equation"],
                    "properties": {
                        "equation": {"type": "string"},
                        "variables": {"type": "array",
                                      "items": {"type": "string"}},
                        "allow_complex": {"type": "boolean"}}}
    output_schema = {"type": "object",
                     "properties": {
                         "solutions": {"type": "array"},
                         "solution_count": {"type": "integer"},
                         "variables": {"type": "array"},
                         "numeric_solutions": {"type": "array"}}}

    def _checked_run(self, arguments: dict) -> ToolResult:
        raw = self._require_str(arguments, "equation")
        timeout = float(arguments.get("timeout_s", DEFAULT_TIMEOUT_S))
        allow_complex = bool(arguments.get("allow_complex", False))

        parts = [p for p in raw.replace("|", ";").split(";") if p.strip()]
        if not parts:
            raise ToolError("INVALID_INPUT", "empty equation")
        if len(parts) > 6:
            raise ToolError("INVALID_INPUT", "system too large (max 6 eqs)")

        rels = []
        all_symbols: set = set()
        for part in parts:
            rels.append(self._parse_relation(part, timeout))
            all_symbols |= rels[-1].free_symbols

        variables = arguments.get("variables")
        if variables is not None:
            if not isinstance(variables, list) or \
                    not all(isinstance(v, str) for v in variables) or \
                    not variables:
                raise ToolError("INVALID_INPUT",
                                "'variables' must be a non-empty string list")
            syms = [Symbol(v) for v in variables]
            for s in syms:
                if s not in all_symbols:
                    raise ToolError("INVALID_INPUT",
                                    f"variable {s} not present in equations")
        else:
            syms = sorted(all_symbols, key=lambda s: s.name)
            if not syms:
                raise ToolError("INVALID_INPUT",
                                "no variables in equation (nothing to solve)")
            if len(syms) > 4:
                raise ToolError("INVALID_INPUT",
                                f"too many variables ({len(syms)}), "
                                "pass 'variables' explicitly (max 4)")

        try:
            # single equation MUST be passed as a scalar, not a 1-element
            # list: solve([eq], syms) silently returns [] for polynomials
            # with no rational roots (x**5 - x - 1) where solve(eq, syms)
            # returns theRootOf form
            rel_arg = rels[0] if len(rels) == 1 else rels
            sols = run_with_timeout(
                lambda: sympy.solve(rel_arg, syms, dict=True),
                timeout, "solve")
        except ToolError:
            raise
        except NotImplementedError:
            sols = None
        except Exception as e:  # noqa: BLE001
            raise ToolError("SOLVE_ERROR", f"solver failed: {e}")

        if sols is None:
            return ToolResult(tool=self.name, status="ok", result={
                "solutions": [], "solution_count": 0,
                "variables": [s.name for s in syms],
                "numeric_solutions": [],
                "note": "no closed-form solution found (solve returned None)"})

        results, numerics = [], []
        for sol in sols[:20]:                       # bound pathological size
            entry, num_entry = {}, {}
            for sym in syms:
                val = sol.get(sym)
                if val is None:
                    continue
                if not allow_complex:
                    # drop non-real solutions (sympy solve reports complex
                    # roots of real polynomials by default). is_real is
                    # None for RootOf forms: is_real is None used to be
                    # treated as non-real, silently DROPPING real roots of
                    # e.g. x**3 - 3*x - 1 = 0
                    if val.free_symbols == set():
                        if val.is_real is False:
                            continue
                        if val.is_real is None:
                            try:
                                z = complex(val.evalf())
                            except (TypeError, ValueError):
                                pass
                            else:
                                if abs(z.imag) > 1e-9:
                                    continue
                entry[sym.name] = expression_to_string(val)
                num = numeric_value(val)
                if num is not None:
                    num_entry[sym.name] = num
            if entry:
                results.append(entry)
                numerics.append(num_entry)
        return ToolResult(tool=self.name, status="ok", result={
            "solutions": results,
            "solution_count": len(results),
            "variables": [s.name for s in syms],
            "numeric_solutions": numerics})

    @staticmethod
    def _parse_relation(part: str, timeout: float) -> sympy.Expr:
        part = part.strip()
        # check "==" first: "=" is a substring of "==", so the old order
        # never reached the "==" branch (dead code)
        for op in ("==", "="):
            if op in part:
                left_s, right_s = part.split(op, 1)
                break
        else:
            left_s, right_s = part, "0"
        left = safe_parse(left_s, timeout_s=timeout)
        right = safe_parse(right_s, timeout_s=timeout)
        return left - right