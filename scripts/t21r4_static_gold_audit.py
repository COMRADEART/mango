"""T21R4.13 — static gold audit against a LOCAL reimplementation of the
frozen retrieval arithmetic.

This script verifies, BEFORE HOLDOUT_FROZEN and with ZERO runtime
exposure, that the T21R4 gold rows are satisfiable by the frozen Mango
retrieval pipeline arithmetic:

  tokenize (a-z0-9, stoplist) -> BM25 Okapi (k1=1.2, b=0.75)
  -> search top (top_k*3)=24 by (score desc, chunk_id asc)
  -> rerank (coverage 1.0 + 0.01*bm25/max + 0.02*authority/10,
     over top max(8, 24) candidates, sorted (-score, chunk_id))
  -> dedup (4-gram Jaccard >= 0.85 vs kept same-source chunk,
     then cap MAX_PER_SOURCE=3) -> final window = deduped[:8]

The arithmetic is REIMPLEMENTED here as pure data functions (the frozen
constants are copied, not imported); no sciencemath module is imported
or executed (enforced by tests/test_t21r4_blind_holdout_contract.py).

Checks:
  1. every retrieval-mode gold chunk appears in the deduped top-8 window
     (rank recorded; floors recall@5/recall@10 need ranks <= 5 / <= 10)
  2. every answer-mode gold chunk (singlehop/citation/temporal/
     adversarial-override/negatives/restatements) appears in the window
  3. every genuine-conflict gold row (unresolved/authority/freshness)
     has BOTH conflict-pair chunks in the window
  4. >= 80 genuine-conflict rows have the first-ranked pair member at
     rank > 1 ("not-rank-1 relevant conflict evidence") — the T21R3
     failure mechanism that the T21R4 repair targets

Writes evaluations/t21r4/static_gold_audit.json.

Usage: python scripts/t21r4_static_gold_audit.py
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / "rag" / "gk_holdout_t21r4"
SUITES_DIR = ROOT / "evaluations" / "t21r4" / "suites"
OUT = ROOT / "evaluations" / "t21r4" / "static_gold_audit.json"

TOP_K = 8
CANDIDATE_MULTIPLIER = 3
K1 = 1.2
B = 0.75
JACCARD_THRESHOLD = 0.85
MAX_PER_SOURCE = 3
COVERAGE_WEIGHT = 1.0
RERANK_TIEBREAK_WEIGHT = 0.01
AUTHORITY_BONUS = 0.02
AUTHORITY_RANK = {
    "PRIMARY_REFERENCE": 6,
    "ENCYCLOPEDIC": 5,
    "ACADEMIC_REFERENCE": 4,
    "GOVERNMENT_PUBLICATION": 4,
    "INSTITUTIONAL": 3,
    "GENERAL_REFERENCE": 2,
    "UNKNOWN": 0,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset({
    "a", "an", "the", "of", "to", "in", "and", "or", "is", "are", "was",
    "were", "be", "been", "it", "its", "as", "at", "by", "for", "on",
    "with", "that", "this", "from", "which", "who", "whom", "what",
    "when", "where", "how", "why", "did", "does", "do", "have", "has",
    "had", "many", "much", "there", "their", "about", "into", "also",
})


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def normalize_query(query: str) -> str:
    return " ".join(query.split()).strip().rstrip("?!. ")


def _slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-") or "section"


def _shingles(text: str, n: int = 4) -> frozenset:
    toks = tokenize(text)
    if len(toks) < n:
        return frozenset({" ".join(toks)}) if toks else frozenset()
    return frozenset(tuple(toks[i:i + n])
                     for i in range(len(toks) - n + 1))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Local corpus index (pure data)
# ---------------------------------------------------------------------------

_CHUNKS: list[dict] = []
for _line in (HOLDOUT / "chunks.jsonl").read_text(
        encoding="utf-8").splitlines():
    if _line.strip():
        _CHUNKS.append(json.loads(_line))
BY_ID = {c["chunk_id"]: c for c in _CHUNKS}

_DOCS: list[dict[str, int]] = []
_DOC_LEN: list[int] = []
_INVERTED: dict[str, dict[int, int]] = {}
for _pos, _c in enumerate(_CHUNKS):
    _toks = tokenize(_c["text"])
    _tf: dict[str, int] = {}
    for _t in _toks:
        _tf[_t] = _tf.get(_t, 0) + 1
    _DOCS.append(_tf)
    _DOC_LEN.append(len(_toks))
    for _term, _freq in _tf.items():
        _INVERTED.setdefault(_term, {})[_pos] = _freq
N_DOCS = len(_DOCS)
AVG_LEN = (sum(_DOC_LEN) / N_DOCS) if N_DOCS else 0.0


def _idf(term: str) -> float:
    postings = _INVERTED.get(term)
    if not postings:
        return 0.0
    df = len(postings)
    return math.log(1.0 + (N_DOCS - df + 0.5) / (df + 0.5))


def _score(query_tokens: list[str], pos: int) -> float:
    total = 0.0
    dl = _DOC_LEN[pos] or 1
    norm = K1 * (1.0 - B + B * dl / (AVG_LEN or 1.0))
    for term in query_tokens:
        freq = _DOCS[pos].get(term)
        if not freq:
            continue
        tf_norm = (freq * (K1 + 1.0)) / (freq + norm)
        total += _idf(term) * tf_norm
    return total


def _search(query: str, top_k: int) -> list[tuple[str, float]]:
    toks = tokenize(normalize_query(query))
    candidates: set[int] = set()
    for term in toks:
        candidates.update(_INVERTED.get(term, ()))
    scored = [(_score(toks, pos), _CHUNKS[pos]["chunk_id"])
              for pos in candidates]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(cid, s) for s, cid in scored[:max(0, top_k)]]


def _rerank(ranked: list[tuple[str, float]], query: str) \
        -> list[tuple[str, float]]:
    candidates = ranked[:max(TOP_K, TOP_K * CANDIDATE_MULTIPLIER)]
    q_terms = set(tokenize(normalize_query(query)))
    max_score = max((s for _, s in candidates), default=0.0) or 1.0
    out: list[tuple[str, float]] = []
    for chunk_id, score in candidates:
        chunk = BY_ID[chunk_id]
        meta = chunk["metadata"] or {}
        bonus = AUTHORITY_BONUS * AUTHORITY_RANK.get(
            meta.get("authority_class", "UNKNOWN"), 0) / 10.0
        span_terms = set(tokenize(chunk["text"]))
        coverage = (len(q_terms & span_terms) / len(q_terms)) if q_terms \
            else 0.0
        score2 = (COVERAGE_WEIGHT * coverage
                  + RERANK_TIEBREAK_WEIGHT * (score / max_score) + bonus)
        out.append((chunk_id, score2))
    out.sort(key=lambda item: (-item[1], item[0]))
    return out


def _dedup(ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
    kept: list[tuple[str, float]] = []
    kept_shingles: dict[str, list[frozenset]] = {}
    per_source: dict[str, int] = {}
    for chunk_id, score in ranked:
        chunk = BY_ID[chunk_id]
        sid = chunk["source_id"]
        if per_source.get(sid, 0) >= MAX_PER_SOURCE:
            continue
        sh = _shingles(chunk["text"])
        duplicate = any(_jaccard(sh, other) >= JACCARD_THRESHOLD
                        for other in kept_shingles.get(sid, ()))
        if duplicate:
            continue
        kept.append((chunk_id, score))
        kept_shingles.setdefault(sid, []).append(sh)
        per_source[sid] = per_source.get(sid, 0) + 1
    return kept


def window(query: str) -> list[str]:
    """The frozen final retrieval window (deduped top-8, in order)."""
    ranked = _search(query, TOP_K * CANDIDATE_MULTIPLIER)
    reranked = _rerank(ranked, query)
    return [cid for cid, _s in _dedup(reranked)[:TOP_K]]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

_PAIR_MARKERS = {
    "unresolved_conflict": (" (conflict a)", " (conflict b)"),
    "authority_resolvable_conflict": ("", " (alt)"),
    "freshness_resolvable_conflict": ("", " (draft)"),
}


def _pair_chunks(entity: str, attr: str, kind: str) -> list[str]:
    markers = _PAIR_MARKERS[kind]
    ids = []
    for marker in markers:
        if marker == "":
            matches = [c for c in _CHUNKS
                       if c["metadata"].get("fact_entity") == entity
                       and c["metadata"].get("fact_attribute") == attr
                       and not any(m in c["section"] for m in (
                           " (record)", " (restated)", " (conflict a)",
                           " (conflict b)", " (alt)", " (draft)"))]
            assert len(matches) == 1, (entity, attr, len(matches))
            ids.append(matches[0]["chunk_id"])
        else:
            matches = [c for c in _CHUNKS
                       if c["metadata"].get("fact_entity") == entity
                       and c["metadata"].get("fact_attribute") == attr
                       and c["section"].endswith(marker)]
            assert len(matches) == 1, (entity, attr, marker, len(matches))
            ids.append(matches[0]["chunk_id"])
    return ids


def main() -> int:
    suite_dirs = sorted(p for p in SUITES_DIR.iterdir() if p.is_dir())
    per_suite: dict[str, dict] = {}
    failures: list[str] = []
    rank_hist: dict[int, int] = {}
    conflict_rows_checked = 0
    conflict_rows_both_in_window = 0
    not_rank1 = 0

    for suite_dir in suite_dirs:
        name = suite_dir.name
        rows = [json.loads(line) for line in
                (suite_dir / "holdout.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()]
        stats = {"rows": len(rows), "gold_in_window": 0,
                 "gold_rank_max": 0, "gold_ranks_gt5": 0,
                 "conflict_rows": 0, "conflict_pairs_in_window": 0,
                 "not_rank1": 0}
        for row in rows:
            gold = row["gold"]
            query = row["request"]["query"]
            win = window(query)
            gcid = gold.get("gold_chunk_id")
            if gcid is not None:
                if gcid in win:
                    stats["gold_in_window"] += 1
                    rank = win.index(gcid) + 1
                    stats["gold_rank_max"] = max(stats["gold_rank_max"],
                                                 rank)
                    rank_hist[rank] = rank_hist.get(rank, 0) + 1
                    if rank > 5:
                        stats["gold_ranks_gt5"] += 1
                else:
                    failures.append(
                        f"{name}/{row['case_id']}: gold chunk not in "
                        f"window (query={query!r})")
            if row["category"] in _PAIR_MARKERS:
                conflict_rows_checked += 1
                stats["conflict_rows"] += 1
                # Resolve the conflict pair by re-deriving the entity
                # from the gold row: unresolved rows carry no gold chunk,
                # so match by query entity token against the world.
                pairs = _resolve_pair(row, name)
                if pairs is None:
                    failures.append(
                        f"{name}/{row['case_id']}: could not resolve "
                        f"conflict pair")
                    continue
                in_win = [cid for cid in pairs if cid in win]
                if len(in_win) == len(pairs):
                    conflict_rows_both_in_window += 1
                    stats["conflict_pairs_in_window"] += 1
                    first_rank = min(win.index(cid) for cid in in_win) + 1
                    if first_rank > 1:
                        not_rank1 += 1
                        stats["not_rank1"] += 1
                else:
                    failures.append(
                        f"{name}/{row['case_id']}: conflict pair missing "
                        f"from window ({len(in_win)}/{len(pairs)}); "
                        f"query={query!r}")
        per_suite[name] = stats

    result = {
        "audit": "t21r4-static-gold-audit-v1",
        "method": "local reimplementation of frozen retrieval arithmetic "
                  "(no runtime import, no runtime execution)",
        "top_k": TOP_K,
        "candidate_multiplier": CANDIDATE_MULTIPLIER,
        "per_suite": per_suite,
        "gold_rank_histogram": {str(k): v for k, v in sorted(
            rank_hist.items())},
        "conflict_rows_checked": conflict_rows_checked,
        "conflict_pairs_in_window": conflict_rows_both_in_window,
        "not_rank1_rows": not_rank1,
        "not_rank1_minimum": 80,
        "not_rank1_pass": not_rank1 >= 80,
        "n_failures": len(failures),
        "failures": failures[:40],
        "pass": not failures and not_rank1 >= 80,
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items()
                      if k != "per_suite"}, indent=2))
    for name, stats in per_suite.items():
        print(f"  {name}: {json.dumps(stats)}")
    return 0 if result["pass"] else 1


def _resolve_pair(row: dict, suite_name: str) -> list[str] | None:
    """Re-derive the two conflict-pair chunk ids for a gold conflict row
    from the world conflict table (data only)."""
    category = row["category"]
    query = row["request"]["query"]
    qtoks = set(tokenize(query))
    # entity = the world entity whose name tokens are all in the query
    import t21r4_world as W
    candidates = []
    if category == "unresolved_conflict":
        conflicts = [r for r in W.CONFLICTS
                     if r["class"] == "EQUAL_AUTHORITY_UNRESOLVED"]
        attr = "established year"
    elif category == "authority_resolvable_conflict":
        conflicts = [r for r in W.CONFLICTS
                     if r["class"] == "AUTHORITY_RESOLVABLE"]
        attr = "established year"
    else:
        conflicts = [r for r in W.CONFLICTS
                     if r["class"] == "FRESHNESS_RESOLVABLE"]
        attr = "introduction year"
    for conflict in conflicts:
        etoks = set(tokenize(conflict["entity"]))
        if etoks and etoks <= qtoks:
            candidates.append(conflict["entity"])
    if len(candidates) != 1:
        return None
    return _pair_chunks(candidates[0], attr, category)


if __name__ == "__main__":
    raise SystemExit(main())