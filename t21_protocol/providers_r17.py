"""T21R17 candidate serialization and provider: full evidence pass-through.

The frozen R16 canonical serialization (canonical_candidate_row) recorded
only status/answer/counters/citations — the fields the R16 generic scorer
consumed. T21R17's explicit metrics require the runtime's own citation
report, claim review, and evidence-pack records, so the registered v2
serialization passes them through verbatim (still purely re-serializing:
the only transformation remains removing the runtime's inline citation
markers from the composed answer text, exactly as in the frozen R16
serialization). No candidate semantics are added or altered.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .providers import RUNTIME_NATIVE_CANDIDATE, RealCandidateProvider, runtime_modules

PROVIDER_ID_EVIDENCE = "t21_protocol.providers_r17:RealCandidateProviderEvidence"
SERIALIZATION_V2 = "t21_protocol.providers_r17:canonical_candidate_row_v2"


def canonical_candidate_row_v2(case_id: str, answer: Any) -> dict[str, Any]:
    """Registered canonical serialization (v2) of a frozen-runtime answer.

    Passes through the runtime's own status, zero-tolerance counters,
    citations, citation report, claim review, evidence pack, and eligibility
    record. The composed answer text keeps the R16 rule: inline citation
    markers the runtime itself reports are removed (the official gold
    contract is citation-free)."""
    text = answer.answer
    for citation in answer.citations:
        text = text.replace(f" [{citation['citation_id']}]", "")
    return {
        "case_id": case_id,
        "status": answer.status,
        "answer": text.strip(),
        "counters": dict(answer.zero_tolerance),
        "citations": [dict(citation) for citation in answer.citations],
        "citation_report": dict(answer.citation_report),
        "claim_review": dict(answer.claim_review),
        "evidence_pack": dict(answer.evidence_pack),
        "eligibility": dict(answer.eligibility),
        "serialization": "t21-candidate-row-v2",
    }


class RealCandidateProviderEvidence(RealCandidateProvider):
    """Frozen production candidate for T21R17: the identical frozen runtime
    (answer_knowledge over the frozen loader) with the registered v2
    evidence serialization. Same corpus-contract identity as the R16
    provider; initialization loads the corpus exactly once and never
    executes holdout questions."""

    provider_id = PROVIDER_ID_EVIDENCE
    serialization = SERIALIZATION_V2

    def __init__(self, root: Path, corpus_dir: Path, *, top_k: int = 8):
        super().__init__(root, corpus_dir, top_k=top_k)

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        outputs = [
            canonical_candidate_row_v2(
                row["case_id"], self._pipeline_module.answer_knowledge(row["query"], self.corpus, top_k=self.top_k)
            )
            for row in rows
        ]
        self.rows_executed += len(outputs)
        return outputs


def direct_runtime_outputs_v2(root: Path, corpus_dir: Path, rows: list[dict[str, Any]], *, top_k: int = 8) -> list[dict[str, Any]]:
    """Direct frozen-runtime execution mapped through the v2 serialization
    (parity checks for the evidence provider)."""
    _, corpus_module, pipeline_module = runtime_modules(root)
    corpus = corpus_module.load_corpus(corpus_dir)
    return [
        canonical_candidate_row_v2(
            row["case_id"], pipeline_module.answer_knowledge(row["query"], corpus, top_k=top_k)
        )
        for row in rows
    ]


__all__ = [
    "RUNTIME_NATIVE_CANDIDATE",
    "PROVIDER_ID_EVIDENCE",
    "SERIALIZATION_V2",
    "canonical_candidate_row_v2",
    "direct_runtime_outputs_v2",
    "RealCandidateProviderEvidence",
]