"""JSON/JSONL helpers with explicit UTF-8 handling (Windows-safe)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_REPO_ROOT: Path | None = None


def find_repo_root() -> Path:
    """Locate the repository root (dir containing pyproject.toml).

    Walks up from this file's package location, then from the CWD as a
    fallback (pip-installed package outside a checkout). Cached."""
    global _REPO_ROOT
    if _REPO_ROOT is not None:
        return _REPO_ROOT
    for start in (Path(__file__).resolve().parent, Path.cwd()):
        for candidate in [start, *start.parents]:
            if (candidate / "pyproject.toml").exists():
                _REPO_ROOT = candidate
                return _REPO_ROOT
    raise FileNotFoundError("repository root (pyproject.toml) not found")


def read_jsonl(path: str | os.PathLike) -> list[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return out


def write_jsonl(path: str | os.PathLike, records: list[dict], atomic: bool = True) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not atomic:
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_json(path: str | os.PathLike) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | os.PathLike, obj, atomic: bool = True) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not atomic:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_yaml(path: str | os.PathLike) -> dict:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)