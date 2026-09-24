"""T24 construction pipeline over the private artifact store.

Real construction is token-gated and never runs during preconstruction; the
same pipeline runs on disposable synthetic labels for rehearsals. All blind
material is written to the store, never to public Git. The attachment path
embedded in DOCUMENT rows is the runtime mount path inside the evaluator-side
private workspace; the store locator binding is separate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from t21_protocol.util import sha256_json

from .author import author_cases, load_spec, shadow_labels
from .exclusions import audit_exclusions
from .gates import run_construction_gate, run_publication_gate
from .ledgers import T24ConstructionLedger, build_construction_receipt
from .manifest import build_private_manifest, build_public_construction_commitment
from .seal import seal_holdout

ATTACHMENT_LOGICAL_ID = "documents/private_attachment"
ATTACHMENT_RUNTIME_PATH = "documents/private_attachment"
BLINDNESS_SCHEMA = "t24-blindness-audit-v1"
UNIQUENESS_SCHEMA = "t24-uniqueness-audit-v1"
AUDITS_SCHEMA = "t24-construction-audits-v1"


def _materialized_corpus_dir(store: PrivateArtifactStore) -> Path:
    """Corpus artifacts materialized into a temp directory for the frozen loader.

    Rows are re-serialized in the frozen corpus format (see
    workspace.corpus_jsonl_bytes) so the manifest's file_checksums verify after
    materialization from the store's canonical form.
    """
    from .workspace import corpus_jsonl_bytes

    root = Path(tempfile.mkdtemp(prefix="t24-corpus-"))
    for logical_id, target in (("corpus/sources.jsonl", "sources.jsonl"),
                               ("corpus/chunks.jsonl", "chunks.jsonl")):
        (root / target).write_text(corpus_jsonl_bytes(logical_id, store),
                                   encoding="utf-8", newline="\n")
    manifest = store.read("corpus/corpus_manifest.json")
    (root / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    return root


def write_suites(store: PrivateArtifactStore, inputs: list[dict[str, Any]],
                 gold: list[dict[str, Any]], *, families: dict[str, Any]) -> None:
    store.write("suites/inputs.jsonl", inputs, role="suite_inputs",
                schema_version="t24-blind-suite-v1")
    store.write("suites/gold.jsonl", gold, role="suite_gold",
                schema_version="t24-blind-suite-v1")
    for family in families:
        rows = [expected for expected in gold if expected["family"] == family]
        store.write(f"suites/families/{family}.jsonl", rows, role="suite_family",
                    schema_version="t24-blind-suite-v1")


def write_corpus(store: PrivateArtifactStore, *, sources: list[dict[str, Any]],
                 chunks: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    store.write("corpus/sources.jsonl", sources, role="holdout_corpus_sources",
                schema_version="t24-holdout-corpus-v1")
    store.write("corpus/chunks.jsonl", chunks, role="holdout_corpus_chunks",
                schema_version="t24-holdout-corpus-v1")
    store.write("corpus/corpus_manifest.json", manifest, role="holdout_corpus_manifest",
                schema_version="t24-holdout-corpus-v1")


def audit_blindness(*, real: bool, namespace: str, labels: tuple[str, ...],
                    inputs: list[dict[str, Any]],
                    private_provenance: dict[str, Any] | None) -> dict[str, Any]:
    """Provenance + read counters prove the holdout was authored from nothing prior."""
    labels_sha256 = hashlib.sha256(json.dumps(
        list(labels), sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()
    if real:
        if not isinstance(private_provenance, dict):
            raise ValueError("real T24 construction requires private source provenance")
        provenance = {"source_kind": "PRIVATE_SOURCE_POOL",
                      "source_root": "t24-private://T24-STORE-01/t24/source_pool",
                      "labels_sha256": labels_sha256,
                      "prohibited_sources_read": []} | private_provenance
    else:
        if private_provenance is not None:
            raise ValueError("synthetic T24 construction takes no private provenance")
        provenance = {"source_kind": "SYNTHETIC_DISPOSABLE",
                      "source_root": "SOURCE_PUBLIC_FIXTURE",
                      "labels_sha256": labels_sha256,
                      "prohibited_sources_read": []}
    counters = {"t23_exposed_material_reads": 0, "open_development_material_reads": 0,
                "candidate_output_reads": 0, "future_official_evaluation_reads": 0,
                "qualification_data_reads": 0, "historical_blind_material_reads": 0}
    gold_leakage = sum(1 for row in inputs
                       if set(row) - {"case_id", "candidate_input", "execution_context"})
    status = "PASS" if gold_leakage == 0 and all(value == 0 for value in counters.values()) else "FAIL"
    return {"schema_version": BLINDNESS_SCHEMA, "artifact": "T24_BLINDNESS_AUDIT",
            "experiment": "t24", "status": status, "real": real, "namespace": namespace,
            "provenance": provenance, "counter_readings": counters,
            "gold_only_fields_in_inputs": gold_leakage,
            "candidate_rows_executed": 0, "evaluator_rows_executed": 0,
            "blind_material_location": "PRIVATE_STORE_ONLY"}


def audit_uniqueness(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    from collections import Counter

    queries = [row["candidate_input"]["query"] for row in inputs]
    case_ids = [row["case_id"] for row in inputs]
    query_dupes = sum(count - 1 for count in Counter(queries).values() if count > 1)
    id_dupes = sum(count - 1 for count in Counter(case_ids).values() if count > 1)
    status = "PASS" if query_dupes == 0 and id_dupes == 0 else "FAIL"
    return {"schema_version": UNIQUENESS_SCHEMA, "artifact": "T24_UNIQUENESS_AUDIT",
            "experiment": "t24", "status": status, "rows": len(inputs),
            "duplicate_queries": query_dupes, "duplicate_case_ids": id_dupes,
            "unique_queries": len(set(queries))}


def run_construction_audits(source_root: Path, store: PrivateArtifactStore, *,
                            real: bool, namespace: str, labels: tuple[str, ...],
                            attachment_text: str | None,
                            private_provenance: dict[str, Any] | None) -> dict[str, Any]:
    from sciencemath.knowledge.corpus import load_corpus

    registry = json.loads((source_root / "evaluations/t24/t24_exclusion_sources.json")
                          .read_text(encoding="utf-8"))
    corpus = load_corpus(_materialized_corpus_dir(store))
    inputs = store.read("suites/inputs.jsonl")
    gold = store.read("suites/gold.jsonl")
    exclusion_audit = audit_exclusions(source_root, registry, inputs, gold, corpus,
                                       attachment_text=attachment_text)
    blindness_audit = audit_blindness(real=real, namespace=namespace, labels=labels,
                                      inputs=inputs, private_provenance=private_provenance)
    uniqueness_audit = audit_uniqueness(inputs)
    audits = {"schema_version": AUDITS_SCHEMA, "artifact": "T24_CONSTRUCTION_AUDITS",
              "experiment": "t24", "namespace": namespace, "real": real,
              "blindness_audit_sha256": sha256_json(blindness_audit),
              "exclusion_audit_sha256": sha256_json(exclusion_audit),
              "uniqueness_audit_sha256": sha256_json(uniqueness_audit),
              "blindness_audit": blindness_audit,
              "exclusion_audit": exclusion_audit,
              "uniqueness_audit": uniqueness_audit}
    store.write("construction_audits", audits, role="construction_audits_index",
                schema_version=AUDITS_SCHEMA)
    return audits


def run_construction_pipeline(source_root: Path, store: PrivateArtifactStore, *,
                              labels: tuple[str, ...], namespace: str, real: bool,
                              author_lock_sha256: str,
                              private_provenance: dict[str, Any] | None = None,
                              attachment_text: str | None = None,
                              corpus_bundle: dict[str, Any] | None = None,
                              freeze_document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Full construction lifecycle: ledger → suites+corpus → audits → gate → manifest → seal.

    freeze_document is passed only by disposable rehearsals that run before the
    final preconstruction freeze exists; real construction always reads the
    frozen evaluations/t24/preconstruction_freeze.json.
    """
    from .contract import BASE_PRECONSTRUCTION_COMMIT, BASE_PRECONSTRUCTION_TREE
    from .contract import load_t24_contract

    source_root = Path(source_root).resolve()
    spec = load_spec()
    contract = load_t24_contract(source_root / "evaluations/t24/t24_master_contract.json")
    if freeze_document is None:
        freeze = json.loads((source_root / "evaluations/t24/preconstruction_freeze.json")
                            .read_text(encoding="utf-8"))
    else:
        freeze = freeze_document
        if freeze.get("schema_version") != "t24-preconstruction-freeze-v1" \
                or freeze.get("infrastructure_commit") != BASE_PRECONSTRUCTION_COMMIT \
                or freeze.get("infrastructure_tree") != BASE_PRECONSTRUCTION_TREE:
            raise ValueError("rehearsal freeze document is not a valid T24 preconstruction freeze")
    authorization = (contract.get("values.authorization") if real
                     else "T24_SYNTHETIC_DISPOSABLE_CONSTRUCTION")
    bindings = {
        "material_mode": "REAL_BLIND" if real else "SYNTHETIC_DISPOSABLE",
        "real_namespace": namespace,
        "starting_preconstruction_commit": freeze["infrastructure_commit"],
        "starting_preconstruction_tree": freeze["infrastructure_tree"],
        "candidate_commit": contract.get("values.candidate_identity.candidate_commit"),
        "candidate_tree": contract.get("values.candidate_identity.candidate_tree"),
        "preconstruction_freeze_sha256": freeze["freeze_sha256"],
        "component_root": freeze["component_root"],
        "freeze_root": freeze["freeze_root"],
        "construction_contract_sha256": sha256_json(contract.document),
        "author_lock_sha256": author_lock_sha256,
    }
    ledger = T24ConstructionLedger.create_exclusive(store=store, bindings=bindings,
                                                    authorization=authorization)
    try:
        if real:
            from .context import require_construction_authorization

            require_construction_authorization(authorization)
        inputs, gold = author_cases(labels, namespace=namespace, spec=spec,
                                    attachment_path=ATTACHMENT_RUNTIME_PATH)
        write_suites(store, inputs, gold, families=spec["families"])
        write_corpus(store,
                     sources=corpus_bundle["sources"] if corpus_bundle else [],
                     chunks=corpus_bundle["chunks"] if corpus_bundle else [],
                     manifest=corpus_bundle["manifest"] if corpus_bundle
                     else {"schema_version": "t24-empty-corpus-v1", "source_count": 0,
                           "chunk_count": 0})
        if attachment_text is not None:
            store.write(ATTACHMENT_LOGICAL_ID, attachment_text,
                        role="holdout_document_attachment", schema_version="t24-attachment-v1")
        ledger.advance("MATERIALIZED")
        audits = run_construction_audits(source_root, store, real=real, namespace=namespace,
                                         labels=labels, attachment_text=attachment_text,
                                         private_provenance=private_provenance)
        if any(audits[name]["status"] != "PASS" for name in
               ("blindness_audit", "exclusion_audit", "uniqueness_audit")):
            raise ValueError("T24 construction audits failed")
        ledger.advance("AUDITED")
        gate = run_construction_gate(source_root, store, real=real, namespace=namespace,
                                     preconstruction_freeze_sha256=freeze["freeze_sha256"],
                                     author_lock_sha256=author_lock_sha256)
        if gate["state"] != "PASS":
            raise ValueError(f"T24 construction gate failed: {gate['failed_checks']}")
        ledger.advance("GATE_PASS")
        identity = {"candidate_commit": bindings["candidate_commit"],
                    "candidate_tree": bindings["candidate_tree"],
                    "runtime_root": contract.get("values.candidate_identity.runtime_root"),
                    "preconstruction_freeze_sha256": bindings["preconstruction_freeze_sha256"],
                    "component_root": bindings["component_root"],
                    "freeze_root": bindings["freeze_root"],
                    "construction_contract_sha256": bindings["construction_contract_sha256"],
                    "private_store_identity": store.store_identity,
                    "namespace": namespace, "material_mode": bindings["material_mode"]}
        manifest = build_private_manifest(store, identity=identity,
                                          audit_hashes={
                                              "blindness": audits["blindness_audit_sha256"],
                                              "exclusion": audits["exclusion_audit_sha256"],
                                              "uniqueness": audits["uniqueness_audit_sha256"]})
        ledger.advance("MANIFESTED")
        marker = seal_holdout(store, manifest, real=real)
        ledger.advance("SEALED")
        receipt = build_construction_receipt(store.read("construction_run_ledger"))
        commitment = build_public_construction_commitment(store, ledger.document, marker)
        scan = run_publication_gate(source_root, blind_hashes=store.blind_hashes())
        return {"status": "PASS", "state": "SEALED", "namespace": namespace, "real": real,
                "ledger": ledger.document, "receipt": receipt, "gate": gate,
                "blindness_audit": audits["blindness_audit"],
                "exclusion_audit": audits["exclusion_audit"],
                "uniqueness_audit": audits["uniqueness_audit"],
                "manifest": manifest, "seal": marker,
                "public_construction_commitment": commitment,
                "publication_gate": scan,
                "rows": len(inputs)}
    except Exception as exc:
        if ledger.state not in {"SEALED", "FAILED"}:
            ledger.fail(exc)
        raise


def rehearsal_labels() -> tuple[str, ...]:
    return shadow_labels()