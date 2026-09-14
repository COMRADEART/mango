"""Restore code-final summary model provenance after resume regrade."""
import json
from pathlib import Path

p = Path("evaluations/t15/runs/code-final/summary.json")
s = json.loads(p.read_text(encoding="utf-8"))
s["model"] = {
    "model": "Qwen/Qwen3-4B-Instruct-2507",
    "used": True,
    "load": {"ok": True, "error": None,
             "quantization": "4bit-nf4-double",
             "load_vram_bytes": 2716700672,
             "peak_vram_bytes": 2716700672,
             "reserved_vram_bytes": 2732589056,
             "smoke_latency_s": 0.88},
    "gen": {"seed": 20260912, "max_new_tokens": 384},
}
s["vram_peak_bytes"] = 2846436352
s["wall_seconds"] = round(724.0 + 3.8, 1)
s["phases"] = [
    {"phase": "main", "rows": 132, "wall_seconds": 724.0,
     "note": "frozen system+grader; regression rows misgraded by "
             "evidence-shape bug"},
    {"phase": "regrade", "rows": 7, "wall_seconds": 3.8,
     "note": "regression rows only, fixed grader, deterministic "
             "(no model); runner behavior identical by construction"},
]
p.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
print("summary patched; n_pass =", s["n_pass"], "acc =", s["accuracy"])
