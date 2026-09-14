"""Diagnose refactor/algo/multi failures: statuses, reasons, trails."""
import json
from pathlib import Path

p = Path("evaluations/t15/runs/code-final/predictions.jsonl")
rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
        if l.strip()]
for r in rows:
    if r["category"] in ("refactor", "algo", "multi_fix", "data_xform") \
            and not r["pass"]:
        print("=" * 70)
        print(r["task_id"], r["category"], r["status"], r["latency_s"])
        print("detail:", r["detail"][:400])
        print("reasons:", r["reasons"][:2])
        print("touched:", r["files_touched"], "test:", r.get("test"))
