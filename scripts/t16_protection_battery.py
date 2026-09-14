"""T16.48 — protection battery (does not overwrite T15/T15R artifacts)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
PROT = REPO / "evaluations/t16/protection"


def run(cmd, env=None, **kw):
    print("::", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(REPO), env=env, **kw)
    print(":: exit", r.returncode, flush=True)
    return r


def main() -> int:
    PROT.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "scripts/t15r_mutation_probe.py"])
    mut_src = REPO / "evaluations/t15r/mutation_safety_probe.json"
    if mut_src.exists():
        shutil.copy(mut_src, REPO / "evaluations/t16/mutation_safety_probe.json")

    run([sys.executable, "scripts/t8_t4_arm.py", "--model", MODEL,
         "--label", "t16-protect-t4", "--max-new-tokens", "1024"])

    env = os.environ.copy()
    env["MANGO_EVAL_MODEL"] = MODEL
    run([sys.executable, "scripts/run_rag_eval_t5r.py", "--suite", "frozen",
         "--variants", "NORAG,G",
         "--out-dir", "evaluations/t16/protection/t5r"], env=env)

    run([sys.executable, "scripts/run_capacity_eval.py", "--model", MODEL,
         "--label", "t16-protect-cap",
         "--out", "evaluations/t16/protection/cap"])

    run([sys.executable, "scripts/run_extraction_benchmark.py", "--model",
         MODEL, "--label", "t16-protect-ext"])

    run([sys.executable, "scripts/t10_run_correction_v2.py", "--model", MODEL,
         "--label", "t16-protect-correction", "--arm", "t10",
         "--split", "final"])

    run([sys.executable, "scripts/t14r2_scicomp_eval.py", "--model", MODEL,
         "--suite", "scicomp", "--label", "t16-scicomp-recheck",
         "--out-root", "evaluations/t16/protection"])

    run([sys.executable, "scripts/t15r_run_code_eval.py", "--split", "final",
         "--suite", "v1.1", "--run-name", "t16-protect-code"])
    code_src = REPO / "evaluations/t15r/runs/t16-protect-code"
    if code_src.exists():
        dest = PROT / "code"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(code_src, dest)

    print("T16_PROTECTION_BATTERY_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
