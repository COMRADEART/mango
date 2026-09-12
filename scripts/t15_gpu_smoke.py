"""T15 GPU smoke: load Qwen3-4B 4-bit, time one short structured generation."""
import json
import sys
import time

sys.path.insert(0, "src")

from sciencemath.evaluation.model_loader import load_model_safely
from sciencemath.executive.llm import call_model

MODEL = "Qwen/Qwen3-4B-Instruct-2507"

tok, model, info = load_model_safely(MODEL)
print("LOAD_INFO:", json.dumps({k: v for k, v in info.items()
                                if k != "error"}, indent=1))
if not info["ok"]:
    print("LOAD_ERROR:", info["error"])
    raise SystemExit(2)

prompt = ("Propose a minimal patch as JSON list [{file, old, new}]. "
          "Task: Fix add in src/calc.py. The file contains "
          "'def add(a, b):\\n    return a - b\\n'. Tests expect add(2,3)==5. "
          "Reply with ONLY the JSON list.")
t0 = time.time()
text, n_in, n_out = call_model(
    model, tok, prompt, {"seed": 7, "max_new_tokens": 256})
dt = time.time() - t0
print(f"GEN_SECONDS: {dt:.1f} in={n_in} out={n_out}")
print("GEN_TEXT:", text[:1500])
