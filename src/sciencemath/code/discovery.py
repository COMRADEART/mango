"""T15.4 — repository discovery (inspect structure before editing).

Discovers: directory structure, filenames, language detection, package
manifests, build/test configuration, major entry points, dependency
declarations, generated/vendor dirs. Never searches .git objects, model
artifacts, build caches, venvs, node_modules, or generated output unless
explicitly required.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sciencemath.code.context import RepoContext

SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt",
    "vendor", "third_party", ".idea", ".vscode", "artifacts",
})
SKIP_SUFFIXES = (".safetensors", ".bin", ".pt", ".onnx", ".pyc", ".pyo")

LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
    ".rs": "rust", ".java": "java", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby",
    ".php": "php", ".swift": "swift", ".kt": "kotlin", ".md": "markdown",
    ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
}

MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
             "package.json", "Cargo.toml", "go.mod", "pom.xml",
             "build.gradle", "Gemfile", "composer.json")

MAX_FILES = 5000


def _git(args: list, root: Path) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                           text=True, timeout=15, encoding="utf-8",
                           errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def discover_repo(root: str | Path, *, max_files: int = MAX_FILES) -> RepoContext:
    """Bounded discovery of a repository. Pure inspection, no mutation."""
    base = Path(root).resolve()
    ctx = RepoContext(repository_root=str(base))
    if not base.is_dir():
        ctx.notes = ("repository_root is not a directory",)
        return ctx

    ctx.git_head = _git(["rev-parse", "HEAD"], base) or "UNKNOWN"
    ctx.branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], base) or "UNKNOWN"
    porcelain = _git(["status", "--porcelain"], base)
    dirty = [ln[3:].strip() for ln in porcelain.splitlines() if ln.strip()]
    ctx.worktree_status = "CLEAN" if not dirty else "DIRTY"
    ctx.dirty_files = tuple(dirty[:50])

    files: list[Path] = []
    for p in sorted(base.rglob("*")):
        if len(files) >= max_files:
            ctx.notes = (*ctx.notes, f"file cap reached at {max_files}",)
            break
        rel = p.relative_to(base)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_dir():
            continue
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(p)

    langs: dict[str, int] = {}
    for p in files:
        lang = LANGUAGE_BY_SUFFIX.get(p.suffix.lower())
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
    ctx.languages = tuple(sorted(langs, key=lambda k: -langs[k]))

    rels = [f.relative_to(base).as_posix() for f in files]
    relset = set(rels)
    ctx.config_files = tuple(sorted(r for r in rels
                                    if Path(r).name in MANIFESTS
                                    or r.endswith((".cfg", ".ini"))))
    if "pyproject.toml" in relset or "setup.py" in relset:
        ctx.package_system = "python"
    elif "package.json" in relset:
        ctx.package_system = "node"
    elif "Cargo.toml" in relset:
        ctx.package_system = "cargo"
    elif "go.mod" in relset:
        ctx.package_system = "go"

    if "pyproject.toml" in relset:
        ctx.build_system = "setuptools/pyproject"
    elif "package.json" in relset:
        ctx.build_system = "npm"

    test_hits = [r for r in rels if "/tests/" in f"/{r}" or r.startswith("tests/")
                 or Path(r).name.startswith(("test_", "conftest"))]
    if any(r.endswith((".py",)) for r in test_hits):
        ctx.test_framework = "pytest"
    elif any(r.endswith((".js", ".ts")) for r in test_hits):
        ctx.test_framework = "node-test"
    ctx.test_dirs = tuple(sorted({r.split("/")[0] for r in test_hits
                                  if "/" in r} or (["tests"] if test_hits else [])))
    src_dirs = {r.split("/")[0] for r in rels
                if r.split("/")[0] in ("src", "lib", "app", "pkg", "mango")}
    ctx.source_dirs = tuple(sorted(src_dirs))

    entries = [r for r in rels if Path(r).name in (
        "__main__.py", "main.py", "app.py", "index.js", "main.go",
        "main.rs", "cli.py") or r.endswith("/__init__.py") and r.count("/") == 1]
    ctx.entry_points = tuple(sorted(entries[:20]))
    return ctx
