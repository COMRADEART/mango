"""Construction-time T23 blindness audit; no runtime or evaluator calls."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .author import GOLD_ONLY
from .contract import PATHS, sha256_json
from t21_protocol.util import sha256_path

PROHIBITED_PROVENANCE = {
    "HISTORICAL_REAL_BLIND", "OPEN_DEVELOPMENT", "PUBLIC_T23_QUALIFICATION",
    "CANDIDATE_OUTPUT", "FUTURE_OFFICIAL_EVALUATION",
}
FUTURE_OUTPUTS = tuple(PATHS[key] for key in (
    "router_decisions", "selected_capability_execution", "candidate_outputs",
    "router_evaluator", "capability_evaluator", "raw_results",
    "router_metric_evidence", "router_floor_evidence",
    "protected_t22_metric_evidence", "protected_t22_floor_evidence",
    "holdout_results", "evaluation_provenance", "evaluation_ledger"))


def audit_blindness(root: Path, inputs: list[dict[str, Any]], gold: list[dict[str, Any]],
                    provenance: dict[str, Any], *, real: bool,
                    labels: list[str] | tuple[str, ...] | None = None,
                    source_corpus: Path | None = None) -> dict[str, Any]:
    """Require explicit source provenance and zero observed contamination."""
    base_fields = {"source_kind", "source_root", "prohibited_sources_read",
                   "candidate_outputs_read", "historical_blind_values_read",
                   "open_development_values_read", "qualification_values_read",
                   "shadow_values_read", "future_evaluation_values_read"}
    real_fields = {"labels_sha256", "corpus_sha256", "independent_author",
                   "source_pool_origin"}
    if set(provenance) != base_fields | (real_fields if real else set()):
        raise ValueError("blindness provenance incomplete")
    expected_kind = "INDEPENDENT_PRIVATE" if real else "SYNTHETIC_DISPOSABLE"
    if provenance["source_kind"] != expected_kind:
        raise ValueError("blindness source kind mismatch")
    if not isinstance(provenance["source_root"], str) or not provenance["source_root"]:
        raise ValueError("blindness source root missing")
    if real:
        source = Path(provenance["source_root"]).resolve()
        if not source.is_dir() or source.is_relative_to(Path(root).resolve()):
            raise ValueError("real source pool is not external private material")
        if (labels is None or source_corpus is None
                or source != Path(source_corpus).resolve()
                or provenance["labels_sha256"] != sha256_json(list(labels))
                or provenance["corpus_sha256"] != sha256_path(source)
                or not isinstance(provenance["independent_author"], str)
                or not provenance["independent_author"].strip()
                or provenance["source_pool_origin"] != "UNSEEN_INDEPENDENT_PRIVATE_POOL"):
            raise ValueError("private source provenance does not bind the supplied material")
    candidate = sum(bool(set(row.get("candidate_input", {})) & GOLD_ONLY)
                    or bool(set(row) - {"case_id", "candidate_input", "execution_context"})
                    for row in inputs)
    candidate += int(provenance["candidate_outputs_read"])
    historical = int(provenance["historical_blind_values_read"])
    development = int(provenance["open_development_values_read"])
    qualification = int(provenance["qualification_values_read"])
    shadow = int(provenance["shadow_values_read"]) if real else 0
    future = int(provenance["future_evaluation_values_read"])
    if provenance["prohibited_sources_read"]:
        if not isinstance(provenance["prohibited_sources_read"], list):
            raise ValueError("prohibited source provenance malformed")
        for category in provenance["prohibited_sources_read"]:
            if category not in PROHIBITED_PROVENANCE:
                raise ValueError("unknown prohibited source category")
            if category == "HISTORICAL_REAL_BLIND":
                historical += 1
            elif category == "OPEN_DEVELOPMENT":
                development += 1
            elif category == "PUBLIC_T23_QUALIFICATION":
                qualification += 1
            elif category == "CANDIDATE_OUTPUT":
                candidate += 1
            else:
                future += 1
    future += sum((Path(root) / relative).exists() for relative in FUTURE_OUTPUTS)
    if real:
        shadow += sum("SHD-" in json.dumps(row) or "t23-shadow" in row.get("case_id", "")
                      for row in inputs)
    if len(inputs) != len(gold):
        raise ValueError("blindness input/gold count mismatch")
    violations = candidate + historical + development + qualification + shadow + future
    return {
        "schema_version": "t23-construction-blindness-v1",
        "status": "PASS" if violations == 0 else "FAIL",
        "candidate_leakage": candidate, "historical_leakage": historical,
        "open_development_leakage": development,
        "public_qualification_leakage": qualification,
        "disposable_shadow_leakage": shadow,
        "future_evaluation_leakage": future, "violations": violations,
        "source_provenance_sha256": sha256_json(provenance),
    }


def synthetic_provenance() -> dict[str, Any]:
    return {"source_kind": "SYNTHETIC_DISPOSABLE", "source_root": "SOURCE_PUBLIC_FIXTURE",
            "prohibited_sources_read": [], "candidate_outputs_read": 0,
            "historical_blind_values_read": 0, "open_development_values_read": 0,
            "qualification_values_read": 0, "shadow_values_read": 0,
            "future_evaluation_values_read": 0}
