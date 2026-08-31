"""T5 Wikipedia ingestion — STUB (not implemented yet).

Will collect curated science/math Wikipedia pages (per configs/rag.yaml,
never the full dump), chunk to ~650 tokens preserving section headings, and
write rag/corpus/*.jsonl with title/pageid/url/section/revision/license/chunk_id
metadata per chunk.
"""
import sys

STUB_MESSAGE = """
STATUS: BLOCKED - ingest_wikipedia is not implemented yet (milestone T5).
Design is pinned in configs/rag.yaml (categories, chunking, metadata schema).
"""


def main() -> int:
    sys.stderr.write(STUB_MESSAGE)
    return 90


if __name__ == "__main__":
    raise SystemExit(main())