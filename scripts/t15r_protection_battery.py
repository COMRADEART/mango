"""T15R.33 — fresh protection battery (does not overwrite T15 artifacts)."""
from __future__ import annotations

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


def main() -> int:
    run([sys.executable, "scripts/t15r_mutation_probe.py"])

    run([sys.executable, "scripts/t8_t4_arm.py", "--model", MODEL,
         "--label", "t15r-protect-t4", "--max-new-tokens", "1024"])

    env = os.environ.copy()
    env["MANGO_EVAL_MODEL"] = MODEL
    run([sys.executable, "scripts/run_rag_eval_t5r.py", "--suite", "frozen",
         "--variants", "NORAG,G",
         "--out-dir", "evaluations/t15r/protection/t5r"], env=env)

    run([sys.executable, "scripts/run_capacity_eval.py", "--model", MODEL,
         "--label", "t15r-protect-cap",
         "--out", "evaluations/t15r/protection/cap"])

    run([sys.executable, "scripts/run_extraction_benchmark.py", "--model",
         MODEL, "--label", "t15r-protect-ext"])

    run([sys.executable, "scripts/t10_run_correction_v2.py", "--model",
         MODEL, "--label", "t15r-protect-correction", "--arm", "t10",
         "--split", "final"])

    run([sys.executable, "scripts/t14r2_scicomp_eval.py", "--model", MODEL,
         "--suite", "scicomp", "--label", "t15r-scicomp-recheck",
         "--out-root", "evaluations/t15r/protection"])

    print("T15R_PROTECTION_BATTERY_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
