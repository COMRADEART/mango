"""T21.53 — performance measurement for the knowledge RAG runtime.

Measures, on the frozen corpus (rag/gk_corpus, manifest checksum
944d4504...):
- index build: wall time and on-disk corpus size;
- retrieval: p50/p95 latency over the full frozen retrieval-suite question
  set (floor: p95 <= 500 ms);
- end-to-end answer_knowledge: p50/p95 latency over a deterministic
  question sample;
- process RSS after the run.

Deterministic; local only; no network, no paid compute.
Output: evaluations/t21/performance.json.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402
from sciencemath.knowledge.retrieval import retrieve  # noqa: E402

SUITES_DIR = ROOT / "evaluations" / "t21" / "suites"
OUT_PATH = ROOT / "evaluations" / "t21" / "performance.json"
P95_FLOOR_MS = 500.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(q / 100.0 * len(s) + 0.5)) - 1))
    return s[idx]


def load_rows(suite: str, split: str) -> list[dict]:
    path = SUITES_DIR / suite / f"{split}.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rss_bytes() -> int:
    try:
        import psutil
        return psutil.Process().memory_info().rss
    except Exception:  # noqa: BLE001
        try:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        except Exception:  # noqa: BLE001
            return 0


def main() -> int:
    corpus_dir = ROOT / "rag" / "gk_corpus"
    corpus_bytes = sum(p.stat().st_size for p in corpus_dir.rglob("*")
                       if p.is_file())

    t0 = time.perf_counter()
    corpus = load_corpus()
    build_s = time.perf_counter() - t0

    retrieval_rows = load_rows("mango-general-retrieval-v1", "final") \
        + load_rows("mango-general-retrieval-v1", "dev")
    ret_ms: list[float] = []
    for row in retrieval_rows:
        t = time.perf_counter()
        retrieve(corpus.index, corpus.chunks_by_id,
                 row["request"]["query"], top_k=8)
        ret_ms.append((time.perf_counter() - t) * 1000.0)

    answer_rows = (load_rows("mango-general-knowledge-rag-v1", "final")[:40]
                   + load_rows("mango-general-abstention-v1", "final")[:20]
                   + load_rows("mango-general-multihop-v1", "final")[:20])
    e2e_ms: list[float] = []
    for row in answer_rows:
        t = time.perf_counter()
        answer_knowledge(row["request"]["query"], corpus)
        e2e_ms.append((time.perf_counter() - t) * 1000.0)

    perf = {
        "milestone": "T21.53 performance measurement",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "manifest_checksum": corpus.manifest.get("manifest_checksum"),
            "on_disk_bytes": corpus_bytes,
            "sources": corpus.manifest.get("source_count"),
            "chunks": corpus.manifest.get("chunk_count"),
        },
        "index_build_seconds": round(build_s, 3),
        "retrieval_ms": {
            "n": len(ret_ms),
            "p50": round(percentile(ret_ms, 50), 2),
            "p95": round(percentile(ret_ms, 95), 2),
            "floor_p95_ms": P95_FLOOR_MS,
            "pass": percentile(ret_ms, 95) <= P95_FLOOR_MS,
        },
        "end_to_end_ms": {
            "n": len(e2e_ms),
            "p50": round(percentile(e2e_ms, 50), 2),
            "p95": round(percentile(e2e_ms, 95), 2),
        },
        "rss_bytes": rss_bytes(),
        "gpu": {"used": False, "reason": "deterministic lexical pipeline; "
                                         "no model inference in the runtime"},
    }
    perf["pass"] = perf["retrieval_ms"]["pass"]
    OUT_PATH.write_text(json.dumps(perf, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(perf, indent=2))
    return 0 if perf["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())