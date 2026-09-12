"""T15.5 — deterministic repository search interfaces.

Exact/local search before model speculation. Every hit carries file:line
evidence; callers must never claim a symbol exists without a hit here.
Respects the T15.4 skip lists.
"""
from __future__ import annotations

import re
from pathlib import Path

from sciencemath.code.discovery import SKIP_DIRS, SKIP_SUFFIXES

MAX_HITS = 200
MAX_FILE_BYTES = 1_000_000


def _iter_files(root: Path, *, include_suffixes=None):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        if include_suffixes and p.suffix.lower() not in include_suffixes:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield p


def _read_lines(p: Path) -> list[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def search_text(root: str | Path, pattern: str, *, max_hits: int = MAX_HITS,
                regex: bool = False) -> list[dict]:
    """Plain-text (default) or regex search. Returns evidence hits."""
    base = Path(root)
    rx = re.compile(pattern) if regex else None
    hits: list[dict] = []
    for p in _iter_files(base):
        for i, line in enumerate(_read_lines(p), start=1):
            ok = bool(rx.search(line)) if rx else (pattern in line)
            if ok:
                hits.append({
                    "file": p.relative_to(base).as_posix(),
                    "line": i,
                    "text": line.strip()[:240],
                })
                if len(hits) >= max_hits:
                    return hits
    return hits


def search_symbol(root: str | Path, name: str,
                  *, max_hits: int = MAX_HITS) -> list[dict]:
    """Symbol search: def/class/import/assignment of `name` (word-bounded)."""
    rx = re.compile(
        r"(^\s*(def|class)\s+%s\b|^\s*%s\s*[:=]|import\s+.*\b%s\b|"
        r"from\s+\S+\s+import\s+.*\b%s\b|\b%s\s*\()" % ((re.escape(name),) * 5))
    hits: list[dict] = []
    base = Path(root)
    for p in _iter_files(base):
        for i, line in enumerate(_read_lines(p), start=1):
            if rx.search(line):
                hits.append({
                    "file": p.relative_to(base).as_posix(),
                    "line": i,
                    "text": line.strip()[:240],
                })
                if len(hits) >= max_hits:
                    return hits
    return hits


def search_imports(root: str | Path, module: str) -> list[dict]:
    rx = re.compile(r"^\s*(import\s+%s\b|from\s+%s(\s+import|\.))\.?"
                    % (re.escape(module), re.escape(module)))
    hits: list[dict] = []
    base = Path(root)
    for p in _iter_files(base):
        for i, line in enumerate(_read_lines(p), start=1):
            if rx.search(line):
                hits.append({
                    "file": p.relative_to(base).as_posix(),
                    "line": i,
                    "text": line.strip()[:240],
                })
    return hits


def find_files(root: str | Path, name_part: str) -> list[str]:
    """File-path search by substring (case-insensitive)."""
    base = Path(root)
    needle = name_part.lower()
    out = []
    for p in _iter_files(base):
        rel = p.relative_to(base).as_posix()
        if needle in rel.lower():
            out.append(rel)
    return sorted(out)


def symbol_exists(root: str | Path, name: str) -> tuple:
    """Return (exists: bool, hits). The ONLY sanctioned existence claim."""
    hits = search_symbol(root, name)
    return (bool(hits), hits)
