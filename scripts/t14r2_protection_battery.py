"""T14R2.19 — full protection battery after the T14R2 repair (GPU).

Fresh rerun with the SAME frozen suites and writers as T14
(t14_protection_battery.py); only labels/out-dirs are T14R2-specific
so no prior artifact is overwritten. Fidelity protection is covered
by scripts/t14r2_mutation_safety_probe.py (8/8 already verified) plus
the fidelity suite in the T14R2 replay; security runs on CPU pytest
afterwards (t14r2_protection_summary.py).
"""
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
    run([sys.executable, "scripts/t8_t4_arm.py", "--model", MODEL,
         "--label", "t14r2-protect-t4", "--max-new-tokens", "1024"])

    env = os.environ.copy()
    env["MANGO_EVAL_MODEL"] = MODEL
    run([sys.executable, "scripts/run_rag_eval_t5r.py", "--suite", "frozen",
         "--variants", "NORAG,G",
         "--out-dir", "evaluations/t14r2/protection/t5r"], env=env)

    run([sys.executable, "scripts/run_capacity_eval.py", "--model", MODEL,
         "--label", "t14r2-protect-cap",
         "--out", "evaluations/t14r2/protection/cap"])

    run([sys.executable, "scripts/run_extraction_benchmark.py", "--model",
         MODEL, "--label", "t14r2-protect-ext"])

    run([sys.executable, "scripts/t10_run_correction_v2.py", "--model",
         MODEL, "--label", "t14r2-protect-correction", "--arm", "t10",
         "--split", "final"])

    print("T14R2_PROTECTION_BATTERY_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())