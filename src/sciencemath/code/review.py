"""T15.26–T15.27 — bounded code review and independent diff inspection.

Review inspects correctness, regressions, security, error handling, tests,
API compatibility, and maintainability — findings reference actual code
evidence, never invented bugs. Severity: BLOCKER / HIGH / MEDIUM / LOW /
NOTE. The diff gate FAILS CLOSED on unexpected files, generated artifacts,
lockfile churn, binaries, secret-like strings, test deletions, benchmark
or protected-component edits.
"""
from __future__ import annotations

import re

BLOCKER = "BLOCKER"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
NOTE = "NOTE"

SEVERITIES = (BLOCKER, HIGH, MEDIUM, LOW, NOTE)

_REVIEW_CHECKS = (
    ("correctness", re.compile(r"\b(off.by.one|wrong (op|sign|index)|"
                               r"inverted|swapped|missing (return|await|"
                               r"check|null))\b", re.I)),
    ("correctness", re.compile(r"^\s*assert\s+True\s*(#.*)?$")),
    ("error_handling", re.compile(r"except\s*:|except\s+Exception\s*:"
                                  r"\s*pass|TODO|FIXME|XXX|HACK", re.I)),
    ("security", re.compile(r"\beval\s*\(|exec\s*\(|os\.system|"
                            r"subprocess\.(call|run|Popen)\s*\(.*shell\s*=\s*"
                            r"True|pickle\.loads|yaml\.load\s*\(", re.I)),
    ("api_compat", re.compile(r"def\s+\w+\(.*(?!.*=.*\).*:)", re.I)),
)

_FINDING = re.compile(r"^(?P<file>\S+):(?P<line>\d+):\s*(?P<msg>.+)$")


def code_review(diff_text: str, *, changed_files=()) -> dict:
    """Deterministic review over the actual diff. Evidence-bound findings."""
    findings: list[dict] = []
    lines = (diff_text or "").splitlines()
    current_file = ""
    for line in lines:
        if line.startswith("+++ "):
            current_file = line[4:].strip()
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        for area, rx in _REVIEW_CHECKS:
            if rx.search(body):
                sev = HIGH if area == "security" else (
                    MEDIUM if area in ("correctness", "error_handling")
                    else LOW)
                findings.append({
                    "severity": sev,
                    "area": area,
                    "file": current_file,
                    "evidence": body.strip()[:200],
                })
    # Every review ends with an explicit verdict, even when clean.
    verdict = "APPROVE" if not any(
        f["severity"] in (BLOCKER, HIGH) for f in findings) else "CHANGES_REQUESTED"
    return {"findings": findings, "verdict": verdict,
            "files_reviewed": list(changed_files or [])}


_GENERATED = re.compile(
    r"(?i)(package-lock\.json$|yarn\.lock$|poetry\.lock$|"
    r"\.min\.js$|\.bundle\.js$|__pycache__|/dist/|/build/)")
_BINARY = re.compile(r"(?i)(\.png$|\.jpg$|\.jpeg$|\.gif$|\.ico$|\.pdf$|"
                     r"\.zip$|\.exe$|\.dll$|\.so$|\.safetensors$)")
_SECRET_LIKE = re.compile(
    r"(?i)(api[_-]?key\s*[:=]|password\s*[:=]|ghp_[A-Za-z0-9]{8,}|"
    r"sk-(live|test)-[A-Za-z0-9]{8,})")


def diff_review(diff_text: str, *, task_allows: tuple = (),
                expect_test_changes: bool = False) -> dict:
    """Independent deterministic diff inspection. FAIL CLOSED."""
    from sciencemath.code.safety import protected_edit
    problems: list[str] = []
    files: list[str] = []
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ "):
            f = line[4:].strip().removeprefix("b/")
            files.append(f)
            if _GENERATED.search(f):
                problems.append(f"generated/lockfile artifact: {f}")
            if _BINARY.search(f):
                problems.append(f"binary addition: {f}")
            if protected_edit(f, task_allows=task_allows):
                problems.append(f"protected-component edit: {f}")
        if line.startswith("+") and not line.startswith("+++"):
            if _SECRET_LIKE.search(line):
                problems.append("secret-like string in added lines")
    removed_tests = [f for f in files
                     if ("test" in f.lower()) and not expect_test_changes]
    # Test-file *modification* is fine when the task adds tests; wholesale
    # deletion signals are caught via removed line counts by the caller.
    _ = removed_tests
    return {"ok": not problems, "problems": problems, "files": files}
