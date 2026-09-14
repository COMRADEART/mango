"""T21 — General Knowledge RAG runtime.

KNOWLEDGE_RAG: local-first, citation-grounded retrieval and answer
generation over a frozen local knowledge corpus. Deterministic: no
network, no inference, fixed seed. This package never replaces SCIENCE_RAG
(src/sciencemath/rag/), which stays frozen; retrieval discipline utilities
are imported read-only.
"""
from __future__ import annotations

from sciencemath.knowledge.schema import KnowledgeChunk, KnowledgeSourceRecord
from sciencemath.knowledge.pipeline import KnowledgeAnswer, answer_knowledge

__all__ = [
    "KnowledgeChunk",
    "KnowledgeSourceRecord",
    "KnowledgeAnswer",
    "answer_knowledge",
]