"""CPU smoke: tokenize real frozen-corpus examples with the Qwen3 tokenizer.

Verifies prompt masking, supervised-tail presence and seq-length headroom
before the GPU dry run. Development helper — not part of the eval pipeline.
"""
import json
import sys

from transformers import AutoTokenizer

from sciencemath.training.sft_data import TokenizeStats, tokenize_example

MAX_SEQ = 1024


def main() -> int:
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-1.7B")
    path = "training/datasets/sciencemath-sft-v1/train.jsonl"
    recs = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 12:
                break
            recs.append(json.loads(line))
    stats = TokenizeStats()
    worst = 0
    for r in recs:
        out = tokenize_example(tok, r["question"], r["target_response"],
                               max_seq_length=MAX_SEQ, stats=stats)
        if out is None:
            print(f"{r['id'][:32]:34s} DROPPED (too long)")
            continue
        n_prompt = sum(1 for l in out["labels"] if l == -100)
        n_sup = sum(1 for l in out["labels"] if l != -100)
        worst = max(worst, len(out["input_ids"]))
        assert out["labels"][0] == -100
        assert out["labels"][-1] != -100, "closure marker must be supervised"
        print(f"{r['id'][:32]:34s} len={len(out['input_ids']):5d} "
              f"prompt={n_prompt:5d} supervised={n_sup:4d}")
    print("stats:", stats.to_dict(), "| worst len:", worst, "/", MAX_SEQ)
    return 0


if __name__ == "__main__":
    sys.exit(main())