"""Shared helpers for the scripts/ entry points: repo-root-relative paths and
config loading, independent of the current working directory."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CONFIG_DIR = REPO_ROOT / "configs"
DATA_DIR = REPO_ROOT / "data"


def load_configs() -> dict:
    """Load all config YAMLs into one dict keyed by config name."""
    from sciencemath.utils.io_utils import load_yaml

    cfg = {}
    for name in ("model", "training", "data", "rag"):
        path = CONFIG_DIR / f"{name}.yaml"
        if path.exists():
            merged = cfg.setdefault(name, {})
            merged.update(load_yaml(path) or {})
    return cfg


def setup_logging(name: str = "sciencemath"):
    from sciencemath.utils.logging_setup import setup_logging as _setup

    return _setup(REPO_ROOT / "training" / "logs", name=name)