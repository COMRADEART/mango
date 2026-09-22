"""T22 candidate provider: request-date threading over the frozen runtime.

The T22 remediated candidate exposes the temporal signal carrier E
(``request_date``) through the runtime's explicit ``now`` input
(pipeline.answer_knowledge(now=...)). The candidate remains purely
re-serializing at the registered v2 serialization (providers_r17
canonical_candidate_row_v2, byte-identical transformation): the ONLY
delta from the R17 evidence provider is that each gold row's
candidate-visible ``request_date`` field is threaded into the runtime as
the explicit request timestamp. No gold-only field (construction_tag,
expected route/status, floor identity, blind-case labels) is ever read.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .providers import RUNTIME_NATIVE_CANDIDATE, RealCandidateProvider, runtime_modules
from .providers_r17 import SERIALIZATION_V2, canonical_candidate_row_v2

PROVIDER_ID_T22_EVIDENCE = "t21_protocol.providers_t22:RealCandidateProviderT22Evidence"


class RealCandidateProviderT22Evidence(RealCandidateProvider):
    """Production candidate for T22: the identical frozen runtime
    (answer_knowledge over the frozen loader) with the registered v2
    serialization and the T22 request-date carrier threading. Same
    corpus-contract identity as the R17 provider; initialization loads the
    corpus exactly once and never executes holdout questions."""

    provider_id = PROVIDER_ID_T22_EVIDENCE
    serialization = SERIALIZATION_V2

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        outputs = [
            canonical_candidate_row_v2(
                row["case_id"],
                self._pipeline_module.answer_knowledge(
                    row["query"], self.corpus, top_k=self.top_k,
                    now=row.get("request_date", ""),
                ),
            )
            for row in rows
        ]
        self.rows_executed += len(outputs)
        return outputs


def direct_runtime_outputs_v2_t22(
    root: Path,
    corpus_dir: Path,
    rows: list[dict[str, Any]],
    *,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Direct frozen-runtime execution with the T22 request-date threading,
    mapped through the v2 serialization (parity checks for the provider)."""
    _, corpus_module, pipeline_module = runtime_modules(root)
    corpus = corpus_module.load_corpus(corpus_dir)
    return [
        canonical_candidate_row_v2(
            row["case_id"],
            pipeline_module.answer_knowledge(
                row["query"], corpus, top_k=top_k,
                now=row.get("request_date", ""),
            ),
        )
        for row in rows
    ]


__all__ = [
    "RUNTIME_NATIVE_CANDIDATE",
    "PROVIDER_ID_T22_EVIDENCE",
    "SERIALIZATION_V2",
    "canonical_candidate_row_v2",
    "direct_runtime_outputs_v2_t22",
    "RealCandidateProviderT22Evidence",
]