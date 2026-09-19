"""Preregistered T21R13 holdout seal protocol (data-only)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "t21r13-seal-v1"
AUTHORIZATION_PHRASE = "T21R13_BLIND_SEAL_AUTHORIZED"
CORPUS_FILES = ("world.jsonl", "sources.jsonl", "chunks.jsonl",
                "corpus_manifest.json")
AUDIT_FILES = (
    "construction_audit.json", "construction_gate.json",
    "static_gold_audit.json", "holdout_uniqueness.json",
    "holdout_blindness.json",
)
EXPOSURE_FILES = (
    "evaluation_run_ledger.json", "raw_results.jsonl", "holdout_results.json",
)
SCRIPT_INPUTS = (
    "t21r13_world.py", "t21r13_build_suites.py",
    "t21r13_retrieval_mirror.py", "t21r13_construction_audit.py",
    "t21r13_construction_gate.py", "t21r13_static_semantics.py",
    "t21r13_static_gold_audit.py", "t21r13_uniqueness.py",
    "t21r13_blindness_audit.py", "t21r13_run_eval.py",
    "t21r13_official_eval.py", "t21r13_freeze_holdout.py",
    "t21r13_preconstruction.py", "t21r13_spec_author.py", "t21r13_blind_author.py", "t21r13_exact_design_lib.py", "t21r13_fixtures.py",
)
EVALUATION_INPUTS = (
    "validation_contract.json", "holdout_construction_contract.json",
    "scoring_semantics.json", "preregistration.json",
    "preconstruction_qualification.json", "prior_exclusion.json",
    "remediation_exclusion.json", "remediation_provenance.json",
    "blindness_policy.json", "synthetic_protocol_report.json",
    "runtime_freeze.json", "evaluator_freeze.json",
    "T21R11_CLOSURE.json",
    "real_blind_construction_readiness.json",
    "current_test_applicability.json",
    "test_failure_adjudication.json",
    "contract_gate_coverage.json",
    "exact_design_tag_vocabulary.json",
    "exact_design_schema.json",
)
FROZEN_ARTIFACTS = (
    ("runtime_freeze.json", "T21R13_RUNTIME_FREEZE"),
    ("evaluator_freeze.json",
    "T21R11_CLOSURE.json",
    "real_blind_construction_readiness.json",
    "current_test_applicability.json",
    "test_failure_adjudication.json",
    "contract_gate_coverage.json",
    "exact_design_tag_vocabulary.json",
    "exact_design_schema.json", "T21R13_EVALUATOR_FREEZE"),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> int:
    return sum(bool(line.strip()) for line in path.read_text(
        encoding="utf-8").splitlines())


def _paths(root: Path) -> tuple[Path, Path, Path]:
    out = root / "evaluations" / "t21r13"
    corpus = root / "rag" / "gk_holdout_t21r13"
    suites = out / "suites"
    return out, corpus, suites


def verify_component_freeze(root: Path, freeze_path: Path, artifact: str) -> \
        dict:
    """Re-hash every frozen component listed in a freeze artifact.

    Refuses (raises ValueError) on any drift, missing component, wrong
    artifact identity, non-frozen status, prior runtime execution, or an
    empty component map. There is no fallback and no rewriting.
    """
    freeze = _json(freeze_path)
    if freeze.get("artifact") != artifact:
        raise ValueError(f"frozen artifact identity mismatch: {freeze_path.name}")
    if freeze.get("status") != "FROZEN":
        raise ValueError(f"frozen artifact is not FROZEN: {freeze_path.name}")
    if freeze.get("runtime_execution_count") != 0:
        raise ValueError(f"frozen artifact records runtime execution: "
                         f"{freeze_path.name}")
    components = freeze.get("component_sha256")
    if not isinstance(components, dict) or not components:
        raise ValueError(f"frozen artifact has no component_sha256 map: "
                         f"{freeze_path.name}")
    for relative, expected in components.items():
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"frozen component entry malformed: {relative}")
        path = root / relative
        if not path.is_file():
            raise ValueError(f"frozen component missing: {relative}")
        if _sha(path) != expected:
            raise ValueError(f"frozen component hash mismatch: {relative}")
    return {"artifact": artifact, "freeze": freeze_path.name,
            "verified_components": len(components), "status": "VERIFIED"}


def verify_all_component_freezes(root: Path, out: Path | None = None) -> dict:
    """Verify every frozen component of both runtime and evaluator freezes."""
    out = out if out is not None else _paths(root)[0]
    results = [verify_component_freeze(root, out / name, artifact)
               for name, artifact in FROZEN_ARTIFACTS]
    return {"status": "VERIFIED",
            "verified_components": sum(result["verified_components"]
                                       for result in results),
            "freezes": results, "runtime_execution_count": 0}


def build_manifest(root: Path) -> dict:
    out, corpus, suites = _paths(root)
    verify_all_component_freezes(root, out)
    for name in EXPOSURE_FILES:
        if (out / name).exists():
            raise ValueError(f"one-shot exposure artifact already exists: {name}")
    contract = _json(out / "holdout_construction_contract.json")
    expected_suites = contract["suite_target_exact"]
    freeze_inputs: dict[str, dict] = {}
    for name in EVALUATION_INPUTS:
        path = out / name
        if not path.is_file():
            raise ValueError(f"missing freeze input: {path}")
        freeze_inputs[path.relative_to(root).as_posix()] = {
            "sha256": _sha(path)}
    for name in SCRIPT_INPUTS:
        path = root / "scripts" / name
        if not path.is_file():
            raise ValueError(f"missing freeze input: {path}")
        freeze_inputs[path.relative_to(root).as_posix()] = {
            "sha256": _sha(path)}
    for name in AUDIT_FILES:
        path = out / name
        if not path.is_file():
            raise ValueError(f"missing audit: {name}")
        audit = _json(path)
        status = audit.get("status") or audit.get("verdict")
        if status not in {"PASS", "UNIQUE"}:
            raise ValueError(f"audit is not passing: {name}")
        freeze_inputs[path.relative_to(root).as_posix()] = {
            "sha256": _sha(path)}
    corpus_block = {}
    for name in CORPUS_FILES:
        path = corpus / name
        if not path.is_file():
            raise ValueError(f"missing corpus file: {name}")
        corpus_block[name] = {"sha256": _sha(path)}
        if path.suffix == ".jsonl":
            corpus_block[name]["rows"] = _rows(path)
    suite_block = {}
    for suite_id, expected_count in expected_suites.items():
        path = suites / suite_id / "holdout.jsonl"
        if not path.is_file():
            raise ValueError(f"missing suite: {suite_id}")
        count = _rows(path)
        if count != expected_count:
            raise ValueError(f"suite count mismatch: {suite_id}")
        suite_block[suite_id] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path), "rows": count,
        }
    freeze_root = hashlib.sha256(json.dumps(
        {"freeze_inputs": freeze_inputs, "corpus": corpus_block,
         "suites": suite_block}, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    return {
        "artifact": "T21R13_HOLDOUT_MANIFEST",
        "schema_version": SCHEMA_VERSION,
        "freeze_root_sha256": freeze_root,
        "freeze_inputs": freeze_inputs,
        "corpus": corpus_block,
        "suites": suite_block,
        "expected_suite_ids": list(expected_suites),
        "expected_exact_counts": expected_suites,
        "runtime_execution_count": 0,
    }


def seal(root: Path) -> dict:
    out, _corpus, _suites = _paths(root)
    manifest_path = out / "holdout_manifest.json"
    marker_path = out / "HOLDOUT_FROZEN"
    if manifest_path.exists() or marker_path.exists():
        raise FileExistsError("refusing to replace an existing T21R13 seal")
    manifest = build_manifest(root)
    manifest_path.write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    marker = {
        "artifact": "T21R13_HOLDOUT_FROZEN",
        "schema_version": SCHEMA_VERSION,
        "holdout_manifest_sha256": _sha(manifest_path),
        "freeze_root_sha256": manifest["freeze_root_sha256"],
        "official_runtime_exposures": 0,
        "runtime_rows_executed": 0,
    }
    marker_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    return {"status": "PASS", "manifest": manifest, "marker": marker,
            "runtime_execution_count": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", required=True)
    arguments = parser.parse_args()
    if arguments.authorization != AUTHORIZATION_PHRASE:
        raise SystemExit("T21R13 sealing is not authorized")
    result = seal(ROOT)
    print(json.dumps({"status": result["status"],
                      "freeze_root_sha256": result["marker"][
                          "freeze_root_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
