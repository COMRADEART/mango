"""Historical artifact write guard — static + runtime regression.

Later milestone protection harnesses (T16+) must never invoke
``scripts/t15r_mutation_probe.py`` without an explicit milestone-local
``--out``: the probe's default destination is the historical
``evaluations/t15r/mutation_safety_probe.json`` artifact, which is an
immutable record (pinned by
``tests/test_post_t20_historical_artifact_hygiene.py``).

Mechanical check: every literal subprocess argument list in the T16-T20
protection harnesses that names the probe must also contain a literal
``--out`` whose value is a milestone-local path (never the historical T15R
path). The only callers allowed to use the historical default are the probe
script itself and the T15R protection battery — the T15R-context owner of
the artifact (see the probe's own docstring).

The check intentionally inspects literal argument lists only: building a
command that lacks ``--out`` at the literal site fails the guard even if a
later ``+=`` would add it. The guard is conservative by design.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = "t15r_mutation_probe.py"
HISTORICAL = ROOT / "evaluations/t15r/mutation_safety_probe.json"
CANONICAL_BLOB_SHA = "fba2437f78633884bd31965d78a4250bd1ca893c"

# Milestone -> its protection harness. Every post-T15R protection battery
# added in the future must be registered here.
HARNESS: dict[str, str] = {
    "T16": "scripts/t16_protection_battery.py",
    "T17": "scripts/t17_protection_summary.py",
    "T18": "scripts/t18_protection_summary.py",
    "T19": "scripts/t19_protection_summary.py",
    "T20": "scripts/t20_protection_summary.py",
    "T21": "scripts/t21_protection_battery.py",
    "T21R": "scripts/t21r_protection_battery.py",
    "T21R2": "scripts/t21r2_protection_battery.py",
    "T21R3": "scripts/t21r3_protection_battery.py",
    "T21R4": "scripts/t21r4_protection_battery.py",
    "T21R5": "scripts/t21r5_protection_battery.py",
}

# Callers that own the historical T15R artifact and may keep the default.
T15R_CONTEXT = {
    "scripts/t15r_mutation_probe.py",
    "scripts/t15r_protection_battery.py",
}


def _string_consts(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _names_probe(value: str) -> bool:
    return (value == PROBE
            or value.endswith("/" + PROBE)
            or value.endswith("\\" + PROBE))


def _probe_invocations(tree: ast.AST) -> list[list[str]]:
    """All literal list/tuple argument containers that name the probe."""
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            consts = _string_consts(node)
            if any(_names_probe(c) for c in consts):
                found.append(consts)
    return found


def _unsafe_reason(args: list[str]) -> str | None:
    if "--out" not in args:
        return "probe invoked without --out (would use the historical T15R default)"
    idx = args.index("--out")
    out = args[idx + 1] if idx + 1 < len(args) else None
    if not out or "t15r" in out.lower():
        return f"--out is missing or points at the historical T15R path ({out!r})"
    return None


def _git_blob_sha(path: Path) -> str:
    out = subprocess.run(
        ["git", "hash-object", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_t16_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T16"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T16 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t17_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T17"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T17 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t18_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T18"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T18 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t19_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T19"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T19 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t20_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T20"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T20 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t21_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T21"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T21 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t21r_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T21R"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T21R harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t21r2_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T21R2"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T21R2 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t21r3_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T21R3"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T21R3 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t21r4_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T21R4"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T21R4 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_t21r5_harness_invokes_probe_with_milestone_local_out() -> None:
    tree = ast.parse((ROOT / HARNESS["T21R5"]).read_text(encoding="utf-8"))
    invocations = _probe_invocations(tree)
    assert invocations, "T21R5 harness no longer runs the mutation probe?"
    for args in invocations:
        assert _unsafe_reason(args) is None


def test_out_destinations_are_milestone_local() -> None:
    for milestone, rel in HARNESS.items():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for args in _probe_invocations(tree):
            out = args[args.index("--out") + 1].replace("\\", "/")
            assert out.startswith(f"evaluations/{milestone.lower()}/"), \
                f"{rel}: --out {out!r} is not under {milestone.lower()}/"


def test_no_unsafe_probe_caller_anywhere_in_scripts() -> None:
    """Sweep every script: outside the T15R context, no probe invocation may
    omit a milestone-local --out."""
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in T15R_CONTEXT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for args in _probe_invocations(tree):
            assert _unsafe_reason(args) is None, f"{rel}: {_unsafe_reason(args)}"


def test_guard_detects_the_legacy_unsafe_pattern() -> None:
    """Negative control: the checker must flag the pre-fix invocation shape,
    so the guard cannot silently rot into a no-op."""
    unsafe = (
        "run([sys.executable, 'scripts/t15r_mutation_probe.py'])\n"
        "safe = ['scripts/t15r_mutation_probe.py', '--out', "
        "'evaluations/t20/mutation_safety_probe.json']\n"
    )
    invocations = _probe_invocations(ast.parse(unsafe))
    assert len(invocations) == 2
    reasons = [_unsafe_reason(inv) for inv in invocations]
    assert any(r is not None for r in reasons), "guard missed the unsafe shape"
    assert any(r is None for r in reasons), "guard rejects a safe --out shape"


def test_probe_writes_to_temp_out_and_leaves_history_untouched(
        tmp_path: Path) -> None:
    """Runtime check: the probe succeeds against a temporary --out, and the
    historical T15R artifact is byte-identical afterwards."""
    out = tmp_path / "mutation_safety_probe.json"
    r = subprocess.run(
        [sys.executable, "scripts/t15r_mutation_probe.py", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["passed"] is True
    assert _git_blob_sha(HISTORICAL) == CANONICAL_BLOB_SHA