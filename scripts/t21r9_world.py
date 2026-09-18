"""Preregistered T21R9 blind-world materializer.

The future blind author supplies an offline private specification.  This
script validates and atomically materializes it without importing any Mango
runtime component.  It is intentionally inert until explicit post-audit
authorization; this preregistration phase never calls ``main``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "rag" / "gk_holdout_t21r9"
DISPOSABLE_PREFIX = "pre9q-"
AUTHORIZATION_PHRASE = "T21R9_BLIND_CONSTRUCTION_AUTHORIZED"


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_world_spec(specification: dict) -> dict:
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
    if any(value.casefold().startswith(DISPOSABLE_PREFIX) for value in identifiers):
        raise ValueError("disposable pre9q identities are forbidden in blind data")
    source_set = set(source_ids)
    for chunk in chunks:
        if str(chunk.get("source_id") or "") not in source_set:
            raise ValueError(f"chunk source does not resolve: {chunk.get('chunk_id')}")
        metadata = chunk.get("metadata") or {}
        for field in ("fact_entity", "fact_attribute", "fact_value"):
            if field not in metadata:
                raise ValueError(f"chunk lacks structured {field}: "
                                 f"{chunk.get('chunk_id')}")
    return {"world": len(world), "sources": len(sources),
            "chunks": len(chunks)}


def materialize_world(specification: dict, output: Path) -> dict:
    counts = validate_world_spec(specification)
    if output.exists():
        raise FileExistsError(f"refusing to replace existing world: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="t21r9-world-", dir=output.parent))
    try:
        hashes: dict[str, str] = {}
        for name in ("world", "sources", "chunks"):
            payload = b"".join(_canonical_bytes(row)
                               for row in specification[name])
            path = temporary / f"{name}.jsonl"
            path.write_bytes(payload)
            hashes[path.name] = _sha_bytes(payload)
        manifest = {
            "artifact": "T21R9_BLIND_CORPUS_MANIFEST",
            "counts": counts,
            "files_sha256": hashes,
            "runtime_rows_executed": 0,
        }
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
        raise SystemExit("T21R9 blind construction is not authorized")
    specification = json.loads(arguments.private_spec.read_text(
        encoding="utf-8"))
    manifest = materialize_world(specification, arguments.output)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
