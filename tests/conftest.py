"""Pytest configuration: repo-root path exposure and src import bootstrapping
(works whether or not the package is pip-installed)."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SRC_DIR))