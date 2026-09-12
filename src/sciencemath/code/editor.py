"""T15.7–T15.8, T15.11 — minimal edits, patch validation, no test weakening.

- Smallest change that satisfies the behavior; unrelated diff tracked.
- An edit is DONE only after parse/compile + targeted tests + diff review.
- Test-weakening patterns (deleted assertions, loosened tolerances,
  truthy-swaps, disabled tests, fixture edits to fit code) are rejected.
"""
from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path

from sciencemath.code.safety import protected_edit

# --- test-weakening detectors (T15.11) ---------------------------------------
_WEAKEN_PATTERNS = (
    (re.compile(r"^\s*#\s*noqa"), "suppressed lint without justification"),
    (re.compile(r"@pytest\.mark\.(skip|skipif|xfail)"), "disabled test marker"),
    (re.compile(r"pytest\.skip\s*\("), "added unconditional skip"),
    (re.compile(r"assert\s+True(\s|$)"), "trivial truthy assertion"),
    (re.compile(r"except\s*:\s*pass"), "swallowed exception"),
)

_TOLERANCE_LOOSEN = re.compile(
    r"(abs_tol|rel_tol|tolerance|atol|rtol|\btol\b|delta)\s*=\s*([0-9.eE+-]+)")

_EXACT_TO_TRUTHY = re.compile(r"assert\s+(\w+)\s*==\s*(True|1)\b")


def detect_test_weakening(before: str, after: str) -> list[str]:
    """Compare test-file versions; return a list of violations (empty = OK)."""
    violations: list[str] = []
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    # Deleted assertions without replacement.
    before_asserts = [l.strip() for l in before_lines if "assert" in l]
    after_asserts = [l.strip() for l in after_lines if "assert" in l]
    for a in before_asserts:
        if a not in after_asserts and not any(
                difflib.SequenceMatcher(None, a, b).ratio() > 0.85
                for b in after_asserts):
            violations.append(f"deleted assertion: {a[:120]}")
    for i, line in enumerate(after_lines, start=1):
        for rx, msg in _WEAKEN_PATTERNS:
            if rx.search(line):
                violations.append(f"line {i}: {msg}: {line.strip()[:120]}")
        m = _EXACT_TO_TRUTHY.search(line)
        if m:
            violations.append(f"line {i}: exact check weakened: "
                              f"{line.strip()[:120]}")
    # Loosened numeric tolerances.
    before_tol = {m.group(1): float(m.group(2))
                  for l in before_lines for m in [_TOLERANCE_LOOSEN.search(l)]
                  if m}
    for l in after_lines:
        m = _TOLERANCE_LOOSEN.search(l)
        if m and m.group(1) in before_tol:
            try:
                if float(m.group(2)) > before_tol[m.group(1)]:
                    violations.append(
                        f"loosened tolerance {m.group(1)}: "
                        f"{before_tol[m.group(1)]} -> {m.group(2)}")
            except ValueError:
                pass
    return violations


def is_test_file(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return ("/tests/" in f"/{p}" or name.startswith("test_")
            or name.endswith("_test.py"))


def apply_edit(root: str | Path, rel_path: str, old: str, new: str, *,
               task_allows: tuple = ()) -> dict:
    """Apply one exact-match replacement. Fails closed on ambiguity.

    Returns a result record with diff stats. Never touches protected paths.
    """
    base = Path(root)
    raw = rel_path.replace("\\", "/")
    if ".." in raw.split("/"):
        return {"ok": False, "error": "path escapes repository root",
                "files_touched": []}
    rel = raw.lstrip("./")
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return {"ok": False, "error": "path escapes repository root",
                "files_touched": []}
    if protected_edit(rel, task_allows=task_allows):
        return {"ok": False, "error": f"protected component: {rel}",
                "files_touched": []}
    if not target.is_file():
        return {"ok": False, "error": f"not a file: {rel}",
                "files_touched": []}
    try:
        original = target.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"unreadable: {e}", "files_touched": []}
    count = original.count(old)
    if count == 0:
        return {"ok": False, "error": "oldString not found",
                "files_touched": []}
    if count > 1:
        return {"ok": False,
                "error": f"oldString matches {count}x; not unique",
                "files_touched": []}
    updated = original.replace(old, new, 1)
    if is_test_file(rel):
        violations = detect_test_weakening(original, updated)
        if violations:
            return {"ok": False, "error": "test weakening rejected",
                    "violations": violations, "files_touched": []}
    target.write_text(updated, encoding="utf-8")
    diff = list(difflib.unified_diff(original.splitlines(),
                                     updated.splitlines(), lineterm=""))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    return {"ok": True, "file": rel, "lines_added": added,
            "lines_removed": removed, "diff": "\n".join(diff)[:8000],
            "files_touched": [rel]}


def create_file(root: str | Path, rel_path: str, content: str, *,
                task_allows: tuple = ()) -> dict:
    """Create one NEW file. Refuses overwrites, escapes, protected paths,
    and missing parent directories (no recursive tree creation)."""
    base = Path(root)
    raw = rel_path.replace("\\", "/")
    if ".." in raw.split("/"):
        return {"ok": False, "error": "path escapes repository root",
                "files_touched": []}
    rel = raw.lstrip("./")
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return {"ok": False, "error": "path escapes repository root",
                "files_touched": []}
    if protected_edit(rel, task_allows=task_allows):
        return {"ok": False, "error": f"protected component: {rel}",
                "files_touched": []}
    if target.exists():
        return {"ok": False, "error": f"already exists: {rel}",
                "files_touched": []}
    if not target.parent.is_dir():
        return {"ok": False, "error": f"parent missing: {rel}",
                "files_touched": []}
    ok_s, err = syntax_ok(rel, content)
    if not ok_s:
        return {"ok": False, "error": f"new file syntax: {err}",
                "files_touched": []}
    if is_test_file(rel):
        violations = detect_test_weakening("", content)
        if violations:
            return {"ok": False, "error": "test weakening rejected",
                    "violations": violations, "files_touched": []}
    target.write_text(content, encoding="utf-8")
    added = len(content.splitlines())
    return {"ok": True, "file": rel, "lines_added": added,
            "lines_removed": 0, "diff": f"+++ b/{rel}\n(new file, "
            f"{added} lines)", "files_touched": [rel]}


def syntax_ok(path: str, text: str) -> tuple:
    """Parse/compile check. Returns (ok, error)."""
    if path.endswith(".py"):
        try:
            ast.parse(text)
            return True, ""
        except SyntaxError as e:
            return False, f"{e.msg} at line {e.lineno}"
    return True, ""  # non-Python: no local parser; tests decide


def diff_stats(diff_text: str) -> dict:
    lines = (diff_text or "").splitlines()
    return {
        "lines_added": sum(1 for l in lines
                           if l.startswith("+") and not l.startswith("+++")),
        "lines_removed": sum(1 for l in lines
                             if l.startswith("-") and not l.startswith("---")),
        "files_touched": sorted({l[4:].split("\t")[0]
                                 for l in lines if l.startswith("+++ ")
                                 and not l.startswith("+++ /dev/null")}),
    }
