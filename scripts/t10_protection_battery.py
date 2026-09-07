"""T10.18–T10.21 — protection rerun battery (GPU-sequential).

Runs all four frozen protection suites on the T10-improved candidate
(Qwen3-4B-Instruct-2507, no adapter, tools/verifier/retrieval/extraction
layers unaltered):
  T10.18 T4        t8_t4_arm.py          -> evaluations/t8/runs/t10-protect-t4
  T10.19 T5R       run_rag_eval_t5r.py   -> evaluations/t10/protection/t5r
  T10.20 capacity  run_capacity_eval.py  -> evaluations/t10/protection/cap
  T10.21 extraction run_extraction_benchmark.py -> evaluations/t9/runs/t10-protect-ext
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL = "Qwen/Qwen3-4B-Instruct-2507"


def run(cmd, env=None, **kw):
    print("::", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(REPO), env=env, **kw)
    print(":: exit", r.returncode, flush=True)
    return r


run([sys.executable, "scripts/t8_t4_arm.py", "--model", MODEL,
     "--label", "t10-protect-t4", "--max-new-tokens", "1024"])

env = os.environ.copy()
env["MANGO_EVAL_MODEL"] = MODEL
run([sys.executable, "scripts/run_rag_eval_t5r.py", "--suite", "frozen",
     "--variants", "NORAG,G", "--out-dir", "evaluations/t10/protection/t5r"],
    env=env)

run([sys.executable, "scripts/run_capacity_eval.py", "--model", MODEL,
     "--label", "t10-protect-cap",
     "--out", "evaluations/t10/protection/cap"])

run([sys.executable, "scripts/run_extraction_benchmark.py", "--model", MODEL,
     "--label", "t10-protect-ext"])

print("PROTECTION_BATTERY_DONE", flush=True)