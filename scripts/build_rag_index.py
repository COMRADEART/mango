"""T5 RAG index builder (implements the T0 stub).

Embeds rag/corpus/*.jsonl with the selected local embedding model and
writes a vector index to rag/index/ behind the abstracted VectorStore
interface (FAISS first; swappable). Also writes:
  rag/embeddings/embedding_manifest.json — model/revision/license/
      dimension/normalization/hardware/throughput (T5.7)
  rag/index/index_manifest.json — corpus version, embedding revision,
      chunk/vector counts, dimension, checksum, build timestamp,
      source/domain distribution (T5.8/T5.16)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sciencemath.rag.embeddings import CANDIDATES, SentenceTransformerEmbedder  # noqa: E402
from sciencemath.rag.retriever import load_corpus  # noqa: E402
from sciencemath.rag.vectorstore import (build_index_manifest, make_store,  # noqa: E402
                                         finalize_index_manifest, file_sha256)
from sciencemath.utils.io_utils import load_json, load_yaml, write_json  # noqa: E402

CORPUS_DIR = REPO_ROOT / "rag" / "corpus"
INDEX_DIR = REPO_ROOT / "rag" / "index"
EMB_DIR = REPO_ROOT / "rag" / "embeddings"

# the T5.7 evaluation (scripts/eval_embeddings.py) writes its decision here
DECISION_PATH = EMB_DIR / "embedding_decision.json"


def chosen_spec() -> tuple[str, str]:
    """Embedding model chosen by measured evaluation (decision file if
    present, else the config default)."""
    cfg = load_yaml(REPO_ROOT / "configs" / "rag.yaml")
    if DECISION_PATH.exists():
        dec = load_json(DECISION_PATH)
        # 'winner' is the CANDIDATES key ('e5-small-v2'); 'model' field
        # would be the HF id ('intfloat/e5-small-v2')
        return dec["winner"], (dec.get("winner_revision")
                               or dec.get("revision") or "")
    spec = cfg["embedding"]["model"]
    return spec, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", default="cpu",
                    help="cpu (default; GPU stays with the reasoner) | cuda")
    ap.add_argument("--engine", default=None,
                    help="override configs/rag.yaml retrieval.vector_store")
    args = ap.parse_args()

    chunks, corpus_manifest = load_corpus(CORPUS_DIR)
    key, revision = chosen_spec()
    # resolve full spec (revision pinned at embed time if unset)
    spec = CANDIDATES.get(key) or next(
        (s for s in CANDIDATES.values() if s.model == key), None)
    if spec is None:
        print(f"embedding model {key!r} not in evaluated candidates",
              file=sys.stderr)
        return 90
    if revision:
        from dataclasses import replace
        spec = replace(spec, revision=revision)
    embedder = SentenceTransformerEmbedder(spec, device=args.device)

    cfg = load_yaml(REPO_ROOT / "configs" / "rag.yaml")
    engine = args.engine or cfg["retrieval"]["vector_store"]
    ids = sorted(chunks)
    texts = [chunks[i]["text"] for i in ids]

    t0 = time.perf_counter()
    vectors = embedder.embed_passages(texts)
    embed_s = time.perf_counter() - t0
    store = make_store(engine, vectors.shape[1])
    store.add(vectors, ids)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_path = INDEX_DIR / f"index_{engine}.faiss"
    store.save(index_path)

    source_dist: dict[str, int] = {}
    domain_dist: dict[str, int] = {}
    for i in ids:
        r = chunks[i]
        source_dist[r["source_id"]] = source_dist.get(r["source_id"], 0) + 1
        domain_dist[r["domain"]] = domain_dist.get(r["domain"], 0) + 1

    manifest = build_index_manifest(
        corpus_version=corpus_manifest["corpus_version"],
        corpus_checksum=corpus_manifest.get("corpus_checksum", ""),
        embedding_model=spec.model,
        embedding_revision=spec.revision,
        engine=engine,
        index_path=index_path,
        chunk_count=len(ids),
        source_distribution=source_dist,
        domain_distribution=domain_dist,
        build_seconds=time.perf_counter() - t0)
    manifest = finalize_index_manifest(manifest, dimension=store.dimension,
                                       vector_count=len(store))

    emb_manifest = {
        "manifest_version": "1.0.0",
        "model": spec.model,
        "revision": spec.revision or None,   # None = unpinned (record later)
        "license": spec.license,
        "dimension": store.dimension,
        "normalization": spec.normalize,
        "query_prefix": spec.query_prefix,
        "device": args.device,
        "batch_size": embedder.batch_size,
        "throughput_passages_per_s": round(len(texts) / embed_s, 1),
        "notes": spec.notes,
        "candidates_evaluated": sorted(CANDIDATES),
    }
    write_json(EMB_DIR / "embedding_manifest.json", emb_manifest)
    write_json(INDEX_DIR / "index_manifest.json", manifest)
    print(json.dumps({"engine": engine, "vectors": len(store),
                      "dimension": store.dimension,
                      "checksum": manifest["checksum"],
                      "embed_seconds": round(embed_s, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())