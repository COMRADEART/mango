"""T8.4 — per-candidate hardware feasibility probe (RTX 4050 6 GB).

For each candidate:
  1. tokenizer load
  2. quantized model load (4-bit NF4, double quant, device_map=auto)
  3. tiny generation
  4. VRAM measurement (load + peak generation)
  5. 5-question smoke (from the frozen capacity suite)
  6. memory cleanup

Records model load VRAM, peak generation VRAM, RAM, load time, tokens/sec,
OOM / offload behavior, disk size. No silent CPU offload for the main
comparison: a load that spills to CPU is recorded as cpu_offload=True.

Usage: python scripts/t8_hardware_probe.py --model ID --label slug
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

OUT = REPO / "evaluations" / "t8" / "hardware"
SUITE = REPO / "evaluations" / "t8" / "capacity-suite" / "v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--label", required=True)
    ap.add_argument("--compute-dtype", default="bfloat16")
    ap.add_argument("--smoke-n", type=int, default=5)
    args = ap.parse_args()

    import torch
    from sciencemath.evaluation.model_loader import load_model_safely
    from sciencemath.evaluation.prompts import build_evaluation_content, \
        render_for_model
    from sciencemath.evaluation.extraction import extract_answer

    OUT.mkdir(parents=True, exist_ok=True)
    rec: dict = {"label": args.label, "model": args.model,
                 "revision": args.revision, "recorded_at": now(),
                 "gpu": torch.cuda.get_device_name(0)
                 if torch.cuda.is_available() else "cpu",
                 "vram_total_mib": round(
                     torch.cuda.get_device_properties(0).total_memory / 2**20)
                 if torch.cuda.is_available() else None}

    def ram_gb() -> float:
        try:
            import psutil
            return round(psutil.virtual_memory().used / 2**30, 2)
        except Exception:  # noqa: BLE001
            return -1.0

    rec["ram_before_gb"] = ram_gb()

    tok, model, load_info = load_model_safely(
        args.model, compute_dtype=args.compute_dtype)
    rec["load"] = {k: v for k, v in load_info.items()}
    if not load_info.get("ok"):
        rec["oom"] = "OOM" in str(load_info.get("error", ""))
        (OUT / f"{args.label}.json").write_text(
            json.dumps(rec, indent=2), encoding="utf-8")
        print("PROBE FAILED:", load_info.get("error"))
        return 1

    # device placement audit: any CPU-offloaded module?
    offload = sorted({str(p.device) for p in model.parameters()
                      if str(p.device) != "cuda:0"})
    rec["cpu_offload"] = bool(offload)
    rec["offload_devices"] = offload[:8]

    # disk size from the resolved HF cache snapshot
    try:
        from huggingface_hub import snapshot_download
        snap = snapshot_download(args.model, revision=args.revision,
                                 allow_patterns=["*.safetensors", "*.json",
                                                 "*.txt"])
        rec["disk_size_gb"] = round(sum(
            os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(snap)
            for f in fs) / 2**30, 2)
    except Exception as exc:  # noqa: BLE001
        rec["disk_size_gb"] = None
        rec["disk_note"] = f"{type(exc).__name__}: {exc}"

    # 5-question smoke from the frozen capacity suite
    items = [json.loads(l) for l in
             (SUITE / "questions.jsonl").read_text(encoding="utf-8")
             .splitlines() if l.strip()][:args.smoke_n]
    torch.cuda.reset_peak_memory_stats()
    smoke = []
    tps_all, lat_all = [], []
    for it in items:
        content = build_evaluation_content(it["question"], it["answer_type"],
                                           it.get("choices"))
        prompt = render_for_model(tok, content, enable_thinking=False)
        inputs = tok(prompt, return_tensors="pt").to(model.device)
        t0 = time.time()
        try:
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=256,
                                     do_sample=False,
                                     pad_token_id=tok.pad_token_id
                                     or tok.eos_token_id)
            dt = time.time() - t0
            n = int(out.shape[1] - inputs["input_ids"].shape[1])
            text = tok.decode(out[0][inputs["input_ids"].shape[1]:],
                              skip_special_tokens=True)
            smoke.append({
                "eval_id": it["eval_id"], "latency_s": round(dt, 2),
                "new_tokens": n, "ok": True,
                "extracted": extract_answer(text, it["answer_type"],
                                            it.get("choices")),
                "preview": text[:120],
            })
            tps_all.append(n / dt if dt > 0 else 0)
            lat_all.append(dt)
        except torch.cuda.OutOfMemoryError:
            smoke.append({"eval_id": it["eval_id"], "ok": False,
                          "oom": True})
            rec["oom"] = True
            break
        except Exception as exc:  # noqa: BLE001
            smoke.append({"eval_id": it["eval_id"], "ok": False,
                          "error": f"{type(exc).__name__}: {exc}"})
    rec["smoke"] = smoke
    rec["tokens_per_s_median"] = round(sorted(tps_all)[len(tps_all) // 2], 2) \
        if tps_all else None
    rec["latency_median_s"] = round(sorted(lat_all)[len(lat_all) // 2], 2) \
        if lat_all else None
    rec["peak_gen_vram_mib"] = round(
        torch.cuda.max_memory_reserved() / 2**20, 1)
    rec["ram_after_gb"] = ram_gb()
    rec["ok"] = all(s.get("ok") for s in smoke) and not rec.get("oom")

    # cleanup (step 6)
    del model, tok
    import gc
    gc.collect()
    torch.cuda.empty_cache()

    (OUT / f"{args.label}.json").write_text(json.dumps(rec, indent=2),
                                            encoding="utf-8")
    print(json.dumps({k: rec.get(k) for k in
                      ("label", "ok", "cpu_offload", "disk_size_gb",
                       "peak_gen_vram_mib", "tokens_per_s_median",
                       "latency_median_s", "oom")}, indent=2, default=str))
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())