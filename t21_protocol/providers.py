"""Material and candidate providers with explicit real/synthetic identity."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .builder import build_real_rows, build_rows
from .context import MaterialMode, WorkspaceMode
from .errors import ProvenanceError
from .util import write_json, write_jsonl


@dataclass(frozen=True)
class MaterialBundle:
    rows_by_suite: dict[str, list[dict[str, Any]]]
    world: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    chunks: list[dict[str, Any]]


class MaterialProvider(Protocol):
    provider_id: str
    provider_kind: str
    material_mode: MaterialMode
    synthetic: bool
    placeholder_audits: bool

    def build(self, contract: Any, author_spec: dict[str, Any]) -> MaterialBundle: ...


class CandidateProvider(Protocol):
    provider_id: str
    provider_kind: str
    synthetic: bool

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class SyntheticMaterialProvider:
    provider_id = "qualification-synthetic-material-v1"
    provider_kind = "SYNTHETIC_FIXTURE"
    material_mode = MaterialMode.SYNTHETIC
    synthetic = True
    placeholder_audits = False

    def build(self, contract: Any, author_spec: dict[str, Any]) -> MaterialBundle:
        rows_by_suite = build_rows(contract, author_spec)
        domains = author_spec["canonical_domains"]
        world = [
            {"record_type": "entity", "entity_id": f"syn-ent-{index:02d}", "name": f"Synthetic {domain}", "domain": domain}
            for index, domain in enumerate(domains)
        ]
        sources = [
            {"source_id": f"syn-src-{index:02d}", "topic_tags": [domain], "title": f"Synthetic {domain}"}
            for index, domain in enumerate(domains)
        ]
        chunks = [
            {
                "chunk_id": f"syn-src-{index:02d}:chunk-0",
                "source_id": f"syn-src-{index:02d}",
                "text": f"Synthetic {domain} evidence for qualification answers.",
                "metadata": {"fact_entity": f"syn-ent-{index:02d}", "fact_attribute": "QUALIFICATION_VALUE"},
            }
            for index, domain in enumerate(domains)
        ]
        return MaterialBundle(rows_by_suite, world, sources, chunks)


class RealBlindMaterialProvider:
    provider_id = "contract-real-blind-author-v1"
    provider_kind = "REAL_AUTHOR"
    material_mode = MaterialMode.REAL_BLIND
    synthetic = False
    placeholder_audits = False

    def build(self, contract: Any, author_spec: dict[str, Any]) -> MaterialBundle:
        rows_by_suite = build_real_rows(contract, author_spec)
        rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
        world: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        chunks: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            domain = row["gold"]["required_domains"][0]
            entity_id = f"r15-ent-{index:05d}"
            source_id = row["gold"]["source_ids"][0]
            chunk_id = row["gold"]["chunk_ids"][0]
            answer = row["gold"]["expected_answer"]
            world.append({"record_type": "entity", "entity_id": entity_id, "name": f"R15 blind entity {index:05d}", "domain": domain})
            sources.append({"source_id": source_id, "topic_tags": row["gold"]["required_domains"], "title": f"R15 blind register {index:05d}"})
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "source_id": source_id,
                    "text": f"Blind record {row['case_id']} states the registered value {answer}.",
                    "metadata": {"fact_entity": entity_id, "fact_attribute": "REGISTERED_VALUE", "fact_value": answer},
                }
            )
        return MaterialBundle(rows_by_suite, world, sources, chunks)


class RealDryRunMaterialProvider(RealBlindMaterialProvider):
    provider_id = "disposable-real-mode-dry-run-v1"
    provider_kind = "REAL_DRY_RUN_AUTHOR"
    material_mode = MaterialMode.REAL_DRY_RUN


class SyntheticCandidateProvider:
    provider_id = "qualification-stub-candidate-v1"
    provider_kind = "SYNTHETIC_CANDIDATE"
    synthetic = True

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "case_id": row["case_id"],
                "status": row["gold"]["expect_status"],
                "answer": row["gold"].get("expected_answer"),
                "counters": {},
            }
            for row in rows
        ]


class FileCandidateProvider:
    provider_id = "official-candidate-output-file-v1"
    provider_kind = "REAL_CANDIDATE"
    synthetic = False

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        del rows
        return list(self.rows)


def validate_material_provider(
    provider: MaterialProvider, workspace_mode: WorkspaceMode, *, qualification_rehearsal: bool = False
) -> None:
    if provider.placeholder_audits:
        raise ProvenanceError("placeholder audit provider rejected")
    if workspace_mode == WorkspaceMode.SYNTHETIC_DISPOSABLE:
        if not provider.synthetic or provider.material_mode != MaterialMode.SYNTHETIC:
            raise ProvenanceError("synthetic workspace requires synthetic material provider")
        return
    if provider.synthetic or provider.provider_kind == "SYNTHETIC_FIXTURE":
        raise ProvenanceError("synthetic material provider rejected in REAL_EXPERIMENT mode")
    if qualification_rehearsal:
        if provider.material_mode not in {MaterialMode.REAL_BLIND, MaterialMode.REAL_DRY_RUN}:
            raise ProvenanceError("real-mode rehearsal provider has invalid material mode")
    elif provider.material_mode != MaterialMode.REAL_BLIND or provider.provider_kind != "REAL_AUTHOR":
        raise ProvenanceError("production construction requires the real blind author")


def validate_candidate_provider(provider: CandidateProvider, workspace_mode: WorkspaceMode) -> None:
    if workspace_mode == WorkspaceMode.REAL_EXPERIMENT and (
        provider.synthetic or provider.provider_kind != "REAL_CANDIDATE"
    ):
        raise ProvenanceError("stub, synthetic, or mock candidate rejected in REAL_EXPERIMENT mode")
    if workspace_mode == WorkspaceMode.SYNTHETIC_DISPOSABLE and not provider.synthetic:
        raise ProvenanceError("synthetic workspace requires synthetic candidate provider")


def materialize_bundle(root: Path, contract: Any, bundle: MaterialBundle) -> dict[str, Any]:
    corpus = root / "rag" / f"gk_holdout_{contract.experiment}"
    corpus.mkdir(parents=True, exist_ok=False)
    write_jsonl(corpus / "world.jsonl", bundle.world)
    write_jsonl(corpus / "sources.jsonl", bundle.sources)
    write_jsonl(corpus / "chunks.jsonl", bundle.chunks)
    manifest = {
        "schema_version": "t21-corpus-v1",
        "world": len(bundle.world),
        "sources": len(bundle.sources),
        "chunks": len(bundle.chunks),
    }
    write_json(corpus / "corpus_manifest.json", manifest, exclusive=True)
    suite_root = root / "evaluations" / contract.experiment / "suites"
    counts: dict[str, int] = {}
    from .util import sha256_json

    for suite_name, rows in bundle.rows_by_suite.items():
        target = suite_root / suite_name
        target.mkdir(parents=True, exist_ok=False)
        counts[suite_name] = write_jsonl(target / "holdout.jsonl", rows)
        write_json(
            target / "manifest.json",
            {"schema_version": "t21-suite-v1", "suite": suite_name, "rows": len(rows), "rows_root": sha256_json(rows)},
            exclusive=True,
        )
    return {"corpus": manifest, "suite_counts": counts}
