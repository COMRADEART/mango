"""Remove regression rows from code-final predictions for clean regrade."""
import json
from pathlib import Path

p = Path("evaluations/t15/runs/code-final/predictions.jsonl")
rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
        if l.strip()]
keep = [r for r in rows
        if not (r["category"] == "regression" and not r.get("skipped"))]
drop = [r for r in rows if r not in keep]
print(f"keeping {len(keep)}, dropping {len(drop)} regression rows")
p.write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
