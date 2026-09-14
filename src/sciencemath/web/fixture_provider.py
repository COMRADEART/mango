"""T16.3/T16.4 — deterministic fixture search and fetch providers."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sciencemath.web.limits import FREE_LOCAL
from sciencemath.web.safety import classify_url
from sciencemath.web.source import Source, UNKNOWN

_TOKEN = re.compile(r"[a-z0-9]{2,}", re.I)
_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "for", "in", "on", "is",
    "are", "was", "were", "what", "who", "which", "this", "that", "with",
    "from", "look", "up", "search", "web", "official", "source", "primary",
    "according", "current", "today", "latest", "please", "tell", "me",
}


class FixtureCorpus:
    def __init__(self, pages: list[Source], *, query_time: str):
        self.pages = {p.source_id: p for p in pages}
        self.by_url = {p.url: p for p in pages if p.url != UNKNOWN}
        self.query_time = query_time

    def get(self, source_id: str) -> Source | None:
        return self.pages.get(source_id)


class FixtureSearchProvider:
    provider_name = "FIXTURE_SEARCH_PROVIDER"
    provider_cost_class = FREE_LOCAL
    network_required = False
    live_or_fixture = "fixture"

    def __init__(self, corpus: FixtureCorpus):
        self.corpus = corpus

    def timestamp(self) -> str:
        return self.corpus.query_time

    def search(self, query: str) -> list[Source]:
        q_all = {t.lower() for t in _TOKEN.findall(query or "")}
        q = {t for t in q_all if t not in _STOP and len(t) > 2}
        if not q:
            q = q_all
        if not q:
            return []
        scored = []
        for p in self.corpus.pages.values():
            if p.fetch_status == "NOT_FOUND":
                continue
            blob = f"{p.title} {p.publisher} {p.content} {p.source_id}"
            tokens = {t.lower() for t in _TOKEN.findall(blob)}
            hit = len(q & tokens)
            if hit <= 0:
                continue
            scored.append((hit / len(q), p.source_id, p))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [p for _, _, p in scored[:20]]

    def fetch(self, url: str) -> Source:
        return FixtureFetchProvider(self.corpus).fetch(url)

    def metadata(self, url: str) -> dict:
        return FixtureFetchProvider(self.corpus).metadata(url)


class FixtureFetchProvider:
    provider_name = "FIXTURE_FETCH_PROVIDER"
    provider_cost_class = FREE_LOCAL
    network_required = False
    live_or_fixture = "fixture"

    def __init__(self, corpus: FixtureCorpus):
        self.corpus = corpus

    def timestamp(self) -> str:
        return self.corpus.query_time

    def search(self, query: str) -> list[Source]:
        return FixtureSearchProvider(self.corpus).search(query)

    def fetch(self, url: str) -> Source:
        gate = classify_url(url)
        now = self.corpus.query_time
        if not gate["ok"]:
            return Source(
                source_id="blocked:" + (gate["reason"] or "url"),
                url=url or UNKNOWN,
                fetch_status="BLOCKED",
                retrieved_at=now,
                live_or_fixture="fixture",
                title=UNKNOWN,
            )
        page = self.corpus.by_url.get(url)
        if page is None:
            return Source(source_id="missing:" + url, url=url,
                          fetch_status="NOT_FOUND", retrieved_at=now,
                          live_or_fixture="fixture")
        from copy import deepcopy
        out = deepcopy(page)
        out.retrieved_at = now
        out.live_or_fixture = "fixture"
        return out

    def metadata(self, url: str) -> dict:
        src = self.fetch(url)
        return {
            "url": src.url,
            "source_id": src.source_id,
            "title": src.title,
            "publisher": src.publisher,
            "publication_date": src.publication_date,
            "modified_date": src.modified_date,
            "fetch_status": src.fetch_status,
            "trust_class": src.trust_class,
            "content_hash": src.content_hash,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
