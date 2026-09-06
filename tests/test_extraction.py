"""T2 answer extraction and matching tests (deterministic scoring only).

Tag-based test inputs are built from the THINK_OPEN / THINK_CLOSE constants
(constructed in the module under test) so no file ever contains mangleable
literal reasoning tags.
"""
from sciencemath.evaluation.extraction import (
    THINK_CLOSE,
    THINK_OPEN,
    answers_match,
    extract_answer,
    normalize_symbolic,
    signals_uncertainty,
    strip_think_block,
)

NL = "\n"


def think_block(reasoning: str) -> str:
    return THINK_OPEN + reasoning + THINK_CLOSE


# ------------------------------------------------------------------ think
def test_strip_think_closed_full_block():
    raw = think_block("reasoning here") + NL + "Final answer: 4"
    assert strip_think_block(raw).startswith("Final answer")


def test_strip_think_same_line():
    raw = THINK_OPEN + "reasoning" + THINK_CLOSE + "4"
    assert strip_think_block(raw) == "4"


def test_strip_think_empty_block():
    raw = THINK_OPEN + THINK_CLOSE + "4"
    assert strip_think_block(raw) == "4"


def test_strip_think_multiline_visible_answer():
    raw = (THINK_OPEN + NL + "reasoning" + NL + THINK_CLOSE + NL +
           "The answer is 4." + NL + NL +
           "Explanation: because 2 + 2 = 4.")
    out = strip_think_block(raw)
    assert out.startswith("The answer is 4.")
    assert "Explanation" in out


def test_strip_think_unclosed_returns_empty():
    raw = THINK_OPEN + "never closed, no final answer"
    assert strip_think_block(raw) == ""


def test_strip_think_absent_passthrough():
    raw = "Final answer: 4"
    assert strip_think_block(raw) == raw


def test_strip_think_closed_takes_last_block():
    raw = think_block("first") + " " + think_block("second") + "final"
    assert strip_think_block(raw) == "final"


def test_ordinary_word_think_untouched():
    raw = "I think the answer is 4."
    assert strip_think_block(raw) == raw


# -------------------------------------------------------------- extraction
def test_extract_boxed_math():
    raw = "We compute 2+2 = 4." + NL + "\\boxed{4}"
    assert extract_answer(raw, "numeric") == "4"


def test_extract_boxed_nested_braces():
    raw = "steps..." + NL + "\\boxed{\\frac{1}{2}}"
    assert extract_answer(raw, "numeric") == "\\frac{1}{2}"


def test_extract_last_boxed_wins():
    raw = "\\boxed{3} then corrected: \\boxed{4}"
    assert extract_answer(raw, "numeric") == "4"


def test_extract_hash_marker_gsm8k():
    raw = "So she has 5 + 3 = 8 apples." + NL + "#### 8"
    assert extract_answer(raw, "numeric") == "8"


def test_extract_answer_is_prose():
    raw = "After simplification, the answer is 42"
    assert extract_answer(raw, "numeric") == "42"


def test_extract_bare_last_line():
    raw = NL.join(["step", "step", "4"])
    assert extract_answer(raw, "numeric") == "4"


def test_extract_none_when_nothing_gradable():
    # open think tag with no close and no visible answer: extraction fails
    raw = THINK_OPEN + "thinking only, no answer"
    assert extract_answer(raw, "numeric") is None


def test_extract_in_think_block_answer_is_not_scored():
    # a wrong draft INSIDE the hidden reasoning must never be extracted
    raw = (think_block("Maybe the answer is 7." + NL +
                       "After checking, it is 4.") + NL +
           "Final answer: 4")
    assert extract_answer(raw, "numeric") == "4"


def test_extract_visible_wrong_answer_wins_over_hidden():
    # hidden block contains the right answer, visible text says 7: score 7
    raw = think_block("The correct answer is 4.") + NL + "Final answer: 7"
    extracted = extract_answer(raw, "numeric")
    assert extracted == "7"
    assert answers_match("4", extracted) is False


def test_extract_mcq_letter():
    raw = "The correct option is C." + NL + "\\boxed{C}"
    choices = ["a", "b", "c", "d"]
    assert extract_answer(raw, "multiple_choice", choices) == "C"


def test_extract_mcq_invalid_letter_is_none():
    choices = ["a", "b", "c", "d"]                      # letters A-D only
    assert extract_answer("\\boxed{E}", "multiple_choice",
                          choices) is None


def test_extract_mcq_think_then_letter():
    choices = ["x", "y", "z"]
    raw = think_block("narrowing down...") + NL + "\\boxed{B}"
    assert extract_answer(raw, "multiple_choice", choices) == "B"


# ---------------------------------------------------------------- matching
def test_answers_match_numeric_tolerance():
    assert answers_match("0.3333333333", "0.33333333331")


def test_answers_match_commas_and_dollars():
    assert answers_match("$72,000", "72000")


def test_answers_match_identical_latex_frac():
    assert answers_match("\\frac{1}{2}", "\\frac{1}{2}")


def test_answers_match_frac_vs_decimal_is_t2_limitation():
    # documented T2 limitation: no symbolic equivalence checking (the T4
    # SymPy verifier adds it) - latex fractions do NOT match decimals
    assert answers_match("\\frac{1}{2}", "0.5") is False


def test_answers_match_text_normalization():
    assert normalize_symbolic("$x = 15$") == "x=15"


def test_answers_match_none_extracted():
    assert answers_match("42", None) is False


# ------------------------------------------------------- uncertainty gate
def test_signals_uncertainty_positive():
    assert signals_uncertainty("I'm sorry, but I cannot determine that.")


def test_signals_uncertainty_negative():
    assert not signals_uncertainty(
        "The population of Berlin in 1876 was 800000.")