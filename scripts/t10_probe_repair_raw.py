"""Probe raw firewall repair output for T10.6 taxonomy confirmation."""
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\allam\Documents\new\model")
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.executive.correction import targeted_repair_prompt  # noqa: E402
from sciencemath.evaluation.model_loader import load_model_safely  # noqa: E402

items = {r["eval_id"]: r for r in
         (json.loads(l) for l in
          (ROOT / "evaluations/t10/correction-suite/v2/questions.jsonl")
          .read_text(encoding="utf-8").splitlines() if l)}
rows = [json.loads(l) for l in
        (ROOT / "evaluations/t10/runs/qwen3-4b-t9arm-dev/predictions.jsonl")
        .read_text(encoding="utf-8").splitlines() if l]

tok, model, load = load_model_safely("Qwen/Qwen3-4B-Instruct-2507")
assert load["ok"], load["error"]
import torch  # noqa: E402

fail_ids = [r["eval_id"] for r in rows
            if r["case_class"] == "TRUE_FAIL" and not r["final_correct"]]
provenance = {}
for eid in fail_ids:
    it = items[eid]
    row = next(r for r in rows if r["eval_id"] == eid)
    prompt = targeted_repair_prompt(
        question=row["question"],
        answer=row["initial_answer"],
        component=row["failed_component"],
        evidence=row["evidence"],
        expected=row["expected_answer"])
    p = tok.apply_chat_template([{"role": "user", "content": prompt}],
                                tokenize=False, add_generation_prompt=True,
                                enable_thinking=False)
    inputs = tok(p, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=320, do_sample=False,
                             pad_token_id=tok.pad_token_id or tok.eos_token_id)
    raw = tok.decode(out[0][inputs["input_ids"].shape[1]:],
                     skip_special_tokens=True)
    print("=" * 80)
    print(eid)
    print("RAW REPAIR:", raw[:420])
    provenance[eid] = raw

out = ROOT / "evaluations/t10/runs/qwen3-4b-t9arm-dev/raw_repair_probe.json"
out.write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
               encoding="utf-8")
print("\nsaved", len(provenance), "raw repair outputs to", out)