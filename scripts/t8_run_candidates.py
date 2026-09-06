"""T8 candidate pipeline driver (GPU-sequential).

Waits for the control capacity eval to finish (its summary.json appearing
under evaluations/t8/runs/qwen3-1.7b-control/model/), then for each
candidate:
  1. hardware probe  (t8_hardware_probe.py) — if it fails or the smoke is
     degenerate, the capacity eval is SKIPPED and the failure recorded
  2. model-only capacity eval (run_capacity_eval.py)

Phi-4-mini-reasoning gets --max-new-tokens 2048 (card-mandated long-CoT
comparator; exception recorded per T8.7 rules). Everything else runs the
matched 1024 default.

Finally runs t8_pareto_select.py. All stdout goes to the driver log.

Usage: python scripts/t8_run_candidates.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "evaluations" / "t8" / "runs"
CONTROL_SUMMARY = RUNS / "qwen3-1.7b-control" / "model" / "summary.json"
STATE = REPO / "evaluations" / "t8" / "candidate_pipeline_state.json"

# (model_id, label, max_new_tokens, note)
CANDIDATES = [
    ("Qwen/Qwen3-4B-Instruct-2507", "qwen3-4b-instruct", 1024, ""),
    ("microsoft/Phi-4-mini-instruct", "phi4-mini-instruct", 1024, ""),
    ("microsoft/Phi-4-mini-reasoning", "phi4-mini-reasoning", 2048,
     "long-CoT comparator: card-guided 2048 max_new_tokens (T8.7 exception)"),
    ("HuggingFaceTB/SmolLM3-3B", "smollm3-3b", 1024, ""),
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def wait_for_control() -> bool:
    if CONTROL_SUMMARY.exists():
        log("control summary already present")
        return True
    log("waiting for control capacity eval to finish "
        "(summary.json not yet written)...")
    deadline = time.time() + 6 * 3600
    while time.time() < deadline:
        time.sleep(60)
        if CONTROL_SUMMARY.exists():
            log("control summary detected")
            return True
    log("TIMEOUT waiting for control eval")
    return False


def run(cmd: list[str]) -> int:
    log("$ " + " ".join(cmd))
    r = subprocess.run([sys.executable, *cmd], cwd=str(REPO))
    log(f"exit code {r.returncode}")
    return r.returncode


def main() -> int:
    state: dict = {"candidates": {}}
    if not wait_for_control():
        state["error"] = "control eval did not finish in time"
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return 1

    for model_id, label, max_new, note in CANDIDATES:
        rec: dict = {"model": model_id, "max_new_tokens": max_new}
        if note:
            rec["note"] = note

        # 1. hardware probe
        rc = run(["scripts/t8_hardware_probe.py", "--model", model_id,
                  "--label", label])
        probe = REPO / "evaluations" / "t8" / "hardware" / f"{label}.json"
        probe_ok = rc == 0 and probe.exists() and \
            json.loads(probe.read_text(encoding="utf-8")).get("ok")
        rec["probe_ok"] = probe_ok
        if not probe_ok:
            rec["eval"] = "SKIPPED (probe failed or smoke degenerate)"
            state["candidates"][label] = rec
            STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
            log(f"{label}: PROBE FAILED — skipping capacity eval")
            continue

        # 2. model-only capacity eval
        cmd = ["scripts/run_capacity_eval.py", "--model", model_id,
               "--label", label, "--max-new-tokens", str(max_new)]
        rc = run(cmd)
        summary = RUNS / label / "model" / "summary.json"
        rec["eval_exit_code"] = rc
        rec["eval_ok"] = summary.exists() and \
            json.loads(summary.read_text(encoding="utf-8")).get("ok", False)
        state["candidates"][label] = rec
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        log(f"{label}: eval_ok={rec['eval_ok']}")

    # 3. Pareto selection over whatever completed
    run(["scripts/t8_pareto_select.py"])
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    log("candidate pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())