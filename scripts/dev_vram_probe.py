"""Worst-case VRAM probe: N x the longest corpus sequences, forward/backward
steps on the real 4-bit model + LoRA. Development helper used to decide
micro-batch size before the real T3 run. Usage: python dev_vram_probe.py [n]"""
import json
import sys

N_BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 2

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from sciencemath.evaluation.model_loader import quantization_config
from sciencemath.training.attach import attach_lora, adapter_active_state
from sciencemath.training.sft_data import SFTCollator, tokenize_corpus

MAX_SEQ = 1024


def main() -> int:
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-1.7B")
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    recs = []
    with open("training/datasets/sciencemath-sft-v1/train.jsonl",
              encoding="utf-8") as f:
        for line in f:
            recs.append(json.loads(line))
    feats, stats = tokenize_corpus(tok, recs, max_seq_length=MAX_SEQ)
    print("tokenized:", stats)
    # the N longest examples = worst-case batch
    feats.sort(key=lambda x: len(x["input_ids"]), reverse=True)
    batch = feats[:N_BATCH]
    print("worst-case lens:", [len(x["input_ids"]) for x in batch])

    collator = SFTCollator(tok.pad_token_id)
    inputs = collator(batch)
    inputs = {k: v.to("cuda") for k, v in inputs.items()}

    bnb = quantization_config("bfloat16")
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen3-1.7B", quantization_config=bnb, device_map="auto")
    model.config.use_cache = False
    peft_model = attach_lora(model, {
        "r": 32, "lora_alpha": 64, "lora_dropout": 0.05,
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                           "gate_proj", "up_proj", "down_proj"]})
    assert adapter_active_state(peft_model)["adapter_active"]
    base_vram = torch.cuda.max_memory_allocated()
    torch.cuda.reset_peak_memory_stats()

    from torch.utils.data import DataLoader
    dl = DataLoader(batch, batch_size=N_BATCH, collate_fn=collator)
    opt = torch.optim.AdamW(
        [p for p in peft_model.parameters() if p.requires_grad], lr=1e-4)
    peft_model.train()
    peft_model.gradient_checkpointing_enable()
    for step, b in enumerate(dl):
        b = {k: v.to("cuda") for k, v in b.items()}
        out = peft_model(**b)
        out.loss.backward()
        opt.step()
        opt.zero_grad()
        print(f"step {step}: loss={out.loss.item():.4f} "
              f"peak={torch.cuda.max_memory_allocated() / 1e9:.2f} GB")
    peak = torch.cuda.max_memory_allocated()
    print(f"BASE_VRAM {base_vram / 1e9:.2f} GB | WORST_CASE_PEAK {peak / 1e9:.2f} GB")
    print(json.dumps({"base_vram_bytes": int(base_vram),
                      "worst_case_peak_bytes": int(peak),
                      "batch": N_BATCH, "seq_len": MAX_SEQ}))
    return 0


if __name__ == "__main__":
    sys.exit(main())