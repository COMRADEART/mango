"""T21R12 exact-design schema, vocabulary, and gate handlers.

Mechanical only: construction_tags must exactly match contract leaf names
for COUNT leaves. No synonyms. No post-hoc remapping.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable

EXACT_DESIGN_OBJECTS = (
    "multihop_exact_design",
    "crossdomain_exact_design",
    "citation_exact_design",
    "conflict_exact_design",
    "temporal_exact_design",
    "security_exact_design",
)

# Leaf type registry: every preregistered leaf must appear here.
LEAF_TYPES: dict[str, dict[str, str]] = {
    "multihop_exact_design": {
        "two_hop_bridges": "COUNT",
        "wrong_bridge_distractors": "COUNT",
        "ambiguous_bridge_entities": "COUNT",
        "missing_second_hop": "COUNT",
        "invalid_terminal_evidence": "COUNT",
        "partial_paths": "COUNT",
        "relation_aliases": "COUNT",
        "led_by_relations": "COUNT",
    },
    "crossdomain_exact_design": {
        "novel_pair_families": "COUNT",
        "rows_per_pair": "EXACT_DISTRIBUTION",
        "prior_exact_pair_templates_forbidden": "FORBIDDEN_OVERLAP",
    },
    "citation_exact_design": {
        "wrong_locator": "COUNT",
        "wrong_source": "COUNT",
        "wrong_chunk": "COUNT",
        "right_source_wrong_chunk": "COUNT",
        "missing_citation": "COUNT",
        "partial_citation": "COUNT",
        "multi_source_claim": "COUNT",
        "spoofed_locator": "COUNT",
    },
    "conflict_exact_design": {
        "same_rank_contradiction": "COUNT",
        "authority_ranked_contradiction": "COUNT",
        "fresh_stale_disagreement": "COUNT",
        "numeric_disagreement": "COUNT",
        "identity_disagreement": "COUNT",
        "relation_disagreement": "COUNT",
        "resolvable_conflicts": "COUNT",
        "unresolvable_conflicts": "COUNT",
    },
    "temporal_exact_design": {
        "explicit_current": "COUNT",
        "stale_snapshot": "COUNT",
        "static_unnecessary_web": "COUNT",
        "historical_as_of": "COUNT",
    },
    "security_exact_design": {
        "prompt_injection": "COUNT",
        "citation_id_spoof": "COUNT",
        "source_authority_escalation": "COUNT",
        "memory_backfill": "COUNT",
        "retrieved_code_execution": "COUNT",
        "unauthorized_network": "COUNT",
        "unauthorized_memory_write": "COUNT",
    },
}

CROSSDOMAIN_PAIR_TAGS = (
    "literature_to_biography",
    "arts_to_biography",
    "technology_history_to_biography",
    "history_to_biography",
    "culture_to_biography",
    "natural_philosophy_to_biography",
    "civic_architecture_to_biography",
)

# Canonical tag vocabulary = all COUNT leaf names + crossdomain pair tags.
def tag_vocabulary() -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for obj, leaves in LEAF_TYPES.items():
        tags = [name for name, typ in leaves.items() if typ == "COUNT"]
        if obj == "crossdomain_exact_design":
            tags = list(CROSSDOMAIN_PAIR_TAGS)
        groups[obj] = tags
    all_tags = sorted({tag for tags in groups.values() for tag in tags})
    return {
        "artifact": "T21R12_EXACT_DESIGN_TAG_VOCABULARY",
        "version": "t21r12-v1",
        "synonyms_allowed": False,
        "groups": groups,
        "all_tags": all_tags,
        "crossdomain_pair_tags": list(CROSSDOMAIN_PAIR_TAGS),
        "rule": "construction_tags entries that claim exact-design membership must be in all_tags; COUNT leaves are counted by exact tag match",
    }


def default_contract_exact_design() -> dict[str, dict[str, Any]]:
    return {
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
            "prior_exact_pair_templates_forbidden": True,
        },
        "citation_exact_design": {
            "wrong_locator": 60,
            "wrong_source": 60,
            "wrong_chunk": 60,
            "right_source_wrong_chunk": 60,
            "missing_citation": 50,
            "partial_citation": 50,
            "multi_source_claim": 60,
            "spoofed_locator": 50,
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
        "temporal_exact_design": {
            "explicit_current": 70,
            "stale_snapshot": 70,
            "static_unnecessary_web": 60,
            "historical_as_of": 50,
        },
        "security_exact_design": {
            "prompt_injection": 150,
            "citation_id_spoof": 100,
            "source_authority_escalation": 100,
            "memory_backfill": 100,
            "retrieved_code_execution": 75,
            "unauthorized_network": 75,
            "unauthorized_memory_write": 50,
        },
    }


def enumerate_leaves(contract: dict) -> list[tuple[str, str, Any, str]]:
    """Return (object, leaf, required, type) for every exact-design leaf."""
    out: list[tuple[str, str, Any, str]] = []
    for obj in EXACT_DESIGN_OBJECTS:
        if obj not in contract:
            raise ValueError(f"missing exact-design object: {obj}")
        expected_types = LEAF_TYPES[obj]
        actual = contract[obj]
        unknown = set(actual) - set(expected_types)
        missing = set(expected_types) - set(actual)
        if unknown:
            raise ValueError(f"unknown contract fields in {obj}: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing contract leaves in {obj}: {sorted(missing)}")
        for leaf, required in sorted(actual.items()):
            out.append((obj, leaf, required, expected_types[leaf]))
    return out


def _tag_counts(rows: list[dict]) -> Counter:
    counts: Counter = Counter()
    for row in rows:
        tags = row.get("construction_tags") or []
        if not isinstance(tags, list):
            continue
        for tag in tags:
            counts[str(tag)] += 1
    return counts


def _unknown_tags(rows: list[dict], vocabulary: set[str]) -> list[str]:
    bad: list[str] = []
    for row in rows:
        for tag in row.get("construction_tags") or []:
            t = str(tag)
            # Allow non-design operational tags only if prefixed with meta:
            if t in vocabulary or t.startswith("meta:"):
                continue
            # Any tag that looks like a design leaf name but is unknown is fatal;
            # also any tag not in vocabulary and not meta: is fatal under R12.
            bad.append(t)
    return sorted(set(bad))


def check_exact_design_count(required: int, rows: list[dict], leaf: str) -> dict:
    observed = int(_tag_counts(rows).get(leaf, 0))
    return {
        "gate_function": "check_exact_design_count",
        "source_field": "construction_tags",
        "comparison": "==",
        "required": required,
        "observed": observed,
        "passed": observed == required,
    }


def check_exact_design_distribution(required: int, rows: list[dict], leaf: str) -> dict:
    """rows_per_pair: each CROSSDOMAIN_PAIR_TAGS tag must equal required."""
    counts = _tag_counts(rows)
    per = {tag: int(counts.get(tag, 0)) for tag in CROSSDOMAIN_PAIR_TAGS}
    passed = all(v == required for v in per.values()) and len(per) == len(CROSSDOMAIN_PAIR_TAGS)
    return {
        "gate_function": "check_exact_design_distribution",
        "source_field": "construction_tags",
        "comparison": f"each of {len(CROSSDOMAIN_PAIR_TAGS)} pair tags == {required}",
        "required": required,
        "observed": per,
        "passed": passed,
    }


def check_novel_pair_families(required: int, rows: list[dict], leaf: str) -> dict:
    counts = _tag_counts(rows)
    present = [tag for tag in CROSSDOMAIN_PAIR_TAGS if counts.get(tag, 0) > 0]
    observed = len(present)
    return {
        "gate_function": "check_novel_pair_families",
        "source_field": "construction_tags",
        "comparison": "==",
        "required": required,
        "observed": observed,
        "present_families": present,
        "passed": observed == required,
    }


def check_forbidden_overlap(required: bool, context: dict, leaf: str) -> dict:
    """prior_exact_pair_templates_forbidden: context must supply overlap_total==0."""
    overlap = int(context.get("prior_pair_template_overlap", context.get("prior_exact_query_overlap", -1)))
    ok = (overlap == 0) if required else True
    return {
        "gate_function": "check_forbidden_overlap",
        "source_field": "prior_exclusion_fingerprints",
        "comparison": "overlap_total == 0" if required else "n/a",
        "required": required,
        "observed": overlap,
        "passed": ok,
    }


HANDLER_BY_TYPE: dict[str, str] = {
    "COUNT": "check_exact_design_count",
    "EXACT_DISTRIBUTION": "check_exact_design_distribution",
    "FORBIDDEN_OVERLAP": "check_forbidden_overlap",
    "BOOLEAN": "check_forbidden_overlap",
    "MINIMUM": "check_exact_design_count",
    "MAXIMUM": "check_exact_design_count",
    "EXACT_SET": "check_novel_pair_families",
    "RATIO_MINIMUM": "check_exact_design_count",
    "RATIO_MAXIMUM": "check_exact_design_count",
}


def evaluate_leaf(
    obj: str,
    leaf: str,
    required: Any,
    leaf_type: str,
    rows: list[dict],
    context: dict | None = None,
) -> dict:
    context = context or {}
    if leaf_type == "COUNT":
        result = check_exact_design_count(int(required), rows, leaf)
    elif leaf_type == "EXACT_DISTRIBUTION" and leaf == "rows_per_pair":
        result = check_exact_design_distribution(int(required), rows, leaf)
    elif leaf_type in {"COUNT"}:
        result = check_exact_design_count(int(required), rows, leaf)
    elif leaf == "novel_pair_families":
        result = check_novel_pair_families(int(required), rows, leaf)
    elif leaf_type in {"FORBIDDEN_OVERLAP", "BOOLEAN"}:
        result = check_forbidden_overlap(bool(required), context, leaf)
    else:
        return {
            "gate_function": None,
            "source_field": None,
            "comparison": None,
            "required": required,
            "observed": None,
            "passed": False,
            "error": f"unhandled leaf type {leaf_type}",
            "status": "UNHANDLED",
        }
    result.update({
        "contract_path": f"{obj}.{leaf}",
        "requirement_type": leaf_type,
        "status": "PASS" if result["passed"] else "FAIL",
    })
    return result


def evaluate_exact_design(contract: dict, rows: list[dict], context: dict | None = None) -> dict:
    context = context or {}
    vocab = set(tag_vocabulary()["all_tags"])
    unknown = _unknown_tags(rows, vocab)
    checks = []
    unhandled = 0
    for obj, leaf, required, leaf_type in enumerate_leaves(contract):
        # novel_pair_families uses dedicated handler even though typed COUNT
        if leaf == "novel_pair_families":
            result = check_novel_pair_families(int(required), rows, leaf)
            result.update({
                "contract_path": f"{obj}.{leaf}",
                "requirement_type": leaf_type,
                "status": "PASS" if result["passed"] else "FAIL",
            })
        else:
            result = evaluate_leaf(obj, leaf, required, leaf_type, rows, context)
        if result.get("status") == "UNHANDLED" or result.get("gate_function") is None:
            unhandled += 1
        checks.append(result)
    passed = sum(1 for c in checks if c.get("status") == "PASS")
    failed = sum(1 for c in checks if c.get("status") == "FAIL")
    unknown_ok = len(unknown) == 0
    status = "PASS" if failed == 0 and unhandled == 0 and unknown_ok else "FAIL"
    return {
        "status": status,
        "leaf_requirements_total": len(checks),
        "passed": passed,
        "failed": failed,
        "unhandled": unhandled,
        "unknown_construction_tags": unknown,
        "checks": checks,
    }


def schema_document(contract: dict) -> dict:
    leaves = []
    for obj, leaf, required, leaf_type in enumerate_leaves(contract):
        handler = (
            "check_novel_pair_families" if leaf == "novel_pair_families"
            else HANDLER_BY_TYPE.get(leaf_type)
        )
        leaves.append({
            "contract_path": f"{obj}.{leaf}",
            "object": obj,
            "leaf": leaf,
            "requirement_type": leaf_type,
            "required": required,
            "gate_function": handler,
            "source_field": (
                "prior_exclusion_fingerprints"
                if leaf_type in {"FORBIDDEN_OVERLAP", "BOOLEAN"} and leaf != "novel_pair_families"
                else "construction_tags"
            ),
        })
    handlers = {leaf["gate_function"] for leaf in leaves}
    unhandled = [leaf for leaf in leaves if not leaf["gate_function"]]
    return {
        "artifact": "T21R12_EXACT_DESIGN_SCHEMA",
        "version": "t21r12-v1",
        "objects": list(EXACT_DESIGN_OBJECTS),
        "leaf_requirements_registered": len(leaves),
        "gate_handlers_registered": len(leaves) - len(unhandled),
        "unhandled_leaves": len(unhandled),
        "handler_names": sorted(handlers - {None}),
        "leaves": leaves,
        "fail_closed_on": [
            "unknown contract field",
            "unhandled contract leaf",
            "missing design tag",
            "unknown construction tag",
            "count mismatch",
            "distribution mismatch",
            "forbidden overlap",
            "suite mismatch",
            "annotation violation",
            "runtime execution",
        ],
    }
