"""Train/evaluation contamination (leakage) detection.

Two checks, per engineering rules:
  direct leakage  - identical normalized fingerprint of the question text
  near leakage    - character n-gram Jaccard similarity above threshold

check_splits() is run by build_splits.py after every split generation and
validation MUST FAIL when direct leakage is found (fail_on_direct=True).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sciencemath.datasets.dedup import jaccard, shingles
from sciencemath.datasets.normalize import text_fingerprint


@dataclass
class LeakagePair:
    train_id: str
    eval_id: str
    eval_split: str
    similarity: float
    kind: str                     # "direct" | "near"
    train_source: str
    eval_source: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class LeakageResult:
    pairs: list[LeakagePair] = field(default_factory=list)

    @property
    def direct(self) -> list[LeakagePair]:
        return [p for p in self.pairs if p.kind == "direct"]

    @property
    def near(self) -> list[LeakagePair]:
        return [p for p in self.pairs if p.kind == "near"]

    @property
    def has_direct(self) -> bool:
        return bool(self.direct)

    def to_dict(self) -> dict:
        return {"direct": [p.to_dict() for p in self.direct],
                "near": [p.to_dict() for p in self.near]}


def find_direct_leakage(train: list[dict], eval_sets: dict[str, list[dict]]) -> LeakageResult:
    """Exact normalized-question-text matches between train and eval splits."""
    train_fp: dict[str, dict] = {}
    for rec in train:
        train_fp.setdefault(text_fingerprint(str(rec.get("question", ""))), rec)

    result = LeakageResult()
    for split_name, recs in eval_sets.items():
        seen_in_eval: set[str] = set()
        for rec in recs:
            fp = text_fingerprint(str(rec.get("question", "")))
            if fp in seen_in_eval:
                continue
            seen_in_eval.add(fp)
            if fp in train_fp:
                t = train_fp[fp]
                result.pairs.append(LeakagePair(
                    train_id=t.get("id", "?"), eval_id=rec.get("id", "?"),
                    eval_split=split_name, similarity=1.0, kind="direct",
                    train_source=t.get("source", "?"), eval_source=rec.get("source", "?")))
    return result


def find_near_leakage(train: list[dict], eval_sets: dict[str, list[dict]],
                      threshold: float = 0.90, ngram_size: int = 4,
                      max_pairs: int = 500_000) -> LeakageResult:
    """Approximate contamination check via shingle Jaccard with an inverted
    index over train shingles (train is usually the bigger side)."""
    sh = [shingles(str(r.get("question", "")), ngram_size) for r in train]
    inv: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(sh):
        for g in s:
            inv[g].append(i)

    result = LeakageResult()
    examined = 0
    for split_name, recs in eval_sets.items():
        for rec in recs:
            if examined > max_pairs:
                break
            q = shingles(str(rec.get("question", "")), ngram_size)
            if not q:
                continue
            # only candidates sharing enough rare shingles: count postings
            cand_counts: defaultdict[int, int] = defaultdict(int)
            for g in q:
                postings = inv.get(g)
                if postings is None or len(postings) > 300:   # too common to be informative
                    continue
                for i in postings:
                    cand_counts[i] += 1
            best_i, best_sim = -1, 0.0
            for i, shared in cand_counts.items():
                examined += 1
                if shared < threshold * min(len(q), len(sh[i])):
                    continue
                sim = jaccard(q, sh[i])
                if sim > best_sim:
                    best_i, best_sim = i, sim
            if best_i >= 0 and best_sim >= threshold:
                t = train[best_i]
                result.pairs.append(LeakagePair(
                    train_id=t.get("id", "?"), eval_id=rec.get("id", "?"),
                    eval_split=split_name, similarity=round(best_sim, 4),
                    kind="near", train_source=t.get("source", "?"),
                    eval_source=rec.get("source", "?")))
    return result


def find_source_overlap(train: list[dict], eval_sets: dict[str, list[dict]]) -> dict:
    """Sources present in BOTH train and eval. Not always contamination
    (sources legitimately span splits) but must be reported; eval-only
    benchmark sources appearing in train is a hard failure."""
    train_sources = defaultdict(int)
    for r in train:
        train_sources[r.get("source", "?")] += 1
    overlap: dict[str, dict] = {}
    for split_name, recs in eval_sets.items():
        eval_sources = defaultdict(int)
        for r in recs:
            eval_sources[r.get("source", "?")] += 1
        common = set(train_sources) & set(eval_sources)
        for s in sorted(common):
            overlap.setdefault(s, {})[split_name] = {
                "train": train_sources[s], "eval": eval_sources[s]}
    return overlap


def check_splits(splits: dict[str, list[dict]], *,
                 near_threshold: float = 0.90,
                 near_enabled: bool = True,
                 fail_on_direct: bool = True,
                 eval_only_sources: set[str] | None = None) -> dict:
    """Run full contamination check over {'train': [...], 'validation': [...],
    'test': [...]}. Returns a report dict; raises LeakageError when direct
    leakage exists and fail_on_direct is set."""
    train = splits.get("train", [])
    eval_sets = {k: v for k, v in splits.items() if k != "train"}

    direct = find_direct_leakage(train, eval_sets)
    near = (find_near_leakage(train, eval_sets, threshold=near_threshold)
            if near_enabled else LeakageResult())
    overlap = find_source_overlap(train, eval_sets)

    eval_only_violations = []
    if eval_only_sources:
        for rec in train:
            if rec.get("source") in eval_only_sources:
                eval_only_violations.append({"id": rec.get("id"),
                                             "source": rec.get("source")})

    # passed is a truth flag independent of fail behavior: direct leakage and
    # eval-only-source violations always mean failure.
    passed = (not direct.has_direct) and (not eval_only_violations)
    report = {
        "passed": passed,
        "fail_on_direct": fail_on_direct,
        "direct_leakage": direct.to_dict()["direct"],
        "near_leakage": near.to_dict()["near"],
        "near_threshold": near_threshold,
        "source_overlap": overlap,
        "eval_only_source_violations": eval_only_violations,
    }
    if direct.has_direct and fail_on_direct:
        raise LeakageError(
            f"DIRECT train/eval leakage: {len(direct.direct)} identical "
            f"question fingerprints leaked into evaluation. Refusing to "
            f"emit splits. First leak: {direct.direct[0].to_dict()}")
    return report


class LeakageError(RuntimeError):
    """Raised when direct train/eval contamination is detected."""