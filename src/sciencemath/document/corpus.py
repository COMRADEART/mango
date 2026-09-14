"""Fixture corpus helpers for tests and evals."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "evaluations" / "t17" / "fixtures"


def fixture_dir() -> Path:
    return FIX


def fixture_path(name: str) -> Path:
    return FIX / name


def manifest() -> dict:
    p = FIX / "manifest.json"
    if not p.exists():
        return {"files": []}
    return json.loads(p.read_text(encoding="utf-8"))


def sandbox_roots() -> list[Path]:
    # Fixture sandbox only. Do not include tests/ — pytest --basetemp lives
    # at tests/.pytest_tmp and is not a document-access root.
    return [FIX.resolve()]


def supplied_path(rel: str) -> str:
    """Map suite/repo-relative fixture paths into the sandbox."""
    s = (rel or "").replace("\\", "/")
    if s.startswith("..") or s.startswith("/") or (len(s) > 1 and s[1] == ":"):
        return rel
    prefix = "evaluations/t17/fixtures/"
    if s.startswith(prefix):
        return str(FIX / s[len(prefix):])
    name = Path(s).name
    cand = FIX / name
    if cand.exists():
        return str(cand)
    return rel
