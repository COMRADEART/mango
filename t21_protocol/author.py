"""Deterministic contract-driven authoring used by qualification and construction."""
from __future__ import annotations

from typing import Any

from .author_t22 import compose_row_authoring
from .taxonomy import canonical_labels, load_taxonomy
from .util import sha256_json


def build_specs(contract: Any, root_for_contract_artifacts) -> dict[str, Any]:
    taxonomy = load_taxonomy(root_for_contract_artifacts / contract.get("artifacts.domain_taxonomy"))
    labels = sorted(canonical_labels(taxonomy))
    pairs = contract.get("crossdomain_pairs")
    suites: dict[str, Any] = {}
    for suite_name, suite in contract.get("suites").items():
        suites[suite_name] = {
            "family": suite["family"],
            "count": suite["count"],
            "namespace": contract.get("identity.namespace"),
            "case_id_prefix": contract.get("identity.case_id_prefix"),
        }
    spec = {
        "schema_version": "t21-author-spec-v1",
        "experiment": contract.experiment,
        "seed": contract.get("author.seed"),
        "vocabulary": contract.get("author.vocabulary"),
        "canonical_domains": labels,
        "crossdomain_pairs": pairs,
        "suites": suites,
        "exact_design": contract.get("exact_design"),
    }
    # T22-only, contract-gated: contracts that declare the frozen temporal
    # design artifact carry the validated row_authoring block (per-tag
    # templates, sub-shapes, request-date carrier); every prior experiment's
    # contract lacks the declaration and keeps the byte-identical spec.
    row_authoring = compose_row_authoring(contract, root_for_contract_artifacts)
    if row_authoring is not None:
        spec["row_authoring"] = row_authoring
    return spec


def fingerprint_root(spec: dict[str, Any]) -> str:
    return sha256_json(spec)


def shadow_author(contract: Any, root_for_contract_artifacts) -> dict[str, Any]:
    spec = build_specs(contract, root_for_contract_artifacts)
    return {"spec": spec, "fingerprint_root": fingerprint_root(spec)}
