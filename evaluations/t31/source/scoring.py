"""T31.9 The scoring pass — raw rows in, scored rows out.

Scoring is a pure function of a raw row plus its item. Nothing here reads a
result from the other arm, nothing consults a model, and nothing can be
influenced by how either side is doing — which is what lets the scored set be
rebuilt from the raw set at any time and compared against what was reported.

That separation has a practical consequence worth stating: the raw file is the
expensive artifact and the scored file is derived from it, so a scorer change
is a re-scoring, not a re-run. If a scorer defect is found after the run, the
scored rows are regenerated and the report is rebuilt from them, with the
generations untouched.

What the pass enforces:

* **Completeness before scoring.** A short raw set is refused rather than
  scored, because a rate computed over it would be a rate over something other
  than the benchmark. This is the fail-nonvacuity rule at the point where it
  can still be caught.
* **Every raw row scored, including failures.** A generation that could not be
  read is a scored row carrying ``answer_extraction_failure``, not a missing
  row. Dropping it would raise every rate by shrinking the denominator.
* **Determinism.** The same raw row scored twice gives the same scored row,
  including the tier that decided it. That is what makes the reported number
  reproducible by a third party with the same inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from sciencemath.comparability.contract import BENCHMARKS
from sciencemath.comparability.extractors import extract, strip_reasoning
from sciencemath.comparability.loaders import EvalItem
from sciencemath.comparability.rows import (
    EVIDENCE_ROOT, append_rows, build_scored_row, raw_path, read_rows,
    require_complete, scored_path,
)
from sciencemath.comparability.scorers import score


class ScoringError(RuntimeError):
    """A raw row could not be scored, or the set to score is unsound."""


def item_index(items: Iterable[EvalItem]) -> dict[str, EvalItem]:
    """Items by id, refusing a collision.

    A duplicate id would make one item's row unscoreable and silently score
    another's twice, so it is a failure here rather than a wrong number later.
    """
    index: dict[str, EvalItem] = {}
    for item in items:
        if item.item_id in index:
            raise ScoringError(
                f"two items share the id {item.item_id!r}; the id is what "
                f"pairs the two arms, so it has to identify exactly one item")
        index[item.item_id] = item
    return index


def score_row(raw: dict[str, Any], item: EvalItem) -> dict[str, Any]:
    """Score one generation. Deterministic, total, and never arm-dependent."""
    kind = BENCHMARKS[item.benchmark]["kind"]
    generation = raw.get("raw_generation") or ""
    finish_reason = raw.get("finish_reason") or "stop"
    extraction = extract(item, kind, generation)
    verdict = score(item, kind, extraction, generation,
                    finish_reason=finish_reason)
    return build_scored_row(
        raw,
        normalized_generation=strip_reasoning(generation),
        extraction=extraction, score=verdict)


@dataclass(frozen=True)
class ScoringProgress:
    arm: str
    benchmark: str
    scored: int
    total: int
    correct: int


def score_arm(benchmark: str, arm: str, items: Sequence[EvalItem], *,
              root: Path | None = None,
              require: bool = True) -> ScoringProgress:
    """Score one arm's captured rows for one benchmark.

    ``require`` is the fail-nonvacuity switch and defaults to on: a rate is
    only reported over a set that is complete against the frozen suite.
    """
    root = root or EVIDENCE_ROOT
    source = raw_path(root, arm, benchmark)
    rows, unreadable = read_rows(source)
    if unreadable:
        raise ScoringError(f"{source} has unparseable lines {unreadable}")

    expected_ids = [item.item_id for item in items]
    if require:
        require_complete(rows, expected_ids, arm=arm, benchmark=benchmark)

    index = item_index(items)
    scored: list[dict[str, Any]] = []
    for row in rows:
        item = index.get(str(row.get("item_id")))
        if item is None:
            raise ScoringError(
                f"{source} contains {row.get('item_id')!r}, which is not in "
                f"the frozen suite; scoring it would put a row in the results "
                f"that no item accounts for")
        scored.append(score_row(row, item))

    written = append_rows(scored_path(root, arm, benchmark), scored)
    return ScoringProgress(arm=arm, benchmark=benchmark, scored=written,
                           total=len(rows),
                           correct=sum(1 for row in scored
                                       if row["content_valid"]))


def _canonical(row: dict[str, Any]) -> str:
    """A row's serialised form, so an in-memory tuple and the list it becomes
    on disk compare equal. The comparison is between what would be written and
    what was written, which is the question the check is actually asking."""
    import json

    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def rescore_is_identical(benchmark: str, arm: str, items: Sequence[EvalItem], *,
                         root: Path | None = None) -> bool:
    """Re-score and confirm nothing moved.

    The brief asks for deterministic hashes over the scored results, which is
    only meaningful if scoring is a function rather than a judgement. This is
    the check that it is.
    """
    root = root or EVIDENCE_ROOT
    rows, _ = read_rows(raw_path(root, arm, benchmark))
    index = item_index(items)
    existing, _ = read_rows(scored_path(root, arm, benchmark))
    if len(existing) != len(rows):
        return False
    stored = {_canonical(row) for row in existing}
    for row in rows:
        item = index.get(str(row.get("item_id")))
        if item is None:
            return False
        if _canonical(score_row(row, item)) not in stored:
            return False
    return True
