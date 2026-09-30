"""T31.1 The frozen vocabulary: what is being compared, and what a row means.

Everything that a run, a scorer and a report must agree on lives here, so
that no two modules can quietly disagree about the spelling of a benchmark or
the meaning of "correct". A metric that is defined in two places is a metric
that will eventually mean two things.

Two of these constants carry more weight than the rest and are worth stating
plainly:

``ARM_BASE`` / ``ARM_ADAPTER``
    The experiment has exactly one independent variable. Both arms receive
    the same items, the same prompt, the same chat template, the same
    decoding settings, the same extractor and the same scorer. The only
    difference between a base row and an adapter row with the same item id is
    which weights produced the tokens.

``content_valid``
    The T31 brief requires schema validity and content validity to be
    permanently separate, and this package keeps them separate all the way
    from the row schema to the report. A model that emits perfectly formatted
    text containing a wrong answer is a *content* failure. Protocol
    compliance is never allowed to stand in for reasoning success.
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
SCHEMA_VERSION: Final = "t31-comparability-v1"

# ---------------------------------------------------------------------------
# the experiment
# ---------------------------------------------------------------------------
#: The two arms under test. Identical in every respect but the weights.
ARM_BASE: Final = "base"
ARM_ADAPTER: Final = "adapter"
ARMS: Final = (ARM_BASE, ARM_ADAPTER)

#: The five benchmarks the brief requires, in report order. Order is fixed so
#: that a summary table is byte-stable across runs.
BENCHMARK_ORDER: Final = ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq")

#: Per-benchmark behaviour, frozen before any generation happens. ``kind``
#: selects the extractor and scorer; ``answer_format`` is the shape of a
#: correct final answer; ``max_new_tokens`` is the generation budget.
BENCHMARKS: Final = {
    "gsm8k": {
        "kind": "numeric",
        "split": "test",
        "answer_format": "#### <number>",
        "max_new_tokens": 512,
    },
    "math500": {
        "kind": "math",
        "split": "test",
        "answer_format": "\\boxed{...}",
        "max_new_tokens": 1024,
    },
    "arc_easy": {
        "kind": "multiple_choice",
        "split": "test",
        "answer_format": "single letter",
        "max_new_tokens": 32,
    },
    "arc_challenge": {
        "kind": "multiple_choice",
        "split": "test",
        "answer_format": "single letter",
        "max_new_tokens": 32,
    },
    "sciq": {
        "kind": "multiple_choice",
        "split": "test",
        "answer_format": "single letter",
        "max_new_tokens": 32,
    },
}

# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------
#: Answer extraction result. ``AMBIGUOUS`` is deliberately distinct from
#: ``FAILED``: a generation that offers two different final answers is a
#: different kind of evidence from one that offers none, and the brief asks
#: for extraction failures to be recorded separately from content failures.
EXTRACTION_OK: Final = "OK"
EXTRACTION_AMBIGUOUS: Final = "AMBIGUOUS"
EXTRACTION_FAILED: Final = "FAILED"

#: The error taxonomy. ``correct`` leads because every row carries exactly one
#: of these, and a scorer that has to special-case the happy path is a scorer
#: whose taxonomy is incomplete.
ERROR_CATEGORIES: Final = (
    "correct",
    "wrong_reasoning",
    "wrong_final_answer",
    "formatting_failure",
    "answer_extraction_failure",
    "abstention",
    "truncated_generation",
    "invalid_option",
    "hallucinated_constraint",
    "tool_runtime_failure",
    "other",
)

#: Categories that mean "the harness could not read an answer", as opposed to
#: "the model answered and was wrong". Used by the analysis to separate
#: measurement failure from capability failure, and by the report to refuse to
#: present the two as the same number.
MEASUREMENT_FAILURE_CATEGORIES: Final = (
    "answer_extraction_failure",
    "truncated_generation",
    "tool_runtime_failure",
)

# ---------------------------------------------------------------------------
# the decision
# ---------------------------------------------------------------------------
#: The three tokens the report may end with. Exactly one is emitted.
DECISION_PASS: Final = "MANGO_T31_PUBLIC_COMPARABILITY_PASS"
DECISION_PARTIAL: Final = "MANGO_T31_PUBLIC_COMPARABILITY_PARTIAL"
DECISION_FAIL: Final = "MANGO_T31_PUBLIC_COMPARABILITY_FAIL"

#: The T31 brief is explicit that the decision judges the *evidence*, not the
#: model: "T31 can still PASS if the comparison is rigorous, complete and
#: reproducible." The three outcomes of the comparison itself are recorded
#: separately from the decision, under these names.
COMPARISON_LIFT: Final = "positive_model_level_lift_observed"
COMPARISON_EQUAL: Final = "no_clear_model_level_lift_demonstrated"
COMPARISON_REGRESSION: Final = "negative_model_level_delta_observed"
