"""Wikipedia RAG (T5 — not implemented yet).

Planned public surface (implemented in T5, do not depend on it before then):
  ingest_wikipedia()  -> rag/corpus/*.jsonl (chunked, metadata-preserving)
  build_index()       -> abstract VectorStore (FAISS implementation first)
  retrieve(query)     -> {chunks, scores, sources, debug}
"""
__all__: list[str] = []

_NOT_IMPLEMENTED = (
    "sciencemath.rag is planned for milestone T5 (Wikipedia RAG). "
    "This import is a placeholder so the package layout exists; no "
    "functionality has been implemented yet."
)


def __getattr__(name):
    raise ImportError(_NOT_IMPLEMENTED)