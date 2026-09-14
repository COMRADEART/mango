"""T18.65 real local disk persistence smoke (outside fixtures)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.memory.pipeline import handle
from sciencemath.memory.store import MemoryStore

OUT = ROOT / "evaluations/t18/live_smoke.json"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mango_t18_smoke_"))
    db = tmp / "smoke.sqlite"
    steps = {}
    s = MemoryStore(db)
    r = handle("Remember that smoke city is Lisbon.",
               store=s, owner_id="smoke", scope_type="GLOBAL_USER",
               scope_id="smoke", user_explicit=True, subject="city")
    steps["write"] = r.status == "MEMORY_STORE"
    s.close()
    s = MemoryStore(db)
    q = handle("What city?", store=s, owner_id="smoke",
               scope_type="GLOBAL_USER", scope_id="smoke")
    steps["restart_read"] = "Lisbon" in q.answer
    s.close()
    s = MemoryStore(db)
    u = handle("Correction: city is Porto.",
               store=s, owner_id="smoke", scope_type="GLOBAL_USER",
               scope_id="smoke", user_explicit=True, subject="city",
               op="MEMORY_SUPERSEDE")
    steps["update"] = u.status == "MEMORY_SUPERSEDE"
    s.close()
    s = MemoryStore(db)
    q2 = handle("What city?", store=s, owner_id="smoke",
                scope_type="GLOBAL_USER", scope_id="smoke")
    steps["update_restart"] = "Porto" in q2.answer and "Lisbon" not in q2.answer
    mid = q2.memories[0].memory_id if q2.memories else None
    handle("delete", store=s, owner_id="smoke", scope_type="GLOBAL_USER",
           scope_id="smoke", memory_id=mid, op="MEMORY_DELETE")
    s.close()
    s = MemoryStore(db)
    q3 = handle("What city?", store=s, owner_id="smoke",
                scope_type="GLOBAL_USER", scope_id="smoke")
    steps["delete_restart"] = q3.status == "MEMORY_NO_MATCH"
    s.close()
    ok = all(steps.values())
    doc = {
        "milestone": "T18.65 real local persistence smoke",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db),
        "outside_fixtures": True,
        "steps": steps,
        "result": "PASS" if ok else "FAIL",
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
