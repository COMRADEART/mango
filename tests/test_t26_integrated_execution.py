from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciencemath.integrated.runner import (AUTHORITY, Adapter, ExecutionError,
                                           IntegratedRunner, RecoverableError,
                                           validate_plan)
from t26_protocol.lifecycle import (T26PrivateStore, require_token,
                                    validate_blind_cases)
from t26_protocol.native_smoke import native_case, run_native_smoke
from t26_protocol.production import _sandbox
from t26_protocol.qualification import (build_public_cases, fixture_adapters,
                                         make_case, run_qualification)
from t26_protocol.rehearsal import run_rehearsals
from t26_protocol.qualification import exclusion_fingerprints


def test_public_qualification_covers_all_families_and_floors():
    report = run_qualification()
    assert report["status"] == "PASS"
    assert report["family_count"] == 16
    assert report["scenario_count"] == 64
    assert report["dispatch_unmatched"] == 0
    assert report["unexpected_unknown_terminal"] == 0
    assert all(value == 0 for value in report["score"]["critical_counters"].values())


def test_native_math_and_scicomp_handoff(tmp_path: Path):
    cases, _, _ = build_public_cases()
    exclusions = exclusion_fingerprints(cases + [native_case()[0]])
    root = Path(__file__).resolve().parents[1]
    report = run_native_smoke(root, exclusions)
    assert report["status"] == "PASS"
    assert report["verified_steps"] == 3
    assert report["handoffs"] == 2


def test_two_rehearsals_recover_resume_and_refuse_authority():
    report = run_rehearsals()
    assert report["status"] == "PASS"
    assert len(report["runs"]) == 2
    assert set(report["semantic_diffs"].values()) == {0}
    for run in report["runs"]:
        assert run["recovery"]["retry_count"] == 2
        assert run["recovery"]["replan_count"] == 1
        assert run["resume"]["step_one_calls_after_resume"] == 1
        assert run["authority_adversarial"]["critical_violations"] == 0


def test_unknown_and_external_authority_fail_before_execution(tmp_path: Path):
    scenario, _, injection = make_case("math_chain", 0)
    counter = {"calls": 0}
    def adapter(payload, context):
        counter["calls"] += 1
        return fixture_adapters(injection)["MATH_T4"].execute(payload, context)
    adapters = fixture_adapters(injection)
    adapters["MATH_T4"] = Adapter("MATH_T4", adapter)
    invalid = json.loads(json.dumps(scenario))
    invalid["gold"] = {"answer": 10}
    with pytest.raises(ExecutionError):
        IntegratedRunner(adapters, sandbox_root=tmp_path).run(invalid)
    invalid = json.loads(json.dumps(scenario))
    invalid["plan"]["authority"] = "PERFORM_EXTERNAL_ACTION"
    with pytest.raises(ExecutionError):
        IntegratedRunner(adapters, sandbox_root=tmp_path).run(invalid)
    assert counter["calls"] == 0


def test_unverified_result_cannot_complete(tmp_path: Path):
    scenario, _, injection = make_case("math_chain", 0)
    adapters = fixture_adapters(injection)
    original = adapters["GENERAL"].execute
    def corrupt(payload, context):
        output = original(payload, context)
        output["value"] += 9
        return output
    adapters["GENERAL"] = Adapter("GENERAL", corrupt)
    output = IntegratedRunner(adapters, sandbox_root=tmp_path).run(scenario)
    assert output["terminal"] == "ERROR"
    assert output["verified_steps"] == ["s1", "s2"]
    assert output["final_answer"] is None
    assert output["trace"][-1]["verification_result"] == "FAIL"


def test_checkpoint_tamper_and_second_execution_refused(tmp_path: Path):
    scenario, _, injection = make_case("math_chain", 1)
    runner = IntegratedRunner(fixture_adapters(injection), sandbox_root=tmp_path)
    partial = runner.run(scenario, stop_after_steps=1)
    assert partial["terminal"] == "PARTIAL"
    with pytest.raises(ExecutionError):
        runner.run(scenario)
    checkpoint = tmp_path / "checkpoints" / f"{scenario['scenario_id']}.json"
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    data["state"]["authority"] = "PERFORM_EXTERNAL_ACTION"
    checkpoint.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ExecutionError):
        runner.run(scenario, resume=True)


def test_disposable_storage_and_tokens_fail_closed(tmp_path: Path):
    store = T26PrivateStore(tmp_path / "T26-STORE-01", tmp_path / "public")
    assert store.locator("control/example.json").startswith("t26-private://")
    with pytest.raises(PermissionError):
        require_token("T26_ONE_SHOT_OFFICIAL_EVALUATION-v2", "evaluation")
    with pytest.raises(ValueError):
        store.path("../escape")
    store.write_once("control/example.json", {"public_safe_fixture": True})
    with pytest.raises(FileExistsError):
        store.write_once("control/example.json", {})
    with pytest.raises(ValueError, match="exclusion oracle"):
        validate_blind_cases([], [], {}, {})


def test_code_and_memory_sandbox_escape_refused(tmp_path: Path):
    with pytest.raises(ExecutionError):
        _sandbox({"sandbox_root": str(tmp_path)}, "../outside")
    scenario, _, _ = make_case("memory_assisted_multiturn", 0)
    assert validate_plan(scenario["plan"])["authority"] == AUTHORITY
