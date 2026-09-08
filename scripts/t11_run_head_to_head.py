"""Driver: full T11.20 head-to-head run (arms A then B, GPU-sequential)."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

for arm in ("A", "B"):
    r = subprocess.run(
        [sys.executable, "scripts/t11_scicomp_head_to_head.py",
         "--arm", arm, "--label", f"t11-h2h-arm{arm.lower()}"],
        cwd=str(REPO))
    print(f":: arm {arm} exit {r.returncode}", flush=True)

print("HEAD_TO_HEAD_DONE", flush=True)