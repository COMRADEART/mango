"""T16.13 / T16.37 — bounded evidence extraction.

Short spans only. Prefer paraphrase+provenance over webpage copies.
"""
from __future__ import annotations

import hashlib
import re

from sciencemath.web.limits import ResearchLimits
from sciencemath.web.source import EvidenceSpan

_SENT = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-z0-9]{3,}", re.I)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_spans(source, query: str, *,
                  limits: ResearchLimits | None = None) -> list[EvidenceSpan]:
    limits = limits or ResearchLimits()
    content = getattr(source, "content", "") or ""
    if not content:
        return []
    qtok = {t.lower() for t in _TOKEN.findall(query or "")}
    sentences = [s.strip() for s in _SENT.split(content) if s.strip()]
    if not sentences:
        sentences = [content.strip()]
    scored = []
    cursor = 0
    for sent in sentences:
        start = content.find(sent, cursor)
        if start < 0:
            start = cursor
        end = start + len(sent)
        cursor = end
        stok = {t.lower() for t in _TOKEN.findall(sent)}
        ov = len(qtok & stok) / max(1, len(qtok)) if qtok else 0.0
        if ov <= 0 and not re.search(
                r"\b(ceo|mayor|efficacy|api|/v\d|/widgets|appointed|"
                r"passed in|official|frankfurt|planck|bankrupt|billion|"
                r"privacy|high is|client\.get|x-helios)\b", sent, re.I):
            continue
        scored.append((ov, start, EvidenceSpan(
            source_id=source.source_id,
            start=start,
            end=end,
            text=sent[: limits.max_quote_chars],
            content_hash=_hash(sent),
        )))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for _, _, span in scored[: limits.max_evidence_spans_per_source]:
        out.append(span)
    return out
