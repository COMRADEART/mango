"""T16.28 — free live-web smoke test (Wikipedia REST). Never fake success."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.web.live_provider import WikipediaLiveProvider
from sciencemath.web.pipeline import research
from sciencemath.web.limits import FREE_NETWORK

QUERIES = [
    "Planck constant",
    "Public Records Act",
    "Python (programming language)",
    "National Institute of Standards and Technology",
    "HTTP",
    "JSON",
    "Newton's laws of motion",
    "Speed of light",
    "Wikipedia",
    "Qwen (language model)",
    "Retrieval-augmented generation",
    "Helium",
    "Chief executive officer",
    "European Union",
    "Frankfurt",
]


def main() -> int:
    out = ROOT / "evaluations/t16/live_smoke.json"
    enabled = os.environ.get("MANGO_WEB_LIVE", "1") == "1"
    prov = WikipediaLiveProvider(enabled=enabled, timeout_s=10.0)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    if not enabled:
        doc = {
            "status": "LIVE_PROVIDER_UNAVAILABLE",
            "reason": "MANGO_WEB_LIVE!=1",
            "provider": prov.provider_name,
            "paid_or_free": "free",
            "cost_class": FREE_NETWORK,
            "operational_provider": False,
            "recorded_at": now,
            "queries": 0, "successful": 0, "failed": 0, "rate_limited": 0,
        }
        out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(doc, indent=2))
        return 0
    successful = failed = rate_limited = 0
    for q in QUERIES:
        rec = {"query": q, "status": "ERROR", "urls": []}
        try:
            hits = prov.search(q)
            if not hits:
                rec["status"] = "NO_HITS"
                failed += 1
            else:
                page = prov.fetch(hits[0].url)
                rec["urls"] = [hits[0].url]
                rec["fetch_status"] = page.fetch_status
                rec["title"] = page.title
                if page.fetch_status == "OK" and (page.content or "").strip():
                    rec["status"] = "OK"
                    successful += 1
                    r = research(f"Look up {q}", provider=prov)
                    rec["pipeline_status"] = r.status
                    rec["answer_prefix"] = (r.answer or "")[:180]
                else:
                    rec["status"] = page.fetch_status or "FAIL"
                    failed += 1
        except Exception as e:
            rec["status"] = "ERROR"
            rec["error"] = type(e).__name__
            failed += 1
        rows.append(rec)
    operational = successful > 0
    doc = {
        "status": "PASS" if operational else "LIVE_PROVIDER_UNAVAILABLE",
        "provider": prov.provider_name,
        "paid_or_free": "free",
        "cost_class": FREE_NETWORK,
        "date_tested": now,
        "operational_provider": operational,
        "queries": len(QUERIES),
        "successful": successful,
        "failed": failed,
        "rate_limited": rate_limited,
        "rows": rows,
        "notes": "Live smoke is not the frozen promotion benchmark.",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in (
        "status", "provider", "queries", "successful", "failed",
        "operational_provider")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
