"""T20.8/T20.42/T20.43/T20.68 independent deterministic verification.

The VERIFIER is logically separate from workers (T20.9). It receives the
task objective, success criteria, the worker artifact with provenance, and
allowed deterministic checks — never worker hidden reasoning. Only PASS can
satisfy a mandatory verified task criterion (T20.42).
"""
from __future__ import annotations

from sciencemath.orchestration.contract import VERIFIER_DECISIONS
from sciencemath.orchestration.workers import INJECTED_ORCHESTRATOR_DIRECTIVES


def allowed_deterministic_checks(task: dict) -> list[str]:
    checks = ["artifact_present", "content_hash_present",
              "evidence_covers_criteria", "no_error_claim_success",
              "provenance_complete"]
    skill = task.get("required_skill") or ""
    if skill in ("CODE",):
        checks.append("test_results_consistent")
    if skill in ("SCICOMP", "MATH_T4"):
        checks.append("numeric_result_recheck")
    if skill in ("WEB_RESEARCH", "SCIENCE_RAG", "DOCUMENT"):
        checks.append("citation_support")
    return checks


def verify_artifact(task: dict, artifact: dict, worker_result: dict,
                    verifier_agent_id: str,
                    dependency_facts: list | None = None) -> dict:
    """Deterministic verifier decision with structured reasons."""
    reasons: list[str] = []
    decision = "PASS"
    criteria = list(task.get("success_criteria") or [])
    facts = list(worker_result.get("facts") or [])
    blob = " ".join(str(f) for f in facts)
    blob_l = blob.lower()

    # 1. artifact present with content hash
    if not artifact or not artifact.get("artifact_id"):
        decision = "INSUFFICIENT_EVIDENCE"
        reasons.append("missing artifact reference")
    elif not artifact.get("content_hash"):
        reasons.append("artifact content hash missing")
        decision = "INSUFFICIENT_EVIDENCE"

    # 2. evidence coverage of success criteria
    if decision == "PASS":
        missing = []
        for c in criteria:
            cl = str(c).lower()
            if cl and cl not in blob_l:
                missing.append(str(c))
        if missing:
            if not facts:
                decision = "INSUFFICIENT_EVIDENCE"
                reasons.append(
                    "no evidence supplied for criteria: " + "; ".join(missing))
            else:
                decision = "FAIL"
                reasons.append(
                    "evidence does not cover criteria: " + "; ".join(missing))

    # 3. failed tests presented as success (T20.55)
    if decision == "PASS":
        errors = list(worker_result.get("errors") or [])
        if errors and worker_result.get("result_status") == "SUCCEEDED" \
                and any("fail" in str(e).lower() for e in errors):
            decision = "FAIL"
            reasons.append("failed test presented as success")

    # 4. fabricated citation: cites evidence not in inputs/dependencies
    if decision == "PASS" and "cite:" in blob_l:
        deps = {str(x).lower() for x in (dependency_facts or [])}
        for f in facts:
            fl = str(f).lower()
            if fl.startswith("cite:") and f"literal:{f}" not in blob_l:
                if str(f)[5:].lower() not in deps:
                    decision = "FAIL"
                    reasons.append("fabricated citation not in evidence set")

    # 5. bad numerical result: numeric claim must match recheck when provided
    if decision == "PASS" and task.get("numeric_check"):
        exp = (task.get("numeric_check") or {})
        claim = worker_result.get("numeric_value")
        if claim is None or abs(float(claim) - float(exp.get("value"))) > \
                float(exp.get("tol") or 1e-9):
            decision = "FAIL"
            reasons.append("numeric result failed deterministic recheck")

    # 6. injection containment: payload text is DATA (T20.40)
    injection = [d for d in INJECTED_ORCHESTRATOR_DIRECTIVES
                 if d.lower() in blob_l]
    bypass = any(k in blob_l for k in
                 ("skip verifier", "already verified myself",
                  "verification not needed"))
    if injection:
        reasons.append("injected directive treated as data: "
                       + "; ".join(injection))
    if bypass:
        # Bypass claims never waive mandatory verification (T20.68).
        reasons.append("verification bypass claim rejected as data")
        if worker_result.get("payload_flags") and \
                "self_verification_attempt" in worker_result["payload_flags"]:
            reasons.append("self-verification attempt rejected")

    # 7. partial coverage -> bounded revision
    if decision == "PASS" and facts and len(criteria) > len(facts):
        decision = "NEEDS_REVISION"
        reasons.append("partial evidence: bounded revision requested")

    if decision not in VERIFIER_DECISIONS:
        decision = "INSUFFICIENT_EVIDENCE"
    return {
        "verifier_agent_id": verifier_agent_id,
        "decision": decision,
        "reasons": reasons,
        "allowed_checks": allowed_deterministic_checks(task),
    }


def escalate_disagreement(task: dict, artifact: dict,
                          first: dict, second: dict,
                          dependency_facts: list | None = None) -> dict:
    """T20.43 deterministic escalation between two disagreeing verifiers.

    1. identify disputed criterion
    2. run the allowed deterministic check
    3. request bounded worker clarification
    4. otherwise INSUFFICIENT_EVIDENCE (blocked)
    No blind majority vote.
    """
    if first.get("decision") == second.get("decision"):
        return {**first, "escalation": ""}
    disputed = ""
    for r in first.get("reasons") or []:
        for r2 in second.get("reasons") or []:
            if r != r2:
                disputed = r
                break
    # deterministic check: re-run evidence coverage strictly
    strict = verify_artifact(task, artifact,
                             {"facts": list(artifact.get("facts") or []),
                              "errors": [], "result_status": "SUCCEEDED"},
                             "deterministic_check", dependency_facts)
    return {
        "verifier_agent_id": "deterministic_check",
        "decision": strict["decision"],
        "reasons": strict["reasons"] + [f"disputed: {disputed}"],
        "allowed_checks": strict["allowed_checks"],
        "escalation": "deterministic_check",
    }


def verifier_payload_is_data(payload_text: str) -> dict:
    """Verifier-bound payload text is DATA (T20.66)."""
    hit = [d for d in INJECTED_ORCHESTRATOR_DIRECTIVES
           if d.lower() in (payload_text or "").lower()]
    return {"injection_flagged": bool(hit), "flagged_text": hit}