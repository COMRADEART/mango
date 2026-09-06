"""T2 deterministic failure taxonomy: fixed classification order,
reproducible categories, HALLUCINATED_FACT never auto-assigned."""
import pytest

from sciencemath.evaluation.taxonomy import CATEGORIES, classify_failure


def test_category_list_contains_reserved_label():
    assert "HALLUCINATED_FACT" in CATEGORIES


def test_pass_returns_none():
    assert classify_failure(correct=True, extracted="4",
                            answer_type="numeric", choices=None,
                            raw="\\boxed{4}") is None


def test_order_error_before_everything():
    # an error on a correct-looking output still reports the error class
    assert classify_failure(correct=False, extracted="4",
                            answer_type="numeric", choices=None,
                            raw="\\boxed{4}",
                            error="RuntimeError: device-side assertion") == \
        "GENERATION_ERROR"


def test_oom_classified():
    assert classify_failure(correct=False, extracted=None,
                            answer_type="numeric", choices=None, raw="",
                            error="torch.cuda.OutOfMemoryError: OOM") == "OOM"


def test_truncated_output():
    assert classify_failure(correct=False, extracted="partial so far",
                            answer_type="numeric", choices=None,
                            raw="partial so far, and then",
                            finish_reason="length") == "TRUNCATED_OUTPUT"


def test_invalid_choice_mcq():
    # extracted a letter that is not a valid choice index
    assert classify_failure(correct=False, extracted="E",
                            answer_type="multiple_choice",
                            choices=["a", "b", "c", "d"],
                            raw="\\boxed{E}") == "INVALID_CHOICE"


def test_extraction_failure_mcq():
    assert classify_failure(correct=False, extracted=None,
                            answer_type="multiple_choice",
                            choices=["a", "b"],
                            raw="I think it is the second one") == \
        "EXTRACTION_FAILURE"


def test_calibration_confident_assertion_is_wrong_answer():
    assert classify_failure(correct=False, extracted="800000",
                            answer_type="text", choices=None,
                            raw="The population was 800000.",
                            expected_answer="__UNKNOWN__",
                            category="uncertainty_calibration") == "WRONG_ANSWER"


def test_calibration_refusal_not_failure_path():
    # answering with uncertainty is CORRECT for calibration items
    assert classify_failure(correct=True, extracted=None,
                            answer_type="text", choices=None,
                            raw="I cannot determine that.",
                            expected_answer="__UNKNOWN__",
                            category="uncertainty_calibration") is None


def test_wrong_answer_default():
    assert classify_failure(correct=False, extracted="7",
                            answer_type="numeric", choices=None,
                            raw="\\boxed{7}", expected_answer="8") == \
        "WRONG_ANSWER"


def test_hallucinated_fact_never_auto_assigned():
    # even obviously confabulated text stays within the assignable set
    out = classify_failure(correct=False, extracted=None,
                           answer_type="text", choices=None,
                           raw="The temperature was 21.4 degrees.",
                           expected_answer="__UNKNOWN__",
                           category="uncertainty_calibration")
    assert out in CATEGORIES and out != "HALLUCINATED_FACT"


def test_deterministic_repeats():
    args = dict(correct=False, extracted="5", answer_type="numeric",
                choices=None, raw="\boxed{5}", expected_answer="8")
    assert classify_failure(**args) == classify_failure(**args)