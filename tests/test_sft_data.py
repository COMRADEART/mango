"""T3 SFT tokenization/masking tests (stub tokenizer, no network)."""
import re

from sciencemath.training.sft_data import (
    SFTCollator,
    build_labels,
    find_response_start,
    tokenize_example,
)


class StubTokenizer:
    """Whitespace tokenizer with a minimal Qwen-like chat template.

    apply_chat_template(enable_thinking=False) inserts '</think>' before the
    assistant content — the prompt prefix property holds by construction."""

    eos = "<|end|>"

    def apply_chat_template(self, messages, tokenize=False,
                            add_generation_prompt=False,
                            enable_thinking=None):
        parts = []
        for m in messages:
            parts.append(f"USER:{m['content']}\n"
                         if m["role"] == "user"
                         else f"ASSISTANT:{m['content']}{self.eos}")
        if add_generation_prompt:
            parts.append("ASSISTANT:")
        return "".join(parts)

    # role markers must tokenize as standalone tokens (like real BPE) or the
    # assistant prefix would fuse with the first response word
    _TOKEN_RE = re.compile(r"USER:|ASSISTANT:|\S+")

    def __call__(self, text, add_special_tokens=False, **kw):
        ids = [hash(m) % 1000 for m in self._TOKEN_RE.findall(text)]
        return {"input_ids": ids}

    def __getattr__(self, name):
        if name == "pad_token_id":
            return 0
        raise AttributeError(name)


def test_build_labels_masks_prompt():
    labels = build_labels([1, 2, 3, 4, 5], prompt_len=3)
    assert labels == [-100, -100, -100, 4, 5]


def test_tokenize_masks_user_turn_and_supervises_response():
    tok = StubTokenizer()
    out = tokenize_example(tok, "What is 2+2?", "Final answer: \\boxed{4}",
                           max_seq_length=512)
    ids = out["input_ids"]
    labels = out["labels"]
    assert len(ids) == len(labels) == len(out["attention_mask"])
    # the full text ends with the response; the response tail must be supervised
    assert any(l != -100 for l in labels)
    # prompt tokens (USER:...) are masked
    assert labels[0] == -100
    # attention is all ones pre-padding
    assert all(a == 1 for a in out["attention_mask"])


def test_tokenize_overflow_shortens_question_keeps_target():
    tok = StubTokenizer()
    long_q = ("This is a long setup sentence. " * 60) + "Final ask: what is 1+1?"
    out = tokenize_example(tok, long_q, "Final answer: \\boxed{2}",
                           max_seq_length=64)
    assert out is not None
    # target tokens must survive: find the boxed answer text supervised
    supervised = [i for i, l in zip(out["input_ids"], out["labels"]) if l != -100]
    assert supervised


def test_tokenize_impossible_overflow_is_dropped():
    tok = StubTokenizer()
    huge_target = "word " * 500
    stats_calls = []

    class Stats:
        dropped_too_long = 0

    out = tokenize_example(tok, "short?", huge_target, max_seq_length=64)
    assert out is None


def test_find_response_start_locates_assistant_prefix():
    full = [1, 2, 3, 7, 7, 7, 9]
    prompt = [1, 2, 3, 7]
    # the prompt tail [1,2,3] appears at 0; response starts after it
    assert find_response_start(full, prompt) >= 3


def test_collator_pads_and_masks_labels():
    import torch
    collator = SFTCollator(pad_token_id=0)
    feats = [
        {"input_ids": [1, 2, 3], "labels": [-100, 2, 3], "attention_mask": [1, 1, 1]},
        {"input_ids": [4, 5], "labels": [-100, 5], "attention_mask": [1, 1]},
    ]
    batch = collator(feats)
    assert isinstance(batch["input_ids"], torch.Tensor)
    assert batch["input_ids"][1].tolist() == [4, 5, 0]
    assert batch["labels"][1].tolist() == [-100, 5, -100]
    assert batch["attention_mask"][1].tolist() == [1, 1, 0]
    assert batch["input_ids"].shape == (2, 3)
    assert batch["labels"].dtype == torch.long