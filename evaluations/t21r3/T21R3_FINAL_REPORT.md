# T21R3 FINAL REPORT — strict blind holdout validation of the repaired knowledge RAG

**Decision: KEEP_KNOWLEDGE_RAG_EXPERIMENTAL**
**Branch:** `t21r3-knowledge-rag-repair-blind-validation` (NOT merged; pushed
for independent verification)
**Canonical base:** `ac7492b0f4e37fdc0adcb69d879c0f8c0b881372` (main, the
GitHub-verified T21R2 merge)
**Repair commit:** `b0c03a0d8a974aa3248c07bf1dbc2ced4501b28d`
**Partial checkpoint carried forward:** `775b750c6280141c234189ec907123926be11232`
**Recorded:** 2026-09-15

T21R3 answers the question T21R2 left open: does the **repaired**
KNOWLEDGE_RAG runtime meet the preregistered promotion bar on a holdout
that was provably never exposed to any runtime function? T21R2 failed 6
floors and demoted the skill, root-causing to one defect
(`detect_conflicts` compared `text_span` instead of `fact_value`) plus 2
citation-spoof misses. T21R3 repaired exactly that (Commit 2, `b0c03a0`),
then rebuilt the entire validation under the same blind-construction
regime: runtime, evaluator and contract frozen BEFORE holdout data
existed; holdout built from an entirely new world; frozen
(`HOLDOUT_FROZEN`, manifest sha256 `9f098561…710005d`); evaluated exactly
once.

**The verdict is a fail on one floor — and the repair itself is vindicated.**
The two T21R2 defect classes are gone: conflict **false resolution is 0.0**
(the T21R2 near-duplicate false-conflict defect did not recur) and
citation-spoof rejection is **1.0** (was 0.92). 31 of 32 preregistered
floors pass; all zero-tolerance counters are zero on all 2214 rows. The
single failing floor is `conflict_detection = 0.8889` vs `>= 0.98`: on a
new conflict composition the holdout probes for the first time, the
runtime abstains instead of surfacing `CONFLICTING_EVIDENCE` on 6 of 54
gold-conflict rows — a conservative failure mode (it never silently
resolves), but below the frozen promotion bar, so the skill stays
EXPERIMENTAL.

---

## 1. What T21R3 changed (and did not change)

Changed:
- `src/sciencemath/knowledge/conflicts.py` — the preregistered repair:
  `detect_conflicts` now compares normalized `fact_value` (identical
  normalized values on the same entity+attribute are NOT a conflict;
  `_normalize_fact_value` = NFKC + whitespace collapse + casefold only).
- `src/sciencemath/knowledge/provenance_spoof.py` — minimum spoof repair
  enforcing the invariant "user-provided citation/source IDs are NOT
  provenance; only retrieved/validated evidence may establish citation
  authority". Harmless discussion of citation syntax is not blocked.
- `rag/gk_holdout_t21r3/` — new blind holdout corpus (854 world records,
  16 sources, 750 chunks), first committed only in the final T21R3 commit.
- `evaluations/t21r3/**` — freezes, contract, suites, audits, one-shot
  results, ledger, failure analysis, decision, battery, final audit,
  blindness audit, report.
- `scripts/t21r3_*.py` — T21R3 harness scripts (new files).
- `tests/test_t21r3_conflict_repair.py`,
  `tests/test_t21r3_spoof_repair.py` — repair regression tests.
- `tests/test_t21r3_blind_holdout_contract.py` — new firewall test file.
- `tests/test_historical_artifact_write_guard.py` — one preregistered
  delta: the T21R3 harness registration (same pattern as T16..T21R2).

NOT changed:
- `src/sciencemath/executive/skills.py` — byte-identical to the T21R3.B1
  freeze; **KNOWLEDGE_RAG stays EXPERIMENTAL** (the decision action is a
  registry no-op by design).
- Executive Router — EXPERIMENTAL, untouched.
- Every other frozen runtime group — recomputed composites match
  `runtime_freeze.json` exactly.
- `evaluations/t21/**`, `evaluations/t21r/**`, `evaluations/t21r2/**`,
  `rag/gk_corpus/`, `rag/gk_holdout_t21r/`, `rag/gk_holdout_t21r2/` —
  byte-identical to the canonical base (protection battery layer 6).
- T21R2 gold, artifacts and results — untouched; the T21R2 replay ran
  NON-PROMOTIONALLY before the repair (`t21r2_replay_non_promotional.json`)
  and `t21r2_spoof_root_cause.json` records the spoof root cause.
- `evaluations/t15r/mutation_safety_probe.json` — git blob still
  `fba2437f78633884bd31965d78a4250bd1ca893c`.
- Top-level `full_junit.xml` — not drifted.

## 2. Blind construction (Commit 3 pipeline)

1. **T21R3.B1 runtime freeze** — composite SHA-256 over every frozen
   runtime group AFTER the repair commit; KNOWLEDGE_RAG registry record
   (EXPERIMENTAL, registry `1d04bd00…`); refuses to run once
   `rag/gk_holdout_t21r3/world.jsonl` exists. Recorded before holdout
   construction.
2. **T21R3.1 evaluator freeze** — `scripts/t21r3_run_eval.py` source hash
   `bfee6c21…` plus preregistered scoring semantics, frozen before holdout
   construction.
3. **Validation contract** — floors (32 across retrieval/answers/citations/
   abstention_conflict/temporal/security), 20 zero-tolerance gates, suite
   minimums (320/300/220/220/240/280/240/320, total ≥ 2140), uniqueness
   rule, one-shot rule, post-freeze immutability.
4. **World regeneration (entirely new)** — no T21/T21R/T21R2 entity
   identity reused: 40 new towns, 30 new people (with near-name families),
   38 new works, 12 artworks, 12 institutions, 12 technologies, 4 nations,
   16 curated facts, 6 slow-geography facts, 5 absent entities, 10 new
   injection directives (all verified against the frozen runtime's
   directive patterns), and a 159-entry year table (1100–1261) disjoint
   from every year value used by the three prior worlds.
5. **Static pre-freeze QA** — `static_gold_audit.json`: PASS, 0 failures,
   2214 rows; coverage/entity-gate/temporal/conflict mechanics
   transcribed bit-identically from the frozen runtime and verified
   against it on synthetic inputs only (firewall-tested).
6. **Eight suites** — retrieval `rw-`, singlehop `bn-`, multihop `cw-`,
   crossdomain `dx-`, citation `gz-`, conflict-abstention `hl-`, temporal
   `jm-`, adversarial `kv-`; 2214 rows: retrieval 320, singlehop 306,
   multihop 224, crossdomain 225, citation 245, conflict-abstention 302,
   temporal 250, adversarial 342.
7. **Uniqueness audit** — verdict **UNIQUE**: 0 overlap against the UNION
   of T21 + T21R + T21R2 on case ids, entity identities (substring-checked
   both directions), exact queries, chunk ids, source ids, gold answer
   values, exact source texts, and verbatim attack strings; 0 duplicate
   rows/queries within T21R3. Near-duplicate Jaccard flags (211) are
   audit-only.
8. **HOLDOUT_FROZEN** — manifest over all frozen inputs, corpus and
   suites; written before any runtime exposure.

The firewall (`tests/test_t21r3_blind_holdout_contract.py`, 33 tests)
mechanically enforces: no runtime import or entrypoint name in any
construction script; freeze ordering and tamper detection (composites
recomputed); bit-identical transcription of runtime mechanics on synthetic
inputs; manifest agreement; post-freeze suite immutability.

## 3. The one-shot evaluation

`official_runtime_exposures = 1` (`evaluation_run_ledger.json`, exit 0,
no preview/smoke/dry-run). The frozen evaluator ran the frozen runtime
over all 2214 rows exactly once.

**Passed (31 of 32 floors):**
- Retrieval: recall@5 = recall@10 = 0.9906 (floor 0.94), MRR 0.962,
  nDCG@5 0.9694, source diversity 0.9978.
- Grounded accuracy: overall 0.9921 (≥0.90), domain macro 0.9941 (≥0.88),
  singlehop 1.0 (≥0.92), multihop 1.0 (≥0.85), crossdomain 0.9956 (≥0.86).
- Citations: resolvability/validity/precision/coverage/
  supported-claim-rate all 1.0, fabricated citations 0, unsupported
  confident answers 0.
- Abstention: insufficient-evidence precision 1.0, recall 1.0.
- **Conflict false resolution 0.0 — the T21R2 defect is repaired** (T21R2
  lost 32+ rows to false conflicts on identical-value restatements; zero
  recurred).
- Temporal: explicit-current routing 1.0, stale-current 0, unnecessary web
  routing 0.0, historical as-of 1.0.
- Security: prompt-injection containment 1.0, **citation-id spoof
  rejection 1.0** (was 0.92 in T21R2), all zero-tolerance counters 0
  (no authority escalation, memory backfill, code execution, network
  action, or unauthorized memory write on any of 342 adversarial rows).
- All 8 suite minimums met.

**Failed (1 floor):**

| group | metric | value | floor |
|---|---|---|---|
| abstention_conflict | conflict_detection | 0.8889 (48/54) | ≥ 0.98 |

## 4. Failure analysis — one new case class, exactly reconciled

`conflict_detection = 48/54 = 0.8889` exactly. The 6 missed gold-conflict
rows did **not** answer (`conflict_false_resolution = 0.0`) — they
abstained `INSUFFICIENT_EVIDENCE`. The repair's core guarantee held: no
silently resolved conflict anywhere in the holdout.

**Mechanism (static evidence, no second runtime exposure):** conflict
scoping in the frozen pipeline (`_relevant_conflicts`,
`src/sciencemath/knowledge/pipeline.py:201-211`) requires the TOP-RANKED
reranked item to carry `fact_entity`/`fact_attribute` metadata. The new
equal-authority conflict composition probes 9 phrasings per conflict; for
phrasings whose content tokens overlap the conflict chunk text weakly
(e.g. "recorded" / "listed" / "establishment" vs the chunk sentence "The
established year of X is NNNN, per the Register…"), a chunk without fact
metadata can rank first, the scoped conflict list is empty
(`NO_CONFLICT`), and the row then hits the coverage gate, which abstains
instead of surfacing `CONFLICTING_EVIDENCE`. This case class (top-item
metadata scoping) is distinct from the T21R2 defect (value comparison) and
was never exercised by T21/T21R/T21R2 — the strict blind holdout is again
the first to exercise it.

**Evaluator validity: VALID.** The evaluator source hash matches the
pre-holdout freeze; the post-freeze evaluator bug policy
(`T21R3_EVALUATOR_INVALID`) was NOT triggered. The failed floor is frozen
runtime behavior on valid gold.

## 5. Decision

**KEEP_KNOWLEDGE_RAG_EXPERIMENTAL** — mechanically derived
(`final_decision.json`): zero-tolerance all zero and all suite minimums
met, but one capability floor failed, so the preregistered decision
function keeps the skill EXPERIMENTAL. **No registry change was applied**
(`applied: false`; `src/sciencemath/executive/skills.py` byte-identical to
the freeze). **No post-freeze repair is permitted**: the holdout is now
runtime-exposed, so any repair informed by these results would invalidate
the blind validation. A future milestone (T21R4 or equivalent) must repair
the top-item conflict-scoping path and build a NEW blind holdout under the
same regime — this holdout is now non-promotional.

The repair of record stands verified: the T21R2 defects (value-blind
conflict detection, spoofable citation provenance) are fixed on fresh
blind evidence; the remaining gap is narrower and different in kind.

## 6. Protection and integrity

- Protection battery **ALL_PASS** (7 layers): every frozen runtime
  composite — the repaired knowledge runtime included — matches the
  T21R3.B1 freeze; registry matches the freeze record (KNOWLEDGE_RAG
  EXPERIMENTAL, 11 ACTIVE / 1 EXPERIMENTAL); Executive Router untouched;
  T15R canonical blob `fba2437f…` unchanged; mutation probe rerun with
  milestone-local `--out evaluations/t21r3/mutation_safety_probe.json`;
  holdout freeze identity re-verified AFTER the evaluation; historical
  artifacts (T21 + T21R + T21R2 + three corpora) byte-identical to the
  canonical base; security pytest subset green.
- Full pytest: **1713 tests, 0 failures, 0 errors, 2 skipped** →
  `evaluations/t21r3/full_junit.xml` + `evaluations/t21r3/pytest_final.json`;
  top-level `full_junit.xml` not drifted.
- `final_audit.json`: **ALL_CHECKS_PASS** (24 mechanical checks, including
  the honest-failure gate `floors_failed_as_recorded`).
- `blindness_audit.json`: **BLINDNESS_MAINTAINED** — runtime freeze <
  evaluator freeze < HOLDOUT_FROZEN < evaluation start (recorded
  timestamps); freeze scripts structurally refuse holdout-first ordering;
  construction scripts are runtime-isolated (firewall-tested); pre-freeze
  blindness audit has 0 violations; exactly one runtime exposure; no
  post-freeze repair.

## 7. What a future milestone must do

1. Repair conflict scoping: when any retrieved evidence item (not only the
   top-ranked one) carries fact metadata matching a detected conflict's
   claim key, scope the conflict — or rank fact-metadata chunks first for
   conflict-prone phrasings.
2. Keep the equal-authority multi-phrasing conflict composition mandatory
   (9 phrasings per conflict) — it is the case class that caught this gap.
3. Keep the value-comparison repair and provenance-spoof gate (both now
   verified on blind data by `tests/test_t21r3_conflict_repair.py` and
   `tests/test_t21r3_spoof_repair.py`).
4. Build a NEW blind holdout (T21R4) under the same freeze-first regime;
   the T21R3 holdout is runtime-exposed and non-promotional.

---

**STOP. Do not start T22.**