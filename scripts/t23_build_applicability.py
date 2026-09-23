"""Deterministically materialize the public-safe T23 applicability ledger."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from t23_protocol.applicability import LEDGER, build_ledger  # noqa: E402
from t23_protocol.lifecycle import verify_lifecycle  # noqa: E402


def main() -> None:
    if verify_lifecycle(ROOT, "t23")["status"] != "PASS":
        raise SystemExit("T23 real-path/preconstruction state is not valid")
    ledger = build_ledger(ROOT)
    target = ROOT / LEDGER
    target.write_bytes((json.dumps(ledger, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    print(f"ledger_entries={len(ledger['entries'])}")


if __name__ == "__main__":
    main()
