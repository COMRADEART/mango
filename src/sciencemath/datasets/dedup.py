"""Deduplication: exact, normalized-text, and near-duplicate (character
n-gram Jaccard via an inverted index) removal.

One union-find pass collapses all duplicate relations (exact question,
normalized fingerprint, near-duplicate shingles) into single clusters; one
representative per cluster is kept, preferring records that carry solutions.
Deterministic for a fixed input order.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sciencemath.datasets.normalize import clean_text, text_fingerprint


def shingles(text: str, n: int = 4) -> frozenset[str]:
    s = " ".join(text_fingerprint(text).split())
    if len(s) < n:
        return frozenset({s}) if s else frozenset()
    return frozenset(s[i:i + n] for i in range(len(s) - n + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / (len(a) + len(b) - inter)


@dataclass
class DedupResult:
    kept: list[dict]
    duplicates: list[dict]           # {id, source, duplicate_of, reason}
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def n_kept(self) -> int:
        return len(self.kept)


def _prefer(existing: dict, candidate: dict) -> bool:
    """True when candidate should replace the current representative."""
    def score(d: dict) -> int:
        return bool(d.get("solution")) + bool(d.get("explanation"))
    return score(candidate) > score(existing)


def deduplicate(records: list[dict], *,
                ngram_size: int = 4,
                near_threshold: float = 0.85,
                near_enabled: bool = True,
                max_scan_pairs: int = 2_000_000) -> DedupResult:
    n = len(records)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    counts = {"exact": 0, "normalized": 0, "near_duplicate": 0}
    duplicates: list[dict] = []
    dup_reason: list[str] = ["" for _ in range(n)]   # edge reason per record

    # exact + normalized-text relations (streaming; first-wins parent links)
    by_exact: dict[str, int] = {}
    by_fingerprint: dict[str, int] = {}
    for i, rec in enumerate(records):
        q_raw = " ".join(clean_text(str(rec.get("question", "")))[0].split()).lower()
        fp = text_fingerprint(str(rec.get("question", "")))

        prev = by_exact.get(q_raw)
        if prev is not None:
            parent[i] = prev
            dup_reason[i] = "exact_question"
            continue
        by_exact[q_raw] = i

        prev = by_fingerprint.get(fp)
        if prev is not None:
            parent[i] = prev
            dup_reason[i] = "normalized_text"
            continue
        by_fingerprint[fp] = i

    # near-duplicate relations via inverted shingle index
    if near_enabled and n > 1:
        sh = [shingles(str(r.get("question", "")), ngram_size) for r in records]
        inv: dict[str, list[int]] = defaultdict(list)
        for i, s in enumerate(sh):
            for g in s:
                inv[g].append(i)

        pair_count = 0
        for g, postings in inv.items():
            if pair_count > max_scan_pairs:
                break
            if len(postings) < 2 or len(postings) > 1000:
                continue
            for x in range(len(postings)):
                for y in range(x + 1, len(postings)):
                    pair_count += 1
                    i, j = postings[x], postings[y]
                    if find(i) == find(j):
                        continue
                    a, b = sh[i], sh[j]
                    inter = len(a & b)
                    if inter < near_threshold * min(len(a), len(b)):
                        continue
                    if inter / (len(a) + len(b) - inter) >= near_threshold:
                        union(i, j)
                        if not dup_reason[j]:
                            dup_reason[j] = "near_duplicate"

    # pick one representative per cluster; demote the loser of _prefer
    representative: dict[int, dict] = {}
    for i, rec in enumerate(records):
        root = find(i)
        if root not in representative:
            representative[root] = rec
            continue
        rep = representative[root]
        if _prefer(rep, rec):
            representative[root] = rec
            demoted, keeper = rep, rec
        else:
            demoted, keeper = rec, rep
        reason = dup_reason[i] or "near_duplicate"
        # counts use the short public keys: exact | normalized | near_duplicate
        count_key = {"exact_question": "exact",
                     "normalized_text": "normalized",
                     "near_duplicate": "near_duplicate"}[reason]
        counts[count_key] = counts.get(count_key, 0) + 1
        duplicates.append({"id": demoted.get("id"), "source": demoted.get("source"),
                           "duplicate_of": keeper.get("id"),
                           "reason": reason})

    kept = [r for r in records if id(r) in {id(v) for v in representative.values()}]
    return DedupResult(kept=kept, duplicates=duplicates, counts=counts)