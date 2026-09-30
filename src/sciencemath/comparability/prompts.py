"""T31.4 Prompt policy — one frozen policy per benchmark, applied to both arms.

The brief is unambiguous: "Do not improve the adapter's prompt independently.
Do not use benchmark-specific prompt engineering for one side." The way to
honour that is structural rather than procedural — this module has no arm
parameter. There is exactly one function that turns an item into a prompt,
and both arms call it. A function that *could* be asked for a base prompt and
an adapter prompt is a function that will eventually be asked.

The policy is also deliberately thin. Each instruction says only what the
answer extractor needs in order to read an answer: the benchmark's own
canonical marker (``####`` for GSM8K, ``\\boxed{}`` for MATH-500) or a single
option letter. Nothing here asks a model to reason in a particular style,
because a prompt that shapes reasoning is a prompt that can be tuned, and a
tuned prompt makes the weights no longer the only variable.

The rendered prompt is a pure function of the item plus the frozen decoding
mode, so the base and adapter rows for one item necessarily carry the same
prompt text — and the test suite asserts that rather than trusting it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from sciencemath.comparability.loaders import EvalItem

#: Rendered with ``{question}`` and, for multiple choice, ``{options}``.
PROMPT_POLICY: Final = {
    "numeric": (
        "{question}\n\n"
        "Solve the problem. Show your working, then give the final answer on "
        "its own line as: #### <number>"
    ),
    "math": (
        "{question}\n\n"
        "Solve the problem. Put your final answer inside \\boxed{{}}."
    ),
    "multiple_choice": (
        "{question}\n\n"
        "{options}\n"
        "Answer with the single letter of the correct option."
    ),
}

#: No system message is used, for either arm or any benchmark. Recorded as an
#: empty string rather than omitted so that a raw row always carries the field
#: the brief asks for, and so that "there was no system prompt" is a fact on
#: the row rather than an absence a reader has to interpret.
SYSTEM_PROMPT: Final = ""


def render_options(choices: tuple[tuple[str, str], ...]) -> str:
    """One option per line, as ``A) text``."""
    return "\n".join(f"{label}) {text}" for label, text in choices)


def prompt_text(item: EvalItem, kind: str) -> str:
    """The user-turn content for an item. Pure; no arm, no randomness."""
    template = PROMPT_POLICY[kind]
    body = template.format(question=item.question,
                           options=render_options(item.choices))
    return body


def prompt_policy_hash() -> str:
    """Canonical hash of the policy *literals*, for the frozen configuration.

    This covers ``PROMPT_POLICY`` and ``SYSTEM_PROMPT`` and nothing else. It
    does **not** cover how an item is rendered into those templates — a change
    to ``render_options`` or ``prompt_text`` alters the exact text both arms
    are asked while leaving this hash, and therefore the frozen configuration
    hash, unchanged. That gap is closed elsewhere rather than here: every raw
    row records its rendered ``user_prompt`` and a ``prompt_sha256`` over it,
    so a rendering change shows up in the evidence row by row, and the pack
    copies this module in verbatim under ``source/`` and hashes it. The
    limitation is stated rather than papered over, because a hash that looks
    like it pins the prompt but does not is worse than one that says what it
    pins.
    """
    blob = json.dumps({"policy": PROMPT_POLICY, "system": SYSTEM_PROMPT},
                      sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def render_chat(tokenizer: Any, user_text: str, *,
                enable_thinking: bool) -> str:
    """Apply the model's own chat template.

    One template, taken from the tokenizer, for both arms. The adapter ships
    no template of its own — that is asserted in the tests, not assumed — so
    the only thing that differs between the two rendered strings for a given
    item is nothing at all.
    """
    messages = [{"role": "user", "content": user_text}]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=enable_thinking)
