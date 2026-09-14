# T21 FINAL REPORT — Grounded General Knowledge RAG

_Recorded 2026-09-14 (branch `t21-general-knowledge-rag`)_

## 0. Promotion decision

**PROMOTE_KNOWLEDGE_RAG_SKILL**

| Item | Value |
| --- | --- |
| Decision | KNOWLEDGE_RAG promoted EXPERIMENTAL → ACTIVE (T21.60, applied idempotently) |
| Registry | 12 ACTIVE, 0 EXPERIMENTAL post-promotion (was 11 ACTIVE + 1 EXPERIMENTAL) |
| Executive Router | KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL — untouched, never claimed by T21 |
| SCIENCE_RAG | Unchanged (ACTIVE, `t5r_rag` hash pin verified) |
| Applied | yes — `evaluations/t21/promotion_decision.json` |

## 1. Scope and constraints

- Local-first general knowledge RAG over a **frozen, project-owned fixture corpus** (`rag/gk_corpus/`, manifest checksum `944d4504…`): 18 sources / 541 chunks / 519 fact rows, all deterministic fixture material (CC0-equivalent), no third-party text, no scraping, retrieval-only and never training material.
- Pipeline: BM25 lexical retrieval → coverage-primary bounded rerank → deterministic dedup → evidence pack with provenance → mechanical citation resolution → claim-evidence gate → answer/abstain statuses → freshness/temporal boundary model → conflict handling → prompt-injection firewall (`instruction_authority=0`) → query-injection defense.
- Dense retrieval deliberately not implemented (lexical only; RRF reserved for a future dense retriever — preregistered in `tuning_closed.json`).
- **No model memory backfill (T21.21)**: absent evidence → abstention, never a memorized answer. **No training** was used or needed: every defect found during dev tuning was repaired in deterministic runtime/phrasing logic.
- No paid compute; no network in the runtime path; Executive Router and all promoted runtimes untouched (hash identity verified).

## 2. Benchmark suites (T21.33–T21.39)

All seven preregistered suites were built with dev/final positional splits after deterministic category interleave, frozen before tuning, and never edited afterwards (T21.50).

| Suite | Dev | FINAL | Floor (total) |
| --- | --- | --- | --- |
| mango-general-knowledge-rag-v1 | 320/320 | 320/320 | ≥600 (640) |
| mango-general-retrieval-v1 | 240 rows | 240 rows | ≥400 (480) |
| mango-general-citation-v1 | 160/160 | 160/160 | ≥300 (320) |
| mango-general-abstention-v1 | 124/124 | 124/124 | ≥240 (248) |
| mango-general-temporal-boundary-v1 | 140 rows | 140 rows | ≥200 (280) |
| mango-general-multihop-v1 | 120/120 | 120/120 | ≥240 (240) |
| mango-general-adversarial-v1 | 136/136 | 137/137 | ≥240 (273) |

**2,483 FINAL rows; every row passes its frozen gold expectation.**

## 3. Preregistered floors (T21.43–T21.50) — `floors_comparison` all PASS

| Suite | Metric | Floor | Dev | FINAL |
| --- | --- | --- | --- | --- |
| knowledge-rag | answer_accuracy_overall | ≥0.90 | 1.0000 | 1.0000 |
| knowledge-rag | answer_accuracy_macro | ≥0.88 | 1.0000 | 1.0000 |
| multihop | answer_accuracy_overall | ≥0.90 | 1.0000 | 1.0000 |
| multihop | answer_accuracy_macro | ≥0.88 | 1.0000 | 1.0000 |
| retrieval | recall@5 | ≥0.94 | 1.0000 | 1.0000 |
| retrieval | recall@10 | ≥0.97 | 1.0000 | 1.0000 |
| retrieval | MRR | ≥0.85 | 0.9771 | 1.0000 |
| retrieval | nDCG@5 | ≥0.88 | 0.9831 | 1.0000 |
| citation | resolvability | =1.0 | 1.0000 | 1.0000 |
| citation | validity | =1.0 | 1.0000 | 1.0000 |
| citation | precision | ≥0.99 | 1.0000 | 1.0000 |
| abstention | precision | ≥0.98 | 1.0000 | 1.0000 |
| abstention | recall | ≥0.97 | 1.0000 | 1.0000 |
| temporal | explicit_current_routing_accuracy | =1.0 | 1.0000 | 1.0000 |
| temporal | stale_current_false_answers | =0 | 0 | 0 |
| temporal | unnecessary_web_rate | ≤0.03 | 0.0000 | 0.0000 |
| adversarial | containment_rate | =1.0 | 1.0000 | 1.0000 |
| adversarial | model_memory_backfill_events | =0 | 0 | 0 |

## 4. Zero-tolerance gate (T21.49)

**PASS** — all 20 counters exactly zero on every row of every suite, dev and final. Totals across 2,483 FINAL rows + 2,481 dev rows: `{}` (no counter ever fired).

## 5. Baselines (T21.40–T21.42)

- **Model-only baseline (T21.40)**: Qwen3-4B-Instruct-2507 (cached locally), retrieval disabled, deterministic recorded subset (36 rows stratified over knowledge/abstention/adversarial). Result: **0.0 answer accuracy on fixture-world facts** (the model invents values, e.g. "Fernvale was founded in 1883") and **12/12 model-memory backfill events on deliberately-absent facts** (e.g. answers Einstein 1905 / Mona Lisa 1503 from memory where the runtime must abstain). This is exactly the failure mode the T21 runtime forbids; the runtime records 0 backfill events.
- **BM25 baseline (T21.41)**: plain BM25 (no coverage rerank, no dedup, no gates) on mango-general-retrieval-v1 FINAL: recall@5 1.0, recall@10 1.0, MRR 0.9938, nDCG@5 0.9953. The runtime's coverage-primary rerank + dedup achieves MRR 1.0 / nDCG@5 1.0 on the same split.
- **SCIENCE_RAG non-regression (T21.42)**: `tests/test_rag_t5r.py` + registry/router suites — 82 tests, 0 failures; `t5r_rag` composite hash matches the T21.1 freeze pin. `science_rag_regression.json`: PASS.

## 6. Protection battery (T21.51/T21.52) and performance (T21.53)

- **Protection battery**: ALL_PASS (`protection/regression_summary.json`). All frozen component hashes match the T21.1 freeze; the two preregistered deltas (skill_registry T21.2 registration, historical_write_guard T21 harness registration) verify against their decision records; T15R canonical blob `fba2437…` unchanged; mutation-safety probe rerun with milestone-local `--out evaluations/t21/mutation_safety_probe.json` → PASS; suite freeze checksums match; security pytest subset green. "T21" registered in the HARNESS dict of `tests/test_historical_artifact_write_guard.py`.
- **Performance**: index build 0.007 s; retrieval p50 0.21 ms / **p95 0.37 ms** (floor ≤500 ms) over 480 queries; end-to-end p50 0.55 ms / p95 0.99 ms; RSS ~27 MB; GPU unused (deterministic lexical pipeline).

## 7. Real local smoke (T21.56)

8/8 query types pass end-to-end on the frozen corpus: simple fact, attribute fact, two-hop bridge, explicit-current (routes WEB_RESEARCH), historical as-of (snapshot ANSWER), absent entity (INSUFFICIENT_EVIDENCE), unresolved conflict (CONFLICTING_EVIDENCE), injection override (contained, grounded answer).

## 8. Failure analysis (T21.57)

FINAL split: **0 failures, 0 open defects.** Five dev-tuning defects were found and fixed **before** the FINAL freeze (documented with root causes in `failure_analysis.json`): BM25-length rerank bias → coverage-primary rerank; bridge phrasing gap → creator-cue scan; entity-gate first-word skip → all-token check; TCP phrasing verb mismatch → attribute-noun templates; and the historical as-of coverage-frame gap (found by the smoke) → content-only coverage measurement for as-of queries, with the full evaluation re-recorded on the unchanged frozen suites.

## 9. Focused tests and full suite (T21.61)

- Focused: `tests/test_t21_knowledge_rag.py` — 36 tests, 0 failures.
- Full canonical pytest (`scripts/run_pytest_summary.py`): **1625 tests, 0 failures, 0 errors, 2 skipped** (`pytest_final.json` / `full_junit.xml`).
- Registry contract pin updated with the promotion decision record (T20 contract test: 12 ACTIVE / 0 EXPERIMENTAL post-promotion).

## 10. Reproducibility

- Corpus manifest checksum `944d45043afd0d080f0e26d1f8000a25f905b6284840588d966c511264b076a0`; suite manifests carry `final_sha256`; `tuning_closed.json` pins all pipeline constants; no wall clock in the runtime; every artifact records its inputs' checksums.
- All artifacts under `evaluations/t21/`: `entry_freeze.json`, `frozen_components.json`, `registry_registration.json`, `corpus_manifest.json`, `tuning_closed.json`, `floors.json`, `suites/` (7), `eval_results.json`, `baselines.json`, `performance.json`, `smoke.json`, `mutation_safety_probe.json`, `protection/regression_summary.json`, `science_rag_regression.json`, `failure_analysis.json`, `final_audit.json`, `promotion_decision.json`.

## 11. Boundaries and non-goals

- Executive Router unchanged (EXPERIMENTAL); KNOWLEDGE_RAG is registered-but-unrouted by the router (routing integration is a future milestone's scope).
- No planning-role, orchestration-role, or paid-compute changes; KNOWLEDGE_RAG is LOCAL_FREE, offline, deterministic.
- STOP after T21: T22 is not started.