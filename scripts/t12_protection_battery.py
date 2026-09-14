"""T12.30 — full regression battery rerun (GPU-sequential).

Identical to the T11 protection battery (same frozen suites, same
writers, same runtime) with t12-protect-* labels. T12 modified only the
scicomp planner/adoption interface, which these suites do not exercise —
the battery proves the correction firewall, T4, T5R, capacity,
extraction, and correction layers are untouched.

  T4          t8_t4_arm.py               -> evaluations/t8/runs/t12-protect-t4
  T5R         run_rag_eval_t5r.py        -> evaluations/t12/protection/t5r
  capacity    run_capacity_eval.py       -> evaluations/t12/protection/cap
  extraction  run_extraction_benchmark.py-> evaluations/t9/runs/t12-protect-ext
  correction  t10_run_correction_v2.py   -> evaluations/t10/runs/t12-protect-correction

Frozen baselines (T10 close / T11 rerun, all reproduced exactly in T11):
  T4 recall ~74.67%, false PASS = 0
  T5R  ~58.62%, citations 0/0/0
  generalization 110/131 = 0.857 (overall)
  extraction wrong-final = 0
  correction true_correction >= 0.80, preservation 1.0, collateral 0,
  blind agreement 0
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
     "--label", "t12-protect-t4", "--max-new-tokens", "1024"])

env = os.environ.copy()
env["MANGO_EVAL_MODEL"] = MODEL
run([sys.executable, "scripts/run_rag_eval_t5r.py", "--suite", "frozen",
     "--variants", "NORAG,G", "--out-dir", "evaluations/t12/protection/t5r"],
    env=env)

run([sys.executable, "scripts/run_capacity_eval.py", "--model", MODEL,
     "--label", "t12-protect-cap",
     "--out", "evaluations/t12/protection/cap"])

run([sys.executable, "scripts/run_extraction_benchmark.py", "--model",
     MODEL, "--label", "t12-protect-ext"])

run([sys.executable, "scripts/t10_run_correction_v2.py", "--model", MODEL,
     "--label", "t12-protect-correction", "--arm", "t10",
     "--split", "final"])

print("T12_PROTECTION_BATTERY_DONE", flush=True)