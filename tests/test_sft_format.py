"""T3 SFT formatting tests: canonical format, budgets, closure markers."""
from sciencemath.training.sft_format import (
    FINAL_MATH,
    REASONING_BUDGETS,
    budget_class,
    build_target,
    general_response,
    last_boxed,
    math_response,
    render_training_text,
    science_response,
    strip_gsm8k_solution,
    within_budget,
)


class StubTokenizer:
    """Minimal chat-template tokenizer for format tests."""

    def apply_chat_template(self, messages, tokenize=False,
                            add_generation_prompt=False,
                            enable_thinking=None):
        parts = []
        for m in messages:
            parts.append(f"<|user|>{m['content']}<|end|>"
                         if m["role"] == "user"
                         else f"<|assistant|>{m['content']}<|end|>")
        if add_generation_prompt:
            parts.append("<|assistant|>")
        return "".join(parts)


def test_math_response_has_explicit_closure():
    t = math_response("Add 2 and 2.", "4")
    assert t == "Add 2 and 2.\n\nFinal answer: \\boxed{4}"
    assert t.startswith("Add 2 and 2.")
    assert t.endswith("Final answer: \\boxed{4}")


def test_science_response_answer_first():
    t = science_response("Water boils at 100 C.", "100 C")
    assert t.startswith("Answer: \\boxed{100 C}")
    assert "Water boils" in t


def test_general_response_closure():
    t = general_response("yes", "Because all A are B.")
    assert "\\boxed{yes}" in t and "Because all A are B." in t


def test_last_boxed_balanced_braces():
    assert last_boxed(r"\boxed{\frac{1}{2}}") == r"\frac{1}{2}"
    assert last_boxed(r"a \boxed{7} b \boxed{x+y}") == "x+y"
    assert last_boxed("no box here") is None


def test_gsm8k_solution_split_strips_calculator_annotations():
    raw = "She has 2<<2*1=2>> apples.\n#### 2"
    sol, final = strip_gsm8k_solution(raw)
    assert final == "2"
    assert "<<" not in sol and "apples" in sol


def test_gsm8k_missing_closure_marker_is_rejected():
    assert strip_gsm8k_solution("just some steps") is None


def test_budget_classes():
    assert budget_class("mathematics") == "math"
    assert budget_class("general_science") == "science"
    assert budget_class("scientific_reasoning", "instruction_following") == "general"
    assert budget_class("scientific_reasoning", "unit_conversion") == "general"
    assert budget_class("scientific_reasoning", "scientific_reasoning") == "science"


def test_over_budget_target_is_rejected_not_truncated():
    rec = {"domain": "mathematics", "source": "math-competition",
           "answer": "5", "solution": "x" * 2000}
    target, reason = build_target(rec)
    assert target is None
    assert "budget" in reason


def test_within_budget_boundaries():
    long_math = "x" * 1500 + " Final answer: \\boxed{1}"
    assert within_budget(long_math, "mathematics")
    assert not within_budget(long_math + "x" * 200, "mathematics")


def test_build_target_gsm8k_flow():
    rec = {"domain": "mathematics", "source": "gsm8k",
           "question": "q", "answer": "2*3=6\n#### 6"}
    target, reason = build_target(rec)
    assert target is not None and target.endswith("Final answer: \\boxed{6}")


def test_render_training_text_has_no_think_block():
    rendered = render_training_text(StubTokenizer(), "What is 2+2?", "Final answer: \\boxed{4}")
    assert "think" not in rendered
    assert "<|user|>What is 2+2?" in rendered
    assert "Final answer: \\boxed{4}" in rendered


def test_science_target_without_explanation_still_closes():
    rec = {"domain": "general_science", "source": "sciq",
           "question": "q", "answer": "pollination", "explanation": ""}
    target, reason = build_target(rec)
    assert target == "Answer: \\boxed{pollination}"


def test_math_without_extractable_answer_rejected():
    rec = {"domain": "mathematics", "source": "math-competition",
           "question": "q", "answer": "", "solution": "no box here"}
    target, reason = build_target(rec)
    assert target is None and "no extractable" in reason