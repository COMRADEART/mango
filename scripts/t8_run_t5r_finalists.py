"""T8.16 — T5R integration arms for the two finalists (GPU-sequential).

Runs the FROZEN T5R stack (variant G = adopted config, plus NORAG) per
finalist base model via the MANGO_EVAL_MODEL override (no adapter).
Phi-4-mini-reasoning gets the recorded 2048-token exception.
Outputs: evaluations/t8/runs/<label>/t5r/<variant>/
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "evaluations" / "t8" / "runs"

FINALISTS = [
    ("Qwen/Qwen3-4B-Instruct-2507", "qwen3-4b-instruct", None),
    ("microsoft/Phi-4-mini-reasoning", "phi4-mini-reasoning", "2048"),
]

for model, label, mx in FINALISTS:
    env = os.environ.copy()
    env["MANGO_EVAL_MODEL"] = model
    env.pop("MANGO_EVAL_MAX_TOKENS", None)
    if mx:
        env["MANGO_EVAL_MAX_TOKENS"] = mx
    out = RUNS / label / "t5r"
    cmd = [sys.executable, "scripts/run_rag_eval_t5r.py", "--suite",
           "frozen", "--variants", "NORAG,G", "--out-dir", str(out)]
    print(f"=== T5R arm: {label} (max_new_tokens={mx or 1024}) ===",
          flush=True)
    r = subprocess.run(cmd, cwd=str(REPO), env=env)
    print(f"--- {label} exit {r.returncode}", flush=True)
print("T5R finalist arms complete", flush=True)
