"""Material and candidate providers with explicit real/synthetic identity."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .builder import build_real_rows, build_real_rows_runtime_native, build_rows
from .context import MaterialMode, WorkspaceMode
from .errors import ProvenanceError
from .util import write_json, write_jsonl

RUNTIME_NATIVE_CORPUS_FORMAT = "mango-general-knowledge-corpus-v1"
RUNTIME_NATIVE_MATERIALIZER = "t21_protocol.providers:runtime-native-materializer"
RUNTIME_NATIVE_CANDIDATE = "t21_protocol.providers:RealCandidateProvider"


@dataclass(frozen=True)
class MaterialBundle:
    rows_by_suite: dict[str, list[dict[str, Any]]]
    world: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    runtime_sources: tuple[Any, ...] = ()
    runtime_chunks: tuple[Any, ...] = ()
    runtime_native: bool = False

    @property
    def is_runtime_native(self) -> bool:
        return self.runtime_native and bool(self.runtime_sources) and bool(self.runtime_chunks)


def contract_runtime_native(contract: Any) -> dict[str, Any] | None:
    try:
        return contract.get("runtime_native")
    except KeyError:
        return None


def _contract_root(contract: Any) -> Path:
    return contract.path.resolve().parents[2]


def runtime_modules(root: Path) -> tuple[Any, Any, Any]:
    """Import the frozen candidate runtime modules (lazy: src layout).

    The runtime is imported, never copied: schema, corpus loader, and
    answer pipeline are the frozen candidate bytes themselves."""
    src = str((root / "src").resolve())
    if src not in sys.path:
        sys.path.insert(0, src)
    import sciencemath.knowledge.corpus as corpus_module
    import sciencemath.knowledge.pipeline as pipeline_module
    import sciencemath.knowledge.schema as schema_module

    return schema_module, corpus_module, pipeline_module


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
        if contract_runtime_native(contract) is None:
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
        # Runtime-native contracts (T21R16): even disposable qualification
        # material is produced by the frozen runtime producers and materialized
        # through the frozen corpus writer, so the frozen loader can load it.
        # There is no second, qualification-only corpus model.
        schema, corpus_module, _ = runtime_modules(_contract_root(contract))
        world: list[dict[str, Any]] = []
        runtime_sources: list[Any] = []
        runtime_chunks: list[Any] = []
        evidence_by_domain: dict[str, tuple[Any, Any]] = {}
        for index, domain in enumerate(domains):
            entity_id = f"syn-ent-{index:02d}"
            world.append({"record_type": "entity", "entity_id": entity_id, "name": f"Synthetic {domain}", "domain": domain})
            evidence = f"Synthetic {domain} evidence for qualification answers."
            source = schema.KnowledgeSourceRecord(
                source_id=schema.make_source_id(f"Synthetic {domain}", "Qualification synthetic register", "synthetic-v1"),
                source_title=f"Synthetic {domain}",
                source_type="fixture_register",
                source_uri_or_origin=f"synthetic://{domain}",
                publisher_or_collection="Qualification synthetic register",
                license="project_owned_fixtures",
                revision_or_version="synthetic-v1",
                retrieved_at_or_snapshot_date=corpus_module.CORPUS_SNAPSHOT_DATE,
                language="en",
                authority_class="GENERAL_REFERENCE",
                freshness_class="STATIC",
                topic_tags=[domain],
                content_text=evidence,
            )
            chunk = schema.chunk_source_text(source, [("record", evidence)])[0]
            chunk.metadata = {
                **chunk.metadata,
                "fact_entity": entity_id,
                "fact_attribute": "QUALIFICATION_VALUE",
            }
            evidence_by_domain[domain] = (source, chunk)
            runtime_sources.append(source)
            runtime_chunks.append(chunk)
        for suite_rows in rows_by_suite.values():
            for row in suite_rows:
                source, chunk = evidence_by_domain[row["gold"]["required_domains"][0]]
                row["gold"]["source_ids"] = [source.source_id]
                row["gold"]["chunk_ids"] = [chunk.chunk_id]
        return MaterialBundle(
            rows_by_suite, world, [source.to_dict() for source in runtime_sources], [chunk.to_dict() for chunk in runtime_chunks],
            runtime_sources=tuple(runtime_sources),
            runtime_chunks=tuple(runtime_chunks),
            runtime_native=True,
        )


class RealBlindMaterialProvider:
    provider_id = "contract-real-blind-author-v1"
    provider_kind = "REAL_AUTHOR"
    material_mode = MaterialMode.REAL_BLIND
    synthetic = False
    placeholder_audits = False

    def build(self, contract: Any, author_spec: dict[str, Any]) -> MaterialBundle:
        runtime_native = contract_runtime_native(contract) is not None
        rows_by_suite = (
            build_real_rows_runtime_native(contract, author_spec)
            if runtime_native
            else build_real_rows(contract, author_spec)
        )
        rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
        if runtime_native:
            return self._build_runtime_native(contract, rows_by_suite, rows)
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

    def _build_runtime_native(
        self, contract: Any, rows_by_suite: dict[str, list[dict[str, Any]]], rows: list[dict[str, Any]]
    ) -> MaterialBundle:
        """R16 blind author -> runtime-native materializer.

        The author emits semantic facts only. Every runtime-affecting field is
        produced by the frozen schema's own producers: source IDs by
        make_source_id over the authored identity, chunk IDs by make_chunk_id,
        chunk structure by chunk_source_text, record hashes by the frozen
        __post_init__. Gold source/chunk references are filled from those
        frozen producers during construction (never at evaluation time)."""
        schema, corpus_module, _ = runtime_modules(_contract_root(contract))
        snapshot = corpus_module.CORPUS_SNAPSHOT_DATE
        world: list[dict[str, Any]] = []
        runtime_sources: list[Any] = []
        runtime_chunks: list[Any] = []
        for index, row in enumerate(rows):
            case_id = row["case_id"]
            statement = row["gold"]["expected_answer"]
            value = statement.removeprefix(f"Blind record {case_id} states the registered value ").removesuffix(".")
            # The fact entity IS the blind record: the frozen entity gate
            # requires every fact-entity token to appear in the query, and the
            # authored query names the record by case_id.
            entity_id = case_id
            world.append({"record_type": "entity", "entity_id": entity_id, "name": f"R16 blind entity {index:05d}", "domain": row["gold"]["required_domains"][0]})
            source = schema.KnowledgeSourceRecord(
                source_id=schema.make_source_id(f"R16 blind register {index:05d}", "Mango blind evaluation register", "r16-blind-v1"),
                source_title=f"R16 blind register {index:05d}",
                source_type="fixture_register",
                source_uri_or_origin=f"blind://{contract.experiment}/{case_id}",
                publisher_or_collection="Mango blind evaluation register",
                license="project_owned_fixtures",
                revision_or_version="r16-blind-v1",
                retrieved_at_or_snapshot_date=corpus_module.CORPUS_SNAPSHOT_DATE,
                language="en",
                authority_class="PRIMARY_REFERENCE",
                freshness_class="STATIC",
                topic_tags=list(row["gold"]["required_domains"]),
                content_text=statement,
            )
            chunk = schema.chunk_source_text(source, [("record", statement)])[0]
            chunk.metadata = {
                **chunk.metadata,
                "fact_entity": entity_id,
                "fact_attribute": "REGISTERED_VALUE",
                "fact_value": value,
            }
            row["gold"]["source_ids"] = [source.source_id]
            row["gold"]["chunk_ids"] = [chunk.chunk_id]
            runtime_sources.append(source)
            runtime_chunks.append(chunk)
        sources = [source.to_dict() for source in runtime_sources]
        chunks = [chunk.to_dict() for chunk in runtime_chunks]
        return MaterialBundle(
            rows_by_suite, world, sources, chunks,
            runtime_sources=tuple(runtime_sources),
            runtime_chunks=tuple(runtime_chunks),
            runtime_native=True,
        )


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


def canonical_candidate_row(case_id: str, answer: Any) -> dict[str, Any]:
    """Registered canonical serialization of a frozen-runtime answer.

    Purely re-serializing: the citation markers the runtime itself reports
    are removed from the composed answer text (the official gold contract is
    citation-free); status, zero-tolerance counters, and citation records
    pass through unchanged. No candidate semantics are added or altered."""
    text = answer.answer
    for citation in answer.citations:
        text = text.replace(f" [{citation['citation_id']}]", "")
    return {
        "case_id": case_id,
        "status": answer.status,
        "answer": text.strip(),
        "counters": dict(answer.zero_tolerance),
        "citations": [dict(citation) for citation in answer.citations],
    }


def direct_runtime_outputs(root: Path, corpus_dir: Path, rows: list[dict[str, Any]], *, top_k: int = 8) -> list[dict[str, Any]]:
    """Direct frozen-runtime execution over an already-loaded corpus format.

    Used only by parity/compatibility checks: loads the corpus with the
    frozen loader, runs the frozen answer entry point per row, and maps each
    answer through the same registered canonical serialization."""
    _, corpus_module, pipeline_module = runtime_modules(root)
    corpus = corpus_module.load_corpus(corpus_dir)
    return [
        canonical_candidate_row(row["case_id"], pipeline_module.answer_knowledge(row["query"], corpus, top_k=top_k))
        for row in rows
    ]


class RealCandidateProvider:
    """Frozen production candidate for runtime-native experiments.

    Delegates directly to the already-frozen Mango runtime entry point
    (answer_knowledge) over a corpus loaded by the frozen loader. No new
    candidate semantics: initialization loads the corpus exactly once and
    never executes holdout questions; generate() maps each frozen runtime
    KnowledgeAnswer through the registered canonical serialization."""

    provider_id = RUNTIME_NATIVE_CANDIDATE
    provider_kind = "REAL_CANDIDATE"
    synthetic = False

    def __init__(self, root: Path, corpus_dir: Path, *, top_k: int = 8):
        self.corpus_dir = Path(corpus_dir)
        self.top_k = top_k
        self.rows_executed = 0
        _, corpus_module, pipeline_module = runtime_modules(root)
        self._corpus_module = corpus_module
        self._pipeline_module = pipeline_module
        self.corpus = corpus_module.load_corpus(self.corpus_dir)

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        outputs = [
            canonical_candidate_row(
                row["case_id"], self._pipeline_module.answer_knowledge(row["query"], self.corpus, top_k=self.top_k)
            )
            for row in rows
        ]
        self.rows_executed += len(outputs)
        return outputs


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


def materialize_bundle_runtime_native(
    root: Path, contract: Any, bundle: MaterialBundle
) -> dict[str, Any]:
    """Runtime-native materialization: the frozen runtime writes the corpus.

    No T21-specific corpus writer runs. sources.jsonl, chunks.jsonl, and
    corpus_manifest.json (per-file checksums + manifest checksum) are
    produced by the frozen build_corpus_files, and the frozen load_corpus
    validates the materialized result fail-closed before any suite is
    written."""
    if not bundle.is_runtime_native:
        raise ProvenanceError("runtime-native materialization requires a runtime-native bundle")
    corpus = root / "rag" / f"gk_holdout_{contract.experiment}"
    corpus.mkdir(parents=True, exist_ok=False)
    write_jsonl(corpus / "world.jsonl", bundle.world)
    _, corpus_module, _ = runtime_modules(root)
    manifest = corpus_module.build_corpus_files(corpus, list(bundle.runtime_sources), list(bundle.runtime_chunks))
    corpus_module.load_corpus(corpus)
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
    return {
        "corpus": manifest,
        "suite_counts": counts,
        "corpus_format": RUNTIME_NATIVE_CORPUS_FORMAT,
        "materializer": RUNTIME_NATIVE_MATERIALIZER,
        "runtime_loader_validated": True,
    }


def materialize_bundle(root: Path, contract: Any, bundle: MaterialBundle) -> dict[str, Any]:
    if bundle.is_runtime_native:
        return materialize_bundle_runtime_native(root, contract, bundle)
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
