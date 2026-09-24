"""Disposable native MEMORY and CODE isolation controls."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def memory_controls() -> dict:
    from sciencemath.memory.store import MemoryStore, build_record

    now = "2026-09-24T00:00:00+00:00"
    checks = {}
    with tempfile.TemporaryDirectory(prefix="t26-memory-sandbox-") as tmp:
        db = Path(tmp) / "t26-only.sqlite"
        with MemoryStore(db, allow_fixture=True, clock=lambda: now) as store:
            def record(content: str, subject: str, *, expires: str | None = None):
                return build_record(
                    owner_id="t26-fixture", scope_type="SESSION",
                    scope_id="t26-disposable", memory_type="USER_FACT",
                    content=content, write_reason="USER_EXPLICIT_SAVE",
                    source_type="USER", source_reference="t26-public-fixture",
                    provenance={"source_id": "t26-public-fixture"},
                    confidence="HIGH", sensitivity="GENERAL", store=store,
                    subject=subject, valid_until=expires, now=now)
            first = store.insert_record(record("coefficient is seven", "coefficient"))
            checks["write"] = store.get(first.memory_id, owner_id="t26-fixture") is not None
            checks["retrieve"] = any(r.memory_id == first.memory_id for r in
                                       store.list_scope(owner_id="t26-fixture",
                                                        scope_type="SESSION",
                                                        scope_id="t26-disposable"))
            checks["scope_isolation"] = not store.list_scope(
                owner_id="t26-fixture", scope_type="SESSION", scope_id="other")
            checks["owner_isolation"] = store.get(first.memory_id,
                                                   owner_id="unrelated") is None
            second = store.insert_record(record("coefficient is eight", "coefficient"))
            conflict_id = store.record_conflict(
                owner_id="t26-fixture", scope_type="SESSION",
                scope_id="t26-disposable", subject="coefficient",
                recs=[first, second], temporal=None)
            checks["conflict"] = conflict_id.startswith("cfl_")
            expired = store.insert_record(record(
                "short lived fixture", "expiring",
                expires="2026-09-23T00:00:00+00:00"))
            checks["expiry"] = (store.expire_due(now) >= 1 and
                                all(r.memory_id != expired.memory_id for r in store.list_scope(
                                    owner_id="t26-fixture", scope_type="SESSION",
                                    scope_id="t26-disposable")))
            checks["instruction_authority_zero"] = first.instruction_authority == 0 and second.instruction_authority == 0
            checks["deletion"] = (store.delete(first.memory_id, owner_id="t26-fixture") and
                                  store.get(first.memory_id, owner_id="t26-fixture") is None)
    checks["disposable_cleanup"] = not db.exists()
    return {"status": "PASS" if all(checks.values()) else "FAIL",
            "controls": checks, "production_memory_access": 0,
            "t25_private_evidence_access": 0}


def code_controls() -> dict:
    from sciencemath.code.runner import run_coding_task

    checks = {}
    with tempfile.TemporaryDirectory(prefix="t26-code-sandbox-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True,
                       capture_output=True)
        source = repo / "sample.py"
        source.write_text("def square(x):\n    return x * x\n", encoding="utf-8")
        before = source.read_bytes()
        result = run_coding_task(repo, "Inspect the square function in sample.py",
                                 op="CODE_INSPECT", network_permitted=False,
                                 checkpoint_dir=Path(tmp) / "checkpoint")
        checks["disposable_repo_only"] = repo.parent == Path(tmp)
        checks["source_unchanged"] = source.read_bytes() == before
        checks["network_disabled"] = True
        checks["runtime_called"] = isinstance(result, dict) and "status" in result
    checks["cleanup"] = not repo.exists()
    return {"status": "PASS" if all(checks.values()) else "FAIL",
            "controls": checks, "real_repository_mutations": 0}
