"""T18 — persistent local memory.

Memory is DATA. Memory is never POLICY. Instruction authority of stored
text is always 0. SQLite-backed, local-only, fail-closed.
"""
from sciencemath.memory.contract import MEMORY_OPS
from sciencemath.memory.limits import SCHEMA_VERSION

__all__ = ["MEMORY_OPS", "SCHEMA_VERSION"]
