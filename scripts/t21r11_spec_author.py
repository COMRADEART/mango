"""Author the T21R11 preregistration contracts without blind material."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r11"
R10_DIR = ROOT / "evaluations" / "t21r10"

SUITE_TARGETS = {
    "mango-t21r11-retrieval-holdout-v1": 600,
    "mango-t21r11-singlehop-holdout-v1": 550,
    "mango-t21r11-multihop-holdout-v1": 800,
    "mango-t21r11-crossdomain-holdout-v1": 700,
    "mango-t21r11-citation-claim-holdout-v1": 450,
    "mango-t21r11-conflict-abstention-holdout-v1": 800,
    "mango-t21r11-temporal-holdout-v1": 250,
    "mango-t21r11-adversarial-holdout-v1": 650,
}

PROHIBITED_REAL_PATHS = [
    "rag/gk_holdout_t21r11",
    "evaluations/t21r11/suites",
    "evaluations/t21r11/HOLDOUT_FROZEN",
    "evaluations/t21r11/holdout_manifest.json",
    "evaluations/t21r11/evaluation_run_ledger.json",
    "evaluations/t21r11/raw_results.jsonl",
    "evaluations/t21r11/holdout_results.json",
]

STATES = {
    "KNOWLEDGE_RAG": "EXPERIMENTAL",
    "Executive Router": "EXPERIMENTAL",
    "T21": "OPEN",
    "T21R9": "CLOSED / NON_PROMOTIONAL_INFRASTRUCTURE_FAILURE",
    "T21R10": "CLOSED / VALID_CAPABILITY_FAILURE",
    "T21R11": "PREREGISTRATION / PRECONSTRUCTION",
    "T22": "BLOCKED",
}

HYPOTHESES = {
    "H1_RETRIEVAL": {
        "claim": "Improve top-window retrieval while retaining top-10 reachability.",
        "measures": ["recall_at_5", "recall_at_10", "mrr", "ndcg_at_5",
                     "source_diversity"],
    },
    "H2_MULTIHOP": {
        "claim": "Improve structured path resolution through parsing, relation interpretation, and bridge validation.",
        "measures": ["multi_hop_grounded_accuracy", "bridge_correctness",
                     "terminal_evidence_correctness", "partial_path_behavior"],
    },
    "H3_CROSS_DOMAIN": {
        "claim": "Combine independently supported cross-domain evidence without unsupported synthesis.",
        "measures": ["cross_domain_synthesis_accuracy"],
    },
    "H4_CONFLICT": {
        "claim": "Detect contradiction and avoid false resolution.",
        "measures": ["conflict_detection", "conflict_false_resolution"],
    },
    "H5_ABSTENTION": {
        "claim": "Recognize insufficient evidence with high precision.",
        "measures": ["insufficient_evidence_precision",
                     "insufficient_evidence_recall",
                     "unsupported_confident_answers"],
    },
    "H6_CITATIONS": {
        "claim": "Bind every factual claim to the exact evidence used.",
        "measures": ["citation_resolvability", "citation_validity",
                     "citation_precision", "citation_coverage",
                     "supported_factual_claim_rate",
                     "fabricated_citation_count"],
    },
    "H7_REGRESSION_PROTECTION": {
        "claim": "Retain all temporal and security strengths demonstrated by T21R10.",
        "measures": ["explicit_current_routing_accuracy",
                     "stale_snapshot_false_current_answers",
                     "static_query_unnecessary_web_routing",
                     "historical_as_of_handling",
                     "prompt_injection_containment",
                     "citation_id_spoof_rejection",
                     "source_authority_escalation_events",
                     "model_memory_backfill_events",
                     "retrieved_code_execution_events",
                     "unauthorized_network_action_events",
                     "unauthorized_memory_write_events"],
    },
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write(name: str, value: object) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")


def build_documents() -> dict[str, dict]:
    r10_validation = _json(R10_DIR / "validation_contract.json")
    r10_semantics = _json(R10_DIR / "scoring_semantics.json")
    floors = r10_validation["floors"]
    floor_bytes = _canonical(floors)
    if sum(len(group) for group in floors.values()) != 32:
        raise ValueError("T21R10 floor count is not exactly 32")
    floor_sha = _sha_bytes(floor_bytes)

    validation = {
        "artifact": "T21R11_VALIDATION_CONTRACT",
        "version": "t21r11-validation-v1",
        "preregistered_before_blind_data": True,
        "promotion_floor_count": 32,
        "floors": floors,
        "floor_canonical_sha256": floor_sha,
        "t21r10_floor_canonical_sha256": _sha_bytes(
            _canonical(r10_validation["floors"])),
        "floor_difference": [],
        "official_evaluation": {
            "evaluator": "scripts/t21r11_run_eval.py",
            "official_runner": "scripts/t21r11_official_eval.py",
            "preflight_only_entry": "t21r11_official_eval.preflight",
            "one_shot_exposure_maximum": 1,
            "automatic_retry": "FORBIDDEN",
            "failed_run": "PERMANENT",
        },
        "states": STATES,
    }
    scoring = {
        "artifact": "T21R11_SCORING_SEMANTICS",
        "milestone": "T21R11",
        "version": "t21r11-scoring-v1",
        "definition": r10_semantics["definition"],
        "canonical_definition_sha256": _sha_bytes(
            _canonical(r10_semantics["definition"])),
        "t21r10_definition_sha256": _sha_bytes(
            _canonical(r10_semantics["definition"])),
        "semantic_difference": [],
    }
    construction = {
        "artifact": "T21R11_HOLDOUT_CONSTRUCTION_CONTRACT",
        "version": "t21r11-construction-v1",
        "blind_data_authorized": False,
        "runtime_execution_maximum": 0,
        "candidate_repair_policy": "Any failed real construction/static gate closes that candidate non-promotional; no post-construction repair.",
        "blind_namespace": {
            "name": "mango-r11b-v1",
            "case_id_prefix": "r11b-",
            "must_be_new": True,
        },
        "suite_target_exact": SUITE_TARGETS,
        "total_rows_exact": sum(SUITE_TARGETS.values()),
        "retrieval_mirror": {
            "implementation": "scripts/t21r11_retrieval_mirror.py",
            "top_k": 8,
            "candidate_multiplier": 3,
            "stages": ["normalization", "BM25", "reranking",
                       "same_source_dedup", "source_reservation", "top_8"],
            "initial_window_source": "derived_by_static_audit",
            "builder_declared_initial_window_forbidden": True,
            "parity_with_frozen_production_required": True,
        },
        "path_achievability": {
            "first_edge": "safe FactEdge from derived top-8 matching exact normalized start identity and canonical first relation",
            "leader_ranking": ["authority_rank", "freshness_rank"],
            "equal_rank_contradiction": "CONFLICTING_EVIDENCE",
            "selected_value_must_equal_bridge": True,
            "hop2_and_terminal_validated_separately": True,
            "bridge_identity": "exact NFKC casefold whitespace identity",
            "terminal_evidence": "required and independently validated",
        },
        "multihop_exact_design": {
            "two_hop_bridges": 200,
            "wrong_bridge_distractors": 100,
            "ambiguous_bridge_entities": 100,
            "missing_second_hop": 100,
            "invalid_terminal_evidence": 100,
            "partial_paths": 100,
            "relation_aliases": 50,
            "led_by_relations": 50,
        },
        "crossdomain_exact_design": {
            "novel_pair_families": 7,
            "rows_per_pair": 100,
            "r10_exact_pair_templates_forbidden": True,
        },
        "conflict_exact_design": {
            "same_rank_contradiction": 100,
            "authority_ranked_contradiction": 100,
            "fresh_stale_disagreement": 100,
            "numeric_disagreement": 100,
            "identity_disagreement": 100,
            "relation_disagreement": 100,
            "resolvable_conflicts": 100,
            "unresolvable_conflicts": 100,
        },
        "citation_exact_design": {
            "wrong_locator": 60, "wrong_source": 60, "wrong_chunk": 60,
            "right_source_wrong_chunk": 60, "missing_citation": 50,
            "partial_citation": 50, "multi_source_claim": 60,
            "spoofed_locator": 50,
        },
        "temporal_exact_design": {
            "explicit_current": 70, "stale_snapshot": 70,
            "static_unnecessary_web": 60, "historical_as_of": 50,
        },
        "security_exact_design": {
            "prompt_injection": 150, "citation_id_spoof": 100,
            "source_authority_escalation": 100, "memory_backfill": 100,
            "retrieved_code_execution": 75,
            "unauthorized_network": 75, "unauthorized_memory_write": 50,
        },
        "abstention_required_scenarios": [
            "missing_evidence", "partial_evidence", "missing_bridge",
            "invalid_terminal", "irrelevant_retrieval", "conflicting_evidence",
        ],
        "independence": {
            "prior_fingerprint_artifact": "evaluations/t21r11/prior_exclusion.json",
            "remediation_fingerprint_artifact": "evaluations/t21r11/remediation_exclusion.json",
            "historical_milestones": [
                "T21", "T21R", "T21R2", "T21R3", "T21R4", "T21R5",
                "T21R6", "T21R7", "T21R8_DIAGNOSTIC", "T21R9_SEALED",
                "T21R10_SEALED"],
            "historical_dimensions": [
                "case_ids", "entity_identities", "source_ids", "chunk_ids",
                "exact_queries", "exact_answers", "exact_source_text",
                "verbatim_attack_wording"],
            "open_remediation_dimensions": [
                "case_ids", "entity_identities", "source_ids", "chunk_ids",
                "exact_queries", "exact_answers", "exact_source_text",
                "verbatim_attack_wording", "relations"],
            "maximum_overlap": 0,
            "algorithm": "SHA-256",
            "raw_historical_material_available_to_builders": False,
        },
        "builder_firewall": {
            "scripts": ["scripts/t21r11_world.py",
                        "scripts/t21r11_build_suites.py"],
            "forbidden_modules": ["sciencemath", "pipeline", "router",
                "retrieval", "evidence_paths", "relations", "conflicts",
                "citations", "injection", "t21r11_run_eval"],
            "forbidden_calls": ["answer_knowledge", "resolve_path",
                "retrieve", "run_answer_row", "evaluate"],
            "historical_blind_paths_forbidden": True,
            "remediation_validation_paths_forbidden": True,
        },
        "prohibited_real_paths_before_authorization": PROHIBITED_REAL_PATHS,
    }
    blindness = {
        "artifact": "T21R11_BLINDNESS_POLICY",
        "version": "t21r11-blindness-v1",
        "candidate_runtime_imports_forbidden": True,
        "candidate_outputs_forbidden": True,
        "candidate_failures_forbidden": True,
        "candidate_decision_traces_forbidden": True,
        "candidate_source_implementation_details_forbidden": True,
        "individual_t21r10_failures_forbidden": True,
        "t21r11_remediation_validation_outputs_forbidden": True,
        "raw_historical_material_available_to_builder": False,
        "allowed_inputs": ["evaluation contracts", "hash-only exclusions",
                           "independent private blind specification"],
        "ast_audit": "scripts/t21r11_blindness_audit.py",
    }
    preregistration = {
        "artifact": "T21R11_PREREGISTRATION",
        "version": "t21r11-preregistration-v1",
        "phase": "PREREGISTRATION / PRECONSTRUCTION",
        "real_blind_construction_authorized": False,
        "official_blind_status": "NOT_BUILT",
        "promotion_authorized": False,
        "hypotheses": HYPOTHESES,
        "suite_target_exact": SUITE_TARGETS,
        "total_rows_exact": sum(SUITE_TARGETS.values()),
        "promotion_floor_count": 32,
        "promotion_floors_canonical_sha256": floor_sha,
        "promotion_floors_byte_equivalent_to_t21r10": True,
        "one_shot": {
            "existing_ledger": "REFUSE", "existing_raw": "REFUSE",
            "existing_results": "REFUSE", "failed_run": "PERMANENT",
            "automatic_retry": "FORBIDDEN",
        },
        "remediation_evidence_interpretation": {
            "DEV": "OPEN",
            "VALIDATION": "FROZEN_INTERNAL_VALIDATION",
            "OFFICIAL_BLIND": "NOT_BUILT",
            "claim": "Targeted mechanisms repaired on open/frozen internal diagnostics only; no official capability claim.",
        },
        "t21r10_preservation": {
            "official_result": "T21R10_OFFICIAL_EVALUATION_FAIL",
            "floors_passed": 19, "floors_failed": 13,
            "rows_executed": 4800, "runtime_errors": 0,
            "zero_tolerance_security_violations": 0,
            "rerun": False, "rescore": False, "holdout_modified": False,
        },
        "states": STATES,
        "stop_rule": "A PASS authorizes only a separate construction request; no real blind construction or evaluation.",
    }
    return {
        "preregistration.json": preregistration,
        "validation_contract.json": validation,
        "scoring_semantics.json": scoring,
        "holdout_construction_contract.json": construction,
        "blindness_policy.json": blindness,
    }


def write_documents() -> dict:
    documents = build_documents()
    present = [path for path in PROHIBITED_REAL_PATHS
               if (ROOT / path).exists()]
    if present:
        raise RuntimeError(f"real R11 paths already exist: {present}")
    for name, value in documents.items():
        _write(name, value)
    return {name: _sha_bytes((OUT_DIR / name).read_bytes())
            for name in documents}


def main() -> int:
    hashes = write_documents()
    print(json.dumps({"status": "PASS", "artifacts": hashes},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
