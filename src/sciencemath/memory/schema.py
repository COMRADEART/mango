"""Deterministic schema migrations for the local SQLite memory store.

Python sqlite3 executes parameterized DML only. DDL here is constant SQL
authored in-repo — never concatenated with user content.
Source: https://docs.python.org/3/library/sqlite3.html
SQLite WAL: https://www.sqlite.org/wal.html
FTS5: https://www.sqlite.org/fts5.html
"""
from __future__ import annotations

SCHEMA_STATEMENTS_V1 = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        k TEXT PRIMARY KEY,
        v TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY,
        memory_id TEXT NOT NULL UNIQUE,
        owner_id TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        content TEXT NOT NULL,
        normalized_content TEXT NOT NULL,
        subject_key TEXT NOT NULL,
        value_key TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_reference TEXT,
        provenance TEXT NOT NULL,
        confidence TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        last_accessed_at TEXT,
        status TEXT NOT NULL,
        revision INTEGER NOT NULL,
        lineage_id TEXT NOT NULL,
        predecessor_id TEXT,
        content_hash TEXT NOT NULL,
        sensitivity TEXT NOT NULL,
        write_reason TEXT NOT NULL,
        instruction_authority INTEGER NOT NULL DEFAULT 0
            CHECK (instruction_authority = 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tombstones (
        memory_id TEXT PRIMARY KEY,
        deletion_time TEXT NOT NULL,
        previous_content_hash TEXT NOT NULL,
        deletion_reason TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        op TEXT NOT NULL,
        memory_id TEXT,
        owner_id TEXT,
        scope_type TEXT,
        scope_id TEXT,
        details TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conflicts (
        conflict_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        subject_key TEXT NOT NULL,
        memory_ids TEXT NOT NULL,
        values_json TEXT NOT NULL,
        timestamps TEXT NOT NULL,
        sources TEXT NOT NULL,
        confidences TEXT NOT NULL,
        possible_temporal TEXT,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mem_owner_scope_status
        ON memories(owner_id, scope_type, scope_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mem_subject
        ON memories(owner_id, subject_key, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mem_hash
        ON memories(content_hash)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mem_lineage
        ON memories(lineage_id, revision)
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        memory_id UNINDEXED,
        content,
        normalized_content,
        subject_key,
        tokenize = 'unicode61'
    )
    """,
)
