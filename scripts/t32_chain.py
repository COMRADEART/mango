"""T32 operational chain: train candidates + dev evals + selection + final eval.

Serial, idempotent, independent of any agent session background-task system.
Each step is skipped when its output artifact already exists, so the script
can be re-run after interruption (training itself also resumes from the last
checkpoint via run_training). Rules are the predeclared DEV_PROTOCOL.md.

Usage (from the repo root, any terminal):
    set PYTHONPATH=src
    python -u scripts/t32_chain.py

Only NEW artifacts are produced; every step logs to evaluations/t32/development/<step>_log.txt.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(".").resolve()
DEV = ROOT / "evaluations" / "t32" / "development"
CANDS = {
    "A": "t32-A-math-restore",
    "B": "t32-B-task-balanced",
    "C": "t32-C-conservative",
}


def log(step: str, msg: str) -> None:
    print(f"chain [{step}] {msg}", flush=True)


def run(step: str, argv: list[str]) -> int:
    import os

    env = dict(os.environ, PYTHONPATH="src")
    with open(DEV / f"{step}_log.txt", "ab") as f:
        f.write(f"\n===== {step} relaunch {time.strftime('%F %T')} =====\n".encode())
        p = subprocess.run([sys.executable, "-u", "-m", *argv], env=env,
                           stdout=f, stderr=subprocess.STDOUT)
    log(step, f"exit={p.returncode}")
    return p.returncode


def train_done(tag: str) -> bool:
    m = ROOT / "training" / "adapters" / CANDS[tag] / "training_manifest.json"
    return m.exists()


def dev_metrics(label: str) -> dict | None:
    p = DEV / f"{label}_metrics.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    DEV.mkdir(parents=True, exist_ok=True)

    # ---- 1-3. train + dev-eval A, B, C ----
    for tag in "ABC":
        name = CANDS[tag]
        if train_done(tag):
            log(f"train_{tag}", f"manifest exists; skipping training for {name}")
        else:
            t = time.time()
            if run(f"train_{tag}",
                   ["sciencemath.t32.train_candidate",
                    "--candidate", tag]) != 0:
                log(f"train_{tag}", "FAILED; stopping chain")
                return 1
            log(f"train_{tag}", f"wall {time.time() - t:.0f}s")

        label = f"t32-{tag}"
        if dev_metrics(label):
            log(f"dev_{tag}", "metrics exist; skipping dev eval")
        else:
            t = time.time()
            if run(f"dev_{tag}",
                   ["sciencemath.t32.dev_eval",
                    "--arm-dir", f"training/adapters/{name}",
                    "--label", label]) != 0:
                log(f"dev_{tag}", "FAILED; stopping chain")
                return 1
            log(f"dev_{tag}", f"wall {time.time() - t:.0f}s")

    # ---- 4. Phase 8 selection (predeclared rule) ----
    if run("selection", ["sciencemath.t32.selection",
                         "--candidates", "t32-A,t32-B,t32-C"]) != 0:
        log("selection", "FAILED; stopping chain")
        return 1
    sel = json.loads((DEV / "T32_PHASE8_SELECTION.json").read_text(
        encoding="utf-8"))
    selected = sel.get("selected")
    if not selected:
        log("selection", "no candidate selected; stopping chain")
        return 1
    log("selection", f"selected={selected}")

    # ---- 5. Phase 9 final locked eval (ONE run) ----
    if (ROOT / "evaluations" / "t32" / "final" / selected).exists() and \
            all((ROOT / "evaluations" / "t32" / "final" / selected /
                 f"{b}.jsonl").exists() for b in
                ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq")):
        log("final", "fresh arm rows already complete; skipping")
    else:
        t = time.time()
        if run("final",
               ["sciencemath.t32.final_eval",
                "--adapter-dir", f"training/adapters/{CANDS[selected[-1]]}",
                "--arm-name", selected]) != 0:
            log("final", "FAILED; stopping chain")
            return 1
        log("final", f"wall {time.time() - t:.0f}s")

    # ---- 6. paired analysis ----
    return run("paired", ["sciencemath.t32.paired", selected])


if __name__ == "__main__":
    raise SystemExit(main())