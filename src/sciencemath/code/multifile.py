"""T15R.12–T15R.13 — multi-file dependency mapping and atomic edits."""
from __future__ import annotations

import ast
import re
from pathlib import Path


_ACROSS = re.compile(
    r"\b(across\s+src/|and\s+update\s+callers|and\s+src/|"
    r"across\s+\S+\s+and\s+|coordinated|multi-?file)\b", re.I)


def is_multi_file_task(request: str, context_files: list | None = None,
                       involved: list | None = None) -> bool:
    files = [f for f in (context_files or []) + (involved or [])
             if f and not str(f).endswith("__init__.py")]
    src_py = [f for f in files if str(f).replace("\\", "/").endswith(".py")
              and "/test" not in str(f).replace("\\", "/").lower()
              and not Path(str(f)).name.startswith("test_")]
    if len(set(src_py)) >= 2:
        return True
    return bool(_ACROSS.search(request or ""))


def _read(base: Path, rel: str) -> str:
    try:
        return (base / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def _module_name(rel: str) -> str:
    p = rel.replace("\\", "/").removesuffix(".py")
    p = p.removeprefix("src/").replace("/", ".")
    if p.endswith(".__init__"):
        p = p[: -len(".__init__")]
    return p


def map_dependencies(root: str | Path, files: list[str] | None = None
                     ) -> dict:
    """Explicit dependency map before multi-file edits (T15R.12)."""
    base = Path(root)
    if files:
        involved = [f.replace("\\", "/") for f in files if f]
    else:
        involved = []
        src = base / "src"
        if src.is_dir():
            involved = [p.relative_to(base).as_posix()
                        for p in sorted(src.rglob("*.py"))
                        if p.name != "__init__.py"]
    tests_dir = base / "tests"
    test_files = []
    if tests_dir.is_dir():
        test_files = [p.relative_to(base).as_posix()
                      for p in sorted(tests_dir.rglob("test_*.py"))]

    symbols: dict[str, list[str]] = {}
    imports: dict[str, list[str]] = {}
    calls: list[dict] = []
    for rel in involved:
        text = _read(base, rel)
        defined: list[str] = []
        imported: list[str] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    defined.append(node.name)
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            defined.append(t.id)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    imported.append(mod)
                    for alias in node.names:
                        calls.append({"from": rel, "import": mod,
                                      "name": alias.name})
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imported.append(alias.name)
        symbols[rel] = sorted(set(defined))
        imports[rel] = sorted(set(imported))

    tests_covering: dict[str, list[str]] = {f: [] for f in involved}
    for tf in test_files:
        ttext = _read(base, tf)
        for rel in involved:
            stem = Path(rel).stem
            mod = _module_name(rel)
            if stem in ttext or mod in ttext or rel in ttext:
                tests_covering[rel].append(tf)

    shared: list[str] = []
    for a in involved:
        for b in involved:
            if a >= b:
                continue
            sa, sb = set(symbols.get(a, [])), set(symbols.get(b, []))
            overlap = sorted(sa & sb)
            if overlap:
                shared.append(f"{a}∩{b}:{','.join(overlap)}")
            # A imported by B
            mb = _module_name(a)
            if mb in ",".join(imports.get(b, [])) or Path(a).stem in "".join(
                    imports.get(b, [])):
                shared.append(f"{b} imports {a}")

    propagation = []
    for rel, defs in symbols.items():
        users = [other for other in involved if other != rel
                 and any(d in _read(base, other) for d in defs[:8])]
        if users:
            propagation.append({"file": rel, "propagates_to": users})

    return {
        "files_involved": involved,
        "symbols_involved": symbols,
        "call_relationships": calls[:40],
        "shared_interfaces": shared[:20],
        "tests_covering_each_file": tests_covering,
        "expected_change_propagation": propagation,
    }


def missing_coupled_files(edits: list, dep_map: dict) -> list[str]:
    """Files that the dependency map says are coupled but the patch omits."""
    involved = list(dep_map.get("files_involved") or [])
    if len(involved) < 2:
        return []
    touched = {e.get("file", "").replace("\\", "/") for e in (edits or [])
               if isinstance(e, dict)}
    if not touched:
        return list(involved)
    # If the patch touches one producer/consumer pair member, require all
    # involved src files (not tests) that import each other.
    src_involved = [f for f in involved
                    if "test" not in f.lower() and f.endswith(".py")]
    if len(src_involved) >= 2 and touched & set(src_involved):
        return [f for f in src_involved if f not in touched]
    return []


def format_dep_map(dep_map: dict) -> str:
    lines = ["Multi-file dependency map (do not assume a single-file patch):"]
    lines.append("files_involved: " + ", ".join(
        dep_map.get("files_involved") or []))
    for rel, syms in (dep_map.get("symbols_involved") or {}).items():
        lines.append(f"  symbols {rel}: {', '.join(syms[:12])}")
    for s in (dep_map.get("shared_interfaces") or [])[:8]:
        lines.append(f"  shared: {s}")
    for p in (dep_map.get("expected_change_propagation") or [])[:6]:
        lines.append(f"  propagation {p.get('file')} -> "
                     f"{p.get('propagates_to')}")
    return "\n".join(lines)
