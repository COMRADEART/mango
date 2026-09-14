"""T21.6 — corpus freeze and preregistration closure.

Writes evaluations/t21/corpus_manifest.json (frozen corpus identity) and
evaluations/t21/tuning_closed.json (pipeline constants + corpus checksums).
After this script runs, the corpus files and the recorded constants are
FINAL: no tuning, no threshold changes, no gold edits after freeze
(T21.50). The file checksums recorded here are the integrity anchors the
final audit re-verifies.

Usage: python scripts/t21_freeze_corpus.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.citations import resolve_citations  # noqa: E402
from sciencemath.knowledge.claim_gate import (  # noqa: E402
    PARTIAL_THRESHOLD,
    SUPPORT_THRESHOLD,
)
from sciencemath.knowledge.retrieval import (  # noqa: E402
    COVERAGE_WEIGHT,
    JACCARD_THRESHOLD,
    MAX_PER_SOURCE,
    RERANK_TIEBREAK_WEIGHT,
)
from sciencemath.knowledge.pipeline import MIN_COVERAGE, MIN_TOP_SCORE, TOP_K  # noqa: E402
from sciencemath.knowledge.retrieval import decompose_query  # noqa: E402

OUT_DIR = ROOT / "evaluations" / "t21"
CORPUS_DIR = ROOT / "rag" / "gk_corpus"


def main() -> None:
    corpus_manifest = json.loads(
        (CORPUS_DIR / "corpus_manifest.json").read_text(encoding="utf-8"))
    corpus_manifest["generator"] = "scripts/t21_corpus.py"
    corpus_manifest["runtime_package"] = "src/sciencemath/knowledge/"
    corpus_manifest["policy"] = {
        "no_user_document_ingestion": True,
        "no_live_web_text": True,
        "not_training_material": True,
        "retrieval_only": True,
        "project_owned_fixtures": True,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "corpus_manifest.json").write_text(
        json.dumps(corpus_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")

    tuning = {
        "corpus_version": corpus_manifest["corpus_version"],
        "corpus_file_checksums": corpus_manifest["file_checksums"],
        "corpus_manifest_checksum": corpus_manifest["manifest_checksum"],
        "pipeline_constants": {
            "top_k": TOP_K,
            "min_top_score": MIN_TOP_SCORE,
            "min_coverage": MIN_COVERAGE,
            "rerank_coverage_weight": COVERAGE_WEIGHT,
            "rerank_tiebreak_weight": RERANK_TIEBREAK_WEIGHT,
            "rerank_formula": "coverage-primary: score = COVERAGE_WEIGHT * "
                              "whole-question coverage + "
                              "RERANK_TIEBREAK_WEIGHT * normalized BM25 + "
                              "authority bonus",
            "rerank_authority_bonus": 0.02,
            "jaccard_dedup_threshold": JACCARD_THRESHOLD,
            "max_per_source": MAX_PER_SOURCE,
            "max_subqueries": decompose_query.__defaults__[0]
            if decompose_query.__defaults__ else 4,
            "claim_support_threshold": SUPPORT_THRESHOLD,
            "claim_partial_threshold": PARTIAL_THRESHOLD,
            "citation_support_threshold": 0.45,
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
        },
        "policy": {
            "dense_retrieval": "not implemented; lexical BM25 only; RRF "
                               "reserved for a future dense retriever",
            "no_model_memory_backfill": True,
            "no_training_to_repair_defects": True,
            "no_threshold_lowering_after_freeze": True,
            "no_gold_edits_after_freeze": True,
        },
    }
    (OUT_DIR / "tuning_closed.json").write_text(
        json.dumps(tuning, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print("corpus freeze written:")
    print("  ", (OUT_DIR / "corpus_manifest.json").as_posix())
    print("  ", (OUT_DIR / "tuning_closed.json").as_posix())
    print("  corpus manifest checksum:",
          corpus_manifest["manifest_checksum"])


if __name__ == "__main__":
    main()