"""Print one prediction row."""
import json
import sys
from pathlib import Path

run, task = sys.argv[1], sys.argv[2]
p = Path(f"evaluations/t15/runs/{run}/predictions.jsonl")
for l in p.read_text(encoding="utf-8").splitlines():
    if l.strip():
        r = json.loads(l)
        if r["task_id"] == task:
            print(json.dumps(r, indent=1)[:3000])
