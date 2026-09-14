"""DOCUMENT → SCICOMP / CODE / WEB sanitizers. Facts only."""
from __future__ import annotations

from sciencemath.document.injection import (
    sanitize_for_code, sanitize_for_scicomp, sanitize_for_web,
)
from sciencemath.document.models import FLOAT, INTEGER, NormalizedDocument


def numeric_inputs_from_document(doc: NormalizedDocument, column: str | None = None
                                 ) -> dict:
    values = []
    lineage = []
    for t in doc.tables:
        cols = [column] if column else list(t.inferred_types)
        for i, row in enumerate(t.rows):
            for c in cols:
                cell = row.get(c)
                if cell is None:
                    continue
                if cell.inferred_type in (INTEGER, FLOAT) and isinstance(
                        cell.interpreted_value, (int, float)) and not isinstance(
                        cell.interpreted_value, bool):
                    values.append(cell.interpreted_value)
                    lineage.append({
                        "document_id": doc.document_id, "table": t.table_name,
                        "row": i, "column": c, "raw_value": cell.raw_value,
                    })
    payload = sanitize_for_scicomp(values)
    payload["lineage"] = lineage
    payload["operation_hint"] = "describe"
    return payload


def route_to_scicomp(doc: NormalizedDocument, column: str | None = None) -> dict:
    from sciencemath.scicomp.invocation import invoke
    nums = numeric_inputs_from_document(doc, column)
    values = nums.get("values") or []
    if len(values) < 2:
        return {"status": "DOC_NO_EVIDENCE", "reason": "need_numeric_column",
                **nums}
    result = invoke({"operation": "describe", "inputs": {"values": values}},
                    question="describe numeric column from document")
    env = result.envelope
    # Document text cannot override SciComp
    return {
        "status": env.get("status"),
        "scicomp": env,
        "document_inputs": nums,
        "document_overrides_scicomp": False,
        "adopted": result.adopted,
    }


def facts_for_code(doc: NormalizedDocument) -> dict:
    facts = [b.text[:400] for b in doc.blocks[:12]]
    return sanitize_for_code(facts)


def web_release_gate(doc: NormalizedDocument, *, user_explicit: bool = False
                     ) -> dict:
    gate = sanitize_for_web(doc.text or "")
    if user_explicit:
        gate["user_explicit_compare"] = True
        gate["may_upload"] = False
        gate["reason"] = "still_local_unless_provider_free_and_explicit"
    return gate
