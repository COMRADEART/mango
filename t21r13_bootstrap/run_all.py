#!/usr/bin/env python3
import subprocess, sys
from pathlib import Path
ROOT = Path.cwd()
boot = Path(__file__).resolve().parent
steps = [
    "phase_a_closure.py",
    "phase_b_r13_core.py",
    "phase_c_synth_qualify.py",
]
for name in steps:
    print("====", name)
    proc = subprocess.run([sys.executable, str(boot / name)], cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
print("ALL_PHASES_OK")
