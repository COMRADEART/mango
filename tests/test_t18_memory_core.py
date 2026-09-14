"""T18 unit tests: store, write gating, retrieval, isolation, lineage."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from sciencemath.memory.contract import (
    MEMORY_BLOCKED_LIMIT, MEMORY_BLOCKED_SECRET, MEMORY_CONFLICT,
    MEMORY_DELETE, MEMORY_FORGET_SCOPE, MEMORY_NO_MATCH, MEMORY_RETRIEVE,
    MEMORY_STORE, MEMORY_SUPERSEDE, classify_request,
)
from sciencemath.memory.pipeline import handle
from sciencemath.memory.store import MemoryStore, build_record
from sciencemath.memory.paths import assert_runtime_path, default_memory_dir


def _db(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "t18.sqlite")


def test_sqlite_init_and_migration(tmp_path):
    s = _db(tmp_path)
    row = s._conn.execute(
        "SELECT MAX(version) FROM schema_migrations").fetchone()
    assert int(row[0]) == 1
    jm = s._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(jm).lower() == "wal"
    fk = s._conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert int(fk) == 1
    s.close()


def test_runtime_path_rejects_src(tmp_path):
    from sciencemath.memory.paths import REPO_ROOT
    bad = REPO_ROOT / "src" / "oops.sqlite"
    try:
        assert_runtime_path(bad)
        raise AssertionError("should refuse src")
    except ValueError as e:
        assert "src" in str(e)
    d = default_memory_dir()
    assert "runtime" in str(d).replace("\\", "/")


def test_explicit_write_and_exact_retrieval(tmp_path):
    s = _db(tmp_path)
    r = handle("Remember that project mango uses PostgreSQL.",
               store=s, owner_id="owner_a", scope_type="PROJECT",
               scope_id="mango", memory_type="PROJECT_DECISION",
               user_explicit=True)
    assert r.status == MEMORY_STORE
    assert r.memories
    s.close()
    s2 = MemoryStore(tmp_path / "t18.sqlite")
    q = handle("What database did we choose for project mango?",
               store=s2, owner_id="owner_a", scope_type="PROJECT",
               scope_id="mango")
    assert q.status == MEMORY_RETRIEVE
    assert "PostgreSQL" in q.answer
    assert q.used_memories and q.used_memories[0]["memory_id"]
    assert q.explanations
    s2.close()


def test_implicit_non_write(tmp_path):
    s = _db(tmp_path)
    r = handle("I like pineapple on pizza.",
               store=s, owner_id="owner_a", scope_type="SESSION",
               scope_id="s1")
    assert r.extra.get("implicit_rejected") or r.status == MEMORY_NO_MATCH
    listed = s.list_scope(owner_id="owner_a", scope_type="SESSION",
                          scope_id="s1")
    assert listed == []
    s.close()


def test_fts_and_paraphrase(tmp_path):
    s = _db(tmp_path)
    handle("Remember that my preferred editor is Cursor.",
           store=s, owner_id="u", scope_type="GLOBAL_USER",
           scope_id="u", memory_type="USER_PREFERENCE", user_explicit=True)
    q = handle("What is my preferred editor?",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u")
    assert "Cursor" in q.answer
    s.close()


def test_owner_and_project_isolation(tmp_path):
    s = _db(tmp_path)
    handle("Remember that project mango uses PostgreSQL.",
           store=s, owner_id="owner_a", scope_type="PROJECT",
           scope_id="mango", user_explicit=True)
    handle("Remember that project bunnyos uses SQLite.",
           store=s, owner_id="owner_a", scope_type="PROJECT",
           scope_id="bunnyos", user_explicit=True)
    handle("Remember that owner B favorite color is blue.",
           store=s, owner_id="owner_b", scope_type="GLOBAL_USER",
           scope_id="owner_b", user_explicit=True)
    a = handle("What database did we choose?",
               store=s, owner_id="owner_a", scope_type="PROJECT",
               scope_id="mango")
    assert "PostgreSQL" in a.answer
    assert "SQLite" not in a.answer or "bunny" not in a.answer.lower()
    b = handle("What database did we choose?",
               store=s, owner_id="owner_b", scope_type="PROJECT",
               scope_id="mango")
    assert b.status == MEMORY_NO_MATCH
    assert "PostgreSQL" not in b.answer
    leak = handle("favorite color",
                  store=s, owner_id="owner_a", scope_type="GLOBAL_USER",
                  scope_id="owner_a")
    assert "blue" not in leak.answer.lower() or leak.status == MEMORY_NO_MATCH
    s.close()


def test_duplicate_suppression(tmp_path):
    s = _db(tmp_path)
    handle("Remember that favorite editor is Cursor.",
           store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
           user_explicit=True, subject="favorite_editor")
    r2 = handle("Remember that favorite editor is Cursor.",
                store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
                user_explicit=True, subject="favorite_editor")
    assert r2.extra.get("duplicate_suppressed")
    rows = s.list_scope(owner_id="u", scope_type="GLOBAL_USER", scope_id="u")
    assert len(rows) == 1
    s.close()


def test_supersession_and_user_correction(tmp_path):
    s = _db(tmp_path)
    handle("Remember that favorite editor is VS Code.",
           store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
           user_explicit=True, subject="favorite_editor")
    r = handle("Correction: favorite editor is now Cursor.",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
               user_explicit=True, subject="favorite_editor",
               op=MEMORY_SUPERSEDE)
    assert r.status == MEMORY_SUPERSEDE
    q = handle("What is my preferred editor?",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u")
    assert "Cursor" in q.answer
    assert "VS Code" not in q.answer
    s.close()


def test_conflict_not_silent(tmp_path):
    s = _db(tmp_path)
    handle("Remember that the user lives in New York.",
           store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
           user_explicit=True, subject="lives_in")
    r = handle("Remember that the user lives in Boston.",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
               user_explicit=True, subject="lives_in")
    assert r.status == MEMORY_CONFLICT
    assert r.conflict and len(r.conflict["memory_ids"]) >= 2
    s.close()


def test_temporal_supersession(tmp_path):
    s = _db(tmp_path)
    handle("Remember that employer is A.",
           store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
           user_explicit=True, subject="employer",
           valid_from="2025-01-01T00:00:00.000000Z")
    r = handle("Remember that employer is B.",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
               user_explicit=True, subject="employer",
               valid_from="2026-01-01T00:00:00.000000Z")
    assert r.status == MEMORY_SUPERSEDE
    q = handle("Who is the employer?",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u")
    assert "B" in q.answer
    s.close()


def test_expiration(tmp_path):
    s = _db(tmp_path)
    handle("Remember that temp token is abc.",
           store=s, owner_id="u", scope_type="TEMPORARY", scope_id="t1",
           memory_type="TEMPORARY", user_explicit=True,
           valid_until="2020-01-01T00:00:00.000000Z")
    q = handle("temp token",
               store=s, owner_id="u", scope_type="TEMPORARY", scope_id="t1",
               now="2026-01-01T00:00:00.000000Z")
    assert q.status == MEMORY_NO_MATCH
    s.close()


def test_delete_and_fts_cleanup(tmp_path):
    s = _db(tmp_path)
    r = handle("Remember that secret nickname is kiwi.",
               store=s, owner_id="u", scope_type="SESSION", scope_id="s1",
               user_explicit=True)
    mid = r.memories[0].memory_id
    handle("Delete that memory", store=s, owner_id="u", scope_type="SESSION",
           scope_id="s1", memory_id=mid, op=MEMORY_DELETE)
    assert s.get(mid, owner_id="u") is None
    assert not s.fts_has(mid)
    q = handle("secret nickname",
               store=s, owner_id="u", scope_type="SESSION", scope_id="s1")
    assert q.status == MEMORY_NO_MATCH
    assert "kiwi" not in q.answer
    assert not s.audit_has_content("kiwi")
    s.close()
    s2 = MemoryStore(tmp_path / "t18.sqlite")
    q2 = handle("secret nickname",
                store=s2, owner_id="u", scope_type="SESSION", scope_id="s1")
    assert q2.status == MEMORY_NO_MATCH
    s2.close()


def test_forget_scope(tmp_path):
    s = _db(tmp_path)
    handle("Remember that a is 1.", store=s, owner_id="u",
           scope_type="SESSION", scope_id="s9", user_explicit=True)
    handle("Remember that b is 2.", store=s, owner_id="u",
           scope_type="SESSION", scope_id="s9", user_explicit=True)
    r = handle("Forget this session", store=s, owner_id="u",
               scope_type="SESSION", scope_id="s9", op=MEMORY_FORGET_SCOPE)
    assert r.status == MEMORY_FORGET_SCOPE
    assert s.list_scope(owner_id="u", scope_type="SESSION", scope_id="s9") == []
    s.close()


def test_provenance_and_inference_not_fact(tmp_path):
    s = _db(tmp_path)
    r = handle("Remember that inferred mood is happy.",
               store=s, owner_id="u", scope_type="SESSION", scope_id="s",
               user_explicit=True, memory_type="INFERENCE",
               source_type="DERIVED")
    assert r.memories[0].memory_type == "INFERENCE"
    assert r.memories[0].confidence in ("LOW", "MEDIUM", "UNKNOWN")
    assert r.memories[0].instruction_authority == 0
    s.close()


def test_no_match_does_not_fabricate(tmp_path):
    s = _db(tmp_path)
    q = handle("What is my dog's name?",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u")
    assert q.status == MEMORY_NO_MATCH
    assert "I remember" not in q.answer
    assert q.fabrication["fabricated_memory_claim"] == 0
    s.close()


def test_current_input_outranks_stale(tmp_path):
    s = _db(tmp_path)
    handle("Remember that favorite editor is VS Code.",
           store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
           user_explicit=True, subject="favorite_editor")
    q = handle("What is my preferred editor?",
               store=s, owner_id="u", scope_type="GLOBAL_USER", scope_id="u",
               current_user_input="My preferred editor is now Cursor.")
    assert q.status == "CURRENT_INPUT"
    assert "Cursor" in q.answer
    s.close()


def test_verified_tool_outranks_stale(tmp_path):
    s = _db(tmp_path)
    handle("Remember that project test count is 1190.",
           store=s, owner_id="u", scope_type="PROJECT", scope_id="mango",
           user_explicit=True, subject="test_count")
    q = handle("What is the project test count?",
               store=s, owner_id="u", scope_type="PROJECT", scope_id="mango",
               verified_tool={"value": "1242 tests pass", "verified": True})
    assert q.status == "VERIFIED_TOOL"
    assert "1242" in q.answer
    s.close()


def test_resource_limit(tmp_path):
    s = _db(tmp_path)
    big = "x" * 9000
    r = handle("Remember that blob is " + big,
               store=s, owner_id="u", scope_type="SESSION", scope_id="s",
               user_explicit=True)
    assert r.status == MEMORY_BLOCKED_LIMIT
    s.close()


def test_classify_ops():
    assert classify_request("Remember that we use PostgreSQL.") == MEMORY_STORE
    assert classify_request("What database did we choose?") == MEMORY_RETRIEVE
    assert classify_request("What is 12 * 11?") == MEMORY_NO_MATCH


def test_cache_invalidation_after_delete(tmp_path):
    s = _db(tmp_path)
    handle("Remember that mascot is mango.",
           store=s, owner_id="u", scope_type="PROJECT", scope_id="p",
           user_explicit=True)
    q1 = handle("mascot", store=s, owner_id="u", scope_type="PROJECT",
                scope_id="p")
    assert "mango" in q1.answer
    mid = q1.memories[0].memory_id
    handle("delete", store=s, owner_id="u", scope_type="PROJECT",
           scope_id="p", memory_id=mid, op=MEMORY_DELETE)
    q2 = handle("mascot", store=s, owner_id="u", scope_type="PROJECT",
                scope_id="p")
    assert q2.status == MEMORY_NO_MATCH
    s.close()
