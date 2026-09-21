"""Executed construction audits shared by real and disposable workspaces."""
from __future__ import annotations

import base64
import gzip
import json
import re
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .context import MaterialMode, WorkspaceMode
from .errors import ValidationError
from .exact_design import require_exact_design
from .freeze import verify_freeze
from .preflight import validate_gold_bundle
from .providers import MaterialBundle, MaterialProvider, contract_runtime_native
from .util import read_json, sha256_bytes, sha256_file, sha256_json, write_json

DIMENSIONS = (
    "case_ids",
    "entity_identities",
    "source_ids",
    "chunk_ids",
    "exact_queries",
    "exact_answers",
    "exact_source_text",
    "verbatim_attack_wording",
)
REMEDIATION_DIMENSIONS = (*DIMENSIONS, "relations")
FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
REAL_FORBIDDEN_PATTERNS = (
    re.compile(r"Synthetic qualification", re.IGNORECASE),
    re.compile(r"synthetic\s*=\s*true", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])syn-[A-Za-z0-9_-]*", re.IGNORECASE),
    re.compile(r"stub_candidate", re.IGNORECASE),
    re.compile(r"temporary_fixture", re.IGNORECASE),
)


def _exact(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def _entity(value: object) -> str:
    return " ".join(_exact(value).casefold().split())


def _fingerprint(dimension: str, value: object) -> str:
    normalized = _entity(value) if dimension == "entity_identities" else _exact(value)
    return sha256_bytes(normalized.encode("utf-8"))


def _decode_fingerprints(document: Any) -> set[str]:
    if isinstance(document, str):
        encoded = document
        expected_count = None
        expected_root = None
    elif isinstance(document, dict) and isinstance(document.get("fingerprints"), list):
        values = document["fingerprints"]
        if values != sorted(set(values)) or any(not FINGERPRINT.fullmatch(value) for value in values):
            raise ValidationError("historical fingerprint array is not canonical")
        if document.get("count") != len(values):
            raise ValidationError("historical fingerprint count mismatch")
        return set(values)
    elif isinstance(document, dict):
        encoded = document.get("fingerprints_gzip_base64")
        expected_count = document.get("count")
        expected_root = document.get("set_sha256")
    else:
        raise ValidationError("historical fingerprint payload has unknown schema")
    if not isinstance(encoded, str):
        raise ValidationError("historical fingerprint payload is missing")
    try:
        payload = gzip.decompress(base64.b64decode(encoded, validate=True))
        values = [line for line in payload.decode("ascii").splitlines() if line]
    except (ValueError, OSError, UnicodeError) as exc:
        raise ValidationError(f"historical fingerprint payload is invalid: {exc}") from exc
    if values != sorted(set(values)) or any(not FINGERPRINT.fullmatch(value) for value in values):
        raise ValidationError("historical fingerprints are not sorted unique SHA-256 values")
    canonical = ("\n".join(values) + ("\n" if values else "")).encode("ascii")
    if expected_count is not None and expected_count != len(values):
        raise ValidationError("historical fingerprint payload count mismatch")
    if expected_root is not None and expected_root != sha256_bytes(canonical):
        raise ValidationError("historical fingerprint payload root mismatch")
    return set(values)


def material_values(bundle: MaterialBundle) -> dict[str, set[str]]:
    rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
    values = {dimension: set() for dimension in REMEDIATION_DIMENSIONS}
    values["case_ids"].update(_exact(row.get("case_id")) for row in rows)
    values["source_ids"].update(_exact(source.get("source_id")) for source in bundle.sources)
    values["chunk_ids"].update(_exact(chunk.get("chunk_id")) for chunk in bundle.chunks)
    values["exact_queries"].update(_exact(row.get("query")) for row in rows)
    values["exact_answers"].update(_exact((row.get("gold") or {}).get("expected_answer")) for row in rows)
    values["exact_source_text"].update(_exact(chunk.get("text")) for chunk in bundle.chunks)
    values["verbatim_attack_wording"].update(
        _exact((row.get("construction") or {}).get("attack_wording"))
        for row in rows
        if (row.get("construction") or {}).get("attack_wording")
    )
    for record in bundle.world:
        if record.get("record_type") == "entity" or record.get("type") == "WorldEntity":
            values["entity_identities"].update(
                _entity(record.get(field)) for field in ("entity_id", "name") if record.get(field)
            )
    for chunk in bundle.chunks:
        metadata = chunk.get("metadata") or {}
        if metadata.get("fact_entity"):
            values["entity_identities"].add(_entity(metadata["fact_entity"]))
        if metadata.get("fact_attribute"):
            values["relations"].add(_exact(metadata["fact_attribute"]))
    for row in rows:
        values["relations"].update(
            _exact(value) for value in (row.get("construction") or {}).get("canonical_relations", [])
        )
    return {name: {value for value in items if value} for name, items in values.items()}


def material_fingerprints(bundle: MaterialBundle) -> dict[str, set[str]]:
    return {
        dimension: {_fingerprint(dimension, value) for value in values}
        for dimension, values in material_values(bundle).items()
    }


def _historical_forbidden(source_root: Path, policy: dict[str, Any]) -> dict[str, set[str]]:
    registry = read_json(source_root / policy["upstream_registry"])
    milestones = registry.get("milestones")
    if not isinstance(milestones, dict):
        raise ValidationError("historical registry milestone schema invalid")
    forbidden = {dimension: set() for dimension in DIMENSIONS}
    for milestone, payload in milestones.items():
        dimensions = payload.get("dimensions") if isinstance(payload, dict) else None
        if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
            raise ValidationError(f"historical registry dimensions invalid: {milestone}")
        for dimension in DIMENSIONS:
            forbidden[dimension].update(_decode_fingerprints(dimensions[dimension]))
    return forbidden


def _audit_collision_sets(
    observed: dict[str, set[str]], forbidden: dict[str, set[str]], *, artifact: str, material_mode: MaterialMode
) -> dict[str, Any]:
    collisions = {
        dimension: sorted(observed.get(dimension, set()) & forbidden.get(dimension, set()))
        for dimension in forbidden
    }
    collisions = {dimension: values for dimension, values in collisions.items() if values}
    return {
        "schema_version": "t21-executed-uniqueness-audit-v1",
        "artifact": artifact,
        "status": "PASS" if not collisions else "FAIL",
        "audit_mode": "EXECUTED",
        "material_mode": material_mode.value,
        "dimensions_checked": len(forbidden),
        "fingerprints_checked": sum(len(observed.get(dimension, set())) for dimension in forbidden),
        "collision_total": sum(len(values) for values in collisions.values()),
        "collisions": collisions,
    }


def historical_uniqueness(
    source_root: Path, contract: Any, bundle: MaterialBundle, material_mode: MaterialMode
) -> dict[str, Any]:
    policy = read_json(source_root / contract.get("artifacts.historical_exclusion"))
    forbidden = _historical_forbidden(source_root, policy)
    return _audit_collision_sets(
        material_fingerprints(bundle),
        forbidden,
        artifact=f"{contract.experiment.upper()}_HISTORICAL_UNIQUENESS",
        material_mode=material_mode,
    )


def remediation_uniqueness(
    source_root: Path, contract: Any, bundle: MaterialBundle, material_mode: MaterialMode
) -> dict[str, Any]:
    policy = read_json(source_root / contract.get("artifacts.remediation_exclusion"))
    forbidden = {dimension: set(values) for dimension, values in policy["dimensions"].items()}
    return _audit_collision_sets(
        material_fingerprints(bundle),
        forbidden,
        artifact=f"{contract.experiment.upper()}_REMEDIATION_UNIQUENESS",
        material_mode=material_mode,
    )


def _independent_design(rows: Iterable[dict[str, Any]], contract: Any) -> dict[str, Any]:
    observed = Counter(
        f"{row.get('suite_family')}.{row.get('construction_tag')}"
        for row in rows
        if row.get("construction_tag") is not None
    )
    expected: dict[str, int] = {}
    for family, requirements in contract.get("exact_design").items():
        if family == "crossdomain":
            for pair in contract.get("crossdomain_pairs"):
                expected[f"crossdomain.{pair['id']}"] = requirements["rows_per_pair"]
        else:
            expected.update({f"{family}.{tag}": count for tag, count in requirements.items()})
    mismatches = {
        key: {"expected": expected.get(key), "observed": observed.get(key, 0)}
        for key in sorted(set(expected) | set(observed))
        if expected.get(key) != observed.get(key, 0)
    }
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "requirements": 38,
        "observed_design": dict(sorted(observed.items())),
        "design_root": sha256_json(dict(sorted(observed.items()))),
        "mismatches": mismatches,
    }


def static_gold_audit(root: Path, contract: Any, bundle: MaterialBundle) -> dict[str, Any]:
    report = validate_gold_bundle(root, contract)
    source_ids = {source.get("source_id") for source in bundle.sources}
    chunk_ids = {chunk.get("chunk_id") for chunk in bundle.chunks}
    missing_sources = 0
    missing_chunks = 0
    missing_answers = 0
    rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
    for row in rows:
        gold = row.get("gold") or {}
        missing_sources += len(set(gold.get("source_ids", [])) - source_ids)
        missing_chunks += len(set(gold.get("chunk_ids", [])) - chunk_ids)
        if gold.get("expect_status") == "ANSWER" and not gold.get("expected_answer"):
            missing_answers += 1
    passed = not missing_sources and not missing_chunks and not missing_answers
    return {
        "schema_version": "t21-static-gold-audit-v1",
        "artifact": f"{contract.experiment.upper()}_STATIC_GOLD_AUDIT",
        "status": "PASS" if passed and report["status"] == "PASS" else "FAIL",
        "audit_mode": "EXECUTED",
        "rows": len(rows),
        "missing_source_references": missing_sources,
        "missing_chunk_references": missing_chunks,
        "missing_answers": missing_answers,
        "gold_validator_status": report["status"],
    }


def _forbidden_material_hits(bundle: MaterialBundle) -> list[str]:
    serialized = json.dumps(
        {"rows": bundle.rows_by_suite, "world": bundle.world, "sources": bundle.sources, "chunks": bundle.chunks},
        sort_keys=True,
        ensure_ascii=True,
    )
    return [pattern.pattern for pattern in REAL_FORBIDDEN_PATTERNS if pattern.search(serialized)]


def blindness_audit(
    root: Path,
    bundle: MaterialBundle,
    provider: MaterialProvider,
    workspace_mode: WorkspaceMode,
    material_mode: MaterialMode,
    *,
    experiment: str = "t21r15",
    author_invocations: int,
) -> dict[str, Any]:
    out = root / "evaluations" / experiment
    evaluation_paths = (
        out / "evaluation_run_ledger.json",
        out / "candidate_outputs.jsonl",
        out / "evaluator_results.json",
        out / "score_results.json",
        out / "raw_results.jsonl",
        out / "metric_evidence.json",
        out / "floor_evidence.json",
        out / "holdout_results.json",
    )
    present = [path.name for path in evaluation_paths if path.exists()]
    forbidden_hits = _forbidden_material_hits(bundle) if workspace_mode == WorkspaceMode.REAL_EXPERIMENT else []
    passed = author_invocations == 1 and not present and not forbidden_hits and not provider.placeholder_audits
    return {
        "schema_version": "t21-blindness-audit-v1",
        "artifact": f"{experiment.upper()}_HOLDOUT_BLINDNESS_AUDIT",
        "status": "PASS" if passed else "FAIL",
        "audit_mode": "EXECUTED",
        "workspace_mode": workspace_mode.value,
        "material_mode": material_mode.value,
        "provider_kind": provider.provider_kind,
        "author_invocations": author_invocations,
        "evaluation_artifacts_present": present,
        "forbidden_material_hits": forbidden_hits,
        "placeholder_audits": provider.placeholder_audits,
    }


def root_of_trust_audit(source_root: Path, contract: Any) -> dict[str, Any]:
    roots = contract.get("roots")
    experiment_tag = contract.experiment.upper()
    try:
        candidate_commit = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", roots["candidate_commit"]],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        candidate_tree = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", f"{roots['candidate_commit']}^{{tree}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationError(f"candidate root-of-trust cannot be resolved: {exc}") from exc
    runtime = verify_freeze(
        source_root,
        source_root / contract.get("artifacts.runtime_freeze"),
        artifact=f"{experiment_tag}_RUNTIME_FREEZE",
    )
    evaluator = verify_freeze(
        source_root,
        source_root / contract.get("artifacts.evaluator_freeze"),
        artifact=f"{experiment_tag}_EVALUATOR_FREEZE",
    )
    floor_root = sha256_json(contract.get("promotion_floors"))
    mismatches = []
    if candidate_commit != roots["candidate_commit"]:
        mismatches.append("candidate_commit")
    if candidate_tree != roots["candidate_tree"]:
        mismatches.append("candidate_tree")
    if runtime["root"] != roots["runtime_root"]:
        mismatches.append("runtime_root")
    if evaluator["root"] != roots["evaluator_root"]:
        mismatches.append("evaluator_root")
    if floor_root != roots["floor_hash"]:
        mismatches.append("floor_hash")
    runtime_contract_checks: dict[str, Any] = {}
    if contract_runtime_native(contract) is not None:
        # the candidate provider module is whatever the contract registered;
        # R16 contracts resolve to t21_protocol/providers.py
        provider_module = contract.get("roots.candidate_provider_id").split(":", 1)[0].replace(".", "/") + ".py"
        expected = {
            "runtime_data_contract_root": sha256_json(read_json(source_root / contract.get("artifacts.candidate_runtime_data_contract"))),
            "runtime_corpus_contract_sha256": sha256_file(source_root / contract.get("artifacts.runtime_corpus_contract")),
            "runtime_field_provenance_sha256": sha256_file(source_root / contract.get("artifacts.runtime_field_provenance")),
            "candidate_provider_sha256": sha256_file(source_root / provider_module),
        }
        for name, expected_digest in expected.items():
            actual = roots.get(name)
            if actual != expected_digest:
                mismatches.append(name)
        runtime_contract_checks = {
            "verified_roots": sorted(expected),
            "provider_module": provider_module,
        }
    return {
        "schema_version": "t21-root-of-trust-audit-v1",
        "artifact": f"{experiment_tag}_ROOT_OF_TRUST_AUDIT",
        "status": "PASS" if not mismatches else "FAIL",
        "audit_mode": "EXECUTED",
        "candidate_commit": candidate_commit,
        "candidate_tree": candidate_tree,
        "runtime_root": runtime["root"],
        "evaluator_root": evaluator["root"],
        "floor_hash": floor_root,
        "mismatches": mismatches,
        **({"runtime_contract_checks": runtime_contract_checks} if runtime_contract_checks else {}),
    }


def validate_executed_audit(report: dict[str, Any], workspace_mode: WorkspaceMode) -> None:
    if report.get("status") != "PASS" or report.get("audit_mode") != "EXECUTED":
        raise ValidationError(f"construction audit did not execute successfully: {report.get('artifact')}")
    if workspace_mode == WorkspaceMode.REAL_EXPERIMENT and (
        report.get("placeholder") is True or report.get("synthetic") is True
    ):
        raise ValidationError("placeholder or synthetic PASS audit rejected in REAL_EXPERIMENT mode")


def run_construction_audits(
    root: Path,
    source_root: Path,
    contract: Any,
    bundle: MaterialBundle,
    provider: MaterialProvider,
    workspace_mode: WorkspaceMode,
    material_mode: MaterialMode,
    *,
    author_invocations: int,
) -> dict[str, Any]:
    out = root / "evaluations" / contract.experiment
    experiment_tag = contract.experiment.upper()
    runtime_native = contract_runtime_native(contract) is not None
    rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
    historical = historical_uniqueness(source_root, contract, bundle, material_mode)
    remediation = remediation_uniqueness(source_root, contract, bundle, material_mode)
    exact = require_exact_design(rows, contract)
    exact = {
        "schema_version": "t21-exact-design-audit-v1",
        "artifact": f"{experiment_tag}_EXACT_DESIGN_AUDIT",
        "audit_mode": "EXECUTED",
        **exact,
        "design_root": sha256_json(exact["observed_design"]),
    }
    independent = _independent_design(rows, contract)
    gate_pass = historical["status"] == remediation["status"] == independent["status"] == "PASS"
    gate = {
        "schema_version": "t21-construction-gate-v1",
        "artifact": f"{experiment_tag}_CONSTRUCTION_GATE",
        "status": "PASS" if gate_pass else "FAIL",
        "audit_mode": "EXECUTED",
        "checks": 62 if runtime_native else 60,
        "suite_total": len(rows),
        "design_root": independent["design_root"],
        "independent_design": independent,
        "historical_status": historical["status"],
        "remediation_status": remediation["status"],
    }
    crosscheck = {
        "schema_version": "t21-gate-auditor-crosscheck-v1",
        "artifact": f"{experiment_tag}_GATE_AUDITOR_CROSSCHECK",
        "status": "PASS" if gate["design_root"] == exact["design_root"] else "FAIL",
        "audit_mode": "EXECUTED",
        "gate_design_root": gate["design_root"],
        "auditor_design_root": exact["design_root"],
        "disagreements": 0 if gate["design_root"] == exact["design_root"] else 1,
    }
    static = static_gold_audit(root, contract, bundle)
    blindness = blindness_audit(
        root,
        bundle,
        provider,
        workspace_mode,
        material_mode,
        experiment=contract.experiment,
        author_invocations=author_invocations,
    )
    gold = validate_gold_bundle(root, contract)
    compatibility = {
        "schema_version": "t21-gold-compatibility-v1",
        "artifact": f"{experiment_tag}_GOLD_COMPATIBILITY",
        "status": gold["status"],
        "audit_mode": "EXECUTED",
        "rows": gold["rows"],
        "taxonomy_labels": gold["taxonomy_labels"],
        "floor_paths": gold["floor_paths"],
        "same_gold_validator": True,
    }
    trust = root_of_trust_audit(source_root, contract)
    reports = {
        "historical_uniqueness.json": historical,
        "remediation_uniqueness.json": remediation,
        "construction_gate.json": gate,
        "exact_design_audit.json": exact,
        "gate_auditor_crosscheck.json": crosscheck,
        "static_gold_audit.json": static,
        "holdout_blindness.json": blindness,
        "gold_compatibility.json": compatibility,
        "root_of_trust.json": trust,
    }
    for report in reports.values():
        validate_executed_audit(report, workspace_mode)
    if runtime_native:
        # Runtime-native construction additionally proves, on the executed
        # artifacts, that the frozen loader loaded the real corpus with zero
        # candidate executions and that the frozen production candidate
        # initializes against it without executing holdout rows.
        for name in ("runtime_loader_validation.json", "candidate_provider_compatibility.json"):
            validate_executed_audit(read_json(out / name), workspace_mode)
    for name, report in reports.items():
        write_json(out / name, report, exclusive=True)
    return {"status": "PASS", "reports": len(reports), "design_root": exact["design_root"]}
