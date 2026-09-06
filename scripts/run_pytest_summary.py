"""Run the full pytest suite and print the exact summary line.

The pytest terminal summary is intermittently lost when stdout is a pipe
on this Windows setup, so this harness captures it via a stream-wrapping
plugin and asserts the counts against the JUnit XML.
"""
import os
import sys
import xml.etree.ElementTree as ET

import pytest


class _SummaryCapture:
    """Hook the terminalreporter summary line."""

    def __init__(self) -> None:
        self.summary = None

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        try:
            text = terminalreporter._tw.getvalue()
        except Exception:  # noqa: BLE001
            return
        for line in reversed(text.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                self.summary = line.strip()
                break


def main() -> int:
    # `tests.conftest` is imported by test_licenses.py; make the repo
    # root importable exactly as the CLI pytest invocation does.
    sys.path.insert(0, os.getcwd())
    capture = _SummaryCapture()
    code = pytest.main(["tests", "-q", "--junitxml=full_junit.xml",
                        "-p", "no:cacheprovider"],
                       plugins=[capture])
    tree = ET.parse("full_junit.xml")
    s = tree.getroot().find("testsuite")
    junit = ("JUNIT: tests=%s failures=%s errors=%s skipped=%s time=%s" %
             (s.get("tests"), s.get("failures"), s.get("errors"),
              s.get("skipped"), s.get("time")))
    print("EXITCODE", code)
    print("SUMMARY:", capture.summary or "(summary line not captured)")
    print(junit)
    return 0 if (code == 0 and s.get("failures") == "0"
                 and s.get("errors") == "0") else 1


if __name__ == "__main__":
    sys.exit(main())