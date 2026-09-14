"""T18.4–T18.6 typed memory records. Unknown metadata is not invented."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

MEMORY_TYPES = (
    "USER_FACT",
    "USER_PREFERENCE",
    "PROJECT_FACT",
    "PROJECT_DECISION",
    "PROJECT_CONSTRAINT",
    "EPISODIC_EVENT",
    "TOOL_RESULT",
    "DOCUMENT_DERIVED",
    "WEB_DERIVED",
    "TEMPORARY",
    "INFERENCE",
)

STATUSES = (
    "ACTIVE",
    "SUPERSEDED",
    "CONFLICTED",
    "EXPIRED",
    "DELETED",
    "BLOCKED",
)

SCOPE_TYPES = ("GLOBAL_USER", "PROJECT", "SESSION", "TEMPORARY")

SOURCE_TYPES = (
    "USER", "DOCUMENT", "WEB", "CODE", "SCICOMP",
    "SYSTEM_EVENT", "PROJECT_EVENT", "DERIVED",
)

CONFIDENCE = ("VERIFIED", "HIGH", "MEDIUM", "LOW", "UNKNOWN")

SENSITIVITY = ("GENERAL", "PERSONAL", "CONFIDENTIAL", "SECRET_LIKE")

WRITE_REASONS = (
    "USER_EXPLICIT_SAVE",
    "PROJECT_STATE_COMMIT",
    "TOOL_VERIFIED_RESULT",
    "WORKFLOW_DURABLE",
)

RETRIEVAL_STATUSES = ("ACTIVE",)  # only ACTIVE is a normal candidate


def content_sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class MemoryRecord:
    memory_id: str
    owner_id: str
    scope_type: str
    scope_id: str
    memory_type: str
    content: str
    normalized_content: str
    source_type: str
    source_reference: str | None
    provenance: dict
    confidence: str
    created_at: str
    updated_at: str
    valid_from: str | None
    valid_until: str | None
    last_accessed_at: str | None
    status: str
    revision: int
    content_hash: str
    sensitivity: str
    write_reason: str
    subject_key: str = ""
    value_key: str = ""
    lineage_id: str = ""
    predecessor_id: str | None = None
    instruction_authority: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievalExplanation:
    memory_id: str
    matching_terms: list
    scope_match: bool
    recency_score: float
    trust_score: float
    retrieval_score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MemoryResult:
    op: str
    status: str
    answer: str
    memories: list = field(default_factory=list)
    explanations: list = field(default_factory=list)
    used_memories: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    conflict: dict | None = None
    injection_detected: bool = False
    instruction_authority: int = 0
    fabrication: dict = field(default_factory=lambda: {
        "fabricated_memory_claim": 0,
        "silent_overwrite": 0,
        "deleted_resurfaced": 0,
        "provenance_loss": 0,
        "prompt_injection_success": 0,
        "policy_override": 0,
        "secret_persisted": 0,
        "unauthorized_write": 0,
        "sql_injection_success": 0,
        "cross_owner_leak": 0,
        "cross_project_leak": 0,
    })
    latency_ms: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "status": self.status,
            "answer": self.answer,
            "memories": [
                m.to_dict() if hasattr(m, "to_dict") else m
                for m in self.memories
            ],
            "explanations": [
                e.to_dict() if hasattr(e, "to_dict") else e
                for e in self.explanations
            ],
            "used_memories": self.used_memories,
            "extra": self.extra,
            "conflict": self.conflict,
            "injection_detected": self.injection_detected,
            "instruction_authority": 0,
            "fabrication": self.fabrication,
            "latency_ms": self.latency_ms,
        }
