"""T16.5 — structured source representation.

Missing metadata stays UNKNOWN. Never invent a date, author, title,
or publisher.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

UNKNOWN = "UNKNOWN"

SOURCE_TYPES = (
    "OFFICIAL_PAGE", "SPECIFICATION", "SOURCE_REPOSITORY", "PAPER",
    "GOVERNMENT_PAGE", "NEWS_ARTICLE", "BLOG", "WIKI", "FORUM",
    "SOCIAL", "AGGREGATOR", "PRESS_RELEASE", "DATASET", "UNKNOWN",
)

FETCH_STATUSES = (
    "OK", "REDIRECT", "NOT_FOUND", "FORBIDDEN", "ERROR", "BLOCKED",
    "UNSUPPORTED", "UNKNOWN",
)


def _u(value: str | None) -> str:
    v = (value or "").strip()
    return v if v else UNKNOWN


@dataclass
class EvidenceSpan:
    source_id: str
    start: int
    end: int
    text: str
    content_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Source:
    source_id: str
    url: str
    domain: str = UNKNOWN
    title: str = UNKNOWN
    publisher: str = UNKNOWN
    source_type: str = UNKNOWN
    publication_date: str = UNKNOWN
    modified_date: str = UNKNOWN
    retrieved_at: str = UNKNOWN
    author: str = UNKNOWN
    language: str = UNKNOWN
    content_hash: str = UNKNOWN
    trust_class: str = UNKNOWN
    primary_or_secondary: str = UNKNOWN
    live_or_fixture: str = "fixture"
    fetch_status: str = UNKNOWN
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)
    canonical_url: str = UNKNOWN
    syndicate_group: str = UNKNOWN
    content: str = ""
    redirect_from: str = UNKNOWN

    def __post_init__(self) -> None:
        self.source_id = _u(self.source_id)
        self.url = _u(self.url)
        self.domain = _u(self.domain)
        self.title = _u(self.title)
        self.publisher = _u(self.publisher)
        self.source_type = _u(self.source_type)
        self.publication_date = _u(self.publication_date)
        self.modified_date = _u(self.modified_date)
        self.retrieved_at = _u(self.retrieved_at)
        self.author = _u(self.author)
        self.language = _u(self.language)
        self.trust_class = _u(self.trust_class)
        self.primary_or_secondary = _u(self.primary_or_secondary)
        self.fetch_status = _u(self.fetch_status)
        self.canonical_url = _u(self.canonical_url)
        self.syndicate_group = _u(self.syndicate_group)
        if self.content and self.content_hash == UNKNOWN:
            self.content_hash = hashlib.sha256(
                self.content.encode("utf-8")).hexdigest()

    def to_dict(self, *, include_content: bool = False) -> dict:
        d = asdict(self)
        if not include_content:
            d.pop("content", None)
        d["evidence_spans"] = [
            s.to_dict() if isinstance(s, EvidenceSpan) else s
            for s in self.evidence_spans
        ]
        return d
