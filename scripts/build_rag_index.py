"""T5 RAG index building — STUB (not implemented yet).

Will embed rag/corpus/*.jsonl with sentence-transformers/all-MiniLM-L6-v2 and
write a FAISS index to rag/index/ behind the abstracted vector-store
interface (src/sciencemath/rag/, added in T5).
"""
import sys

STUB_MESSAGE = """
STATUS: BLOCKED - build_rag_index is not implemented yet (milestone T5).
"""


def main() -> int:
    sys.stderr.write(STUB_MESSAGE)
    return 90


if __name__ == "__main__":
    raise SystemExit(main())