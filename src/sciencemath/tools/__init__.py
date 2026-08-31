"""Math tool layer (T4 — not implemented yet).

Planned public surface: calculator.py (safe Python calculator), sympy_tool.py
(solve/derivative/integrate/simplify/unit conversion) behind a safe sandboxed
interface — no arbitrary shell execution from the chat UI.
"""
__all__: list[str] = []

_NOT_IMPLEMENTED = (
    "sciencemath.tools is planned for milestone T4 (mathematical verification). "
    "This import is a placeholder so the package layout exists."
)


def __getattr__(name):
    raise ImportError(_NOT_IMPLEMENTED)