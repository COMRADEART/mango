"""T15.9–T15.10 — test selection and test-generation policy.

Classify: TARGETED_TEST / RELATED_SUBSYSTEM_TEST / FULL_SUITE /
NO_TEST_AVAILABLE. Small changes run targeted tests first; promotion
evaluation runs the full suite. Generated tests must assert externally
meaningful behavior and must never weaken existing tests.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

TARGETED_TEST = "TARGETED_TEST"
RELATED_SUBSYSTEM_TEST = "RELATED_SUBSYSTEM_TEST"
FULL_SUITE = "FULL_SUITE"
NO_TEST_AVAILABLE = "NO_TEST_AVAILABLE"

SCOPES = (TARGETED_TEST, RELATED_SUBSYSTEM_TEST, FULL_SUITE,
          NO_TEST_AVAILABLE)


def classify_test_scope(files_touched: list, *, test_files_present: bool) -> str:
    if not files_touched:
        return NO_TEST_AVAILABLE if not test_files_present else TARGETED_TEST
    if len(files_touched) == 1:
        return TARGETED_TEST
    if len(files_touched) <= 5:
        return RELATED_SUBSYSTEM_TEST
    return FULL_SUITE


def related_tests_for(repo_root: str | Path, files_touched: list) -> list[str]:
    """Map touched source files to candidate test files (same stem)."""
    base = Path(repo_root)
    tests = []
    for rel in files_touched:
        stem = Path(rel).stem
        for cand in (f"tests/test_{stem}.py", f"tests/{stem}_test.py"):
            if (base / cand).is_file() and cand not in tests:
                tests.append(cand)
    return tests


def invalidate_pycache(repo_root: str | Path, files_touched: list) -> int:
    """Remove stale bytecode for touched files.

    CPython validates .pyc by source mtime at SECONDS resolution; a fast
    edit→test→repair→retest cycle can otherwise retest STALE bytecode
    (two writes within one second). Clearing the touched stems' pyc
    entries guarantees tests exercise current source. Returns count
    of removed files.
    """
    base = Path(repo_root)
    removed = 0
    for rel in files_touched:
        stem = Path(rel).stem
        parent = base / Path(rel).parent
        cache = parent / "__pycache__"
        if not cache.is_dir():
            continue
        for pyc in cache.glob(f"{stem}.*.pyc"):
            try:
                pyc.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def run_pytest_targets(repo_root: str | Path, targets: list[str],
                       *, timeout_s: int = 300,
                       touch_files: list | None = None) -> dict:
    """Run pytest on explicit targets. Records real counts — never invented.

    Returns {executed, exit_code, passed, failed, errors, skipped, output}.
    executed=False when pytest itself could not run (counts stay 0 and the
    caller must report NOT_RUN, never PASS).
    """
    if not targets:
        return {"executed": False, "exit_code": None, "passed": 0,
                "failed": 0, "errors": 0, "skipped": 0, "output": "",
                "note": "no targets"}
    import os as _os
    invalidate_pycache(repo_root, list(touch_files or []))
    try:
        env = dict(_os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        r = subprocess.run(
            ["python", "-m", "pytest", *targets, "-q", "-p",
             "no:cacheprovider"], cwd=str(repo_root), capture_output=True,
            text=True, timeout=timeout_s, env=env, encoding="utf-8",
            errors="replace")
    except Exception as e:  # noqa: BLE001 — record, never fabricate
        return {"executed": False, "exit_code": None, "passed": 0,
                "failed": 0, "errors": 0, "skipped": 0, "output": str(e)[:2000],
                "note": "pytest did not execute"}
    out = (r.stdout or "") + (r.stderr or "")
    passed = failed = errors = skipped = 0
    import re as _re
    for line in out.splitlines():
        s = line.strip()
        # short summary ("1 failed, 2 passed in 0.5s") and -q tail
        # ("1 failed in 0.05s") both count; FAILED header lines are
        # uppercase and never match the lowercase patterns below.
        for m in _re.finditer(r"(\d+)\s+(passed|failed|errors?|skipped)", s):
            n = int(m.group(1))
            if m.group(2) == "passed":
                passed = max(passed, n)
            elif m.group(2) == "failed":
                failed = max(failed, n)
            elif m.group(2).startswith("error"):
                errors = max(errors, n)
            else:
                skipped = max(skipped, n)
    # Fallback evidence: pytest's short-summary FAILED/ERROR lines. (A
    # nested pytest run on this Windows setup intermittently omits the
    # "N failed in Xs" tail line; the FAILED lines plus the real exit
    # code remain authoritative evidence — never invented.)
    n_failed_lines = sum(1 for line in out.splitlines()
                         if line.strip().startswith("FAILED "))
    n_error_lines = sum(1 for line in out.splitlines()
                        if line.strip().startswith("ERROR "))
    failed = max(failed, n_failed_lines)
    errors = max(errors, n_error_lines)
    failure_ids = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("FAILED ") or s.startswith("ERROR "):
            token = s.split()[1] if len(s.split()) > 1 else s
            token = token.split(" ")[0].rstrip(":")
            if token and token not in failure_ids:
                failure_ids.append(token)
    if not failure_ids and failed:
        failure_ids = [f"anon:{i}" for i in range(failed)]
    # pytest -q progress line (FFFF.) as last-resort counts when nested
    # pytest omits both the summary tail and FAILED node-id lines.
    if r.returncode != 0 and failed == 0 and errors == 0:
        for line in reversed(out.splitlines()):
            s = line.strip()
            if s and set(s) <= set(".EFEsxX") and any(c in s for c in "FE"):
                failed = max(failed, s.count("F"))
                errors = max(errors, s.count("E"))
                break
        if failed == 0 and errors == 0:
            failed = 1
        if not failure_ids:
            failure_ids = [f"anon:{i}" for i in range(max(failed, errors))]
    return {"executed": True, "exit_code": r.returncode, "passed": passed,
            "failed": failed, "errors": errors, "skipped": skipped,
            "failure_ids": failure_ids,
            "output": out[-4000:]}


TEST_GEN_RULES = (
    "test externally meaningful behavior",
    "reproduce the bug when possible",
    "fail before repair where appropriate",
    "pass after repair",
    "avoid asserting implementation trivia",
    "never weaken existing tests",
    "never delete inconvenient tests",
)


def test_gen_forbidden(action: str) -> bool:
    """True if a proposed test action is forbidden (T15.10)."""
    a = (action or "").lower()
    return any(k in a for k in (
        "edit expected value to pass", "skip failing test",
        "mark xfail to hide", "reduce coverage", "delete failing test",
        "loosen tolerance"))
