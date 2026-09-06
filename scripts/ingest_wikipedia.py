"""T5 Wikipedia ingestion — curated corpus builder (implements the T0 stub).

Collects CURATED science/math Wikipedia pages (configs/rag.yaml seed
list per subject, depth-1 link expansion capped, never the full dump),
cleans them (T5.5), chunks semantically (T5.6), and writes
rag/corpus/*.jsonl with full provenance per chunk (T5.4).

License gate: the run is refused unless data/science_sources/
source_registry.json grants wikipedia_en approved_for_local_index.

Raw responses are cached under data/raw/wikipedia/ (offline re-runs and
provenance). Attribution string per chunk:
  'Text from Wikipedia (en), article "<TITLE>", revision <REVID>,
   retrieved <DATE>, <URL>. Licensed CC BY-SA 4.0.'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urlrequest
from urllib.parse import quote, urlencode

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sciencemath.rag.chunking import ChunkPlan, chunk_document, estimate_tokens  # noqa: E402
from sciencemath.rag.cleaning import clean_document  # noqa: E402
from sciencemath.rag.schema import SciDocument, chunk_checksum, validate_document  # noqa: E402
from sciencemath.rag.source_registry import SourceRegistry  # noqa: E402
from sciencemath.rag.taxonomy import classify_domain  # noqa: E402
from sciencemath.utils.io_utils import load_yaml, read_jsonl, write_json, write_jsonl  # noqa: E402

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = ("Mango-T5-research/0.1 (local science retrieval corpus; "
              "contact: none)")
CACHE_DIR = REPO_ROOT / "data" / "raw" / "wikipedia"
CORPUS_DIR = REPO_ROOT / "rag" / "corpus"

_boilerplate_note = ("boilerplate sections (References/External links/...) "
                     "are dropped by rag.cleaning")


def _api_get(params: dict, *, timeout: float = 30.0,
             retries: int = 5) -> dict:
    """Polite MediaWiki API GET with raw-disk cache and 429 backoff."""
    from urllib.error import HTTPError
    url = f"{API}?{urlencode(params)}"
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    last_exc = None
    for attempt in range(retries):
        req = urlrequest.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data, ensure_ascii=False),
                             encoding="utf-8")
            return data
        except HTTPError as exc:
            if exc.code not in (429, 503):
                raise
            wait = 2.0 * (attempt + 1) * (attempt + 1)   # 2,8,18,32,50 s
            retry_after = exc.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = max(wait, float(retry_after))
            print(f"  [rate-limited {exc.code}; backing off {wait:.0f}s "
                  f"(attempt {attempt + 1}/{retries})]", file=sys.stderr)
            time.sleep(wait)
            last_exc = exc
    raise last_exc


def fetch_page_extract(title: str) -> dict | None:
    """Full plain-text extract + metadata for one page (or None)."""
    data = _api_get({
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "extracts|info|pageprops", "inprop": "url",
        "explaintext": 1, "exsectionformat": "wiki", "redirects": 1,
        "titles": title,
    })
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    page = pages[0]
    if "missing" in page or not page.get("extract"):
        return None
    if "disambiguation" in (page.get("pageprops") or {}):
        return None  # skip disambiguation pages
    return {
        "title": page.get("title", title),
        "pageid": page.get("pageid"),
        "revision": str(page.get("lastrevid") or ""),
        "url": page.get("fullurl") or
               f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
        "text": page["extract"],
        "touched": (page.get("touched") or "")[:10],
    }


def fetch_links(title: str, limit: int = 500) -> list[str]:
    """Namespace-0 internal links of a page (deterministic alphabetical)."""
    data = _api_get({
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "links", "plnamespace": 0, "pllimit": max(limit, 10),
        "titles": title, "redirects": 1,
    })
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return []
    links = [l.get("title") for l in pages[0].get("links", [])
             if l.get("title")]
    return sorted(set(links))


def normalize_text(text: str) -> str:
    """Corpus-level text normalization used for exact/near-dup keys only;
    the STORED text is the cleaned original (never over-normalized).
    Punctuation is stripped so 'quickly!' and 'quickly' dedupe."""
    t = unicodedata.normalize("NFKC", text.lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def jaccard(a: str, b: str) -> float:
    sa, sb = set(normalize_text(a).split()), set(normalize_text(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _page_domain(title: str, subject: str, section: str) -> str:
    """Chunk domain: keyword classification first (it can refine across
    subjects, e.g. a chemistry section on a biology page); the configured
    subject is the authoritative fallback so link-expanded pages like
    'Geology' don't degrade to 'general' (T5.4 provenance)."""
    d = classify_domain(
        f"{title} {subject.replace('_', ' ')} {section}")
    return d if d != "general" else subject


def build_chunks_for_page(page: dict, subject: str, plan: ChunkPlan,
                          *, near_dup_threshold: float = 0.9,
                          seen_texts: list[tuple[str, str]] | None = None,
                          ) -> list[SciDocument]:
    """Clean -> section chunk -> SciDocument for one page."""
    cleaned = clean_document(page["title"], page["text"])
    raw_chunks = chunk_document(cleaned.sections, plan)
    doc_id = f"wiki-{page['pageid']}"
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out: list[SciDocument] = []
    for rc in raw_chunks:
        slug = re.sub(r"[^a-z0-9]+", "_", rc["section"].lower()).strip("_")[:40] \
            if rc["section"] else "intro"
        # section slugs truncate at 40 chars; disambiguate so two long
        # section names in one article can't collide on chunk_id
        slug += "_" + hashlib.sha1(
            (rc["section"] or "intro").encode("utf-8")).hexdigest()[:8]
        chunk_id = f"{doc_id}:{slug}:{rc['chunk_index']}"
        text = rc["text"]
        # duplicate/near-duplicate detection (T5.5)
        if seen_texts is not None:
            key = normalize_text(text)
            if any(key == k or jaccard(text, t) >= near_dup_threshold
                   for k, t in seen_texts):
                continue
            seen_texts.append((key, text))
        doc = SciDocument(
            document_id=doc_id,
            source_id="wikipedia_en",
            source_type="encyclopedia",
            title=page["title"],
            section=rc["section"],
            # T5.4: domain is provenance metadata — the configured subject
            # is authoritative; keyword classification refines it and the
            # fallback keeps link-expanded pages out of 'general'.
            domain=_page_domain(page["title"], subject, rc["section"]),
            subject="",
            text=text,
            url=page["url"],
            revision=page["revision"],
            publication_date="",
            retrieved_at=date,
            license="CC BY-SA 4.0",
            attribution=(f"Text from Wikipedia (en), article "
                         f"\"{page['title']}\", revision {page['revision']}, "
                         f"retrieved {date}, {page['url']}. "
                         f"Licensed CC BY-SA 4.0."),
            chunk_id=chunk_id,
            checksum="")
        doc.checksum = chunk_checksum(doc)
        out.append(doc)
    return out


def ingest(*, cfg_path: Path = REPO_ROOT / "configs" / "rag.yaml",
           subjects: list[str] | None = None, dry_run: bool = False) -> dict:
    registry = SourceRegistry()
    registry.require("wikipedia_en", "local_index")  # license gate
    cfg = load_yaml(cfg_path)
    ing = cfg["ingestion"]
    plan = ChunkPlan(
        chunk_size_tokens=int(cfg["chunking"]["chunk_size_tokens"]),
        overlap_tokens=int(cfg["chunking"]["chunk_overlap_tokens"]))
    max_depth = int(ing.get("max_depth", 0))
    max_pages = int(ing.get("max_pages_per_subject", 40))
    chosen = subjects or list(ing["categories"])
    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    all_docs: list[SciDocument] = []
    stats: dict[str, dict] = {}
    seen_texts: list[tuple[str, str]] = []   # corpus-wide dedup
    for subject in chosen:
        seeds = list(ing["categories"][subject])
        titles, fetched = list(seeds), {}
        # depth-1 expansion: links of seeds, alphabetical, capped
        if max_depth >= 1:
            budget = max_pages - len(seeds)
            for seed in seeds:
                if budget <= 0:
                    break
                for link in fetch_links(seed):
                    if budget <= 0:
                        break
                    if link not in titles:
                        titles.append(link)
                        budget -= 1
        titles = titles[:max_pages]
        page_docs: list[SciDocument] = []
        n_pages = 0
        for title in titles:
            page = fetch_page_extract(title)
            if not page:
                stats.setdefault(subject, {"pages": 0, "chunks": 0,
                                           "skipped": []})["skipped"].append(title)
                time.sleep(0.05)
                continue
            docs = build_chunks_for_page(page, subject, plan,
                                         seen_texts=seen_texts)
            page_docs.extend(docs)
            n_pages += 1
            time.sleep(0.6)  # politeness (Wikipedia API etiquette)
        stats[subject] = {"pages": n_pages, "chunks": len(page_docs),
                          "skipped": stats.get(subject, {}).get("skipped", [])}
        all_docs.extend(page_docs)
        print(f"[{subject}] pages={n_pages} chunks={len(page_docs)}",
              file=sys.stderr)

    # validate every chunk (provenance completeness gate)
    errors = []
    for d in all_docs:
        errs = validate_document(d, source_ids={"wikipedia_en"})
        if errs:
            errors.append(f"{d.chunk_id}: {'; '.join(errs)}")
    if errors:
        raise RuntimeError(f"provenance validation failed:\n" + "\n".join(
            errors[:20]))

    records = [d.to_dict() for d in all_docs]
    for r in records:
        r["source_id"] = "wikipedia_en"
        r["retrieved_at"] = r["retrieved_at"] or retrieved_at

    # corpus manifest (T5.16 versioning contract)
    domain_dist: dict[str, int] = {}
    for r in records:
        domain_dist[r["domain"]] = domain_dist.get(r["domain"], 0) + 1
    manifest = {
        "corpus_version": f"mango-science-corpus-v0.1",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_id": "wikipedia_en",
        "source_license": "CC BY-SA 4.0",
        "registry_status": "APPROVED",
        "documents": len({r["document_id"] for r in records}),
        "chunks": len(records),
        "domains": domain_dist,
        "config": {"subjects": chosen, "max_depth": max_depth,
                   "max_pages_per_subject": max_pages,
                   "chunk_size_tokens": plan.chunk_size_tokens,
                   "chunk_overlap_tokens": plan.overlap_tokens},
        "per_subject": stats,
        "attribution": ("Text from Wikipedia (en), article '<title>', "
                        "revision <revid>, retrieved <date>, <url>. "
                        "Licensed CC BY-SA 4.0."),
        "approved_for_redistribution": False,
        "notes": "Internal retrieval corpus; not for redistribution or SFT.",
    }
    if not dry_run:
        CORPUS_DIR.mkdir(parents=True, exist_ok=True)
        path = CORPUS_DIR / "wikipedia_en.jsonl"
        write_jsonl(path, records)
        # checksums AFTER writing (manifest covers files)
        manifest = dict(manifest)
        manifest["file_checksums"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
        manifest["corpus_checksum"] = hashlib.sha256(
            json.dumps(records, sort_keys=True).encode()).hexdigest()[:16]
        write_json(CORPUS_DIR / "corpus_manifest.json", manifest)
    print(f"corpus: {len(records)} chunks from "
          f"{manifest['documents']} documents", file=sys.stderr)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subjects", nargs="*", default=None,
                    help="restrict to these config subjects")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and build but do not write rag/corpus/")
    args = ap.parse_args()
    manifest = ingest(subjects=args.subjects, dry_run=args.dry_run)
    print(json.dumps({k: manifest[k] for k in
                      ("corpus_version", "documents", "chunks", "domains")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())