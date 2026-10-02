"""Repository write allowlists and tracked-tree cleanliness checks."""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .errors import WriteGuardError
from .util import sha256_file, sha256_json


def snapshot_tree(root: Path, *, exclude_git: bool = True) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if exclude_git and (relative == ".git" or relative.startswith(".git/")):
            continue
        snapshot[relative] = sha256_file(path)
    return snapshot


def diff_snapshots(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(after) - set(before)),
        "deleted": sorted(set(before) - set(after)),
        "modified": sorted(path for path in set(before) & set(after) if before[path] != after[path]),
    }


def _allowed(relative: str, patterns: tuple[str, ...]) -> bool:
    return any(
        relative == pattern.rstrip("/")
        or relative.startswith(pattern.rstrip("/") + "/")
        or fnmatch.fnmatchcase(relative, pattern)
        for pattern in patterns
    )


class WriteGuard:
    def __init__(self, root: Path, writable_paths: Iterable[str]):
        self.root = root.resolve()
        self.writable_paths = tuple(Path(path).as_posix() for path in writable_paths)
        self.before: dict[str, str] = {}
        self.diff: dict[str, list[str]] = {}

    def __enter__(self) -> "WriteGuard":
        self.before = snapshot_tree(self.root)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.diff = diff_snapshots(self.before, snapshot_tree(self.root))
        unexpected = sorted(
            path
            for category in self.diff.values()
            for path in category
            if not _allowed(path, self.writable_paths)
        )
        if unexpected and exc is None:
            raise WriteGuardError(f"unexpected filesystem writes: {unexpected}")
        return False


def tracked_tree(root: Path) -> dict[str, str]:
    command = ["git", "-C", str(root), "ls-files", "-z"]
    result = subprocess.run(command, check=True, capture_output=True)
    files = [part.decode("utf-8") for part in result.stdout.split(b"\0") if part]
    snapshot: dict[str, str] = {}
    for relative in files:
        path = root / relative
        snapshot[relative] = sha256_file(path) if path.is_file() else "__DELETED__"
    return snapshot


def tracked_tree_hash(root: Path) -> str:
    return sha256_json(tracked_tree(root))


def protocol_test_cleanliness(root: Path, command: list[str]) -> dict[str, Any]:
    before = tracked_tree(root)
    process = subprocess.run(command, cwd=root, text=True, capture_output=True)
    after = tracked_tree(root)
    diff = diff_snapshots(before, after)
    drift = sum(len(values) for values in diff.values())
    return {
        "status": "PASS" if process.returncode == 0 and drift == 0 else "FAIL",
        "exit_code": process.returncode,
        "tracked_tree_before": sha256_json(before),
        "tracked_tree_after": sha256_json(after),
        "tracked_modifications": len(diff["modified"]),
        "tracked_deletions": len(diff["deleted"]),
        "tracked_additions": len(diff["added"]),
        "stdout": process.stdout,
        "stderr": process.stderr,
    }
