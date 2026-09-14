"""Retrieval cache keyed by owner, scope, query, and DB generation."""
from __future__ import annotations

from sciencemath.memory.limits import MAX_CACHE_ENTRIES


class RetrievalCache:
    def __init__(self, max_entries: int = MAX_CACHE_ENTRIES):
        self.max_entries = max_entries
        self._rows: dict[tuple, list] = {}

    def key(self, owner_id: str, scope_type: str, scope_id: str,
            query: str, generation: int) -> tuple:
        return (owner_id, scope_type, scope_id, query, generation)

    def get(self, owner_id: str, scope_type: str, scope_id: str,
            query: str, generation: int):
        return self._rows.get(
            self.key(owner_id, scope_type, scope_id, query, generation))

    def put(self, owner_id: str, scope_type: str, scope_id: str,
            query: str, generation: int, value: list) -> None:
        if len(self._rows) >= self.max_entries:
            self._rows.clear()
        self._rows[self.key(owner_id, scope_type, scope_id, query,
                            generation)] = value

    def invalidate(self) -> None:
        self._rows.clear()
