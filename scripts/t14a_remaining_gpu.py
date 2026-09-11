"""T14A remaining GPU legs after mango-scicomp-eval-v1 arm B.

Conceptual and fidelity suites are frozen T12 artifacts. T13 classifier
is unchanged; only the T14 necessity router differs.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(cmd):
    print("::", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(REPO))
    print(":: exit", r.returncode, flush=True)
    if r.returncode != 0:
        raise SystemExit(r.returncode)


def main() -> int:
    run([sys.executable, "-u", "scripts/t12_scicomp_eval.py",
         "--suite", "conceptual", "--arm", "B",
         "--label", "t14a-conceptual-B",
         "--out-root", "evaluations/t14/runs",
         "--max-new-tokens", "700"])
    run([sys.executable, "-u", "scripts/t12_scicomp_eval.py",
         "--suite", "fidelity", "--arm", "B",
         "--label", "t14a-fidelity-B",
         "--out-root", "evaluations/t14/runs",
         "--max-new-tokens", "700"])
    print("T14A_REMAINING_GPU_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
