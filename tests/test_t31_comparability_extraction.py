"""T31 categories 6, 7, 8, 9, 10 — answer extraction and per-benchmark scoring.

Categories 6 to 10 of the brief are the per-benchmark extraction and scoring
rules: GSM8K numeric normalisation, MATH-500 boxed parsing, ARC option
extraction, SciQ option mapping, and extraction in general. They are tested
together because they are one mechanism wearing five hats, and because the
defects worth catching here are the *shared* ones — a parser that is too
permissive inflates both arms, a parser that is too brittle depresses both.

Two tests below are regression guards for real defects found by running the
frozen adapter before the suite existed:

``test_the_english_article_is_not_read_as_option_a``
    Option labels are upper case. A case-insensitive scan for a bare letter
    reads the article "a" — which appears in nearly every sentence of working
    — as a vote for option A. That would manufacture agreement out of
    grammar, and it would do so more often for whichever arm writes more
    prose.

``test_a_boxed_numeric_answer_is_read_even_though_the_prompt_asked_for_a_hash``
    The frozen adapter answers GSM8K with ``\\boxed{72}`` where the base model
    writes ``#### 72``. Refusing to read the boxed form would convert a
    formatting difference into a capability difference.
"""
from __future__ import annotations

import pytest

from sciencemath.comparability.extractors import (
    extract, extract_choice, extract_math, extract_numeric, normalize_number,
    strip_reasoning,
)
from sciencemath.comparability.scorers import math_equivalent, score

import t31_comparability_support as S


# ---------------------------------------------------------------------------
# category 6 — normalisation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("72", "72"), (" 72 ", "72"), ("1,000", "1000"), ("$18", "18"),
    ("$1,000.00", "1000"), ("0.50", "0.5"), ("72.", "72"), ("-3", "-3"),
    ("50%", "50"), ("", None), ("abc", None), ("nan", None),
])
def test_numbers_normalise_to_a_canonical_form(raw, expected):
    assert normalize_number(raw) == expected


def test_reasoning_blocks_are_not_part_of_the_answer():
    raw = "thinking about it  thinkingwrong track: 9</think>\n#### 18"
    assert "wrong track" not in strip_reasoning(raw)
    assert extract_numeric(raw).answer == "18"


# ---------------------------------------------------------------------------
# category 7 — GSM8K
# ---------------------------------------------------------------------------
def test_the_hash_marker_is_the_primary_rule():
    result = extract_numeric("She sells 18.\n#### 18")
    assert result.ok and result.answer == "18" and result.tier == "hash_marker"


def test_the_last_hash_marker_wins():
    assert extract_numeric("#### 3\nwait, no\n#### 18").answer == "18"


def test_a_missing_marker_falls_back_to_the_last_number():
    result = extract_numeric("So she sells 18 eggs each day.")
    assert result.ok and result.answer == "18"
    assert result.tier == "last_number_fallback"


def test_a_boxed_numeric_answer_is_read_even_though_the_prompt_asked_for_a_hash():
    """The regression guard for the frozen adapter's house style."""
    result = extract_numeric("Natalia sold 48+24 = 72 clips.\n\n"
                             "Final answer: \\boxed{72}")
    assert result.ok and result.answer == "72"
    assert result.tier == "boxed_fallback"


def test_a_generation_with_no_number_is_an_extraction_failure():
    result = extract_numeric("I am not able to solve this one.")
    assert result.status == "FAILED"


def test_an_empty_generation_is_an_extraction_failure():
    assert extract_numeric("   ").status == "FAILED"


# ---------------------------------------------------------------------------
# category 8 — MATH-500
# ---------------------------------------------------------------------------
def test_the_last_boxed_expression_is_the_answer():
    assert extract_math("first \\boxed{1}\nthen \\boxed{5}").answer == "5"


def test_nested_braces_are_balanced():
    result = extract_math("So the value is \\boxed{\\frac{1}{2}}.")
    assert result.answer == "\\frac{1}{2}"
    assert result.tier == "boxed"


def test_deeply_nested_braces_are_balanced():
    assert extract_math("\\boxed{\\frac{\\sqrt{2}}{3}}").answer == \
        "\\frac{\\sqrt{2}}{3}"


def test_an_answer_cue_is_a_fallback_for_math():
    result = extract_math("We compute it.\nThe answer is 5.")
    assert result.ok and result.tier == "answer_cue_fallback"


def test_a_bare_last_line_is_the_last_resort_for_math():
    result = extract_math("Working...\n42")
    assert result.ok and result.answer == "42"
    assert result.tier == "last_line_fallback"


def test_math_with_no_answer_at_all_fails():
    assert extract_math("").status == "FAILED"


@pytest.mark.parametrize("predicted,gold,expected", [
    ("\\frac{1}{2}", "\\frac{1}{2}", True),
    ("0.5", "\\frac{1}{2}", True),
    ("\\frac{2}{4}", "\\frac{1}{2}", True),
    ("2", "\\frac{1}{2}", False),
    ("3", "4", False),
    ("(3,\\frac{\\pi}{2})", "(3,\\frac{\\pi}{2})", True),
])
def test_math_equivalence_is_layered_and_deterministic(predicted, gold,
                                                       expected):
    verdict, tier = math_equivalent(predicted, gold)
    assert verdict is expected, (verdict, tier)
    # Determinism: the same pair resolves the same way every time.
    assert math_equivalent(predicted, gold) == (verdict, tier)


def test_symbolic_equivalence_is_attempted_only_for_safe_constructs():
    """An integral is outside the whitelist, so it must not reach sympy."""
    _, tier = math_equivalent("\\int_0^1 x dx", "\\frac{1}{2}")
    assert tier == "string_fallback"


# ---------------------------------------------------------------------------
# categories 9 and 10 — ARC and SciQ option extraction
# ---------------------------------------------------------------------------
def test_a_cued_letter_is_read():
    assert extract_choice("Answer: B", ["A", "B", "C", "D"]).answer == "B"


def test_a_parenthesised_letter_is_read():
    assert extract_choice("C) oxidants", ["A", "B", "C", "D"]).answer == "C"


def test_a_boxed_letter_is_read():
    assert extract_choice("Answer: \\boxed{A}", ["A", "B", "C", "D"]
                          ).answer == "A"


def test_a_lowercase_boxed_letter_is_read():
    assert extract_choice("\\boxed{c}", ["A", "B", "C", "D"]).answer == "C"


def test_a_bare_letter_on_its_own_line_is_read():
    assert extract_choice("Let me think.\n\nD\n", ["A", "B", "C", "D"]
                          ).answer == "D"


def test_the_english_article_is_not_read_as_option_a():
    """The regression guard: 'a' is a word, not a vote for option A."""
    result = extract_choice(
        "This is a question about a process in a plant cell.",
        ["A", "B", "C", "D"])
    assert result.status == "FAILED", result.to_dict()


def test_lowercase_prose_letters_do_not_become_options():
    result = extract_choice(
        "the carbon cycle is important because a lot of carbon moves "
        "between a few reservoirs", ["A", "B", "C", "D"])
    assert result.status == "FAILED", result.to_dict()


def test_two_different_options_are_ambiguous_not_guessed():
    result = extract_choice("It is either A or B.", ["A", "B", "C", "D"])
    assert result.status == "AMBIGUOUS"
    assert "A" in result.note and "B" in result.note


def test_the_option_text_written_out_in_full_is_matched():
    choices = (("A", "sunlight"), ("B", "water"), ("C", "soil"),
               ("D", "air"))
    result = extract_choice("The answer is water.", ["A", "B", "C", "D"],
                            choices)
    assert result.answer == "B"


def test_a_letter_outside_the_item_alphabet_is_not_accepted():
    """A 4-option item must not accept 'E'."""
    assert extract_choice("E", ["A", "B", "C", "D"]).status == "FAILED"


def test_arc_items_with_numeric_labels_are_read_with_those_labels():
    assert extract_choice("The answer is 3.", ["1", "2", "3", "4"]
                          ).answer == "3"


# ---------------------------------------------------------------------------
# units and codes are not option votes
# ---------------------------------------------------------------------------
def test_a_real_generation_is_not_ambiguous_because_it_quotes_a_temperature():
    """The generation that found this defect, verbatim from a base-model run.

    The model answered D and then explained. The ``C`` of ``20°C`` was read as
    a competing option, so a correct answer was recorded as an extraction
    failure — a parsing artefact charged to the model, on both arms.
    """
    raw = "D) The average high temperature in May is 20°C."
    assert extract_choice(raw, ["A", "B", "C", "D"]).answer == "D"


def test_a_mis_decoded_degree_sign_still_binds():
    """The same generation as the tokenizer actually returned it: the degree
    sign came back as U+FFFD, which no letter-or-digit boundary excludes."""
    raw = "D) The average high temperature in May is 20�C."
    assert extract_choice(raw, ["A", "B", "C", "D"]).answer == "D"


@pytest.mark.parametrize("raw,answer", [
    ("The temperature rises to 20°C.", None),      # a unit, with no option
    ("A) 5V is the potential difference.", "A"),
    ("B) The 3D model is printed.", "B"),
    ("C) It is a 2D projection.", "C"),
])
def test_a_letter_glued_to_a_unit_is_not_an_option(raw, answer):
    result = extract_choice(raw, ["A", "B", "C", "D"])
    assert result.answer == answer, result.to_dict()


def test_separators_still_delimit_an_option_letter():
    """The fix must not eat the decorated forms the prompts actually provoke."""
    for raw in ("(C)", "**C**", '"C"', "C.", "- C", "Answer: C"):
        assert extract_choice(raw, ["A", "B", "C", "D"]).answer == "C", raw


def test_a_boxed_unit_is_not_read_as_its_last_letter():
    """``\\boxed{20°C}`` is a temperature in a box, not option C."""
    result = extract_choice("\\boxed{20°C}", ["A", "B", "C", "D"])
    assert result.answer != "C", result.to_dict()


def test_two_genes_do_not_cancel_out_the_answer():
    """A bound letter is not a vote, so it cannot manufacture ambiguity."""
    result = extract_choice("B) both genes D3 and C4 are expressed.",
                            ["A", "B", "C", "D"])
    assert result.answer == "B", result.to_dict()


# ---------------------------------------------------------------------------
# category 13 — malformed output
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", [
    "", "   ", "\n\n", "!!!", "```json\n{}\n```", "None", "N/A",
    "I cannot determine the answer from the information given.",
])
def test_malformed_or_uninformative_output_fails_closed(raw):
    assert extract(S.item(), "numeric", raw).status == "FAILED"
    assert extract(S.item(), "math", raw).status in ("FAILED", "OK")


def test_extraction_never_raises_on_arbitrary_text():
    for raw in ("\\boxed{", "####", "))))", "\\frac{1}{", "\x00\x01",
                "A" * 5000, "#####", "$"):
        extract(S.item(), "numeric", raw)
        extract(S.item(), "math", raw)
        extract(S.mcq(), "multiple_choice", raw)


# ---------------------------------------------------------------------------
# category 20 — schema validity is not content validity
# ---------------------------------------------------------------------------
def test_a_formatted_wrong_answer_is_a_content_failure_not_a_protocol_success():
    scored = score(S.item(gold="72"), "numeric",
                   extract_numeric("#### 18"), "#### 18")
    assert scored.schema_valid is True
    assert scored.content_valid is False
    assert scored.error_category == "wrong_final_answer"


def test_a_correct_answer_in_the_wrong_format_is_a_schema_failure():
    scored = score(S.item(gold="72"), "numeric",
                   extract_numeric("So the total is 72."),
                   "So the total is 72.")
    assert scored.content_valid is True
    assert scored.schema_valid is False


def test_the_two_flags_are_independent_on_every_combination():
    correct_formatted = score(S.item(gold="72"), "numeric",
                              extract_numeric("#### 72"), "#### 72")
    assert (correct_formatted.content_valid,
            correct_formatted.schema_valid) == (True, True)

    wrong_formatted = score(S.item(gold="72"), "numeric",
                            extract_numeric("#### 18"), "#### 18")
    assert (wrong_formatted.content_valid,
            wrong_formatted.schema_valid) == (False, True)

    correct_unformatted = score(S.item(gold="72"), "numeric",
                                extract_numeric("total is 72"), "total is 72")
    assert (correct_unformatted.content_valid,
            correct_unformatted.schema_valid) == (True, False)

    wrong_unformatted = score(S.item(gold="72"), "numeric",
                              extract_numeric("total is 18"), "total is 18")
    assert (wrong_unformatted.content_valid,
            wrong_unformatted.schema_valid) == (False, False)


def test_a_multiple_choice_answer_is_scored_by_label_equality():
    item = S.mcq(gold_label="C")
    assert score(item, "multiple_choice",
                 extract_choice("The answer is C.", "ABCD"), "The answer is C."
                 ).content_valid is True
    assert score(item, "multiple_choice",
                 extract_choice("The answer is A.", "ABCD"), "The answer is A."
                 ).content_valid is False


def test_a_truncated_generation_is_labelled_as_such():
    scored = score(S.item(), "numeric", extract_numeric("Let me work through"),
                   "Let me work through", finish_reason="length")
    assert scored.error_category == "truncated_generation"


def test_an_abstention_is_labelled_as_such():
    raw = "I cannot determine the answer from the information given."
    scored = score(S.item(), "numeric", extract_numeric(raw), raw)
    assert scored.error_category == "abstention"


def test_the_gold_appearing_in_the_working_is_recorded_but_not_rewarded():
    raw = "48 + 24 = 72, and then I divide by 10 to get 7.2\n#### 7.2"
    scored = score(S.item(gold="72"), "numeric", extract_numeric(raw), raw)
    assert scored.content_valid is False
    assert "gold value present in the working but not reported" in scored.notes


def test_a_model_is_never_its_own_judge():
    """No code path in the scoring layer may call a model."""
    import ast
    import pathlib

    package = pathlib.Path(__file__).resolve().parents[1] / "src" / \
        "sciencemath" / "comparability"
    offenders: list[str] = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] in ("openai", "anthropic", "cohere",
                                          "litellm", "ollama", "requests"):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders
