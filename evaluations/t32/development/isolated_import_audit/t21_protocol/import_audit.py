"""Static and dynamic import-time filesystem side-effect audit."""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from typing import Any, Iterable

from .write_guard import diff_snapshots, snapshot_tree

WRITE_CALLS = frozenset({"write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "rmdir"})


def _top_level_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    bodies = getattr(tree, "body", [])
    for statement in bodies:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(statement, ast.If) and _is_main_guard(statement.test):
            continue
        calls.extend(node for node in ast.walk(statement) if isinstance(node, ast.Call))
    return calls


def _is_main_guard(test: ast.AST) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def static_import_write_audit(paths: Iterable[Path]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            findings.append({"path": path.as_posix(), "line": getattr(exc, "lineno", 0), "call": "unparseable"})
            continue
        for call in _top_level_calls(tree):
            name = None
            if isinstance(call.func, ast.Attribute):
                name = call.func.attr
            elif isinstance(call.func, ast.Name):
                name = call.func.id
            if name in WRITE_CALLS or name == "open" and len(call.args) > 1 and isinstance(call.args[1], ast.Constant) and any(
                marker in str(call.args[1].value) for marker in ("w", "a", "x", "+")
            ):
                findings.append({"path": path.as_posix(), "line": call.lineno, "call": name})
    return {"status": "PASS" if not findings else "FAIL", "writers": len(findings), "findings": findings}


def dynamic_import_write_audit(root: Path, modules: Iterable[str]) -> dict[str, Any]:
    before = snapshot_tree(root)
    prior = list(sys.path)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    try:
        for module in modules:
            sys.modules.pop(module, None)
            importlib.import_module(module)
    finally:
        sys.path[:] = prior
    after = snapshot_tree(root)
    diff = diff_snapshots(before, after)
    # Python bytecode/cache artifacts are ignored by Git and not repository evidence.
    unexpected = [
        path for category in diff.values() for path in category
        if "__pycache__/" not in path and not path.endswith(".pyc")
    ]
    return {"status": "PASS" if not unexpected else "FAIL", "writers": len(unexpected), "paths": sorted(unexpected)}
