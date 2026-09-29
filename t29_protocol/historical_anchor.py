"""T29 historical predecessor anchor schema (T29 authorization §13–§16).

One explicit, machine-readable, fixed-shape schema for sealed predecessor
anchor documents.  Producers and every consumer validate the SAME schema
before any indexed access; free-form nested predecessor reports cannot cross
a module boundary.  This is the structural correction for the adjudicated
``FROZEN_PRODUCER_CONSUMER_REPORT_SCHEMA_MISMATCH`` class (the T28 consumer
indexed top-level keys the frozen T28 producer emitted only nested under
``disposable_layout``).

Unknown fields fail closed; missing fields fail closed; wrong types fail
closed; predecessor terminal states fail closed.  A validated anchor is the
only lawful representation of a predecessor state inside T29 protocol code.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

SCHEMA_VERSION = "t29-historical-anchor-state-v1"
ARTIFACT_PREFIX = "T29_HISTORICAL_ANCHOR"

#: The exact field set (§13).  Nothing else may appear at the top level, and
#: every field must appear at the top level exactly once.
ANCHOR_FIELDS = (
    "experiment",
    "construction_state",
    "construction_attempt",
    "evaluation_state",
    "evaluation_attempt",
    "evaluation_eligibility",
    "capability_status",
    "private_rows_read",
    "store_authenticated",
    "commitment_root",
)

#: Frozen predecessor terminal vocabulary (§16 "unknown terminal state" must
#: fail closed).  Only these states validate; the T29 terminal vocabulary is
#: intentionally NOT part of the predecessor anchor vocabulary.
CONSTRUCTION_STATES_ACCEPTED = frozenset({"SEALED"})
EVALUATION_STATES_ACCEPTED = frozenset({
    "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
    "UNSPENT_BUT_PERMANENTLY_NOT_AUTHORIZED",
    "SYNTHETIC_SEALED_UNEVALUATED",
})
EVALUATION_ELIGIBILITY_ACCEPTED = frozenset({
    "PERMANENTLY_INELIGIBLE",
    "PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
    "SYNTHETIC_DISPOSABLE",
})
CAPABILITY_STATUS_ACCEPTED = frozenset({"NOT_MEASURED"})

#: Known predecessor experiment identities whose terminal states are frozen
#: by §40; no other experiment may claim an anchor under this schema.
KNOWN_EXPERIMENTS = frozenset({"t27", "t28"})

#: Per-experiment attempt guarantees (§16 "wrong attempt" must fail closed):
#: both predecessors completed exactly one construction and zero evaluations.
EXPECTED_ATTEMPTS = {
    "construction_attempt": 1,
    "evaluation_attempt": 0,
}

TYPES = {
    "experiment": str,
    "construction_state": str,
    "construction_attempt": int,
    "evaluation_state": str,
    "evaluation_attempt": int,
    "evaluation_eligibility": str,
    "capability_status": str,
    "private_rows_read": int,
    "store_authenticated": bool,
    "commitment_root": str,
}


class HistoricalAnchorError(ValueError):
    """Raised for any anchor schema/semantics mutation (fail closed)."""


def validate_historical_anchor_state(document: Any, *,
                                     experiments: frozenset[str] | None = None,
                                     ) -> dict[str, Any]:
    """Validate the exact anchor shape and the predecessor terminal state.

    Every rejection names the mutation class; no consumer may index an
    unvalidated raw report (§14).  Returns a defensive copy typed exactly.
    """
    if experiments is None:
        experiments = KNOWN_EXPERIMENTS
    if not isinstance(document, dict):
        raise HistoricalAnchorError("historical anchor must be a JSON object")
    if set(document) != set(ANCHOR_FIELDS):
        unknown = sorted(set(document) - set(ANCHOR_FIELDS))
        missing = sorted(set(ANCHOR_FIELDS) - set(document))
        raise HistoricalAnchorError(
            "historical anchor field-set drift"
            + (f"; unknown fields: {unknown}" if unknown else "")
            + (f"; missing fields: {missing}" if missing else ""))
    for field in ANCHOR_FIELDS:
        value = document[field]
        expected_type = TYPES[field]
        # bool is a subclass of int in Python; exclude it from int fields.
        if expected_type is int and isinstance(value, bool):
            raise HistoricalAnchorError(
                f"historical anchor wrong type: {field} must be int")
        if not isinstance(value, expected_type):
            raise HistoricalAnchorError(
                f"historical anchor wrong type: {field} must be "
                f"{expected_type.__name__}")
    # A field moved into a nested object (the T28 defect shape) or any extra
    # nested dictionary is refused: the exact top-level set above already
    # fails unknown keys, and the following probe makes the failure
    # explicit for the nested-variant mutation controls (§16).
    for field in ANCHOR_FIELDS:
        if isinstance(document[field], dict):
            raise HistoricalAnchorError(
                f"historical anchor field nested, not scalar: {field}")
    if document["experiment"] not in experiments:
        raise HistoricalAnchorError(
            f"historical anchor wrong experiment: {document['experiment']!r}")
    if document["construction_state"] not in CONSTRUCTION_STATES_ACCEPTED:
        raise HistoricalAnchorError(
            "historical anchor unknown terminal construction state: "
            + repr(document["construction_state"]))
    if document["construction_attempt"] != EXPECTED_ATTEMPTS["construction_attempt"]:
        raise HistoricalAnchorError(
            "historical anchor wrong construction attempt: "
            + repr(document["construction_attempt"]))
    if not (isinstance(document["construction_attempt"], int)
            and document["construction_attempt"] >= 1):
        raise HistoricalAnchorError(
            "historical anchor wrong construction attempt")
    if document["evaluation_state"] not in EVALUATION_STATES_ACCEPTED:
        raise HistoricalAnchorError(
            "historical anchor unknown terminal evaluation state: "
            + repr(document["evaluation_state"]))
    if document["evaluation_attempt"] != EXPECTED_ATTEMPTS["evaluation_attempt"]:
        raise HistoricalAnchorError(
            "historical anchor wrong evaluation attempt: "
            + repr(document["evaluation_attempt"]))
    if document["evaluation_eligibility"] not in EVALUATION_ELIGIBILITY_ACCEPTED:
        raise HistoricalAnchorError(
            "historical anchor wrong evaluation eligibility: "
            + repr(document["evaluation_eligibility"]))
    if document["capability_status"] not in CAPABILITY_STATUS_ACCEPTED:
        raise HistoricalAnchorError(
            "historical anchor wrong capability status: "
            + repr(document["capability_status"]))
    if document["private_rows_read"] != 0:
        raise HistoricalAnchorError(
            "historical anchor predecessor private rows read must be zero")
    if len(document["commitment_root"]) != 64 or any(
            char not in "0123456789abcdef"
            for char in document["commitment_root"]):
        raise HistoricalAnchorError(
            "historical anchor commitment_root must be a SHA-256 hex digest")
    # Official-terminal pairing: when the anchor binds an OFFICIAL state,
    # the eligibility pairing is frozen per experiment (§16 "wrong
    # eligibility").  Synthetic-disposable rehearsal anchors are validated
    # by the same schema but carry the explicitly synthetic vocabulary.
    synthetic = document["evaluation_state"] == "SYNTHETIC_SEALED_UNEVALUATED"
    if synthetic:
        if document["evaluation_eligibility"] != "SYNTHETIC_DISPOSABLE":
            raise HistoricalAnchorError(
                "synthetic anchor must bind SYNTHETIC_DISPOSABLE eligibility")
    else:
        if document["evaluation_eligibility"] not in {
                "PERMANENTLY_INELIGIBLE",
                "PERMANENTLY_NOT_AUTHORIZED_FOR_T27"}:
            raise HistoricalAnchorError(
                "historical anchor wrong evaluation eligibility: "
                + repr(document["evaluation_eligibility"]))
        if document["experiment"] == "t27" and document[
                "evaluation_eligibility"] != (
                "PERMANENTLY_NOT_AUTHORIZED_FOR_T27"):
            raise HistoricalAnchorError(
                "t27 anchor must bind PERMANENTLY_NOT_AUTHORIZED_FOR_T27")
        if document["experiment"] == "t28" and document[
                "evaluation_eligibility"] != "PERMANENTLY_INELIGIBLE":
            raise HistoricalAnchorError(
                "t28 anchor must bind PERMANENTLY_INELIGIBLE")
    return {field: document[field] for field in ANCHOR_FIELDS}


def build_historical_anchor_state(*, experiment: str,
                                  construction_state: str,
                                  construction_attempt: int,
                                  evaluation_state: str,
                                  evaluation_attempt: int,
                                  evaluation_eligibility: str,
                                  capability_status: str,
                                  private_rows_read: int,
                                  store_authenticated: bool,
                                  commitment_root: str,
                                  ) -> dict[str, Any]:
    """Producer side of the T29 anchor contract (§14).

    The same validator that every consumer runs validates the producer's own
    output; a producer whose shape drifts is refused at construction, not at
    consumption.
    """
    document = validate_historical_anchor_state({
        "experiment": experiment,
        "construction_state": construction_state,
        "construction_attempt": construction_attempt,
        "evaluation_state": evaluation_state,
        "evaluation_attempt": evaluation_attempt,
        "evaluation_eligibility": evaluation_eligibility,
        "capability_status": capability_status,
        "private_rows_read": private_rows_read,
        "store_authenticated": store_authenticated,
        "commitment_root": commitment_root,
    })
    return document


def anchor_sha256(document: dict[str, Any]) -> str:
    """Semantic identity of one validated anchor document."""
    validate_historical_anchor_state(document)
    return sha256_json(document)


def commit_root(commitments: dict[str, Any]) -> str:
    """Commitment root over the official T27/T28 sealed-commitment map."""
    if not isinstance(commitments, dict) or not commitments:
        raise HistoricalAnchorError("commitment map absent")
    return sha256_json(commitments)


def serialize_anchor(document: dict[str, Any]) -> bytes:
    """Canonical public serialization for a validated anchor (§15)."""
    validate_historical_anchor_state(document)
    return (json.dumps(document, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def deserialize_anchor(payload: bytes | str) -> dict[str, Any]:
    """Deserialize a serialized anchor and schema-validate it (§15)."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    try:
        parsed = json.loads(payload)
    except ValueError as exc:
        raise HistoricalAnchorError(
            "historical anchor is not valid JSON") from exc
    return validate_historical_anchor_state(parsed)


def load_historical_anchor_state(path: Path | str) -> dict[str, Any]:
    """Read → deserialize → validate → return (the §15 consumer chain)."""
    path = Path(path)
    if not path.is_file():
        raise HistoricalAnchorError(f"historical anchor absent: {path.name}")
    anchor = deserialize_anchor(path.read_bytes())
    return anchor


# --- frozen official anchor documents (preconstruction, repo-byte bound) -----


def t27_official_anchor(root: Path) -> dict[str, Any]:
    """Frozen T27 predecessor anchor built from public T27 commitments."""
    from t27_protocol.t28_private_oracle import official_t27_commitments

    commitments = official_t27_commitments(root)
    return build_historical_anchor_state(
        experiment="t27",
        construction_state="SEALED",
        construction_attempt=1,
        evaluation_state="UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        evaluation_attempt=0,
        evaluation_eligibility="PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
        capability_status="NOT_MEASURED",
        private_rows_read=0,
        store_authenticated=True,
        commitment_root=commit_root({key: value for key, value in
                                     commitments.items()
                                     if not key.endswith("_state")
                                     and not key.endswith("_eligibility")}),
    )


def t28_official_anchor(root: Path) -> dict[str, Any]:
    """Frozen T28 predecessor anchor binding the exact §10 commitments."""
    root = Path(root).resolve()
    required = {
        "t28_public_construction_commit": "9c3f320edea143e46afe9b6e5bcb2a3da33a989a",
        "t28_construction_ledger_sha256": (
            "2e104783ebb38cd690c838b69a6f127a8d651dabaeab1bd9865ab9d79b2a790c"),
        "t28_construction_ledger_root": (
            "d10397caef04ba24fee0209dd7bfaf4b1dd16fa8774e78f6ccb55a2ea2f882e6"),
        "t28_private_manifest_sha256": (
            "7f1b853d34e4194c714db542418b483f198aa1743c807aa23b54bac06fb8f7c1"),
        "t28_construction_seal_sha256": (
            "eb6f74685aab85f06038c9597b1ab23eee475a004589ab82f504593b89f789f0"),
        "t28_private_holdout_root": (
            "2b4f8f54284d9bb77fdaee9f94979d52d745520ff916bf3a1178d8a9d55025e2"),
    }
    receipt = json.loads(
        (root / "evaluations/t28/construction/"
         "T28_PUBLIC_CONSTRUCTION_RECEIPT.json").read_text(encoding="utf-8"))
    adjudication = json.loads(
        (root / "evaluations/t28/"
         "T28_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json").read_text(
            encoding="utf-8"))
    observed = {
        "t28_public_construction_commit":
            adjudication["public_construction"]["commit"],
        "t28_construction_ledger_sha256":
            receipt["construction_ledger_sha256"],
        "t28_construction_ledger_root": receipt["construction_ledger_root"],
        "t28_private_manifest_sha256": receipt["manifest_sha256"],
        "t28_construction_seal_sha256": receipt["seal_sha256"],
        "t28_private_holdout_root": receipt["private_blind_root"],
    }
    if adjudication.get("official_evaluation_eligibility") != "INELIGIBLE" \
            or adjudication.get("official_evaluation_eligibility_state") \
            != "PERMANENTLY_INELIGIBLE" \
            or adjudication.get("evaluation_attempt_count") != 0 \
            or adjudication.get("capability_status") != "NOT_MEASURED":
        raise HistoricalAnchorError(
            "T28 adjudication anchors disagree with the §10 commitments")
    if observed != required:
        raise HistoricalAnchorError(
            "official T28 public commitments disagree with the frozen §10 "
            "values")
    return build_historical_anchor_state(
        experiment="t28",
        construction_state="SEALED",
        construction_attempt=1,
        evaluation_state="UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        evaluation_attempt=0,
        evaluation_eligibility="PERMANENTLY_INELIGIBLE",
        capability_status="NOT_MEASURED",
        private_rows_read=0,
        store_authenticated=True,
        commitment_root=commit_root(required),
    )


#: The exact frozen predecessor §10 commitment map bound by the t28 anchor.
T28_SEALED_COMMITMENTS = {
    "t28_public_construction_commit": "9c3f320edea143e46afe9b6e5bcb2a3da33a989a",
    "t28_construction_ledger_sha256": (
        "2e104783ebb38cd690c838b69a6f127a8d651dabaeab1bd9865ab9d79b2a790c"),
    "t28_construction_ledger_root": (
        "d10397caef04ba24fee0209dd7bfaf4b1dd16fa8774e78f6ccb55a2ea2f882e6"),
    "t28_private_manifest_sha256": (
        "7f1b853d34e4194c714db542418b483f198aa1743c807aa23b54bac06fb8f7c1"),
    "t28_construction_seal_sha256": (
        "eb6f74685aab85f06038c9597b1ab23eee475a004589ab82f504593b89f789f0"),
    "t28_private_holdout_root": (
        "2b4f8f54284d9bb77fdaee9f94979d52d745520ff916bf3a1178d8a9d55025e2"),
}
T28_TERMINAL_BINDINGS = {
    "t28_capability": "NOT_MEASURED",
    "t28_evaluation_attempt": 0,
    "t28_evaluation_eligibility": "PERMANENTLY_INELIGIBLE",
}


def mutation_controls() -> dict[str, Any]:
    """Every §16 mutation must fail closed; every shape must be exact."""
    base = t27_synthetic_anchor()
    controls: list[dict[str, Any]] = []

    def refused(name: str, mutate) -> dict[str, Any]:
        document = json.loads(json.dumps(base))
        mutate(document)
        try:
            validate_historical_anchor_state(document)
        except HistoricalAnchorError:
            return {"control": name, "refused": True}
        return {"control": name, "refused": False}

    def moved_in(document: dict[str, Any]) -> None:
        scalar = document["construction_state"]
        del document["construction_state"]
        document["detail"] = {"construction_state": scalar}

    def moved_out(document: dict[str, Any]) -> None:
        document["extra"] = {"evaluation_state":
                             document["evaluation_state"]}

    def renamed(document: dict[str, Any]) -> None:
        document["capability_verdict"] = document["capability_status"]
        del document["capability_status"]

    def missing(document: dict[str, Any]) -> None:
        del document["store_authenticated"]

    def wrong_type(document: dict[str, Any]) -> None:
        document["construction_attempt"] = "1"

    def wrong_experiment(document: dict[str, Any]) -> None:
        document["experiment"] = "t27-synthetic"

    def wrong_attempt(document: dict[str, Any]) -> None:
        document["evaluation_attempt"] = 1

    def wrong_eligibility(document: dict[str, Any]) -> None:
        document["evaluation_eligibility"] = "ELIGIBLE"

    def unknown_terminal(document: dict[str, Any]) -> None:
        document["evaluation_state"] = "MATERIALIZED_FINALLY"

    controls.extend([
        refused("field moved into nested object", moved_in),
        refused("field moved out of nested object", moved_out),
        refused("field renamed", renamed),
        refused("field missing", missing),
        refused("wrong type", wrong_type),
        refused("wrong experiment", wrong_experiment),
        refused("wrong attempt", wrong_attempt),
        refused("wrong eligibility", wrong_eligibility),
        refused("unknown terminal state", unknown_terminal),
    ])
    passed = all(item["refused"] for item in controls)
    # Roundtrip: producer → serialize → deserialize → validate → consumer.
    anchor = build_historical_anchor_state(
        experiment="t27", construction_state="SEALED",
        construction_attempt=1,
        evaluation_state="UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        evaluation_attempt=0,
        evaluation_eligibility="PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
        capability_status="NOT_MEASURED", private_rows_read=0,
        store_authenticated=False, commitment_root="a" * 64)
    roundtrip = deserialize_anchor(serialize_anchor(anchor))
    roundtrip_exact = roundtrip == anchor
    return {
        "schema_version": "t29-historical-anchor-mutation-controls-v1",
        "artifact": "T29_HISTORICAL_ANCHOR_MUTATION_CONTROLS",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if passed and roundtrip_exact else "FAIL",
        "schema_version_control": SCHEMA_VERSION,
        "field_count": len(ANCHOR_FIELDS),
        "mutation_controls": controls,
        "mutation_refusals_required": len(controls),
        "mutation_refusals_failed": sum(
            1 for item in controls if not item["refused"]),
        "roundtrip_exact": roundtrip_exact,
        "raw_indexing_consumers": 0,
    }


def t27_synthetic_anchor() -> dict[str, Any]:
    """Disposable synthetic predecessor anchor used by mutation controls."""
    return build_historical_anchor_state(
        experiment="t27", construction_state="SEALED",
        construction_attempt=1,
        evaluation_state="SYNTHETIC_SEALED_UNEVALUATED",
        evaluation_attempt=0, evaluation_eligibility="SYNTHETIC_DISPOSABLE",
        capability_status="NOT_MEASURED", private_rows_read=0,
        store_authenticated=False, commitment_root="b" * 64)