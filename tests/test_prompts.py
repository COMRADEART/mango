"""T2 prompt standardization: identical evaluation_content for all models,
chat-template rendering isolated, MCQ choices rendered as A-E lines.

Test fakes use plain '[U]...[/A]' markers instead of real chat special
tokens, so nothing here depends on renderer-sensitive sequences.
"""
from sciencemath.evaluation.prompts import (
    build_evaluation_content,
    render_for_model,
)


class FakeTokenizer:
    """Minimal chat-template stand-in (jinja2 not required)."""

    def apply_chat_template(self, messages, tokenize=False,
                            add_generation_prompt=True, **kwargs):
        content = messages[0]["content"]
        thinking = kwargs.get("enable_thinking")
        suffix = "[thinking=" + str(thinking) + "]" if thinking is not None \
            else ""
        return "[U]" + content + suffix + "[/A]"


def test_math_content_has_boxed_instruction():
    c = build_evaluation_content("What is 3+3?", "numeric")
    assert "What is 3+3?" in c
    assert "\\boxed{}" in c


def test_mcq_content_lists_choices_and_letter_instruction():
    c = build_evaluation_content("Pick one", "multiple_choice",
                                 ["sun", "moon", "mars"])
    assert "A. sun" in c and "B. moon" in c and "C. mars" in c
    assert "\\boxed{C}" in c        # example letter in instruction


def test_content_identical_across_calls():
    a = build_evaluation_content("Q?", "numeric")
    b = build_evaluation_content("Q?", "numeric")
    assert a == b                   # standardization guarantee


def test_render_wraps_without_changing_content():
    tok = FakeTokenizer()
    content = build_evaluation_content("What is 3+3?", "numeric")
    out = render_for_model(tok, content)
    assert content in out
    assert out.endswith("[/A]")


def test_render_passes_thinking_flag_when_given():
    tok = FakeTokenizer()
    out = render_for_model(tok, "q", enable_thinking=True)
    assert "[thinking=True]" in out
    out2 = render_for_model(tok, "q", enable_thinking=False)
    assert "[thinking=False]" in out2


def test_render_falls_back_when_template_rejects_thinking_flag():
    tok = FakeTokenizer()

    def strict(*args, **kwargs):
        # a template without the Qwen3 thinking kwarg fails on it loudly
        if "enable_thinking" in kwargs:
            raise TypeError("unexpected keyword argument 'enable_thinking'")
        messages = args[0]
        return "[U]" + messages[0]["content"] + "[/A]"

    tok.apply_chat_template = strict
    out = render_for_model(tok, "the question", enable_thinking=True)
    assert "the question" in out
    assert out.endswith("[/A]")