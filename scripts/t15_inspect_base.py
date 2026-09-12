"""Print baseline responses for data_xform + api tasks."""
import json
from pathlib import Path

p = Path("evaluations/t15/runs/baseline-final/predictions.jsonl")
want = ("data_xform", "api_compat")
for l in p.read_text(encoding="utf-8").splitlines():
    if l.strip():
        r = json.loads(l)
        if r["category"] in want and r["task_id"] in (
                "mce-v1-0121", "mce-v1-0131"):
            print("=" * 60)
            print(r["task_id"], r["category"], r["reasons"])
            print(r["response"][:1200])
