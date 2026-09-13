"""Extract import_err golden-file metadata for T15R.18 decision."""
import json
from pathlib import Path

suite = Path("evaluations/t15/suites/mango-code-eval-v1/final.jsonl")
rows = [json.loads(l) for l in Path(
    "evaluations/t15/runs/code-final/predictions.jsonl"
).read_text(encoding="utf-8").splitlines() if l.strip()]
tasks = {json.loads(l)["task_id"]: json.loads(l)
         for l in suite.read_text(encoding="utf-8").splitlines() if l.strip()}
for r in rows:
    if r["category"] != "import_err":
        continue
    t = tasks[r["task_id"]]
    gold = t.get("golden")
    print(r["task_id"], "pass", r["pass"], "touched", r.get("files_touched"),
          "golden", gold, "repair_file", t.get("repair_file"),
          "family", t.get("family"))
