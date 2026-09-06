"""source_registry — license/usage gating for scientific sources (T5.1).

Deny by default. Nothing enters Mango's local scientific corpus unless
its usage status is explicit in data/science_sources/source_registry.json.

Gate rules (mirror data/science_sources/LICENSE_MANIFEST.md):
  1. unknown source_id            -> denied for every usage
  2. missing/unknown status       -> denied
  3. REVIEW_REQUIRED / BLOCKED    -> denied for retrieval and indexing
  4. RETRIEVAL_ONLY               -> live retrieval allowed, indexing denied
  5. APPROVED without the specific approved_for_* flag -> that usage denied
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sciencemath.utils.io_utils import find_repo_root

DEFAULT_REGISTRY_PATH = (
    find_repo_root() / "data" / "science_sources" / "source_registry.json"
)

STATUSES = ("APPROVED", "RETRIEVAL_ONLY", "REVIEW_REQUIRED", "BLOCKED")
USAGES = ("local_index", "redistribution", "training", "retrieval")


class SourceRegistryError(RuntimeError):
    """Raised when the registry file is malformed."""


class SourceRegistry:
    """Deny-by-default gate over the scientific source registry."""

    def __init__(self, registry_path: str | Path = DEFAULT_REGISTRY_PATH):
        self.path = Path(registry_path)
        self._sources: dict[str, dict] = {}
        self._policy: dict = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise SourceRegistryError(
                f"source registry not found: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        policy = data.get("policy", {})
        if not policy.get("deny_by_default", False):
            raise SourceRegistryError(
                "registry policy must set deny_by_default=true")
        for src in data.get("sources", []):
            sid = src.get("source_id")
            if not sid or sid in self._sources:
                raise SourceRegistryError(f"duplicate/missing source_id: {sid!r}")
            if src.get("status") not in STATUSES:
                raise SourceRegistryError(
                    f"source {sid} has invalid status {src.get('status')!r}")
            self._sources[sid] = src
        self._policy = policy

    # -- queries -----------------------------------------------------------
    def get(self, source_id: str) -> dict | None:
        return self._sources.get(source_id)

    def source_ids(self) -> list[str]:
        return sorted(self._sources)

    def sources_with_status(self, *statuses: str) -> list[dict]:
        return [s for s in self._sources.values() if s["status"] in statuses]

    def allows(self, source_id: str, usage: str) -> bool:
        """Deny-by-default usage check. usage in USAGES."""
        if usage not in USAGES:
            return False  # unknown usage category -> deny
        src = self._sources.get(source_id)
        if src is None:
            return False          # rule 1
        status = src["status"]
        if status == "BLOCKED" or status == "REVIEW_REQUIRED":
            return False          # rules 2-3
        if usage == "retrieval":
            return True           # APPROVED and RETRIEVAL_ONLY may be queried
        if status == "RETRIEVAL_ONLY":
            return False          # rule 4: no durable anything
        # status == APPROVED: require the explicit flag
        return bool(src.get(f"approved_for_{usage}", False))

    def require(self, source_id: str, usage: str) -> None:
        """Raise LicenseGateError if the usage is denied."""
        if not self.allows(source_id, usage):
            raise LicenseGateError(
                f"usage {usage!r} of source {source_id!r} is denied by the "
                f"license gate ({self.path.name})")


class LicenseGateError(PermissionError):
    """A source/usage combination failed the deny-by-default gate."""


@lru_cache(maxsize=8)
def _default_registry(path: str) -> SourceRegistry:
    return SourceRegistry(Path(path))


def default_registry() -> SourceRegistry:
    """Shared SourceRegistry instance (loads the repo registry once)."""
    return _default_registry(str(DEFAULT_REGISTRY_PATH))