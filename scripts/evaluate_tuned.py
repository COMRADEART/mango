"""T3 tuned-model evaluation on the FROZEN sciencemath-eval-v1 suite.

Loads Qwen3-1.7B + the T3 LoRA adapter (never merged) and runs the exact
frozen suite with the protocol DECLARED in configs/training.yaml
(evaluation_protocol) — before any tuned results were seen.

Also performs the adapter ablation check: for a small fixed subset, the
adapter is programmatically disabled and re-enabled; outputs must differ
(proving the adapter actually drove the tuned behavior) and the
adapter-active state is recorded programmatically in adapter_metadata.json.

Usage:
  python scripts/evaluate_tuned.py --limit 5      # smoke
  python scripts/evaluate_tuned.py                # full 188-question run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, load_configs, setup_logging  # noqa: E402

from sciencemath.utils.io_utils import read_jsonl, write_json  # noqa: E402

SUITE_DIR = REPO_ROOT / "evaluations" / "suite" / "v1"
OUT_DIR = REPO_ROOT / "evaluations" / "tuned" / "sciencemath-v0.1-t3"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="evaluate only the first N questions (smoke runs)")
    ap.add_argument("--adapter", default=None,
                    help="adapter dir (default: configs/training.yaml adapter_output_dir)")
    args = ap.parse_args()

    log = setup_logging("evaluate_tuned")
    cfg = load_configs()
    training_cfg = cfg.get("training", {})
    protocol = training_cfg.get("evaluation_protocol", {})
    if not protocol:
        print("REFUSED: no evaluation_protocol declared in configs/training.yaml "
              "(the T3 protocol must be fixed before evaluation).")
        return 91

    adapter_dir = Path(args.adapter) if args.adapter else \
        REPO_ROOT / training_cfg["training"]["adapter_output_dir"]
    if not adapter_dir.exists():
        print(f"REFUSED: adapter not found at {adapter_dir}. Train first "
              f"(scripts/train_lora.py).")
        return 91

    # ---- frozen suite integrity ----
    from evaluate_base import verify_suite
    integrity = verify_suite(SUITE_DIR)
    if not integrity.get("verified", False):
        print(f"REFUSED: frozen suite failed integrity check: {integrity}")
        return 91

    model_cfg = cfg.get("model", {}).get("selected", {})
    model_id = model_cfg.get("model_id")
    generation = dict(protocol["generation"])
    mode = protocol["mode"]
    enable_thinking = bool(protocol["enable_thinking"])
    log.info("declared protocol: mode=%s thinking=%s generation=%s",
             mode, enable_thinking, generation)

    # ---- load base + adapter ----
    from sciencemath.training.attach import load_base_with_adapter, adapter_active_state
    tok, model, load_info = load_base_with_adapter(model_id, str(adapter_dir))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUT_DIR / "hardware.json", {"load": load_info,
                                           "recorded_at": datetime.now(timezone.utc).isoformat()})
    if not load_info.get("ok"):
        write_json(OUT_DIR / "manifest.json", {
            "status": "LOAD_FAILED", "error": load_info.get("error")})
        print("LOAD FAILED:", load_info.get("error"))
        return 92

    adapter_meta = {
        "adapter_dir": str(adapter_dir),
        "model_id": model_id,
        "adapter_active_at_load": load_info.get("adapter_state"),
        "ablation": None,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    # ---- adapter ablation check (adapter ON vs OFF must differ) ----
    suite = read_jsonl(SUITE_DIR / "questions.jsonl")
    ablation_ids = [q["eval_id"] for q in suite[:4]]
    import torch
    from sciencemath.evaluation.prompts import build_evaluation_content, render_for_model
    ablation_records = []
    try:
        with torch.no_grad():
            for q in suite[:4]:
                content = build_evaluation_content(q["question"], q["answer_type"],
                                                   q.get("choices"))
                templ = render_for_model(tok, content, enable_thinking=enable_thinking)
                ids = tok(templ, return_tensors="pt",
                          truncation=True, max_length=2048).to(model.device)
                gen = model.generate(**ids, max_new_tokens=96, do_sample=False,
                                     pad_token_id=tok.pad_token_id or tok.eos_token_id)
                text_on = tok.decode(gen[0][ids["input_ids"].shape[1]:],
                                     skip_special_tokens=True)
                with model.disable_adapter():
                    off_state = adapter_active_state(model)
                    gen_off = model.generate(**ids, max_new_tokens=96, do_sample=False,
                                             pad_token_id=tok.pad_token_id or tok.eos_token_id)
                    text_off = tok.decode(gen_off[0][ids["input_ids"].shape[1]:],
                                          skip_special_tokens=True)
                on_state = adapter_active_state(model)
                ablation_records.append({
                    "eval_id": q["eval_id"],
                    "adapter_on_active": on_state["adapter_active"],
                    "adapter_off_active": off_state["adapter_active"],
                    "outputs_differ": text_on != text_off,
                    "output_on_preview": text_on[:120],
                    "output_off_preview": text_off[:120],
                })
        differ = sum(1 for a in ablation_records if a["outputs_differ"])
        adapter_meta["ablation"] = {
            "n_questions": len(ablation_records),
            "outputs_differ": differ,
            "adapter_on_active_all": all(a["adapter_on_active"] for a in ablation_records),
            "adapter_off_active_none": all(not a["adapter_off_active"]
                                           for a in ablation_records),
            "genuine_adapter_effect": bool(differ >= max(1, len(ablation_records) // 2)),
            "records": ablation_records,
        }
    except Exception as exc:
        adapter_meta["ablation"] = {"error": f"{type(exc).__name__}: {exc}"}
    write_json(OUT_DIR / "adapter_metadata.json", adapter_meta)
    log.info("ablation: %s", json.dumps(
        {k: v for k, v in adapter_meta["ablation"].items() if k != "records"}
        if adapter_meta.get("ablation") else {}))

    # ---- full frozen-suite run via the T2 runner (resume-capable) ----
    # model/tokenizer are PASSED IN so the adapter-loaded PeftModel is what
    # actually generates every prediction (evaluate_model must not reload a
    # bare base model behind our backs)
    from sciencemath.evaluation.runner import evaluate_model
    summary = evaluate_model(
        model_id=model_id, mode=mode, model_slug="qwen3-1.7b+t3",
        suite_dir=SUITE_DIR, out_dir=OUT_DIR,
        generation=generation, quantized_4bit=True,
        enable_thinking=enable_thinking,
        max_seq_tokens=protocol.get("max_seq_tokens", 8192),
        model=model, tokenizer=tok,
        limit=args.limit)

    # annotate manifest with adapter provenance
    manifest_path = OUT_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["adapter"] = {
            "path": str(adapter_dir),
            "ablation_genuine": (adapter_meta.get("ablation") or {}).get(
                "genuine_adapter_effect"),
            "training_manifest": str(Path(adapter_dir) / "training_manifest.json"),
            "protocol": protocol,
        }
        manifest["adapter_metadata"] = "adapter_metadata.json"
        write_json(manifest_path, manifest)

    # environment record
    write_json(OUT_DIR / "environment.json", {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "torch": __import__("torch").__version__,
        "transformers": __import__("transformers").__version__,
        "peft": __import__("peft").__version__,
        "bitsandbytes": __import__("bitsandbytes").__version__,
        "accelerate": __import__("accelerate").__version__,
    })
    print(json.dumps(summary, indent=1, default=str)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())