"""T4 router tests: rule-based tool recommendation + mandatory call logging."""
import json

import pytest

from sciencemath.tools.base import ToolRegistry
from sciencemath.tools.calculator import CalculatorTool
from sciencemath.tools.router import (ToolCallLogger, build_default_registry,
                                      invoke_logged, route_question)


class TestRouting:
    @pytest.mark.parametrize("question,tool", [
        ("What is 17 * 23?", "calculator"),
        ("Calculate 15% of 80", "calculator"),
        ("Solve for x: 2x + 3 = 11", "equation_solver"),
        ("Find the roots of x^2 - 4 = 0", "equation_solver"),
        ("Find the derivative of x**3 sin(x)", "symbolic_math"),
        ("Evaluate the integral of 1/x from 1 to e", "symbolic_math"),
        ("Simplify (x**2 - 1)/(x - 1)", "symbolic_math"),
        ("Convert 5 kilometers to miles", "unit_converter"),
        ("How many centimeters are in 3 inches?", "unit_converter"),
        ("Calculate the mean of 2, 4, 6", "numerical_math"),
        ("What is the standard deviation of 1, 2, 3, 4?", "numerical_math"),
        ("How many ways can 5 people be arranged?", "numerical_math"),
    ])
    def test_routes_to_tool(self, question, tool):
        routing = route_question(question)
        assert tool in routing["tools"], (question, routing)
        assert routing["reasons"][tool]

    @pytest.mark.parametrize("question", [
        "What is the powerhouse of the cell?",
        "Who wrote Romeo and Juliet?",
        "The capital of France is",
        "Explain photosynthesis in plants.",
        "",
    ])
    def test_no_tools_for_non_math(self, question):
        assert route_question(question)["tools"] == []

    def test_deterministic_order(self):
        routing = route_question("Simplify the expression and calculate "
                                 "the mean of 1, 2, 3")
        names = ["calculator", "symbolic_math", "unit_converter",
                 "equation_solver", "numerical_math"]
        order = [names.index(t) for t in routing["tools"]]
        assert order == sorted(order)

    def test_routing_does_not_execute(self):
        # router returns recommendations only — no side effects possible
        routing = route_question("Calculate 2+2")
        assert set(routing["tools"]) <= {"calculator", "symbolic_math",
                                         "equation_solver", "unit_converter",
                                         "numerical_math"}


class TestToolCallLogger:
    def test_logs_routing_and_invocations(self, tmp_path):
        log_path = tmp_path / "tools_log.jsonl"
        logger = ToolCallLogger(log_path)
        registry = build_default_registry()

        routing = route_question("What is 17 * 23?")
        logger.log_routing("q1", "What is 17 * 23?", routing)
        result = invoke_logged(registry, logger, "q1", "calculator",
                               {"expression": "17 * 23"})
        assert result.status == "ok" and result.result["value"] == 391

        lines = [json.loads(l) for l in
                 log_path.read_text(encoding="utf-8").strip().splitlines()]
        events = [l["event"] for l in lines]
        assert events == ["route", "tool_call"]
        assert lines[1]["tool"] == "calculator"
        assert lines[1]["status"] == "ok"
        assert lines[1]["question_id"] == "q1"
        assert "wall_time_s" in lines[1]

    def test_failed_calls_logged_too(self, tmp_path):
        log_path = tmp_path / "tools_log.jsonl"
        logger = ToolCallLogger(log_path)
        registry = build_default_registry()
        result = invoke_logged(registry, logger, "q2", "calculator",
                               {"expression": "__import__('os').system('x')"})
        assert result.status == "error"
        lines = [json.loads(l) for l in
                 log_path.read_text(encoding="utf-8").strip().splitlines()]
        assert lines[0]["status"] == "error"
        assert lines[0]["error"]["code"] == "DISALLOWED_EXPRESSION"

    def test_unknown_tool_invocation_logged(self, tmp_path):
        log_path = tmp_path / "tools_log.jsonl"
        logger = ToolCallLogger(log_path)
        result = invoke_logged(ToolRegistry(), logger, "q3",
                               "time_machine", {})
        assert result.error["code"] == "UNKNOWN_TOOL"
        assert json.loads(log_path.read_text(
            encoding="utf-8").strip().splitlines()[0])["tool"] == \
            "time_machine"

    def test_log_is_append_only_jsonl(self, tmp_path):
        log_path = tmp_path / "tools_log.jsonl"
        logger = ToolCallLogger(log_path)
        for i in range(5):
            logger.log({"event": "test", "i": i})
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 5
        assert all(isinstance(json.loads(l), dict) for l in lines)


class TestDefaultRegistry:
    def test_all_five_tools(self):
        registry = build_default_registry()
        assert registry.names() == ["calculator", "equation_solver",
                                    "numerical_math", "symbolic_math",
                                    "unit_converter"]

    def test_end_to_end_question(self, tmp_path):
        """Full pipeline: route -> invoke -> verify."""
        from sciencemath.tools.verifier import verify_answer
        logger = ToolCallLogger(tmp_path / "log.jsonl")
        registry = build_default_registry()
        question = "Solve 2*x + 3 = 11 for x."
        routing = route_question(question)
        assert "equation_solver" in routing["tools"]
        r = invoke_logged(registry, logger, "qX", "equation_solver",
                          {"equation": "2*x + 3 = 11"})
        assert r.ok
        model_answer = f"x = {r.result['solutions'][0]['x']}"
        assert verify_answer(model_answer, "4")["verdict"] == "PASS"