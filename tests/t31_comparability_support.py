"""T31 test support for the public-comparability evaluation layer.

Kept separate from the parked ``t31_support.py`` (that file belongs to the
state-engine work-in-progress on another branch and is deliberately not
touched by this milestone).
"""
from __future__ import annotations

from sciencemath.comparability.contract import BENCHMARKS
from sciencemath.comparability.loaders import EvalItem, item_id_for
from sciencemath.comparability.prompts import SYSTEM_PROMPT, prompt_text


def item(benchmark: str = "gsm8k", *, question: str = "How many?",
         gold: str = "72", gold_label: str | None = None,
         choices: tuple[tuple[str, str], ...] = (), split: str = "test",
         native_id: str | None = None, **meta) -> EvalItem:
    """Build an item directly, for tests that do not need a dataset.

    ``native_id`` is the seed when the benchmark has one, and the question text
    otherwise — which matters when several items share a question stem, as
    ARC's test split genuinely does. Without a native id those items would mint
    the same item id, and the id would stop identifying an item.
    """
    return EvalItem(
        item_id=item_id_for(benchmark, split,
                            native_id if native_id is not None else question),
        benchmark=benchmark, split=split, native_id=native_id,
        question=question, choices=choices, gold=gold, gold_label=gold_label,
        meta=dict(meta),
    )


def mcq(gold_label: str = "A", *, question: str = "Which one?",
        choices: tuple[tuple[str, str], ...] = (
            ("A", "sunlight"), ("B", "water"), ("C", "soil"), ("D", "air")),
        benchmark: str = "arc_easy", **meta) -> EvalItem:
    return item(benchmark, question=question, gold=gold_label,
                gold_label=gold_label, choices=choices, **meta)


def kind_of(item_: EvalItem) -> str:
    return BENCHMARKS[item_.benchmark]["kind"]


def raw_row(item_: EvalItem, arm: str = "base", *,
            generation: str = "#### 72", finish_reason: str = "stop",
            config_hash: str = "c" * 64, **overrides):
    """A complete raw row for an item, with every field filled in."""
    from sciencemath.comparability.rows import build_raw_row

    fields = dict(
        arm=arm,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt_text(item_, kind_of(item_)),
        model_id="Qwen/Qwen3-1.7B",
        model_revision="70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        adapter_id=None, adapter_revision=None, adapter_sha256=None,
        config_hash=config_hash,
        enable_thinking=False,
        raw_generation=generation,
        finish_reason=finish_reason,
        latency_s=0.5, prompt_tokens=100, output_tokens=20, error=None,
    )
    fields.update(overrides)
    return build_raw_row(item_, **fields)


def scored_row(raw: dict, *, content_valid: bool, schema_valid: bool = True,
               extracted: str | None = "72", status: str = "OK",
               error_category: str = "correct", tier: str = "exact"):
    """A scored row built from an explicitly stated outcome.

    Tests that care about the *analysis* should not depend on the scorer
    getting a particular string right; they state the outcome they mean.
    """
    from sciencemath.comparability.extractors import Extraction
    from sciencemath.comparability.rows import build_scored_row
    from sciencemath.comparability.scorers import Score

    extraction = Extraction(status=status, answer=extracted, tier=tier, note="")
    score = Score(content_valid=content_valid, schema_valid=schema_valid,
                  error_category=error_category, scorer_tier=tier, notes=())
    return build_scored_row(raw, normalized_generation=raw["raw_generation"],
                            extraction=extraction, score=score)


def arm_rows(items, *, arm: str, correct_ids: set[str],
             **raw_overrides) -> list[dict]:
    """Scored rows for one arm where exactly ``correct_ids`` were answered."""
    rows = []
    for item_ in items:
        raw = raw_row(item_, arm=arm, **raw_overrides)
        ok = item_.item_id in correct_ids
        rows.append(scored_row(
            raw, content_valid=ok,
            extracted="72" if ok else "11",
            error_category="correct" if ok else "wrong_final_answer"))
    return rows

