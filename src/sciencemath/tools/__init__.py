"""Mango T4 tool layer: deterministic math tools + verifier + router.

Public surface:
    tools.base            Tool / ToolResult / ToolError / ToolRegistry /
                          ensure_json_safe / run_with_timeout
    tools.safeparse       normalize_input / lenient_expression / validate_ast
    tools.calculator      CalculatorTool            (AST-walk, no eval)
    tools.symbolic_math   SymbolicMathTool          (SymPy behind the gate)
    tools.equation_solver EquationSolverTool
    tools.unit_converter  UnitConverterTool
    tools.numerical_math  NumericalMathTool
    tools.verifier        parse_answer / verify_answer / verify_model_output
    tools.router          route_question / ToolCallLogger / invoke_logged /
                          build_default_registry
"""
from sciencemath.tools.base import (Tool, ToolError, ToolRegistry,
                                    ToolResult, ensure_json_safe,
                                    run_with_timeout)
from sciencemath.tools.calculator import CalculatorTool
from sciencemath.tools.equation_solver import EquationSolverTool
from sciencemath.tools.numerical_math import NumericalMathTool
from sciencemath.tools.router import (ToolCallLogger, build_default_registry,
                                      invoke_logged, route_question)
from sciencemath.tools.symbolic_math import (SymbolicMathTool, safe_parse,
                                             symbolic_equivalence)
from sciencemath.tools.unit_converter import UnitConverterTool, parse_quantity
from sciencemath.tools.verifier import (parse_answer, verify_answer,
                                        verify_model_output)

__all__ = [
    "Tool", "ToolError", "ToolRegistry", "ToolResult",
    "ensure_json_safe", "run_with_timeout",
    "CalculatorTool", "SymbolicMathTool", "EquationSolverTool",
    "UnitConverterTool", "NumericalMathTool",
    "safe_parse", "symbolic_equivalence", "parse_quantity",
    "parse_answer", "verify_answer", "verify_model_output",
    "route_question", "ToolCallLogger", "invoke_logged",
    "build_default_registry",
]