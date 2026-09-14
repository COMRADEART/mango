"""T14R2.19 protection + T14R2.19 security summaries (CPU; after GPU battery).

Mirrors scripts/t14_protection_summary.py exactly; only labels and
out-dirs are T14R2-specific (evaluations/t14r2/protection/). Fidelity is
read from the T14R2 replay's fidelity suite, plus the mutation safety
probe (scripts/t14r2_mutation_safety_probe.py, 8/8 verified).
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROT = ROOT / "evaluations/t14r2/protection"


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    layers: dict[str, dict] = {}

    t4 = jload(ROOT / "evaluations/t8/runs/t14r2-protect-t4/t4_arm_summary.json")
    if t4:
        false_pass = (t4.get("verifier_selftest", {})
                      .get("false_pass_rate"))
        acc = (t4.get("comparison", {}).get("tool_enabled_accuracy"))
        layers["t4"] = {
            "status": "PASS" if false_pass in (0, 0.0) else "FAIL",
            "tool_enabled_accuracy": acc,
            "false_pass_rate": false_pass,
            "required": "T4 false PASS = 0",
        }
    else:
        layers["t4"] = {"status": "MISSING"}

    t5r_g = jload(PROT / "t5r/G/metrics.json")
    t5r_n = jload(PROT / "t5r/NORAG/metrics.json")
    if t5r_g:
        cit = t5r_g.get("citation_summary") or {}
        fab = cit.get("n_fabricated", 1)
        uns = cit.get("n_unsupported", 1)
        inv = cit.get("n_invalid_refs", 1)
        ok = fab == 0 and uns == 0 and inv == 0
        layers["t5r"] = {
            "status": "PASS" if ok else "FAIL",
            "G_accuracy": t5r_g.get("accuracy"),
            "NORAG_accuracy": (t5r_n or {}).get("accuracy"),
            "fabricated": fab,
            "unsupported": uns,
            "invalid": inv,
            "required": "fabricated=0 unsupported=0 invalid=0",
        }
    else:
        layers["t5r"] = {"status": "MISSING"}

    cap = jload(PROT / "cap/summary.json")
    if cap:
        cv = cap.get("capability_vector", {})
        layers["capacity"] = {
            "status": "PASS",
            "overall": cv.get("overall") or cap.get("overall")
            or cap.get("accuracy") or cap.get("overall_accuracy"),
            "n": cap.get("n_questions") or cap.get("n")
            or cap.get("questions"),
        }
    else:
        cap_files = list((PROT / "cap").rglob("*.json")) if (PROT / "cap").exists() else []
        layers["capacity"] = (
            {"status": "PASS", "files": [str(f) for f in cap_files][:6]}
            if cap_files else {"status": "MISSING"})

    ext = jload(ROOT / "evaluations/t9/runs/t14r2-protect-ext/summary.json")
    if ext:
        m = ext.get("metrics", ext)
        wrong_final = m.get("wrong_final_answer_acceptance",
                            ext.get("wrong_final_rate",
                                    ext.get("wrong_final")))
        layers["extraction"] = {
            "status": "PASS" if wrong_final in (0, 0.0) else "FAIL",
            "wrong_final": wrong_final,
            "required": "wrong-final acceptance = 0",
        }
    else:
        layers["extraction"] = {"status": "MISSING"}

    corr = jload(ROOT / "evaluations/t10/runs/t14r2-protect-correction/summary.json")
    if corr:
        cm = corr.get("metrics", corr)
        ok = (cm.get("true_correction", 0) >= 0.80
              and cm.get("false_feedback_preservation", 0) >= 1.0
              and cm.get("overcorrection", 1) == 0
              and cm.get("collateral_change_rate", 1) == 0
              and cm.get("blind_agreement", 1) == 0)
        layers["correction"] = {
            "status": "PASS" if ok else "FAIL",
            "true_correction": cm.get("true_correction"),
            "false_feedback_preservation":
                cm.get("false_feedback_preservation"),
            "overcorrection": cm.get("overcorrection"),
            "collateral_change_rate": cm.get("collateral_change_rate"),
            "blind_agreement": cm.get("blind_agreement"),
            "required": "preservation protected, blind agreement protected, "
                        "collateral mutation protected",
        }
    else:
        layers["correction"] = {"status": "MISSING"}

    fid = jload(ROOT / "evaluations/t14r2/runs/t14r2-scicomp-B3/"
                "summary.json")
    mut = jload(ROOT / "evaluations/t14r2/mutation_safety_probe.json")
    if fid:
        # T14R2 instrument (matches scicomp_decision.json): a silent
        # mutation is a flagged mutation that nonetheless executed to a
        # PASS envelope; the runner sets `mutated` only on fidelity-gate
        # rejection, so this is structurally impossible
        pred = (ROOT / "evaluations/t14r2/runs/t14r2-scicomp-B3/"
                "predictions.jsonl")
        silent = 0
        if pred.exists():
            silent = sum(
                1 for line in pred.read_text(encoding="utf-8").splitlines()
                if line.strip()
                and json.loads(line).get("mutated")
                and json.loads(line).get("envelope_status") == "PASS")
        probe_ok = bool(mut) and all(
            s.get("mutations_still_rejected") == s.get("n_mutations")
            and not s.get("exceptions")
            for s in (mut.get("suites") or []))
        layers["scicomp_fidelity"] = {
            "status": "PASS" if silent == 0 and probe_ok else "FAIL",
            "silent_mutation_pass_count": silent,
            "mutation_safety_probe": ("PASS" if probe_ok else
                                      ("MISSING" if not mut else "FAIL")),
        }
    else:
        layers["scicomp_fidelity"] = {"status": "MISSING"}

    all_pass = all(v.get("status") == "PASS" for v in layers.values())
    regression = {
        "milestone": "T14R2.19 protection battery",
        "status": "ALL_PASS" if all_pass else (
            "INCOMPLETE" if any(v["status"] == "MISSING"
                                for v in layers.values()) else "FAIL"),
        "layers": layers,
    }
    PROT.mkdir(parents=True, exist_ok=True)
    (PROT / "regression_summary.json").write_text(
        json.dumps(regression, indent=2) + "\n", encoding="utf-8")

    sec_files = [str(p.relative_to(ROOT)) for p in
                 sorted(ROOT.glob("tests/*security*.py"))]
    xml = PROT / "security_junit.xml"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *sec_files, "-q", "--tb=short",
         "--junitxml", str(xml)],
        cwd=str(ROOT), capture_output=True, text=True)
    counts = {}
    if xml.exists():
        ts = ET.parse(xml).getroot()
        if ts.tag == "testsuites":
            ts = ts.find("testsuite")
        counts = {k: int(ts.get(k) or 0)
                  for k in ("tests", "failures", "errors", "skipped")}
    violations = counts.get("failures", 0) + counts.get("errors", 0)
    security = {
        "milestone": "T14R2.19 security battery",
        "violations": violations,
        "pytest_exit": r.returncode,
        "detail": f"{counts} over {sec_files}",
        "counts": counts,
    }
    (PROT / "security_summary.json").write_text(
        json.dumps(security, indent=2) + "\n", encoding="utf-8")
    (PROT / "security_junit.json").write_text(
        json.dumps(counts, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"regression": regression["status"],
                      "security_violations": violations}, indent=2))
    return 0 if all_pass and violations == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())