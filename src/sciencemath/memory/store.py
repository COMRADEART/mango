"""SQLite WAL memory store. All DML uses parameterized queries.

Python sqlite3: https://docs.python.org/3/library/sqlite3.html
SQLite WAL: https://www.sqlite.org/wal.html
SQLite FTS5: https://www.sqlite.org/fts5.html
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sciencemath.memory.cache import RetrievalCache
from sciencemath.memory.limits import MemoryLimits, SCHEMA_VERSION
from sciencemath.memory.models import MemoryRecord, content_sha
from sciencemath.memory.normalize import (
    extract_value, normalize_content, subject_key, value_key,
)
from sciencemath.memory.paths import assert_runtime_path, default_db_path
from sciencemath.memory.schema import SCHEMA_STATEMENTS_V1

_COLS = (
    "memory_id", "owner_id", "scope_type", "scope_id", "memory_type",
    "content", "normalized_content", "subject_key", "value_key",
    "source_type", "source_reference", "provenance", "confidence",
    "created_at", "updated_at", "valid_from", "valid_until",
    "last_accessed_at", "status", "revision", "lineage_id",
    "predecessor_id", "content_hash", "sensitivity", "write_reason",
    "instruction_authority",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row_record(row: sqlite3.Row) -> MemoryRecord:
    prov = row["provenance"]
    try:
        provenance = json.loads(prov) if isinstance(prov, str) else (prov or {})
    except json.JSONDecodeError:
        provenance = {"raw": prov, "parse_error": True}
    return MemoryRecord(
        memory_id=row["memory_id"],
        owner_id=row["owner_id"],
        scope_type=row["scope_type"],
        scope_id=row["scope_id"],
        memory_type=row["memory_type"],
        content=row["content"],
        normalized_content=row["normalized_content"],
        source_type=row["source_type"],
        source_reference=row["source_reference"],
        provenance=provenance if isinstance(provenance, dict) else {},
        confidence=row["confidence"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        last_accessed_at=row["last_accessed_at"],
        status=row["status"],
        revision=int(row["revision"]),
        content_hash=row["content_hash"],
        sensitivity=row["sensitivity"],
        write_reason=row["write_reason"],
        subject_key=row["subject_key"],
        value_key=row["value_key"],
        lineage_id=row["lineage_id"],
        predecessor_id=row["predecessor_id"],
        instruction_authority=0,
    )


class MemoryStore:
    """Local transactional SQLite store. Not a cloud or vector DB."""

    def __init__(self, path: str | Path | None = None, *,
                 limits: MemoryLimits | None = None,
                 allow_fixture: bool = False,
                 clock=utcnow):
        self.limits = limits or MemoryLimits()
        self.clock = clock
        raw = Path(path) if path is not None else default_db_path()
        if str(raw) == ":memory:":
            self.path = Path(":memory:")
            db = ":memory:"
        else:
            self.path = assert_runtime_path(raw, allow_fixture=allow_fixture)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = str(self.path)
        self._conn = sqlite3.connect(
            db, timeout=self.limits.connect_timeout_s,
            isolation_level="DEFERRED")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # PRAGMA does not take bound parameters; timeout is an int limit.
        self._conn.execute(
            "PRAGMA busy_timeout = %d" % int(self.limits.busy_timeout_ms))
        if db != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()
        self.cache = RetrievalCache(self.limits.max_cache_entries)
        self.fts_available = self._probe_fts()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def _migrate(self) -> None:
        with self._conn:
            for stmt in SCHEMA_STATEMENTS_V1:
                self._conn.execute(stmt)
            cur = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
            current = int(cur.fetchone()[0])
            if current < SCHEMA_VERSION:
                self._conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (SCHEMA_VERSION, self.clock()))
            gen = self._conn.execute(
                "SELECT v FROM meta WHERE k = ?", ("generation",)).fetchone()
            if gen is None:
                self._conn.execute(
                    "INSERT INTO meta(k, v) VALUES (?, ?)", ("generation", "0"))

    def _probe_fts(self) -> bool:
        try:
            self._conn.execute(
                "SELECT 1 FROM memories_fts LIMIT 1")
            return True
        except sqlite3.OperationalError:
            return False

    def generation(self) -> int:
        row = self._conn.execute(
            "SELECT v FROM meta WHERE k = ?", ("generation",)).fetchone()
        return int(row["v"]) if row else 0

    def _bump(self) -> int:
        self._conn.execute(
            "UPDATE meta SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT) "
            "WHERE k = ?", ("generation",))
        self.cache.invalidate()
        return self.generation()

    def _retry(self, fn):
        last = None
        for i in range(self.limits.max_db_retry):
            try:
                return fn()
            except sqlite3.OperationalError as e:
                last = e
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    time.sleep(0.01 * (i + 1))
                    continue
                raise
        raise last

    def _audit(self, op: str, *, memory_id: str | None = None,
               owner_id: str | None = None, scope_type: str | None = None,
               scope_id: str | None = None, details: dict | None = None) -> None:
        blob = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        if "content" in (details or {}):
            # never persist deleted/full content in audit
            details = dict(details)
            details.pop("content", None)
            blob = json.dumps(details, ensure_ascii=False, sort_keys=True)
        self._conn.execute(
            "INSERT INTO audit_log(ts, op, memory_id, owner_id, scope_type, "
            "scope_id, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.clock(), op, memory_id, owner_id, scope_type, scope_id, blob))

    def _fts_upsert(self, rec: MemoryRecord) -> None:
        if not self.fts_available:
            return
        rows = self._conn.execute(
            "SELECT rowid FROM memories_fts WHERE memory_id = ?",
            (rec.memory_id,)).fetchall()
        for r in rows:
            self._conn.execute(
                "DELETE FROM memories_fts WHERE rowid = ?", (r[0],))
        if rec.status == "ACTIVE":
            self._conn.execute(
                "INSERT INTO memories_fts(memory_id, content, "
                "normalized_content, subject_key) VALUES (?, ?, ?, ?)",
                (rec.memory_id, rec.content, rec.normalized_content,
                 rec.subject_key))

    def _fts_delete(self, memory_id: str) -> None:
        if not self.fts_available:
            return
        # FTS5 deletes are rowid-based.
        # https://www.sqlite.org/fts5.html#the_delete_command
        rows = self._conn.execute(
            "SELECT rowid FROM memories_fts WHERE memory_id = ?",
            (memory_id,)).fetchall()
        for r in rows:
            self._conn.execute(
                "DELETE FROM memories_fts WHERE rowid = ?", (r[0],))

    def expire_due(self, now: str | None = None) -> int:
        now = now or self.clock()

        def _do():
            with self._conn:
                rows = self._conn.execute(
                    "SELECT memory_id FROM memories WHERE status = 'ACTIVE' "
                    "AND valid_until IS NOT NULL AND valid_until <= ?",
                    (now,)).fetchall()
                n = 0
                for r in rows:
                    self._conn.execute(
                        "UPDATE memories SET status = 'EXPIRED', "
                        "updated_at = ? WHERE memory_id = ?",
                        (now, r["memory_id"]))
                    self._fts_delete(r["memory_id"])
                    self._audit("MEMORY_EXPIRED", memory_id=r["memory_id"],
                                details={"valid_until_passed": True})
                    n += 1
                if n:
                    self._bump()
                return n

        return self._retry(_do)

    def get(self, memory_id: str, *, owner_id: str,
            include_deleted: bool = False) -> MemoryRecord | None:
        self.expire_due()
        if include_deleted:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE memory_id = ? AND owner_id = ?",
                (memory_id, owner_id)).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE memory_id = ? AND owner_id = ? "
                "AND status != 'DELETED'",
                (memory_id, owner_id)).fetchone()
        if row is None:
            return None
        if row["status"] == "DELETED":
            return None
        rec = _row_record(row)
        if rec.status == "ACTIVE":
            self._conn.execute(
                "UPDATE memories SET last_accessed_at = ? WHERE memory_id = ?",
                (self.clock(), memory_id))
        return rec

    def insert_record(self, rec: MemoryRecord) -> MemoryRecord:
        def _do():
            with self._conn:
                self._conn.execute(
                    "INSERT INTO memories(" + ",".join(_COLS) + ") VALUES ("
                    + ",".join("?" for _ in _COLS) + ")",
                    (
                        rec.memory_id, rec.owner_id, rec.scope_type,
                        rec.scope_id, rec.memory_type, rec.content,
                        rec.normalized_content, rec.subject_key, rec.value_key,
                        rec.source_type, rec.source_reference,
                        json.dumps(rec.provenance, ensure_ascii=False,
                                   sort_keys=True),
                        rec.confidence, rec.created_at, rec.updated_at,
                        rec.valid_from, rec.valid_until, rec.last_accessed_at,
                        rec.status, rec.revision, rec.lineage_id,
                        rec.predecessor_id, rec.content_hash, rec.sensitivity,
                        rec.write_reason, 0,
                    ))
                self._fts_upsert(rec)
                self._audit("MEMORY_STORE", memory_id=rec.memory_id,
                            owner_id=rec.owner_id, scope_type=rec.scope_type,
                            scope_id=rec.scope_id,
                            details={"write_reason": rec.write_reason,
                                     "content_hash": rec.content_hash,
                                     "revision": rec.revision})
                self._bump()
            return rec

        return self._retry(_do)

    def set_status(self, memory_id: str, status: str, *,
                   owner_id: str, now: str | None = None) -> None:
        now = now or self.clock()

        def _do():
            with self._conn:
                self._conn.execute(
                    "UPDATE memories SET status = ?, updated_at = ? "
                    "WHERE memory_id = ? AND owner_id = ?",
                    (status, now, memory_id, owner_id))
                if status != "ACTIVE":
                    self._fts_delete(memory_id)
                else:
                    row = self._conn.execute(
                        "SELECT * FROM memories WHERE memory_id = ?",
                        (memory_id,)).fetchone()
                    if row:
                        self._fts_upsert(_row_record(row))
                self._bump()

        self._retry(_do)

    def find_active_duplicates(self, *, owner_id: str, scope_type: str,
                               scope_id: str, subject_key_v: str,
                               value_key_v: str) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE owner_id = ? AND scope_type = ? "
            "AND scope_id = ? AND subject_key = ? AND value_key = ? "
            "AND status = 'ACTIVE'",
            (owner_id, scope_type, scope_id, subject_key_v, value_key_v)
        ).fetchall()
        return [_row_record(r) for r in rows]

    def find_active_subject(self, *, owner_id: str, scope_type: str,
                            scope_id: str, subject_key_v: str
                            ) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE owner_id = ? AND scope_type = ? "
            "AND scope_id = ? AND subject_key = ? AND status = 'ACTIVE'",
            (owner_id, scope_type, scope_id, subject_key_v)).fetchall()
        return [_row_record(r) for r in rows]

    def list_scope(self, *, owner_id: str, scope_type: str, scope_id: str,
                   status: str = "ACTIVE") -> list[MemoryRecord]:
        self.expire_due()
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE owner_id = ? AND scope_type = ? "
            "AND scope_id = ? AND status = ? ORDER BY updated_at DESC",
            (owner_id, scope_type, scope_id, status)).fetchall()
        return [_row_record(r) for r in rows]

    def candidates(self, *, owner_id: str, scope_type: str, scope_id: str,
                   allow_global: bool = False,
                   limit: int | None = None) -> list[MemoryRecord]:
        self.expire_due()
        lim = min(limit or self.limits.max_candidates,
                  self.limits.max_candidates)
        if allow_global:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE owner_id = ? AND status = "
                "'ACTIVE' AND ((scope_type = 'GLOBAL_USER') OR "
                "(scope_type = ? AND scope_id = ?)) "
                "ORDER BY updated_at DESC LIMIT ?",
                (owner_id, scope_type, scope_id, lim)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE owner_id = ? AND scope_type = ? "
                "AND scope_id = ? AND status = 'ACTIVE' "
                "ORDER BY updated_at DESC LIMIT ?",
                (owner_id, scope_type, scope_id, lim)).fetchall()
        return [_row_record(r) for r in rows]

    def fts_query(self, query: str, *, owner_id: str, scope_type: str,
                  scope_id: str, allow_global: bool = False,
                  limit: int | None = None) -> list[tuple[MemoryRecord, float]]:
        self.expire_due()
        lim = min(limit or self.limits.max_candidates,
                  self.limits.max_candidates)
        q = (query or "").strip()
        if not q or not self.fts_available:
            return [(c, 0.0) for c in self.candidates(
                owner_id=owner_id, scope_type=scope_type, scope_id=scope_id,
                allow_global=allow_global, limit=lim)]
        # FTS5 MATCH binds as a parameter (literal user data, not SQL).
        match = " OR ".join(
            '"' + t.replace('"', "") + '"' for t in q.split()[:12] if t)
        if not match:
            match = '"' + q.replace('"', "")[:80] + '"'
        try:
            if allow_global:
                rows = self._conn.execute(
                    "SELECT m.*, bm25(memories_fts) AS rnk "
                    "FROM memories_fts JOIN memories m "
                    "ON m.memory_id = memories_fts.memory_id "
                    "WHERE memories_fts MATCH ? AND m.owner_id = ? "
                    "AND m.status = 'ACTIVE' AND "
                    "((m.scope_type = 'GLOBAL_USER') OR "
                    "(m.scope_type = ? AND m.scope_id = ?)) "
                    "ORDER BY rnk LIMIT ?",
                    (match, owner_id, scope_type, scope_id, lim)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT m.*, bm25(memories_fts) AS rnk "
                    "FROM memories_fts JOIN memories m "
                    "ON m.memory_id = memories_fts.memory_id "
                    "WHERE memories_fts MATCH ? AND m.owner_id = ? "
                    "AND m.scope_type = ? AND m.scope_id = ? "
                    "AND m.status = 'ACTIVE' ORDER BY rnk LIMIT ?",
                    (match, owner_id, scope_type, scope_id, lim)).fetchall()
        except sqlite3.OperationalError:
            return [(c, 0.0) for c in self.candidates(
                owner_id=owner_id, scope_type=scope_type, scope_id=scope_id,
                allow_global=allow_global, limit=lim)]
        out = []
        for r in rows:
            rec = _row_record(r)
            rnk = float(r["rnk"] if r["rnk"] is not None else 0.0)
            # bm25: more negative is better in FTS5; convert to 0..1-ish
            score = 1.0 / (1.0 + abs(rnk))
            out.append((rec, score))
        return out

    def delete(self, memory_id: str, *, owner_id: str,
               reason: str = "USER_DELETE") -> bool:
        now = self.clock()

        def _do():
            with self._conn:
                row = self._conn.execute(
                    "SELECT * FROM memories WHERE memory_id = ? "
                    "AND owner_id = ?",
                    (memory_id, owner_id)).fetchone()
                if row is None:
                    return False
                prev_hash = row["content_hash"]
                self._conn.execute(
                    "UPDATE memories SET status = 'DELETED', content = '', "
                    "normalized_content = '', value_key = '', "
                    "updated_at = ? WHERE memory_id = ? AND owner_id = ?",
                    (now, memory_id, owner_id))
                self._fts_delete(memory_id)
                self._conn.execute(
                    "INSERT OR REPLACE INTO tombstones("
                    "memory_id, deletion_time, previous_content_hash, "
                    "deletion_reason) VALUES (?, ?, ?, ?)",
                    (memory_id, now, prev_hash, reason))
                self._audit("MEMORY_DELETE", memory_id=memory_id,
                            owner_id=owner_id,
                            details={"previous_content_hash": prev_hash,
                                     "deletion_reason": reason})
                self._bump()
                return True

        return bool(self._retry(_do))

    def forget_scope(self, *, owner_id: str, scope_type: str,
                     scope_id: str) -> int:
        now = self.clock()

        def _do():
            with self._conn:
                rows = self._conn.execute(
                    "SELECT memory_id, content_hash FROM memories "
                    "WHERE owner_id = ? AND scope_type = ? AND scope_id = ? "
                    "AND status != 'DELETED'",
                    (owner_id, scope_type, scope_id)).fetchall()
                n = 0
                for r in rows:
                    self._conn.execute(
                        "UPDATE memories SET status = 'DELETED', content = '', "
                        "normalized_content = '', value_key = '', "
                        "updated_at = ? WHERE memory_id = ?",
                        (now, r["memory_id"]))
                    self._fts_delete(r["memory_id"])
                    self._conn.execute(
                        "INSERT OR REPLACE INTO tombstones("
                        "memory_id, deletion_time, previous_content_hash, "
                        "deletion_reason) VALUES (?, ?, ?, ?)",
                        (r["memory_id"], now, r["content_hash"],
                         "FORGET_SCOPE"))
                    n += 1
                self._audit("MEMORY_FORGET_SCOPE", owner_id=owner_id,
                            scope_type=scope_type, scope_id=scope_id,
                            details={"count": n})
                if n:
                    self._bump()
                return n

        return int(self._retry(_do))

    def record_conflict(self, *, owner_id: str, scope_type: str, scope_id: str,
                        subject: str, recs: list[MemoryRecord],
                        temporal: str | None) -> str:
        cid = "cfl_" + uuid.uuid4().hex[:12]
        now = self.clock()

        def _do():
            with self._conn:
                self._conn.execute(
                    "INSERT INTO conflicts(conflict_id, owner_id, scope_type, "
                    "scope_id, subject_key, memory_ids, values_json, "
                    "timestamps, sources, confidences, possible_temporal, "
                    "created_at, status) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cid, owner_id, scope_type, scope_id, subject,
                     json.dumps([r.memory_id for r in recs]),
                     json.dumps([r.content for r in recs],
                                ensure_ascii=False),
                     json.dumps([r.created_at for r in recs]),
                     json.dumps([r.source_type for r in recs]),
                     json.dumps([r.confidence for r in recs]),
                     temporal, now, "OPEN"))
                self._audit("MEMORY_CONFLICT", owner_id=owner_id,
                            scope_type=scope_type, scope_id=scope_id,
                            details={"conflict_id": cid,
                                     "memory_ids": [r.memory_id for r in recs]})
            return cid

        return self._retry(_do)

    def fts_has(self, memory_id: str) -> bool:
        if not self.fts_available:
            return False
        row = self._conn.execute(
            "SELECT memory_id FROM memories_fts WHERE memory_id = ?",
            (memory_id,)).fetchone()
        return row is not None

    def audit_has_content(self, needle: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM audit_log WHERE details LIKE ? LIMIT 1",
            ("%" + needle + "%",)).fetchone()
        return row is not None

    def new_id(self) -> str:
        return "mem_" + uuid.uuid4().hex[:16]


def build_record(*, owner_id: str, scope_type: str, scope_id: str,
                 memory_type: str, content: str, write_reason: str,
                 source_type: str, source_reference: str | None,
                 provenance: dict, confidence: str, sensitivity: str,
                 store: MemoryStore, subject: str | None = None,
                 value: str | None = None, valid_from: str | None = None,
                 valid_until: str | None = None, lineage_id: str | None = None,
                 predecessor_id: str | None = None, revision: int = 1,
                 now: str | None = None, memory_id: str | None = None
                 ) -> MemoryRecord:
    now = now or store.clock()
    norm = normalize_content(content)
    sk = subject_key(subject, content, scope_id=scope_id)
    vk = value_key(value or extract_value(content), content)
    mid = memory_id or store.new_id()
    lid = lineage_id or mid
    return MemoryRecord(
        memory_id=mid,
        owner_id=owner_id,
        scope_type=scope_type,
        scope_id=scope_id,
        memory_type=memory_type,
        content=content,
        normalized_content=norm,
        source_type=source_type,
        source_reference=source_reference,
        provenance=provenance,
        confidence=confidence,
        created_at=now,
        updated_at=now,
        valid_from=valid_from or now,
        valid_until=valid_until,
        last_accessed_at=None,
        status="ACTIVE",
        revision=revision,
        content_hash=content_sha(norm),
        sensitivity=sensitivity,
        write_reason=write_reason,
        subject_key=sk,
        value_key=vk,
        lineage_id=lid,
        predecessor_id=predecessor_id,
        instruction_authority=0,
    )
