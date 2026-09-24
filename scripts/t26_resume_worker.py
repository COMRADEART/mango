#!/usr/bin/env python3
"""Separate-process checkpoint/resume control for synthetic T26 rehearsal."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from sciencemath.integrated.runner import IntegratedRunner  # noqa: E402
from t26_protocol.qualification import fixture_adapters, make_case  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"interrupt", "resume"}:
        raise SystemExit("usage: t26_resume_worker.py interrupt|resume sandbox")
    phase, sandbox = sys.argv[1], Path(sys.argv[2])
    scenario, _, injection = make_case("plan_replan_resume", 1)
    runner = IntegratedRunner(fixture_adapters(injection), sandbox_root=sandbox)
    output = runner.run(scenario, stop_after_steps=1) if phase == "interrupt" else runner.run(scenario, resume=True)
    print(json.dumps({"pid": __import__("os").getpid(),
                      "terminal": output["terminal"],
                      "verified_steps": output["verified_steps"],
                      "step_one_calls": sum(e.get("step_id") == "s1" and
                                            "capability_selected" in e
                                            for e in output["trace"]),
                      "handoffs": len(output["handoffs"])}))


if __name__ == "__main__":
    main()
