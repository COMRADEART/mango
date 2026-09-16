"""T21R5 — static gold audit (data-only; runs BEFORE HOLDOUT_FROZEN).

Mechanically verifies, with a LOCAL reimplementation of the frozen
retrieval arithmetic (never importing the runtime — the AST blindness
firewall test enforces this), that the gold of every suite row is
achievable against the frozen T21R5 corpus:

  1. window: every row's gold_chunk_id is in the final evidence window
     (BM25 -> rerank -> dedup -> B1 select_window, mirrored exactly);
  2. conflict windows: for authority/freshness resolvable rows the
     canonical AND loser chunks are both in the window; for unresolved
     rows both conflict chunks are in the window;
  3. winner-not-rank-1: >= 80 loser-vocabulary stress rows where the
     canonical winner is NOT rank 1 of the final window while the loser
     chunk is present (the B2 winner-propagation stress);
  4. naive-window domination: >= 100 multihop/crossdomain rows where a
     required source is ABSENT from the naive top-8 deduplicated window
     (the B1 reservation stress; measured WITHOUT select_window);
  5. coverage gate: for every ANSWER row, the frozen dual coverage
     formulation measured over the gold chunk's quarantined synthesis
     text (plus the hop-2 chunk for bridge rows) meets MIN_COVERAGE;
  6. hop-2 bridge: for every bridge row, the creator's birthplace chunk
     is in the hop-2 retrieval window ("{creator} born birthplace",
     top_k=3);
  7. injection exposure: every source-directive exposure row's gold
     chunk keeps at least one non-directive sentence carrying the safe
     fact after quarantine;
  8. citation spoof: every spoof query is flagged by the frozen ID-token
     spoof detection (reimplemented as data);
  9. conflict negatives: no conflict chunk pair exists for any
     unrelated-conflict negative row's (entity, attribute);
 10. absent probes: no absent-entity token appears in any corpus chunk.

Usage: python scripts/t21r6_static_gold_audit.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / "rag" / "gk_holdout_t21r6"
SUITES_DIR = ROOT / "evaluations" / "t21r6" / "suites"

TOP_K = 8
MIN_COVERAGE = 0.60
JACCARD_THRESHOLD = 0.85
MAX_PER_SOURCE = 3
WINDOW_RESERVE_FRACTION = 0.5
COVERAGE_WEIGHT = 1.0
RERANK_TIEBREAK_WEIGHT = 0.01
AUTHORITY_BONUS = 0.02
K1, B = 1.2, 0.75

# ---------------------------------------------------------------------------
# Frozen-runtime data copies (cross-checked mechanically by
# tests/test_t21r6_blind_holdout_contract.py against the runtime sources)
# ---------------------------------------------------------------------------

_TOKEN_RE = None  # set below as data


def _token_re() -> "re.Pattern[str]":
    return _RE_WORD


_RE_WORD = None  # assigned after import section below

STOP_WORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "and", "or", "is", "are", "was",
    "were", "be", "been", "it", "its", "as", "at", "by", "for", "on", "with",
    "that", "this", "from", "which", "who", "whom", "what", "when", "where",
    "how", "why", "did", "does", "do", "does", "have", "has", "had", "many",
    "much", "there", "their", "about", "into", "also",
})

AUTHORITY_RANK = {
    "PRIMARY_REFERENCE": 6,
    "ENCYCLOPEDIC": 5,
    "ACADEMIC_REFERENCE": 4,
    "GOVERNMENT_PUBLICATION": 4,
    "INSTITUTIONAL": 3,
    "GENERAL_REFERENCE": 2,
    "UNKNOWN": 0,
}

FRAME_TOKENS = frozenset({
    "identify", "tell", "give", "name", "list", "state", "describe",
    "define", "show", "indicate", "find", "belong", "belongs", "under",
    "over", "about", "between", "during", "kept", "keep", "listed",
    "called", "named", "known", "located", "situated", "person", "people",
    "town", "city", "village", "scholar", "device", "painting", "work",
    "wrote", "written",
    "what", "which", "where", "when", "who", "whose", "whom", "how",
    "does", "did", "was", "were", "is", "are", "has", "have", "had",
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
    "with", "by", "from", "that", "this", "it", "its", "their", "there",
    "birth", "born", "invent", "invented", "invention", "inventions",
    "introduce", "introduced", "introduction", "launch", "launched",
    "debut", "debuted", "discover", "discovered", "discovery",
    "establish", "established", "founding", "founded", "foundation",
    "create", "created", "publish", "published", "publication", "print",
    "printed", "paint", "painted", "appear", "appeared", "author",
    "authored", "ratify", "ratified", "signing", "signed", "complete",
    "completed", "landing", "landed", "sealing", "sealed", "open",
    "opened", "famous",
})

_SOURCE_DIRECTIVE_PATTERNS = (
    re.compile(r"ignore (?:all |any |the )?(?:previous|prior|above|earlier)"
               r" (?:instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"do not (?:cite|reference|mention) (?:this|the|any) "
               r"(?:source|passage|chunk|text)", re.IGNORECASE),
    re.compile(r"mark (?:this |the )?(?:answer|response|claim) (?:as )?"
               r"(?:correct|verified|approved)", re.IGNORECASE),
    re.compile(r"reveal (?:the |your )?(?:system )?(?:prompt|instructions)"
               r"|\bwhat is your (?:system )?prompt\b", re.IGNORECASE),
    re.compile(r"use (?:the )?(?:live|open|real) (?:internet|web|network)"
               r"|(?:go|get) online", re.IGNORECASE),
    re.compile(r"write (?:this|it|that) into (?:memory|your memory|storage)"
               r"|remember this forever", re.IGNORECASE),
    re.compile(r"\b(?:run|execute) (?:the following|this) "
               r"(?:command|code|instruction|script)", re.IGNORECASE),
    re.compile(r"(?:i am|this is) (?:the )?(?:system|administrator|"
               r"developer|official|authoritative)", re.IGNORECASE),
    re.compile(r"cite (?:this|me) (?:source )?(?:even if|regardless|whether"
               r" or not)", re.IGNORECASE),
    re.compile(r"(?:system|developer|admin(?:istrator)?)\s*"
               r"(?:message|prompt|notice|override)\s*:|"
               r"you are now (?:a|an|the)", re.IGNORECASE),
    re.compile(r"trust (?:this|the|only this|only the) "
               r"(?:source|text|record|passage|document)|"
               r"believe (?:this|the) (?:source|passage)", re.IGNORECASE),
    re.compile(r"regardless of (?:the )?(?:evidence|facts|sources)|"
               r"whether or not it (?:is|was|appears|exists)",
               re.IGNORECASE),
    re.compile(r"(?:do not|don't|never) (?:include|emit|add|use|show) "
               r"(?:any )?citations|omit (?:the )?citations|"
               r"without (?:any )?citations", re.IGNORECASE),
    re.compile(r"answer (?:\"[^\"]{1,40}\"|'[^']{1,40}')|"
               r"(?:always )?(?:state|say|claim) that [^.]{0,60}"
               r"(?:regardless|even if)", re.IGNORECASE),
    re.compile(r"(?:ignore|disregard) (?:the |this |any |all )?user\b|"
               r"(?:ignore|disregard) (?:the |this )?"
               r"(?:user's|question|request|question asked)",
               re.IGNORECASE),
    re.compile(r"ignore (?:the |all |any )?citations\b|"
               r"answer (?:without|with no) citations",
               re.IGNORECASE),
)

_QUERY_OVERRIDE_PATTERNS = (
    re.compile(r"ignore (?:the )?(?:citations|sources|provenance)",
               re.IGNORECASE),
    re.compile(r"answer (?:from|with|using) (?:your )?(?:memory|own "
               r"knowledge|internal knowledge|training)", re.IGNORECASE),
    re.compile(r"say you (?:found|have|used) (?:a |the )?source",
               re.IGNORECASE),
    re.compile(r"(?:return|include|make up|fabricate) (?:a |the )?"
               r"(?:fake|nonexistent|dummy) (?:url|citation|source)",
               re.IGNORECASE),
    re.compile(r"use (?:the |this )?source even if (?:it is |it's |you are "
               r"|they are )?unrelated", re.IGNORECASE),
    re.compile(r"skip (?:the )?(?:verification|evidence gate|claim check)",
               re.IGNORECASE),
    re.compile(r"ignore (?:all |any |the )?(?:previous|prior|above|earlier)"
               r" (?:instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"(?:i am|this is) (?:the )?(?:system|administrator|"
               r"developer|official|authoritative)", re.IGNORECASE),
)

_SOURCE_ID_RE = re.compile(r"\bgk-([0-9a-f]{12})\b")
_CHUNK_ID_RE = re.compile(r"\b(gk-[0-9a-f]{12}:[A-Za-z0-9_.:-]+)\b")
_CITATION_ID_RE = re.compile(r"\b(C\d+-[0-9a-f]{8,})\b")
_PROVENANCE_CLAIM_CUES = re.compile(
    r"(?:according to|per|from|cite|citing|use|trust|reference|see)\b",
    re.IGNORECASE)

_HISTORICAL_AS_OF = re.compile(
    r"\bas of\s+(?:the\s+)?(?:end of\s+)?(\d{4}|[A-Z][a-z]+ \d{1,2},? "
    r"\d{4}|\w+ \d{4})\b", re.IGNORECASE)
_QUESTION_FRAME_RE = re.compile(
    r"\b(?:which|what|where|when|who|whose|why|how)\b", re.IGNORECASE)

_RE_WORD = re.compile(r"[a-z0-9]+")
_RE_TEXT_WORD = re.compile(r"[A-Za-z0-9][\w'-]*")


def tokenize(text: str) -> list[str]:
    return [t for t in _RE_WORD.findall(text.lower())
            if t not in STOP_WORDS]


def raw_tokens(text: str) -> list[str]:
    return _RE_WORD.findall(text.lower())


def normalize_query(query: str) -> str:
    cleaned = " ".join(query.split()).strip().rstrip("?!. ")
    return cleaned


def strip_frame_tokens(text: str) -> str:
    tokens = _RE_TEXT_WORD.findall(text)
    kept = [t for t in tokens if t.lower() not in FRAME_TOKENS]
    if not kept:
        return text
    return " ".join(kept)


def content_coverage_query(query: str) -> str:
    return normalize_query(strip_frame_tokens(query))


def as_of_coverage_query(query: str) -> str:
    if "as of" not in query.lower():
        return query
    text = _HISTORICAL_AS_OF.sub(" ", query)
    text = _QUESTION_FRAME_RE.sub(" ", text)
    return normalize_query(text)


def strip_injection_phrases(query: str) -> str:
    cleaned = query
    matched = False
    for pat in _QUERY_OVERRIDE_PATTERNS:
        m = pat.search(cleaned)
        if m:
            matched = True
            cleaned = cleaned[:m.start()] + " " + cleaned[m.end():]
    if matched and ":" in cleaned:
        cleaned = cleaned.rsplit(":", 1)[-1]
    return normalize_query(cleaned)


def quarantine_source_text(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        if not s.strip():
            continue
        if any(p.search(s) for p in _SOURCE_DIRECTIVE_PATTERNS):
            continue
        kept.append(s.strip())
    return " ".join(kept)


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

_CHUNKS: list[dict] = []
for _line in (ROOT / "rag" / "gk_holdout_t21r6" / "chunks.jsonl") \
        .read_text(encoding="utf-8").splitlines():
    if _line.strip():
        _CHUNKS.append(json.loads(_line))
_CHUNKS_BY_ID = {c["chunk_id"]: c for c in _CHUNKS}

_SOURCES_BY_ID: dict[str, dict] = {}
for _line in (ROOT / "rag" / "gk_holdout_t21r6" / "sources.jsonl") \
        .read_text(encoding="utf-8").splitlines():
    if _line.strip():
        s = json.loads(_line)
        _SOURCES_BY_ID[s["source_id"]] = s

# BM25 index (mirror of index.py, data only)
_DOCS: list[dict[str, int]] = []
_DOC_LEN: list[int] = []
_INV: dict[str, dict[int, int]] = {}
for _pos, _c in enumerate(_CHUNKS):
    _toks = tokenize(_c["text"])
    _tf: dict[str, int] = {}
    for _t in _toks:
        _tf[_t] = _tf.get(_t, 0) + 1
    _DOCS.append(_tf)
    _DOC_LEN.append(len(_toks))
    for _t, _f in _tf.items():
        _INV.setdefault(_t, {})[_pos] = _f
_N_DOCS = len(_DOCS)
_AVG_LEN = (sum(_DOC_LEN) / _N_DOCS) if _N_DOCS else 0.0


def _idf(term: str) -> float:
    postings = _INV.get(term)
    if not postings:
        return 0.0
    df = len(postings)
    return math.log(1.0 + (_N_DOCS - df + 0.5) / (df + 0.5))


def _bm25_score(query_tokens: list[str], pos: int) -> float:
    total = 0.0
    dl = _DOC_LEN[pos] or 1
    norm = K1 * (1.0 - B + B * dl / (_AVG_LEN or 1.0))
    for term in query_tokens:
        freq = _DOCS[pos].get(term)
        if not freq:
            continue
        tf_norm = (freq * (K1 + 1.0)) / (freq + norm)
        total += _idf(term) * tf_norm
    return total


def bm25_search(query: str, top_k: int) -> list[tuple[str, float]]:
    toks = tokenize(normalize_query(query))
    candidates: set[int] = set()
    for term in toks:
        candidates.update(_INV.get(term, ()))
    scored = [(_bm25_score(toks, pos), _CHUNKS[pos]["chunk_id"])
              for pos in candidates]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(cid, s) for s, cid in scored[:max(0, top_k)]]


def _shingles(text: str, n: int = 4) -> frozenset:
    toks = tokenize(text)
    if len(toks) < n:
        return frozenset({" ".join(toks)}) if toks else frozenset()
    return frozenset(tuple(toks[i:i + n])
                     for i in range(len(toks) - n + 1))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return (len(a & b) / union) if union else 0.0


def rerank(ranked: list[tuple[str, float]], query: str,
           top_k: int) -> list[tuple[str, float]]:
    candidates = ranked[:max(top_k, top_k * 3)]
    q_terms = set(tokenize(normalize_query(query)))
    max_score = max((s for _, s in candidates), default=0.0) or 1.0
    out = []
    for chunk_id, score in candidates:
        chunk = _CHUNKS_BY_ID.get(chunk_id)
        if chunk is None:
            continue
        bonus = 0.02 * AUTHORITY_RANK.get(
            (chunk.get("metadata") or {}).get("authority_class",
                                              "UNKNOWN"), 0) / 10.0
        span_terms = set(tokenize(chunk["text"]))
        coverage = (len(q_terms & span_terms) / len(q_terms)) \
            if q_terms else 0.0
        out.append((chunk_id, coverage + 0.01 * (score / max_score)
                    + bonus))
    out.sort(key=lambda item: (-item[1], item[0]))
    return out


def dedup_chunks(ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
    kept: list[tuple[str, float]] = []
    kept_shingles: dict[str, list[frozenset]] = {}
    per_source: dict[str, int] = {}
    for chunk_id, score in ranked:
        chunk = _CHUNKS_BY_ID.get(chunk_id)
        if chunk is None:
            continue
        sid = chunk["source_id"]
        if per_source.get(sid, 0) >= MAX_PER_SOURCE:
            continue
        sh = _shingles(chunk["text"])
        dup = False
        for other in kept_shingles.get(sid, ()):
            if _jaccard(sh, other) >= JACCARD_THRESHOLD:
                dup = True
                break
        if dup:
            continue
        kept.append((chunk_id, score))
        kept_shingles.setdefault(sid, []).append(sh)
        per_source[sid] = per_source.get(sid, 0) + 1
    return kept


def select_window(deduped: list[tuple[str, float]],
                  top_k: int) -> list[tuple[str, float]]:
    if len(deduped) <= top_k:
        return list(deduped)
    window = list(deduped[:top_k])
    max_score = max(s for _, s in deduped) or 0.0
    window_sources = {_CHUNKS_BY_ID[c]["source_id"] for c, _ in window
                      if c in _CHUNKS_BY_ID}
    reserved: list[tuple[str, float]] = []
    seen_sources: set[str] = set()
    for chunk_id, score in deduped[top_k:]:
        chunk = _CHUNKS_BY_ID.get(chunk_id)
        if chunk is None:
            continue
        sid = chunk["source_id"]
        if sid in window_sources or sid in seen_sources:
            continue
        seen_sources.add(sid)
        if score >= WINDOW_RESERVE_FRACTION * max_score:
            reserved.append((chunk_id, score))
    if not reserved:
        return window
    for chunk_id, score in reserved:
        source_counts: dict[str, int] = {}
        for cid, _s in window:
            ch = _CHUNKS_BY_ID.get(cid)
            if ch is not None:
                source_counts[ch["source_id"]] = \
                    source_counts.get(ch["source_id"], 0) + 1
        droppable = [i for i, (cid, _s) in enumerate(window)
                     if _CHUNKS_BY_ID.get(cid) is not None
                     and source_counts.get(
                         _CHUNKS_BY_ID[cid]["source_id"], 0) > 1]
        if not droppable:
            droppable = list(range(len(window)))
        drop_i = min(droppable,
                     key=lambda i: (window[i][1], window[i][0]))
        window[drop_i] = (chunk_id, score)
    window.sort(key=lambda item: (-item[1], item[0]))
    return window


def final_window(query: str, top_k: int = TOP_K) -> list[str]:
    effective = strip_injection_phrases(query)
    ranked = bm25_search(effective, top_k * 3)
    rr = rerank(ranked, effective, top_k)
    dd = dedup_chunks(rr)
    return [cid for cid, _ in select_window(dd, top_k)]


def naive_window(query: str, top_k: int = TOP_K) -> list[str]:
    effective = strip_injection_phrases(query)
    ranked = bm25_search(effective, top_k * 3)
    rr = rerank(ranked, effective, top_k)
    return [cid for cid, _ in dedup_chunks(rr)[:top_k]]


def coverage_ratio(query: str, spans: list[str]) -> float:
    q_terms = [t for t in tokenize(normalize_query(query)) if len(t) > 3]
    if not q_terms:
        return 0.0
    span_terms: set[str] = set()
    for span in spans:
        span_terms.update(tokenize(span))
    return sum(1 for t in q_terms if t in span_terms) / len(q_terms)


def spoof_flagged(query: str) -> bool:
    fake_sources = [m for m in _SOURCE_ID_RE.findall(query)
                    if f"gk-{m}" not in _SOURCES_BY_ID]
    fake_chunks = [m for m in _CHUNK_ID_RE.findall(query)
                   if m not in _CHUNKS_BY_ID]
    fake_citations = _CITATION_ID_RE.findall(query)
    cue = bool(_PROVENANCE_CLAIM_CUES.search(query))
    return bool(fake_sources or fake_chunks
                or (fake_citations and cue))


# ---------------------------------------------------------------------------
# Conflict chunk helpers
# ---------------------------------------------------------------------------

_SUFFIX_MARKERS = (" (record)", " (restated)", " (conflict a)",
                   " (conflict b)", " (alt)", " (draft)")


def _is_conflict_chunk(c: dict) -> bool:
    return any(m in c["section"] for m in _SUFFIX_MARKERS)


def _chunks_for(entity: str, attr: str) -> list[dict]:
    return [c for c in _CHUNKS
            if (c.get("metadata") or {}).get("fact_entity") == entity
            and (c.get("metadata") or {}).get("fact_attribute") == attr]


def _entity_tokens_in_query(query: str, entity: str) -> bool:
    q = set(raw_tokens(query))
    toks = [t for t in raw_tokens(entity)]
    return bool(toks) and all(t in q for t in toks)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

BRIDGE_CATEGORIES = {"two_hop_bridge", "art_to_biography",
                     "technology_to_biography", "literature_to_biography",
                     "civic_writings_to_biography"}


def main() -> int:
    failures: list[str] = []
    report: dict = {"checks": {}, "failures": []}

    rows: list[dict] = []
    for path in sorted(SUITES_DIR.glob("*/holdout.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    report["rows"] = len(rows)

    # window caches
    window_cache: dict[str, list[str]] = {}
    naive_cache: dict[str, list[str]] = {}

    def _window(query: str) -> list[str]:
        if query not in window_cache:
            window_cache[query] = final_window(query)
        return window_cache[query]

    def _naive(query: str) -> list[str]:
        if query not in naive_cache:
            naive_cache[query] = naive_window(query)
        return naive_cache[query]

    # ---- 1. gold chunk in window -----------------------------------------
    win_miss = []
    for row in rows:
        gold = row["gold"]
        gcid = gold.get("gold_chunk_id")
        if not gcid:
            continue
        win = _window(row["request"]["query"])
        if gcid not in win:
            win_miss.append((row["case_id"], row["request"]["query"]))
    report["checks"]["gold_in_window"] = {
        "checked": sum(1 for r in rows if r["gold"].get("gold_chunk_id")),
        "misses": len(win_miss)}
    failures.extend(f"gold_in_window {cid}: {q!r}"
                    for cid, q in win_miss[:40])

    # ---- 2/3. conflict windows + winner-not-rank-1 ------------------------
    stress_total = 0
    stress_winner_not_rank1 = 0
    conflict_win_miss = []
    near_dup_companion_miss = []
    for row in rows:
        cat = row["category"]
        gold = row["gold"]
        gcid = gold.get("gold_chunk_id")
        q = row["request"]["query"]
        if cat in ("authority_resolvable_conflict",
                   "freshness_resolvable_conflict",
                   "near_duplicate_false_conflict"):
            # unresolved rows carry no gold chunk; their pair co-presence
            # is verified by the dedicated check below. Near-dup
            # companion co-presence is report-only: corroboration is not
            # a floored metric and the gold chunk is always required.
            if not gcid:
                conflict_win_miss.append((row["case_id"], "no gold chunk"))
                continue
            gold_c = _CHUNKS_BY_ID[gcid]
            entity = gold_c["metadata"]["fact_entity"]
            attr = gold_c["metadata"]["fact_attribute"]
            others = [c["chunk_id"] for c in _chunks_for(entity, attr)
                      if c["chunk_id"] != gcid]
            win = _window(q)
            for ocid in others:
                if ocid not in win:
                    if cat == "near_duplicate_false_conflict":
                        near_dup_companion_miss.append(row["case_id"])
                    else:
                        conflict_win_miss.append(
                            (row["case_id"], f"companion {ocid} not in window"))
        if cat == "unresolved_conflict":
            # both conflict chunks must be in the window (gold has no
            # chunk id; derive from entity via the query-side town)
            # entity = the town name: last token group in the query
            # handled via companion check above using gold chunk when
            # present; unresolved rows carry no gold chunk -> use the
            # conflict pair found by matching query entity tokens.
            pass
        low = q.lower()
        if "antiquarian notes" in low or "officeholder roll" in low:
            stress_total += 1
            win = _window(q)
            if cat == "unresolved_conflict":
                # pair chunks for the queried town; stress = a non-pair
                # chunk (the mayor snapshot) occupies rank 1
                pair_ids = None
                for c in _CHUNKS:
                    m = c.get("metadata") or {}
                    if m.get("fact_attribute") == "established year" \
                            and _is_conflict_chunk(c) \
                            and _entity_tokens_in_query(
                                q, m["fact_entity"]):
                        pair_ids = {
                            o["chunk_id"]
                            for o in _chunks_for(m["fact_entity"],
                                                 "established year")}
                        break
                if pair_ids and win and win[0] not in pair_ids:
                    stress_winner_not_rank1 += 1
            else:
                assert gcid, row["case_id"]
                if gcid in win and win.index(gcid) + 1 > 1:
                    stress_winner_not_rank1 += 1
    report["checks"]["conflict_windows"] = {
        "misses": len(conflict_win_miss)}
    report["checks"]["near_dup_companion_report_only"] = {
        "misses": len(near_dup_companion_miss)}
    report["checks"]["winner_not_rank1"] = {
        "stress_rows": stress_total,
        "winner_not_rank1": stress_winner_not_rank1}
    failures.extend(f"conflict_window {cid}: {msg}"
                    for cid, msg in conflict_win_miss[:40])
    if stress_winner_not_rank1 < 80:
        failures.append(
            f"winner_not_rank1 {stress_winner_not_rank1} < 80")

    # unresolved rows: derive conflict entity from corpus metadata by
    # matching the query tokens to fact_entity of unresolved conflict
    # chunks; verify both chunks present.
    unresolved_miss = []
    for row in rows:
        if row["category"] != "unresolved_conflict":
            continue
        q = row["request"]["query"]
        win = _window(q)
        win_pairs = [(c["metadata"]["fact_entity"],
                      c["metadata"]["fact_attribute"])
                     for c in (_CHUNKS_BY_ID[i] for i in win)
                     if c.get("metadata", {}).get("fact_entity")]
        # find the (entity, attr) probed: the town with both conflict
        # chunks whose name appears in the query
        best = None
        for c in _CHUNKS:
            m = c.get("metadata") or {}
            if not _is_conflict_chunk(c) or \
                    m.get("fact_attribute") != "established year":
                continue
            ent = m["fact_entity"]
            if _entity_tokens_in_query(q, ent):
                pair = (ent, "established year")
                n_pair = sum(1 for p in win_pairs if p == pair)
                if n_pair >= 2:
                    best = pair
                    break
        if best is None:
            unresolved_miss.append(row["case_id"])
    report["checks"]["unresolved_pair_in_window"] = {
        "misses": len(unresolved_miss)}
    if unresolved_miss:
        failures.append(
            f"unresolved_pair_in_window misses: "
            f"{len(unresolved_miss)} e.g. {unresolved_miss[:5]}")

    # ---- 4. naive-window domination ---------------------------------------
    domination = 0
    dom_total = 0
    for row in rows:
        req = row["gold"].get("required_sources") or []
        if not req:
            continue
        dom_total += 1
        naive = _naive(row["request"]["query"])
        naive_sources = {_CHUNKS_BY_ID[c]["source_id"] for c in naive
                         if c in _CHUNKS_BY_ID}
        if any(s not in naive_sources for s in req):
            domination += 1
    report["checks"]["naive_domination"] = {
        "multi_source_rows": dom_total, "dominated": domination}
    if domination < 100:
        failures.append(f"naive_domination {domination} < 100")

    # ---- 5. coverage gate proxy -------------------------------------------
    cov_fail = []
    for row in rows:
        gold = row["gold"]
        if gold["expect_status"] != "ANSWER":
            continue
        gcid = gold.get("gold_chunk_id")
        if not gcid:
            continue
        q = row["request"]["query"]
        spans = [quarantine_source_text(_CHUNKS_BY_ID[gcid]["text"])]
        if row["category"] in BRIDGE_CATEGORIES:
            creator = _CHUNKS_BY_ID[gcid]["metadata"]["fact_value"]
            bp = [c for c in _chunks_for(creator, "birthplace")
                  if not _is_conflict_chunk(c)]
            if bp:
                spans.append(quarantine_source_text(bp[0]["text"]))
        if row["category"] == "near_duplicate_false_conflict":
            # corroborators join the cited spans at runtime; include the
            # same-value restated companion (any source) when present
            m = _CHUNKS_BY_ID[gcid]["metadata"]
            for comp in _chunks_for(m["fact_entity"], m["fact_attribute"]):
                if comp["chunk_id"] != gcid:
                    spans.append(quarantine_source_text(comp["text"]))
        base = as_of_coverage_query(strip_injection_phrases(q))
        content = content_coverage_query(base)
        cov = max(coverage_ratio(base, spans),
                  coverage_ratio(content, spans))
        if cov < MIN_COVERAGE:
            cov_fail.append((row["case_id"], q, round(cov, 3)))
    report["checks"]["coverage_gate"] = {"failures": len(cov_fail)}
    failures.extend(f"coverage {cid} {cov}: {q!r}"
                    for cid, q, cov in cov_fail[:40])

    # ---- 6. hop-2 bridge window --------------------------------------------
    hop2_fail = []
    for row in rows:
        if row["category"] not in BRIDGE_CATEGORIES:
            continue
        gcid = row["gold"]["gold_chunk_id"]
        creator = _CHUNKS_BY_ID[gcid]["metadata"]["fact_value"]
        hop2_query = f"{creator} born birthplace"
        ranked = bm25_search(hop2_query, 3 * 3)
        rr = rerank(ranked, hop2_query, 3)
        win = [cid for cid, _ in select_window(dedup_chunks(rr), 3)]
        bp = [c for c in _chunks_for(creator, "birthplace")
              if not _is_conflict_chunk(c)]
        if not bp or bp[0]["chunk_id"] not in win:
            hop2_fail.append((row["case_id"], creator))
    report["checks"]["hop2_bridge"] = {"failures": len(hop2_fail)}
    failures.extend(f"hop2 {cid}: {creator!r}" for cid, creator
                    in hop2_fail[:20])

    # ---- 7. injection exposure quarantine ----------------------------------
    expo_fail = []
    for row in rows:
        if row["category"] != "source_directive_exposure":
            continue
        gcid = row["gold"]["gold_chunk_id"]
        text = _CHUNKS_BY_ID[gcid]["text"]
        synth = quarantine_source_text(text)
        value = (_CHUNKS_BY_ID[gcid].get("metadata") or {}) \
            .get("fact_value") or ""
        safe_tokens = set(tokenize(value))
        if not synth or not (safe_tokens
                             & set(tokenize(synth))):
            expo_fail.append((row["case_id"], gcid))
    report["checks"]["exposure_safe_fact"] = {"failures": len(expo_fail)}
    failures.extend(f"exposure {cid}: {gcid}" for cid, gcid
                    in expo_fail[:20])

    # ---- 8. spoof flags ------------------------------------------------------
    spoof_miss = []
    for row in rows:
        if row["category"] != "citation_spoof":
            continue
        if not spoof_flagged(row["request"]["query"]):
            spoof_miss.append(row["case_id"])
    report["checks"]["spoof_flagged"] = {"misses": len(spoof_miss)}
    if spoof_miss:
        failures.append(f"spoof_flagged misses: {spoof_miss[:5]}")

    # ---- 9. conflict negatives ----------------------------------------------
    # A companion chunk counts as a conflict only when it asserts a
    # DIFFERENT value for the same (entity, attribute); same-value
    # restatements are corroboration, not conflict.
    neg_fail = []
    for row in rows:
        if row["category"] != "unrelated_conflict_negative":
            continue
        gcid = row["gold"]["gold_chunk_id"]
        m = _CHUNKS_BY_ID[gcid]["metadata"]
        gold_value = (m.get("fact_value") or "").strip().lower()
        companions = [c for c in _chunks_for(m["fact_entity"],
                                             m["fact_attribute"])
                      if _is_conflict_chunk(c)
                      and (c.get("metadata") or {})
                      .get("fact_value", "").strip().lower() != gold_value]
        if companions:
            neg_fail.append((row["case_id"], m["fact_entity"]))
    report["checks"]["negative_clean"] = {"failures": len(neg_fail)}
    failures.extend(f"negative_not_clean {cid}: {ent}" for cid, ent
                    in neg_fail[:10])

    # ---- 10. absent probe entities ------------------------------------------
    # The probe entity must appear in NO corpus chunk text and in NO chunk
    # metadata (near-miss distractor names like "Typewriter Yard" are
    # different entities by design; only exact-phrase absence is required).
    # These are the T21R6 ABSENT_ENTITIES, mechanically verified absent
    # from every prior corpus and prior query set at build time
    # (scripts/t21r6_build_suites.py :: _verify_absent_probe_entities).
    absent_fail = []
    probe_entities = ["the dynamo", "the typewriter",
                      "the stethoscope", "the gyroscope", "the periscope"]
    for probe in probe_entities:
        for c in _CHUNKS:
            if probe in c["text"].lower() or probe == (c.get("metadata")
                                                       or {}).get(
                    "fact_entity"):
                absent_fail.append((probe, c["chunk_id"]))
    report["checks"]["absent_tokens_absent"] = {
        "failures": len(absent_fail)}
    failures.extend(f"absent_token_hit {probe}: {cid}"
                    for probe, cid in absent_fail[:10])

    report["failures"] = failures
    report["status"] = "PASS" if not failures else "FAIL"
    out = ROOT / "evaluations" / "t21r6" / "static_gold_audit.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items()
                      if k != "failures"}, indent=2))
    if failures:
        print("FAILURES:")
        for f in failures[:60]:
            print(" -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())