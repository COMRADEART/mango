"""T16.10 — search diversity: duplicates, syndicates, mirrors, canonicals."""
from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw)
    except Exception:
        return raw
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "/").rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), host, path, "", "", ""))


def duplicate_key(source) -> str:
    syn = getattr(source, "syndicate_group", "") or ""
    if syn and syn != "UNKNOWN":
        return "syn:" + syn
    can = getattr(source, "canonical_url", "") or ""
    url = getattr(source, "url", "") or ""
    target = can if can and can != "UNKNOWN" else url
    return "can:" + canonical_url(target)


def diversify(sources: list, *, max_per_domain: int = 4) -> list:
    """Keep independent evidence; drop near-duplicates after the first."""
    seen_keys: set[str] = set()
    domain_n: dict[str, int] = {}
    out = []
    for s in sources:
        key = duplicate_key(s)
        if key in seen_keys:
            continue
        domain = (getattr(s, "domain", "") or "").lower()
        if domain.startswith("www."):
            domain = domain[4:]
        n = domain_n.get(domain, 0)
        if domain and n >= max_per_domain:
            continue
        seen_keys.add(key)
        domain_n[domain] = n + 1
        out.append(s)
    return out


def unique_domains(sources: list) -> list[str]:
    seen = []
    for s in sources:
        d = (getattr(s, "domain", "") or "").lower()
        if d and d not in seen:
            seen.append(d)
    return seen
