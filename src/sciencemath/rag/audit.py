"""audit — retrieval audit logging (T5.24).

Every retrieval-enabled answer is auditable. One JSONL record per
answer attempt (RetrievalAuditLogger, mirroring tools.router.ToolCallLogger):

    query, router decision (route + tools + domain), retrieval used
    yes/no, embedding model, retrieved chunk IDs, retrieval scores,
    reranking scores, selected context (ids), rejected context (ids +
    why), tool calls, final source IDs, latency, errors.

Never logs secrets or credentials: the logger redacts anything that
looks like an authorization header/token if it ever appears in a record.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_SECRET_RE = re.compile(
    r"((?:authorization|api[_-]?key|token|password|secret|bearer)"
    r"\s*[:=]\s*(?:bearer\s+)?)\S+",
    re.IGNORECASE)


def _redact(value):
    """Best-effort redaction of credential-looking strings."""
    if isinstance(value, str):
        return _SECRET_RE.sub(r"\1<redacted>", value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class RetrievalAuditLogger:
    """Append-only JSONL audit log (thread-safe)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records = 0
        self._lock = threading.Lock()

    def log(self, record: dict) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 **_redact(record)}
        try:
            text = json.dumps(entry, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = json.dumps(
                {k: str(v) for k, v in entry.items()}, ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
            self._records += 1

    def log_answer_attempt(
        self, *, question_id: str, question: str, route: dict,
        retrieval_used: bool, embedding_model: str | None,
        retrieved_chunk_ids: list[str], retrieval_scores: dict[str, float],
        rerank_scores: dict[str, float], selected_ids: list[str],
        rejected: list[dict], tool_calls: list[dict], final_source_ids: list[str],
        latency_s: float, error: str | None = None,
        evidence_state: str | None = None,
    ) -> None:
        self.log({
            "event": "rag_answer",
            "question_id": question_id,
            "question_preview": question[:160],
            "route": route,
            "retrieval_used": retrieval_used,
            "embedding_model": embedding_model,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieval_scores": retrieval_scores,
            "rerank_scores": rerank_scores,
            "selected_context_ids": selected_ids,
            "rejected_context": rejected,
            "tool_calls": tool_calls,
            "final_source_ids": final_source_ids,
            "evidence_state": evidence_state,
            "latency_s": round(latency_s, 4),
            "error": error,
        })