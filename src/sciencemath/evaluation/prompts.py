"""Standardized evaluation prompt construction.

Rule enforced here: `build_evaluation_content()` produces SEMANTICALLY
IDENTICAL text for every model (evaluation_content). Chat-template rendering
(`render_for_model`) is a separate, model-specific step and never changes
the question text or instruction. Prompts are never tuned per model based
on performance.

Scoring contract with the model, stated IN the prompt (same for all models):

  math/numeric/text : final answer must appear inside \\boxed{...}
  multiple_choice   : final choice letter inside \\boxed{}, e.g. \\boxed{C}
"""
from __future__ import annotations

from sciencemath.evaluation.extraction import _MCQ_INSTRUCTION

MATH_INSTRUCTION = (
    "Solve the following problem step by step. "
    "Put your final answer inside \\boxed{} on the last line."
)
SCIENCE_TEXT_INSTRUCTION = (
    "Answer the following question. "
    "Put your final answer (the exact term) inside \\boxed{} on the last line."
)


def build_evaluation_content(question: str, answer_type: str,
                             choices: list[str] | None = None) -> str:
    """The single source of truth for question wording. Identical for every
    model; only the chat_TEMPLATE differs (see render_for_model)."""
    if answer_type == "multiple_choice" and choices:
        lines = [question.strip(), ""]
        for i, ch in enumerate(choices):
            lines.append(f"{chr(65 + i)}. {ch}")
        lines += ["", _MCQ_INSTRUCTION]
        return "\n".join(lines)
    if answer_type == "numeric":
        return f"{MATH_INSTRUCTION}\n\n{question.strip()}"
    return f"{SCIENCE_TEXT_INSTRUCTION}\n\n{question.strip()}"


def render_for_model(tokenizer, eval_content: str,
                     *, enable_thinking: bool | None = None) -> str:
    """Wrap the (identical) evaluation content with the model's own chat
    template. `thinking` is an explicit, recorded switch (Qwen3); models
    without the flag ignore it."""
    from jinja2 import TemplateError  # type: ignore

    messages = [{"role": "user", "content": eval_content}]
    kwargs = {"tokenize": False, "add_generation_prompt": True}
    if enable_thinking is not None:
        kwargs["enable_thinking"] = enable_thinking
    try:
        return tokenizer.apply_chat_template(messages, **kwargs)
    except (TemplateError, TypeError):
        # model whose template lacks the enable_thinking kwarg
        kwargs.pop("enable_thinking", None)
        try:
            return tokenizer.apply_chat_template(messages, **kwargs)
        except Exception:
            # template-free model: minimal deterministic fallback wrapper
            return f"User: {eval_content}\nAssistant:"