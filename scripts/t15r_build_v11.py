"""T15R.18–T15R.19 — mango-code-eval-v1.1 metadata correction.

Copies mango-code-eval-v1 without altering fixtures, requests, tests,
checks, difficulty, or prompts. The ONLY task-level change is filling
an empty `golden` file list for import_err rows that already declare
`repair_file`. Those empty golden sets caused T15's unrelated-edit
metric (3/72) to count legitimate repair_file touches as unrelated.

Does not rewrite historical T15 v1 artifacts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evaluations/t15/suites/mango-code-eval-v1"
DST = ROOT / "evaluations/t15r/suites/mango-code-eval-v1.1"
DOC = ROOT / "evaluations/t15r/v1_vs_v1.1.json"

IMMUTABLE = (
    "task_id", "category", "op", "request", "fixture", "checks",
    "context_files", "tests_to_run", "repair_file", "model_needed",
    "family", "review_file", "review_bad", "review_base",
)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def correct_row(row: dict) -> tuple[dict, bool]:
    out = json.loads(json.dumps(row))
    changed = False
    if out.get("category") == "import_err":
        gold = out.get("golden") or []
        rf = out.get("repair_file")
        files = {g.get("file") for g in gold if isinstance(g, dict)}
        if rf and rf not in files:
            # file-only metadata; no old/new, so this cannot be used as a patch
            out["golden"] = list(gold) + [{"file": rf}]
            changed = True
    return out, changed


def write_split(name: str) -> tuple[str, list[str]]:
    src = SRC / f"{name}.jsonl"
    dst = DST / f"{name}.jsonl"
    corrected: list[str] = []
    lines = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        out, ch = correct_row(row)
        if ch:
            corrected.append(out["task_id"])
        lines.append(json.dumps(out, ensure_ascii=False))
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return sha(dst), corrected


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    v1_man = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    v1_final = sha(SRC / "final.jsonl")
    v1_dev = sha(SRC / "dev.jsonl")
    assert v1_final == v1_man["final_sha256"], "v1 final checksum drifted"
    assert v1_dev == v1_man["dev_sha256"], "v1 dev checksum drifted"

    final_sha, final_ids = write_split("final")
    dev_sha, dev_ids = write_split("dev")
    man = {
        "benchmark": "mango-code-eval-v1.1",
        "version": "v1.1",
        "parent": "mango-code-eval-v1",
        "parent_final_sha256": v1_final,
        "parent_dev_sha256": v1_dev,
        "seed": v1_man["seed"],
        "total": v1_man["total"],
        "dev_n": v1_man["dev_n"],
        "final_n": v1_man["final_n"],
        "dev_sha256": dev_sha,
        "final_sha256": final_sha,
        "correction": {
            "kind": "golden_file_metadata_only",
            "categories": ["import_err"],
            "final_task_ids": final_ids,
            "dev_task_ids": dev_ids,
            "adds": "golden[].file = repair_file when golden was empty",
            "does_not_change": [
                "task behavior", "expected outputs", "tests", "difficulty",
                "model prompts", "scoring of unrelated categories",
                "golden old/new patches",
            ],
        },
        "behavioral_changes": "NONE",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    (DST / "manifest.json").write_text(
        json.dumps(man, indent=2) + "\n", encoding="utf-8")
    DOC.write_text(json.dumps({
        "v1_historical_unchanged": True,
        "v1_final_sha256": v1_final,
        "v1.1_created": True,
        "v1.1_final_sha256": final_sha,
        "v1.1_dev_sha256": dev_sha,
        "metadata_corrections": [
            {"task_id": tid, "split": "final",
             "change": "add golden file metadata = repair_file"}
            for tid in final_ids
        ] + [
            {"task_id": tid, "split": "dev",
             "change": "add golden file metadata = repair_file"}
            for tid in dev_ids
        ],
        "behavioral_changes_to_benchmark": "NONE",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "v1_final": v1_final, "v1.1_final": final_sha,
        "final_corrected": final_ids, "dev_corrected": dev_ids,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
