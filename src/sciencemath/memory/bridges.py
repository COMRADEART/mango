"""MEMORY ↔ other skills. Memory text has no tool-execution authority."""
from __future__ import annotations

from sciencemath.memory.safety import sanitize_facts, scan_injection


def facts_for_code(contents: list[str]) -> dict:
    return sanitize_facts(contents, kind="memory_facts_code")


def facts_for_document(contents: list[str]) -> dict:
    return sanitize_facts(contents, kind="memory_facts_document")


def facts_for_web(contents: list[str]) -> dict:
    g = sanitize_facts(contents, kind="memory_facts_web")
    g["may_upload"] = False
    return g


def facts_for_scicomp(contents: list[str]) -> dict:
    g = sanitize_facts(contents, kind="memory_facts_scicomp")
    g["may_override_scicomp"] = False
    return g


def document_to_memory_request(*, fact: str, document_id: str,
                               citation: dict, user_explicit: bool) -> dict:
    """DOCUMENT may persist only when explicitly authorized."""
    inj = scan_injection(fact)
    return {
        "content": fact,
        "memory_type": "DOCUMENT_DERIVED",
        "source_type": "DOCUMENT",
        "source_reference": f"{document_id}:{citation}",
        "provenance": {
            "document_id": document_id,
            "citation": citation,
            "instruction_authority": 0,
            "injection": inj,
        },
        "user_explicit": user_explicit,
        "durable_memory": bool(user_explicit),
        "write_reason": "USER_EXPLICIT_SAVE" if user_explicit else None,
        "instruction_authority": 0,
    }


def web_to_memory_request(*, claim: str, source_id: str, citation: dict,
                          retrieved_at: str, freshness: str,
                          user_explicit: bool, valid_until: str | None) -> dict:
    return {
        "content": claim,
        "memory_type": "WEB_DERIVED",
        "source_type": "WEB",
        "source_reference": f"{source_id}:{citation}",
        "provenance": {
            "source_id": source_id, "citation": citation,
            "retrieved_at": retrieved_at, "freshness": freshness,
            "instruction_authority": 0,
        },
        "user_explicit": user_explicit,
        "durable_memory": bool(user_explicit),
        "write_reason": "USER_EXPLICIT_SAVE" if user_explicit else None,
        "valid_until": valid_until,
        "instruction_authority": 0,
    }


def scicomp_to_memory_request(*, operation: str, result, result_hash: str,
                              verified: bool, user_explicit: bool) -> dict:
    return {
        "content": f"{operation} => {result}",
        "memory_type": "TOOL_RESULT",
        "source_type": "SCICOMP",
        "source_reference": result_hash,
        "provenance": {
            "operation": operation, "result_hash": result_hash,
            "verified": verified, "instruction_authority": 0,
        },
        "user_explicit": user_explicit,
        "durable_memory": bool(user_explicit),
        "write_reason": "TOOL_VERIFIED_RESULT" if user_explicit else None,
        "confidence": "VERIFIED" if verified else "MEDIUM",
        "instruction_authority": 0,
    }


def code_to_memory_request(*, decision: str, run_id: str,
                           user_explicit: bool) -> dict:
    return {
        "content": decision,
        "memory_type": "PROJECT_DECISION",
        "source_type": "CODE",
        "source_reference": run_id,
        "provenance": {"run_id": run_id, "instruction_authority": 0},
        "user_explicit": user_explicit,
        "durable_memory": bool(user_explicit),
        "write_reason": "PROJECT_STATE_COMMIT" if user_explicit else None,
        "instruction_authority": 0,
    }
