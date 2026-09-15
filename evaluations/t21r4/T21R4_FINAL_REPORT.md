# T21R4 FINAL REPORT — conflict-scoping repair validated on a fresh strict blind holdout

**Decision: KEEP_KNOWLEDGE_RAG_EXPERIMENTAL**
**Branch:** `t21r4-conflict-scoping-repair-blind-validation` (NOT merged; pushed
for independent mechanical audit)
**Canonical base:** `9932fee0b3bfe01797b743e0e829aaca404f5ba7` (main, the
T21R3 merge commit)
**Repair commit:** `c1227ab789bdc50b9c2a8c0a2da0c991fda01f78`
**Recorded:** 2026-09-15

T21R4 answers the question T21R3 left open: does the **conflict-scoping
repair** make the KNOWLEDGE_RAG runtime meet the preregistered promotion
bar on a holdout that was provably never exposed to any runtime function?
T21R3 failed exactly one floor (`conflict_detection = 0.8889`): conflict
scoping required the TOP-RANKED reranked item to carry fact metadata, so
on phrasings whose content tokens overlap the conflict chunk text weakly,
a chunk without fact metadata could rank first, the scoped conflict list
went empty, and the row abstained instead of surfacing
`CONFLICTING_EVIDENCE`. T21R4 repaired exactly that with a
**query-relevant** scoping rule (Commit 2, `c1227ab`) — a conflict is
scoped as relevant when ANY retrieved evidence item (not only rank 1)
carries fact metadata matching the conflict's claim key — then rebuilt
the entire validation under the same blind-construction regime: runtime,
evaluator and contract frozen BEFORE holdout data existed; holdout built
from an entirely new world with a strengthened conflict stress suite;
frozen (`HOLDOUT_FROZEN`, manifest sha256 `dcd81471…ddfe98c`); evaluated
exactly once.

**The repair target is achieved on blind data: `conflict_detection =
120/120 = 1.0`** (T21R3: 48/54 = 0.8889), with **conflict false
resolution 0.0** and **insufficient-evidence recall 1.0**. 26 of 32
preregistered floors pass; all zero-tolerance counters are zero on all
2535 rows. The decision is nonetheless KEEP_EXPERIMENTAL: 6 floors fail
— source diversity 0.882 (< 0.95), the three citation floors at 0.9622
(≠ 1.0 / < 0.99), insufficient-evidence precision 0.9606 (< 0.98, 8
over-abstentions), and prompt-injection containment 0.9794 (≠ 1.0, 8 of
389 adversarial rows). The skill stays EXPERIMENTAL and a future
milestone must build a NEW blind holdout; the T21R4 holdout is now
exposed and non-promotional.

---

## 1. What T21R4 changed (and did not change)

Changed:
- `src/sciencemath/knowledge/pipeline.py` — the preregistered repair:
  query-relevant conflict scoping. A detected conflict is scoped as
  relevant when any retrieved evidence item in the window carries
  `fact_entity`/`fact_attribute` metadata matching the conflict's claim
  key — not only the top-ranked item. No semantic embeddings, no model
  calls, no nondeterministic classification; the scoping signal is the
  same frozen fact-metadata schema.
- `rag/gk_holdout_t21r4/` — new blind holdout corpus (1546 world records,
  16 sources, 1245 chunks), first committed only in the final T21R4
  commit.
- `evaluations/t21r4/**` — freezes, contract, suites, audits, one-shot
  results, ledger, failure analysis, decision, battery, report.
- `scripts/t21r4_*.py` — T21R4 harness scripts (new files).
- `tests/test_t21r4_blind_holdout_contract.py` — new firewall test file
  (34 tests).
- `tests/test_historical_artifact_write_guard.py` — one preregistered
  delta: the T21R4 protection battery registration (same pattern as
  T16..T21R3).

NOT changed:
- `src/sciencemath/executive/skills.py` — byte-identical to the T21R4.B1
  freeze; **KNOWLEDGE_RAG stays EXPERIMENTAL** (the decision action is a
  registry no-op by design).
- Executive Router — EXPERIMENTAL, untouched.
- `evaluations/t21/**`, `evaluations/t21r/**`, `evaluations/t21r2/**`,
  `evaluations/t21r3/**`, `rag/gk_corpus/`, `rag/gk_holdout_t21r/`,
  `rag/gk_holdout_t21r2/`, `rag/gk_holdout_t21r3/` — byte-identical to
  the canonical base (protection battery layer 6).
- The T21R3 holdout was used ONLY for diagnosis, reproduction, and
  unit/regression testing during the repair phase (pre-freeze); it was
  never used as T21R4 promotion evidence. The T21R3 failure mechanism is
  frozen in `t21r3_failure_evidence.json` and reproduced by
  `t21r3_replay_non_promotional.json` / `t21r3_root_cause.json`.
- T21R3 gold, artifacts and results — untouched.
- `evaluations/t15r/mutation_safety_probe.json` — git blob still
  `fba2437f78633884bd31965d78a4250bd1ca893c`.
- Top-level `full_junit.xml` — not drifted (it does not exist at the
  repo root; the milestone junit is `evaluations/t21r4/full_junit.xml`).

## 2. Blind construction (Commit 3 pipeline)

1. **T21R4.B1 runtime freeze** — composite SHA-256 over 14 frozen runtime
   groups AFTER the repair commit; KNOWLEDGE_RAG registry record
   (EXPERIMENTAL); refuses to run once
   `rag/gk_holdout_t21r4/world.jsonl` exists. One preregistered
   re-record (`re_record_post_registration` marked in the freeze doc):
   the protection-battery registration delta changed the
   `historical_write_guard` composite after the original B1 freeze;
   every OTHER group was proven byte-identical to the original freeze
   and the holdout corpus/suites proven untouched against the
   HOLDOUT_FROZEN manifest before the re-record. The evaluator source
   itself was never modified (its frozen hash matched at evaluation
   time).
2. **T21R4.1 evaluator freeze** — `scripts/t21r4_run_eval.py` source hash
   (raw sha256 `066ea9ab…dc0d100e`) plus preregistered scoring
   semantics, frozen before holdout construction.
3. **Validation contract** — floors (32 across retrieval/answers/
   citations/abstention_conflict/temporal/security), zero-tolerance
   gates, suite minimums (320/320/200/200/240/400/220/320, total
   ≥ 2300), conflict stress requirements (`conflicts_with_relevant_
   evidence_not_rank1_min: 80`), uniqueness rule, one-shot rule,
   post-freeze immutability.
4. **World regeneration (entirely new)** — no T21/T21R/T21R2/T21R3
   entity identity reused: 4 nations, 84 towns, new people (with
   near-name families), works, artworks, institutions, technologies,
   curated facts, slow-geography facts, absent entities, near-miss
   distractors, 12 injection directives, and a year table disjoint from
   every prior world's year values. Four name collisions found by the
   uniqueness audit (Ravenscar, Saltmarsh, Elverton, Yelverton) were
   replaced (Ravenmill, Salternwick, Elverholt, Yelverley) and the world
   fully rebuilt BEFORE the freeze.
5. **Conflict stress suite (strengthened)** — the conflict suite probes
   the T21R3 failure mechanism directly: 240 genuine conflicts across
   3 phrasings each, of which **80 are preregistered not-rank-1 cases**
   (stress phrasings reproduce the top-item scoping failure: the
   same-entity mayor chunk out-covers the conflict pair so the relevant
   conflict evidence ranks 2–3, never 1), plus 80 unresolved-conflict
   rows, 80 unrelated-conflict negatives, 100 same-value restatements,
   and near-duplicate negatives — 527 conflict-suite rows total.
6. **Static pre-freeze QA** — `static_gold_audit.json`: **pass, 0
   failures, 2535 rows**; the frozen retrieval arithmetic (tokenize /
   stopwords / BM25 Okapi k1=1.2 b=0.75 / rerank / Jaccard dedup /
   MAX_PER_SOURCE / top-8 window) was transcribed bit-identically from
   the frozen runtime and verified against it on synthetic inputs only
   (firewall-tested). Every gold-conflict pair verified in-window;
   not_rank1 = 80 (exactly meets the contract minimum); every gold row
   answered from the window.
7. **Eight suites** — retrieval `re-`, singlehop `sh-`, multihop `mh-`,
   crossdomain `cd-`, citation `cc-`, conflict-abstention `ca-`,
   temporal `tm-`, adversarial `ad-`; **2535 rows**: retrieval 320,
   singlehop 340, multihop 224, crossdomain 225, citation 260,
   conflict-abstention 527, temporal 250, adversarial 389.
8. **Uniqueness audit** — verdict **UNIQUE**: 0 overlap against the
   UNION of T21 + T21R + T21R2 + T21R3 on case ids, entity identities
   (substring-checked both directions, in both query directions), exact
   queries, chunk ids, source ids, gold answer values, exact source
   texts, and verbatim attack strings; 0 duplicate rows/queries within
   T21R4. Near-duplicate Jaccard flags (79) are audit-only.
9. **HOLDOUT_FROZEN** — manifest over all frozen inputs, corpus and
   suites; written before any runtime exposure.

The firewall (`tests/test_t21r4_blind_holdout_contract.py`, 34 tests)
mechanically enforces: no runtime import or entrypoint name in any
construction script (plus a string-literal scan for runtime function
names, docstring excluded); freeze ordering and tamper detection
(composites recomputed); bit-identical transcription of runtime
mechanics on synthetic inputs; override-table fidelity against
`injection._QUERY_OVERRIDE_PATTERNS`; manifest agreement; post-freeze
suite immutability.

## 3. The one-shot evaluation

`official_runtime_exposures = 1` (`evaluation_run_ledger.json`, exit 0,
no preview/smoke/dry-run). The frozen evaluator ran the frozen runtime
over all 2535 rows exactly once (2026-09-15T21:35:34Z → 21:35:36Z).

**Passed (26 of 32 floors):**
- Retrieval: recall@5 = recall@10 = **1.0**, MRR 0.9875, nDCG@5 0.9908.
- Grounded accuracy: overall 0.9634 (≥0.90), domain macro 0.9705 (≥0.88),
  singlehop 0.9971 (≥0.92), multihop 0.875 (≥0.85), crossdomain synthesis
  0.8889 (≥0.86).
- **Conflict: `conflict_detection = 120/120 = 1.0` — the T21R4 repair
  target achieved on blind data** (T21R3: 48/54 = 0.8889), with
  **conflict false resolution 0.0** and insufficient-evidence recall 1.0.
  All 80 preregistered not-rank-1 stress cases resolved correctly, and
  all 6 gold per-category conflict classes pass: authority_resolvable 1.0,
  freshness_resolvable 1.0, unresolved 1.0, unrelated-conflict negative
  1.0, near-duplicate false-conflict negative, name-family
  disambiguation 1.0.
- Temporal: explicit-current routing 1.0, stale-current 0, unnecessary web
  routing 0.0, historical as-of 1.0.
- Security: **citation-id spoof rejection 1.0**, fabricated citations 0,
  unsupported confident answers 0, all zero-tolerance counters 0 (no
  authority escalation, memory backfill, code execution, network action,
  or unauthorized memory write on any of 389 adversarial rows).
- Citation coverage 1.0, supported-factual-claim-rate 1.0.
- All 8 suite minimums met.

**Failed (6 floors):**

| group | metric | value | floor |
|---|---|---|---|
| retrieval | source_diversity | 0.882 (396/449) | ≥ 0.95 |
| citations | citation_resolvability | 0.9622 | = 1.0 |
| citations | citation_validity | 0.9622 | = 1.0 |
| citations | citation_precision | 0.9622 | ≥ 0.99 |
| abstention_conflict | insufficient_evidence_precision | 0.9606 (195/203) | ≥ 0.98 |
| security | prompt_injection_containment | 0.9794 (381/389) | = 1.0 |

## 4. Failure analysis — separate surfaces, exactly reconciled

`failure_analysis.json` reconciles every failed floor to integer row
counts against the gold suites (pure artifact reconciliation — no runtime
re-exposure):

- **Conflict suite over-abstentions (8/527 rows; the 0.9606 floor):**
  120/120 gold conflicts detected; 195 of 203 abstained rows are
  gold-abstain (precision 195/203 = 0.9606). The 8 over-abstentions are
  answer-mode rows in the conflict suite whose gold expects a resolved
  ANSWER. Mechanism (HYPOTHESIS, static reading only): query-relevant
  scoping widened the scoped-conflict set; on a small set of authority-/
  freshness-resolvable or negative rows the scoped list is now non-empty
  and the pipeline abstains instead of resolving. Notably the two
  authority-/freshness-resolvable conflict categories themselves score
  1.0 — the over-abstentions sit elsewhere in the suite's answer rows.
- **Source diversity (53/449 multisource rows below the bar):** with
  MAX_PER_SOURCE=3 and 4-gram Jaccard dedup, same-entity restatement
  chunks can occupy the window so one of the two required source
  identities is absent from the final top-8 on some multihop/crossdomain
  rows.
- **Citation verdict gaps (0.9622 over all 1801 answer-mode rows):** a
  small set of answer rows carry citations whose verdicts are not OK; the
  frozen evaluator wrote no per-row artifact, so no row-level
  reconciliation is possible without re-exposure, which is forbidden.
- **Injection containment (8/389 not contained):** containment counts
  adversarial rows that answered correctly AND carried no non-zero
  zero-tolerance counter; 8 rows failed at least one condition (all
  zero-tolerance counters remain zero, so the failures are wrong-answer
  containment rows).

**Evaluator validity: VALID.** The evaluator source hash matches the
pre-holdout evaluator freeze; the post-freeze evaluator bug policy
(`T21R4_EVALUATOR_INVALID`) was NOT triggered. The failed floors are
frozen runtime behavior on valid gold.

## 5. Decision

**KEEP_KNOWLEDGE_RAG_EXPERIMENTAL** — mechanically derived
(`final_decision.json`): zero-tolerance all zero and all suite minimums
met, but 6 of 32 preregistered capability floors failed, so the
preregistered decision function keeps the skill EXPERIMENTAL. **No
registry change was applied** (`applied: false`;
`src/sciencemath/executive/skills.py` byte-identical to the freeze).
**No post-freeze repair is permitted**: the holdout is now
runtime-exposed, so any repair informed by these results would invalidate
the blind validation. A future milestone (T21R5 or equivalent) must build
a NEW blind holdout under the same regime — the T21R4 holdout is now
non-promotional.

The repair of record stands verified: **the T21R3 top-item conflict-
scoping defect is fixed on fresh blind evidence** (`conflict_detection`
0.8889 → 1.0, including all 80 preregistered not-rank-1 stress cases),
with zero false resolutions and zero zero-tolerance violations. The
remaining gaps are different in kind: multi-source window diversity,
citation verdict completeness on answer rows, over-abstention on a
handful of conflict-suite answer rows, and 8 adversarial containment
rows.

## 6. Protection and integrity

- Protection battery **ALL_PASS** (7 layers): every frozen runtime
  composite — the repaired knowledge runtime included — matches the
  T21R4.B1 freeze; registry matches the freeze record (KNOWLEDGE_RAG
  EXPERIMENTAL); Executive Router untouched; T15R canonical blob
  `fba2437f…` unchanged; mutation probe rerun with milestone-local
  `--out evaluations/t21r4/mutation_safety_probe.json`; holdout freeze
  identity re-verified AFTER the evaluation; historical artifacts
  (T21 + T21R + T21R2 + T21R3, four corpora) byte-identical to the
  canonical base; security pytest subset green.
- Full pytest: **1759 tests, 0 failures, 0 errors, 2 skipped** →
  `evaluations/t21r4/full_junit.xml`; top-level `full_junit.xml` not
  drifted.
- Freeze chain recorded: runtime freeze hash `27106583…025388`,
  evaluator freeze hash `15af95d9…749964`, holdout manifest sha256
  `dcd81471…ddfe98c`; runtime freeze < evaluator freeze < HOLDOUT_FROZEN
  < evaluation start (recorded timestamps).
- No post-freeze repair; no rerun of any holdout row; exactly one
  official runtime exposure.

## 7. What a future milestone must do

1. Address the four remaining failure surfaces in priority order:
   multi-source window diversity (source_diversity 0.882), citation
   verdict completeness on answer rows (0.9622), conflict-suite
   over-abstention (8 rows), adversarial containment (8 rows) — each
   needs its own root-cause evidence from a NEW blind holdout.
2. Keep the query-relevant conflict scoping repair and the not-rank-1
   stress composition (80/240) mandatory — it is the case class that
   caught the T21R3 gap and it passed 1.0.
3. Keep the value-comparison repair and provenance-spoof gate (verified
   again on blind data by the T21R4 regression gates and protection
   battery).
4. Build a NEW blind holdout (T21R5) under the same freeze-first regime;
   the T21R4 holdout is runtime-exposed and non-promotional.

---

**STOP. Do not start T22.**