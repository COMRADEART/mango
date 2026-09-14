"""T15R mutation-safety probe — CODE repair-loop must not weaken frozen gates.

Historical note (post-T20 hygiene): later protection batteries must NOT
rewrite this historical artifact. Reruns should pass --out pointing at
their own milestone directory; the default output remains the historical
T15R path only for the T15R battery itself.
"""
from __future__ import annotations

import argparse
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

OUT = ROOT / "evaluations/t15r/mutation_safety_probe.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", default=None,
        help="output path; default = historical evaluations/t15r/ path. "
             "Later milestones must pass their own milestone-local path.")
    args = ap.parse_args()
    out = Path(args.out) if args.out else OUT

    suites = [_mod.replay_suite(n, d) for n, d in _mod.SUITES]
    passed = all(s["passed"] for s in suites)
    doc = {"milestone": "T15R mutation-safety probe (T14R2 logic, current tree)",
           "recorded_at": datetime.now(timezone.utc).isoformat(),
           "suites": suites, "passed": passed}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for s in suites:
        print(f"{s['suite']}: {s['mutations_still_rejected']}/"
              f"{s['n_mutations']} rejected, "
              f"exceptions {len(s['exceptions'])} -> "
              f"{'PASS' if s['passed'] else 'FAIL'}")
    print("overall:", "PASS" if passed else "FAIL", "->", out)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
