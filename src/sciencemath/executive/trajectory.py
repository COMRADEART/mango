"""T7.30 — Trajectory logging (JSONL, one event per phase transition /
step / decision). No hidden chain of thought: prompts and raw outputs
are recorded, and any <think> block is already stripped in llm.py, so
the log contains exactly what was shown to and produced by the model
for the recorded decision points."""
from __future__ import annotations

import json
import time
from pathlib import Path


class TrajectoryLogger:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, run_id: str, event: str, payload: dict) -> None:
        if not self.path:
            return
        rec = {"ts": time.time(), "run_id": run_id, "event": event,
               "payload": payload}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str)
                    + "\n")