"""T20.82 apply the promotion decision to the ORCHESTRATION registry entry.

Reads evaluations/t20/final_audit.json. Only PROMOTE flips
EXPERIMENTAL -> ACTIVE; KEEP leaves it EXPERIMENTAL; REJECT disables.
The Executive Router is never touched. Writes the decision record.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "evaluations/t20/final_audit.json"
SKILLS = ROOT / "src/sciencemath/executive/skills.py"
OUT = ROOT / "evaluations/t20/promotion_decision.json"


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    decision = audit["decision"]

    if decision == "PROMOTE_ORCHESTRATION_SKILL":
        text = SKILLS.read_text(encoding="utf-8")
        # flip only the ORCHESTRATION entry's availability
        pattern = re.compile(
            r'("ORCHESTRATION": _skill\(.*?)availability=EXPERIMENTAL',
            re.DOTALL)
        new_text, n = pattern.subn(
            r'\1availability=ACTIVE', text, count=1)
        if n == 0 and "Promoted ACTIVE at T20." in text:
            # idempotent: the promotion is already applied
            out = {
                "milestone": "T20.82 promotion decision applied",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "decision": decision,
                "applied": "already applied (ORCHESTRATION is ACTIVE)",
                "executive_router": "untouched; remains EXPERIMENTAL and "
                                    "is not claimed by T20",
            }
            OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
            print(json.dumps(out, indent=2))
            return 0
        assert n == 1, "ORCHESTRATION EXPERIMENTAL entry not found"
        new_text = new_text.replace(
            '"external action authority. T20 runtime.",',
            '"external action authority. T20 runtime. "\n'
            '                        "Promoted ACTIVE at T20.",', 1)
        # the registry import must still parse after the edit
        import ast
        ast.parse(new_text)
        SKILLS.write_text(new_text, encoding="utf-8")
        applied = "ORCHESTRATION EXPERIMENTAL -> ACTIVE"
    elif decision == "REJECT_ORCHESTRATION_SKILL":
        text = SKILLS.read_text(encoding="utf-8")
        pattern = re.compile(
            r'("ORCHESTRATION": _skill\(.*?)availability=EXPERIMENTAL',
            re.DOTALL)
        new_text, n = pattern.subn(r"\1availability=DISABLED", text, count=1)
        assert n == 1, "ORCHESTRATION EXPERIMENTAL entry not found"
        SKILLS.write_text(new_text, encoding="utf-8")
        applied = "ORCHESTRATION EXPERIMENTAL -> DISABLED"
    else:
        applied = "no registry change (KEEP_ORCHESTRATION_EXPERIMENTAL)"

    out = {
        "milestone": "T20.82 promotion decision applied",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "applied": applied,
        "executive_router": "untouched; remains EXPERIMENTAL and is not "
                            "claimed by T20",
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    # sanity: the registry still imports
    subprocess.run(
        ["python", "-c",
         "import sys; sys.path.insert(0, 'src'); "
         "from sciencemath.executive.skills import default_registry; "
         "print(default_registry()['ORCHESTRATION']['availability'])"],
        cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())