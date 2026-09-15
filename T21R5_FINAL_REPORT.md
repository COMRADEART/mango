# T21R5 FINAL REPORT — Knowledge RAG reliability closure: repairs proven on T21R4 replay; blind validation terminated T21R5_EVALUATOR_INVALID by a post-freeze evaluator crash

**Decision: T21R5_EVALUATOR_INVALID** (preregistered in
`validation_contract.json → allowed_decisions` and
`post_freeze_evaluator_bug_rule`)
**Branch:** `t21r5-knowledge-rag-reliability-closure` (NOT merged; pushed for
independent mechanical audit)
**Canonical base:** `6174ebde0972a3f199b231a160bdb0875eb9bb7a` (main, the
T21R4 merge commit)
**Repair commit:** `d8076beb1012f83723e1ccd91967cee2b5af2ab8`
**Holdout freeze:** `HOLDOUT_FROZEN`, manifest sha256
`74d2ad4621418bf74ace57a6a402f24c25720b7bdeea1b7a781af6b48143e87f`
**Recorded:** 2026-09-15

T21R5 set out to (A) diagnose the six failed T21R4 floors, (B) repair them
with generalized runtime changes, (C) prove the repairs on the exposed
T21R4 holdout as strictly non-promotional regression evidence, and (D)
re-run the full blind-validation discipline — runtime frozen, evaluator
frozen, holdout built blind, frozen, then evaluated exactly once. Phases
A–D were completed exactly as preregistered. The single official exposure
then crashed **inside the frozen evaluator** on the first gold row that
carries `required_domains`:

```
File "scripts/t21r5_run_eval.py", line 186, in run_answer_row
    s.get("domain") for s in (corpus.source(c["source_id"]) ...)
AttributeError: 'KnowledgeSourceRecord' object has no attribute 'get'
```

`corpus.source()` returns a `KnowledgeSourceRecord` dataclass; the
required-domains check calls dict-style `.get` on it. The line exists only
in the T21R5 evaluator — the T21R4 evaluator has no required-domains
handling; the defect was introduced in the T21R5 adaptation and could not
be exercised pre-freeze because the blindness rule forbids running the
runtime on any holdout datum before `HOLDOUT_FROZEN`.

Per the preregistered rule — verbatim: *"If an evaluator bug is discovered
after HOLDOUT_FROZEN or after the first evaluation starts: STOP. Do NOT fix
and rerun T21R5. Decision is T21R5_EVALUATOR_INVALID; the exposed holdout
becomes non-promotional and a future milestone with another fresh holdout
is required."* — nothing was fixed, nothing was re-run, and the decision is
**T21R5_EVALUATOR_INVALID**. The `evaluation_run_ledger.json` records
`exit_code 1`, `official_runtime_exposures 1` and the full traceback; the
evaluation completed 1288 of 3531 rows (retrieval, singlehop, multihop)
before the crash. Floors were never evaluated; no promotion is claimed;
KNOWLEDGE_RAG stays EXPERIMENTAL exactly as frozen.

---

## 1. What T21R5 changed (and did not change)

Changed (commit `d8076be`, frozen post-repair):
- `src/sciencemath/knowledge/` — the preregistered B-repairs, all
  generalized (no case IDs, no hardcoded T21R4 entity names):
  **B1** source-aware evidence diversification (window reservation
  `WINDOW_RESERVE_FRACTION = 0.5` reserves room for cross-source
  corroborators); **B2** resolved-conflict winner propagation (the
  resolved winner's chunk text drives the coverage gate via
  `synth_text`); **B3** citation-by-construction (citations resolved from
  selected evidence items); **B4** source-directive quarantine
  (sentence-level quarantine of retrieved directives,
  `quarantine_source_text`, 16 frozen directive patterns); plus 8 frozen
  query-override patterns in the injection scanner.
- `rag/gk_holdout_t21r5/` — new blind holdout corpus, first committed only
  in the final T21R5 commit.
- `evaluations/t21r5/**`, `scripts/t21r5_*.py`,
  `tests/test_t21r5_blind_holdout_contract.py` — freezes, contract,
  suites, audits, harness, firewall tests.

Unchanged (verified by the protection battery and the contract tests):
- Executive Router, skill registry (KNOWLEDGE_RAG EXPERIMENTAL), T15R
  canonical blob `fba2437f…`, all T21/T21R/T21R2/T21R3/T21R4 evaluation
  artifacts and corpora (byte-identical to canonical base `6174ebd`).

## 2. Phase A — diagnosis (T21R4 holdout used as development data only)

All T21R4-replay artifacts are labeled `T21R4_REPLAY_NON_PROMOTIONAL` with
`promotion_value: ZERO`. Root-cause reports:
`source_diversity_root_cause.json`, `citation_root_cause.json`,
`over_abstention_root_cause.json`, `injection_root_cause.json`,
`failure_taxonomy.json`, `diagnostic_replay.jsonl`. The six T21R4 failures
were traced to: window saturation by same-source near-duplicates
(diversity 0.882), citation ids resolved from a narrowed item set
(citation floors 0.9622), over-abstention when the resolved winner's text
was not measured by the coverage gate (IE precision 0.9606), and eight
injected-directive sentences surviving into answer content (containment
0.9794).

## 3. Phase C — repair proof on the exposed T21R4 replay (non-promotional)

Replaying the repaired runtime over the entire exposed T21R4 holdout:
**2535/2535 rows correct**, and every previously failed floor now at
target (`t21r4_replay_non_promotional.json`): source diversity 1.0 (≥0.95),
citation resolvability/validity 1.0, precision 1.0 (≥0.99), coverage 1.0
(≥0.98), supported 1.0 (≥0.99), fabricated 0, IE precision 1.0 (≥0.98),
over-abstentions 0, injection containment 1.0, spoof rejection 1.0,
conflict detection 1.0, false resolution 0.0. All development targets met;
this is regression evidence only and carries zero promotion value.

## 4. Phases D — blind construction and freeze (all completed pre-exposure)

- Runtime freeze recorded `2026-09-15T22:53:24Z` on the repaired runtime;
  evaluator freeze `22:55:54Z`; both BEFORE any T21R5 holdout data existed
  (enforced by `t21r5_freeze_runtime.py` refusing to run if
  `world.jsonl` exists).
- Holdout built entirely from a new Wealdmark world: **3531 rows / 8
  suites** (retrieval 488, singlehop 512, multihop 288, crossdomain 400,
  citation-claim 349, conflict-abstention 669, temporal 250, adversarial
  575) — every preregistered suite/composition minimum exceeded (≥2600
  total, ≥200 multi-source diversity cases, ≥100 naive-top-score
  domination, ≥300 citation rows, ≥150 resolvable conflicts, ≥160 fresh
  source injections with safe facts, ≥160 fresh query-side attacks).
- Construction is data-only (AST-verified: no runtime import or
  invocation in any construction script; all frozen arithmetic
  reimplemented locally and cross-checked bit-identically against the
  frozen runtime constants — token regex/stop-list, BM25 k1/b, coverage
  and rerank weights, dedup Jaccard/per-source caps, window reservation,
  authority ranks, frame-token vocabularies, as-of stripping, override
  and directive pattern tables, spoof ID regexes, corpus schema hash
  functions — on synthetic inputs only).
- Pre-freeze QA: static gold audit **PASS** (gold chunk in the computed
  final window for all 3081 answer-bearing rows, 0 coverage-gate misses,
  145/145 winner-not-rank-1 stress rows, 418 naive-top-score dominated
  rows, 0 spoof misses, 0 negative-class contamination); uniqueness audit
  **UNIQUE** against the union of all five prior worlds (case IDs,
  prefixes, queries, entities incl. whole-word identity, source/chunk
  IDs, answers, chunk texts, attack strings; 3 towns and one absent-probe
  entity were renamed at the source during construction when whole-word
  collisions with prior-world surnames/work titles/queries were
  detected).
- Contract tests: `tests/test_t21r5_blind_holdout_contract.py` — 37
  passed (3 post-freeze checks skipped until `HOLDOUT_FROZEN`; all pass
  post-freeze).
- `HOLDOUT_FROZEN` at `23:39:31Z`; official exposure started `23:39:42Z`.

## 5. The official exposure and the post-freeze evaluator crash

Exactly one official exposure was started. It processed 1288/3531 rows
(retrieval 488, singlehop 512, multihop 288 — all counters zero-tolerance
clean on those rows) and crashed on the first crossdomain row at the
frozen evaluator's required-domains check (defect detailed above). The
ledger froze `official_runtime_exposures: 1`. Per the preregistered rule
the run was **not** repaired, **not** re-run, and no frozen artifact was
touched after `HOLDOUT_FROZEN`.

Partial, explicitly **non-promotional** observations from the 1288
officially exposed rows (diagnostic data for a future milestone; the
holdout is now exposed and these numbers must never be cited as
validation):
- retrieval: 488/488 correct; Recall@5 1.0, Recall@10 1.0, MRR 0.9949,
  nDCG@5 0.9962.
- singlehop: 512/512 correct.
- multihop: 256/288 (0.8889). All 32 failures are one failure class: the
  phrasing "Within which town was the author of {work} born?" across 32
  distinct works ends `INSUFFICIENT_EVIDENCE` because the person-birthplace
  bridge chunk never enters the final window (hop2 bridge does not join)
  and the coverage measured on the selected winner span is 0.0 — while all
  other 8 phrasings of the same works pass. This phrasing-dependent
  bridge failure is recorded for the next milestone; it was NOT repaired
  post-freeze.

## 6. Protection battery

`evaluations/t21r5/protection/regression_summary.json`: **7 of 8 layers
PASS** (runtime freeze identity incl. the repaired knowledge runtime and
the Executive Router; registry boundaries with KNOWLEDGE_RAG EXPERIMENTAL;
T15R canonical blob; mutation probe; T21R5 freeze identity — every T21R5
freeze input, corpus file and suite hash matches; historical artifacts
byte-identical to canonical base; security pytest subset). One layer,
`T21R4 freeze identity`, **FAILs on a T21R4-INHERITED bookkeeping defect**,
not a T21R5 change: `evaluations/t21r4/holdout_manifest.json` records
freeze-input hashes for `runtime_freeze.json`, `holdout_uniqueness.json`
and `scripts/t21r4_freeze_evaluator.py` that do not match the versions
committed in T21R4's terminal commit `fbe034a` — the freeze-time contents
of those three files were never committed (T21R4's own battery ran before
that finalization), so the mismatch exists verbatim at canonical base
`6174ebd`. `git diff 6174ebd` proves nothing under those paths has changed
since the T21R4 merge. This is recorded here for the mechanical audit; the
T21R4 manifest itself is a frozen artifact and was not modified.

## 7. Decision

`T21R5_EVALUATOR_INVALID`, exactly as preregistered. KNOWLEDGE_RAG remains
EXPERIMENTAL (`registry_action: none`); no post-freeze repair was applied;
the T21R5 holdout is exposed and non-promotional. A future milestone must
build a NEW blind holdout with an evaluator whose every scoring path —
including the required-domains check — is exercised end-to-end on
synthetic fixture rows (never holdout data) BEFORE the evaluator freeze,
and should also address the recorded multihop bridge-over-abstention
diagnostic.

---

## FINAL OUTPUT

- **Status:** T21R5 closed — repairs proven on T21R4 replay (2535/2535,
  all 6 previously failed floors at target on development replay); blind
  holdout (3531 rows, 8 suites) constructed, audited (static gold PASS,
  uniqueness UNIQUE) and frozen; the single official exposure crashed in
  the frozen evaluator (post-freeze evaluator bug); decision recorded.
- **Decision: T21R5_EVALUATOR_INVALID** (KNOWLEDGE_RAG stays EXPERIMENTAL;
  holdout exposed and non-promotional; STOP — do not start T22).
- **SHAs:** branch `t21r5-knowledge-rag-reliability-closure`; repair commit
  `d8076beb1012f83723e1ccd91967cee2b5af2ab8`; canonical base
  `6174ebde0972a3f199b231a160bdb0875eb9bb7a`; holdout manifest
  `74d2ad4621418bf74ace57a6a402f24c25720b7bdeea1b7a781af6b48143e87f`;
  raw_results `e07d6ca0fb51a3de4516f79bc51891d73bbe31d153c89f032c4d80a98b68e184`;
  final branch SHA recorded in the terminal output of this session's push.
- **Floors:** NOT EVALUATED — the frozen evaluator crashed after 1288 of
  3531 rows; no floor value is citable. Partial non-promotional
  observations (officially exposed rows only): retrieval Recall@5 1.0 /
  Recall@10 1.0 / MRR 0.9949 / nDCG@5 0.9962 (488/488), singlehop 512/512,
  multihop 256/288 = 0.8889 (32 phrasing-dependent bridge
  over-abstentions); zero zero-tolerance counter hits on the exposed rows.
- **T21R4 replay (non-promotional, development evidence only):** 2535/2535
  correct; source diversity 1.0; citation resolvability/validity/precision
  /coverage/supported 1.0, fabricated 0; IE precision 1.0, over-abstentions
  0; injection containment 1.0; spoof rejection 1.0; conflict detection
  1.0, false resolution 0.0.
- **Next milestone (NOT started):** new blind holdout; evaluator with
  every scoring path pre-verified on synthetic rows before freeze; multihop
  bridge diagnostic investigation.