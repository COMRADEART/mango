"""Inference engine + chat CLI (T6 — not implemented yet).

Planned public surface: load model+adapter, mode dispatch (/math /science /rag
/tools /sources /status), explanation depth (concise|student|detailed) and
RAG/tool orchestration from scripts/run_chat.py.
"""
__all__: list[str] = []

_NOT_IMPLEMENTED = (
    "sciencemath.inference is planned for milestone T6 (integrated assistant). "
    "This import is a placeholder so the package layout exists."
)


def __getattr__(name):
    raise ImportError(_NOT_IMPLEMENTED)