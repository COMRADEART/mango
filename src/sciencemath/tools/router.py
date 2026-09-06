"""router — decide which deterministic tools a question should use.

The router is rule-based (regex/keyword patterns over the question text)
and NEVER executes anything: it only recommends tools. Don't invoke tools
for every question — science prose without math gets no tools. Every
routing decision and every tool invocation is logged to a JSONL file
through ToolCallLogger.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sciencemath.tools.base import ToolRegistry, ToolResult

# (tool, compiled pattern, reason label) — first match per tool wins
_RULES: list[tuple[str, re.Pattern, str]] = [
    ("calculator", re.compile(
        r"\b(calculate|compute|evaluate|work out|how\s+much\s+is|"
        r"what\s+is\s+(?:the\s+)?value\s+of)\b", re.IGNORECASE),
     "explicit computation request"),
    ("calculator", re.compile(
        r"[-+0-9(]\s*[-+0-9(][^a-zA-Z]*[+\-*/^×÷][^a-zA-Z]*[-+0-9)]"),
     "arithmetic expression present"),
    ("calculator", re.compile(r"\d+\s*%\s*(?:of|off)\b|\bof\s+\d+\s*%",
                              re.IGNORECASE),
     "percentage computation"),
    ("equation_solver", re.compile(
        r"\b(solve|solution\s+set|roots?\s+of|find\s+[a-z]\b[^.]*\bequation|"
        r"solve\s+for\s+[a-z]\b|zeroes?|zeros?)\b", re.IGNORECASE),
     "equation solving request"),
    ("symbolic_math", re.compile(
        r"\b(derivative|differentiate|d/d[a-z]|integral|integrate|"
        r"antiderivative|simplify|factor(?:ise|ize)?\b|expand\b|"
        r"limit\s+as)\b", re.IGNORECASE),
     "symbolic operation requested"),
    ("unit_converter", re.compile(
        r"\b(convert|conversion|how\s+many\s+\w+\s+are\s+in|"
        r"how\s+many\s+\w+\s+in|express\s+.*\s+in\b|"
        r"in\s+(?:kilometers|metres|meters|miles|feet|inches|"
        r"kilograms|grams|pounds|celsius|fahrenheit|kelvin|"
        r"liters|litres|gallons|joules|calories|newtons|seconds|hours|"
        r"minutes)\b)", re.IGNORECASE),
     "unit conversion request"),
    ("unit_converter", re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:km|km/h|mph|m/s|meters?|metres?|"
        r"kilometers?|centimeters?|millimeters?|grams?|kilograms?|"
        r"pounds?|ounces?|degrees?\s+celsius|degrees?\s+fahrenheit|"
        r"celsius|fahrenheit|kelvin|liters?|litres?|milliliters?|"
        r"joules?|calories?|newtons?|pascals?|atm|moles?|"
        r"seconds?|minutes?|hours?|days?|years?|eV|joules)\b"
        r"[^.]{0,40}\b(?:in|to|into)\b", re.IGNORECASE),
     "quantity with unit converted to another unit"),
    ("numerical_math", re.compile(
        r"\b(mean|average|median|mode|standard\s+deviation|variance|"
        r"percentile|quartile)\b", re.IGNORECASE),
     "statistics requested"),
    ("numerical_math", re.compile(
        r"\b(how\s+many\s+ways|combinations?|permutations?|"
        r"arrangements?|nCr|nPr|factorial|binomial\s+coefficient)\b",
        re.IGNORECASE),
     "combinatorics requested"),
    ("numerical_math", re.compile(
        r"\b(matrix|determinant|inverse\s+of\s+(?:the\s+)?matrix)\b",
        re.IGNORECASE),
     "matrix operation requested"),
]

TOOL_NAMES = ("calculator", "symbolic_math", "equation_solver",
              "unit_converter", "numerical_math")


def route_question(question: str) -> dict:
    """Rule-based tool recommendation. Returns:
    {"tools": [names...], "reasons": {tool: reason}, "primary": name|None}
    No tool is executed here."""
    if not isinstance(question, str) or not question.strip():
        return {"tools": [], "reasons": {}, "primary": None}
    tools: list[str] = []
    reasons: dict[str, str] = {}
    for name, pattern, reason in _RULES:
        if name in reasons:
            continue
        if pattern.search(question):
            tools.append(name)
            reasons[name] = reason
    # deterministic order: TOOL_NAMES order
    tools = [t for t in TOOL_NAMES if t in tools]
    return {"tools": tools, "reasons": reasons,
            "primary": tools[0] if tools else None}


class ToolCallLogger:
    """Append-only JSONL log of router decisions and tool invocations.

    Every tool call MUST be logged (T4 requirement). The log is the audit
    trail: question id, tool, arguments, status, error, wall time."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records = 0
        self._lock = threading.Lock()

    def log(self, record: dict) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 **record}
        # serialize the open-write-close cycle: concurrent invocations
        # (threaded generation) interleaved lines and lost records; also
        # tolerate non-JSON-serializable arguments instead of crashing.
        try:
            text = json.dumps(entry, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = json.dumps(
                {k: str(v) for k, v in entry.items()}, ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
            self._records += 1

    def log_routing(self, question_id: str, question: str,
                    routing: dict) -> None:
        self.log({"event": "route", "question_id": question_id,
                  "question_preview": question[:160],
                  "tools": routing["tools"], "reasons": routing["reasons"]})

    def log_invocation(self, question_id: str, tool_name: str,
                       arguments: dict, result: ToolResult,
                       wall_time_s: float) -> None:
        self.log({"event": "tool_call", "question_id": question_id,
                  "tool": tool_name, "arguments": arguments,
                  "status": result.status,
                  "error": result.error,
                  "result_preview": _preview(result.result),
                  "wall_time_s": round(wall_time_s, 4)})


def _preview(result, limit: int = 400) -> object:
    """Truncated result for the log (full results live in predictions)."""
    try:
        text = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)[:limit]
    return text if len(text) <= limit else text[:limit] + "…(truncated)"


def invoke_logged(registry: ToolRegistry, logger: ToolCallLogger,
                  question_id: str, tool_name: str,
                  arguments: dict) -> ToolResult:
    """Invoke a tool with mandatory logging. Returns the ToolResult."""
    start = time.perf_counter()
    result = registry.invoke(tool_name, arguments)
    wall = time.perf_counter() - start
    logger.log_invocation(question_id, tool_name, arguments, result, wall)
    return result


def build_default_registry() -> ToolRegistry:
    """Registry with all five T4 tools."""
    from sciencemath.tools.calculator import CalculatorTool
    from sciencemath.tools.equation_solver import EquationSolverTool
    from sciencemath.tools.numerical_math import NumericalMathTool
    from sciencemath.tools.symbolic_math import SymbolicMathTool
    from sciencemath.tools.unit_converter import UnitConverterTool

    return ToolRegistry([CalculatorTool(), SymbolicMathTool(),
                         EquationSolverTool(), UnitConverterTool(),
                         NumericalMathTool()])