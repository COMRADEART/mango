"""T18.64 performance sample on a temporary local DB."""
from __future__ import annotations

import json
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.memory.pipeline import handle
from sciencemath.memory.store import MemoryStore

OUT = ROOT / "evaluations/t18/performance.json"


def _ms(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t18perf_"))
    db = tmp / "perf.sqlite"
    s = MemoryStore(db)
    writes, retr, upd, dele = [], [], [], []
    for i in range(40):
        writes.append(_ms(lambda i=i: handle(
            f"Remember that item {i} is value-{i}.",
            store=s, owner_id="p", scope_type="PROJECT", scope_id="perf",
            user_explicit=True, subject=f"item_{i}")))
        retr.append(_ms(lambda i=i: handle(
            f"item {i}", store=s, owner_id="p", scope_type="PROJECT",
            scope_id="perf")))
    upd.append(_ms(lambda: handle(
        "Correction: item 0 is value-x.",
        store=s, owner_id="p", scope_type="PROJECT", scope_id="perf",
        user_explicit=True, subject="item_0", op="MEMORY_SUPERSEDE")))
    last = s.list_scope(owner_id="p", scope_type="PROJECT", scope_id="perf")
    if last:
        dele.append(_ms(lambda: handle(
            "delete", store=s, owner_id="p", scope_type="PROJECT",
            scope_id="perf", memory_id=last[0].memory_id, op="MEMORY_DELETE")))
    s.close()
    t0 = time.perf_counter()
    s2 = MemoryStore(db)
    s2.close()
    open_ms = (time.perf_counter() - t0) * 1000
    size = db.stat().st_size if db.exists() else 0

    def p95(xs):
        if not xs:
            return None
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]

    doc = {
        "milestone": "T18.64 performance",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "write_ms_mean": statistics.mean(writes) if writes else None,
        "retrieval_ms_mean": statistics.mean(retr) if retr else None,
        "recall_p95_ms": p95(retr),
        "update_ms": upd[0] if upd else None,
        "delete_ms": dele[0] if dele else None,
        "database_open_ms": open_ms,
        "database_size_bytes": size,
        "ram": "not sampled",
        "vram": "CPU SQLite; VRAM unused",
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
