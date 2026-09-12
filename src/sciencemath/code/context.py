"""T15.3 — bounded repository-context representation.

Tracks exactly: repository_root, git_head, branch, worktree_status,
languages, package/build system, test framework, source/test/config
dirs, entry points, candidate relevant files. Never ingests the whole
repository blindly; targeted discovery fills candidates on demand.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class RepoContext:
    repository_root: str = ""
    git_head: str = ""
    branch: str = ""
    worktree_status: str = "UNKNOWN"  # CLEAN | DIRTY | UNKNOWN
    dirty_files: tuple = ()
    languages: tuple = ()
    package_system: str = "UNKNOWN"
    build_system: str = "UNKNOWN"
    test_framework: str = "UNKNOWN"
    source_dirs: tuple = ()
    test_dirs: tuple = ()
    config_files: tuple = ()
    entry_points: tuple = ()
    candidate_files: tuple = ()
    notes: tuple = ()

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("dirty_files", "languages", "source_dirs", "test_dirs",
                  "config_files", "entry_points", "candidate_files", "notes"):
            d[k] = list(d[k])
        return d

    def with_candidates(self, files) -> "RepoContext":
        seen, ordered = set(self.candidate_files), list(self.candidate_files)
        for f in files:
            if f not in seen:
                seen.add(f)
                ordered.append(f)
        self.candidate_files = tuple(ordered)
        return self


REQUIRED_KEYS = ("repository_root", "git_head", "branch", "worktree_status",
                 "languages", "package_system", "test_framework",
                 "source_dirs", "test_dirs", "config_files", "entry_points",
                 "candidate_files")


def context_complete(ctx: RepoContext) -> tuple:
    """Return (complete: bool, missing: list)."""
    missing = [k for k in REQUIRED_KEYS if getattr(ctx, k, None) in ("", (), None)]
    # git_head/branch may legitimately be UNKNOWN outside a git checkout;
    # entry_points/candidate_files may legitimately be empty (discovery
    # found none / candidates are filled on demand by search).
    missing = [k for k in missing
               if k not in ("git_head", "branch", "entry_points",
                            "candidate_files")]
    return (not missing, missing)


def empty_context(root: str = "") -> RepoContext:
    return RepoContext(repository_root=root)
