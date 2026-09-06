"""Classify the 29 frozen T8S Qwen3-4B tool failures."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluations/t8/runs/qwen3-4b-instruct/t4_tool/tool_calls.jsonl"
OUT = ROOT / "evaluations/t9/tool_failure_audit.json"


def classify(row: dict) -> tuple[str, str]:
    code = (row.get("error") or {}).get("code", "")
    message = (row.get("error") or {}).get("message", "").lower()
    if code == "UNKNOWN_TOOL":
        return "WRONG_TOOL", "MODEL_INVOCATION"
    if code == "PARSE_ERROR":
        return "PARSER_REJECTION", "MODEL_INVOCATION"
    if code == "INTERNAL_ERROR":
        return "TOOL_INTERNAL_FAILURE", "TOOL_IMPLEMENTATION"
    if code in {"DISALLOWED_EXPRESSION", "UNKNOWN_UNIT"} or "unknown operation" in message:
        return "UNSUPPORTED_EXPRESSION", "MODEL_INVOCATION"
    if code in {"TIMEOUT", "RESOURCE_LIMIT"}:
        return "RESOURCE_CAP", "TOOL_IMPLEMENTATION"
    if code == "INVALID_INPUT":
        return "MALFORMED_ARGUMENT", "MODEL_INVOCATION"
    return "OTHER", "UNRESOLVED"


def main() -> None:
    calls = [json.loads(line) for line in SOURCE.read_text().splitlines() if line.strip()]
    failed = [r for r in calls if r.get("status") == "error"]
    rows = []
    for row in failed:
        category, ownership = classify(row)
        rows.append({"question_id": row["question_id"], "tool": row["tool"],
                     "arguments": row["arguments"], "error": row["error"],
                     "category": category, "ownership": ownership})
    categories = Counter(r["category"] for r in rows)
    owners = Counter(r["ownership"] for r in rows)
    result = {"source": str(SOURCE.relative_to(ROOT)), "tool_invocations": len(calls),
              "valid": len(calls) - len(failed), "failures": len(failed),
              "failure_categories": dict(sorted(categories.items())),
              "ownership": dict(sorted(owners.items())), "rows": rows}
    assert len(calls) == 150 and len(failed) == 29
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
