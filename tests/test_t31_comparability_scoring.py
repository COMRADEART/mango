"""T31 tests, brief categories 6-10, 13 and 20: scoring, per benchmark.

The brief's construction order puts this second, before any generation runs:
"2. validate scorer against known simple cases". Every case below is a case
whose right answer is knowable without a model, so a scorer defect shows up
here as a failing assertion instead of as a plausible-looking accuracy number
in the report.

The four benchmark kinds get their own section because they fail differently.
GSM8K fails by normalising numbers wrongly; MATH fails by being unable to see
that two spellings are one expression; the multiple-choice benchmarks fail by
reading an answer out of prose that does not contain one. The last of those is
the dangerous one, because its failures inflate rather than depress accuracy.

Scoring and extraction are one pipeline, so these tests exercise both. That is
deliberate: the question is not "is the parser right?" but "is the number in
the results table right?", and only the pipeline answers that.
"""
from __future__ import annotations

import pytest

from sciencemath.comparability.extractors import extract
from sciencemath.comparability.scorers import math_equivalent, score

from t31_comparability_support import item, kind_of, mcq


def run(subject, raw: str, *, finish: str = "stop"):
    """Extract and score one generation, the way the runner does."""
    kind = kind_of(subject)
    return score(subject, kind, extract(subject, kind, raw), raw,
                 finish_reason=finish)


def gsm8k(gold: str = "72"):
    return item("gsm8k", question="How many eggs?", gold=gold)


def math500(gold: str = r"\frac{1}{2}"):
    return item("math500", question="Solve.", gold=gold)


def sciq(gold_label: str = "C"):
    return item("sciq", question="Which?", gold=gold_label,
                gold_label=gold_label,
                choices=(("A", "alpha"), ("B", "beta"), ("C", "gamma"),
                         ("D", "delta")))


# ---------------------------------------------------------------------------
# category 7 — GSM8K, numeric exact match
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("generation,gold", [
    ("#### 72", "72"),
    ("#### 1,000", "1000"),
    ("#### 72.0", "72"),
    ("#### $1000", "1000"),
    ("#### 0.50", "0.5"),
    ("#### -3", "-3"),
])
def test_a_correct_number_scores_correct_however_it_is_written(generation,
                                                               gold):
    """Normalisation is the whole scorer here, so it is tested as such."""
    result = run(gsm8k(gold), generation)
    assert result.content_valid is True
    assert result.error_category == "correct"
    assert result.schema_valid is True


def test_the_hash_marker_is_what_makes_it_schema_valid():
    """The prompt asks for ``####``; answering without it is a format failure.

    Content and format are separate facts about the same generation, and both
    are recorded rather than collapsed into one verdict.
    """
    result = run(gsm8k("72"), "So she sells 18 eggs, no wait, 72.")
    assert result.schema_valid is False
    assert result.content_valid is True
    assert result.scorer_tier == "decimal_equality"


def test_a_wrong_number_is_wrong_even_when_perfectly_formatted():
    result = run(gsm8k("72"), "#### 18")
    assert result.content_valid is False
    assert result.schema_valid is True
    assert result.error_category == "wrong_final_answer"


def test_a_wrong_number_reached_by_prose_is_still_wrong():
    result = run(gsm8k("72"), "She has 18 eggs left.")
    assert result.content_valid is False
    assert result.schema_valid is False


def test_a_declined_answer_is_an_abstention_not_a_wrong_answer():
    """Different facts: "I don't know" and "the answer is 18" are not alike."""
    result = run(gsm8k("72"), "I cannot determine the number of eggs.")
    assert result.content_valid is False
    assert result.error_category == "abstention"


def test_a_generation_cut_off_by_the_token_budget_says_so():
    result = run(gsm8k("72"), "First, she", finish="length")
    assert result.error_category == "truncated_generation"
    assert result.content_valid is False


# ---------------------------------------------------------------------------
# category 8 — MATH-500, normalised and symbolic comparison
# ---------------------------------------------------------------------------
def test_an_identically_written_answer_is_correct():
    result = run(math500(r"\frac{1}{2}"), r"Thus \boxed{\frac{1}{2}}.")
    assert result.content_valid is True
    assert result.scorer_tier == "exact_normalized"
    assert result.schema_valid is True


@pytest.mark.parametrize("gold,predicted", [
    (r"\frac{1}{2}", "0.5"),
    (r"\frac{1}{2}", r"\frac{2}{4}"),
    ("4", "2+2"),
    ("3", r"\frac{6}{2}"),
    ("3", "6/2"),
    ("2\\pi", r"2\cdot\pi"),
    (r"\sqrt{2}", r"2^{1/2}"),
    ("1024", "2^{10}"),
    ("81", "3^{4}"),
    ("1000", "10^{3}"),
    (r"\frac{1}{8}", "2^{-3}"),
])
def test_mathematically_equal_answers_are_equal(gold, predicted):
    """Otherwise the scorer measures LaTeX spelling, not mathematics."""
    result = run(math500(gold), "\\boxed{" + predicted + "}")
    assert result.content_valid is True
    assert result.scorer_tier in ("exact_normalized", "numeric", "symbolic")


@pytest.mark.parametrize("gold,predicted", [
    (r"\frac{1}{2}", "1"),
    (r"\frac{1}{2}", "2"),
    ("4", "5"),
    ("x^2+1", "x^2-1"),
])
def test_mathematically_different_answers_are_different(gold, predicted):
    result = run(math500(gold), "\\boxed{" + predicted + "}")
    assert result.content_valid is False
    assert result.error_category == "wrong_final_answer"


def test_a_braced_exponent_is_translated_with_its_brace_closed():
    """Measured defect, repaired.

    The original substitution turned ``^{`` into ``**(`` and left the closing
    brace alone, so ``x^{2}+1`` became ``x**(2}+1``. Every braced exponent in a
    probe was then scored wrong, including ``3^{4}`` against a gold of ``81``.
    On MATH-500 that penalises whichever arm writes braces, which is a scorer
    artefact masquerading as a capability difference.
    """
    from sciencemath.comparability.scorers import _to_python_expression

    assert _to_python_expression("x^{2}+1") == "x**(2)+1"
    assert _to_python_expression("2^{10}") == "2**(10)"
    # Nested exponents close in the right order.
    assert _to_python_expression("x^{2^{3}}") == "x**(2**(3))"
    # An unclosed brace is left alone rather than given a stray parenthesis.
    assert _to_python_expression("x^{2") == "x**{2"
    assert math_equivalent("x^{2}+1", "x^2+1") == (True, "symbolic")


def test_an_unclosed_brace_never_becomes_a_false_match():
    """The failure mode of a brace repair is inventing equivalence."""
    for gold, predicted in [(r"x^{2{", r"x^{2"), ("1", r"x^{2"), ("2", "{2}")]:
        assert math_equivalent(predicted, gold)[0] is False


def test_an_answer_outside_the_whitelist_falls_back_instead_of_guessing():
    """An integral is not something this scorer can compare safely."""
    result = run(math500(r"\frac{1}{2}"),
                 r"The area is \boxed{\int_0^1 x\,dx}.")
    assert result.scorer_tier in ("symbolic", "string_fallback")
    assert result.content_valid is False


def test_an_answer_without_a_box_is_a_schema_failure_but_still_read():
    """Refusing to read it would turn a format difference into a capability
    difference, which is the one thing this layer must never do."""
    result = run(math500(r"\frac{1}{2}"), r"Therefore the answer is \frac{1}{2}")
    assert result.content_valid is True
    assert result.schema_valid is False


# ---------------------------------------------------------------------------
# category 9 — ARC, option choice
# ---------------------------------------------------------------------------
def test_the_gold_letter_scores_correct():
    result = run(mcq(gold_label="A"), "The answer is A.")
    assert result.content_valid is True
    assert result.schema_valid is True
    assert result.scorer_tier == "label_equality"


def test_another_letter_scores_wrong():
    result = run(mcq(gold_label="A"), "B")
    assert result.content_valid is False
    assert result.error_category == "wrong_final_answer"


def test_naming_the_correct_option_in_words_is_correct_but_not_schema_valid():
    """A text answer is a correct answer given in the wrong format."""
    subject = mcq(gold_label="A",
                  choices=(("A", "gravity"), ("B", "magnetism"),
                           ("C", "friction"), ("D", "pressure")))
    result = run(subject, "gravity")
    assert result.content_valid is True
    assert result.schema_valid is False


def test_naming_a_wrong_option_in_words_is_wrong():
    subject = mcq(gold_label="A",
                  choices=(("A", "gravity"), ("B", "magnetism"),
                           ("C", "friction"), ("D", "pressure")))
    result = run(subject, "friction")
    assert result.content_valid is False


def test_two_named_options_are_an_invalid_option_not_a_guess():
    result = run(mcq(gold_label="A"), "A or C")
    assert result.content_valid is False
    assert result.error_category == "invalid_option"


def test_a_non_answer_fails_closed_rather_than_matching_by_accident():
    """The dangerous direction: prose must not manufacture a correct answer."""
    for raw in ("", "   ", "\n\n", "???", "None", "The correct answer is 42."):
        result = run(mcq(gold_label="A"), raw)
        assert result.content_valid is False, raw
        assert result.schema_valid is False, raw
        assert result.error_category in ("answer_extraction_failure",
                                         "abstention")


def test_a_cue_anchored_letter_is_read_over_a_later_bare_one():
    """Documented leniency, applied to both arms.

    "The answer is A. Also B." is read as A: only the first letter is
    cue-anchored, and the second is bare prose. Tightening this by scanning
    the whole sentence would misfire on the far more common "the answer is A,
    not C" — which names two letters and commits to one — so the leniency is
    kept and disclosed rather than traded for a worse error.
    """
    result = run(mcq(gold_label="A"), "The answer is A. Also B.")
    assert result.content_valid is True


def test_a_truncated_multiple_choice_generation_says_so():
    result = run(mcq(gold_label="A"), "I think the answer is", finish="length")
    assert result.error_category == "truncated_generation"


# ---------------------------------------------------------------------------
# category 10 — SciQ, option choice with a textual answer form
# ---------------------------------------------------------------------------
def test_the_gold_label_is_correct():
    result = run(sciq("C"), "The answer is C.")
    assert result.content_valid is True and result.schema_valid is True


def test_the_gold_option_text_is_correct():
    result = run(sciq("C"), "gamma")
    assert result.content_valid is True
    assert result.schema_valid is False


def test_a_wrong_option_text_is_wrong():
    result = run(sciq("C"), "beta")
    assert result.content_valid is False


def test_a_wrong_label_is_wrong():
    result = run(sciq("C"), "The answer is A.")
    assert result.content_valid is False
    assert result.schema_valid is True


# ---------------------------------------------------------------------------
# category 20 — schema and content are separate facts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("make,raw,expected", [
    # (item factory, generation, (content_valid, schema_valid))
    (lambda: gsm8k("72"), "#### 72", (True, True)),
    (lambda: gsm8k("72"), "#### 18", (False, True)),
    (lambda: gsm8k("72"), "So it is 72.", (True, False)),
    (lambda: gsm8k("72"), "#### 18", (False, True)),
    (lambda: math500(), r"\boxed{\frac{1}{2}}", (True, True)),
    (lambda: math500(), r"\boxed{1}", (False, True)),
    (lambda: math500(), r"the answer is \frac{1}{2}", (True, False)),
    (lambda: mcq(gold_label="A"), "The answer is A.", (True, True)),
    (lambda: mcq(gold_label="A"), "The answer is B.", (False, True)),
    (lambda: mcq(gold_label="A"), "B", (False, True)),
])
def test_every_combination_of_the_two_flags_is_reachable(make, raw, expected):
    """The brief makes the separation absolute, so the cross-tabulation must
    have content in all four cells — a flag that is always equal to the other
    is not a separate flag."""
    result = run(make(), raw)
    assert (result.content_valid, result.schema_valid) == expected


def test_a_perfectly_formatted_wrong_answer_is_not_a_protocol_success():
    """Stated as its own test because it is the brief's explicit rule."""
    result = run(gsm8k("72"), "#### 18")
    assert result.schema_valid is True
    assert result.content_valid is False
    assert result.error_category != "correct"


def test_content_validity_never_reads_the_working():
    """A right number reached by a wrong route is still the right answer —
    the reasoning question is answered by the error taxonomy, not here."""
    result = run(gsm8k("72"), "She adds 5 and 5 to get 72.\n#### 72")
    assert result.content_valid is True


def test_the_gold_appearing_in_the_working_is_recorded_not_rewarded():
    """The model wrote the right value and then committed to another one.

    Recorded as a boolean on the row because it separates "reached the right
    value and reported something else" from "never got there" — useful when
    the T32 handoff is built. It is not an error category and it never turns
    the row correct.
    """
    result = run(gsm8k("72"),
                 "It should have been 72, but after recounting she has 18.")
    assert result.content_valid is False
    assert any("gold value present" in note for note in result.notes)


def test_implicit_multiplication_is_normalised_for_the_symbolic_tier():
    """``2\\pi`` is how LaTeX writes it; Python needs the operator."""
    from sciencemath.comparability.scorers import _to_python_expression

    assert _to_python_expression(r"2\pi") == "2*pi"
    assert _to_python_expression(r"(x+1)(x-1)") == "(x+1)*(x-1)"
    assert _to_python_expression(r"2(x+1)") == "2*(x+1)"
    # A function call is not a product: the name is not preceded by a number.
    assert _to_python_expression(r"\sqrt{2}") == "sqrt(2)"
    assert math_equivalent(r"2\cdot\pi", r"2\pi") == (True, "symbolic")


# ---------------------------------------------------------------------------
# category 8 repair — sympy's __eq__ must not crash the scoring pass
# ---------------------------------------------------------------------------
def test_a_bare_word_symbolic_compare_decides_instead_of_crashing():
    """The defect this pins: ``sympify`` of a bare word resolves the word in
    sympy's namespace, so ``\text{Ellipse}`` (after normalisation strips the
    wrapper) became the *GeometryEntity class*, and ``first == second`` —
    outside any ``try`` — raised ``TypeError`` from sympy's own ``__eq__``,
    aborting the whole scoring pass. The module's rule was already "an engine
    that raises is an engine that cannot decide"; the crash broke the rule.

    The real row is MATH-500 item ``t31-math500-854c4ef180cb`` (base arm):
    model answered ``\text{Ellipse}``, gold is ``\text{ellipse}``."""
    from sciencemath.comparability.scorers import _symbolic_equal

    assert _symbolic_equal("Ellipse", "ellipse") is None
    assert math_equivalent(r"\text{Ellipse}", r"\text{ellipse}") == \
        (False, "string_fallback")


def test_the_crashing_real_row_scores_without_raising():
    """End to end on the row that took the first scoring pass down: same
    extraction, same verdict path, no exception."""
    subject = math500(r"\text{ellipse}")
    result = run(subject, r"$\boxed{\text{Ellipse}}$")
    assert result.content_valid is False
