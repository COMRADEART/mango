"""Frozen T30 evaluation transient-fault control (recovery reachability).

Pre-exposure remediation of
``T30_REAL_CONSTRUCTION_REFUSED_DESIGNATED_RECOVERY_UNREACHABLE_IN_FROZEN_REAL_STACK``:
the frozen REAL production adapter stack never raises ``RecoverableError``
and never returns ``RECOVERABLE_ERROR``, so the frozen scorer predicate
``recovery_success = terminal == COMPLETE and total_retries >= 1`` was
unreachable for every designated-recoverable scenario.

The remediation does NOT redefine the metric, lower the floor, remove the
recoverable population, or make production providers emit recovery
statuses.  Recovery stimulation lives in the evaluation-control layer:

* a PRIVATE_EVALUATION_CONTROL schedule (never gold, never candidate input)
  names ``(scenario_id, step_id, capability)`` targets on qualified local
  deterministic capabilities;
* the schedule is generated from candidate-visible scenarios only, and the
  ``designated_recoverable`` gold label is derived one-way FROM it;
* a wrapper sits AROUND the unchanged T30 production adapters and raises
  exactly one ``RecoverableError("T30_FROZEN_TRANSIENT_EVALUATION_FAULT")``
  on the first matching invocation, then delegates unchanged;
* state is per scenario runner (no persistence across scenarios).

Topology: IntegratedRunner -> recovery-control wrapper -> T30 production
Adapter -> real local implementation.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from t21_protocol.util import sha256_json

from sciencemath.integrated.runner import (Adapter, ExecutionError,
                                           RecoverableError)

SCHEMA_VERSION = "t30-recovery-control-v1"
ARTIFACT = "T30_RECOVERY_CONTROL"
POLICY_SCHEMA_VERSION = "t30-recovery-control-policy-v1"
CONTROL_PATH = "control/recovery_control.json"
STORE_CLASSIFICATION = "PRIVATE_EVALUATION_CONTROL"
DOCUMENT_CLASSIFICATIONS = frozenset({"PRIVATE_EVALUATION_CONTROL",
                                      "SYNTHETIC_DISPOSABLE"})
FAULT_CLASS = "TRANSIENT_RECOVERABLE_ERROR"
FAULT_MESSAGE = "T30_FROZEN_TRANSIENT_EVALUATION_FAULT"
MAX_INJECTIONS = 1
ENTRY_FIELDS = ("scenario_id", "step_id", "capability", "fault_class",
                "max_injections")
DOCUMENT_FIELDS = frozenset({
    "schema_version", "artifact", "classification", "scenario_bundle_root",
    "entries", "entry_count", "policy_root",
})
#: §17: only qualified local deterministic capabilities whose normal second
#: attempt succeeds without any uncontrolled external/transient service.
QUALIFIED_TARGET_CAPABILITIES = ("MATH_T4", "SCICOMP")
#: §13/§16: the control must never carry a gold or scoring field.
FORBIDDEN_CONTROL_FIELDS = frozenset({
    "expected_answer", "expected_terminal", "designated_recoverable",
    "designated_abstention", "expected_replan_trigger",
    "expected_fallback_capability", "expected_verified_steps",
    "metric_designations", "gold", "family", "score", "metrics",
})
#: §15: never visible to the candidate.
CANDIDATE_HIDDEN_FIELDS = frozenset({
    "recovery_control", "fault_schedule", "fault_class",
    "designated_recoverable", "injection_count", "max_injections",
})
WRAPPER_ID = "t30_protocol.recovery_control:wrap_production_adapters"
ATTESTED_ADAPTER_BUILDER = "t30_protocol.production:build_adapters"
#: §5/§26: scorer, metric registry and nonvacuity policy are UNCHANGED by the
#: remediation — pinned (LF-normalized) from the pre-remediation T30
#: preconstruction commit 252b3de1d2606e7aa67626aacbd2daa0bf46b193.
PRE_REMEDIATION_COMMIT = "252b3de1d2606e7aa67626aacbd2daa0bf46b193"
UNCHANGED_SEMANTICS_SHA256 = {
    "t30_protocol/scorer.py":
        "0d67b3ac17071f1c470767e85c612728dc8d0a1f10eb48e8da8bf7c9ff3a271c",
    "evaluations/t30/metric_registry.json":
        "372b5ab67075d6ff0563253ecd79ded6230f034b1bb7a1a68a7639ef54b6bbb0",
    "evaluations/t30/nonvacuity_policy.json":
        "20f3ad5a1412599c58934b464a1d94db05e5aba586d2d84e1c1096a2e028c2f6",
    "t30_protocol/contract.py":
        "f75793b4a63c32ced2047088c63a19872e4e5fd00fa499f724c89f595cfd286b",
}


def unchanged_semantics_report(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    observed = {}
    for relative in UNCHANGED_SEMANTICS_SHA256:
        try:
            data = (root / relative).read_bytes().replace(b"\r\n", b"\n")
            observed[relative] = hashlib.sha256(data).hexdigest()
        except OSError:
            observed[relative] = None
    exact = observed == UNCHANGED_SEMANTICS_SHA256
    return {"pre_remediation_commit": PRE_REMEDIATION_COMMIT,
            "expected_sha256": dict(UNCHANGED_SEMANTICS_SHA256),
            "observed_sha256": observed, "unchanged": exact}


class RecoveryControlError(ValueError):
    """Malformed, gold-dependent, candidate-visible or unsafe control."""


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


def recovery_control_policy() -> dict[str, Any]:
    core = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "artifact": "T30_RECOVERY_CONTROL_POLICY",
        "classification": "PUBLIC_SAFE",
        "remediation": "FROZEN_EVALUATION_TRANSIENT_FAULT_CONTROL",
        "control_schema_version": SCHEMA_VERSION,
        "control_path": CONTROL_PATH,
        "store_classification": STORE_CLASSIFICATION,
        "entry_fields": list(ENTRY_FIELDS),
        "fault_class": FAULT_CLASS, "fault_message": FAULT_MESSAGE,
        "max_injections": MAX_INJECTIONS,
        "qualified_target_capabilities": list(QUALIFIED_TARGET_CAPABILITIES),
        "forbidden_control_fields": sorted(FORBIDDEN_CONTROL_FIELDS),
        "candidate_hidden_fields": sorted(CANDIDATE_HIDDEN_FIELDS),
        "causal_order": [
            "author_and_finalize_candidate_visible_scenarios",
            "generate_recovery_control_from_scenarios_only",
            "derive_designated_recoverable_from_control",
            "finalize_gold", "freeze_package"],
        "designation_rule":
            "set(control.scenario_id) == set(gold.designated_recoverable)",
        "wrapper": WRAPPER_ID,
        "wrapped_adapter_builder": ATTESTED_ADAPTER_BUILDER,
        "second_matching_invocation": "DELEGATE_UNCHANGED",
        "state_scope": "PER_SCENARIO_RUNNER",
        "evaluation_ordering": [
            "preflight", "environment_identity", "STARTED_ledger_and_marker",
            "recovery_control_read", "blind_inputs_read", "gold_read",
            "workspace_creation", "candidate_execution", "EXECUTED",
            "SCORED", "COMPLETE"],
        "preledger_binding_only": [
            "recovery_control_sha256", "recovery_control_schema",
            "recovery_control_population", "recovery_control_policy_root"],
        "scorer_semantics_unchanged": True,
        "recovery_success_predicate":
            "terminal == COMPLETE and budget_state.total_retries >= 1",
        "recovery_success_rate_floor": 1.0,
        "zero_denominator_policy": "FAIL_NONVACUITY",
        "production_provider_status_normalization_unchanged": True,
    }
    return {**core, "policy_root": sha256_json(core)}


POLICY_ROOT = recovery_control_policy()["policy_root"]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def control_sha256(document: dict[str, Any]) -> str:
    """SHA-256 of the exact bytes the private store materializes."""
    return hashlib.sha256(_json_bytes(document)).hexdigest()


def scenario_bundle_root(cases: list[dict[str, Any]]) -> str:
    """Root over candidate-visible scenario bodies only (never gold)."""
    return sha256_json([sha256_json(item) for item in cases])


# ---------------------------------------------------------------------------
# generation (scenarios only) and validation
# ---------------------------------------------------------------------------


def _step_index(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for scenario in cases:
        if not isinstance(scenario, dict) or "scenario_id" not in scenario:
            raise RecoveryControlError("recovery control scenario malformed")
        index[scenario["scenario_id"]] = scenario
    return index


def _target_supported(scenario: dict[str, Any], step_id: str,
                      capability: str) -> None:
    plan = scenario.get("plan") or {}
    steps = {item.get("step_id"): item for item in plan.get("steps", [])}
    step = steps.get(step_id)
    if step is None:
        raise RecoveryControlError("recovery control names an unknown step")
    if step.get("capability") != capability:
        raise RecoveryControlError("recovery control capability mismatch")
    if capability not in QUALIFIED_TARGET_CAPABILITIES:
        raise RecoveryControlError(
            "recovery control targets a nonlocal/unqualified capability "
            "where deterministic recovery cannot be shown")
    budgets = plan.get("budgets") or {}
    if (budgets.get("max_step_retries", 0) < 1
            or budgets.get("max_total_retries", 0) < 1):
        raise RecoveryControlError(
            "recovery control target has no retry budget")


def build_recovery_control(cases: list[dict[str, Any]],
                           targets: list[tuple[str, str]], *,
                           classification: str = STORE_CLASSIFICATION
                           ) -> dict[str, Any]:
    """§14 step 2: generate the schedule from candidate-visible scenarios.

    ``targets`` is a list of ``(scenario_id, step_id)``; the capability is
    read from the scenario plan.  No gold is accepted by this function.
    """
    index = _step_index(cases)
    entries = []
    for scenario_id, step_id in targets:
        scenario = index.get(scenario_id)
        if scenario is None:
            raise RecoveryControlError("recovery control names an unknown scenario")
        step = next((item for item in scenario["plan"]["steps"]
                     if item["step_id"] == step_id), None)
        if step is None:
            raise RecoveryControlError("recovery control names an unknown step")
        entries.append({"scenario_id": scenario_id, "step_id": step_id,
                        "capability": step["capability"],
                        "fault_class": FAULT_CLASS,
                        "max_injections": MAX_INJECTIONS})
    entries.sort(key=lambda item: (item["scenario_id"], item["step_id"]))
    document = {
        "schema_version": SCHEMA_VERSION, "artifact": ARTIFACT,
        "classification": classification,
        "scenario_bundle_root": scenario_bundle_root(cases),
        "entries": entries, "entry_count": len(entries),
        "policy_root": POLICY_ROOT,
    }
    validate_recovery_control(document, cases)
    return document


def _scan_forbidden(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in FORBIDDEN_CONTROL_FIELDS or _scan_forbidden(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_scan_forbidden(item) for item in value)
    return False


def validate_control_shape(document: Any) -> dict[str, Any]:
    """Schema-only validation (no scenario access)."""
    if not isinstance(document, dict):
        raise RecoveryControlError("recovery control missing or not an object")
    if _scan_forbidden(document):
        raise RecoveryControlError("gold/scoring field present in recovery control")
    if set(document) != DOCUMENT_FIELDS:
        raise RecoveryControlError("recovery control schema malformed")
    if (document["schema_version"] != SCHEMA_VERSION
            or document["artifact"] != ARTIFACT
            or document["classification"] not in DOCUMENT_CLASSIFICATIONS
            or document["policy_root"] != POLICY_ROOT):
        raise RecoveryControlError("recovery control identity mismatch")
    entries = document["entries"]
    if (not isinstance(entries, list) or type(document["entry_count"]) is not int
            or document["entry_count"] != len(entries)):
        raise RecoveryControlError("recovery control population malformed")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or tuple(sorted(entry)) != tuple(
                sorted(ENTRY_FIELDS)):
            raise RecoveryControlError("recovery control entry schema malformed")
        if entry["fault_class"] != FAULT_CLASS:
            raise RecoveryControlError("unsupported recovery control fault class")
        if type(entry["max_injections"]) is not int or \
                entry["max_injections"] != MAX_INJECTIONS:
            raise RecoveryControlError("recovery control max_injections != 1")
        if not all(isinstance(entry[key], str) and entry[key]
                   for key in ("scenario_id", "step_id", "capability")):
            raise RecoveryControlError("recovery control entry identity malformed")
        if entry["scenario_id"] in seen:
            raise RecoveryControlError("duplicate recovery control entry")
        seen.add(entry["scenario_id"])
    return {"status": "PASS", "entry_count": len(entries)}


def validate_recovery_control(document: Any,
                              cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Full validation against candidate-visible scenarios (never gold)."""
    validate_control_shape(document)
    if document["scenario_bundle_root"] != scenario_bundle_root(cases):
        raise RecoveryControlError(
            "recovery control is not bound to the finalized scenario bundle")
    index = _step_index(cases)
    for entry in document["entries"]:
        scenario = index.get(entry["scenario_id"])
        if scenario is None:
            raise RecoveryControlError("recovery control names an unknown scenario")
        _target_supported(scenario, entry["step_id"], entry["capability"])
    return {"status": "PASS", "entry_count": document["entry_count"],
            "control_sha256": control_sha256(document)}


def derive_recoverable_labels(document: dict[str, Any]) -> frozenset[str]:
    """§14 step 3: the ONE-WAY derivation control -> designated_recoverable."""
    validate_control_shape(document)
    return frozenset(entry["scenario_id"] for entry in document["entries"])


def check_designation_consistency(document: dict[str, Any],
                                  gold: list[dict[str, Any]]) -> dict[str, Any]:
    """§24: control scenario set == gold designated_recoverable set."""
    labels = derive_recoverable_labels(document)
    designated = [item.get("scenario_id") for item in gold
                  if item.get("designated_recoverable") is True]
    if len(designated) != len(set(designated)):
        raise RecoveryControlError("duplicate designated-recoverable gold row")
    missing = sorted(set(designated) - labels)
    extra = sorted(labels - set(designated))
    if missing or extra:
        raise RecoveryControlError(
            "recovery control / recoverable-gold set mismatch "
            f"(missing={len(missing)}, extra={len(extra)})")
    return {"status": "PASS", "recoverable_population": len(labels)}


def candidate_control_exposure(projected: list[dict[str, Any]]) -> int:
    """§15: count candidate-visible rows carrying any control field."""
    exposed = 0
    for row in projected:
        encoded = json.dumps(row, sort_keys=True)
        if any(f'"{name}"' in encoded for name in CANDIDATE_HIDDEN_FIELDS):
            exposed += 1
    return exposed


def entries_by_scenario(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_control_shape(document)
    return {entry["scenario_id"]: dict(entry) for entry in document["entries"]}


# ---------------------------------------------------------------------------
# adapter identity (§7/§8/§37)
# ---------------------------------------------------------------------------


def adapter_builder_identity(builder: Any) -> str:
    return f"{builder.__module__}:{builder.__qualname__}"


def production_implementation_sha256(root: Path) -> dict[str, str]:
    root = Path(root).resolve()
    result = {}
    for relative in ("t30_protocol/production.py",
                     "t26_protocol/production.py",
                     "t30_protocol/recovery_control.py"):
        data = (root / relative).read_bytes().replace(b"\r\n", b"\n")
        result[relative] = hashlib.sha256(data).hexdigest()
    return result


def adapter_identity_report(root: Path) -> dict[str, Any]:
    """§37: actual build_adapters implementation == attested implementation."""
    from . import official_environment
    actual = adapter_builder_identity(official_environment.build_adapters)
    source = inspect.getsource(official_environment)
    t26_import_present = "from t26_protocol.production import build_adapters" in source
    core = {
        "schema_version": "t30-adapter-identity-v1",
        "artifact": "T30_PRODUCTION_ADAPTER_IDENTITY",
        "classification": "PUBLIC_SAFE",
        "attested_adapter_builder": ATTESTED_ADAPTER_BUILDER,
        "actual_adapter_builder": actual,
        "t26_build_adapters_import_present": t26_import_present,
        "identity_exact": actual == ATTESTED_ADAPTER_BUILDER
                          and not t26_import_present,
        "historical_defect": {
            "code": "T30_REAL_ADAPTER_IMPLEMENTATION_IDENTITY_MISMATCH",
            "old_imported_implementation": "t26_protocol.production:build_adapters",
            "old_attested_implementation": ATTESTED_ADAPTER_BUILDER,
            "corrected_implementation": ATTESTED_ADAPTER_BUILDER,
        },
        "production_implementation_sha256":
            production_implementation_sha256(root),
        "recovery_control_wrapper": WRAPPER_ID,
    }
    core["status"] = "PASS" if core["identity_exact"] else "FAIL"
    return {**core, "adapter_identity_root": sha256_json(core)}


# ---------------------------------------------------------------------------
# the production-adapter wrapper (§18/§19/§20)
# ---------------------------------------------------------------------------


@dataclass
class RecoveryControlAudit:
    scenario_id: str
    entry: dict[str, Any] | None
    injections: int = 0
    delegations: int = 0
    matched_invocations: int = 0
    foreign_scenario_refusals: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"scenario_scheduled": self.entry is not None,
                "injections": self.injections,
                "matched_invocations": self.matched_invocations,
                "delegations": self.delegations,
                "foreign_scenario_refusals": self.foreign_scenario_refusals}


def wrap_production_adapters(adapters: Mapping[str, Adapter], *,
                             scenario_id: str,
                             entry: dict[str, Any] | None
                             ) -> tuple[dict[str, Adapter], RecoveryControlAudit]:
    """Wrap one scenario's production adapters with its (optional) entry.

    Unscheduled scenarios receive the production adapters UNCHANGED (object
    identity preserved).  A scheduled scenario receives the same registry
    with only the target capability wrapped: first matching invocation
    raises one RecoverableError; every later invocation delegates unchanged.
    """
    audit = RecoveryControlAudit(scenario_id=scenario_id, entry=entry)
    if entry is None:
        return dict(adapters), audit
    if entry.get("scenario_id") != scenario_id:
        raise RecoveryControlError("recovery control entry bound to another scenario")
    if entry.get("fault_class") != FAULT_CLASS or \
            entry.get("max_injections") != MAX_INJECTIONS:
        raise RecoveryControlError("recovery control entry unsupported")
    capability = entry["capability"]
    base = adapters.get(capability)
    if base is None:
        raise RecoveryControlError("recovery control target adapter absent")
    if not base.internal_only or base.may_perform_external_action:
        raise RecoveryControlError("recovery control target adapter authority")

    def execute(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if context.get("scenario_id") != scenario_id:
            audit.foreign_scenario_refusals += 1
            raise ExecutionError("recovery control scenario isolation violated")
        if context.get("step_id") == entry["step_id"]:
            audit.matched_invocations += 1
            if audit.injections < MAX_INJECTIONS:
                audit.injections += 1
                audit.events.append({"step_id": entry["step_id"],
                                     "invocation": audit.matched_invocations,
                                     "action": "INJECT"})
                raise RecoverableError(FAULT_MESSAGE)
        audit.delegations += 1
        return base.execute(payload, context)

    wrapped = dict(adapters)
    wrapped[capability] = Adapter(capability, execute, internal_only=True,
                                  may_perform_external_action=False)
    return wrapped, audit


def aggregate_audits(audits: list[RecoveryControlAudit],
                     document: dict[str, Any]) -> dict[str, Any]:
    scheduled = {entry["scenario_id"] for entry in document["entries"]}
    injected = {audit.scenario_id for audit in audits if audit.injections}
    return {
        "scheduled_entries": len(scheduled),
        "injected_first_failures": sum(audit.injections for audit in audits),
        "scenarios_injected": len(injected),
        "unscheduled_injections": len(injected - scheduled),
        "max_injections_observed": max((audit.injections for audit in audits),
                                       default=0),
        "foreign_scenario_refusals": sum(audit.foreign_scenario_refusals
                                         for audit in audits),
        "scheduled_but_not_injected": len(scheduled - injected),
    }


__all__ = [
    "ARTIFACT", "CANDIDATE_HIDDEN_FIELDS", "CONTROL_PATH", "FAULT_CLASS",
    "FAULT_MESSAGE", "FORBIDDEN_CONTROL_FIELDS", "POLICY_ROOT",
    "QUALIFIED_TARGET_CAPABILITIES", "RecoveryControlError",
    "STORE_CLASSIFICATION", "adapter_identity_report", "aggregate_audits",
    "build_recovery_control", "candidate_control_exposure",
    "check_designation_consistency", "control_sha256",
    "derive_recoverable_labels", "entries_by_scenario",
    "recovery_control_policy", "scenario_bundle_root",
    "validate_control_shape", "validate_recovery_control",
    "wrap_production_adapters",
]
