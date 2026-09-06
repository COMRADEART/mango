"""SFT dataset construction for QLoRA training (T3).

Tokenization contract:
  * each example is rendered through the chat template with
    enable_thinking=False (same protocol as the declared primary evaluation);
  * prompt tokens (user turn + generation prefix) are MASKED (-100) so the
    loss trains only the assistant response;
  * max_seq_length overflow: the QUESTION is shortened (leading sentences
    dropped, tail kept) so the target response — especially the final-answer
    closure — is always fully inside the window. Records still too long are
    dropped and counted (never silently truncated mid-answer).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sciencemath.training.sft_format import render_training_text


@dataclass
class TokenizeStats:
    kept: int = 0
    question_shortened: int = 0
    dropped_too_long: int = 0

    def to_dict(self) -> dict:
        return {"kept": self.kept,
                "question_shortened": self.question_shortened,
                "dropped_too_long": self.dropped_too_long}


def render_example(tokenizer, question: str, target: str) -> str:
    """Full training text: user turn + assistant response (no think block)."""
    return render_training_text(tokenizer, question, target)


def render_prompt(tokenizer, question: str) -> str:
    """The generation-time prompt: user turn + assistant generation prefix."""
    messages = [{"role": "user", "content": question.strip()}]
    kwargs = {"tokenize": False, "add_generation_prompt": True,
              "enable_thinking": False}
    try:
        return tokenizer.apply_chat_template(messages, **kwargs)
    except TypeError:
        kwargs.pop("enable_thinking", None)
        return tokenizer.apply_chat_template(messages, **kwargs)


def count_tokens(tokenizer, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=False)["input_ids"])


def build_labels(input_ids: list[int], prompt_len: int) -> list[int]:
    """Mask the prompt prefix (-100); supervise the response tokens."""
    labels = list(input_ids)
    for i in range(min(prompt_len, len(labels))):
        labels[i] = -100
    return labels


def _shorten_question(question: str, tokenizer, target: str,
                      max_seq_length: int) -> str | None:
    """Drop leading sentences until it fits. None when it cannot fit."""
    parts = [p for p in question.replace("\n", " ").split(". ") if p.strip()]
    while len(parts) > 1:
        candidate = ". ".join(parts[1:])
        if len(candidate) < 12:
            return None
        full = render_example(tokenizer, candidate, target)
        if count_tokens(tokenizer, full) <= max_seq_length:
            return candidate
        parts = parts[1:]
    return None


def find_response_start(full_ids: list[int], prompt_ids: list[int]) -> int:
    """Fallback response-start locator: match the prompt's tail sub-sequence
    in full_ids (used only if a template breaks strict prefix property)."""
    tail = prompt_ids[-32:]
    for i in range(len(full_ids) - len(tail), -1, -1):
        if full_ids[i:i + len(tail)] == tail:
            return i + len(tail)
    return 0


def tokenize_example(tokenizer, question: str, target: str,
                     *, max_seq_length: int,
                     stats: TokenizeStats | None = None) -> dict | None:
    """Tokenize one SFT example with prompt masking. Returns None when the
    example cannot fit (counted in stats, never silently truncated)."""
    full = render_example(tokenizer, question, target)
    if count_tokens(tokenizer, full) > max_seq_length:
        shortened = _shorten_question(question, tokenizer, target, max_seq_length)
        if shortened is None:
            if stats is not None:
                stats.dropped_too_long += 1
            return None
        question = shortened
        if stats is not None:
            stats.question_shortened += 1

    prompt_ids = tokenizer(render_prompt(tokenizer, question),
                           add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(render_example(tokenizer, question, target),
                         add_special_tokens=False)["input_ids"]
    prompt_len = len(prompt_ids)
    # prefix-consistency guard: full text must start with the prompt tokens;
    # if a template quirk breaks that, locate the response start by matching
    # the prompt tail instead of corrupting labels
    if full_ids[:prompt_len] != prompt_ids:
        prompt_len = find_response_start(full_ids, prompt_ids)

    labels = build_labels(full_ids, prompt_len)
    if all(l == -100 for l in labels):
        if stats is not None:
            stats.dropped_too_long += 1
        return None
    if stats is not None:
        stats.kept += 1
    return {"input_ids": full_ids, "labels": labels,
            "attention_mask": [1] * len(full_ids)}


def tokenize_corpus(tokenizer, records: list[dict], *,
                    max_seq_length: int) -> tuple[list[dict], dict]:
    """Tokenize a list of corpus records (question + target_response)."""
    stats = TokenizeStats()
    out = []
    for r in records:
        ids = tokenize_example(tokenizer, r["question"], r["target_response"],
                               max_seq_length=max_seq_length, stats=stats)
        if ids is not None:
            ids["source_id"] = r.get("id")
            out.append(ids)
    return out, stats.to_dict()


class SFTCollator:
    """Pad to longest-in-batch; labels padded with -100.

    Returns torch tensors: the Trainer hands the collated batch directly to
    model.forward, which requires real tensors (lists crash embedding())."""

    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, features: list[dict]) -> dict:
        import torch
        maxlen = max(len(f["input_ids"]) for f in features)
        input_ids, labels, attention = [], [], []
        for f in features:
            pad = maxlen - len(f["input_ids"])
            input_ids.append(list(f["input_ids"]) + [self.pad_token_id] * pad)
            labels.append(list(f["labels"]) + [-100] * pad)
            attention.append(list(f["attention_mask"]) + [0] * pad)
        return {"input_ids": torch.tensor(input_ids, dtype=torch.long),
                "labels": torch.tensor(labels, dtype=torch.long),
                "attention_mask": torch.tensor(attention, dtype=torch.long)}