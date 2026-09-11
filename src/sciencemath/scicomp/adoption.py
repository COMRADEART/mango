"""scicomp adoption — verified-result binding contract (T12.11–T12.17).

The T11 adoption gate failed at 0.862 (< 0.90): of 94 PASS results the
reasoner misread 3 into a different number and ignored 3 entirely, and
stale pre-compute answers survived against verified ones. This module
defines the contract the reasoner now sees, and the deterministic
classifier the evaluation uses to grade every adoption decision.

Contract:

* Only a PASS envelope with a matching parameter hash and acceptable
  diagnostics is a VERIFIED_COMPUTE_RESULT (T12.12). NUMERICAL_WARNING,
  NONCONVERGENCE, ILL_CONDITIONED, RESOURCE_LIMIT, INVALID_INPUT are
  NOT_AUTHORITATIVE — the numeric payload must never be presented as
  certainty (T12.13; trust.py already refuses adoption).
* The observation given to the reasoner carries the structured envelope
  (status, result, verified flag, result_type, units,
  source_parameter_hash) so binding is type-strong, not prose-weak.
* Final answers are graded by :func:`classify_adoption` into the
  T12.14 taxonomy; reasonable rounding within the declared per-eval
  atol/rtol is NOT an adoption failure (T12.17), but wrong magnitudes
  are never hidden by tolerance.
"""
from __future__ import annotations

import math
import re

from sciencemath.scicomp.fidelity import numbers_in, semantic_hash
from sciencemath.scicomp.schemas import STATUS_PASS
from sciencemath.scicomp.trust import adoption_allowed

VERIFIED = "VERIFIED_COMPUTE_RESULT"
NOT_AUTHORITATIVE = "NOT_AUTHORITATIVE"

# T12.14 taxonomy
ADOPTED = "ADOPTED"
RESULT_IGNORED = "RESULT_IGNORED"                    # no number in answer
RESULT_MISREAD = "RESULT_MISREAD"                    # different number
STALE_PRECOMPUTE_ANSWER = "STALE_PRECOMPUTE_ANSWER"  # kept prior answer
EXPLANATION_CONTRADICTS_RESULT = "EXPLANATION_CONTRADICTS_RESULT"
UNIT_LOST = "UNIT_LOST"
WRONG_ROUNDING = "WRONG_ROUNDING"                    # out of per-eval tol
DIAGNOSTIC_REJECTION_VALID = "DIAGNOSTIC_REJECTION_VALID"
NO_ADOPTION_EXPECTED = "NO_ADOPTION_EXPECTED"        # not a PASS envelope
OTHER = "OTHER"

# diagnostics that forbid authoritative presentation (T12.13)
_BLOCKING_DIAGNOSTIC_KEYS = ("nonconvergence", "ill_conditioned",
                             "condition_number_exceeded")

# unit tokens we can recognize in a final answer (T12.16 unit binding)
_UNIT_TOKEN_RE = re.compile(
    r"\b(m/s2|m/s\^2|m/s|km/h|kPa|kJ|kW|°C|°K|km|cm|mm|ms|min|hour|hours|"
    r"kg|mg|mL|mol|Pa|Hz|L|m|s|h|g|K|C|J|N|V|A|W)\b\.?", re.I)


def verified_envelope(envelope: dict, source_parameter_hash: str,
                      result_type: str = "", units: str = "") -> dict:
    """The strongly typed result envelope the reasoner receives
    (T12.11). ``verified`` is the trust decision (fail-closed)."""
    env_hash = envelope.get("source_parameter_hash") \
        or envelope.get("request_hash") or source_parameter_hash
    hash_ok = (not source_parameter_hash) or (env_hash == source_parameter_hash)
    verified = bool(
        envelope.get("status") == STATUS_PASS
        and adoption_allowed(envelope) and hash_ok)
    diagnostics = envelope.get("diagnostics") or {}
    warnings = envelope.get("warnings") or []
    blocking = [k for k in _BLOCKING_DIAGNOSTIC_KEYS
                if diagnostics.get(k) not in (None, False)]
    if verified and blocking:
        verified = False
    return {
        "kind": "COMPUTE_RESULT_ENVELOPE",
        "status": envelope.get("status"),
        "result": envelope.get("result"),
        "diagnostics": diagnostics,
        "warnings": warnings,
        "verified": verified,
        "binding": VERIFIED if verified else NOT_AUTHORITATIVE,
        "result_type": result_type or _infer_result_type(
            envelope.get("result")),
        "units": units or (envelope.get("units") or ""),
        "source_parameter_hash": env_hash,
        "hash_match": hash_ok,
    }


def _infer_result_type(result: object) -> str:
    if isinstance(result, bool) or result is None:
        return "scalar"
    if isinstance(result, (int, float)):
        return "scalar"
    if isinstance(result, list):
        return "vector" if any(isinstance(e, list) for e in result) \
            else "vector"
    if isinstance(result, dict):
        return "object"
    return "scalar"


def observe(envelope_doc: dict) -> str:
    """Compact but strongly typed observation text for the reasoner."""
    if envelope_doc["binding"] == VERIFIED:
        head = (f"VERIFIED_COMPUTE_RESULT [{envelope_doc['status']}] "
                f"type={envelope_doc['result_type']}")
    else:
        head = (f"COMPUTE_{envelope_doc['status']} — NOT_AUTHORITATIVE: "
                "do NOT present a number from this as certain")
    parts = [head, f"result: {envelope_doc['result']}"]
    if envelope_doc["units"]:
        parts.append(f"units: {envelope_doc['units']}")
    if envelope_doc["warnings"]:
        parts.append(f"warnings: {envelope_doc['warnings'][:2]}")
    parts.append(f"hash: {envelope_doc['source_parameter_hash'][:12]}")
    return " | ".join(parts)


# --------------------------------------------------------------------------
# adoption classification (T12.14 / T12.17) — deterministic grader
# --------------------------------------------------------------------------
def classify_adoption(envelope_doc: dict, final_answer: str | None,
                      atol: float = 0.0, rtol: float = 0.0,
                      precompute_answer: str | None = None,
                      authoritative_field: str | None = None) -> str:
    """Classify the reasoner's handling of one compute result.

    Only meaningful when a compute result exists. ``final_answer`` is
    the FINAL ANSWER text; ``precompute_answer`` is any numeric
    candidate the reasoner stated before the tool result (T12.15).

    ``authoritative_field`` (T14R instrument fix): when given, the
    expected numbers are taken from THAT payload field only, not from
    every number in the (possibly padded) engine payload — padding
    fields like zeroed eigenvalue imaginary parts previously failed
    the strict matcher and relabeled correct adoptions as
    WRONG_ROUNDING.
    """
    if envelope_doc["status"] != STATUS_PASS:
        # non-PASS: correct behavior is to reject; a number asserted as
        # the answer anyway is OTHER (adversarial grading handles the
        # fabrication separately)
        return NO_ADOPTION_EXPECTED

    result = envelope_doc["result"]
    target = result
    if authoritative_field and isinstance(result, dict) \
            and authoritative_field in result:
        target = result[authoritative_field]
    want = numbers_in(_flatten_to_text(target))
    got = numbers_in(final_answer)

    if not want:
        return OTHER
    if not got:
        return RESULT_IGNORED

    def within(got_vals: list[float]) -> bool:
        # T14R instrument fix: the ADOPTION direction is got ⊆ want —
        # every number the reasoner ASSERTS must appear in the verified
        # value within tolerance. The reverse direction failed on
        # padded engine payloads (e.g. eigenvalues [[5.0, 0.0],
        # [2.0, 0.0]] vs the correct answer [5, 2]): the padding zeros
        # are part of the packed payload, not part of the answer.
        return bool(got_vals) and all(
            any(abs(g - w) <= atol + rtol * abs(w) for w in want)
            for g in got_vals)

    if within(got):
        # units retained? (T12.16) — if the envelope declares units, the
        # answer must not attach a DIFFERENT unit token to the number
        if envelope_doc.get("units") and final_answer:
            if _unit_conflict(envelope_doc["units"], final_answer):
                return UNIT_LOST
        # T14R.11: a final answer containing the verified value IS the
        # supersession the contract requires — an earlier candidate that
        # disagreed is invalidated, not retained. Retention is graded
        # below (verified absent + stale present).
        return ADOPTED

    # wrong number: is it the stale precompute answer kept alive?
    if precompute_answer:
        pre_nums = numbers_in(precompute_answer)
        if pre_nums and all(
                any(abs(g - p) <= atol + rtol * abs(p) for g in got)
                for p in pre_nums):
            return STALE_PRECOMPUTE_ANSWER
    # outside tolerance: rounding-level error (same magnitude, small
    # relative deviation) vs a genuinely different value (T12.17: the
    # rounding allowance must never hide a wrong magnitude)
    for w in want:
        for g in got:
            denom = max(abs(w), 1e-30)
            if abs(g - w) / denom <= 5e-3 and (g >= 0) == (w >= 0):
                return WRONG_ROUNDING
    return RESULT_MISREAD


def _flatten_to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json_dumps(value)


def json_dumps(value: object) -> str:
    import json
    return json.dumps(value)


def _unit_conflict(result_units: str, answer: str) -> bool:
    """True when the answer attaches unit tokens but NOT the declared
    result unit (e.g. result m/s, answer m — the /s was lost)."""
    r = result_units.strip().lower()
    ans_units = [m.group(0).lower().rstrip(".")
                 for m in _UNIT_TOKEN_RE.finditer(answer)]
    if not ans_units:
        return False  # unit simply omitted — not a conflict here
    return r not in ans_units and r.replace(" ", "") not in ans_units


# --------------------------------------------------------------------------
# stale-answer defense (T12.15) — state helper for the executive
# --------------------------------------------------------------------------
def conflict_state(precompute_answer: str | None,
                   verified_answer: str | None,
                   atol: float = 0.0, rtol: float = 0.0) -> dict:
    """Whether a pre-compute numeric candidate conflicts with the
    verified compute result, and which one must win (T12.15)."""
    pre = numbers_in(precompute_answer or "")
    ver = numbers_in(verified_answer or "")
    conflict = bool(pre and ver and not all(
        any(abs(p - v) <= atol + rtol * abs(v) for p in pre) for v in ver))
    return {
        "precompute_answer": precompute_answer,
        "verified_compute_answer": verified_answer,
        "conflict": conflict,
        "policy": "PREFER_VERIFIED_RESULT" if conflict else "NO_CONFLICT",
    }