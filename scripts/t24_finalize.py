#!/usr/bin/env python3
"""Post-rehearsal T24 finalization: protection report, freeze, doctor.

Order: the candidate protection report is written first so the freeze binds it;
the preconstruction freeze is written next (refuses to overwrite); the doctor
runs last against the frozen state and its report lands beside it. No real T24
blind material is created and no real namespace is touched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def main() -> None:
    # 1. Candidate protection report (section 32) — must precede the freeze.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "t24_candidate_protection.py")],
                   check=True)

    # 2. Preconstruction freeze (sections 38-39).
    from t24_protocol.freeze import build_freeze, write_freeze
    from t21_protocol.util import read_json

    freeze = build_freeze(ROOT)
    write_freeze(ROOT, freeze)
    policy = freeze["frozen_policy"]
    print(json.dumps({"freeze_root": freeze["freeze_root"],
                      "freeze_sha256": freeze["freeze_sha256"],
                      "component_count": freeze["component_count"],
                      "frozen_policy": policy,
                      "infrastructure_commit": freeze["infrastructure_commit"]}, indent=1))

    # 3. Production protocol doctor (section 33) against the frozen state.
    from t24_protocol.doctor import run_t24_doctor

    report = run_t24_doctor(ROOT)
    (ROOT / "evaluations" / "t24" / "protocol_doctor_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    failed = [name for name, check in report["checks"].items()
              if check.get("status") != "PASS"]
    print(json.dumps({"verdict": report["verdict"], "check_count": len(report["checks"]),
                      "failed": failed}, indent=1))
    if report["verdict"] != "T24_PRODUCTION_PROTOCOL_DOCTOR_PASS":
        raise SystemExit("T24 PROTOCOL DOCTOR FAILED")
    print("T24 FINALIZATION COMPLETE")


if __name__ == "__main__":
    main()