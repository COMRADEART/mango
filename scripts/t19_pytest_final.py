"""T19.71 — full pytest suite into evaluations/t19/."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _counts(xml_path: Path) -> dict:
    tree = ET.parse(str(xml_path))
    s = tree.getroot()
    if s.tag == "testsuites":
        suites = list(s.findall("testsuite")) or [s]
        tests_n = sum(int(x.get("tests", "0")) for x in suites)
        fail_n = sum(int(x.get("failures", "0")) for x in suites)
        err_n = sum(int(x.get("errors", "0")) for x in suites)
        skip_n = sum(int(x.get("skipped", "0")) for x in suites)
        time_s = sum(float(x.get("time", "0") or 0) for x in suites)
    else:
        tests_n = int(s.get("tests", "0"))
        fail_n = int(s.get("failures", "0"))
        err_n = int(s.get("errors", "0"))
        skip_n = int(s.get("skipped", "0"))
        time_s = float(s.get("time", "0") or 0)
    return {
        "tests": tests_n, "failures": fail_n, "errors": err_n,
        "skipped": skip_n, "time_s": time_s,
        "failed": fail_n,
        "passed": tests_n - fail_n - err_n - skip_n,
    }


def main() -> int:
    stale = ROOT / "tests" / ".pytest_tmp"
    if stale.exists():
        shutil.rmtree(stale, ignore_errors=True)
    out_xml = ROOT / "evaluations/t19/full_junit.xml"
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    py = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q",
         f"--junitxml={out_xml}", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    counts = _counts(out_xml)
    doc = {
        "milestone": "T19.70 — final pytest",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **counts,
        "exit_code": int(py.returncode),
        "stdout_tail": (py.stdout or "")[-2000:],
    }
    out = ROOT / "evaluations/t19/pytest_final.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in (
        "tests", "passed", "failed", "errors", "skipped", "time_s",
        "exit_code")}, indent=2))
    ok = (py.returncode == 0 and doc["failures"] == 0 and doc["errors"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
