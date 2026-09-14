"""T16.52 — full pytest suite into evaluations/t16/."""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.getcwd())
sys.path.insert(0, str(ROOT))

import pytest


def main() -> int:
    out_xml = ROOT / "evaluations/t16/full_junit.xml"
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    code = pytest.main(["tests", "-q", f"--junitxml={out_xml}",
                        "-p", "no:cacheprovider"])
    tree = ET.parse(str(out_xml))
    root_el = tree.getroot()
    s = root_el.find("testsuite") if root_el.tag == "testsuites" else root_el
    if s is None:
        s = root_el
    doc = {
        "milestone": "T16.52 — final pytest",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "tests": int(s.get("tests", "0")),
        "failures": int(s.get("failures", "0")),
        "errors": int(s.get("errors", "0")),
        "skipped": int(s.get("skipped", "0")),
        "exit_code": int(code),
        "failed": int(s.get("failures", "0")),
        "passed": int(s.get("tests", "0")) - int(s.get("failures", "0"))
        - int(s.get("errors", "0")) - int(s.get("skipped", "0")),
        "time_s": float(s.get("time", "0") or 0),
    }
    out = ROOT / "evaluations/t16/pytest_final.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=2))
    ok = (code == 0 and doc["failures"] == 0 and doc["errors"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
