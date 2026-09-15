# T21R2 FINAL REPORT — strict blind holdout validation

**Decision: DEMOTE_KNOWLEDGE_RAG_TO_EXPERIMENTAL**
**Branch:** `t21r2-blind-holdout-validation` (NOT merged; SHA sent for
independent verification)
**Canonical base:** `8d23eabb17b3f66aa7ba3e4815c0ea088e53ae7b` (main, the
GitHub-verified T21R merge)
**Recorded:** 2026-09-15

T21R2 answers one question T21R could not: does KNOWLEDGE_RAG meet the
preregistered promotion bar on a holdout that was **provably never exposed
to the runtime**? T21R's holdout was runtime-exposed pre-freeze, so its
CONFIRM was not independent promotion evidence. T21R2 rebuilt the entire
validation under a blind-construction regime: the runtime, evaluator, and
validation contract were frozen and committed (`25e2a1b`) before any
holdout query, gold row, source, chunk set, or corpus existed; the
holdout was then generated mechanically, audited, frozen
(`HOLDOUT_FROZEN`, manifest sha256 `8e334d8f…c4d218b`), and evaluated
exactly once.

**The verdict is a fail.** The capability is real — retrieval is perfect,
grounded accuracy passes every floor, zero-tolerance counters are zero on
all 1964 rows — but the strict blind holdout falsifies the promotion bar:
6 preregistered floors failed, and every failure reconciles exactly to one
runtime defect the prior holdouts never exercised.

---

## 1. What T21R2 changed (and did not change)

Changed:
- `rag/gk_holdout_t21r2/` — new blind holdout corpus (854 world records,
  16 sources, 678 chunks), first committed only in the final T21R2 commit.
- `evaluations/t21r2/**` — freezes, contract, suites, audits, one-shot
  results, ledger, failure analysis, decision, battery, audits, report.
- `scripts/t21r2_*.py` — T21R2 harness scripts (new files).
- `tests/test_t21r2_blind_holdout_contract.py` — new firewall test file.
- `tests/test_historical_artifact_write_guard.py` — one preregistered
  delta: the T21R2 harness registration.
- `src/sciencemath/executive/skills.py` — the **recorded decision action
  only**: KNOWLEDGE_RAG availability `ACTIVE → EXPERIMENTAL`, applied
  after the evaluation. Nothing else in the file differs from the
  canonical base (verified byte-for-byte outside the KNOWLEDGE_RAG record).
- `tests/test_t21_knowledge_rag.py`, `tests/test_t20_orchestration_contract.py`
  — registry-count expectations updated to the recorded demotion (11
  ACTIVE / 1 EXPERIMENTAL).

NOT changed:
- `src/sciencemath/knowledge/**` — byte-identical to the canonical base
  (git diff empty; composites match the T21R2.0 freeze exactly).
- Every other frozen runtime group — recomputed composites match
  `runtime_freeze.json`.
- Executive Router — EXPERIMENTAL, untouched.
- `evaluations/t21/**`, `evaluations/t21r/**`, `rag/gk_corpus/`,
  `rag/gk_holdout_t21r/` — byte-identical to the canonical base.
- `evaluations/t15r/mutation_safety_probe.json` — git blob still
  `fba2437f78633884bd31965d78a4250bd1ca893c`.
- Top-level `full_junit.xml` — not drifted.

## 2. Blind construction (T21R2.0–T21R2.16)

1. **T21R2.0 runtime freeze** — composite SHA-256 over every frozen
   runtime group, KNOWLEDGE_RAG registry record (ACTIVE,
   registry `83ac989e…`), committed before any holdout data.
2. **T21R2.1 evaluator freeze** — `scripts/t21r2_run_eval.py` source hash
   and preregistered scoring semantics frozen before holdout construction.
3. **T21R2.2 validation contract** — floors, critical zeros, suite
   minimums (300/250/200/200/220/220/220/220, total ≥ 1830), composition
   minimums, uniqueness rule, one-shot rule.
4. **T21R2.4–.5 world + mechanical gold** — an entirely new fixture world
   (16 curated entities, 6 slow-geography entities, towns, nations,
   people, works, artworks, institutions, technologies), rendered into a
   corpus with fact metadata matching the T21/T21R schema exactly
   (verified on synthetic inputs by the firewall tests).
5. **T21R2.6 static pre-freeze QA** — `static_gold_audit.json`: PASS,
   0 failures, 1964 rows; coverage, entity-gate, temporal, conflict and
   schema mechanics transcribed bit-identically from the frozen runtime
   and verified against it on synthetic inputs only.
6. **T21R2.8–.14 eight suites** — retrieval `zb-`, singlehop `qc-`,
   multihop `hj-`, crossdomain `wn-`, citation `kf-`, conflict-abstention
   `vd-`, temporal `ps-`, adversarial `gq-`; every case id, query,
   phrase, and attack string unique within T21R2.
7. **T21R2.15 uniqueness audit** — verdict **UNIQUE**: 0 overlap against
   the UNION of T21 and T21R on case ids, entity identity, exact queries,
   chunk ids, source ids, gold answer values, exact source texts, and
   verbatim attack strings.
8. **T21R2.16 HOLDOUT_FROZEN** — manifest over all frozen inputs, corpus,
   and suites; written before any runtime exposure.

The firewall (`tests/test_t21r2_blind_holdout_contract.py`) mechanically
enforces: no runtime import or entrypoint name in any construction
script, freeze ordering and tamper detection, bit-identical transcription
of runtime mechanics on synthetic inputs, and manifest agreement. At the
final state: 26 passed.

## 3. The one-shot evaluation (T21R2.17–.18)

`official_runtime_exposures = 1` (`evaluation_run_ledger.json`). The
frozen evaluator ran the frozen runtime over all 1964 rows once:
retrieval 320, singlehop 294, multihop 208, crossdomain 216,
citation-claim 220, conflict-abstention 224, temporal 250, adversarial
232.

**Passed (as preregistered):**
- Retrieval: recall@5 = recall@10 = 1.0, MRR 0.9938, nDCG@5 0.9954.
- Grounded accuracy: overall 0.9599 (≥0.90), macro 0.9534 (≥0.88),
  singlehop 0.9592 (≥0.92), multihop 1.0 (≥0.85), crossdomain 0.9444
  (≥0.86); source diversity 0.9717.
- Citation suite in isolation: resolvability/validity/precision/coverage/
  supported-claim-rate all 1.0, fabricated 0.
- Temporal: explicit-current routing 1.0, stale-current 0, unnecessary
  web 0.0, historical as-of 1.0.
- Conflict detection 1.0, conflict false resolution 0.0.
- All 20 zero-tolerance counters zero on every row.
- All 8 suite minimums met.

**Failed (6 floors):**

| group | metric | value | floor |
|---|---|---|---|
| citations | citation_resolvability | 0.9548 | = 1.0 |
| citations | citation_validity | 0.9548 | = 1.0 |
| citations | citation_precision | 0.9548 | ≥ 0.99 |
| abstention_conflict | insufficient_evidence_precision | 0.7935 | ≥ 0.98 |
| security | prompt_injection_containment | 0.9569 | = 1.0 |
| security | citation_id_spoof_rejection | 0.92 | = 1.0 |

## 4. Failure analysis (T21R2.19) — one defect, exactly reconciled

Every aggregate metric reconciles to **exact integer row counts** computed
from the frozen gold suites: 66 incorrect rows = 64 over-abstentions on
gold-ANSWER rows + 2 citation-spoof misses. The 32 over-abstentions in the
conflict-abstention suite are exactly its 32 `near_duplicate_false_conflict`
rows (123/155 = 0.7935 abstention precision reconciles exactly).

**Mechanism (static evidence, no second runtime exposure):** the frozen
`detect_conflicts` metadata path (`src/sciencemath/knowledge/conflicts.py`)
flags a conflict whenever two evidence items share `fact_entity` /
`fact_attribute` but have **different text spans — it never compares the
`fact_value` its own docstring names as the comparison basis**. T21R2's
contract-mandated restated-fact composition (16 same-entity/same-attribute
groups with identical value, different wording, equal authority and
freshness) therefore returns `CONFLICTING_EVIDENCE` for answerable queries.
Neither T21 nor T21R ever contained a same-attribute restated pair, so
this path never compared two spans of one fact before; the strict blind
holdout is the first to exercise it. The singlehop asymmetry confirms the
mechanism: short restatements (emblem/genre/medium) rank into the evidence
set and trip the false conflict (4 wrong each in culture/arts/literature),
while the longer province restatements fall out of the evidence set under
BM25 length normalization (geography 0 wrong).

The 2 spoof misses: on 2 of 25 citation-spoof rows the runtime returned a
non-abstaining status (zero-tolerance counters stayed zero — nothing was
fabricated).

**Evaluator validity: VALID.** No evaluator bug was discovered; the
post-freeze evaluator bug policy was NOT triggered. The failed floors are
frozen-runtime behavior on valid gold. The DEMOTE verdict is robust: the
abstention-precision, containment, and spoof floors fail on suite-local
metrics alone, independent of any contract-wide denominator reading.

## 5. Decision (T21R2.20)

**DEMOTE_KNOWLEDGE_RAG_TO_EXPERIMENTAL** — applied to the registry
(`registry_sha256_after_demotion 1d04bd00…`); SCIENCE_RAG remains ACTIVE;
the Executive Router remains EXPERIMENTAL/untouched. Rationale: T21R's
CONFIRM rested on a runtime-exposed holdout; T21R2's independent holdout
does not reproduce the promotion bar, so the honest recorded state is
EXPERIMENTAL pending a runtime repair (value-aware conflict detection)
validated by a future T21R3 with another fresh blind holdout. The demotion
is the only `src/` delta and was applied strictly after the evaluation.

## 6. Protection and integrity (T21R2.21–.24)

- Protection battery **ALL_PASS**: frozen composites match (the recorded
  demotion is the only verified delta), registry matches the demotion
  record, T15R canonical blob unchanged, mutation probe rerun with
  milestone-local `--out evaluations/t21r2/mutation_safety_probe.json`,
  holdout freeze identity verified, historical artifacts byte-identical,
  security pytest subset green.
- Full pytest: **1655 tests, 0 failures, 0 errors, 2 skipped** →
  `evaluations/t21r2/full_junit.xml`; top-level `full_junit.xml` not
  drifted.
- `final_audit.json`: **ALL_CHECKS_PASS** (24 mechanical checks,
  including the honest-failure gates).
- `blindness_audit.json`: **BLINDNESS_MAINTAINED** — the freeze commit
  `25e2a1b` contains no holdout data; construction scripts are
  runtime-isolated (firewall-tested); exactly one runtime exposure;
  no post-freeze repair.

## 7. What a future milestone must do (T21R3 preregistration notes)

1. Fix `detect_conflicts` to compare `fact_value` (its docstring already
   specifies value disagreement as the conflict criterion) — a one-line
   semantic repair in the metadata path.
2. Re-verify spoof rejection: 2/25 misses need root-causing against the
   fake-reference pattern.
3. Build a NEW blind holdout (T21R3) under the same T21R2 regime; this
   holdout is now runtime-exposed and non-promotional.
4. Keep the near-duplicate restated-fact composition mandatory — it is
   the case class that caught the defect.

---

**STOP. Do not start T22.**