"""T25 disposable E2E rehearsals: construction + evaluation on synthetic shadow material.

Two independent rehearsals run the complete public-safe lifecycle through the
private artifact store (construction → audits → gate → manifest → seal →
evaluation → receipts), each in its own disposable store and private workspace
outside the repository. Determinism is proved by comparing semantic digests and
artifact commitments across the two runs. No real T25 path or real private
namespace is touched, and no real blind material exists anywhere.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
import tempfile
from typing import Any

from t21_protocol.util import sha256_json

from .anchor_t24 import DIMENSIONS
from .construction import run_construction_pipeline, rehearsal_labels
from .contract import BASE_PRECONSTRUCTION_COMMIT, BASE_PRECONSTRUCTION_TREE
from .contract import SHADOW_NAMESPACE
from .freeze import build_freeze
from .ledgers import semantic_ledger_digest
from .store import PrivateArtifactStore
from .workspace import create_private_workspace, dispose_workspace

SHADOW_SCHEMA = "t25-shadow-lifecycle-v1"
SHADOW_STORE_IDENTITY = "T25-REHEARSAL-STORE-01"
ATTACK_FAMILIES = ("security_adversarial", "route_override_adversarial")


def _attachment_text() -> str:
    return "Disposable T25 shadow document SHD: project-owned non-blind fixture.\n"


def _corpus_bundle(source_root: Path) -> dict[str, Any]:
    """The public non-blind rehearsal corpus, materialized into store artifacts."""
    from sciencemath.knowledge.corpus import load_corpus

    corpus_dir = Path(source_root) / "rag" / "gk_corpus"
    corpus = load_corpus(corpus_dir)
    sources = [json.loads(line) for line in (corpus_dir / "sources.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks = [json.loads(line) for line in (corpus_dir / "chunks.jsonl")
              .read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = json.loads((corpus_dir / "corpus_manifest.json").read_text(encoding="utf-8"))
    if len(sources) != len(corpus.sources) or len(chunks) != len(corpus.chunks):
        raise ValueError("rehearsal corpus materialization lost rows")
    return {"sources": sources, "chunks": chunks, "manifest": manifest}


def run_shadow_construction(source_root: Path, store: PrivateArtifactStore, *,
                            freeze_document: dict[str, Any],
                            author_lock_sha256: str) -> dict[str, Any]:
    source_root = Path(source_root).resolve()
    return run_construction_pipeline(
        source_root, store, labels=rehearsal_labels(), namespace=SHADOW_NAMESPACE,
        real=False, author_lock_sha256=author_lock_sha256,
        attachment_text=_attachment_text(), corpus_bundle=_corpus_bundle(source_root),
        freeze_document=freeze_document)


def rehearsal_fingerprints(store: PrivateArtifactStore) -> dict[str, list[str]]:
    """Rehearsal-exclusive fingerprints, hash-only (section 26 discipline).

    Registers the disposable suite and attachment only. The rehearsal corpus is
    the public non-blind gk_corpus shared by design with qualification and the
    doctor, so its identities are deliberately NOT rehearsal-exclusive.
    """
    from .contract import canonical
    from .construction import ATTACHMENT_LOGICAL_ID
    from .exclusions import fingerprint

    inputs = store.read("suites/inputs.jsonl")
    gold = store.read("suites/gold.jsonl")
    if len(inputs) != len(gold) or not inputs:
        raise ValueError("rehearsal fingerprint extraction found no suites")
    attachment = store.read(ATTACHMENT_LOGICAL_ID)
    observed = {
        "case_ids": [fingerprint(row["case_id"]) for row in inputs],
        "exact_queries": [fingerprint(row["candidate_input"]["query"]) for row in inputs],
        "exact_answers": [fingerprint(canonical(row).decode("utf-8")) for row in gold],
        "exact_source_text": [fingerprint(attachment)],
        "verbatim_attack_wording": [
            fingerprint(row["candidate_input"]["query"])
            for row, expected in zip(inputs, gold)
            if expected["family"] in ATTACK_FAMILIES],
    }
    if set(observed) - set(DIMENSIONS) or "relations" in observed:
        raise ValueError("rehearsal fingerprint dimensions invalid")
    return observed


def run_rehearsal(source_root: Path, *, run_index: int, general_context: Any,
                  freeze_document: dict[str, Any],
                  author_lock_sha256: str) -> dict[str, Any]:
    """One full disposable lifecycle; the store and workspace are destroyed after."""
    from .evaluation import run_shadow_evaluation

    source_root = Path(source_root).resolve()
    base = Path(tempfile.mkdtemp(prefix=f"t25-rehearsal-{run_index}-"))
    store = PrivateArtifactStore(base / SHADOW_STORE_IDENTITY / SHADOW_NAMESPACE,
                                 store_identity=SHADOW_STORE_IDENTITY,
                                 namespace=SHADOW_NAMESPACE)
    workspace = None
    try:
        construction = run_shadow_construction(source_root, store,
                                                freeze_document=freeze_document,
                                                author_lock_sha256=author_lock_sha256)
        workspace, mount_report = create_private_workspace(
            source_root, store, purpose=f"rehearsal-{run_index}",
            freeze_document=freeze_document)
        evaluation = run_shadow_evaluation(source_root, store, workspace,
                                           general_context=general_context)
        evaluation_ledger = store.read("evaluation_run_ledger")
        return {
            "run": run_index,
            "status": "PASS" if construction["status"] == evaluation["status"] == "PASS"
            else "FAIL",
            "store_identity": SHADOW_STORE_IDENTITY,
            "namespace": SHADOW_NAMESPACE,
            "real_namespace_touched": False,
            "rows": construction["rows"],
            "construction_state": construction["state"],
            "construction_ledger_semantic_root": semantic_ledger_digest(
                construction["ledger"]),
            "construction_gate_checks": construction["gate"]["check_count"],
            "construction_gate_state": construction["gate"]["state"],
            "private_manifest_component_root": construction["manifest"][
                "private_artifact_component_root"],
            "private_holdout_root": construction["manifest"]["private_holdout_root"],
            "manifest_binding_count": construction["manifest"]["artifact_count"],
            "manifest_counts_by_class": construction["manifest"]["counts_by_class"],
            "seal_state": construction["seal"]["state"],
            "seal_workspace_mode": construction["seal"]["workspace_mode"],
            "public_construction_commitment": construction["public_construction_commitment"],
            "construction_publication_gate": construction["publication_gate"]["status"],
            "evaluation_state": evaluation["status"],
            "evaluation_ledger_semantic_root": semantic_ledger_digest(
                store.read("evaluation_run_ledger")),
            "evaluation_rows": evaluation["rows"],
            "router_metrics": evaluation["router_metrics"]["metrics"],
            "router_floor_pass_count": sum(1 for item in
                                           evaluation["router_metrics"]["floors"].values()
                                           if item["pass"]),
            "protected_t22_floors": evaluation["protected_t22_floors"],
            "provider_parity": evaluation["provider_parity"],
            "provider_initialization_rows": evaluation["provider_initialization_rows"],
            "firewall_counters": evaluation["firewall_counters"],
            "gold_firewall": evaluation["gold_firewall"],
            "evaluation_graph": evaluation["evaluation_graph"],
            "holdout_results_sha256": store.commitment(
                "evaluation/holdout_results.json")["canonical_sha256"],
            "router_metric_evidence_sha256": store.commitment(
                "evaluation/router_metric_evidence.json")["canonical_sha256"],
            "router_floor_evidence_sha256": store.commitment(
                "evaluation/router_floor_evidence.json")["canonical_sha256"],
            "workspace_mount_count": mount_report["mounted_count"],
            "workspace_outside_repository": mount_report["outside_repository"],
            "candidate_rows_executed": 0,
            "rehearsal_fingerprints": {name: sorted(set(values))
                                       for name, values
                                       in rehearsal_fingerprints(store).items()},
            "disposable_store_destroyed": True,
        }
    finally:
        if workspace is not None:
            dispose_workspace(workspace)
        shutil.rmtree(base, ignore_errors=True)


def rehearsal_determinism(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Construction, manifest, evaluation, metric, and graph determinism (section 35)."""
    construction_diff = int(
        first["construction_ledger_semantic_root"] != second["construction_ledger_semantic_root"]
        or first["rows"] != second["rows"]
        or first["construction_state"] != second["construction_state"])
    manifest_diff = int(
        first["private_manifest_component_root"] != second["private_manifest_component_root"]
        or first["private_holdout_root"] != second["private_holdout_root"]
        or first["public_construction_commitment"] != second["public_construction_commitment"])
    evaluation_diff = int(
        first["evaluation_ledger_semantic_root"] != second["evaluation_ledger_semantic_root"]
        or first["evaluation_rows"] != second["evaluation_rows"]
        or first["holdout_results_sha256"] != second["holdout_results_sha256"])
    metric_diff = int(
        first["router_metric_evidence_sha256"] != second["router_metric_evidence_sha256"]
        or first["router_floor_evidence_sha256"] != second["router_floor_evidence_sha256"]
        or first["router_metrics"] != second["router_metrics"]
        or first["router_floor_pass_count"] != second["router_floor_pass_count"]
        or first["protected_t22_floors"] != second["protected_t22_floors"])
    graph_diff = int(first["evaluation_graph"] != second["evaluation_graph"])
    return {"construction_semantic_diff": construction_diff,
            "manifest_commitment_diff": manifest_diff,
            "evaluation_semantic_diff": evaluation_diff,
            "metric_diff": metric_diff,
            "graph_diff": graph_diff}


def run_two_rehearsals(source_root: Path, *, general_context: Any,
                       author_lock_sha256: str) -> dict[str, Any]:
    """Two independent deterministic rehearsals; the freeze used is rehearsal-local."""
    source_root = Path(source_root).resolve()
    freeze_document = build_freeze(source_root)
    runs = []
    for index in (1, 2):
        print(f"T25 rehearsal {index}/2 starting", flush=True)
        runs.append(run_rehearsal(source_root, run_index=index, general_context=general_context,
                                  freeze_document=freeze_document,
                                  author_lock_sha256=author_lock_sha256))
        print(f"T25 rehearsal {index}/2 complete: {runs[-1]['status']}", flush=True)
    comparisons = rehearsal_determinism(runs[0], runs[1])
    fingerprints = runs[0]["rehearsal_fingerprints"]
    fingerprints_stable = all(runs[index]["rehearsal_fingerprints"] == fingerprints
                              for index in (1,))
    passed = all(run["status"] == "PASS" for run in runs) \
        and not any(comparisons.values()) \
        and fingerprints_stable \
        and all(run["real_namespace_touched"] is False for run in runs)
    return {"schema_version": SHADOW_SCHEMA, "artifact": "T25_PRODUCTION_SHADOW_LIFECYCLE",
            "experiment": "t25", "material": "DISPOSABLE_SYNTHETIC_NONBLIND",
            "real_construction_attempts": 0, "real_evaluation_attempts": 0,
            "real_blind_rows": 0,
            "rehearsal_store_identity": SHADOW_STORE_IDENTITY,
            "rehearsal_namespace": SHADOW_NAMESPACE,
            "infrastructure_commit": BASE_PRECONSTRUCTION_COMMIT,
            "infrastructure_tree": BASE_PRECONSTRUCTION_TREE,
            "runs": runs, "comparisons": comparisons,
            "rehearsal_fingerprints_registered": fingerprints_stable,
            "rehearsal_fingerprints": fingerprints,
            "status": "PASS" if passed else "FAIL"}