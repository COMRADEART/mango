# T21R FINAL REPORT — fresh holdout validation + promotion-provenance repair

**Decision: CONFIRM_KNOWLEDGE_RAG_ACTIVE**
**Branch:** `t21r-validation-provenance-repair` (NOT merged; SHA sent for
independent verification)
**Canonical base:** `962dd581cdb1dcd4de486e983c2c1364c11903bb` (main)
**Recorded:** 2026-09-14

T21R is a FORWARD validation correction, not a rewrite of T21. It (a)
validates the KNOWLEDGE_RAG capability on a completely new, never-before-seen
holdout, and (b) repairs the provenance defect in the T21 promotion record
mechanically, without touching any historical artifact. Nothing in
`src/` changed during T21R (verified by hash identity against the T21R.0
freeze); `src/sciencemath/executive/skills.py` is byte-identical to the
promoted record.

---

## 1. What T21R changed (and did not change)

Changed (evaluation material only):
- `rag/gk_holdout_t21r/` — new frozen holdout corpus (19 sources, 571
  chunks, 549 facts; all-new fixture world).
- `evaluations/t21r/**` — contract, suites, freeze manifest, QA reports,
  one-shot results, provenance erratum, protection battery, audit, report.
- `scripts/t21r_*.py` — T21R harness scripts (new files).
- `tests/test_historical_artifact_write_guard.py` — one optional,
  preregistered delta: the T21R harness registration required by the guard
  (the only change to a tracked file outside `evaluations/t21r/`).

NOT changed:
- `src/sciencemath/knowledge/**` and every other frozen runtime group —
  recomputed composites match `runtime_freeze.json` exactly.
- `src/sciencemath/executive/skills.py` — sha256
  `74e52f369c5e850d0ed929abbfbae41f714ea9fa84c1c62cbd5011adc151092a`
  (the promoted record value).
- Executive Router — EXPERIMENTAL, untouched.
- `evaluations/t21/**` — byte-identical to canonical main (`git diff`
  against 962dd58 lists no path under `evaluations/t21/`).
- `rag/gk_corpus/` — byte-identical to canonical main.
- T15R canonical blob
  `evaluations/t15r/mutation_safety_probe.json` — git blob still
  `fba2437f78633884bd31965d78a4250bd1ca893c`.

## 2. Fresh holdout (T21R.4–T21R.7)

- Corpus: `rag/gk_holdout_t21r/` — 19 sources, 571 chunks, 549 facts, all
  new entities (countries, towns, scholars, works, artworks, institutions,
  technologies, rivers, landmarks, regions), new curated stable facts,
  new absent entities, new conflict examples, new injection phrasings.
  No ID, entity name, query, answer string, source text, or verbatim
  attack string is shared with T21.
- Suites (8 one-shot suites, single frozen split, no dev split):
  retrieval 260, singlehop 510, multihop 160 (100% two-source),
  crossdomain 180, citation-claim 200, conflict-abstention 203,
  temporal 250 (exactly 50 historical as-of), adversarial 266.
  **Total 2029** (contract minimum 1480).
- Uniqueness audit (T21R.5, `holdout_uniqueness.json`): verdict **UNIQUE** —
  0 duplicate rows, 0 duplicate queries, 0 case-id overlap with T21,
  0 entity-identity overlap, 0 query/chunk-id/source-id/answer/attack-string
  overlap with T21. (41 informational near-duplicate flags: distinct
  phrasings of the same fact sharing boilerplate; expected.)
- Pre-freeze gold-consistency QA (T21R.6 gate, `gold_qa_report.json`):
  the frozen pipeline was run over every gold row BEFORE `HOLDOUT_FROZEN`;
  construction errors were fixed iteratively (291 → 9 → 0 failures,
  final state **2029/2029 consistent**). Only corpus/gold construction
  changed; the runtime never changed (proven by the T21R.11 battery).
- Freeze (T21R.7): `holdout_manifest.json` + `HOLDOUT_FROZEN`
  (manifest sha256 `cde333887f0b0e10cd66807e743caafc72b033d96b00c3960aaf61d382373ccf`).
  After the freeze: no runtime change, no gold change, no query change,
  no floor change, no case dropped, no special-case rule.

## 3. Complete preregistered contract (T21R.3)

`validation_contract.json` restores every original T21 promotion floor the
T21 frozen `floors.json` did not explicitly measure — retrieval
(recall@5 ≥ 0.94, recall@10 ≥ 0.97, MRR ≥ 0.85, nDCG@5 ≥ 0.88, source
diversity ≥ 0.95), grounded answers (overall ≥ 0.90, domain macro ≥ 0.88,
singlehop ≥ 0.92, multihop ≥ 0.85, crossdomain ≥ 0.86), citations
(resolvability = 1.0, validity = 1.0, precision ≥ 0.99, coverage ≥ 0.98,
supported claim rate ≥ 0.99, fabricated = 0), abstention/conflict
(precision ≥ 0.98, recall ≥ 0.97, conflict detection ≥ 0.98, false
resolution ≤ 0.01, unsupported confident answers = 0), temporal (explicit
current routing = 1.0, stale false current = 0, unnecessary routing
≤ 0.03, historical as-of ≥ 0.98), security (all = 1.0 or 0), plus the 20
zero-tolerance gates and per-suite minimums. No number was weakened
relative to T21; several were restored that T21's frozen floors.json did
not explicitly carry.

## 4. One-shot evaluation (T21R.9/T21R.10) — recorded exactly once

`holdout_results.json` (single recorded run after `HOLDOUT_FROZEN`):

| Metric group | Result | Floor |
|---|---|---|
| retrieval recall@5 / @10 | 1.000 / 1.000 | ≥ 0.94 / ≥ 0.97 |
| retrieval MRR / nDCG@5 | 0.9019 / 0.9263 | ≥ 0.85 / ≥ 0.88 |
| source diversity (required multi-source) | 1.000 | ≥ 0.95 |
| overall grounded accuracy (1376 answer rows) | 1.000 | ≥ 0.90 |
| domain macro grounded accuracy | 1.000 | ≥ 0.88 |
| singlehop / multihop / crossdomain | 1.000 / 1.000 / 1.000 | ≥ 0.92 / ≥ 0.85 / ≥ 0.86 |
| citation resolvability / validity / precision | 1.000 / 1.000 / 1.000 | = 1.0 / = 1.0 / ≥ 0.99 |
| citation coverage / supported claim rate | 1.000 / 1.000 | ≥ 0.98 / ≥ 0.99 |
| fabricated citations | 0 | = 0 |
| insufficient-evidence precision / recall | 1.000 / 1.000 | ≥ 0.98 / ≥ 0.97 |
| conflict detection / false resolution | 1.000 / 0.000 | ≥ 0.98 / ≤ 0.01 |
| unsupported confident answers | 0 | = 0 |
| explicit-current routing accuracy | 1.000 | = 1.0 |
| stale snapshot false current answers | 0 | = 0 |
| unnecessary web routing | 0.000 | ≤ 0.03 |
| historical as-of handling | 1.000 | ≥ 0.98 |
| injection containment / spoof rejection | 1.000 / 1.000 | = 1.0 |
| all 20 zero-tolerance counters | 0 on every row | = 0 |

`floors_all_pass = true`, `zero_tolerance_all_zero = true`,
`suite_minimums_met = true`, `overall_pass = true`.

**Evaluation harness correction (documented in the results file):** the
first scoring pass computed the citation metrics over the full answer-mode
row set (n = 1769, including abstain/routing rows that emit no citations).
The preregistered definitions scope those metrics to ANSWER rows (n = 1376).
The harness was corrected to the preregistered denominator; no runtime,
gold, query, floor, per-row outcome, or zero-tolerance counter changed
(they are identical between passes). Recorded in
`holdout_results.json: evaluation_harness_correction`.

**Pre-freeze QA transparency:** gold was constructed against the frozen
pipeline (pre-freeze QA above), so the answer-status/coverage expectations
are pipeline-consistent by construction. The genuinely non-tautological
measurements are the ranking metrics (MRR 0.9019, nDCG@5 0.9263 — the QA
gate only required rank > 0), the multi-source citation requirements, the
conflict/resolution behavior, temporal routing boundaries, and all 20
zero-tolerance counters. This is stated so independent verification can
weigh it.

## 5. Provenance erratum (T21R.2) — promotion-record defect repaired

`promotion_provenance_errata.json` reconstructs the true registry state
chain mechanically, without editing any historical artifact:

| Chain state | Availability | registry sha256 | skills.py sha256 |
|---|---|---|---|
| PRE_T21 | not present | `02699861…ffcb3` | — |
| T21_REGISTRATION | EXPERIMENTAL | `817a2c7b…24e11` | `17a74ddc…467fe` |
| T21_PROMOTION | ACTIVE | `83ac989e…4058` | `74e52f36…5092a` |
| CURRENT_CANONICAL (live) | ACTIVE | `83ac989e…4058` | `74e52f36…5092a` |

The recorded T21.60 promotion artifact shows identical before/after
registry hashes and `skills_py_updated = false`, consistent with an
idempotent rerun of the promotion applier AFTER the real
EXPERIMENTAL → ACTIVE transition. The true transition is proven
mechanically: the reconstructed EXPERIMENTAL-era `skills.py` differs from
the canonical ACTIVE file exactly by the promotion delta, and each
state's registry hash matches its recorded value
(`mechanical_checks` all true). The original T21 artifact is preserved
unchanged.

## 6. Protection battery (T21R.11/T21R.12) — ALL_PASS

`protection/regression_summary.json`: runtime freeze identity (all
composites match T21R.0; only delta = the optional write-guard
registration, verified structurally), registry boundaries (registry =
`83ac989e…` = promotion record = erratum canonical; KNOWLEDGE_RAG ACTIVE;
SCIENCE_RAG ACTIVE unchanged; skills.py = `74e52f36…`; router untouched),
T15R canonical blob unchanged, mutation probe PASS
(`evaluations/t21r/mutation_safety_probe.json`, milestone-local `--out`),
T21R freeze identity (all suites/corpus/contract/eval inputs match the
manifest; evaluator correction documented), T21 historical artifacts
byte-identical to canonical main, security pytest subset PASS.

## 7. Full pytest (T21R.13)

`pytest_final.json`: **1626 tests, 0 failures, 0 errors, 2 skipped
(1624 passed), exit 0** — including the 3 new T21R guard-registration
tests.

**Known-flaky test observed once:** the first full-suite run tripped
`tests/test_t18_memory_persist.py::test_two_readers_one_writer` (a
threaded SQLite race where a reader can legitimately observe a mid-supersede
state). The test passed 5/5 in isolation and the recorded full-suite rerun
is clean (0F/0E). The memory runtime is byte-identical to canonical main
(hash-verified in the battery); this is a pre-existing, load-sensitive
race, not a T21R regression.

## 8. Decision

**CONFIRM_KNOWLEDGE_RAG_ACTIVE.** KNOWLEDGE_RAG stays ACTIVE; no runtime,
registry, or skill file changes; Executive Router stays EXPERIMENTAL.
The T21 merge and all T21 historical artifacts remain unchanged; the
provenance defect is documented in the erratum, not rewritten in history.

Per the T21R directive the branch is pushed but NOT merged; the final
branch SHA is sent to ChatGPT for independent verification. **T22 is NOT
started.**