"""Identify unrelated-edit outliers + BLOCKED-breakdown for the report."""
import json
from pathlib import Path

suite = {}
for l in Path("evaluations/t15/suites/mango-code-eval-v1/final.jsonl"
              ).read_text(encoding="utf-8").splitlines():
    if l.strip():
        t = json.loads(l)
        suite[t["task_id"]] = t

rows = [json.loads(l) for l in Path(
    "evaluations/t15/runs/code-final/predictions.jsonl").read_text(
    encoding="utf-8").splitlines() if l.strip()]

for r in rows:
    if r["category"] in ("single_fix", "multi_fix", "test_repair", "feature",
                         "refactor", "config", "import_err", "type_err",
                         "algo", "data_xform", "api_compat"):
        t = suite[r["task_id"]]
        gold = {g["file"] for g in t.get("golden", [])}
        touched = set(r.get("files_touched", []))
        extra = touched - gold - {f for f in touched if "test" in f.lower()}
        if r["category"] != "test_repair" and extra:
            print(f"UNRELATED {r['task_id']} {r['category']} pass={r['pass']} "
                  f"touched={sorted(touched)} golden={sorted(gold)}")
print("done")
