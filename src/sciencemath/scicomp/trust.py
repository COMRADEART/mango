"""scicomp trust — provenance boundaries and firewall integration
(T11.17, T11.18).

Trust boundaries (T11.17). Every value Mango may state carries exactly
one provenance category:

* RETRIEVED_FACT — supported by T5R evidence; REQUIRES a citation.
* USER_GIVEN_VALUE — supplied in the problem; no citation.
* DETERMINISTIC_COMPUTATION — produced by the T11 compute engine; no
  citation, but the envelope's diagnostics travel with it.
* MODEL_INFERENCE — derived in prose; no citation, no certainty claim.

A computed result does not need a citation. A retrieved physical
constant does. The two must never be conflated (this is the same
fact/computation distinction the extraction gates enforce).

Correction-firewall integration (T11.18) — WITHOUT touching the frozen
firewall module (its hash is pinned by the T10 audit). The firewall
trusts feedback from AUTHORITATIVE_SOURCES (deterministic tools) and
defers on UNVERIFIED_MODEL_FEEDBACK. This module maps scicomp outcomes
onto those EXISTING semantics, fail-closed:

* envelope PASS with agreeing (or absent) cross-check
      -> authoritative deterministic-tool feedback (VERIFIED trust when
         used as contradiction evidence);
* envelope PASS but cross_check DISAGREE, or status NUMERICAL_WARNING /
  UNKNOWN / FAIL / RESOURCE_LIMIT / INVALID_INPUT
      -> UNVERIFIED feedback: the firewall must DEFER, never force the
         model to adopt the number as certainty.

The mapping is expressed by returning the exact (source, validation)
pair the frozen ``determine_feedback_trust`` already understands, and
tests verify the trust level each case produces (T11.43).
"""
from __future__ import annotations

from enum import Enum

from sciencemath.executive.correction import (
    FeedbackTrust, determine_feedback_trust)
from sciencemath.scicomp.schemas import (STATUS_PASS, STATUS_UNKNOWN,
                                         STATUS_NUMERICAL_WARNING,
                                         UNTRUSTED_STATUSES)


class Provenance(str, Enum):
    """T11.17 provenance categories."""

    RETRIEVED_FACT = "RETRIEVED_FACT"
    USER_GIVEN_VALUE = "USER_GIVEN_VALUE"
    DETERMINISTIC_COMPUTATION = "DETERMINISTIC_COMPUTATION"
    MODEL_INFERENCE = "MODEL_INFERENCE"


REQUIRES_CITATION = {Provenance.RETRIEVED_FACT}


def requires_citation(provenance: Provenance) -> bool:
    """A retrieved fact needs a citation; a computed result does not."""
    return provenance in REQUIRES_CITATION


# Frozen-firewall source labels (existing semantics, no firewall edit):
# "MATH_TOOL" is the deterministic-tool category; "UNVERIFIED_MODEL_
# FEEDBACK" is the defer category.
_AUTHORITATIVE_LABEL = "MATH_TOOL"
_UNVERIFIED_LABEL = "UNVERIFIED_MODEL_FEEDBACK"


def firewall_feedback(envelope: dict) -> tuple[str, str] | None:
    """Map a scicomp envelope to firewall (source, validation) semantics.

    Returns None when the envelope carries no trustworthy number at all
    (no feedback exists to give). Fail-closed (T11.18):

    * PASS + cross-check not disagreeing -> deterministic-tool feedback;
    * anything else (NUMERICAL_WARNING, UNKNOWN, DISAGREE, ...) ->
      UNVERIFIED feedback the firewall will defer on.
    """
    if not isinstance(envelope, dict):
        return None
    status = envelope.get("status")
    if status != STATUS_PASS:
        # NUMERICAL_WARNING / UNKNOWN / FAIL / RESOURCE_LIMIT /
        # INVALID_INPUT: not trustworthy as certainty.
        return (_UNVERIFIED_LABEL, "FAIL")
    cross = envelope.get("cross_check") or {}
    if cross.get("verdict") == "DISAGREE":
        return (_UNVERIFIED_LABEL, "FAIL")
    return (_AUTHORITATIVE_LABEL, "FAIL")


def firewall_trust(envelope: dict) -> FeedbackTrust:
    """The trust level the frozen firewall assigns to this envelope."""
    pair = firewall_feedback(envelope)
    if pair is None:
        return FeedbackTrust.UNVERIFIED
    return determine_feedback_trust(pair[0], pair[1])


def adoption_allowed(envelope: dict) -> bool:
    """Whether Mango may present the result as a verified number.

    True only for PASS envelopes whose cross-check (when present) agrees;
    NUMERICAL_WARNING and UNKNOWN results may be reported as tentative
    model statements but never as verified certainty (T11.18).
    """
    return firewall_trust(envelope) == FeedbackTrust.VERIFIED