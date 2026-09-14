"""Structure-aware chunking. Avoid splitting tables/headings/JSON objects."""
from __future__ import annotations

from sciencemath.document.limits import DocumentLimits
from sciencemath.document.models import NormalizedDocument, TextBlock, UNKNOWN


def chunk_document(doc: NormalizedDocument,
                   limits: DocumentLimits | None = None) -> list[TextBlock]:
    limits = limits or DocumentLimits()
    chunks: list[TextBlock] = []
    for i, b in enumerate(doc.blocks[: limits.max_blocks]):
        if b.block_type in ("table", "heading", "json_value"):
            chunks.append(b)
            continue
        text = b.text or ""
        if len(text) <= 1200:
            chunks.append(b)
            continue
        # split on paragraph only, keep parent
        parts = text.split("\n")
        buf = []
        n = 0
        for line in parts:
            buf.append(line)
            if sum(len(x) for x in buf) >= 800:
                n += 1
                child = TextBlock(
                    document_id=doc.document_id,
                    block_id=f"{b.block_id}-c{n}",
                    block_type=b.block_type,
                    text="\n".join(buf),
                    page=b.page, section=b.section,
                    heading_path=b.heading_path,
                    parent_block_id=b.block_id,
                )
                chunks.append(child)
                buf = []
        if buf:
            n += 1
            chunks.append(TextBlock(
                document_id=doc.document_id,
                block_id=f"{b.block_id}-c{n}",
                block_type=b.block_type,
                text="\n".join(buf),
                page=b.page, section=b.section,
                heading_path=b.heading_path,
                parent_block_id=b.block_id,
            ))
        if len(chunks) >= limits.max_blocks:
            break
    return chunks
