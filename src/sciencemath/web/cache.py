"""T16.42 — bounded evidence cache metadata.

Cached data is never assumed current. Time-sensitive tasks respect
freshness policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sciencemath.web.freshness import is_stale


@dataclass
class CacheRecord:
    url: str
    retrieved_at: str
    content_hash: str
    freshness_class: str

    def to_dict(self) -> dict:
        return asdict(self)


class EvidenceCache:
    def __init__(self):
        self._rows: dict[str, CacheRecord] = {}

    def put(self, url: str, retrieved_at: str, content_hash: str,
            freshness_class: str) -> CacheRecord:
        rec = CacheRecord(url=url, retrieved_at=retrieved_at,
                          content_hash=content_hash,
                          freshness_class=freshness_class)
        self._rows[url] = rec
        return rec

    def get(self, url: str) -> CacheRecord | None:
        return self._rows.get(url)

    def usable(self, url: str, *, question: str, query_time: str,
               source) -> bool:
        rec = self._rows.get(url)
        if rec is None:
            return False
        if rec.freshness_class in ("RECENT", "BREAKING"):
            return not is_stale(source, question=question,
                                query_time=query_time,
                                freshness=rec.freshness_class)
        return True
