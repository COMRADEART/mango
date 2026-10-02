"""Canonical domain-taxonomy contract shared by every protocol consumer."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .util import read_json, sha256_json

TAXONOMY_KEYS = frozenset({"schema_version", "artifact", "experiment", "domains"})
DOMAIN_KEYS = frozenset({"canonical_label", "description", "aliases"})


def normalize_domain(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"[-\s]+", "_", normalized)


def validate_taxonomy(document: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if set(document) != TAXONOMY_KEYS:
        errors.append("taxonomy root fields must match the closed schema")
    domains = document.get("domains")
    if not isinstance(domains, list) or not domains:
        errors.append("domains must be a non-empty array")
        domains = []
    labels: list[str] = []
    for index, domain in enumerate(domains):
        if not isinstance(domain, dict) or set(domain) != DOMAIN_KEYS:
            errors.append(f"domain {index} violates the closed schema")
            continue
        label = domain["canonical_label"]
        if not isinstance(label, str) or normalize_domain(label) != label:
            errors.append(f"domain {index} is not canonical")
        labels.append(label)
        if domain["aliases"] != []:
            errors.append(f"domain {label} defines forbidden aliases")
    if labels != sorted(set(labels)):
        errors.append("domain labels must be sorted and unique")
    if errors:
        raise ValidationError("; ".join(errors))
    return {
        "status": "PASS",
        "canonical_count": len(labels),
        "canonical_labels": labels,
        "taxonomy_root": sha256_json(document),
    }


def load_taxonomy(path: Path) -> dict[str, Any]:
    document = read_json(path)
    validate_taxonomy(document)
    return document


def canonical_labels(document: dict[str, Any]) -> frozenset[str]:
    validate_taxonomy(document)
    return frozenset(domain["canonical_label"] for domain in document["domains"])


def validate_labels(labels: Iterable[Any], taxonomy: dict[str, Any], *, context: str = "row") -> None:
    if isinstance(labels, (str, bytes)):
        raise ValidationError(f"{context}: required_domains has wrong type")
    materialized = list(labels)
    if any(not isinstance(label, str) or not label for label in materialized):
        raise ValidationError(f"{context}: required_domains contains null/empty label")
    normalized = [normalize_domain(label) for label in materialized]
    if len(normalized) != len(set(normalized)):
        raise ValidationError(f"{context}: required_domains contains duplicates")
    unknown = sorted(set(normalized) - canonical_labels(taxonomy))
    if unknown:
        raise ValidationError(f"{context}: labels outside the canonical taxonomy: {unknown}")


def coverage_report(taxonomy: dict[str, Any], consumers: dict[str, Iterable[str]]) -> dict[str, Any]:
    canonical = canonical_labels(taxonomy)
    report: dict[str, Any] = {
        "canonical_count": len(canonical),
        "unknown": 0,
        "consumers": {},
    }
    for name, labels in sorted(consumers.items()):
        consumed = frozenset(labels)
        unknown = sorted(consumed - canonical)
        missing = sorted(canonical - consumed) if name in {"evaluator", "scorer", "domain_macro_aggregator"} else []
        report["unknown"] += len(unknown)
        report["consumers"][name] = {
            "covered": len(consumed & canonical),
            "unknown": unknown,
            "missing": missing,
            "status": "PASS" if not unknown and not missing else "FAIL",
        }
    report["status"] = "PASS" if report["unknown"] == 0 and all(
        item["status"] == "PASS" for item in report["consumers"].values()
    ) else "FAIL"
    return report
