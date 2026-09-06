# T5 FINAL REPORT — Scientific Knowledge and Retrieval Layer (Mango)

Date: 2026-09-03 · Model: Mango-v0.1 (Qwen/Qwen3-1.7B + T3 LoRA adapter, never merged)
Suite: mango-rag-eval-v1 (frozen, 82 questions, sha256-verified at eval start)

**STATUS: PARTIAL**

The retrieval layer itself is complete and measured (T5.1–T5.18, T5.20–T5.26 all
pass), but the T5.19 condition **failed**: retrieval-augmented answering scored
**-3.45 pp below** no-RAG answering under matched generation settings. Per the
PASS GATE ("Do not force PASS if RAG lowers science quality") this is reported
as PARTIAL, not PASS.

---

## 1. What passed

### T5.0 entry gate
- PASS — `evaluations/t5_entry_gate.json` ("T5 UNBLOCKED"), written before any T5 code.

### T5.1 deny-by-default source registry
- 8 sources registered: `wikipedia_en` APPROVED; `openstax` REVIEW_REQUIRED
  (per-book license verification pending); `nasa_public`/`noaa_public` APPROVED;
  `ncbi_pubmed_abstracts`/`pmc_open_access` REVIEW_REQUIRED; `arxiv`
  RETRIEVAL_ONLY; `sciencedirect` BLOCKED.
- License gate enforced at ingestion (`registry.require("wikipedia_en",
  "local_index")`); malformed-registry cases covered in tests.

### T5.2 conservative scope
- Ingested: **Wikipedia (en) only** — curated seed lists + depth-1 link
  expansion capped at 40 pages/subject; never the full dump. 241 documents.
- Corpus never entered SFT weights (`approved_for_redistribution: false`
  in the manifest; T3/T4 training data untouched).
- OpenStax: investigated, blocked on per-book license verification
  (`data/science_sources/LICENSE_MANIFEST.md`).
- Tier-2 connectors (NASA/NOAA/PubMed): architected in the registry, NOT ingested.
- arXiv: RETRIEVAL_ONLY flag, no local index.

### T5.3/T5.4 taxonomy + schema
- Canonical science taxonomy (physics/chemistry/biology/astronomy/
  earth_science/computer_science/interdisciplinary); **mathematics kept
  separate** (non-science domain; retrieval for math only via explicit MIXED).
- Every chunk carries full provenance: document_id, source_id, title, section,
  url, revision, retrieved_at, license (CC BY-SA 4.0), attribution string,
  chunk_id, checksum. Fabricated metadata is structurally prevented
  (validation gate refuses incomplete provenance; 3847/3847 chunks validated).

### T5.5/T5.6 cleaning + chunking
- Science notation preserved through cleaning (H₂O, ΔE, 25 °C, superscripts);
  citation markers/boilerplate removed; hierarchy kept.
- Semantic section chunking: target ~650 tokens, cap 900, overlap 80; near-dup
  corpus-wide dedupe (jaccard ≥ 0.9) removed 176 duplicates; unique chunk_ids
  (sha1-disambiguated slugs).
- Final corpus: **3847 chunks / 241 documents**, domains: math 645, cs 620,
  physics 619, chemistry 602, biology 534, astronomy 436, earth_science 391,
  general 0. Corpus checksum recorded; loader refuses a stale/mismatched corpus.

### T5.7 embedding model chosen by measurement
- 3 candidates measured (probe-set recall/MRR/nDCG + latency + license):
  **e5-small-v2 wins** (recall@1 0.80, MRR 0.90 vs 0.767/0.883 for MiniLM;
  ~19 ms/query CPU). Revision pinned:
  `ffb93f3bd4047442299a41ebb6fa998a38507c52`.

### T5.8 vector store + manifests
- Abstracted `VectorStore` interface; **FAISS IndexFlatIP** production engine,
  brute-force numpy reference (tests assert equivalence + reload survival).
- `rag/index/index_manifest.json`: 3847 vectors, dim 384, checksum
  `1e2dd7d9…819`, corpus version + embedding revision pinned.

### T5.9 retrieval pipeline
- Threshold 0.30 (below → explicit INSUFFICIENT_EVIDENCE, never a guess),
  metadata filtering, token budget, BM25/rerank stage, contained embedder failures.

### T5.10 reranker measured, not assumed
- 3 arms over 20 probes (embedding-only / BM25 / cross-encoder):
  none 0.700/0.675/0.649 (recall@5/MRR/nDCG@5), bm25 0.750/0.583/0.602,
  cross-encoder 0.750/0.645/0.640.
- Per the pre-registered rule, **cross-encoder adopted** (composite 0.678 vs
  0.675) — a marginal, recall-driven gain at 13× rerank latency (306 ms vs
  23 ms), documented as a known cost.

### T5.11 router
- Routing arm: **87.5%** (14/16 expected-route questions); confusion shows
  only SCIENCE→GENERAL and MATH→GENERAL misses; 0 math↔science confusions.

### T5.18 retrieval metrics (separate from answer metrics)
- supporting_fact grading (corpus-refresh tolerant, support-score ≥ 0.45):
  Recall@1 0.786, Recall@3 0.857, **Recall@5 0.929**, MRR 0.827, nDCG@5 0.841,
  irrelevant-chunk rate 0.043.
- domain grading: Recall@5 1.0. Zero fabricated-chunk incidents in retrieval.

### T5.20 citation verification
- Mechanism verified end-to-end: 14 citations parsed in the rag arm;
  **1 fabricated + 11 unsupported correctly flagged**; a `source_attribution`
  answer with no valid citation is scored incorrect (citation-after-filter,
  wrong-source, irrelevant and unsupported paths all covered by tests).

### T5.21 adversarial retrieval
- Distractor (wrong-domain keyword-heavy) probes: 0 correct-by-luck answers;
  irrelevant-distractor chunks do not reach the context (threshold gate).

### T5.22 T4 math performance protected
- **0 retrieval_used_on_math_route violations** across all 66 rag-arm questions
  ("Solve 3x + 5 = 20" class never retrieves).
- Regression check (`evaluations/tool-suite/v1/t5_regression/`): frozen no-tool
  predictions re-verified with the current verifier **150/150 agreement**; the
  30 fresh mev1-* questions regenerated **bit-exact** (30/30 identical
  verdicts, 17/30 correct both). Frozen 70.67% == current 70.67%. Gate PASS;
  frozen artifacts untouched.

### T5.23 conditional prompt injection
- MATH → tool protocol only; SCIENCE → evidence/uncertainty; MIXED → evidence +
  tools; GENERAL → boxed scoring only. No cross-contamination (tests assert).

### T5.24 audit logging
- 256 audit records; **0 unredacted secrets** (authorization/token/key values
  redacted); every record carries selected_context_ids, rejected_context,
  retrieval/rerank scores, evidence_state, ts.

### T5.25 performance baseline (RTX 4050 6 GB)
- embed_query 16.4 ms; vector_search 0.45 ms; rerank_and_select 180.7 ms
  (cross-encoder); **retrieval end-to-end 232.5 ms median** (max 289 ms).
- Generation (256 new tokens): 6.42 s median; peak CUDA 2.0 GB.
- Corpus embed throughput 23.4 passages/s CPU (full re-embed 164 s).

### T5.26 full test suite
- Exact pytest summary: **`507 passed in 25.87s`** (430 pre-existing + 77 new;
  0 failed, 0 skipped). Measured, not estimated.

---

## 2. What failed — T5.19 (the gate that decides STATUS)

Matched settings (same suite, same greedy decode, same tool protocol for
MATH/MIXED; only retrieval removed in the no-RAG arm; 58 generation-eligible
questions — `retrieval_relevance` is retrieval-only by suite design):

| arm | accuracy |
|---|---|
| no-RAG | 44.83% |
| RAG   | 41.38% |
| **absolute delta** | **-3.45 pp** |

Per category (pp): factual_science_qa **+8.34**, insufficient_evidence
**+12.50**, mixed_math_science **-33.34**, multi_hop_science_qa **-33.33**,
quantitative_science 0.00, source_attribution 0.00, conflicting_evidence 0.00,
distractor_retrieval 0.00.

Uncertainty accuracy: 0.00 → 0.0833 with RAG (improvement, small).

### Honest diagnosis
1. **RAG helps exactly where it should** — corpus-grounded factual QA (+8.3 pp)
   and refusing to answer unanswerable probes (+12.5 pp).
2. **RAG hurts computation-heavy questions.** On MIXED/multi-hop items the
   evidence block crowds this 1.7B model: it answers from adjacent retrieved
   text instead of computing (e.g. "273 K" quoted from a chunk when the
   computed answer was required). This is a prompt-design problem for a small
   model, not a retrieval-quality problem (retrieval metrics are strong).
3. **The citation contract is beyond the model today**: only 14 citations were
   emitted across 58 questions; 11 unsupported, 1 fabricated. The 1.7B + math
   adapter does not reliably follow the citation format instruction.
4. Three intermediate runs are preserved (harness fixes were made between
   runs; all deltas were negative): run1 -1.72 pp (citation instruction
   missing, conflict detector over-firing), run2 -3.03 pp (over-strict
   verifier auto-rejected all citations via empty support strings), final
   -3.45 pp. All intermediate prediction files are archived.

### Harness fixes made during this phase (with tests)
- Conflict detection tightened to negation-bound-term matching (function-word
  filtering) — CONFLICTING_EVIDENCE misfires 30/66 → 15/66; glass/units
  fixtures still detected.
- SCIENCE evidence prompt now explicitly requires `[chunk_id]` citations.
- `source_attribution` scoring now fails when no citations parse (previously
  silently skipped verification).
- `parse_inline_citations` now extracts the support sentence (empty support
  strings had auto-rejected every citation).
- `retrieval_relevance` excluded from generation scoring (retrieval-only per
  the frozen suite design).
- Ingestion: domain fallback (general 1628 → 0), unique chunk_ids, newline
  collapse for Wikipedia formula fragments, punctuation-aware dedupe.

---

## 3. Exact pytest summary

```
507 passed in 25.87s
```

(430 pre-existing + 77 new; 0 failed, 0 skipped, 25 files.)

---

## 4. PASS GATE evaluation (17 conditions)

16/17 met. **T5.19 (RAG must not lower science quality) FAILED** — RAG scored
-3.45 pp below no-RAG under matched settings. Per instruction, PASS was not
forced.

**Ready for T6? NO** — one blocking condition remains: retrieval-augmented
answering must at least match no-RAG accuracy. The retrieval machinery is done
and measured; the remaining work is answering-prompt design for a 1.7B model
(evidence placement on MIXED route, citation-format simplification or
post-hoc citation binding) — a T5 refinement, not new scope.

Next Milestone: T6 — Balanced curriculum and capability expansion.
STOP. Do not start T6.