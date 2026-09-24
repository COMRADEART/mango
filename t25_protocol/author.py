"""T25 prospective author: frozen T23 authoring machinery, T25 spec and namespace.

The case authoring algorithm is unchanged from T23 (same 16 families, 80 cases
per family, same per-family templates). Only the specification namespace,
labels, and private-source bindings are T25's.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t23_protocol.author import GOLD_ONLY, author_cases, INPUT_FIELDS  # noqa: F401
from t23_protocol.author import ROUTE_IDS, SPEC, _row  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
T25_SPEC = ROOT / "evaluations" / "t25" / "author_specification.json"
REQUIRED_HISTORICAL_EXCLUSIONS = ("T22_OFFICIAL_EVALUATION_PASS",
                                  "T21R16_OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE",
                                  "T21R17_VALID_CAPABILITY_FAILURE",
                                  "T23_SEALED_PUBLICATION_EXCLUDED",
                                  "T24_SEALED_EVALUATED")


def load_spec(path: Path = T25_SPEC) -> dict[str, Any]:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if (spec.get("schema_version") != "t25-author-spec-v1"
            or spec.get("artifact") != "T25_PROSPECTIVE_AUTHOR_SPECIFICATION"
            or spec.get("experiment") != "t25"
            or spec.get("construction_authorized") is not False
            or spec.get("status") != "PRECONSTRUCTION_ONLY"
            or spec.get("cases_per_family") != 80
            or len(spec.get("families", ())) != 16
            or spec.get("taxonomy", {}).get("route_ids") != list(ROUTE_IDS)
            or spec.get("case_id_prefix") != "t25"
            or spec.get("taxonomy", {}).get("case_id_pattern") != r"^t25-[a-z_]+-[0-9]{4}$"
            or set(spec.get("candidate_visible_fields", ())) != set(INPUT_FIELDS)
            or not set(GOLD_ONLY) <= set(spec.get("gold_only_fields", ()))
            or sum(v["count"] for v in spec.get("mixed_intent_variants", {}).values()) != 80
            or spec.get("material_model", {}).get("suite_count") != 16):
        raise ValueError("T25 author specification drift")
    if not set(REQUIRED_HISTORICAL_EXCLUSIONS) <= set(spec.get("historical_exclusions", ())):
        raise ValueError("T25 author specification missing required historical exclusions")
    if "t25-private://" not in spec.get("blind_material_source", ""):
        raise ValueError("T25 author specification must bind blind material to the private store")
    if "t25_protocol.author:author_cases" != spec.get("author_entry"):
        raise ValueError("T25 author entry mismatch")
    return spec


def shadow_labels() -> tuple[str, ...]:
    """Disposable synthetic labels; never real blind content."""
    return tuple(f"disposable T25 shadow record SHD-{index:04d}" for index in range(80))


def fingerprint_root(spec: dict[str, Any]) -> str:
    implementation = Path(__file__).read_bytes()
    co_implementation = (ROOT / "t23_protocol" / "author.py").read_bytes()
    return _digest({"implementation_sha256": hashlib.sha256(implementation).hexdigest(),
                    "co_implementation_sha256": hashlib.sha256(co_implementation).hexdigest(),
                    "specification_sha256": _digest(spec),
                    "algorithm": "t25-prospective-author-v1"})


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def derive_design(spec: dict[str, Any]) -> dict[str, Any]:
    """Recompute the construction design from the author machinery itself."""
    from collections import Counter

    from .contract import REAL_NAMESPACE

    _, gold = author_cases(shadow_labels(), namespace=REAL_NAMESPACE, spec=spec,
                           attachment_path="t25-private://T25-STORE-01/t25/documents/private_attachment")
    capabilities = json.loads((ROOT / "evaluations" / "t25" / "capability_registry.json")
                              .read_text(encoding="utf-8"))
    mapping = {name: f"evaluations/t25/suites/families/{name}.jsonl"
               for name in spec["families"]}
    return {
        "family_count": 16, "suite_count": 16, "cases_per_family": 80,
        "total_rows": 1280, "families": spec["families"], "suite_mapping": mapping,
        "mixed_intent_variants": {k: v["count"] for k, v in spec["mixed_intent_variants"].items()},
        "counterpressure_pairs": spec["counterpressure_pairs"],
        "candidate_visible_fields": spec["candidate_visible_fields"],
        "gold_only_fields": spec["gold_only_fields"],
        "taxonomy": spec["taxonomy"], "privacy": spec["privacy"],
        "source_pool_constraints": spec["source_pool_constraints"],
        "route_counts": dict(sorted(Counter(row["expected_route"] for row in gold).items())),
        "reason_counts": dict(sorted(Counter(row["expected_reason"] for row in gold).items())),
        "capability_labels": sorted(capabilities["capabilities"]),
        "case_id_pattern": spec["taxonomy"]["case_id_pattern"],
    }