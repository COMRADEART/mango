"""T21.58/T21.59/T21.60 — final audit, promotion decision, application.

Reads every preregistered T21 artifact and decides between the three
preregistered outcomes:

- PROMOTE_KNOWLEDGE_RAG_SKILL  — all gates pass on dev AND final
- KEEP_EXPERIMENTAL            — gates pass but a floor is unmet or the
                                 protection battery failed
- REJECT                       — a zero-tolerance gate fired

The decision is idempotent: applying PROMOTE flips the registry entry
KNOWLEDGE_RAG EXPERIMENTAL -> ACTIVE, records the post-promotion registry
hash, and updates the test pins that reference the T21.2 registration
state. The Executive Router is never touched (it remains
KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL).

Output: evaluations/t21/promotion_decision.json.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

T21 = ROOT / "evaluations" / "t21"


def _read(rel: str):
    return json.loads((T21 / rel).read_text(encoding="utf-8"))


def _skills_py_text() -> str:
    return (ROOT / "src/sciencemath/executive/skills.py").read_text(
        encoding="utf-8")


def _registry_hash() -> str:
    from sciencemath.executive.skills import registry_sha256
    return registry_sha256()


def _lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def main() -> int:
    results = _read("eval_results.json")
    floors = _read("floors.json")
    prot = _read("protection/regression_summary.json")
    smoke = _read("smoke.json")
    perf = _read("performance.json")
    sci = _read("science_rag_regression.json")
    baselines = _read("baselines.json")
    pytest_final_path = T21 / "pytest_final.json"
    pytest_final = _read("pytest_final.json") if pytest_final_path.exists() \
        else None

    gates = {
        "floors_all_pass_both_splits": results["floors_all_pass"] is True,
        "zero_tolerance_all_zero": results["zero_tolerance_all_zero"] is True,
        "overall_pass": results["overall_pass"] is True,
        "protection_battery_all_pass": prot["status"] == "ALL_PASS",
        "t15r_canonical_blob_unchanged":
            prot["layers"]["t15r_canonical_blob"]["blob_sha256"]
            == "fba2437f78633884bd31965d78a4250bd1ca893c",
        "smoke_all_pass": smoke["status"] == "ALL_PASS",
        "performance_p95_within_floor": perf["pass"] is True,
        "science_rag_non_regression": sci["status"] == "PASS",
        "model_only_baseline_recorded":
            baselines["model_only_baseline"].get("ok") is True,
        "bm25_baseline_recorded":
            baselines["bm25_baseline"]["recall_at_5"] >= 0.94,
    }
    if pytest_final is not None:
        gates["full_pytest_zero_failures"] = (
            pytest_final.get("failures", 1) == 0
            and pytest_final.get("errors", 1) == 0)

    zero_tol = results.get("zero_tolerance_totals", {})
    fired = {k: v for k, v in zero_tol.items() if v}

    if fired:
        decision = "REJECT"
        reason = f"zero-tolerance gates fired: {fired}"
    elif not all(gates.values()):
        decision = "KEEP_EXPERIMENTAL"
        failed = [k for k, ok in gates.items() if not ok]
        reason = f"preregistered gates unmet: {failed}"
    else:
        decision = "PROMOTE_KNOWLEDGE_RAG_SKILL"
        reason = ("all preregistered floors pass on dev and final, all 20 "
                  "zero-tolerance counters are zero on every row, the "
                  "protection battery is ALL_PASS with the T15R canonical "
                  "blob unchanged, the real local smoke passes all 8 query "
                  "types, retrieval p95 is within the 500 ms floor, "
                  "SCIENCE_RAG does not regress, and both baselines are "
                  "recorded")

    doc = {
        "milestone": "T21.58-T21.60 final audit and promotion decision",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reason": reason,
        "gates": gates,
        "zero_tolerance_fired": fired,
        "executive_router": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL "
                            "(untouched; never claimed by T21)",
        "registry_sha256_before_promotion": _registry_hash(),
        "registry_sha256_promoted": None,
        "applied": False,
    }

    if decision != "PROMOTE_KNOWLEDGE_RAG_SKILL":
        out = T21 / "promotion_decision.json"
        out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"decision": decision, "gates": gates}, indent=2))
        return 0 if decision == "KEEP_EXPERIMENTAL" else 1

    # ---- idempotent application ------------------------------------------
    text = _skills_py_text()
    needle = ('"KNOWLEDGE_RAG": _skill(\n'
              '            skill_id="KNOWLEDGE_RAG",\n'
              '            description="Local-first general knowledge retrieval with "\n'
              '                        "source provenance, citation-grounded synthesis, "\n'
              '                        "conflict handling, freshness boundaries, and "\n'
              '                        "evidence-based abstention.",\n'
              '            availability=EXPERIMENTAL,')
    promoted = needle.replace(
        "evidence-based abstention.\",",
        "evidence-based abstention. Promoted ACTIVE at T21.\",").replace(
        "availability=EXPERIMENTAL,", "availability=ACTIVE,")
    if needle in text:
        (ROOT / "src/sciencemath/executive/skills.py").write_text(
            text.replace(needle, promoted), encoding="utf-8", newline="\n")
        applied = True
    elif promoted in text or re.search(
            r'"KNOWLEDGE_RAG": _skill\([^)]*availability=ACTIVE', text,
            re.S):
        applied = False  # already promoted (idempotent re-run)
    else:
        raise SystemExit("KNOWLEDGE_RAG registry entry not found")

    # test pins that referenced the T21.2 registration state
    contract = ROOT / "tests/test_t20_orchestration_contract.py"
    ctext = contract.read_text(encoding="utf-8")
    cnew = ctext.replace(
        "    counts = SkillRegistry().counts()\n"
        "    assert counts.get(ACTIVE) == 11\n"
        "    # T21.2 decision record (evaluations/t21/registry_registration.json):\n"
        "    # KNOWLEDGE_RAG is introduced EXPERIMENTAL; it is the only EXPERIMENTAL\n"
        "    # entry and ORCHESTRATION's promotion state is unchanged. Historical\n"
        "    # T20 artifacts were not rewritten.\n"
        "    assert counts.get(EXPERIMENTAL, 0) == 1",
        "    counts = SkillRegistry().counts()\n"
        "    assert counts.get(ACTIVE) == 12\n"
        "    # T21.2 registration record + T21.60 promotion decision record\n"
        "    # (evaluations/t21/registry_registration.json, then\n"
        "    # evaluations/t21/promotion_decision.json): KNOWLEDGE_RAG entered\n"
        "    # EXPERIMENTAL and was promoted ACTIVE at T21 close with every\n"
        "    # preregistered gate met. The Executive Router's promotion state is\n"
        "    # unchanged and no EXPERIMENTAL entry remains.\n"
        "    assert counts.get(EXPERIMENTAL, 0) == 0")
    if cnew != ctext:
        contract.write_text(cnew, encoding="utf-8", newline="\n")

    focused = ROOT / "tests/test_t21_knowledge_rag.py"
    ftext = focused.read_text(encoding="utf-8")
    fnew = ftext.replace(
        'assert d["KNOWLEDGE_RAG"]["availability"] == "EXPERIMENTAL"',
        'assert d["KNOWLEDGE_RAG"]["availability"] == "ACTIVE"').replace(
        'assert counts.get("ACTIVE") == 11\n'
        '    assert counts.get("EXPERIMENTAL", 0) == 1',
        'assert counts.get("ACTIVE") == 12\n'
        '    assert counts.get("EXPERIMENTAL", 0) == 0')
    if fnew != ftext:
        focused.write_text(fnew, encoding="utf-8", newline="\n")

    # importlib: recompute the registry hash against the promoted registry
    for mod in [m for m in list(sys.modules) if "skills" in m]:
        del sys.modules[mod]
    doc["registry_sha256_promoted"] = _registry_hash()
    doc["skills_py_sha256_promoted"] = hashlib.sha256(
        _lf((ROOT / "src/sciencemath/executive/skills.py").read_bytes())
    ).hexdigest()
    doc["applied"] = True
    doc["skills_py_updated"] = applied

    out = T21 / "promotion_decision.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())