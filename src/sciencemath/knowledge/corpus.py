"""Frozen knowledge-corpus loading with manifest verification.

The corpus lives at rag/gk_corpus/ (sources.jsonl, chunks.jsonl,
corpus_manifest.json). The loader refuses to serve if any file checksum
fails — fail-closed provenance, mirroring the T5R corpus loader. The
corpus is project-owned fixture material (see corpus_manifest.json
licensing summary); T21 must not ingest user documents or live web text.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from sciencemath.knowledge.index import BM25Index
from sciencemath.knowledge.schema import (
    KnowledgeChunk,
    KnowledgeSourceRecord,
    chunk_checksum,
    chunk_source_text,
    validate_chunk_invariants,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = ROOT / "rag" / "gk_corpus"
CORPUS_SNAPSHOT_DATE = "2026-01-31"


class CorruptCorpusError(RuntimeError):
    """Corpus content does not match its frozen manifest."""


def _sha256_lf(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


@dataclass
class KnowledgeCorpus:
    """Loaded, verified, frozen corpus view."""

    sources: list[KnowledgeSourceRecord]
    chunks: list[KnowledgeChunk]
    manifest: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        problems = validate_chunk_invariants(self.chunks)
        if problems:
            raise CorruptCorpusError("; ".join(problems[:5]))
        self.chunks_by_id = {c.chunk_id: c for c in self.chunks}
        self.sources_by_id = {s.source_id: s for s in self.sources}
        self.index = BM25Index(self.chunks)

    @property
    def snapshot_date(self) -> str:
        return self.manifest.get("snapshot_date", CORPUS_SNAPSHOT_DATE)

    def chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        return self.chunks_by_id.get(chunk_id)

    def source(self, source_id: str) -> KnowledgeSourceRecord | None:
        return self.sources_by_id.get(source_id)


def _load_sources(path: Path) -> list[KnowledgeSourceRecord]:
    records: list[KnowledgeSourceRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        records.append(KnowledgeSourceRecord(
            source_id=row["source_id"],
            source_title=row["source_title"],
            source_type=row["source_type"],
            source_uri_or_origin=row["source_uri_or_origin"],
            publisher_or_collection=row["publisher_or_collection"],
            license=row["license"],
            revision_or_version=row["revision_or_version"],
            retrieved_at_or_snapshot_date=row[
                "retrieved_at_or_snapshot_date"],
            language=row["language"],
            authority_class=row["authority_class"],
            freshness_class=row["freshness_class"],
            topic_tags=list(row.get("topic_tags") or []),
            content_text=row.get("content_text", ""),
            content_hash=row["content_hash"],
            document_hash=row["document_hash"],
        ))
    return records


def _load_chunks(path: Path) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        chunks.append(KnowledgeChunk.from_dict(json.loads(line)))
    return chunks


def load_corpus(corpus_dir: Path | None = None) -> KnowledgeCorpus:
    """Load the frozen corpus; verify every checksum against the manifest."""
    base = corpus_dir or CORPUS_DIR
    sources_path = base / "sources.jsonl"
    chunks_path = base / "chunks.jsonl"
    manifest_path = base / "corpus_manifest.json"
    for p in (sources_path, chunks_path, manifest_path):
        if not p.exists():
            raise CorruptCorpusError(f"missing corpus file: {p}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("file_checksums") or {}
    if not expected or not all(
            name in expected for name in ("sources.jsonl", "chunks.jsonl")):
        # Fail closed (T21R10): a manifest without per-file checksums cannot
        # prove provenance, so it must never be served.
        raise CorruptCorpusError("manifest lacks file_checksums entries for "
                                 "sources.jsonl and chunks.jsonl")
    for name, want in expected.items():
        got = _sha256_lf(base / name)
        if got != want:
            raise CorruptCorpusError(
                f"{name} checksum mismatch: manifest={want} actual={got}")
    sources = _load_sources(sources_path)
    chunks = _load_chunks(chunks_path)
    if manifest.get("source_count") != len(sources):
        raise CorruptCorpusError("source_count mismatch")
    if manifest.get("chunk_count") != len(chunks):
        raise CorruptCorpusError("chunk_count mismatch")
    return KnowledgeCorpus(sources=sources, chunks=chunks,
                           manifest=manifest)


def build_corpus_files(
    base: Path,
    sources: list[KnowledgeSourceRecord],
    chunks: list[KnowledgeChunk],
    *, snapshot_date: str = CORPUS_SNAPSHOT_DATE,
) -> dict:
    """Write sources.jsonl / chunks.jsonl / corpus_manifest.json and return
    the manifest. Deterministic: sorted writes, content-derived checksums."""
    base.mkdir(parents=True, exist_ok=True)
    sources_path = base / "sources.jsonl"
    chunks_path = base / "chunks.jsonl"

    def write_jsonl(path: Path, rows: list[dict]) -> None:
        text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False)
                       + "\n" for r in rows)
        path.write_text(text, encoding="utf-8", newline="\n")

    write_jsonl(sources_path, [s.to_dict() for s in sources])
    write_jsonl(chunks_path, [c.to_dict() for c in chunks])
    domains = sorted({tag for s in sources for tag in s.topic_tags})
    manifest = {
        "corpus_version": "mango-general-knowledge-corpus-v1",
        "snapshot_date": snapshot_date,
        "source_count": len(sources),
        "chunk_count": len(chunks),
        "domains": domains,
        "license_summary": {
            "project_owned_fixtures": len(sources),
            "notes": "Corpus is project-owned evaluation fixture material "
                     "(CC0-equivalent); retrieval-only, never used for "
                     "training; no third-party text ingested.",
        },
        "file_checksums": {
            "sources.jsonl": _sha256_lf(sources_path),
            "chunks.jsonl": _sha256_lf(chunks_path),
        },
    }
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    manifest["manifest_checksum"] = hashlib.sha256(
        blob.encode("utf-8")).hexdigest()
    (base / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    return manifest


def verify_content_hashes(
    sources: list[KnowledgeSourceRecord],
    chunks: list[KnowledgeChunk],
) -> list[str]:
    """Recompute content hashes; any mismatch is a corpus integrity failure."""
    problems: list[str] = []
    for s in sources:
        if s.content_hash != source_record_hash(s):
            problems.append(f"source content hash mismatch {s.source_id}")
    for c in chunks:
        if c.content_hash != chunk_checksum(c.text):
            problems.append(f"chunk checksum mismatch {c.chunk_id}")
    return problems