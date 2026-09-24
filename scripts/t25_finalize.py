#!/usr/bin/env python3
"""Post-rehearsal T25 finalization: protection report, freeze, doctor.

Order: the candidate protection report is written first so the freeze binds it;
the preconstruction freeze is written next (refuses to overwrite); the doctor
runs last against the frozen state and its report lands beside it. No real T25
blind material is created and no real namespace is touched; T24's private
material is never opened.
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
    # 1. Candidate protection report (sections 11-13) — must precede the freeze.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "t25_candidate_protection.py")],
                   check=True)

    # 2. Preconstruction freeze (sections 27, 15).
    from t25_protocol.freeze import build_freeze, write_freeze

    freeze = build_freeze(ROOT)
    write_freeze(ROOT, freeze)
    policy = freeze["frozen_policy"]
    print(json.dumps({"freeze_root": freeze["freeze_root"],
                      "freeze_sha256": freeze["freeze_sha256"],
                      "component_count": freeze["component_count"],
                      "frozen_policy": policy,
                      "infrastructure_commit": freeze["infrastructure_commit"]}, indent=1))

    # 3. Production protocol doctor (section 26) against the frozen state.
    from t25_protocol.doctor import run_t25_doctor

    report = run_t25_doctor(ROOT)
    (ROOT / "evaluations" / "t25" / "protocol_doctor_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    failed = [name for name, check in report["checks"].items()
              if check.get("status") != "PASS"]
    print(json.dumps({"verdict": report["verdict"], "check_count": len(report["checks"]),
                      "failed": failed}, indent=1))
    if report["verdict"] != "T25_PRODUCTION_PROTOCOL_DOCTOR_PASS":
        raise SystemExit("T25 PROTOCOL DOCTOR FAILED")
    print("T25 FINALIZATION COMPLETE")


if __name__ == "__main__":
    main()