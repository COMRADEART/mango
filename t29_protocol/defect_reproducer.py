"""Public §11 reproducer of the frozen T28 preflight key-shape defect.

The frozen T28 marker-contract producer
(``t28_protocol.construction:official_marker_contract_report``) returns the
official-marker relation state under the nested ``disposable_layout``
container with drifted key names, while the frozen T28-era preflight consumer
(``t27_protocol.t28_private_oracle:validate_t27_store_authentication_evidence``)
pins an exact field set that only exists at TOP-LEVEL keys.  The producer
document is valid (it mirrors the official layout) but its key shape can
never satisfy the frozen consumer: ``T28_FROZEN_PREFLIGHT_KEY_SHAPE_DEFECT``.

This module is public protocol code: it opens no private predecessor store
(the producer builds its own disposable stand-in), parses no private rows,
and contains no real T27/T28/T29 material.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json #: @\label{line:sha}

REQUIRED_VERDICT = "T28_FROZEN_PREFLIGHT_KEY_SHAPE_DEFECT_REPRODUCED"
PRODUCER_QUALIFIED_ID = (
    "t28_protocol.construction:official_marker_contract_report")
CONSUMER_QUALIFIED_ID = (
    "t27_protocol.t28_private_oracle:"
    "validate_t27_store_authentication_evidence")
#: The frozen producer's nested state container (returns relevant state
#: under this key, never at top level).
PRODUCER_STATE_CONTAINER = "disposable_layout"
#: Frozen T28 public adjudication commit (§10 binding).
T28_ADJUDICATION_COMMIT = "9c3f320edea143e46afe9b6e5bcb2a3da33a989a"

#: Frozen-consumer field names with their producer-side nested counterparts:
#: even where the topic matches, the key name (and in two cases the value
#: type) drifts, so the nested state cannot be lifted to the consumer's
#: top-level shape by construction.
_NESTED_COUNTERPARTS = {
    "t27_construction_marker_path": "marker_path_match",
    "t27_construction_marker_committed": "marker_committed",
    "t27_official_evaluation_state": "evaluation_state_sealed_unevaluated",
    "t27_official_evaluation_attempt": "evaluation_attempt_zero",
    "t27_evaluation_event_count": "event_count_zero",
    "t28_fingerprint_derivation_invoked": "fingerprint_derivation_invoked",
}


def _repository_file_sha(root: Path, relative: str) -> str:
    data = (root / relative).read_bytes()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def run_t28_preflight_defect_reproducer(root: Path) -> dict[str, Any]:
    """Drive the frozen producer and frozen consumer; prove the shape defect.

    Deterministic and public: the producer runs on its own disposable
    stand-in store, the frozen consumer refuses the produced document on its
    first key-shape check, and the record binds the exact refusal text plus
    the producer/consumer implementation identities.  No real T27/T28
    private artifact is opened; the one-shot states stay untouched.
    """
    root = Path(root).resolve()
    from t27_protocol.t28_private_oracle import (
        T28_T27_STORE_AUTHENTICATION_FIELDS,
        validate_t27_store_authentication_evidence)
    from t28_protocol.construction import official_marker_contract_report

    producer = official_marker_contract_report(root)

    # The producer succeeded AND its disposable layout mirrors the official
    # layout: the produced state is valid, only its key shape is wrong.
    if producer["status"] != "PASS":
        raise RuntimeError("§11 reproducer: frozen producer did not pass")
    if producer["disposable_layout_mirrors_official"] is not True:
        raise RuntimeError(
            "§11 reproducer: disposable layout does not mirror official")
    nested = producer[PRODUCER_STATE_CONTAINER]
    absent_top_level = sorted(
        set(T28_T27_STORE_AUTHENTICATION_FIELDS) - set(producer))
    if not absent_top_level:
        raise RuntimeError(
            "§11 reproducer: expected absent top-level fields")
    nested_only = sorted(
        key for key in T28_T27_STORE_AUTHENTICATION_FIELDS[4:]
        if key not in set(producer) and key in set(nested) | {
            name for name, counterpart in _NESTED_COUNTERPARTS.items()
            if nested.get(counterpart) is not None})
    try:
        validate_t27_store_authentication_evidence(producer, real=True)
    except ValueError as exc:
        consumer_refusal = f"ValueError: {exc}"
    else:
        raise RuntimeError(
            "§11 reproducer refuses to record a defect the frozen consumer "
            "did not demonstrate")

    # The same facts, lifted to the consumer's key names, still cannot be
    # satisfied: the frozen exact top-level field set pins the value shapes
    # (integers, exact strings), while the producer returns derived boolean
    # checks or omits the fact entirely.
    lifted = {
        "t28_fingerprint_derivation_invoked": nested.get(
            "fingerprint_derivation_invoked"),
        "t27_official_evaluation_state": (
            "UNSPENT_BUT_PERMANENTLY_INELIGIBLE"
            if nested.get("evaluation_state_sealed_unevaluated") else None),
        "t27_official_evaluation_attempt": (
            0 if nested.get("evaluation_attempt_zero") else None),
        "t27_evaluation_event_count": (
            0 if nested.get("event_count_zero") else "non-zero"),
    }
    unrecoverable = {
        "authentication_sha256": (
            "consumer requires a self-hash over the exact top-level field "
            "set; the producer never computes one"),
        "t27_construction_marker_sha256": (
            "producer returns no marker digest, only match booleans"),
        "t27_construction_marker_spent": (
            "producer omits the spent fact; its layout has no counterpart"),
        "t27_private_holdout_root": (
            "producer returns no sealed holdout commitment, only layout "
            "relation booleans"),
        "t27_store_identity": (
            "producer returns no sealed store identity binding"),
    }
    return {
        "schema_version": "t29-t28-public-root-cause-reproduction-v1",
        "artifact": "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION",
        "classification": "PUBLIC_SAFE", "experiment": "t29",
        "status": REQUIRED_VERDICT,
        "required_verdict": REQUIRED_VERDICT,
        "reproduced": True,
        "defect_class": "FROZEN_PREFLIGHT_KEY_SHAPE_DEFECT",
        "claim_scope": "PUBLIC_T28_FROZEN_PREFLIGHT_KEY_SHAPE_ONLY",
        "producer_qualified_id": PRODUCER_QUALIFIED_ID,
        "producer_implementation_sha256": _repository_file_sha(
            root, "t28_protocol/construction.py"),
        "producer_state_container": PRODUCER_STATE_CONTAINER,
        "producer_state_container_deterministic": True,
        "frozen_consumer_qualified_id": CONSUMER_QUALIFIED_ID,
        "frozen_consumer_implementation_sha256": _repository_file_sha(
            root, "t27_protocol/t28_private_oracle.py"),
        "frozen_consumer_expected_key_shape": "top-level keys",
        "frozen_consumer_required_top_level_field_count":
            len(T28_T27_STORE_AUTHENTICATION_FIELDS),
        "producer_top_level_keys": sorted(producer),
        "required_top_level_fields_absent_from_producer": absent_top_level,
        "nested_name_drift_examples": _NESTED_COUNTERPARTS,
        "nested_value_shape_drift_examples": lifted,
        "facts_with_no_producer_counterpart": unrecoverable,
        "consumer_refusal_observed": consumer_refusal,
        "observer_refused_at_first_key_shape_check":
            consumer_refusal == "ValueError: T27 store authentication "
            "evidence field drift",
        "production_impact":
            "the frozen T28 official preflight demanded the producer's "
            "marker-contract state under exact top-level keys while the "
            "frozen producer returns that state under the nested "
            "disposable_layout container with drifted key names; the T28 "
            "official evaluation was therefore refused pre-ledger at the "
            "frozen T27-compatibility preflight",
        "predecessor_commit": T28_ADJUDICATION_COMMIT,
        "predecessor_artifacts": (
            "evaluations/t28/"
            "T28_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json",
            "evaluations/t28/T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json",
        ),
        "reproducer_qualified_id":
            "t29_protocol.defect_reproducer:"
            "run_t28_preflight_defect_reproducer",
        "reproduction": {
            "producer_document_root": sha256_json({
                key: value for key, value in producer.items()
                if key != "disposable_layout"}),
            "disposable_layout_key_count": len(nested),
        },
        "t27_private_rows_opened": 0, "t27_candidate_reruns": 0,
        "t28_private_material_parsed": False,
        "real_one_shot_states_touched": False,
        "row_specific_cause_claimed": False,
    }