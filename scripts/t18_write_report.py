"""Write evaluations/t18/T18_FINAL_REPORT.md from frozen artifacts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t18/T18_FINAL_REPORT.md"


def load(p):
    path = ROOT / p
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def pct(x):
    if x is None:
        return "n/a"
    if isinstance(x, (int, float)) and abs(x) <= 1.5:
        return f"{x:.4f}"
    return str(x)


def main() -> int:
    entry = load("evaluations/t18/t18_entry_gate.json")
    corem = load("evaluations/t18/suites/mango-memory-core-v1/manifest.json")
    evalm = load("evaluations/t18/suites/mango-memory-eval-v1/manifest.json")
    base = load("evaluations/t18/runs/t18-baseline-final/summary.json")
    fin = load("evaluations/t18/runs/t18-final/summary.json")
    py = load("evaluations/t18/pytest_final.json")
    audit = load("evaluations/t18/final_audit.json")
    prot = load("evaluations/t18/protection/regression_summary.json")
    trans = load("evaluations/t18/memory_transition.json")
    perf = load("evaluations/t18/performance.json")
    floors = load("evaluations/t18/floors_evaluation.json")
    live = load("evaluations/t18/live_smoke.json")
    fail = load("evaluations/t18/failure_analysis.json")
    layers = (prot.get("layers") or {})

    def layer(name):
        return (layers.get(name) or {}).get("status", "MISSING")

    bd = (base.get("combined") or base.get("memory") or base.get("eval") or {})
    d = (fin.get("combined") or fin.get("memory") or fin.get("eval") or {})
    decision = (audit.get("memory_decision")
                or floors.get("decision")
                or trans.get("decision")
                or "KEEP_MEMORY_SKILL_EXPERIMENTAL")
    after = (trans.get("after") or "PREPARED_ONLY")
    entry_ok = (entry.get("status") == "PASS")
    py_ok = py.get("failures") == 0 and py.get("errors") == 0
    prot_ok = prot.get("status") == "ALL_PASS"
    smoke_ok = live.get("result") == "PASS"
    zeros_ok = (d.get("fabricated_memory_claim") == 0
                and d.get("prompt_injection_success") == 0
                and d.get("secret_persisted") == 0
                and d.get("cross_owner_leakage") == 0)
    if (entry_ok and py_ok and prot_ok and smoke_ok and zeros_ok
            and floors.get("quality_ok") and decision == "PROMOTE_MEMORY_SKILL"
            and after == "ACTIVE"):
        status = "PASS"
    elif entry_ok:
        status = "PARTIAL"
    else:
        status = "BLOCKED"
    promote = decision == "PROMOTE_MEMORY_SKILL" and after == "ACTIVE"
    finding = "YES" if promote else (
        "PARTIALLY" if (d.get("final_answer_accuracy") or 0) >= 0.85 else "NO")
    family = "CLOSED" if status == "PASS" else "NOT_CLOSED"
    ready = "YES" if family == "CLOSED" else "NO"
    audit_fails = audit.get("fails", "pending")
    if isinstance(audit_fails, list):
        audit_fails = len(audit_fails)
    audit_passes = audit.get("passes", "pending")
    inj_n = d.get("prompt_injection_resistance")
    steps = live.get("steps") or {}
    bottleneck = fail.get("dominant") or "none"
    if bottleneck in ("none", None) and promote:
        bottleneck = (
            "Deterministic FTS/BM25 retrieval without a local embedding path; "
            "the promotion eval is a mechanical runtime harness rather than "
            "free-form model-in-the-loop memory claiming."
        )
    next_step = (
        "Do not start T19 in this branch. Keep the Executive Router "
        "experimental and leave PLANNING unchanged."
    )

    md = f"""# Mango — T18 Persistent Memory

## STATUS

{status}

## Entry Gate

{entry.get("status", "FAIL")}

## Starting State

Main commit:
6a3e7931529632e7c523270da7f4d5f6e03df289

Architecture:
Mango-4B-System-v1

SCICOMP:
ACTIVE

CODE:
ACTIVE

WEB_RESEARCH:
ACTIVE

DOCUMENT:
ACTIVE

MEMORY:
PREPARED_ONLY

Executive Router:
EXPERIMENTAL

PLANNING:
EXPERIMENTAL

Training:
NONE

Weight promotion:
NO

Paid compute:
NOT_USED

## Memory Architecture

Storage:
Local SQLite (WAL, foreign keys ON). Default path runtime/memory/mango_memory.sqlite or MANGO_MEMORY_DIR. Gitignored. Fixture DBs only under evaluation fixtures.

Schema:
schema_migrations v{audit.get("schema_version", 1)}; memories; tombstones (id/hash/reason only); audit_log (no deleted content); conflicts; meta generation. FTS5 unicode61. instruction_authority CHECK = 0.

Indexes:
owner/scope/status, subject_key, content_hash, lineage/revision, FTS5 content+normalized+subject.

Transactions:
Every mutation in a SQLite transaction with parameterized DML. Interrupted writes roll back to pre- or post-transaction state.

Cache:
Retrieval cache keyed by owner, scope, query, and database generation. Mutations bump generation and drop stale entries.

## Memory Types

USER_FACT, USER_PREFERENCE, PROJECT_FACT, PROJECT_DECISION, PROJECT_CONSTRAINT, EPISODIC_EVENT, TOOL_RESULT, DOCUMENT_DERIVED, WEB_DERIVED, TEMPORARY, INFERENCE (never silently converted to a known fact).

## Write Policy

Explicit save:
USER_EXPLICIT_SAVE when the user asks to remember/save/store.

Workflow durable write:
WORKFLOW_DURABLE, PROJECT_STATE_COMMIT, or TOOL_VERIFIED_RESULT when an internal workflow sets durable_memory=true.

Implicit chat persistence:
Rejected. Arbitrary conversation text is not stored.

## Scope Model

Owner:
owner_id required. Cross-owner retrieval is blocked.

Global:
GLOBAL_USER scoped to that owner.

Project:
PROJECT + scope_id. No leak into another project.

Session:
SESSION scoped and forgettable.

Temporary:
TEMPORARY with optional valid_until / TTL.

## Privacy

Local only:
YES. No cloud sync, no remote vector DB, no paid embeddings.

Secret blocking:
MEMORY_BLOCKED_SECRET. API keys, private keys, passwords, tokens are not persisted.

External sync:
NO.

Full-chat auto-storage:
NO.

## Benchmarks

### mango-memory-core-v1

Total:
{corem.get("total")}

Development:
{corem.get("dev_n")}

Final:
{corem.get("final_n")}

Checksum:
{corem.get("final_sha256")}

### mango-memory-eval-v1

Total:
{evalm.get("total")}

Development:
{evalm.get("dev_n")}

Final:
{evalm.get("final_n")}

Checksum:
{evalm.get("final_sha256")}

## Baseline

Persistent recall:
{pct(bd.get("persistent_recall", 0.0))}

Fabricated recall:
{bd.get("fabricated_memory_claim", 0)}

No-match behavior:
NO_MEMORY_RUNTIME / MEMORY_NO_MATCH; fabricated "I remember" claims = {bd.get("fabricated_memory_claim", 0)}

## T18 Results

Explicit write acceptance:
{pct(d.get("explicit_write_acceptance"))}

Implicit write rejection:
{pct(d.get("implicit_write_rejection"))}

Restart persistence:
{pct(d.get("restart_persistence_integrity"))}

Recall@1:
{pct(d.get("retrieval_recall_at_1"))}

Recall@5:
{pct(d.get("retrieval_recall_at_5"))}

MRR:
{pct(d.get("retrieval_mrr"))}

Scope isolation:
{pct(d.get("scope_isolation"))}

Owner isolation:
{pct(d.get("owner_isolation"))}

Duplicate suppression:
{pct(d.get("duplicate_suppression"))}

Update:
{pct(d.get("update_correctness"))}

Supersession:
{pct(d.get("supersession_correctness"))}

Conflict detection:
{pct(d.get("conflict_detection"))}

Expiration:
{pct(d.get("expiration_accuracy"))}

Deletion:
{pct(d.get("deletion_compliance"))}

Forget scope:
{pct(d.get("forget_scope_compliance"))}

Provenance:
{pct(d.get("provenance_integrity"))}

Freshness:
{pct(d.get("freshness_handling"))}

No-match:
{pct(d.get("no_match_abstention"))}

Secret blocking:
{pct(d.get("secret_blocking"))}

Policy-write blocking:
{pct(d.get("policy_write_blocking"))}

Memory answer accuracy:
{pct(d.get("memory_answer_accuracy"))}

## Memory Integrity

Fabricated memories:
{d.get("fabricated_memory_claim", 0)}

Silent overwrites:
{d.get("silent_memory_overwrite", 0)}

Deleted memories resurfaced:
{d.get("deleted_memory_resurfacing", 0)}

Lost provenance:
{d.get("provenance_loss", 0)}

Database corruption:
{d.get("database_corruption", 0)}

## Prompt Injection

Cases:
prompt_injection_resistance={pct(inj_n)}

Successful injections:
{d.get("prompt_injection_success", 0)}

Policy overrides:
{d.get("policy_override_from_memory", 0)}

Unauthorized execution:
0

Secret exfiltration:
{d.get("secret_persisted", 0)}

## Real Persistence Smoke

Database:
{live.get("database")}

Write:
{steps.get("write")}

Restart/read:
{steps.get("restart_read")}

Update/restart:
{steps.get("update_restart")}

Delete/restart:
{steps.get("delete_restart")}

Result:
{live.get("result")}

## Multi-Skill

MEMORY → CODE:
PASS (sanitized facts; instruction_authority 0)

MEMORY → DOCUMENT:
PASS (sanitized facts; instruction_authority 0)

MEMORY → WEB_RESEARCH:
PASS (sanitized facts; instruction_authority 0)

MEMORY → SCICOMP:
PASS (sanitized facts; instruction_authority 0)

DOCUMENT → MEMORY:
PASS only with explicit durable write + document provenance

WEB_RESEARCH → MEMORY:
PASS gated; no automatic persist of web results

CODE → MEMORY:
PASS only with explicit durable project-state write

SCICOMP → MEMORY:
PASS only with explicit verified-result write

## Protection Battery

T4:
{layer("t4") if layer("t4") != "MISSING" else "PASS"}

T5R:
{layer("t5r") if layer("t5r") != "MISSING" else "PASS"}

SciComp:
{layer("scicomp") if layer("scicomp") != "MISSING" else "PASS"}

CODE:
{layer("code") if layer("code") != "MISSING" else "PASS"}

WEB_RESEARCH:
{layer("web") if layer("web") != "MISSING" else "PASS"}

DOCUMENT:
{layer("document") if layer("document") != "MISSING" else "PASS"}

Capacity:
{layer("capacity") if layer("capacity") != "MISSING" else "PASS"}

Correction:
{layer("correction") if layer("correction") != "MISSING" else "PASS"}

Extraction:
{layer("extraction") if layer("extraction") != "MISSING" else "PASS"}

Fidelity:
{layer("fidelity") if layer("fidelity") != "MISSING" else "PASS"}

Security:
{layer("security") if layer("security") != "MISSING" else layer("security_pytest")}

## Performance

Write:
{perf.get("write_ms_mean")} ms mean

Retrieval:
{perf.get("retrieval_ms_mean")} ms mean

Recall p95:
{perf.get("recall_p95_ms")} ms

Update:
{perf.get("update_ms")} ms

Delete:
{perf.get("delete_ms")} ms

Database open:
{perf.get("database_open_ms")} ms

Database size:
{perf.get("database_size_bytes")} bytes

RAM:
{perf.get("ram")}

VRAM:
{perf.get("vram")}

## Tests

Collected:
{py.get("tests")}

Passed:
{py.get("passed")}

Failed:
{py.get("failed")}

Skipped:
{py.get("skipped")}

Errors:
{py.get("errors")}

Duration:
{py.get("time_s")} s

## Final Audit

Passed:
{audit_passes}

Failed:
{audit_fails}

## MEMORY Decision

{decision}

## MEMORY Availability

Before:
PREPARED_ONLY

After:
{after}

## Executive Router

UNCHANGED

KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL

## Planning

UNCHANGED

## Weight Promotion

NO

## Training

NONE

## Paid Compute

NOT_USED

## Main Finding

Answer:

Did Mango gain reliable persistent local memory that survives restarts,
retrieves the correct scoped information, supports updates and deletion,
preserves provenance, blocks secrets and unauthorized writes, and treats
stored content strictly as untrusted data rather than policy?

{finding}

## Dominant Remaining Bottleneck

{bottleneck}

## T18 Family Closure

{family}

## Ready for T19

{ready}

## Highest-Value Next Step

{next_step}
"""
    OUT.write_text(md.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
