"""T16.3 / T16.28 — optional free live providers.

Paid APIs are never used. Network is opt-in via MANGO_WEB_LIVE=1.
Wikipedia REST is FREE_NETWORK. Unavailability is recorded, never faked.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from sciencemath.web.limits import FREE_NETWORK
from sciencemath.web.safety import classify_url
from sciencemath.web.source import UNKNOWN, Source

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST = "https://en.wikipedia.org/api/rest_v1/page/summary/"
USER_AGENT = "MangoT16Research/1.0 (local eval; free Wikipedia API)"


class WikipediaLiveProvider:
    provider_name = "WIKIPEDIA_LIVE"
    provider_cost_class = FREE_NETWORK
    network_required = True
    live_or_fixture = "live"

    def __init__(self, *, timeout_s: float = 8.0, enabled: bool | None = None):
        self.timeout_s = timeout_s
        self.enabled = (os.environ.get("MANGO_WEB_LIVE", "0") == "1"
                        if enabled is None else enabled)

    def timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def search(self, query: str) -> list[Source]:
        if not self.enabled:
            return []
        q = urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": query,
            "srlimit": 5, "format": "json",
        })
        url = WIKI_API + "?" + q
        data = self._get_json(url)
        if not data:
            return []
        hits = (data.get("query") or {}).get("search") or []
        out = []
        for h in hits:
            title = h.get("title") or UNKNOWN
            page_url = "https://en.wikipedia.org/wiki/" + \
                urllib.parse.quote(title.replace(" ", "_"))
            out.append(Source(
                source_id="wiki:" + title,
                url=page_url,
                domain="en.wikipedia.org",
                title=title,
                publisher="Wikimedia Foundation",
                source_type="WIKI",
                trust_class="REPUTABLE_SECONDARY",
                primary_or_secondary="SECONDARY",
                live_or_fixture="live",
                fetch_status="OK",
                content=h.get("snippet") or "",
            ))
        return out

    def fetch(self, url: str) -> Source:
        gate = classify_url(url)
        now = self.timestamp()
        if not gate["ok"]:
            return Source(source_id="blocked:" + (gate["reason"] or "url"),
                          url=url, fetch_status="BLOCKED", retrieved_at=now,
                          live_or_fixture="live")
        if not self.enabled:
            return Source(source_id="live-disabled", url=url,
                          fetch_status="ERROR", retrieved_at=now,
                          live_or_fixture="live")
        title = url.rsplit("/", 1)[-1]
        data = self._get_json(WIKI_REST + urllib.parse.quote(title))
        if not data:
            return Source(source_id="wiki-miss:" + title, url=url,
                          fetch_status="NOT_FOUND", retrieved_at=now,
                          live_or_fixture="live")
        extract = data.get("extract") or ""
        return Source(
            source_id="wiki:" + (data.get("title") or title),
            url=data.get("content_urls", {}).get("desktop", {}).get("page")
            or url,
            domain="en.wikipedia.org",
            title=data.get("title") or UNKNOWN,
            publisher="Wikimedia Foundation",
            source_type="WIKI",
            publication_date=UNKNOWN,
            modified_date=UNKNOWN,
            retrieved_at=now,
            trust_class="REPUTABLE_SECONDARY",
            primary_or_secondary="SECONDARY",
            live_or_fixture="live",
            fetch_status="OK",
            content=extract,
            language=data.get("lang") or "en",
        )

    def metadata(self, url: str) -> dict:
        src = self.fetch(url)
        return {"url": src.url, "title": src.title,
                "fetch_status": src.fetch_status,
                "live_or_fixture": "live"}

    def _get_json(self, url: str) -> dict | None:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read(200_000)
            return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
