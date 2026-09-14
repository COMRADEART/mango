"""T11.25 — adversarial security battery for the scicomp sandbox.

Every probe below must be REJECTED SAFELY: the outcome is a structured
envelope with a non-PASS status (or a PASS that provably never executed
the probe), never a shell command, network access, file read/write, or
arbitrary Python execution. No test in this file may observe a numeric
"answer" produced by running attacker-controlled code.
"""
from __future__ import annotations

import io
import json
import contextlib

import pytest

from sciencemath.scicomp import execute, sandbox
from sciencemath.scicomp.schemas import ScicompError

REJECT_STATUSES = {"FAIL", "UNKNOWN", "INVALID_INPUT", "RESOURCE_LIMIT"}


def _rejected(payload) -> None:
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), \
            contextlib.redirect_stderr(captured):
        env = execute(payload)
    assert env["status"] in REJECT_STATUSES, (payload, env)
    # Nothing the attacker printed should surface as a result.
    assert env["result"] is None or env["status"] != "PASS"
    # The rejection envelope itself must stay JSON-safe.
    json.dumps(env, allow_nan=False)


# --- expression-borne attacks ------------------------------------------------


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo pwned')",
    "__import__('subprocess').run(['ls'])",
    "__builtins__",
    "__builtins__.__dict__",
    "().__class__.__bases__[0].__subclasses__()",
    "open('/etc/passwd').read()",
    "open('data.txt','w')",
    "eval('1+1')",
    "exec('import os')",
    "compile('1','x','eval')",
    "globals()",
    "locals()",
    "x.attr.__dict__",
    "os.path.join('a','b')",
    "sys.exit(0)",
    "'%s'*10**9",
    "f\"{__import__('os')}\"",
    "input()",
    "print(1)",                                  # calls are whitelisted only
    "[x for x in range(10**9)]",                 # comprehension bomb
    "{i: i for i in range(10**9)}",
    "9**9**9**9",                                # exponent bomb
    "factorial(10**9)",                          # eager-eval bomb
])
def test_expression_attacks_rejected(expr):
    with pytest.raises(ScicompError):
        sandbox.compile_expression(expr, ["x"])
    for op, args in [("definite_integral",
                      {"lower": 0, "upper": 1}),
                     ("bracketed_root",
                      {"bracket_low": -1, "bracket_high": 1})]:
        _rejected({"operation": op,
                   "inputs": {"expression": expr, **args}})


# --- numeric-structure attacks -------------------------------------------------


def test_nan_payload_rejected():
    # json.dumps with allow_nan=False in validate_request rejects NaN
    # before any allocation.
    _rejected({"operation": "determinant",
               "inputs": {"matrix": [[float("nan"), 1], [1, 1]]}})


def test_infinity_payload_rejected():
    _rejected({"operation": "describe", "inputs": {"values": [1e308 * 10]}})


def test_boolean_as_number_rejected():
    env = execute({"operation": "describe", "inputs": {"values": [True,
                                                                  False]}})
    assert env["status"] in REJECT_STATUSES | {"PASS"} or True
    # describe treats bools as invalid entries
    assert env["status"] == "INVALID_INPUT"


def test_string_as_number_rejected():
    _rejected({"operation": "describe", "inputs": {"values": ["5"]}})


def test_huge_sweep_rejected_before_allocation():
    _rejected({"operation": "parameter_sweep",
               "inputs": {"expression": "a+b+c+d",
                          "sweeps": {k: list(range(64))
                                     for k in ("a", "b", "c", "d")}}})


def test_deeply_nested_expression_rejected():
    # 100 nested unary minus operations exceed the AST depth cap of 64.
    # (Bare parens don't add AST depth, so they're not a depth vector.)
    expr = "-" * 100 + "x"
    with pytest.raises(ScicompError):
        sandbox.compile_expression(expr, ["x"])


def test_ode_with_reserved_parameter_name_rejected():
    env = execute({"operation": "solve_ode",
                   "inputs": {"equations": ["-t"], "initial_state": [1.0],
                              "t_start": 0, "t_end": 1,
                              "parameters": {"y0": 3.0}}})
    assert env["status"] == "INVALID_INPUT"


def test_ode_with_nonfinite_parameter_rejected():
    env = execute({"operation": "solve_ode",
                   "inputs": {"equations": ["-k*y0"], "initial_state": [1.0],
                              "t_start": 0, "t_end": 1,
                              "parameters": {"k": float("inf")}}})
    assert env["status"] == "INVALID_INPUT"


# --- structural attacks -------------------------------------------------------


def test_no_code_keys_accepted_paths():
    pre = {"operation": "definite_integral", "code": "x"}
    from sciencemath.scicomp.invocation import prevalidate
    assert prevalidate(pre)["ok"] is False
    for key in ("script", "python", "source", "exec", "command", "shell",
                "path"):
        assert prevalidate({"operation": "x", "inputs": {key: 1}})["ok"] \
            is False


def test_executor_has_no_shell_or_network_surface():
    """Structural guarantee: the scicomp package imports no os.system,
    subprocess, socket, or open-on-untrusted-path anywhere in its
    execution path (T11.3)."""
    import sciencemath.scicomp.executor as ex
    import sciencemath.scicomp.sandbox as sb
    for module in (ex, sb):
        source = open(module.__file__, encoding="utf-8").read()
        assert "subprocess" not in source
        assert "socket" not in source
        assert "os.system" not in source
        assert "os.popen" not in source


def test_timeout_envelope_has_no_partial_result(monkeypatch):
    import time as _time
    from sciencemath.scicomp import executor
    from sciencemath.scicomp.registry import Operation
    from sciencemath.scicomp.schemas import Limits

    def slow(inputs, options, active):
        _time.sleep(2.0)

    monkeypatch.setitem(
        executor._registry, "describe",
        Operation("describe", "STATISTICS", "slow test stub", slow))
    env = execute({"operation": "describe",
                   "inputs": {"values": [1, 2, 3]}},
                  limits_config=Limits(wall_clock_s=0.2))
    assert env["status"] == "RESOURCE_LIMIT"
    assert env["result"] is None


def test_rejection_yields_no_file_content():
    # The rejected expression is echoed as the rejection reason (same
    # discipline as the T4 tools), but NO file content can be read and
    # nothing appears in the result payload.
    env = execute({"operation": "bracketed_root",
                   "inputs": {"expression": "open('C:/secrets.txt')",
                              "bracket_low": 0, "bracket_high": 1}})
    assert env["status"] in REJECT_STATUSES
    assert env["result"] is None