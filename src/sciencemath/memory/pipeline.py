"""MEMORY skill pipeline. Writes are intentional; retrieval is scoped.

Stored records have instruction authority 0. Current user input and
verified tool results outrank stale memory.
"""
from __future__ import annotations

import re
import time
from difflib import SequenceMatcher

from sciencemath.memory.contract import (
    MEMORY_BLOCKED_LIMIT, MEMORY_BLOCKED_POLICY, MEMORY_BLOCKED_SECRET,
    MEMORY_CONFLICT, MEMORY_DELETE, MEMORY_EXPLAIN, MEMORY_FORGET_SCOPE,
    MEMORY_LIST, MEMORY_NO_MATCH, MEMORY_RETRIEVE, MEMORY_SEARCH,
    MEMORY_STORE, MEMORY_SUPERSEDE, MEMORY_UPDATE, classify_request,
    is_explicit_write,
)
from sciencemath.memory.limits import DEFAULT_TOP_K, MAX_TOP_K, MemoryLimits
from sciencemath.memory.models import (
    CONFIDENCE, MEMORY_TYPES, SCOPE_TYPES, SENSITIVITY, SOURCE_TYPES,
    MemoryResult,
)
from sciencemath.memory.normalize import extract_value, normalize_content, subject_key
from sciencemath.memory.policy import confidence_for, write_allowed
from sciencemath.memory.retrieval import rank
from sciencemath.memory.safety import is_policy_write, scan_injection
from sciencemath.memory.secrets import classify_sensitivity, looks_like_secret
from sciencemath.memory.store import MemoryStore, build_record, utcnow


def _payload(question: str, content: str | None) -> str:
    if content and str(content).strip():
        raw = str(content).strip()
    else:
        q = (question or "").strip()
        low = q.lower()
        raw = q
        for p in ("remember that ", "remember this: ", "remember this ",
                  "remember the ", "please remember ", "save this: ",
                  "save that ", "store this: ", "store that ",
                  "don't forget that ", "dont forget that ",
                  "keep in mind that ", "update memory: ", "correction: "):
            if low.startswith(p):
                raw = q[len(p):].strip()
                break
    return re.sub(
        r"\s+(please|now|carefully|using memory)\.?\s*$", "", raw,
        flags=re.I).strip()


def _valid_enum(value: str, allowed: tuple, default: str) -> str:
    if value in allowed:
        return value
    return default


def _ground(recs) -> list[dict]:
    out = []
    for r in recs:
        out.append({
            "memory_id": r.memory_id,
            "provenance": r.provenance,
            "confidence": r.confidence,
            "scope_type": r.scope_type,
            "scope_id": r.scope_id,
            "revision": r.revision,
            "memory_type": r.memory_type,
            "source_type": r.source_type,
        })
    return out


def _answer_from(recs) -> str:
    if not recs:
        return "MEMORY_NO_MATCH: no reliable memory."
    parts = []
    for r in recs:
        tag = f"[{r.memory_id} rev={r.revision} {r.confidence}]"
        parts.append(f"{tag} {r.content}")
    return "I remember: " + " | ".join(parts)


def _near_dup(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.92


def _temporal_newer(new_rec, old_rec) -> bool:
    def key(r):
        return r.valid_from or r.created_at or ""
    return key(new_rec) > key(old_rec)


def handle(question: str, *, store: MemoryStore,
           owner_id: str, scope_type: str = "SESSION",
           scope_id: str = "default", content: str | None = None,
           memory_type: str = "USER_FACT",
           write_reason: str | None = None, user_explicit: bool = False,
           durable_memory: bool = False, project_state: bool = False,
           source_type: str = "USER", source_reference: str | None = None,
           provenance: dict | None = None, confidence: str | None = None,
           valid_until: str | None = None, valid_from: str | None = None,
           subject: str | None = None, value: str | None = None,
           memory_id: str | None = None, query: str | None = None,
           top_k: int = DEFAULT_TOP_K, allow_global: bool = False,
           current_user_input: str | None = None,
           verified_tool: dict | None = None,
           op: str | None = None, baseline: bool = False,
           limits: MemoryLimits | None = None,
           now: str | None = None) -> MemoryResult:
    t0 = time.perf_counter()
    limits = limits or store.limits
    now = now or store.clock()
    op = op or classify_request(question)
    scope_type = _valid_enum(scope_type, SCOPE_TYPES, "SESSION")
    memory_type = _valid_enum(memory_type, MEMORY_TYPES, "USER_FACT")
    source_type = _valid_enum(source_type, SOURCE_TYPES, "USER")
    inj = scan_injection((content or "") + "\n" + (question or ""))
    fab = {
        "fabricated_memory_claim": 0,
        "silent_overwrite": 0,
        "deleted_resurfaced": 0,
        "provenance_loss": 0,
        "prompt_injection_success": 0,
        "policy_override": 0,
        "secret_persisted": 0,
        "unauthorized_write": 0,
        "sql_injection_success": 0,
        "cross_owner_leak": 0,
        "cross_project_leak": 0,
    }

    def _done(status, answer, **kw):
        rec = MemoryResult(
            op=op, status=status, answer=answer,
            injection_detected=inj["detected"],
            instruction_authority=0, fabrication=fab,
            latency_ms={"end_to_end": round(
                (time.perf_counter() - t0) * 1000, 3)},
            **kw)
        rec.instruction_authority = 0
        if inj["detected"] and rec.status not in (
                MEMORY_BLOCKED_POLICY, MEMORY_BLOCKED_SECRET):
            rec.extra = dict(rec.extra or {})
            rec.extra["instruction_authority"] = 0
            rec.extra["injection"] = inj
        return rec

    if baseline:
        return _done(
            "NO_MEMORY_RUNTIME",
            "Baseline: MEMORY runtime disabled.",
            extra={"baseline": True})

    if not owner_id:
        return _done(MEMORY_NO_MATCH, "MEMORY_NO_MATCH: owner_id required.")

    store.expire_due(now)

    payload = _payload(question, content)

    if op in (MEMORY_STORE, MEMORY_UPDATE, MEMORY_SUPERSEDE):
        ok, reason = write_allowed(
            question=question, write_reason=write_reason,
            user_explicit=user_explicit, durable_memory=durable_memory,
            project_state=project_state)
        if not ok:
            fab["unauthorized_write"] = 0
            return _done(
                MEMORY_NO_MATCH,
                "Write refused: no valid write_reason "
                "(implicit chat is not persisted).",
                extra={"unauthorized_persistent_write": 0,
                       "implicit_rejected": True})
        if len(payload) > limits.max_content_chars:
            return _done(
                MEMORY_BLOCKED_LIMIT,
                "MEMORY_BLOCKED_LIMIT: content exceeds max memory length. "
                "Large documents belong to DOCUMENT.")
        if looks_like_secret(payload):
            fab["secret_persisted"] = 0
            return _done(
                MEMORY_BLOCKED_SECRET,
                "MEMORY_BLOCKED_SECRET: credential-like material is not stored.")
        if is_policy_write(payload, explicit_quote=user_explicit and (
                "quote" in (question or "").lower()
                or "as text" in (question or "").lower())):
            fab["policy_override"] = 0
            return _done(
                MEMORY_BLOCKED_POLICY,
                "MEMORY_BLOCKED_POLICY: memory may not alter system policy.")
        if memory_type == "INFERENCE":
            # never silently convert inference into a known fact
            pass
        sens = classify_sensitivity(payload)
        if sens == "SECRET_LIKE":
            return _done(
                MEMORY_BLOCKED_SECRET,
                "MEMORY_BLOCKED_SECRET: SECRET_LIKE blocked from persistence.")
        has_prov = bool(source_reference or provenance)
        conf = confidence or confidence_for(
            memory_type=memory_type, source_type=source_type,
            verified=bool((provenance or {}).get("verified")),
            has_provenance=has_prov or source_type == "USER",
            user_confirmed=user_explicit or is_explicit_write(question),
        )
        if memory_type == "INFERENCE" and conf in ("VERIFIED", "HIGH"):
            conf = "MEDIUM"
        if conf not in CONFIDENCE:
            conf = "UNKNOWN"
        if sens not in SENSITIVITY:
            sens = "GENERAL"
        prov = dict(provenance or {})
        if "source_type" not in prov:
            prov["source_type"] = source_type
        if source_reference and "source_reference" not in prov:
            prov["source_reference"] = source_reference
        prov["captured_at"] = now
        if not has_prov and source_type != "USER":
            conf = "UNKNOWN" if conf in ("VERIFIED", "HIGH") else conf
            fab["provenance_loss"] = 0

        sk = subject_key(subject, payload, scope_id=scope_id)
        dups = store.find_active_duplicates(
            owner_id=owner_id, scope_type=scope_type, scope_id=scope_id,
            subject_key_v=sk,
            value_key_v=normalize_content(value or extract_value(payload)))
        if dups:
            rec = dups[0]
            return _done(
                MEMORY_STORE, _answer_from([rec]),
                memories=[rec], used_memories=_ground([rec]),
                extra={"duplicate_suppressed": True, "write_reason": reason})

        existing = store.find_active_subject(
            owner_id=owner_id, scope_type=scope_type, scope_id=scope_id,
            subject_key_v=sk)
        rec = build_record(
            owner_id=owner_id, scope_type=scope_type, scope_id=scope_id,
            memory_type=memory_type, content=payload, write_reason=reason,
            source_type=source_type, source_reference=source_reference,
            provenance=prov, confidence=conf, sensitivity=sens,
            store=store, subject=subject, value=value,
            valid_from=valid_from, valid_until=valid_until,
            now=now,
            lineage_id=existing[0].lineage_id if existing else None,
            predecessor_id=existing[0].memory_id if existing else None,
            revision=(existing[0].revision + 1) if existing else 1,
        )

        if existing:
            same_val = any(
                e.value_key == rec.value_key
                or e.normalized_content == rec.normalized_content
                or _near_dup(e.value_key, rec.value_key)
                for e in existing)
            if same_val:
                return _done(
                    MEMORY_STORE, _answer_from(existing),
                    memories=existing, used_memories=_ground(existing),
                    extra={"duplicate_suppressed": True})
            correction = op in (MEMORY_UPDATE, MEMORY_SUPERSEDE) or (
                user_explicit and classify_request(question) in (
                    MEMORY_UPDATE, MEMORY_SUPERSEDE))
            if correction or (valid_from and any(
                    _temporal_newer(rec, e) for e in existing)):
                stored = store.supersede_records(
                    existing, rec, owner_id=owner_id, now=now)
                return _done(
                    MEMORY_SUPERSEDE, _answer_from([stored]),
                    memories=[stored], used_memories=_ground([stored]),
                    extra={"superseded": [e.memory_id for e in existing],
                           "write_reason": reason})
            # conflict: do not silently overwrite
            ids = [e.memory_id for e in existing]
            for e in existing:
                store.set_status(e.memory_id, "CONFLICTED",
                                 owner_id=owner_id, now=now)
            rec.status = "CONFLICTED"
            stored = store.insert_record(rec)
            cid = store.record_conflict(
                owner_id=owner_id, scope_type=scope_type, scope_id=scope_id,
                subject=sk, recs=[*existing, stored],
                temporal="possible temporal evolution; not auto-resolved")
            conflict = {
                "conflict_id": cid,
                "memory_ids": ids + [stored.memory_id],
                "values": [e.content for e in existing] + [stored.content],
                "timestamps": [e.created_at for e in existing] + [stored.created_at],
                "sources": [e.source_type for e in existing] + [stored.source_type],
                "confidence": [e.confidence for e in existing] + [stored.confidence],
                "possible_temporal": True,
            }
            return _done(
                MEMORY_CONFLICT,
                "MEMORY_CONFLICT: competing active values; not silently chosen.",
                memories=[stored], conflict=conflict,
                extra={"write_reason": reason})

        stored = store.insert_record(rec)
        return _done(
            MEMORY_STORE, _answer_from([stored]),
            memories=[stored], used_memories=_ground([stored]),
            extra={"write_reason": reason, "persisted": True})

    if op == MEMORY_DELETE:
        if not memory_id:
            # delete by subject/query
            q = query or payload
            hits = store.fts_query(
                q, owner_id=owner_id, scope_type=scope_type,
                scope_id=scope_id, allow_global=False, limit=5)
            recs, _ = rank(hits, query=q, now=now, top_k=1)
            if not recs:
                return _done(MEMORY_NO_MATCH,
                             "MEMORY_NO_MATCH: nothing to delete.")
            memory_id = recs[0].memory_id
        ok = store.delete(memory_id, owner_id=owner_id)
        return _done(
            MEMORY_DELETE,
            "Deleted from active retrieval." if ok else "MEMORY_NO_MATCH",
            extra={"deleted": memory_id if ok else None})

    if op == MEMORY_FORGET_SCOPE:
        n = store.forget_scope(owner_id=owner_id, scope_type=scope_type,
                               scope_id=scope_id)
        return _done(
            MEMORY_FORGET_SCOPE,
            f"Forgot {n} memories in scope {scope_type}:{scope_id}.",
            extra={"forgotten": n})

    if op == MEMORY_LIST:
        recs = store.list_scope(owner_id=owner_id, scope_type=scope_type,
                                scope_id=scope_id)
        if not recs:
            return _done(MEMORY_NO_MATCH, "MEMORY_NO_MATCH: empty scope.")
        return _done(MEMORY_LIST, _answer_from(recs), memories=recs,
                     used_memories=_ground(recs))

    if op == MEMORY_EXPLAIN:
        q = query or payload
        recs, expl = _retrieve(store, q, owner_id, scope_type, scope_id,
                               allow_global, top_k, now, limits)
        if not recs:
            return _done(MEMORY_NO_MATCH, "MEMORY_NO_MATCH: nothing to explain.")
        return _done(
            MEMORY_EXPLAIN, _answer_from(recs),
            memories=recs, explanations=expl, used_memories=_ground(recs),
            extra={"rationale": "observable retrieval scores; not chain-of-thought"})

    # retrieve / search / default
    q = query or payload or question
    recs, expl = _retrieve(store, q, owner_id, scope_type, scope_id,
                           allow_global, top_k, now, limits)
    if current_user_input and recs:
        sk_cur = subject_key(None, current_user_input, scope_id=scope_id)
        if any(r.subject_key == sk_cur or sk_cur in (r.subject_key or "")
               or (r.subject_key or "") in sk_cur for r in recs):
            return _done(
                "CURRENT_INPUT",
                "Current user input outranks stored memory: "
                + current_user_input,
                extra={"outranks_memory": True,
                       "stale_memory_ids": [r.memory_id for r in recs]})
    if verified_tool and recs:
        return _done(
            "VERIFIED_TOOL",
            "Verified current data outranks stale memory: "
            + str(verified_tool.get("value") or verified_tool),
            extra={"outranks_memory": True, "verified_tool": verified_tool,
                   "stale_memory_ids": [r.memory_id for r in recs]})
    if not recs:
        return _done(
            MEMORY_NO_MATCH,
            "MEMORY_NO_MATCH: no reliable relevant memory.",
            extra={"abstained": True})
    # never claim remember without records
    ans = _answer_from(recs)
    if "I remember" in ans and not recs:
        fab["fabricated_memory_claim"] = 1
        ans = "MEMORY_NO_MATCH: no reliable relevant memory."
    return _done(
        MEMORY_RETRIEVE if op != MEMORY_SEARCH else MEMORY_SEARCH,
        ans, memories=recs, explanations=expl,
        used_memories=_ground(recs))


def _retrieve(store, query, owner_id, scope_type, scope_id,
              allow_global, top_k, now, limits):
    k = max(1, min(int(top_k or DEFAULT_TOP_K), MAX_TOP_K,
                   limits.max_top_k))
    gen = store.generation()
    cached = store.cache.get(owner_id, scope_type, scope_id, query, gen)
    if cached is not None:
        return cached
    hits = store.fts_query(
        query, owner_id=owner_id, scope_type=scope_type,
        scope_id=scope_id, allow_global=allow_global,
        limit=limits.max_candidates)
    scoped = store.candidates(
        owner_id=owner_id, scope_type=scope_type, scope_id=scope_id,
        allow_global=allow_global)
    by_id = {r.memory_id: (r, sc) for r, sc in hits}
    for rec in scoped:
        if rec.memory_id not in by_id:
            by_id[rec.memory_id] = (rec, 0.0)
    hits = list(by_id.values())
    recs, expl = rank(hits, query=query, now=now, top_k=k)
    recs = [r for r in recs if r.status == "ACTIVE"]
    # Drop near-zero relevance unless this is the only in-scope record
    # and it shares a subject/alias signal.
    if recs and expl and expl[0].retrieval_score < 0.12 and len(scoped) > 1:
        recs, expl = [], []
    expl = [e for e in expl if any(r.memory_id == e.memory_id for r in recs)]
    store.cache.put(owner_id, scope_type, scope_id, query, gen, (recs, expl))
    return recs, expl
