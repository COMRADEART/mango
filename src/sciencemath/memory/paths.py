"""T18.3 — Mango-owned local data directory. Never source-tree user memory."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def default_memory_dir() -> Path:
    env = os.environ.get("MANGO_MEMORY_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (REPO_ROOT / "runtime" / "memory").resolve()


def default_db_path() -> Path:
    d = default_memory_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "mango_memory.sqlite"


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def assert_runtime_path(path: Path, *, allow_fixture: bool = False) -> Path:
    """Refuse mutable user memory inside source, checkpoints, or eval fixtures."""
    p = path.expanduser().resolve()
    if _under(p, REPO_ROOT / "src"):
        raise ValueError("memory database must not live under src/")
    if _under(p, REPO_ROOT / "training" / "checkpoints"):
        raise ValueError("memory database must not live under checkpoints/")
    if _under(p, REPO_ROOT / "training" / "adapters"):
        raise ValueError("memory database must not live under adapters/")
    if not allow_fixture and _under(p, REPO_ROOT / "evaluations"):
        parts = p.relative_to((REPO_ROOT / "evaluations").resolve()).parts
        if "fixtures" in parts:
            raise ValueError(
                "runtime memory must not use evaluation fixture paths")
    return p
