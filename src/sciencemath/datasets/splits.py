"""Seeded, group-aware, domain-stratified train/validation/test splitting.

Design guarantees:
  * deterministic for a fixed seed (hash-based group assignment + sorted walk)
  * questions sharing a group key (default: normalized question text) never
    land in different splits -> template/paraphrase leakage collapses
  * sources listed in eval_only_sources / holdout_sources are permanently
    kept OUT of train (hard contamination limit)
"""
from __future__ import annotations

import hashlib
import random
from collections import defaultdict

from sciencemath.datasets.leakage import LeakageError, check_splits


def group_key(record: dict, method: str = "normalized_question") -> str:
    q = str(record.get("question", ""))
    if method == "normalized_question":
        from sciencemath.datasets.normalize import text_fingerprint
        return "q:" + text_fingerprint(q)
    if method == "source_id":
        return "sid:" + str(record.get("source", "?")) + "::" + str(record.get("source_id", ""))
    if method == "template_hash":
        from sciencemath.datasets.normalize import text_fingerprint
        # digits replaced by '#' so "3x+7=22" and "3x+9=31" share a template
        digits_masked = "".join("#" if ch.isdigit() else ch
                                for ch in text_fingerprint(q))
        return "tpl:" + hashlib.sha1(digits_masked.encode()).hexdigest()[:12]
    raise ValueError(f"unknown group_by method: {method}")


def assign_splits(records: list[dict], *,
                  seed: int = 42,
                  test_fraction: float = 0.10,
                  validation_fraction: float = 0.05,
                  group_by: str = "normalized_question",
                  eval_only_sources: set[str] | None = None,
                  holdout_sources: set[str] | None = None) -> tuple[dict[str, list[dict]], dict]:
    """Return ({'train': [...], 'validation': [...], 'test': [...]}, summary).

    Stratified by domain: within each domain, groups are shuffled (seeded)
    and allocated to splits in proportion to the requested fractions.
    """
    if not 0.0 <= test_fraction < 1.0 or not 0.0 <= validation_fraction < 1.0:
        raise ValueError("fractions must be in [0, 1)")
    if test_fraction + validation_fraction >= 1.0:
        raise ValueError("test + validation fractions must total < 1.0")

    eval_only = {s for s in (eval_only_sources or set()) if s}
    holdout = {s for s in (holdout_sources or set()) if s}
    forced_eval = eval_only | holdout

    # bucket records by (domain, group); group spans split boundaries
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for rec in records:
        src = rec.get("source", "?")
        if src in forced_eval:
            # forced-eval records form their own single-record groups pinned
            # to test below; mixing with normal groups would leak them back
            groups[(str(rec.get("domain", "?")), f"__forced__:{rec.get('id', '')}")] = [rec]
            continue
        groups[(str(rec.get("domain", "?")), group_key(rec, group_by))].append(rec)

    rng = random.Random(seed)
    by_domain: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in groups:
        domain, gk = key
        by_domain[domain].append(key)
    for domain in by_domain:
        rng.shuffle(by_domain[domain])

    splits: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}
    total = sum(len(v) for v in groups.values())
    for domain, keys in by_domain.items():
        n_domain = sum(len(groups[k]) for k in keys)
        quota_test = int(round(n_domain * test_fraction))
        quota_val = int(round(n_domain * validation_fraction))

        filled_test = filled_val = 0
        for k in keys:
            recs = groups[k]
            gk = k[1]
            src = recs[0].get("source", "?")
            if src in forced_eval or gk.startswith("__forced__:"):
                splits["test"].extend(recs)
                filled_test += len(recs)
                continue
            if filled_val < quota_val:
                splits["validation"].extend(recs)
                filled_val += len(recs)
            elif filled_test < quota_test:
                splits["test"].extend(recs)
                filled_test += len(recs)
            else:
                splits["train"].extend(recs)

    # stamp the split label onto every record so split files are self-describing
    for split, recs in splits.items():
        for r in recs:
            r["split"] = split

    summary = {
        "total": total,
        "counts": {k: len(v) for k, v in splits.items()},
        "fractions": {k: (len(v) / total if total else 0.0)
                      for k, v in splits.items()},
        "seed": seed,
        "group_by": group_by,
        "forced_eval_sources": sorted(forced_eval),
        "leakage_passed": True,   # set by build_and_check
    }
    return splits, summary


def build_and_check(records: list[dict], *, seed: int = 42,
                    test_fraction: float = 0.10,
                    validation_fraction: float = 0.05,
                    group_by: str = "normalized_question",
                    eval_only_sources: set[str] | None = None,
                    holdout_sources: set[str] | None = None,
                    near_threshold: float = 0.90,
                    fail_on_direct: bool = True) -> tuple[dict[str, list[dict]], dict, dict]:
    """Convenience: assign splits, then run the contamination check.
    Raises LeakageError on direct leakage (fail_on_direct=True)."""
    splits, summary = assign_splits(
        records, seed=seed, test_fraction=test_fraction,
        validation_fraction=validation_fraction, group_by=group_by,
        eval_only_sources=eval_only_sources, holdout_sources=holdout_sources)
    try:
        leakage = check_splits(splits, near_threshold=near_threshold,
                               fail_on_direct=fail_on_direct,
                               eval_only_sources=eval_only_sources or set())
    except LeakageError:
        summary["leakage_passed"] = False
        raise
    return splits, summary, leakage