"""Exact T23 manifest and independently recomputable holdout seal."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_path, write_json
from .construction_ledger import construction_state, frozen_bindings, verify_ledger
from .contract import canonical, load_t23_contract, sha256_json

SOURCE_BINDINGS = {
    "candidate_identity": "evaluations/t23/candidate_identity.json",
    "construction_contract": "evaluations/t23/t23_master_contract.json",
    "author_specification": "evaluations/t23/author_specification.json",
    "author_lock": "evaluations/t23/author_lock.json",
    "historical_exclusion": "evaluations/t23/historical_exclusion.json",
    "exclusion_source_registry": "evaluations/t23/construction_exclusion_sources.json",
    "t22_exclusion_anchor": "evaluations/t23/t22_exclusion_anchor.json",
    "applicability_ledger": "evaluations/t23/historical_applicability.json",
    "applicability_validation": "evaluations/t23/applicability_validation_report.json",
    "runtime_freeze": "evaluations/t22/runtime_freeze.json",
    "evaluator_freeze": "evaluations/t22/evaluator_freeze.json",
    "evaluation_graph": "evaluations/t23/production_evaluation_graph.json",
    "official_evaluator": "t23_protocol/evaluation.py",
    "scoring_definitions": "t23_protocol/scorer.py",
    "provider_binding": "t23_protocol/provider.py",
    "construction_gate_implementation": "t23_protocol/construction_gate.py",
    "blindness_implementation": "t23_protocol/blindness.py",
    "uniqueness_implementation": "t23_protocol/exclusions.py",
    "ledger_implementation": "t23_protocol/construction_ledger.py",
    "manifest_implementation": "t23_protocol/manifest.py",
}
MATERIAL_BINDINGS = {
    "construction_ledger": "evaluations/t23/construction_run_ledger.json",
    "corpus_sources": "rag/gk_holdout_t23/sources.jsonl",
    "corpus_chunks": "rag/gk_holdout_t23/chunks.jsonl",
    "corpus_manifest": "rag/gk_holdout_t23/corpus_manifest.json",
    "inputs": "evaluations/t23/suites/inputs.jsonl",
    "gold": "evaluations/t23/suites/gold.jsonl",
    "static_audit": "evaluations/t23/suites/static_audit.json",
    "blindness_audit": "evaluations/t23/suites/blindness_audit.json",
    "uniqueness_audit": "evaluations/t23/suites/uniqueness_audit.json",
    "construction_gate": "evaluations/t23/suites/construction_gate.json",
    "construction_audits": "evaluations/t23/construction_audits.json",
}


def _digest(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"T23 manifest missing artifact: {path}")
    return sha256_path(path)


def _semantic_digest(name: str, path: Path) -> str:
    if name == "construction_ledger":
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.pop("created_at", None)
        doc.pop("updated_at", None)
        for event in doc["events"]:
            event.pop("at", None)
        return sha256_json(doc)
    return _digest(path)


def build_manifest(source_root: Path, material_root: Path, *,
                   attachment_path: str, real: bool, namespace: str) -> dict[str, Any]:
    source_root, material_root = Path(source_root).resolve(), Path(material_root).resolve()
    if construction_state(material_root) not in {"GATE_PASS", "MANIFESTED", "SEALED"}:
        raise ValueError("T23 manifest requires GATE_PASS or later")
    contract = load_t23_contract(source_root / "evaluations/t23/t23_master_contract.json")
    design = contract.get("construction_design")
    bindings: dict[str, dict[str, str]] = {}
    freeze_name = ("preconstruction_production_freeze_v3.json"
                   if (source_root / "evaluations/t23/preconstruction_production_freeze_v3.json").exists()
                   else "preconstruction_production_freeze_v2.json")
    source_bindings = dict(SOURCE_BINDINGS)
    source_bindings["preconstruction_freeze"] = "evaluations/t23/" + freeze_name
    material_bindings = dict(MATERIAL_BINDINGS)
    for family, relative in design["suite_mapping"].items():
        material_bindings["suite_" + family] = relative
    material_bindings["document_attachment"] = attachment_path
    suite_dir = material_root / "evaluations/t23/suites"
    expected_suite_files = {relative for relative in material_bindings.values()
                            if relative.startswith("evaluations/t23/suites/")}
    actual_suite_files = {path.relative_to(material_root).as_posix()
                          for path in suite_dir.rglob("*") if path.is_file()}
    if actual_suite_files != expected_suite_files:
        raise ValueError("T23 suites contain missing or unregistered material")
    corpus_dir = material_root / "rag/gk_holdout_t23"
    if {path.name for path in corpus_dir.iterdir()} != {
            "sources.jsonl", "chunks.jsonl", "corpus_manifest.json"}:
        raise ValueError("T23 corpus contains missing or unregistered material")
    for scope, root, registry in (("SOURCE", source_root, source_bindings),
                                  ("MATERIAL", material_root, material_bindings)):
        for name, relative in sorted(registry.items()):
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("T23 manifest path escapes its root")
            bindings[name] = {"scope": scope, "path": relative,
                              "sha256": _digest(path),
                              "semantic_sha256": _semantic_digest(name, path)}
    identity = frozen_bindings(source_root, real=real, namespace=namespace)
    ledger = verify_ledger(material_root / MATERIAL_BINDINGS["construction_ledger"], identity)
    if ledger["state"] != "GATE_PASS":
        raise ValueError("T23 ledger not gated")
    semantic_bindings = {name: {k: v for k, v in binding.items() if k != "sha256"}
                         for name, binding in bindings.items()}
    return {"schema_version": "t23-holdout-manifest-v2", "artifact": "T23_HOLDOUT_MANIFEST",
            "experiment": "t23", "identity": identity,
            "identity_root": sha256_json(identity),
            "bindings": bindings, "binding_count": len(bindings),
            "semantic_root": sha256_json(semantic_bindings),
            "raw_binding_root": sha256_json(bindings)}


def verify_manifest(source_root: Path, material_root: Path) -> dict[str, Any]:
    source_root, material_root = Path(source_root).resolve(), Path(material_root).resolve()
    path = material_root / "evaluations/t23/holdout_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != "t23-holdout-manifest-v2"
            or manifest.get("experiment") != "t23"
            or manifest.get("binding_count") != len(manifest.get("bindings", {}))
            or manifest.get("identity_root") != sha256_json(manifest.get("identity"))):
        raise ValueError("T23 manifest schema or identity mismatch")
    identity = manifest["identity"]
    expected = frozen_bindings(source_root, real=identity["material_mode"] == "REAL_BLIND",
                               namespace=identity["real_namespace"])
    if identity != expected:
        raise ValueError("T23 manifest frozen identity mismatch")
    recomputed = build_manifest(source_root, material_root,
                                attachment_path=manifest["bindings"]["document_attachment"]["path"],
                                real=identity["material_mode"] == "REAL_BLIND",
                                namespace=identity["real_namespace"])
    if recomputed != manifest:
        raise ValueError("T23 manifest binding mismatch or missing artifact")
    return {"status": "PASS", "binding_count": len(manifest["bindings"]),
            "semantic_root": manifest["semantic_root"],
            "raw_binding_root": manifest["raw_binding_root"]}


def seal_holdout(source_root: Path, material_root: Path, manifest: dict[str, Any], *,
                 real: bool) -> dict[str, Any]:
    out = Path(material_root) / "evaluations/t23"
    manifest_path = out / "holdout_manifest.json"
    write_json(manifest_path, manifest, exclusive=True)
    verify_manifest(source_root, material_root)
    identity = manifest["identity"]
    gate_sha = manifest["bindings"]["construction_gate"]["sha256"]
    marker = {
        "schema_version": "t23-holdout-frozen-v2", "experiment": "t23",
        "state": "SEALED", "workspace_mode": "REAL_EXPERIMENT" if real else "SYNTHETIC_DISPOSABLE",
        "material_mode": identity["material_mode"], "construction_authorized": real,
        "construction_attempts": 1, "candidate_rows_executed": 0,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "manifest_semantic_root": manifest["semantic_root"],
        "candidate_commit": identity["candidate_commit"],
        "candidate_tree": identity["candidate_tree"],
        "preconstruction_commit": identity["starting_preconstruction_commit"],
        "preconstruction_freeze_sha256": identity["preconstruction_freeze_sha256"],
        "component_root": identity["component_root"], "freeze_root": identity["freeze_root"],
        "construction_contract_sha256": identity["construction_contract_sha256"],
        "construction_gate_sha256": gate_sha,
        "author_lock_sha256": identity["author_lock_sha256"],
    }
    marker["semantic_root"] = sha256_json({k: v for k, v in marker.items()
                                            if k not in {"manifest_sha256", "semantic_root"}})
    write_json(out / "HOLDOUT_FROZEN", marker, exclusive=True)
    return marker


def verify_seal(source_root: Path, material_root: Path) -> dict[str, Any]:
    out = Path(material_root) / "evaluations/t23"
    marker = json.loads((out / "HOLDOUT_FROZEN").read_text(encoding="utf-8"))
    if marker.get("schema_version") != "t23-holdout-frozen-v2" or marker.get("state") != "SEALED":
        raise ValueError("T23 seal schema/state mismatch")
    manifest_path = out / "holdout_manifest.json"
    if marker.get("manifest_sha256") != hashlib.sha256(manifest_path.read_bytes()).hexdigest():
        raise ValueError("T23 seal manifest SHA mismatch")
    result = verify_manifest(source_root, material_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = manifest["identity"]
    expected = {
        "manifest_semantic_root": manifest["semantic_root"],
        "candidate_commit": identity["candidate_commit"],
        "candidate_tree": identity["candidate_tree"],
        "preconstruction_commit": identity["starting_preconstruction_commit"],
        "preconstruction_freeze_sha256": identity["preconstruction_freeze_sha256"],
        "component_root": identity["component_root"], "freeze_root": identity["freeze_root"],
        "construction_contract_sha256": identity["construction_contract_sha256"],
        "construction_gate_sha256": manifest["bindings"]["construction_gate"]["sha256"],
        "author_lock_sha256": identity["author_lock_sha256"],
    }
    if any(marker.get(k) != v for k, v in expected.items()):
        raise ValueError("T23 seal construction identity mismatch")
    if marker.get("semantic_root") != sha256_json({k: v for k, v in marker.items()
                                                    if k not in {"manifest_sha256", "semantic_root"}}):
        raise ValueError("T23 seal semantic root mismatch")
    if construction_state(material_root) != "SEALED":
        raise ValueError("T23 seal state machine mismatch")
    return {"status": "PASS", "bindings": result["binding_count"],
            "semantic_root": marker["semantic_root"]}
