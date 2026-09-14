"""Cache by content_hash + parser_version. Invalidate on hash change."""
from __future__ import annotations

from sciencemath.document.limits import PARSER_VERSION
from sciencemath.document.models import NormalizedDocument


class DocumentCache:
    def __init__(self):
        self._rows: dict[tuple[str, str], NormalizedDocument] = {}

    def key(self, content_hash: str, parser_version: str = PARSER_VERSION):
        return (content_hash, parser_version)

    def get(self, content_hash: str,
            parser_version: str = PARSER_VERSION) -> NormalizedDocument | None:
        return self._rows.get(self.key(content_hash, parser_version))

    def put(self, doc: NormalizedDocument) -> NormalizedDocument:
        self._rows[self.key(doc.content_hash, doc.parser_version)] = doc
        return doc

    def invalidate(self, content_hash: str) -> None:
        drop = [k for k in self._rows if k[0] == content_hash]
        for k in drop:
            self._rows.pop(k, None)
