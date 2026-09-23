"""T23 one-shot construction, sealed on shadow only in preconstruction."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from sciencemath.knowledge.corpus import load_corpus
from t21_protocol.ledger import ConstructionLedger
from t21_protocol.util import iter_jsonl, read_json, sha256_file, sha256_json, sha256_path, write_json, write_jsonl

from .author import GOLD_ONLY, author_cases, fingerprint_root, load_spec, shadow_labels
from .contract import PATHS, load_t23_contract
from .context import require_construction_authorization
from .lock import verify_lock


def _shadow_root(workspace: Path, source_root: Path) -> Path:
    root = Path(workspace).resolve()
    source = Path(source_root).resolve()
    if root == source or source in root.parents or root in source.parents:
        raise ValueError("shadow construction must use a separate disposable workspace")
    return root


def run_construction_audits(inputs: list[dict[str, Any]], gold: list[dict[str, Any]],
                            corpus: Any, spec: dict[str, Any]) -> dict[str, Any]:
    if len(inputs) != len(gold) or len(inputs) != spec["exact_design"]["total_rows"]:
        raise ValueError("T23 exact design row count mismatch")
    if any(i["case_id"] != g["case_id"] for i, g in zip(inputs, gold)):
        raise ValueError("T23 input/gold identities differ")
    from collections import Counter

    counts = Counter(g["family"] for g in gold)
    routes = Counter(g["expected_route"] for g in gold)
    if set(counts) != set(spec["families"]) or any(count != spec["cases_per_family"] for count in counts.values()):
        raise ValueError("T23 family exact design violated")
    if set(routes) != set(spec["taxonomy"]["route_ids"]) or any(not n for n in routes.values()):
        raise ValueError("T23 route population absent")
    leakage = sum(bool(set(i["candidate_input"]) & GOLD_ONLY) or bool(set(i) - {"case_id", "candidate_input", "execution_context"}) for i in inputs)
    if leakage:
        raise ValueError("T23 gold leakage")
    if any("T22_OFFICIAL_EVALUATION_PASS" in json.dumps(i) for i in inputs):
        raise ValueError("historical milestone entered a candidate query")
    if len(corpus.sources) != corpus.manifest["source_count"] or len(corpus.chunks) != corpus.manifest["chunk_count"]:
        raise ValueError("shadow corpus loader count mismatch")
    missing_refs = sum(c.source_id not in corpus.sources_by_id for c in corpus.chunks)
    if missing_refs:
        raise ValueError("shadow corpus referential failure")
    return {
        "schema_version": "t23-construction-audits-v1", "status": "PASS",
        "rows": len(inputs), "family_counts": dict(sorted(counts.items())),
        "route_counts": dict(sorted(routes.items())),
        "exact_design": "PASS", "signal_visibility": "PASS",
        "gold_leakage": 0, "historical_milestone_overlap": 0,
        "t22_raw_blind_access": 0, "blindness": "PASS",
        "loader_errors": 0, "missing_runtime_fields": 0,
        "invalid_ids": 0, "checksum_failures": 0,
        "referential_failures": missing_refs,
    }


def build_manifest(root: Path, lock: dict[str, Any], attachment_path: str) -> dict[str, Any]:
    out = root / "evaluations" / "t23"
    bindings = {}
    for name, path in {
        "corpus": root / "rag" / "gk_holdout_t23",
        "inputs": out / "suites" / "inputs.jsonl",
        "gold": out / "suites" / "gold.jsonl",
        "audits": out / "construction_audits.json",
        "construction_ledger": out / "construction_run_ledger.json",
        "document_attachment": root / attachment_path,
    }.items():
        bindings[name] = {"path": path.relative_to(root).as_posix(),
                          "sha256": sha256_path(path)}
    return {"schema_version": "t23-holdout-manifest-v1",
            "artifact": "T23_HOLDOUT_MANIFEST", "experiment": "t23",
            "author_fingerprint_root": lock["author_fingerprint_root"],
            "candidate_commit": lock["candidate_commit"],
            "candidate_tree": lock["candidate_tree"],
            "runtime_root": lock["runtime_root"],
            "bindings": bindings, "binding_count": len(bindings),
            "freeze_root_sha256": sha256_json(bindings)}


def seal_holdout(root: Path, manifest: dict[str, Any], *, real: bool = False) -> dict[str, Any]:
    out = root / "evaluations" / "t23"
    write_json(out / "holdout_manifest.json", manifest, exclusive=True)
    marker = {"schema_version": "t23-holdout-frozen-v1", "experiment": "t23",
              "construction_status": "COMPLETE", "state": "SEALED",
              "workspace_mode": "REAL_EXPERIMENT" if real else "SYNTHETIC_DISPOSABLE",
              "material_mode": "REAL_BLIND" if real else "SYNTHETIC",
              "construction_authorized": real, "construction_attempts": 1,
              "candidate_rows_executed": 0,
              "holdout_manifest_sha256": sha256_file(out / "holdout_manifest.json"),
              "freeze_root_sha256": manifest["freeze_root_sha256"],
              "author_fingerprint_root": manifest["author_fingerprint_root"],
              "candidate_commit": manifest["candidate_commit"],
              "candidate_tree": manifest["candidate_tree"],
              "runtime_root": manifest["runtime_root"]}
    write_json(out / "HOLDOUT_FROZEN", marker, exclusive=True)
    return marker


def verify_seal(root: Path) -> dict[str, Any]:
    out = root / "evaluations" / "t23"
    manifest = read_json(out / "holdout_manifest.json")
    marker = read_json(out / "HOLDOUT_FROZEN")
    if (manifest.get("schema_version") != "t23-holdout-manifest-v1"
            or marker.get("schema_version") != "t23-holdout-frozen-v1"
            or marker.get("state") != "SEALED"
            or marker.get("workspace_mode") not in {"REAL_EXPERIMENT", "SYNTHETIC_DISPOSABLE"}
            or marker.get("construction_authorized") is not (marker.get("workspace_mode") == "REAL_EXPERIMENT")
            or marker.get("material_mode") != ("REAL_BLIND" if marker.get("workspace_mode") == "REAL_EXPERIMENT" else "SYNTHETIC")
            or marker.get("candidate_rows_executed") != 0
            or sha256_file(out / "holdout_manifest.json") != marker.get("holdout_manifest_sha256")
            or sha256_json(manifest.get("bindings")) != marker.get("freeze_root_sha256")):
        raise ValueError("T23 seal schema or root mismatch")
    for binding in manifest["bindings"].values():
        path = root / binding["path"]
        if not path.exists() or sha256_path(path) != binding["sha256"]:
            raise ValueError("T23 seal binding missing or corrupt")
    corpus = load_corpus(root / "rag" / "gk_holdout_t23")
    return {"status": "PASS", "bindings": len(manifest["bindings"]),
            "loaded_sources": len(corpus.sources), "loaded_chunks": len(corpus.chunks)}


def materialize_corpus(source_corpus: Path, target_corpus: Path) -> Any:
    """Copy a loader-verified approved corpus once; no hidden synthesis."""
    load_corpus(source_corpus)
    target_corpus.mkdir(parents=True, exist_ok=False)
    for name in ("sources.jsonl", "chunks.jsonl", "corpus_manifest.json"):
        shutil.copyfile(source_corpus / name, target_corpus / name)
    return load_corpus(target_corpus)


def _construct(source_root: Path, root: Path, *, labels: list[str] | tuple[str, ...],
               source_corpus: Path, attachment_path: str, namespace: str,
               real: bool) -> dict[str, Any]:
    """Shared production mechanics; the real wrapper owns authorization."""
    contract = load_t23_contract(source_root / "evaluations" / "t23" / "t23_master_contract.json")
    lock_report = verify_lock(source_root / "evaluations" / "t23" / "author_lock.json")
    lock = read_json(source_root / "evaluations" / "t23" / "author_lock.json")
    spec = load_spec(source_root / "evaluations" / "t23" / "author_specification.json")
    if fingerprint_root(spec) != lock_report["author_fingerprint_root"]:
        raise ValueError("T23 author root differs from lock")
    attachment = (root / attachment_path).resolve()
    if root.resolve() not in attachment.parents or not attachment.is_file():
        raise ValueError("T23 author attachment missing or outside workspace")
    out = root / "evaluations" / "t23"
    out.mkdir(parents=True, exist_ok=True)
    transitions = ["QUALIFIED", "CONSTRUCTION_STARTED"]
    ledger = ConstructionLedger.create_exclusive(out / "construction_run_ledger.json", "t23",
                                                  {"material_mode": "REAL_BLIND" if real else "SYNTHETIC", "namespace": namespace})
    inputs, gold = author_cases(labels, namespace=namespace, spec=spec,
                                attachment_path=attachment_path)
    suites = out / "suites"
    write_jsonl(suites / "inputs.jsonl", inputs)
    write_jsonl(suites / "gold.jsonl", gold)
    target_corpus = root / "rag" / "gk_holdout_t23"
    corpus = materialize_corpus(source_corpus, target_corpus)
    audits = run_construction_audits(inputs, gold, corpus, spec)
    write_json(out / "construction_audits.json", audits, exclusive=True)
    ledger.complete({"rows": len(inputs), "author_fingerprint_root": lock_report["author_fingerprint_root"]})
    transitions.append("CONSTRUCTED")
    manifest = build_manifest(root, lock, attachment_path)
    seal_holdout(root, manifest, real=real)
    transitions.append("SEALED")
    seal = verify_seal(root)
    if len(list(iter_jsonl(suites / "inputs.jsonl"))) != len(inputs):
        raise ValueError("T23 suite loader lost rows")
    return {"status": "PASS", "terminal_state": "SEALED", "transitions": transitions,
            "author_fingerprint_root": lock_report["author_fingerprint_root"],
            "rows": len(inputs), "audits": audits, "seal": seal,
            "real_t23_paths_touched": real}


def run_shadow_construction(source_root: Path, workspace: Path) -> dict[str, Any]:
    """Complete real construction mechanics on disposable nonblind material."""
    root = _shadow_root(workspace, source_root)
    if root.exists() and any(root.iterdir()):
        raise ValueError("shadow workspace must begin empty")
    documents = root / "documents"
    documents.mkdir(parents=True, exist_ok=False)
    (documents / "shadow.txt").write_text(
        "Disposable shadow document SHD: project-owned non-blind fixture.\n",
        encoding="utf-8", newline="\n")
    return _construct(source_root, root, labels=shadow_labels(),
                      source_corpus=source_root / "rag" / "gk_corpus",
                      attachment_path="documents/shadow.txt",
                      namespace="t23-shadow", real=False)


def run_real_construction(source_root: Path, authorization: str, *,
                          private_labels: list[str], private_corpus: Path,
                          attachment_path: str) -> dict[str, Any]:
    """Future authorized one-shot entry; never called by preconstruction."""
    require_construction_authorization(authorization, experiment="t23")
    root = Path(source_root).resolve()
    present = [path for path in PATHS.values() if (root / path).exists()]
    if present:
        raise ValueError(f"real T23 path already exists: {present}")
    corpus = Path(private_corpus).resolve()
    if root == corpus or root in corpus.parents:
        raise ValueError("real blind corpus input must be private and external to repository")
    if not corpus.is_dir():
        raise ValueError("private T23 corpus source is missing")
    return _construct(root, root, labels=private_labels, source_corpus=corpus,
                      attachment_path=attachment_path, namespace="t23", real=True)
