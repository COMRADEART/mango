"""T30 recovery-reachability remediation invariants (disposable material only)."""
from __future__ import annotations

import copy
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import Adapter, ExecutionError, RecoverableError
from t30_protocol.recovery_control import (
    ATTESTED_ADAPTER_BUILDER, CONTROL_PATH, FAULT_MESSAGE, RecoveryControlError,
    adapter_builder_identity, build_recovery_control,
    check_designation_consistency, derive_recoverable_labels,
    unchanged_semantics_report, validate_control_shape,
    validate_recovery_control, wrap_production_adapters)
from t30_protocol.reachability import (production_disposable_bundle,
                                       production_disposable_control,
                                       production_disposable_scenarios)
from t30_protocol.store import PreLedgerViolation, T30PrivateStore

ROOT = Path(__file__).resolve().parents[1]


def test_official_environment_uses_attested_t30_adapter_registry():
    from t30_protocol import official_environment
    from t30_protocol.production import build_adapters
    assert official_environment.build_adapters is build_adapters
    assert adapter_builder_identity(build_adapters) == ATTESTED_ADAPTER_BUILDER
    source = inspect.getsource(official_environment)
    assert "from t26_protocol.production import build_adapters" not in source
    assert "fixture_adapters" not in source


def test_control_generated_from_scenarios_and_labels_derived():
    cases, gold, _fixtures, control = production_disposable_bundle(31)
    assert "gold" not in inspect.signature(build_recovery_control).parameters
    assert validate_recovery_control(control, cases)["status"] == "PASS"
    labels = derive_recoverable_labels(control)
    assert labels == {row["scenario_id"] for row in gold
                      if row["designated_recoverable"]}
    assert len(labels) >= 32
    assert check_designation_consistency(control, gold)["status"] == "PASS"
    assert all(entry["capability"] in {"MATH_T4", "SCICOMP"}
               for entry in control["entries"])


def test_control_refuses_gold_fields_and_bad_injection_counts():
    _cases, _gold, _fixtures, control = production_disposable_bundle(32)
    for key, value in (("expected_answer", 1), ("expected_terminal", "X"),
                       ("max_injections", 2), ("fault_class", "OTHER")):
        tampered = copy.deepcopy(control)
        tampered["entries"][0][key] = value
        with pytest.raises(RecoveryControlError):
            validate_control_shape(tampered)
    with pytest.raises(RecoveryControlError):
        validate_control_shape(None)


def test_control_refuses_unqualified_or_budgetless_targets():
    cases, _designs = production_disposable_scenarios(33)
    subset = copy.deepcopy(cases[:4])
    subset[0]["plan"]["steps"][0]["capability"] = "GENERAL"
    with pytest.raises(RecoveryControlError):
        build_recovery_control(subset, [(subset[0]["scenario_id"], "s1")])
    subset = copy.deepcopy(cases[:4])
    subset[0]["plan"]["budgets"]["max_step_retries"] = 0
    with pytest.raises(RecoveryControlError):
        build_recovery_control(subset, [(subset[0]["scenario_id"], "s1")])


def test_wrapper_injects_exactly_once_and_isolates_scenarios():
    calls = {"n": 0}

    def delegate(payload, context):
        calls["n"] += 1
        return {"status": "OK"}
    base = {capability: Adapter(capability, delegate) for capability in SKILL_IDS}
    entry = {"scenario_id": "t30-disposable-a", "step_id": "s2",
             "capability": "MATH_T4",
             "fault_class": "TRANSIENT_RECOVERABLE_ERROR", "max_injections": 1}
    wrapped, audit = wrap_production_adapters(
        base, scenario_id="t30-disposable-a", entry=entry)
    context = {"scenario_id": "t30-disposable-a", "step_id": "s2"}
    with pytest.raises(RecoverableError, match=FAULT_MESSAGE):
        wrapped["MATH_T4"].execute({}, context)
    assert wrapped["MATH_T4"].execute({}, context) == {"status": "OK"}
    assert wrapped["MATH_T4"].execute({}, context) == {"status": "OK"}
    assert audit.injections == 1 and calls["n"] == 2
    assert wrapped["MATH_T4"].internal_only is True
    assert wrapped["MATH_T4"].may_perform_external_action is False
    with pytest.raises(ExecutionError):
        wrapped["MATH_T4"].execute({}, {"scenario_id": "t30-other",
                                        "step_id": "s2"})
    unscheduled, other = wrap_production_adapters(
        base, scenario_id="t30-disposable-b", entry=None)
    assert all(unscheduled[name] is base[name] for name in base)
    assert other.injections == 0


def test_control_is_ledger_guarded_in_store():
    _cases, _gold, _fixtures, control = production_disposable_bundle(34)
    with TemporaryDirectory(prefix="t30-control-guard-") as tmp:
        store = T30PrivateStore(Path(tmp) / "private", repository_root=ROOT,
                                disposable=True)
        store.write_once_json(CONTROL_PATH, control)
        with pytest.raises(PreLedgerViolation):
            store.read_bytes(CONTROL_PATH)
        descriptor = store.descriptor(CONTROL_PATH, "PRIVATE_EVALUATION_CONTROL")
        assert len(descriptor["sha256"]) == 64


def test_candidate_projection_refuses_control_fields():
    from t30_protocol.construction import candidate_input_projection
    cases, _designs = production_disposable_scenarios(35)
    scenario = copy.deepcopy(cases[0])
    assert candidate_input_projection(scenario) == scenario
    scenario["plan"]["steps"][0]["input"]["fault_class"] = "X"
    with pytest.raises(ValueError):
        candidate_input_projection(scenario)


def test_static_design_requires_recovery_control():
    from t30_protocol.construction import (author_provenance,
                                           static_design_audit,
                                           synthetic_oracle_result)
    cases, gold, fixtures, control = production_disposable_bundle(36)
    oracle = synthetic_oracle_result(cases, gold, variant=36)
    provenance = author_provenance("T30-TEST", "e" * 64, "2026-09-30T00:00:00+00:00")
    passed = static_design_audit(cases, gold, fixtures, oracle, provenance,
                                 recovery_control=control)
    assert passed["status"] == "PASS", passed["failed_checks"]
    missing = static_design_audit(cases, gold, fixtures, oracle, provenance)
    assert missing["status"] == "FAIL"
    assert "recovery_control.present" in missing["failed_checks"]
    tampered = copy.deepcopy(gold)
    index = next(i for i, row in enumerate(tampered)
                 if not row["designated_recoverable"])
    tampered[index]["designated_recoverable"] = True
    mismatch = static_design_audit(cases, tampered, fixtures,
                                   synthetic_oracle_result(cases, tampered,
                                                           variant=36),
                                   provenance, recovery_control=control)
    assert "recovery_control.gold_designation_derived" in mismatch["failed_checks"]


def test_scorer_metric_and_nonvacuity_semantics_unchanged():
    report = unchanged_semantics_report(ROOT)
    assert report["unchanged"] is True, report["observed_sha256"]


def test_production_stack_recovery_through_official_factory():
    """Real production adapters + recovery wrapper on disposable scenarios."""
    from t30_protocol.reachability import execute_production_stack
    from t30_protocol.scorer import score_suite
    cases, designs = production_disposable_scenarios(37)
    subset = [index for index, design in enumerate(designs)
              if design["family"] == designs[0]["family"]][:8]
    sub_cases = [cases[index] for index in subset]
    sub_designs = [designs[index] for index in subset]
    control = production_disposable_control(sub_cases, designs=sub_designs)
    from t30_protocol.reachability import _gold
    gold = _gold(sub_cases, sub_designs, control)
    run = execute_production_stack(ROOT, sub_cases, control)
    score = score_suite(run["outputs"], gold, [case["plan"] for case in sub_cases])
    assert run["stack"]["adapter_builder_actual"] == ATTESTED_ADAPTER_BUILDER
    recovery = score["metrics"]["recovery_success_rate"]
    assert recovery["denominator"] == 2 and recovery["numerator"] == 2
    assert score["metrics"]["replan_correctness_rate"]["pass"] is True
    assert score["metrics"]["safe_abstention_accuracy"]["pass"] is True
    assert sum(audit.injections for audit in run["audits"]) == 2
