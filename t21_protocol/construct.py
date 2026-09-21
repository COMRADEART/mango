"""CLI alias for the production construction-only phase API."""
from __future__ import annotations

from .construction import main, run_construction

__all__ = ["main", "run_construction"]


if __name__ == "__main__":
    raise SystemExit(main())
