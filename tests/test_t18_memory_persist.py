"""Restart persistence, transactions, concurrency, index consistency."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from sciencemath.memory.contract import MEMORY_NO_MATCH, MEMORY_RETRIEVE
from sciencemath.memory.pipeline import handle
from sciencemath.memory.store import MemoryStore


def test_restart_persistence_cycle(tmp_path):
    path = tmp_path / "p.sqlite"
    s = MemoryStore(path)
    handle("Remember that city is Lisbon.", store=s, owner_id="u",
           scope_type="GLOBAL_USER", scope_id="u", user_explicit=True)
    s.close()
    s2 = MemoryStore(path)
    q = handle("What city?", store=s2, owner_id="u",
               scope_type="GLOBAL_USER", scope_id="u")
    assert q.status == MEMORY_RETRIEVE
    assert "Lisbon" in q.answer
    s2.close()


def test_one_hundred_restart_cycles(tmp_path):
    path = tmp_path / "loop.sqlite"
    for i in range(100):
        s = MemoryStore(path)
        handle(f"Remember that counter is {i}.", store=s, owner_id="u",
               scope_type="SESSION", scope_id="loop", user_explicit=True,
               subject="counter", op="MEMORY_SUPERSEDE")
        s.close()
        s2 = MemoryStore(path)
        q = handle("counter", store=s2, owner_id="u",
                   scope_type="SESSION", scope_id="loop")
        assert str(i) in q.answer
        if i % 10 == 0:
            handle("delete", store=s2, owner_id="u", scope_type="SESSION",
                   scope_id="loop",
                   memory_id=q.memories[0].memory_id, op="MEMORY_DELETE")
            q2 = handle("counter", store=s2, owner_id="u",
                        scope_type="SESSION", scope_id="loop")
            # after delete, next loop will write again
            assert q2.status == MEMORY_NO_MATCH or str(i) not in q2.answer \
                or not q2.memories
        s2.close()


def test_transaction_rollback(tmp_path):
    path = tmp_path / "tx.sqlite"
    s = MemoryStore(path)
    handle("Remember that ok is yes.", store=s, owner_id="u",
           scope_type="SESSION", scope_id="s", user_explicit=True)
    before = s.generation()
    try:
        def boom():
            with s._conn:
                s._conn.execute(
                    "INSERT INTO memories(memory_id, owner_id, scope_type, "
                    "scope_id, memory_type, content, normalized_content, "
                    "subject_key, value_key, source_type, provenance, "
                    "confidence, created_at, updated_at, status, revision, "
                    "lineage_id, content_hash, sensitivity, write_reason, "
                    "instruction_authority) VALUES ("
                    "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("mem_partial", "u", "SESSION", "s", "USER_FACT",
                     "partial", "partial", "x", "y", "USER", "{}",
                     "HIGH", "t", "t", "ACTIVE", 1, "mem_partial",
                     "h", "GENERAL", "USER_EXPLICIT_SAVE", 0))
                raise sqlite3.OperationalError("simulated interrupt")
        try:
            boom()
        except sqlite3.OperationalError:
            pass
    finally:
        row = s._conn.execute(
            "SELECT 1 FROM memories WHERE memory_id = ?",
            ("mem_partial",)).fetchone()
        assert row is None
        q = handle("ok", store=s, owner_id="u", scope_type="SESSION",
                   scope_id="s")
        assert "yes" in q.answer
        assert s.generation() == before
    s.close()


def test_two_readers_one_writer(tmp_path):
    path = tmp_path / "c.sqlite"
    s = MemoryStore(path)
    handle("Remember that flag is green.", store=s, owner_id="u",
           scope_type="PROJECT", scope_id="p", user_explicit=True)
    s.close()
    err = []

    def reader():
        st = MemoryStore(path)
        try:
            q = handle("flag", store=st, owner_id="u",
                       scope_type="PROJECT", scope_id="p")
            if "green" not in q.answer and "blue" not in q.answer:
                err.append("miss")
        finally:
            st.close()

    def writer():
        st = MemoryStore(path)
        try:
            handle("Remember that flag is blue.", store=st, owner_id="u",
                   scope_type="PROJECT", scope_id="p", user_explicit=True,
                   subject="flag", op="MEMORY_SUPERSEDE")
        except Exception as e:  # noqa: BLE001
            err.append(str(e))
        finally:
            st.close()

    threads = [threading.Thread(target=reader) for _ in range(2)]
    threads.append(threading.Thread(target=writer))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert err == []
    s2 = MemoryStore(path)
    q = handle("flag", store=s2, owner_id="u", scope_type="PROJECT",
               scope_id="p")
    assert q.status in (MEMORY_RETRIEVE, "MEMORY_SUPERSEDE") or q.memories
    s2.close()


def test_index_agrees_after_mutations(tmp_path):
    path = tmp_path / "idx.sqlite"
    s = MemoryStore(path)
    r = handle("Remember that topic is hydrology.",
               store=s, owner_id="u", scope_type="PROJECT", scope_id="p",
               user_explicit=True, subject="topic")
    mid = r.memories[0].memory_id
    assert s.fts_has(mid)
    handle("Correction: topic is limnology.",
           store=s, owner_id="u", scope_type="PROJECT", scope_id="p",
           user_explicit=True, subject="topic", op="MEMORY_SUPERSEDE")
    assert not s.fts_has(mid)  # superseded removed from FTS
    active = s.list_scope(owner_id="u", scope_type="PROJECT", scope_id="p")
    assert len(active) == 1
    assert s.fts_has(active[0].memory_id)
    s.close()
