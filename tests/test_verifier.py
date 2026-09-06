"""T4 verifier tests — including the mandated FALSE-PASS battery.

The false-PASS rate is a critical T4 metric (target: near zero). The
TestFalsePassProtection class below is the evidence: every wrong or
garbage answer must return FAIL or UNKNOWN, never PASS.
"""
import pytest

from sciencemath.tools.verifier import (parse_answer, verify_answer,
                                        verify_model_output)

# (extracted, expected, answer_type, wanted verdict)
CORRECT_CASES = [
    (r"\frac{1}{2}", "0.5", "exact_answer", "PASS"),
    ("3/4", "0.75", "exact_answer", "PASS"),
    ("(x-1)*(x+1)", "x**2 - 1", "exact_answer", "PASS"),
    ("3.14159", r"\pi", "exact_answer", "PASS"),          # 6 sig digits
    ("5 km", "5 kilometers", "exact_answer", "PASS"),
    ("3 km", "3000 m", "exact_answer", "PASS"),           # unit conversion
    ("25%", "0.25", "exact_answer", "PASS"),
    ("{2, 3}", "2, 3", "exact_answer", "PASS"),
    ("x = 4", "2*x = 8", "exact_answer", "PASS"),
    ("C", "C", "multiple_choice", "PASS"),
    ("cannot be determined", "cannot be determined", "uncertainty", "PASS"),
    ("mitochondria", "mitochondria", "short_text", "PASS"),
    ("\\boxed{42}", "42", "exact_answer", "PASS"),
    ("2, 5", "5, 2", "exact_answer", "PASS"),             # order-independent
]

WRONG_CASES = [
    ("x**2 + 1", "x**2 - 1", "exact_answer"),
    ("2.718", "e", "exact_answer"),
    ("3.14", r"\pi", "exact_answer"),
    ("22/7", r"\pi", "exact_answer"),
    ("0.3333", "1/3", "exact_answer"),
    ("5 km", "5 kg", "exact_answer"),                     # wrong dimension
    ("5 km", "7 km", "exact_answer"),
    ("25%", "0.5", "exact_answer"),
    ("{2, 3}", "2, 4", "exact_answer"),
    ("2", "1, 2", "exact_answer"),                        # incomplete set
    ("{2, 3, 4}", "2, 3", "exact_answer"),                # extra solution
    ("x = 5", "2*x = 8", "exact_answer"),
    ("42", "41", "exact_answer"),
    ("C", "B", "multiple_choice"),
    ("42", "cannot be determined", "uncertainty"),
    ("nucleus", "mitochondria", "short_text"),
    ("2x+1", "2x-1", "exact_answer"),
]

UNKNOWN_CASES = [
    ("", "0.5", "exact_answer"),
    ("1/0", "0.5", "exact_answer"),                       # parses to zoo
    (None, "0.5", "exact_answer"),
    ("blah blah no answer here at all", r"\pi", "exact_answer"),
    # unparsed model answer vs parseable reference: cannot interpret what
    # the model answered -> UNKNOWN (decisive FAIL would grade the prose
    # extraction heuristic, not the model)
    ("hello world", "42", "exact_answer"),
]


class TestVerdictBattery:
    @pytest.mark.parametrize("ext,exp,typ,want", CORRECT_CASES)
    def test_correct(self, ext, exp, typ, want):
        assert verify_answer(ext, exp, typ)["verdict"] == want

    @pytest.mark.parametrize("ext,exp,typ", WRONG_CASES)
    def test_wrong(self, ext, exp, typ):
        assert verify_answer(ext, exp, typ)["verdict"] == "FAIL"

    @pytest.mark.parametrize("ext,exp,typ", UNKNOWN_CASES)
    def test_unknown(self, ext, exp, typ):
        assert verify_answer(ext, exp, typ)["verdict"] == "UNKNOWN"


class TestFalsePassProtection:
    """Critical T4 gate: wrong answers NEVER get PASS."""

    @pytest.mark.parametrize("ext,exp,typ",
                             WRONG_CASES + UNKNOWN_CASES)
    def test_no_false_pass(self, ext, exp, typ):
        assert verify_answer(ext, exp, typ)["verdict"] != "PASS"

    def test_sign_flip_fails(self):
        assert verify_answer("-5", "5")["verdict"] == "FAIL"

    def test_order_of_magnitude_fails(self):
        assert verify_answer("100", "1000")["verdict"] == "FAIL"

    def test_transposed_digits_fail(self):
        assert verify_answer("1234", "1243")["verdict"] == "FAIL"

    def test_decimal_truncation_fails(self):
        assert verify_answer("0.1666", "1/6")["verdict"] == "FAIL"

    def test_wrong_unit_fails_even_if_magnitude_matches(self):
        assert verify_answer("5 kg", "5 km")["verdict"] == "FAIL"

    def test_wrong_temperature_offset_fails(self):
        # 25 degF vs 25 degC must not pass (affine, not multiplicative)
        assert verify_answer("25 degF", "25 degC")["verdict"] == "FAIL"

    def test_prose_never_passes_numeric(self):
        assert verify_answer("The answer is big", "1000")["verdict"] != "PASS"

    def test_timeout_is_unknown_not_pass(self):
        # tiny timeout on a hard equivalence must degrade to UNKNOWN
        r = verify_answer("sin(x)**7 + 1", "cos(x)**7 + 1", "exact_answer",
                          timeout_s=0.001)
        assert r["verdict"] in ("UNKNOWN", "FAIL")    # decisive either way
        assert r["verdict"] != "PASS" or r["method"] != "timeout"


class TestAnswerParsing:
    def test_kinds(self):
        assert parse_answer("5").kind == "number"
        assert parse_answer("5 km").kind == "quantity"
        assert parse_answer("25%").kind == "percent"
        assert parse_answer("x**2").kind == "expression"
        assert parse_answer("x = 4").kind == "expression"   # Eq wrapped
        assert parse_answer("{2, 3}").kind == "solution_set"
        # a lone identifier is a legitimate symbolic expression; only
        # multi-word prose fails to parse
        assert parse_answer("mitochondria").kind == "expression"
        assert parse_answer("no answer here at all").kind == "unparsed"
        assert parse_answer("").kind == "unparsed"

    def test_fraction_not_misparsed_as_quantity(self):
        # regression: "3/4" must be the number 0.75, not quantity "3" "/4"
        obj = parse_answer("3/4")
        assert obj.kind == "number"
        assert obj.value == 0.75

    def test_slash_junk_not_a_unit(self):
        # regression: "1/0" must not parse as quantity with unit "/0"
        assert parse_answer("1/0").kind != "quantity"


class TestRawOutputPreservation:
    def test_verify_model_output_preserves_raw(self):
        raw = ("We compute step by step.\n"
               "The final answer is \\boxed{\\frac{1}{2}}\n"
               "because half of one is one half.")
        rec = verify_model_output(raw, "0.5")
        assert rec["raw_output_preserved"] == raw      # byte-identical
        assert rec["verdict"] == "PASS"
        assert rec["extracted_answer"] == r"\frac{1}{2}"

    def test_raw_never_modified_even_when_wrong(self):
        raw = "I think it is \\boxed{41}."
        rec = verify_model_output(raw, "42")
        assert rec["raw_output_preserved"] == raw
        assert rec["verdict"] == "FAIL"

    def test_think_block_not_graded(self):
        raw = ("<think>let me try 999...</think>\n"
               "Final answer: \\boxed{42}")
        rec = verify_model_output(raw, "42")
        assert rec["verdict"] == "PASS"
        assert rec["extracted_answer"] == "42"

    def test_no_extraction_is_unknown(self):
        rec = verify_model_output("I truly cannot solve this.", "42")
        assert rec["verdict"] == "UNKNOWN"

    def test_record_shape(self):
        rec = verify_model_output("\\boxed{2}", "2")
        for key in ("raw_output_preserved", "extracted_answer",
                    "expected_answer", "answer_type", "verdict", "method",
                    "detail"):
            assert key in rec


class TestUncertaintyCalibration:
    def test_uncertainty_answer_against_marker(self):
        assert verify_answer("cannot be determined",
                             "cannot be determined", "uncertainty")["verdict"] \
            == "PASS"

    def test_confident_answer_against_uncertainty_marker_fails(self):
        assert verify_answer("42", "cannot be determined",
                             "uncertainty")["verdict"] == "FAIL"

    def test_uncertainty_against_concrete_fails(self):
        assert verify_answer("not enough information", "42",
                             "uncertainty")["verdict"] == "FAIL"