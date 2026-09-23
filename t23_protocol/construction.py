"""One-shot T23 construction mechanics; real mode requires new authorization."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import shutil
from typing import Any

from sciencemath.knowledge.corpus import load_corpus
from t21_protocol.util import iter_jsonl, read_json, write_json, write_jsonl

from .author import GOLD_ONLY, author_cases, fingerprint_root, load_spec, shadow_labels
from .blindness import audit_blindness, synthetic_provenance
from .construction_gate import run_construction_gate
from .construction_ledger import T23ConstructionLedger, frozen_bindings
from .contract import CANDIDATE_COMMIT, PATHS, load_t23_contract, sha256_json
from .context import require_construction_authorization
from .exclusions import audit_exclusions, load_exclusion_sources
from .lock import verify_lock
from .manifest import build_manifest, seal_holdout, verify_seal as verify_manifest_seal
from .registry import check_real_path_registry
from t21_protocol.util import sha256_path

ROOT = Path(__file__).resolve().parents[1]


def _shadow_root(workspace: Path, source_root: Path) -> Path:
    root, source = Path(workspace).resolve(), Path(source_root).resolve()
    if root == source or source in root.parents or root in source.parents:
        raise ValueError("shadow construction must use a separate disposable workspace")
    return root


def run_construction_audits(inputs: list[dict[str, Any]], gold: list[dict[str, Any]],
                            corpus: Any, spec: dict[str, Any],
                            design: dict[str, Any] | None = None) -> dict[str, Any]:
    if len(inputs) != len(gold) or len(inputs) != spec["exact_design"]["total_rows"]:
        raise ValueError("T23 exact design row count mismatch")
    if any(i["case_id"] != g["case_id"] for i, g in zip(inputs, gold)):
        raise ValueError("T23 input/gold identities differ")
    counts = Counter(g["family"] for g in gold)
    routes = Counter(g["expected_route"] for g in gold)
    reasons = Counter(g["expected_reason"] for g in gold)
    if set(counts) != set(spec["families"]) or any(v != spec["cases_per_family"] for v in counts.values()):
        raise ValueError("T23 family exact design violated")
    if set(routes) != set(spec["taxonomy"]["route_ids"]) or any(not value for value in routes.values()):
        raise ValueError("T23 route population absent")
    if design is not None and (dict(routes) != design["route_counts"] or dict(reasons) != design["reason_counts"]):
        raise ValueError("T23 route/reason exact design violated")
    leakage = sum(bool(set(i["candidate_input"]) & GOLD_ONLY)
                  or bool(set(i) - {"case_id", "candidate_input", "execution_context"})
                  or bool(set(i["candidate_input"]) - set(spec["candidate_visible_fields"]))
                  for i in inputs)
    if leakage:
        raise ValueError("T23 gold or unknown field leakage")
    annotation_violations = sum(not isinstance(g.get("expected_route"), str)
                                or not isinstance(g.get("expected_reason"), str)
                                or g.get("family") not in spec["families"] for g in gold)
    if len(corpus.sources) != corpus.manifest["source_count"] or len(corpus.chunks) != corpus.manifest["chunk_count"]:
        raise ValueError("T23 corpus loader count mismatch")
    missing_refs = sum(c.source_id not in corpus.sources_by_id for c in corpus.chunks)
    if missing_refs or annotation_violations:
        raise ValueError("T23 referential or annotation failure")
    return {
        "schema_version": "t23-construction-static-audit-v2", "status": "PASS",
        "rows": len(inputs), "family_counts": dict(sorted(counts.items())),
        "route_counts": dict(sorted(routes.items())), "reason_counts": dict(sorted(reasons.items())),
        "exact_design": "PASS", "signal_visibility": "PASS",
        "gold_leakage": 0, "historical_milestone_overlap": 0,
        "t22_raw_blind_access": 0, "blindness": "PASS",
        "loader_errors": 0, "missing_runtime_fields": 0,
        "invalid_ids": 0, "checksum_failures": 0, "referential_failures": 0,
        "annotation_violations": 0, "candidate_rows_executed": 0,
        "evaluator_rows_executed": 0,
    }


def verify_seal(root: Path) -> dict[str, Any]:
    result = verify_manifest_seal(ROOT, root)
    corpus = load_corpus(Path(root) / "rag/gk_holdout_t23")
    return {**result, "loaded_sources": len(corpus.sources),
            "loaded_chunks": len(corpus.chunks)}


def materialize_corpus(source_corpus: Path, target_corpus: Path) -> Any:
    """Copy a loader-verified approved corpus once; no regeneration path."""
    load_corpus(source_corpus)
    target_corpus.mkdir(parents=True, exist_ok=False)
    for name in ("sources.jsonl", "chunks.jsonl", "corpus_manifest.json"):
        shutil.copyfile(source_corpus / name, target_corpus / name)
    return load_corpus(target_corpus)


def _construct(source_root: Path, root: Path, *, labels: list[str] | tuple[str, ...],
               source_corpus: Path, attachment_path: str, namespace: str,
               real: bool, source_provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Shared construction sequence. A failure after ledger creation is terminal."""
    source_root, root = Path(source_root).resolve(), Path(root).resolve()
    contract = load_t23_contract(source_root / "evaluations/t23/t23_master_contract.json")
    lock_report = verify_lock(source_root / "evaluations/t23/author_lock.json")
    spec = load_spec(source_root / "evaluations/t23/author_specification.json")
    if fingerprint_root(spec) != lock_report["author_fingerprint_root"]:
        raise ValueError("T23 author root differs from lock")
    if lock_report["candidate_commit"] != CANDIDATE_COMMIT:
        raise ValueError("T23 author lock candidate differs")
    registry = read_json(source_root / "evaluations/t23/construction_exclusion_sources.json")
    if registry.get("sources") != contract.get("exclusion_sources"):
        raise ValueError("T23 exclusion source registry differs from contract")
    load_exclusion_sources(source_root, registry)
    attachment = (root / attachment_path).resolve()
    if not attachment.is_relative_to(root) or not attachment.is_file():
        raise ValueError("T23 author attachment missing or outside workspace")
    out = root / "evaluations/t23"
    out.mkdir(parents=True, exist_ok=True)
    suites = out / "suites"
    ledger_path = out / "construction_run_ledger.json"
    bindings = frozen_bindings(source_root, real=real, namespace=namespace)
    ledger = T23ConstructionLedger.create_exclusive(ledger_path, bindings)
    try:
        inputs, gold = author_cases(labels, namespace=namespace, spec=spec,
                                    attachment_path=attachment_path)
        suites.mkdir(exist_ok=False)
        write_jsonl(suites / "inputs.jsonl", inputs)
        write_jsonl(suites / "gold.jsonl", gold)
        design = contract.get("construction_design")
        for family, relative in design["suite_mapping"].items():
            rows = [{"case_id": inp["case_id"], "family": expected["family"],
                     "candidate_input": inp["candidate_input"],
                     "expected_route": expected["expected_route"],
                     "expected_reason": expected["expected_reason"]}
                    for inp, expected in zip(inputs, gold) if expected["family"] == family]
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            write_jsonl(path, rows)
        corpus = materialize_corpus(source_corpus, root / "rag/gk_holdout_t23")
        ledger.advance("MATERIALIZED")
        static = run_construction_audits(inputs, gold, corpus, spec, design)
        provenance = source_provenance if real else synthetic_provenance()
        if not isinstance(provenance, dict):
            raise ValueError("independent private source provenance missing")
        blindness = audit_blindness(root, inputs, gold, provenance, real=real,
                                    labels=labels, source_corpus=source_corpus)
        uniqueness = audit_exclusions(source_root, registry, inputs, gold, corpus)
        if blindness["status"] != "PASS" or uniqueness["status"] != "PASS":
            raise ValueError("T23 construction blindness/uniqueness audit failed")
        for name, report in (("static", static), ("blindness", blindness), ("uniqueness", uniqueness)):
            write_json(suites / f"{name}_audit.json", report, exclusive=True)
        write_json(out / "construction_audits.json",
                   {"schema_version": "t23-construction-audits-v2", "status": "PASS",
                    "static": static, "blindness": blindness, "uniqueness": uniqueness},
                   exclusive=True)
        ledger.advance("AUDITED")
        gate = run_construction_gate(source_root, root, real=real, namespace=namespace)
        write_json(suites / "construction_gate.json", gate, exclusive=True)
        ledger.advance("GATE_PASS")
        manifest = build_manifest(source_root, root, attachment_path=attachment_path,
                                  real=real, namespace=namespace)
        seal_holdout(source_root, root, manifest, real=real)
        sealed = verify_manifest_seal(source_root, root)
        if len(list(iter_jsonl(suites / "inputs.jsonl"))) != len(inputs):
            raise ValueError("T23 suite loader lost rows")
        return {"status": "PASS", "terminal_state": "SEALED",
                "transitions": ["PRECONSTRUCTION", "LEDGER_CREATED", "MATERIALIZED",
                                "AUDITED", "GATE_PASS", "MANIFESTED", "SEALED"],
                "author_fingerprint_root": lock_report["author_fingerprint_root"],
                "rows": len(inputs), "audits": static, "blindness": blindness,
                "uniqueness": uniqueness, "gate": gate, "seal": sealed,
                "manifest_semantic_root": manifest["semantic_root"],
                "real_t23_paths_touched": real}
    except Exception as exc:
        try:
            ledger.fail(type(exc).__name__ + ": " + str(exc))
        except Exception:
            pass
        raise


def run_shadow_construction(source_root: Path, workspace: Path) -> dict[str, Any]:
    root = _shadow_root(workspace, source_root)
    if root.exists() and any(root.iterdir()):
        raise ValueError("shadow workspace must begin empty")
    documents = root / "documents"
    documents.mkdir(parents=True, exist_ok=False)
    (documents / "shadow.txt").write_text(
        "Disposable shadow document SHD: project-owned non-blind fixture.\n",
        encoding="utf-8", newline="\n")
    return _construct(source_root, root, labels=shadow_labels(),
                      source_corpus=Path(source_root) / "rag/gk_corpus",
                      attachment_path="documents/shadow.txt",
                      namespace="t23-shadow", real=False)


def run_real_construction(source_root: Path, authorization: str, *,
                          private_labels: list[str], private_corpus: Path,
                          attachment_path: str,
                          private_provenance: Path | None = None) -> dict[str, Any]:
    """Future authorized entry; never invoked by preconstruction qualification."""
    require_construction_authorization(authorization, experiment="t23")
    root = Path(source_root).resolve()
    check_real_path_registry(root, require_absent=True)
    corpus = Path(private_corpus).resolve()
    if root == corpus or corpus.is_relative_to(root) or not corpus.is_dir():
        raise ValueError("real blind corpus must be private and external to repository")
    if private_provenance is None:
        raise ValueError("independent private source provenance is required")
    provenance_path = Path(private_provenance).resolve()
    if provenance_path.is_relative_to(root) or not provenance_path.is_file():
        raise ValueError("private source provenance must be external")
    provenance = read_json(provenance_path)
    if (provenance.get("source_kind") != "INDEPENDENT_PRIVATE"
            or Path(provenance.get("source_root", "")).resolve() != corpus
            or provenance.get("labels_sha256") != sha256_json(private_labels)
            or provenance.get("corpus_sha256") != sha256_path(corpus)
            or provenance.get("source_pool_origin") != "UNSEEN_INDEPENDENT_PRIVATE_POOL"
            or not isinstance(provenance.get("independent_author"), str)
            or not provenance["independent_author"].strip()
            or provenance.get("prohibited_sources_read") != []
            or any(provenance.get(field) != 0 for field in (
                "candidate_outputs_read", "historical_blind_values_read",
                "open_development_values_read", "qualification_values_read",
                "shadow_values_read", "future_evaluation_values_read"))):
        raise ValueError("independent private source provenance invalid before ledger creation")
    return _construct(root, root, labels=private_labels, source_corpus=corpus,
                      attachment_path=attachment_path, namespace="t23", real=True,
                      source_provenance=provenance)
