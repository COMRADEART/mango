"""Show eval run progress (resume state)."""
import json
import sys
from pathlib import Path

run = sys.argv[1] if len(sys.argv) > 1 else "code-final"
p = Path(f"evaluations/t15/runs/{run}/predictions.jsonl")
if not p.exists():
    print("no predictions yet")
else:
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    real = [r for r in rows if not r.get("skipped")]
    print(f"rows={len(rows)} complete={len(real)} "
          f"pass={sum(1 for r in real if r.get('pass'))}")
