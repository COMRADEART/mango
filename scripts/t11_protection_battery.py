"""T11.34–T11.38 — protection rerun battery (GPU-sequential).

Re-runs all four frozen protection suites plus the correction battery on
the UNCHANGED runtime (Mango-4B-System-v1 = Qwen3-4B-Instruct-2507; the
scicomp laboratory is additive and offline — these suites exercise the
same tool/verifier/retrieval/extraction/correction layers as T10):

  T11.34 T4         t8_t4_arm.py          -> evaluations/t11/protection/t4
  T11.35 T5R        run_rag_eval_t5r.py   -> evaluations/t11/protection/t5r
  T11.36 capacity   run_capacity_eval.py  -> evaluations/t11/protection/cap
  T11.38 extraction run_extraction_benchmark.py -> evaluations/t11/protection/ext
  T11.37 correction t10_run_correction_v2.py -> evaluations/t11/protection/correction

Frozen baselines (from T10 close, commit 891ba41):
  T4 recall ~74.67%, false PASS = 0
  T5R  ~58.62%, citations 0/0/0
  generalization 110/131 = 0.840
  extraction wrong-final = 0
  correction battery ALL_PASS
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
     "--label", "t11-protect-t4", "--max-new-tokens", "1024"])

env = os.environ.copy()
env["MANGO_EVAL_MODEL"] = MODEL
run([sys.executable, "scripts/run_rag_eval_t5r.py", "--suite", "frozen",
     "--variants", "NORAG,G", "--out-dir", "evaluations/t11/protection/t5r"],
    env=env)

run([sys.executable, "scripts/run_capacity_eval.py", "--model", MODEL,
     "--label", "t11-protect-cap",
     "--out", "evaluations/t11/protection/cap"])

run([sys.executable, "scripts/run_extraction_benchmark.py", "--model", MODEL,
     "--label", "t11-protect-ext"])

run([sys.executable, "scripts/t10_run_correction_v2.py", "--model", MODEL,
     "--label", "t11-protect-correction", "--arm", "t10",
     "--split", "final"])

print("T11_PROTECTION_BATTERY_DONE", flush=True)