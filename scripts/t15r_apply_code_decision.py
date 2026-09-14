"""T15R.29–T15R.30 — apply CODE decision after floors + protection + pytest.

Does not preselect. Reads artifacts and writes:
  evaluations/t15r/code_decision.json

On PROMOTE_CODE_SKILL only: persist CODE availability ACTIVE in
src/sciencemath/executive/skills.py. Executive Router is not modified.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src/sciencemath/executive/skills.py"
OUT = ROOT / "evaluations/t15r/code_decision.json"

OLD = '''        "CODE": _skill(
            skill_id="CODE",
            description="Code generation/execution runtime. Interface only "
                        "in T14 — not implemented.",
            availability=PREPARED_ONLY,'''

NEW = '''        "CODE": _skill(
            skill_id="CODE",
            description="Bounded repository-level coding intelligence "
                        "(CODE skill runtime). Promoted ACTIVE at T15R.",
            availability=ACTIVE,'''


def main() -> int:
    fl = json.loads((ROOT / "evaluations/t15r/floors_evaluation.json")
                    .read_text(encoding="utf-8"))
    prot = json.loads((ROOT / "evaluations/t15r/protection/regression_summary.json")
                      .read_text(encoding="utf-8"))
    sec = json.loads((ROOT / "evaluations/t15r/protection/security_summary.json")
                     .read_text(encoding="utf-8"))
    py = json.loads((ROOT / "evaluations/t15r/pytest_final.json")
                    .read_text(encoding="utf-8"))
    cfail = fl.get("critical_failures") or []
    qfail = fl.get("quality_failures") or []
    prot_ok = prot.get("status") == "ALL_PASS"
    sec_ok = sec.get("violations") == 0
    py_ok = py.get("failures") == 0 and py.get("errors") == 0
    floors_ok = not cfail and not qfail and fl.get("decision") == "PROMOTE_CODE_SKILL"

    if floors_ok and prot_ok and sec_ok and py_ok:
        decision = "PROMOTE_CODE_SKILL"
        after = "ACTIVE"
    elif cfail:
        decision = "REJECT_CODE_SKILL"
        after = "DISABLED"
    else:
        decision = "KEEP_CODE_SKILL_EXPERIMENTAL"
        after = "PREPARED_ONLY"

    applied = False
    if decision == "PROMOTE_CODE_SKILL":
        text = SKILLS.read_text(encoding="utf-8")
        if OLD not in text:
            raise SystemExit("skills.py CODE block not found for promotion")
        SKILLS.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
        applied = True
    elif decision == "REJECT_CODE_SKILL":
        # Keep PREPARED_ONLY rather than DISABLED unless a later gate
        # requires unavailability; REJECT is recorded, registry stays
        # non-executable (PREPARED_ONLY).
        after = "PREPARED_ONLY"

    doc = {
        "milestone": "T15R.29 CODE decision",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "availability_before": "PREPARED_ONLY",
        "availability_after": after,
        "semantic_before": "EXPERIMENTAL",
        "semantic_after": (
            "ACTIVE" if decision == "PROMOTE_CODE_SKILL"
            else "EXPERIMENTAL" if decision == "KEEP_CODE_SKILL_EXPERIMENTAL"
            else "DISABLED"),
        "applied_registry_edit": applied,
        "executive_router": "UNCHANGED",
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "gates": {
            "floors_ok": floors_ok,
            "critical_failures": cfail,
            "quality_failures": qfail,
            "protection": prot.get("status"),
            "security_violations": sec.get("violations"),
            "pytest_ok": py_ok,
        },
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
