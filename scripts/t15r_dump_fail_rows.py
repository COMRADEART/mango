"""Dump frozen T15 failure rows compactly."""
import json
from pathlib import Path

doc = json.loads(Path(
    "evaluations/t15r/t15_failure_analysis.json").read_text(encoding="utf-8"))
freeze = json.loads(Path(
    "evaluations/t15r/t15_failure_freeze.json").read_text(encoding="utf-8"))
by_id = {r["task_id"]: r for r in freeze["failures"]}
print(f"n={doc['n_classified']}")
for r in doc["rows"]:
    t = r["test"]
    f = by_id[r["task_id"]]
    touched_after = f["files_touched_after_revert"]
    print(
        f"{r['task_id']} {r['category']:12s} {r['primary']:28s} "
        f"base={r['baseline_pass']!s:5s} st={r['code_status']:14s} "
        f"rev={r['reverted']!s:5s} exit={t.get('exit_code')} "
        f"fail={t.get('failed')} passed={t.get('passed')} "
        f"touched={touched_after} reasons={f['final_test_result']['reasons'][:1]}"
    )
