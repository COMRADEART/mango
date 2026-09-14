"""T17 failure taxonomy."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t17/failure_analysis.json"


def main() -> int:
    fin = json.loads(
        (ROOT / "evaluations/t17/runs/t17-final/summary.json").read_text(
            encoding="utf-8"))
    doc = fin.get("document") or {}
    data = fin.get("data_core") or {}
    fails = []
    for k, v in doc.items():
        if isinstance(v, float) and v < 1.0 and "fabricat" not in k:
            fails.append({"metric": k, "measured": v, "suite": "document"})
        if isinstance(v, int) and v > 0 and k.startswith("fabricat"):
            fails.append({"metric": k, "measured": v, "suite": "document"})
    taxonomy = {
        "wrong_file_type": 0,
        "parse_failure": 0,
        "missed_evidence": 0,
        "fabricated_content": doc.get("fabricated_document", 0),
        "unsupported_claim": 0,
        "prompt_injection_follow": doc.get("prompt_injection_success", 0),
        "path_escape": doc.get("path_escape", 0),
        "join_or_agg_error": 0,
        "type_error": 0,
    }
    out = {
        "milestone": "T17 failure analysis",
        "document_final_accuracy": doc.get("final_answer_accuracy"),
        "data_final_accuracy": data.get("final_accuracy"),
        "below_perfect": fails,
        "taxonomy": taxonomy,
        "dominant": "none" if not fails else fails[0]["metric"],
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
