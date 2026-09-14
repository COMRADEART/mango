"""T17.50 performance snapshot from FINAL eval wall times."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    fin = json.loads(
        (ROOT / "evaluations/t17/runs/t17-final/summary.json").read_text(
            encoding="utf-8"))
    doc = fin.get("document") or {}
    data = fin.get("data_core") or {}
    n_doc = int(doc.get("n") or fin.get("n_document") or 0)
    n_data = int(data.get("n") or fin.get("n_data") or 0)
    wall_doc = float(doc.get("wall_s") or 0)
    wall_data = float(data.get("wall_s") or 0)
    out = {
        "milestone": "T17.50 performance",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "document_n": n_doc,
        "data_n": n_data,
        "document_wall_s": wall_doc,
        "data_wall_s": wall_data,
        "document_mean_ms": round(1000 * wall_doc / n_doc, 3) if n_doc else None,
        "data_mean_ms": round(1000 * wall_data / n_data, 3) if n_data else None,
        "vram": "unused (CPU-only mechanical FINAL)",
        "network_requests": 0,
        "paid_compute": "NOT_USED",
        "note": "Correctness over speed. Mechanical parsers; no GPU FINAL.",
    }
    dest = ROOT / "evaluations/t17/performance.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
