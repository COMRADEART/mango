"""Preregistered T21R12 blind-world materializer.

The future blind author supplies an offline private specification.  This
script validates and atomically materializes it without importing any Mango
runtime component.  It is intentionally inert until explicit post-audit
authorization; this preregistration phase never calls ``main``.

T21R12 repair: the emitted corpus_manifest.json is runtime-compatible with
the frozen ``sciencemath.knowledge.corpus.load_corpus`` loader (the T21R9
sealed holdout's construction-only manifest was a pre-exposure
infrastructure failure).  The manifest carries source_count, chunk_count,
and file_checksums under the frozen loader's LF-normalized SHA-256 policy;
construction-only metadata is retained but every runtime-required field is
authoritative.  Runtime compatibility itself is only proven by the actual
``load_corpus`` gate on a disposable synthetic corpus before blind
construction is authorized (see t21r12_preconstruction.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "rag" / "gk_holdout_t21r12"
DISPOSABLE_PREFIX = "pre12q-"
AUTHORIZATION_PHRASE = "T21R12_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
CORPUS_VERSION = "mango-general-knowledge-corpus-v1"
BLIND_NAMESPACE = "mango-r12b-v1"

# Literal copies of the frozen runtime closed vocabularies (schema.py).  The
# builder stays runtime-independent; a duplicate-literal drift would be
# caught by the actual load_corpus compatibility gate, not silently.
AUTHORITY_CLASSES = frozenset((
    "PRIMARY_REFERENCE", "ENCYCLOPEDIC", "ACADEMIC_REFERENCE",
    "GOVERNMENT_PUBLICATION", "INSTITUTIONAL", "GENERAL_REFERENCE",
    "UNKNOWN",
))
FRESHNESS_CLASSES = frozenset((
    "STATIC", "SLOW_CHANGING", "TIME_SENSITIVE", "UNKNOWN",
))
SOURCE_RUNTIME_FIELDS = (
    "source_id", "source_title", "source_type", "source_uri_or_origin",
    "publisher_or_collection", "license", "revision_or_version",
    "retrieved_at_or_snapshot_date", "language", "authority_class",
    "freshness_class", "topic_tags", "content_hash", "document_hash",
)
CHUNK_RUNTIME_FIELDS = (
    "chunk_id", "source_id", "section", "text", "ordinal", "span",
    "metadata", "content_hash",
)


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_lf(value: bytes) -> str:
    """Frozen runtime policy: corpus.py _sha256_lf (CRLF normalized to LF)."""
    return _sha_bytes(value.replace(b"\r\n", b"\n"))


def validate_world_spec(specification: dict, *, qualification_disposable: bool = False) -> dict:
    if specification.get("namespace") != BLIND_NAMESPACE:
        raise ValueError("world specification is outside the frozen R12 namespace")
    required = {"world", "sources", "chunks"}
    missing = sorted(required - set(specification))
    if missing:
        raise ValueError(f"world specification missing {missing}")
    world = specification["world"]
    sources = specification["sources"]
    chunks = specification["chunks"]
    if not all(isinstance(records, list) for records in (world, sources, chunks)):
        raise ValueError("world, sources, and chunks must be lists")
    source_ids = [str(source.get("source_id") or "") for source in sources]
    chunk_ids = [str(chunk.get("chunk_id") or "") for chunk in chunks]
    if not source_ids or not chunk_ids:
        raise ValueError("real blind world must contain sources and chunks")
    if len(source_ids) != len(set(source_ids)) or \
            len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("source and chunk IDs must be unique")
    identifiers = source_ids + chunk_ids + [
        str(row.get("entity_id") or "") for row in world]
    if (not qualification_disposable and
            any(DISPOSABLE_PREFIX in value.casefold() for value in identifiers)):
        raise ValueError("disposable pre11q identities are forbidden in blind data")
    if any(not value.startswith("gk-") for value in source_ids):
        raise ValueError("every source_id must use the gk- prefix so "
                         "citation provenance cannot collide with the T5R corpus")
    for source in sources:
        missing_fields = [field for field in SOURCE_RUNTIME_FIELDS
                          if field not in source]
        if missing_fields:
            raise ValueError(f"source {source.get('source_id')} lacks "
                             f"runtime fields {missing_fields}")
        if source["authority_class"] not in AUTHORITY_CLASSES:
            raise ValueError(f"source {source.get('source_id')} has an "
                             f"unknown authority_class: "
                             f"{source['authority_class']!r}")
        if source["freshness_class"] not in FRESHNESS_CLASSES:
            raise ValueError(f"source {source.get('source_id')} has an "
                             f"unknown freshness_class: "
                             f"{source['freshness_class']!r}")
    source_set = set(source_ids)
    for chunk in chunks:
        missing_fields = [field for field in CHUNK_RUNTIME_FIELDS
                          if field not in chunk]
        if missing_fields:
            raise ValueError(f"chunk {chunk.get('chunk_id')} lacks runtime "
                             f"fields {missing_fields}")
        if str(chunk.get("source_id") or "") not in source_set:
            raise ValueError(f"chunk source does not resolve: {chunk.get('chunk_id')}")
        if chunk.get("content_hash") != _sha_bytes(
                str(chunk.get("text") or "").encode("utf-8")):
            raise ValueError(f"chunk content_hash does not match text: "
                             f"{chunk.get('chunk_id')}")
        span = chunk.get("span") or []
        if (not isinstance(span, list) or len(span) != 2
                or span[0] != 0 or span[1] != len(str(chunk.get("text") or ""))):
            raise ValueError(f"chunk span is not [0, len(text)]: "
                             f"{chunk.get('chunk_id')}")
        if not isinstance(chunk.get("ordinal"), int):
            raise ValueError(f"chunk ordinal is not an integer: "
                             f"{chunk.get('chunk_id')}")
        metadata = chunk.get("metadata") or {}
        for field in ("fact_entity", "fact_attribute", "fact_value"):
            if field not in metadata:
                raise ValueError(f"chunk lacks structured {field}: "
                                 f"{chunk.get('chunk_id')}")
    return {"world": len(world), "sources": len(sources),
            "chunks": len(chunks)}


def runtime_manifest(sources_path: Path, chunks_path: Path,
                     sources: list[dict], counts: dict) -> dict:
    """Emit a manifest in the frozen runtime's exact schema (T21R9 repair).

    Matches corpus.py build_corpus_files checksum semantics byte for byte:
    LF-normalized SHA-256 per file, manifest_checksum over the canonical
    sorted-key JSON of the manifest without its own checksum.  Construction
    metadata is additive; the frozen loader safely ignores it.
    """
    domains = sorted({str(tag) for source in sources
                      for tag in (source.get("topic_tags") or [])})
    licenses: dict[str, int] = {}
    for source in sources:
        license_id = str(source.get("license") or "UNKNOWN")
        licenses[license_id] = licenses.get(license_id, 0) + 1
    manifest = {
        "corpus_version": CORPUS_VERSION,
        "snapshot_date": "T21R12-BLIND",
        "source_count": counts["sources"],
        "chunk_count": counts["chunks"],
        "domains": domains,
        "license_summary": {
            "licenses": licenses,
            "notes": "Blind holdout material must remain retrieval-only "
                     "project-owned evaluation fixture content; no "
                     "third-party text ingested.",
        },
        "file_checksums": {
            "sources.jsonl": _sha256_lf(sources_path.read_bytes()),
            "chunks.jsonl": _sha256_lf(chunks_path.read_bytes()),
        },
        "artifact": "T21R12_BLIND_CORPUS_MANIFEST",
        "runtime_rows_executed": 0,
    }
    # Frozen build_corpus_files() semantics: the checksum covers the complete
    # manifest minus its own manifest_checksum key.
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    manifest["manifest_checksum"] = _sha_bytes(blob.encode("utf-8"))
    return manifest


def materialize_world(specification: dict, output: Path, *,
                      qualification_disposable: bool = False) -> dict:
    """Materialize an authorized world or an explicitly disposable rehearsal.

    The command-line construction path never enables the qualification flag.
    Only the non-blind preconstruction harness may use it, and its output lives
    in a temporary directory that is deleted before qualification completes.
    """
    counts = validate_world_spec(
        specification, qualification_disposable=qualification_disposable)
    if output.exists():
        raise FileExistsError(f"refusing to replace existing world: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="t21r12-world-", dir=output.parent))
    try:
        for name in ("world", "sources", "chunks"):
            payload = b"".join(_canonical_bytes(row)
                               for row in specification[name])
            (temporary / f"{name}.jsonl").write_bytes(payload)
        manifest = runtime_manifest(
            temporary / "sources.jsonl", temporary / "chunks.jsonl",
            specification["sources"], counts)
        manifest_bytes = json.dumps(
            manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        (temporary / "corpus_manifest.json").write_bytes(manifest_bytes)
        os.replace(temporary, output)
    except BaseException:
        for path in temporary.glob("*"):
            path.unlink(missing_ok=True)
        temporary.rmdir()
        raise
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--authorization", required=True)
    arguments = parser.parse_args()
    if arguments.authorization != AUTHORIZATION_PHRASE:
        raise SystemExit("T21R12 blind construction is not authorized")
    specification = json.loads(arguments.private_spec.read_text(
        encoding="utf-8"))
    manifest = materialize_world(specification, arguments.output)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
