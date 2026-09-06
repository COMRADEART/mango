"""Tool-layer base types: errors, results, timeouts, and the registry.

Contract for every tool in `sciencemath.tools`:

* Inputs are plain strings (model- or router-supplied) — treated as
  UNTRUSTED. Expressions are validated by an AST whitelist
  (safeparse.py) or parsed with sympy after that gate; `eval()` is never
  called on untrusted text.
* Outputs are JSON-safe plain dicts (str/int/float/bool/None/list/dict
  only) — verified by ensure_json_safe() before a tool returns.
* Errors are deterministic: a ToolError with a stable `code`, never an
  arbitrary exception leaking out. A failing tool call is a *result*,
  not a crash of the pipeline.
* Calls may take a timeout (thread-based; Windows has no signal.alarm).
  A timed-out call returns status "error" with code TIMEOUT.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """Deterministic tool failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


@dataclass
class ToolResult:
    """Structured, JSON-safe result of one tool invocation."""

    tool: str
    status: str                      # "ok" | "error"
    result: Any = None               # payload when status == "ok"
    error: dict | None = None        # {"code": ..., "message": ...} on error
    meta: dict = field(default_factory=dict)   # timings, sub-results, etc.

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {"tool": self.tool, "status": self.status,
                "result": self.result, "error": self.error,
                "meta": self.meta}


def ensure_json_safe(value: Any, _depth: int = 0) -> Any:
    """Recursively verify a value is JSON-serializable-safe; raise otherwise.

    Allowed: None, bool, int, float (finite), str, list, tuple, dict with
    string keys. Sympy objects, numpy arrays, sets, bytes, and NaN/inf
    floats are rejected (callers must convert explicitly)."""
    if _depth > 12:
        raise ToolError("NOT_JSON_SAFE", "result nesting too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ToolError("NOT_JSON_SAFE", f"non-finite float in result: {value!r}")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [ensure_json_safe(v, _depth + 1) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ToolError("NOT_JSON_SAFE", f"non-string dict key: {k!r}")
            out[k] = ensure_json_safe(v, _depth + 1)
        return out
    raise ToolError("NOT_JSON_SAFE",
                    f"result contains non-JSON-safe value of type "
                    f"{type(value).__name__}")


def run_with_timeout(fn: Callable[[], Any], timeout_s: float,
                     description: str) -> Any:
    """Run fn() in a worker thread, enforcing a wall-clock timeout.

    Raises ToolError(TIMEOUT) if fn does not finish in time. The worker
    thread cannot be killed (Python limitation) and is abandoned — callers
    should keep timeouts generous enough that this is rare, and every
    timeout is recorded in the tool result meta.
    """
    ex = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix=f"tool-{description}")
    try:
        future = ex.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            # Do NOT join the worker (a `with` block would): cancel pending
            # work and abandon the thread so the wall-clock bound holds.
            future.cancel()
            ex.shutdown(wait=False, cancel_futures=True)
            raise ToolError("TIMEOUT",
                            f"{description} exceeded {timeout_s}s timeout")
    finally:
        if not ex._shutdown:  # normal path: clean shutdown, worker joined
            ex.shutdown(wait=True)


class Tool:
    """Base class for deterministic tools. Subclasses implement run()."""

    name: str = "tool"
    description: str = ""
    input_schema: dict = {}
    output_schema: dict = {}
    default_timeout_s: float = 10.0

    def run(self, arguments: dict) -> ToolResult:
        """Execute the tool. Must never raise: convert any exception into
        an error ToolResult so callers get a deterministic shape."""
        try:
            result = self._checked_run(arguments)
            result.result = ensure_json_safe(result.result)
            return result
        except ToolError as e:
            return ToolResult(tool=self.name, status="error", error=e.to_dict())
        except Exception as e:  # noqa: BLE001 — tools must not crash the pipeline
            return ToolResult(
                tool=self.name, status="error",
                error={"code": "INTERNAL_ERROR",
                       "message": f"{type(e).__name__}: {e}"})

    def _checked_run(self, arguments: dict) -> ToolResult:
        raise NotImplementedError

    # -- argument helpers -------------------------------------------------
    @staticmethod
    def _require_str(arguments: dict, key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ToolError("INVALID_INPUT", f"missing or empty '{key}'")
        return value

    @staticmethod
    def _require_number(arguments: dict, key: str,
                        default: Any = None) -> float:
        value = arguments.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolError("INVALID_INPUT", f"'{key}' must be a number")
        value = float(value)
        if value != value or value in (float("inf"), float("-inf")):
            raise ToolError("INVALID_INPUT", f"'{key}' must be finite")
        return value


class ToolRegistry:
    """Name -> Tool map with a stable manifest for prompts and logs."""

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def manifest(self) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.input_schema,
                 "output_schema": t.output_schema}
                for t in (self._tools[n] for n in self.names())]

    def invoke(self, name: str, arguments: dict) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(tool=name, status="error",
                              error={"code": "UNKNOWN_TOOL",
                                     "message": f"no tool named {name!r}"})
        return tool.run(arguments)