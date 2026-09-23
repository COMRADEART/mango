"""Write a public-safe verdict for the exact unrestricted pytest failure set."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from t23_protocol.applicability import validate_applicability  # noqa: E402


def main() -> int:
    report = validate_applicability(ROOT, require_tracked="--require-tracked" in sys.argv[1:])
    target = ROOT / "evaluations/t23/applicability_validation_report.json"
    target.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
