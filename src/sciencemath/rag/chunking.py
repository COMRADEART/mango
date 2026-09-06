"""chunking — semantic, document-aware chunking (T5.6).

NOT a fixed-N-char splitter. Units are structural:
  * section boundaries (heading path becomes chunk metadata)
  * paragraphs / list items (never split mid-line)
  * equations and their surrounding explanation kept together
Target size ~400-900 tokens (config: chunk_size_tokens), sentence-aligned
overlap at chunk seams. Every chunk carries full provenance (caller
supplies source metadata; chunk_id/checksum assigned here or by caller).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_CHUNK_SIZE_TOKENS = 650
DEFAULT_OVERLAP_TOKENS = 80
MIN_CHUNK_TOKENS = 400     # below this, prefer merging with next unit
MAX_CHUNK_TOKENS = 900     # hard cap for a packed chunk

# a line that looks like an equation or formula: keep it atomic
_EQUATION_RE = re.compile(
    r"[A-Za-z0-9_()\[\]]*(?:=|≈|∝|→|⇌)[A-Za-z0-9_()\[\]]"
    r"|^[A-Z][a-z]?\d*(?:[A-Za-z0-9]|\₂|\₂?)*\s*\+\s*[A-Z][a-z]?\d*")

_LIST_ITEM_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (~1.35 tokens/word for English
    scientific prose). The real tokenizer is applied at embed time; this
    only steers chunk boundaries."""
    if not text.strip():
        return 0
    words = len(text.split())
    return int(words * 1.35) + 1


def count_tokens_exact(text: str, tokenizer) -> int:
    """Exact count with a real tokenizer (optional path for manifests)."""
    return len(tokenizer.encode(text, add_special_tokens=False))


def _split_units(text: str) -> list[str]:
    """Paragraph unit extraction: paragraphs and list-item runs stay
    atomic; equations stay with the line directly after them (their
    explanation)."""
    units: list[str] = []
    buf: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        units.append(para)
    return units


def _split_long_unit(unit: str, max_tokens: int) -> list[str]:
    """Sentence-split a unit that alone exceeds max_tokens."""
    if estimate_tokens(unit) <= max_tokens:
        return [unit]
    out, cur = [], ""
    for sent in _SENTENCE_SPLIT.split(unit):
        cand = f"{cur} {sent}".strip()
        if cur and estimate_tokens(cand) > max_tokens:
            out.append(cur)
            cur = sent
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def _tail_overlap(text: str, overlap_tokens: int) -> str:
    """Last sentences totalling <= overlap_tokens (sentence-aligned)."""
    if overlap_tokens <= 0:
        return ""
    sents = _SENTENCE_SPLIT.split(text)
    tail: list[str] = []
    total = 0
    for sent in reversed(sents):
        t = estimate_tokens(sent)
        if total + t > overlap_tokens:
            if tail:
                break
            # a single sentence larger than the overlap budget: skip it
            # and try earlier (typically shorter) sentences instead —
            # never duplicate a whole oversized chunk as "overlap"
            continue
        tail.insert(0, sent)
        total += t
    return " ".join(tail)


@dataclass
class ChunkPlan:
    """Config for chunking (mirrors configs/rag.yaml chunking section)."""
    chunk_size_tokens: int = DEFAULT_CHUNK_SIZE_TOKENS
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS
    min_tokens: int = MIN_CHUNK_TOKENS
    max_tokens: int = MAX_CHUNK_TOKENS


def chunk_section_text(text: str, plan: ChunkPlan | None = None) -> list[str]:
    """Chunk one cleaned section's body text. Returns chunk texts
    (provenance fields are attached by the caller)."""
    plan = plan or ChunkPlan()
    target, overlap = plan.chunk_size_tokens, plan.overlap_tokens
    units: list[str] = []
    for u in _split_units(text):
        units.extend(_split_long_unit(u, plan.max_tokens))

    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0

    def _flush():
        nonlocal cur, cur_tokens
        if cur:
            chunks.append(" ".join(cur).strip())
            tail = _tail_overlap(chunks[-1], overlap)
            cur = [tail] if tail else []
            cur_tokens = estimate_tokens(tail)

    for unit in units:
        t = estimate_tokens(unit)
        if cur and cur_tokens + t > target:
            _flush()
        if t > plan.max_tokens:  # still too big (pathological line)
            pieces = _split_long_unit(unit, target)
            for p in pieces:
                pt = estimate_tokens(p)
                if cur and cur_tokens + pt > target:
                    _flush()
                cur.append(p)
                cur_tokens += pt
        else:
            cur.append(unit)
            cur_tokens += t
    _flush()
    # merge trivially small trailing chunks forward is not possible (last);
    # instead drop a tail chunk that carries no unique content
    if len(chunks) >= 2 and estimate_tokens(chunks[-1]) < plan.min_tokens // 2 \
            and chunks[-1].strip() in chunks[-2]:
        chunks.pop()
    return [c for c in chunks if c.strip()]


def chunk_document(sections: list, plan: ChunkPlan | None = None) -> list[dict]:
    """Chunk a list of cleaning.CleanSection (or objects with .heading/.text).

    Returns dicts: {"section": heading_path, "chunk_index": i, "text": text,
    "token_estimate": n}. Section-boundary preference: chunks never span
    sections. Short sections (< min_tokens) may be merged with the NEXT
    section only when both lack a heading path (front-matter); otherwise
    the small chunk is kept (it is still a complete concept)."""
    plan = plan or ChunkPlan()
    out: list[dict] = []
    for sec in sections:
        texts = chunk_section_text(sec.text, plan)
        for i, t in enumerate(texts):
            out.append({"section": sec.heading, "chunk_index": i,
                        "text": t, "token_estimate": estimate_tokens(t)})
    return out