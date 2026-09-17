# T21R6 FINAL REPORT — Knowledge RAG Final Closure Attempt

**Milestone:** T21R6 — KNOWLEDGE RAG FINAL CLOSURE ATTEMPT
**Branch:** `t21r6-knowledge-rag-final-closure` (pushed, NOT merged)
**Canonical base:** `f71cdb6e7855ba20d58e38b05d7286457bc300ae` (PR #20 T21R5 historical merge)
**Commit 1:** `46d2251d8dfd961ebf68b34f5ff96d760747f967` — *T21R6: harden evaluator and repair multihop reasoning*
**Commit 2:** *T21R6: validate Knowledge RAG on fresh strict blind holdout* (this milestone's validation commit)
**Date:** 2026-09-16

---

## 1. Decision

| Item | Value |
| --- | --- |
| Official exposure count | **1** (one-shot rule honoured; run completed with exit 0, no crash) |
| Preregistered floors passed | **26 / 32** |
| Zero-tolerance counters | **all zero** |
| Suite minimums met | **yes** (3753 rows ≥ 3600; every suite at/above minimum) |
| **Decision** | **KEEP_KNOWLEDGE_RAG_EXPERIMENTAL** |
| T21 status | **OPEN** (validation attempt completed; floors unmet) |
| Ready for T22 | **NO** (T21 closure additionally requires the independent ChatGPT mechanical audit; T22 is BLOCKED) |
| Promotion commit 3 | **NOT created** (floors did not all pass) |

Per the preregistered one-shot rule there is **no fix, no rerun, no gold change, no
floor change** after `HOLDOUT_FROZEN`. The T21R6 holdout is consumed; a future
milestone (T21R7) requires a **new fresh blind holdout**.

## 2. What T21R6 repaired and proved

1. **Entry-gate repair + inherited-debt ledger.** The T21R4 evaluator freeze debt
   was pinned byte-exactly in `evaluations/t21r6/inherited_historical_debt.json`.
   The post-exposure battery mechanically proved five further freeze-input
   mismatches that pre-date T21R6 (each file byte-identical to the canonical-base
   git blob, last changed by its own milestone's validation commit
   `fbe034a`/`da044e4`); the ledger was extended to the closed six-entry set and
   the battery tolerance is now ledger-driven.
2. **Part A — evaluator `required_domains` repair.** The T21R5 evaluator crash
   (`AttributeError` at `scripts/t21r5_run_eval.py:186`, `.get` on a dataclass)
   was repaired via **normalized `topic_tags` of the sources actually cited** —
   never `s.domain`. The repaired evaluator ran the full T21R6 holdout
   (3753 rows) with **zero exceptions**.
3. **Evaluator qualification gate.** 35/35 synthetic cases pass, 0 uncaught
   exceptions, all paths exercised — recorded in
   `evaluations/t21r6/evaluator_qualification.json` **before** the evaluator
   freeze. The evaluator may not be frozen unqualified (T21R5 lesson).
4. **Part C — T21R5 replay (non-promotional).** The repaired runtime + evaluator
   replayed the entire exposed T21R5 holdout: **3531/3531 rows, 0 exceptions,
   all floors pass on replay** — development evidence only (that holdout was
   already exposed and can never promote).
5. **Runtime/evaluator freezes before holdout data.** `runtime_freeze.json` and
   `evaluator_freeze.json` (evaluator sha `92e9e6f8…`) were recorded on the
   repaired runtime **before** any T21R6 holdout data existed; the evaluator's
   `check_freeze` verifies every frozen hash pre-run.

## 3. The fresh T21R6 blind holdout

- **3753 rows / 8 suites** — retrieval 566, singlehop 512, multihop 416
  (416 author→birthplace rows ≥ 120; 416 new-wording rows ≥ 150),
  crossdomain 400 (every row carries exactly 2 `required_domains`),
  citation-claim 365, conflict-abstention 669, temporal 250, adversarial 575.
- **Uniqueness:** verdict `UNIQUE` vs the union of T21/T21R/T21R2/T21R3/T21R4/T21R5
  (queries, case ids, entities, chunk/source ids, chunk texts, gold answer
  values, verbatim attack strings — all zero overlap; absent probe entities
  mechanically verified absent from all prior corpora and query sets).
- **Static gold audit (data-only, local reimplementation of the frozen retrieval
  arithmetic):** `PASS` — every gold chunk in-window (3303/3303), conflict
  windows complete, 145/145 winner-not-rank-1 stress rows, 510/816 naive-window
  domination rows, coverage gate 0 failures, hop-2 bridge 0 failures, exposure
  quarantine, spoof flags, conflict negatives, absent probes all clean.
- **Frozen:** `HOLDOUT_FROZEN` + `holdout_manifest.json`
  (manifest sha `4ad24371ad37a91f0ef83dba4e46faaad88ec45ae6cd88d97cb385ab554fa199`).
- **Blindness firewall:** builders import no runtime module (AST-scanned by
  `tests/test_t21r6_blind_holdout_contract.py`).

## 4. The one official exposure — results

Run ledger was preregistered before execution
(`evaluations/t21r6/evaluation_run_ledger.json`); the evaluator refuses to run
if `raw_results.jsonl` exists. Raw results are immutable.

Per-suite highlights: retrieval recall@5/10 = 1.0 (mrr 0.9965, ndcg@5 0.9974);
singlehop 1.0; crossdomain 1.0; conflict_detection **1.0** with 0 false
resolutions; IE recall 1.0; temporal all four floors perfect; spoof rejection
1.0; all five security event counters 0; fabricated citations 0.

**Failing floors (6):**

| Group | Metric | Value | Floor |
| --- | --- | --- | --- |
| retrieval | source_diversity | 0.9216 | ≥ 0.95 |
| answers | multi_hop_grounded_accuracy | 0.8462 | ≥ 0.85 |
| citations | citation_resolvability | 0.9499 | = 1.0 |
| citations | citation_validity | 0.9499 | = 1.0 |
| citations | citation_precision | 0.9499 | ≥ 0.99 |
| security | prompt_injection_containment | 0.9496 | = 1.0 |

## 5. Root cause (data-only analysis of `raw_results.jsonl`)

All six failing floors are arithmetic consequences of **137 over-abstentions +
5 status mismatches** (142 affected rows) produced by the frozen runtime —
recorded in `evaluations/t21r6/over_abstention_root_cause.json`:

| Sub-mode | n | Mechanism |
| --- | --- | --- |
| A1 multihop "Fellwold" subject gate | 64 | The world-name qualifier appears in NO corpus chunk; the T21R6-hardened subject gate requires every subject token to be covered by the answer chunk → gate unpassable. All 64 failures are exactly the rows containing "fellwold". |
| A2 citation nominalization vocabulary | 42 | Query says "publication"/"introduction"; chunk says "was published in"/"was introduced in". The frozen tokenizer has no stemming → tier-1 sentence never evidenced. |
| B science-RAG misroute | 3 | "a molecule" triggers `ROUTE_SCIENCE_RAG(routed)`; the knowledge runtime never answers (glacier/strait/alloy are not routed). |
| C adversarial exposure vocabulary | 28 | "associated with" / "active in" / "used for" vs chunk "bears the emblem" / "field of study is" / "executed in". |
| D absent-entity conflict route | 5 | ABSENT_Q phrasing "Which record mentions the invention of {e}?" matches the conflict-register vocabulary ("Roll … Records") → CONFLICTING_EVIDENCE instead of INSUFFICIENT_EVIDENCE. |

The T21R6 repairs themselves **worked**: crossdomain 1.0 (the repaired surface),
singlehop 1.0, overall grounded accuracy 0.9539, conflict_detection 1.0
(T21R3/T21R4's failing floor), spoof rejection 1.0, all event counters 0 — the
regression surface is now concentrated in the new phrasing banks' exact-token
vocabulary against the no-stemming gate.

## 6. Protection battery + full pytest

- **Protection battery: ALL_PASS** (8 layers): runtime freeze identity (every
  composite matches the freeze, including the repaired knowledge runtime),
  registry boundaries (KNOWLEDGE_RAG still EXPERIMENTAL), T15R canonical blob
  `fba2437…` unchanged, mutation probe contained, T21R4 and T21R5 exposed
  holdouts byte-identical to their freeze manifests under the ledger-pinned
  inherited debt, all T21..T21R5 artifacts and corpora byte-identical to the
  canonical base, security pytest green.
- **Full pytest: PASS** — 1941 tests, 0 failures, 0 errors, 2 skipped
  (`evaluations/t21r6/pytest_final.json`, `full_junit.xml`).

## 7. What a future milestone (T21R7) must do

1. New fresh blind holdout (the T21R6 holdout is exposed/consumed).
2. Repair candidates recorded in the root-cause file: drop world-qualifier
   tokens ("Fellwold") from query banks or extend the subject-gate framing
   vocabulary; align query attribute vocabulary with corpus sentence tense or
   extend the attribute-cue mapping; restrict science-RAG eligibility routing;
   never let the conflict path outrank the absent-entity abstention for a
   corpus-absent entity.
3. Same preregistration discipline: contract, runtime freeze, evaluator
   qualification + freeze, HOLDOUT_FROZEN, one exposure.
4. T22 remains BLOCKED until the independent ChatGPT mechanical audit closes T21.

## 8. Artifact index (evaluations/t21r6/)

`validation_contract.json`, `entry_gate_baseline.json`,
`inherited_historical_debt.json`, `runtime_freeze.json`,
`evaluator_qualification.json`, `evaluator_freeze.json`,
`t21r5_replay_non_promotional.json`, `static_gold_audit.json`,
`holdout_uniqueness.json`, `holdout_manifest.json`, `HOLDOUT_FROZEN`,
`evaluation_run_ledger.json`, `raw_results.jsonl`, `holdout_results.json`,
`over_abstention_root_cause.json`, `final_decision.json`,
`pytest_final.json`, `full_junit.xml`, `protection/`, `suites/`.