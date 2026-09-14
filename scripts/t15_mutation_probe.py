"""T15 mutation-safety probe — CODE addition must NOT weaken frozen gates.

Reuses the EXACT T14R2 replay logic (same gates, same verdicts) on the
current tree and writes evaluations/t15/mutation_safety_probe.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "t14r2_probe", str(ROOT / "scripts" / "t14r2_mutation_safety_probe.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

OUT = ROOT / "evaluations/t15/mutation_safety_probe.json"


def main() -> int:
    suites = [_mod.replay_suite(n, d) for n, d in _mod.SUITES]
    passed = all(s["passed"] for s in suites)
    doc = {"milestone": "T15 mutation-safety probe (T14R2 logic, current tree)",
           "recorded_at": datetime.now(timezone.utc).isoformat(),
           "suites": suites, "passed": passed}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for s in suites:
        print(f"{s['suite']}: {s['mutations_still_rejected']}/"
              f"{s['n_mutations']} rejected, "
              f"exceptions {len(s['exceptions'])} -> "
              f"{'PASS' if s['passed'] else 'FAIL'}")
    print("overall:", "PASS" if passed else "FAIL", "->", OUT)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
