"""Deterministically rebind public T23 construction identities; no real material."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from t23_protocol.author import author_cases, shadow_labels  # noqa: E402
from t23_protocol.contract import (AUTHORIZATION, CANDIDATE_COMMIT, CANDIDATE_TREE,
                                   EVALUATION_AUTHORIZATION, LEGACY_TRANSITIONS,
                                   PATHS, PRECONSTRUCTION_ARTIFACTS, RUNTIME_ROOT,
                                   STATES, VALUE_KEYS)  # noqa: E402

OUT = ROOT / "evaluations/t23"


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def binding(relative: str) -> dict[str, str]:
    return {"path": relative, "sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()}


def main() -> None:
    candidate = json.loads((OUT / "candidate_identity.json").read_text(encoding="utf-8"))
    if "previous_t23_candidate" not in candidate:
        previous = candidate["t23_candidate"].copy()
        candidate["previous_t23_candidate"] = {
            "candidate_commit": previous["candidate_commit"],
            "candidate_tree": previous["candidate_tree"],
            "historical_status": "SUPERSEDED_BY_QUALIFIED_T23_PRECONSTRUCTION",
        }
    candidate["t23_candidate"]["candidate_commit"] = CANDIDATE_COMMIT
    candidate["t23_candidate"]["candidate_tree"] = CANDIDATE_TREE
    candidate["t23_candidate"]["candidate_parent"] = "b5cb0a8fc9762e55e2224fdb102977337cf7cc46"
    write(OUT / "candidate_identity.json", candidate)
    spec = json.loads((OUT / "author_specification.json").read_text(encoding="utf-8"))
    mapping = {name: f"evaluations/t23/suites/families/{name}.jsonl"
               for name in spec["families"]}
    spec["material_model"] = {
        "family": "one named construction stratum",
        "suite": "one family-specific JSONL output",
        "corpus": "one loader-verified source/chunk collection",
        "specification": "public frozen authoring rules and taxonomy",
        "case": "one identified authored example and private gold",
        "row": "one case in the global input/gold pair and its family suite",
        "family_to_suite": mapping,
        "suite_count": len(mapping),
    }
    write(OUT / "author_specification.json", spec)
    anchor_path = "evaluations/t23/t22_exclusion_anchor.json"
    prior = json.loads((ROOT / "evaluations/t22/prior_exclusion.json").read_text(encoding="utf-8"))
    sources = {
        "historical": binding("evaluations/t22/prior_exclusion.json"),
        "remediation": binding("evaluations/t22/remediation_exclusion.json"),
        "qualification": binding("evaluations/t23/nonblind_qualification_inputs.jsonl"),
        "t22_anchor": binding(anchor_path),
    }
    registry = {"schema_version": "t23-exclusion-sources-v1",
                "sources": sources, "required_milestones": prior["milestone_order"]}
    write(OUT / "construction_exclusion_sources.json", registry)
    _, gold = author_cases(shadow_labels(), namespace="t23-shadow",
                           spec=spec, attachment_path="documents/shadow.txt")
    route_counts = dict(sorted(Counter(row["expected_route"] for row in gold).items()))
    reason_counts = dict(sorted(Counter(row["expected_reason"] for row in gold).items()))
    capabilities = json.loads((OUT / "capability_registry.json").read_text(encoding="utf-8"))
    design = {
        "family_count": 16, "suite_count": 16, "cases_per_family": 80,
        "total_rows": 1280, "families": spec["families"],
        "suite_mapping": mapping,
        "mixed_intent_variants": {k: v["count"] for k, v in spec["mixed_intent_variants"].items()},
        "counterpressure_pairs": spec["counterpressure_pairs"],
        "candidate_visible_fields": spec["candidate_visible_fields"],
        "gold_only_fields": spec["gold_only_fields"],
        "taxonomy": spec["taxonomy"],
        "privacy": spec["privacy"],
        "source_pool_constraints": spec["source_pool_constraints"],
        "route_counts": route_counts, "reason_counts": reason_counts,
        "capability_labels": sorted(capabilities["capabilities"]),
        "case_id_pattern": spec["taxonomy"]["case_id_pattern"],
    }
    values = {
        "identity": {"candidate_commit": CANDIDATE_COMMIT,
                     "candidate_tree": CANDIDATE_TREE, "runtime_root": RUNTIME_ROOT},
        "artifacts": PRECONSTRUCTION_ARTIFACTS | PATHS,
        "real_t23_paths": list(PATHS.values()),
        "shadow_namespace": "t23-shadow-disposable",
        "transitions": LEGACY_TRANSITIONS,
        "authorization": {"construction": AUTHORIZATION,
                          "evaluation": EVALUATION_AUTHORIZATION},
        "construction_authorized": False,
        "construction_design": design,
        "exclusion_sources": sources,
        "construction_states": list(STATES),
        "construction_requirements": {
            "candidate_rows_executed": 0, "evaluator_rows_executed": 0,
            "annotation_violations": 0, "exclusion_status": "PASS",
            "blindness_status": "PASS", "uniqueness_status": "PASS",
            "one_shot_attempt": 1,
        },
    }
    assert set(values) == VALUE_KEYS
    contract = {"schema_version": "t23-master-contract-v2",
                "artifact": "T23_MASTER_CONTRACT", "experiment": "t23",
                "fields": [f"values.{name}" for name in sorted(values)],
                "values": values}
    write(OUT / "t23_master_contract.json", contract)
    print(json.dumps({"candidate_commit": CANDIDATE_COMMIT,
                      "contract_sha256": hashlib.sha256((OUT / "t23_master_contract.json").read_bytes()).hexdigest(),
                      "source_registry_sha256": hashlib.sha256((OUT / "construction_exclusion_sources.json").read_bytes()).hexdigest()},
                     sort_keys=True))


if __name__ == "__main__":
    main()
