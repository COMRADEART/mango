"""Wrapper smoke: one complete REAL_REHEARSAL evaluate_official + one control."""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
ROOT = Path.cwd()

from t30_protocol.contract import EVALUATION_TOKEN
from t30_protocol.evaluation import (
    _wrapper_rehearsal_skeleton, evaluate_official, run_publication_leak_gate,
)

# --- one complete wrapper drive on a disposable stand-in (variant 1)
with _wrapper_rehearsal_skeleton(ROOT, variant=1, real_shaped=False) as ctx:
    skeleton, store, built = ctx
    print("standin:", json.dumps({k: built[k] for k in (
        "receipt_path", "blind_scenario_count", "blind_gold_count",
        "fixture_count", "disposable_rehearsal_tagged",
        "store_disposable")}, sort_keys=True))
    result = evaluate_official(
        skeleton, store.base, EVALUATION_TOKEN, mode="REAL_REHEARSAL")
    print("wrapper status:", result["status"])
    print("ledger states:", [e["event_type"]
                             for e in result["ledger"]["events"]])
    print("score scenario_count:", result["score"]["scenario_count"])
    print("designated_counts:", result["score"]["designated_counts"])
    print("ordering keys ok:", all(result["ordering"].get(k)
          for k in ("ordering_binding_precedes_blind_reads",
                    "ordering_blind_inputs_before_gold",
                    "ordering_reads_before_workspace",
                    "ordering_workspace_precedes_candidate_execution",
                    "ordering_strictly_increasing")))
    print("gold firewall projected_rows:",
          result["gold_firewall"]["projected_rows"])
    assert result["status"] == "PASS", "smoke wrapper run failed"

# --- REAL-mode directional: adapter absent in mirror -> model_hydration refusal
from t30_protocol.evaluation import OfficialEvaluationRefusal
with _wrapper_rehearsal_skeleton(ROOT, variant=7, real_shaped=True) as ctx:
    skeleton, store, _ = ctx
    try:
        evaluate_official(skeleton, store.base, EVALUATION_TOKEN, mode="REAL")
    except OfficialEvaluationRefusal as exc:
        print("control refusal phase:", exc.phase)
        assert exc.phase == "model_hydration_preflight"
    else:
        raise SystemExit("REAL-mode adapter control did NOT refuse")

print("WRAPPER_SMOKE PASS")