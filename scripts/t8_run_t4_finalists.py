"""T8.15 — T4 integration arms for the two finalists (GPU-sequential)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAIRS = [
    ("Qwen/Qwen3-4B-Instruct-2507", "qwen3-4b-instruct", 1024),
    ("microsoft/Phi-4-mini-reasoning", "phi4-mini-reasoning", 2048),
]

for model, label, mx in PAIRS:
    print(f"=== T4 arm: {label} (max_new_tokens={mx}) ===", flush=True)
    cmd = [sys.executable, "scripts/t8_t4_arm.py", "--model", model,
           "--label", label, "--max-new-tokens", str(mx)]
    r = subprocess.run(cmd, cwd=str(REPO))
    print(f"--- {label} exit {r.returncode}", flush=True)
print("T4 finalist arms complete", flush=True)