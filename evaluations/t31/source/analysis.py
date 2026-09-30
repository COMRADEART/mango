"""T31.12 Paired analysis — deltas, uncertainty, and the failure taxonomy.

The brief requires four things of this layer, and each one is a rule about
what may *not* be said:

1. Per-benchmark accuracy for base and adapter, with absolute (pp) and
   relative deltas, and "Do not hide negative deltas" — so the sign is
   computed, never chosen.
2. A defensible uncertainty method, with the explicit warning "Do not claim an
   improvement is meaningful merely because adapter_accuracy >
   base_accuracy". A two-point gap on 1,000 items is not a finding.
3. Paired outcomes preserved (both correct / base only / adapter only /
   neither), with McNemar's test where appropriate, and "Do not overstate
   statistical significance".
4. A failure taxonomy, with "Do not manually reclassify errors merely to
   improve results" — categories come from the scorer, not from judgement.

Two statistical choices worth stating
--------------------------------------
**Clusters, not items.** ARC's *test* splits contain distinct items with
identical question stems but different option sets and gold answers — measured
at construction time on the frozen revisions (2,376 arc_easy items carry 2,371
distinct question fingerprints; 1,172 arc_challenge items carry 1,170). These
are genuinely different items, but a model that misreads "what keeps the
planets in orbit" tends to get every phrasing of it wrong together, so item
outcomes are not independent draws. Resampling items would therefore produce
a confidence interval that is too narrow — the flattering direction. The
bootstrap here resamples *clusters keyed by normalized question stem*, so
clustered outcomes move together. This is applied uniformly to every
benchmark; where every stem is unique the clustering degenerates to ordinary
item bootstrap, which is the correct behaviour, and the report states the
effective cluster count so a reader can see when it mattered.

**Exact McNemar.** With discordant counts in the tens, the chi-square
approximation is unreliable, so the exact conditional (binomial) test is used
throughout rather than only as a small-sample fallback. Two-sided by default.
The p-value is reported as a number, and the report is explicit that it
answers only "is this difference distinguishable from a coin flip among the
items where the two arms disagreed", which is a much narrower question than
"is the adapter better".
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from sciencemath.comparability.contract import (
    COMPARISON_EQUAL, COMPARISON_LIFT, COMPARISON_REGRESSION, EXTRACTION_OK,
)

#: Bootstrap resamples. 10,000 is the usual default for a 95% interval and is
#: cheap here (a few seconds per benchmark over a few thousand items).
BOOTSTRAP_RESAMPLES = 10_000

#: Percentile interval. Stated on the artifact so a reader never has to guess
#: which interval convention produced the numbers.
BOOTSTRAP_ALPHA = 0.05

#: Seed for the resampling. Fixed so that re-running the analysis over the
#: same stored rows reproduces the same interval exactly — an interval that
#: changes between two analyses of one dataset is not evidence.
BOOTSTRAP_SEED = 20260930

#: A delta is called LIFT or REGRESSION only when the 95% interval excludes
#: zero; otherwise it is reported as EQUAL. This is a *label*, not a claim of
#: causation, and the report says so.
_WHITESPACE = re.compile(r"\s+")


class AnalysisError(RuntimeError):
    """The rows cannot support the comparison being asked of them."""


def cluster_key(row: dict[str, Any]) -> str:
    """The unit that is resampled: the question stem, normalized.

    Two ARC items that ask the same question with different options share a
    cluster. Everything else is its own cluster.
    """
    question = _WHITESPACE.sub(" ", str(row.get("question", "")).strip().lower())
    return question or str(row.get("item_id"))


def _correct(row: dict[str, Any]) -> bool:
    """Content correctness — the capability metric, never schema validity.

    The brief requires the two be permanently separated; this function is the
    single place the analysis decides which one counts, so the separation
    cannot be lost by accident somewhere downstream.
    """
    return bool(row.get("content_valid"))


@dataclass(frozen=True)
class PairedOutcome:
    """One item's result under both arms."""
    item_id: str
    benchmark: str
    cluster: str
    base_correct: bool
    adapter_correct: bool
    base_error: str | None
    adapter_error: str | None
    base_extraction: str | None
    adapter_extraction: str | None

    @property
    def cell(self) -> str:
        if self.base_correct and self.adapter_correct:
            return "both_correct"
        if self.base_correct:
            return "base_only"
        if self.adapter_correct:
            return "adapter_only"
        return "neither"


def pair_rows(base_rows: Sequence[dict[str, Any]],
              adapter_rows: Sequence[dict[str, Any]], *, benchmark: str,
              require: bool = True) -> list[PairedOutcome]:
    """Join two arms by item id, refusing to compare mismatched sets.

    A paired analysis over two different item sets is not a paired analysis.
    Missing items are refused (``require=True``) because the natural
    implementation — inner-join and carry on — silently shrinks the denominator
    and reports a rate over whatever happened to survive.
    """
    base_by_id = {str(row["item_id"]): row for row in base_rows}
    adapter_by_id = {str(row["item_id"]): row for row in adapter_rows}
    if set(base_by_id) != set(adapter_by_id):
        only_base = sorted(set(base_by_id) - set(adapter_by_id))[:5]
        only_adapter = sorted(set(adapter_by_id) - set(base_by_id))[:5]
        raise AnalysisError(
            f"{benchmark}: arms cover different items — "
            f"{len(base_by_id)} base, {len(adapter_by_id)} adapter; "
            f"base-only e.g. {only_base}, adapter-only e.g. {only_adapter}")

    outcomes: list[PairedOutcome] = []
    for item_id in sorted(base_by_id):
        base = base_by_id[item_id]
        adapter = adapter_by_id[item_id]
        outcomes.append(PairedOutcome(
            item_id=item_id,
            benchmark=benchmark,
            cluster=cluster_key(base),
            base_correct=_correct(base),
            adapter_correct=_correct(adapter),
            base_error=base.get("error_category"),
            adapter_error=adapter.get("error_category"),
            base_extraction=base.get("extraction_status"),
            adapter_extraction=adapter.get("extraction_status"),
        ))
    if require and not outcomes:
        raise AnalysisError(f"{benchmark}: zero paired items — refusing to "
                            f"report a rate over an empty set")
    return outcomes


def paired_table(outcomes: Sequence[PairedOutcome]) -> dict[str, int]:
    counts = Counter(outcome.cell for outcome in outcomes)
    return {cell: counts.get(cell, 0) for cell in
            ("both_correct", "base_only", "adapter_only", "neither")}


def mcnemar_exact(base_only: int, adapter_only: int) -> dict[str, Any]:
    """Exact two-sided McNemar test on the discordant pairs.

    Only the discordant items carry information about which arm is better; the
    concordant ones are identical under both and cancel. The exact conditional
    test is used rather than the chi-square approximation because the
    discordant counts in a benchmark comparison are routinely small enough that
    the approximation's error matters.

    Returns the p-value plus the discordant counts, and states the question it
    answers, because a bare p-value invites the reading the brief forbids
    ("Do not overstate statistical significance").
    """
    n = base_only + adapter_only
    question = (
        "Among items where the arms disagreed, is the split distinguishable "
        "from a fair coin? This is not a test of overall capability, and a "
        "non-significant result is not evidence that the arms are equivalent."
    )
    if n == 0:
        return {"n_discordant": 0, "base_only": 0, "adapter_only": 0,
                "p_value": None, "method": "exact_binomial_two_sided",
                "question_answered": question,
                "note": "No discordant items: the exact test is undefined, "
                        "and no p-value is reported rather than 1.0."}
    k = min(base_only, adapter_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    p = min(1.0, 2.0 * tail)
    return {"n_discordant": n, "base_only": base_only,
            "adapter_only": adapter_only, "p_value": p,
            "method": "exact_binomial_two_sided",
            "question_answered": question}


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise AnalysisError("empty bootstrap distribution")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight)
                 + sorted_values[upper] * weight)


def cluster_bootstrap_delta(outcomes: Sequence[PairedOutcome], *,
                            resamples: int = BOOTSTRAP_RESAMPLES,
                            seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Percentile bootstrap CI for the adapter-minus-base delta, by cluster.

    Clusters (question stems) are resampled with replacement; every item in a
    drawn cluster comes along. This is what makes the interval honest on ARC,
    where identical stems produce correlated outcomes. When every stem is
    unique it is an ordinary item bootstrap and the output says so.
    """
    if not outcomes:
        raise AnalysisError("cannot bootstrap an empty outcome set")

    by_cluster: dict[str, list[PairedOutcome]] = {}
    for outcome in outcomes:
        by_cluster.setdefault(outcome.cluster, []).append(outcome)
    clusters = sorted(by_cluster)
    if not clusters:                               # pragma: no cover
        raise AnalysisError("no clusters to resample")

    sizes = [len(by_cluster[key]) for key in clusters]
    weighted = len(sizes) != len(outcomes)

    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(resamples):
        drawn = [clusters[rng.randrange(len(clusters))]
                 for _ in range(len(clusters))]
        base_hits = adapter_hits = total = 0
        for key in drawn:
            for outcome in by_cluster[key]:
                total += 1
                base_hits += int(outcome.base_correct)
                adapter_hits += int(outcome.adapter_correct)
        if total:
            deltas.append(100.0 * (adapter_hits - base_hits) / total)
    if not deltas:                                 # pragma: no cover
        raise AnalysisError("bootstrap produced no usable resamples")

    deltas.sort()
    low = _percentile(deltas, BOOTSTRAP_ALPHA / 2)
    high = _percentile(deltas, 1 - BOOTSTRAP_ALPHA / 2)
    return {
        "method": "cluster_percentile_bootstrap",
        "cluster_key": "normalized_question_stem",
        "resamples": resamples,
        "seed": seed,
        "alpha": BOOTSTRAP_ALPHA,
        "ci_low_pp": round(low, 4),
        "ci_high_pp": round(high, 4),
        "cluster_count": len(clusters),
        "item_count": len(outcomes),
        "clustering_material": weighted,
        "excludes_zero": bool(low > 0.0 or high < 0.0),
        "note": (
            "Resampling unit is the normalized question stem, not the item: "
            "outcomes for items sharing a stem are correlated and resampling "
            "items would understate the interval."
            if weighted else
            "Every question stem is unique here, so cluster resampling reduces "
            "to item resampling."),
    }


def error_taxonomy(outcomes: Sequence[PairedOutcome]) -> dict[str, Any]:
    """Failure counts per arm, straight from the scorer's categories.

    Nothing is reclassified here. The brief forbids adjusting categories to
    improve results, and the surest way to make that impossible is to have no
    judgement in this function at all.
    """
    base_errors = Counter(o.base_error for o in outcomes
                          if not o.base_correct and o.base_error)
    adapter_errors = Counter(o.adapter_error for o in outcomes
                             if not o.adapter_correct and o.adapter_error)
    # The status is one of the extractors' own constants — "OK" when an answer
    # was read, "FAILED" when none could be, "AMBIGUOUS" when more than one was
    # offered — so it is compared against the constant rather than a literal
    # spelled out again here. An earlier lower-case "ok" matched nothing, which
    # counted every successfully extracted item as a failure and put this field
    # in flat contradiction with the error counts beside it: an item whose
    # answer could not be read is scored ``answer_extraction_failure``, so both
    # numbers describe the same rows and must agree. Both non-OK statuses count
    # — "the model said nothing" and "the model said two things" are different
    # facts worth recording separately, but neither is a usable measurement.
    extraction_failures = {
        "base": sum(1 for o in outcomes
                    if o.base_extraction and o.base_extraction != EXTRACTION_OK),
        "adapter": sum(1 for o in outcomes
                       if o.adapter_extraction
                       and o.adapter_extraction != EXTRACTION_OK),
    }
    extraction_status = {
        arm: dict(sorted(Counter(
            getattr(o, f"{arm}_extraction") for o in outcomes
            if getattr(o, f"{arm}_extraction")
            and getattr(o, f"{arm}_extraction") != EXTRACTION_OK).items()))
        for arm in ("base", "adapter")
    }
    shared = sum(1 for o in outcomes if o.cell == "neither")
    return {
        "base_error_counts": dict(sorted(base_errors.items())),
        "adapter_error_counts": dict(sorted(adapter_errors.items())),
        "extraction_failures": extraction_failures,
        "extraction_failure_status": extraction_status,
        "shared_failures": shared,
        "note": ("Categories are assigned by the scorer from the generation "
                 "alone; no failure was reclassified after viewing results."),
    }


def schema_content_split(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """The four cells of the schema x content cross-tabulation.

    The brief requires the two facts be permanently separate, and a pair of
    booleans that is only ever reported as totals cannot show that they are:
    a scorer that set ``schema_valid`` from ``content_valid`` would produce
    identical headline numbers. The cross-tabulation is what makes the
    separation visible, because it isolates ``schema_only`` — a well-formed
    wrong answer, which is the exact confusion the rule guards against.
    """
    counts = {"schema_and_content": 0, "schema_only": 0,
              "content_only": 0, "neither": 0}
    for row in rows:
        schema = bool(row.get("schema_valid"))
        content = bool(row.get("content_valid"))
        key = ("schema_and_content" if schema and content else
               "schema_only" if schema else
               "content_only" if content else "neither")
        counts[key] += 1
    return counts


def benchmark_summary(outcomes: Sequence[PairedOutcome], *,
                      extraction_base: dict[str, int] | None = None,
                      extraction_adapter: dict[str, int] | None = None,
                      invalid_base: int = 0,
                      invalid_adapter: int = 0,
                      schema_content_base: dict[str, int] | None = None,
                      schema_content_adapter: dict[str, int] | None = None,
                      ) -> dict[str, Any]:
    """Everything the report needs for one benchmark's model-only comparison.

    Raises on an empty set: the brief's fail-nonvacuity rule means a benchmark
    with no scored items must fail loudly rather than report 0.0% or, worse,
    100%.
    """
    if not outcomes:
        raise AnalysisError("refusing to summarize zero scored items")

    table = paired_table(outcomes)
    total = len(outcomes)
    base_hits = table["both_correct"] + table["base_only"]
    adapter_hits = table["both_correct"] + table["adapter_only"]
    base_acc = base_hits / total
    adapter_acc = adapter_hits / total
    delta_pp = 100.0 * (adapter_acc - base_acc)
    relative = ((adapter_acc - base_acc) / base_acc) if base_acc else None
    bootstrap = cluster_bootstrap_delta(outcomes)
    if delta_pp > 0 and bootstrap["excludes_zero"]:
        comparison = COMPARISON_LIFT
    elif delta_pp < 0 and bootstrap["excludes_zero"]:
        comparison = COMPARISON_REGRESSION
    else:
        comparison = COMPARISON_EQUAL

    return {
        "benchmark": outcomes[0].benchmark if outcomes else "",
        "total_items": total,
        "base_correct": base_hits,
        "adapter_correct": adapter_hits,
        "base_accuracy": round(base_acc, 6),
        "adapter_accuracy": round(adapter_acc, 6),
        "delta_pp": round(delta_pp, 4),
        "relative_delta": (round(relative, 6) if relative is not None else None),
        "comparison": comparison,
        "paired": table,
        "mcnemar": mcnemar_exact(table["base_only"], table["adapter_only"]),
        "uncertainty": bootstrap,
        "invalid_outputs": {"base": int(invalid_base),
                            "adapter": int(invalid_adapter)},
        "extraction_failures": {
            "base": int((extraction_base or {}).get("failures", 0)),
            "adapter": int((extraction_adapter or {}).get("failures", 0)),
        },
        "schema_content": {
            "base": schema_content_base,
            "adapter": schema_content_adapter,
        },
        "errors": error_taxonomy(outcomes),
    }


def diagnostic_rows(outcomes: Sequence[PairedOutcome],
                    base_rows: Sequence[dict[str, Any]],
                    adapter_rows: Sequence[dict[str, Any]]
                    ) -> list[dict[str, Any]]:
    """The T32 handoff: every item where the arms disagreed or both failed.

    Diagnostic output only. The brief is explicit — "Do NOT train on it during
    T31" — and this function only reads and joins; nothing downstream in this
    package consumes its output as training data.
    """
    base_by_id = {str(row["item_id"]): row for row in base_rows}
    adapter_by_id = {str(row["item_id"]): row for row in adapter_rows}
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        if outcome.cell == "both_correct":
            continue
        base = base_by_id[outcome.item_id]
        adapter = adapter_by_id[outcome.item_id]
        rows.append({
            "item_id": outcome.item_id,
            "benchmark": outcome.benchmark,
            "cluster": outcome.cluster,
            "outcome": outcome.cell,
            "difficulty_proxy": {
                "base_output_tokens": base.get("output_tokens"),
                "adapter_output_tokens": adapter.get("output_tokens"),
            },
            "base": {
                "raw_generation": base.get("raw_generation"),
                "extracted_answer": base.get("extracted_answer"),
                "correct": outcome.base_correct,
                "error_category": outcome.base_error,
                "extraction_status": outcome.base_extraction,
            },
            "adapter": {
                "raw_generation": adapter.get("raw_generation"),
                "extracted_answer": adapter.get("extracted_answer"),
                "correct": outcome.adapter_correct,
                "error_category": outcome.adapter_error,
                "extraction_status": outcome.adapter_extraction,
            },
            "gold": base.get("gold"),
            "question": base.get("question"),
        })
    return rows


def aggregate(summaries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Micro-average across benchmarks, for the headline number.

    Reported separately from the per-benchmark table and labelled as a
    micro-average, because a single pooled number over five benchmarks of very
    different sizes hides which one moved.
    """
    summaries = list(summaries)
    if not summaries:
        raise AnalysisError("no benchmark summaries to aggregate")
    total = sum(s["total_items"] for s in summaries)
    if total == 0:
        raise AnalysisError("aggregate over zero items is vacuous")
    base_hits = sum(s["base_correct"] for s in summaries)
    adapter_hits = sum(s["adapter_correct"] for s in summaries)
    base_acc = base_hits / total
    adapter_acc = adapter_hits / total
    return {
        "aggregation": "micro_average_over_items",
        "benchmarks": [s["benchmark"] for s in summaries],
        "total_items": total,
        "base_accuracy": round(base_acc, 6),
        "adapter_accuracy": round(adapter_acc, 6),
        "delta_pp": round(100.0 * (adapter_acc - base_acc), 4),
        "note": ("A single pooled rate over benchmarks of different sizes; "
                 "the per-benchmark table is the interpretable one."),
    }


def to_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
