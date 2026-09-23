"""Run unrestricted pytest without modifying the published historical result."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts import t23_capture_unrestricted as capture  # noqa: E402
from t23_protocol.applicability import validate_applicability  # noqa: E402

RAW = "evaluations/t23/unrestricted_pytest_requalification.json"
VERDICT = "evaluations/t23/applicability_requalification_report.json"


def main() -> int:
    capture.REPORT = ROOT / RAW
    capture.main()
    result = validate_applicability(ROOT, result_path=RAW, require_tracked=False)
    (ROOT / VERDICT).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"],
                      "raw_failed": result.get("raw_pytest_failed", result.get("observed_failures")),
                      "historical_matched": result.get("recognized_historical_failures", 0),
                      "LIVE": result["live_failures"], "UNKNOWN": result["unknown_failures"]},
                     sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
