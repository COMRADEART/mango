"""T24 public-Git blind-blob scanner: worktree, index, tracked files, commit trees, refs.

The blob-content hash is authoritative — a renamed copy of blind material is
still detected. Any blind blob in public Git, or any forbidden pre-evaluation
path, fails closed (required count 0).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from .policy import path_forbidden

SCAN_SCHEMA = "t24-git-blind-blob-scan-v1"
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          check=True, text=True).stdout


def _blob_sha256(root: Path, object_hash: str, cache: dict[str, str]) -> str:
    if object_hash not in cache:
        data = subprocess.run(["git", "cat-file", "blob", object_hash], cwd=root,
                              capture_output=True, check=True).stdout
        cache[object_hash] = hashlib.sha256(data).hexdigest()
    return cache[object_hash]


def _iter_worktree(root: Path) -> Iterable[tuple[str, str]]:
    for path in root.rglob("*"):
        if not path.is_file() or _SKIP_DIRS & set(path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/"):
            continue
        yield relative, hashlib.sha256(path.read_bytes()).hexdigest()


def scan_public_git(root: Path, *, blind_hashes: set[str], refs: tuple[str, ...] = (),
                    include_worktree: bool = True, include_index: bool = True,
                    include_tracked: bool = True, include_refs: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    cache: dict[str, str] = {}
    surfaces: dict[str, dict[str, str]] = {}
    if include_worktree:
        surfaces["worktree"] = dict(_iter_worktree(root))
    if include_index:
        index: dict[str, str] = {}
        for line in _git(root, "ls-files", "-s").splitlines():
            _meta, object_hash, _stage, *path_parts = line.split()
            index["/".join(path_parts)] = object_hash
        surfaces["index"] = index
    if include_tracked:
        surfaces["tracked"] = dict(_iter_tree(root, "HEAD"))
    refs_hashes: dict[str, dict[str, str]] = {}
    if include_refs:
        for ref in refs:
            refs_hashes[ref] = dict(_iter_tree(root, ref))
    blind_blob_matches = []
    for surface, mapping in surfaces.items():
        for relative, object_hash in mapping.items():
            content_hash = (_blob_sha256(root, object_hash, cache)
                            if surface in {"index", "tracked"} else object_hash)
            if content_hash in blind_hashes:
                blind_blob_matches.append({"surface": surface, "path": relative,
                                           "content_sha256": content_hash})
    for ref, mapping in refs_hashes.items():
        for relative, object_hash in mapping.items():
            if _blob_sha256(root, object_hash, cache) in blind_hashes:
                blind_blob_matches.append({"surface": f"ref:{ref}", "path": relative,
                                           "content_sha256": _blob_sha256(root, object_hash, cache)})
    observed_paths = set()
    for surface, mapping in surfaces.items():
        observed_paths.update(mapping)
    for mapping in refs_hashes.values():
        observed_paths.update(mapping)
    path_policy_violations = sorted(path for path in observed_paths if path_forbidden(path))
    required = 0
    return {"schema_version": SCAN_SCHEMA, "experiment": "t24",
            "required_blind_blob_count": required,
            "surfaces_scanned": sorted(surfaces) + [f"ref:{ref}" for ref in refs_hashes],
            "observed_path_count": len(observed_paths),
            "blind_blob_matches": blind_blob_matches,
            "blind_blob_count": len(blind_blob_matches),
            "path_policy_violations": path_policy_violations,
            "status": "PASS" if (len(blind_blob_matches) == required
                                 and not path_policy_violations) else "FAIL"}


def _iter_tree(root: Path, revision: str) -> dict[str, str]:
    """Every blob at a revision (HEAD or any ref)."""
    out = subprocess.run(["git", "ls-tree", "-r", revision], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    mapping: dict[str, str] = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        _mode, kind, object_hash = meta.split()
        if kind == "blob":
            mapping[path] = object_hash
    return mapping


def ensure_clean_public_git(root: Path, *, blind_hashes: set[str],
                            refs: tuple[str, ...] = ()) -> dict[str, Any]:
    """Fail-closed wrapper used before any public-safe T24 publication."""
    report = scan_public_git(root, blind_hashes=blind_hashes, refs=refs)
    if report["status"] != "PASS":
        raise ValueError(f"T24 public Git blind-blob scan failed: "
                         f"{json.dumps({'matches': report['blind_blob_matches'],
                                        'paths': report['path_policy_violations']})}")
    return report