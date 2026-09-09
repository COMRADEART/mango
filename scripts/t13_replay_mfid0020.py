"""T13.15 — mfid-v1-0020 empty-container replay (T12-DEF-1 regression).

T12 defect: ``ValueError: max() iterable argument is empty`` in
``_merge_sub_results`` when the faithful structured request carried an
empty container (``initial_state: []``), surfacing as
PIPELINE_EXCEPTION.  T13 requirement: the fidelity layer now
(1) classifies the request deterministically — no exception,
(2) approves the faithful request (empty container == empty container,
    null != zero != empty discipline intact), and
(3) the frozen engine still rejects the compute (INVALID_INPUT).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (  # noqa: E402
    FIDELITY_FAIL, check_fidelity, validate_planner_request)
from sciencemath.scicomp.invocation import invoke  # noqa: E402

OUT = ROOT / "evaluations/t13/def1_mfid0020_replay.json"

REQUEST = {
    "operation": "solve_ode",
    "parameters": {"equations": ["3*y0"], "initial_state": [],
                   "t_start": 0.0, "t_end": 1.0},
    "source_inputs": {"equations": ["3*y0"], "initial_state": [],
                      "t_start": 0.0, "t_end": 1.0},
    "parameter_provenance": {"equations": "USER_GIVEN",
                             "initial_state": "USER_GIVEN",
                             "t_start": "USER_GIVEN", "t_end": "USER_GIVEN"},
    "preserve_verbatim": [],
    "expected_result_type": "series",
    "reason_for_compute": "T13.15 replay of mfid-v1-0020 (no initial "
                          "condition given; empty container is faithful)",
}
QUESTION = ("Solve the ODE dy/dt = 3*y with no initial condition given, "
            "from t = 0 to t = 1.")


def main() -> int:
    rec = {"eval_id": "mfid-v1-0020", "defect": "T12-DEF-1"}

    # 1. deterministic fidelity classification — no exception
    schema = validate_planner_request(REQUEST)
    rec["schema_ok"] = bool(schema["ok"])
    rec["schema_failures"] = schema["failures"]
    try:
        fid = check_fidelity(REQUEST, QUESTION)
        rec["fidelity_status"] = fid.status
        rec["fidelity_failures"] = fid.failures
        rec["no_exception"] = True
    except Exception as exc:
        rec["no_exception"] = False
        rec["fidelity_status"] = "REPLAY_EXCEPTION"
        rec["fidelity_failures"] = [f"{type(exc).__name__}: {exc}"]

    # 2. frozen engine still rejects the empty container
    try:
        payload = {"operation": REQUEST["operation"],
                   "inputs": REQUEST["parameters"]}
        result = invoke(payload, QUESTION)
        status = result.envelope.get("status", "unknown")
        rec["engine_status"] = status
        rec["engine_rejects"] = status == "INVALID_INPUT"
    except Exception as exc:
        rec["engine_status"] = f"EXCEPTION {type(exc).__name__}: {exc}"
        rec["engine_rejects"] = False

    checks = {
        "fidelity_no_exception": rec.get("no_exception") is True,
        "fidelity_deterministic_pass": rec.get("fidelity_status")
        not in (None, FIDELITY_FAIL, "REPLAY_EXCEPTION"),
        "engine_still_invalid_input": rec.get("engine_rejects") is True,
    }
    rec["checks"] = checks
    rec["status"] = "PASS" if all(checks.values()) else "FAIL"
    OUT.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(json.dumps(rec, indent=1))
    return 0 if rec["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())