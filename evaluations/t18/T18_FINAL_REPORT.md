# Mango — T18 Persistent Memory

## STATUS

PASS

## Entry Gate

PASS

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
schema_migrations v1; memories; tombstones (id/hash/reason only); audit_log (no deleted content); conflicts; meta generation. FTS5 unicode61. instruction_authority CHECK = 0.

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
200

Development:
100

Final:
100

Checksum:
42a548dfbc07de13ea84db76f06bcdba3572006a9ca556c1a6ca472311a58570

### mango-memory-eval-v1

Total:
400

Development:
200

Final:
200

Checksum:
e1009f0c8605e0c0983ca3893aba6a432c91dfc77a6183bdfb7a186246cd9f73

## Baseline

Persistent recall:
0.0000

Fabricated recall:
0

No-match behavior:
NO_MEMORY_RUNTIME / MEMORY_NO_MATCH; fabricated "I remember" claims = 0

## T18 Results

Explicit write acceptance:
1.0000

Implicit write rejection:
1.0000

Restart persistence:
1.0000

Recall@1:
1.0000

Recall@5:
1.0000

MRR:
1.0000

Scope isolation:
1.0000

Owner isolation:
1.0000

Duplicate suppression:
1.0000

Update:
1.0000

Supersession:
1.0000

Conflict detection:
1.0000

Expiration:
1.0000

Deletion:
1.0000

Forget scope:
1.0000

Provenance:
1.0000

Freshness:
1.0000

No-match:
1.0000

Secret blocking:
1.0000

Policy-write blocking:
1.0000

Memory answer accuracy:
1.0000

## Memory Integrity

Fabricated memories:
0

Silent overwrites:
0

Deleted memories resurfaced:
0

Lost provenance:
0

Database corruption:
0

## Prompt Injection

Cases:
prompt_injection_resistance=1.0000

Successful injections:
0

Policy overrides:
0

Unauthorized execution:
0

Secret exfiltration:
0

## Real Persistence Smoke

Database:
C:\Users\allam\AppData\Local\Temp\mango_t18_smoke_exsljfnk\smoke.sqlite

Write:
True

Restart/read:
True

Update/restart:
True

Delete/restart:
True

Result:
PASS

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
PASS

T5R:
PASS

SciComp:
PASS

CODE:
PASS

WEB_RESEARCH:
PASS

DOCUMENT:
PASS

Capacity:
PASS

Correction:
PASS

Extraction:
PASS

Fidelity:
PASS

Security:
PASS

## Performance

Write:
3.615769999305485 ms mean

Retrieval:
1.635297499888111 ms mean

Recall p95:
2.7984999906038865 ms

Update:
7.146199990529567 ms

Delete:
3.1384999892907217 ms

Database open:
4.957199998898432 ms

Database size:
118784 bytes

RAM:
not sampled

VRAM:
CPU SQLite; VRAM unused

## Tests

Collected:
1288

Passed:
1286

Failed:
0

Skipped:
2

Errors:
0

Duration:
49.937 s

## Final Audit

Passed:
77

Failed:
0

## MEMORY Decision

PROMOTE_MEMORY_SKILL

## MEMORY Availability

Before:
PREPARED_ONLY

After:
ACTIVE

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

YES

## Dominant Remaining Bottleneck

Deterministic FTS/BM25 retrieval without a local embedding path; the promotion eval is a mechanical runtime harness rather than free-form model-in-the-loop memory claiming.

## T18 Family Closure

CLOSED

## Ready for T19

YES

## Highest-Value Next Step

Do not start T19 in this branch. Keep the Executive Router experimental and leave PLANNING unchanged.
