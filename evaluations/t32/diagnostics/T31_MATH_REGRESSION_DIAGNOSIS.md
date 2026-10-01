# T32 Phase 2 — T31 math-regression diagnosis

Artifact: `T32_MATH_REGRESSION_DIAGNOSIS` (this file + machine-readable
`T32_PHASE2_HYPOTHESES.json`). Everything below is derived from FROZEN T31
evidence (`evaluations/t31/…`, read-only) plus T32-specific diagnostic
machinery; nothing here rewrote T31 state.

## 1. The measured regression (frozen T31 table, model-only arm)

| benchmark | base | T30 adapter | delta |
|---|---|---|---|
| gsm8k | 81.05% | 58.38% | **−22.67 pp** |
| math500 | 59.80% | 30.40% | **−29.40 pp** |
| arc_easy | 79.46% | 87.67% | +8.21 pp |
| arc_challenge | 61.60% | 77.30% | +15.70 pp |
| sciq | 84.90% | 86.90% | +2.00 pp |

The regression is math-specific and large; the MC/science gains are real.

## 2. Where the T30 adapter's math capability went (Phase 1 taxonomy)

Adapter-wrong / base-right math rows (n=549 gsm8k, 348 math500), labels by
rule-based evidence over generations, ambiguous items left unlabelled:

| label | gsm8k | math500 |
|---|---|---|
| derivation present but wrong (no arithmetic slip) | 351 (63.9%) | 230 (66.1%) |
| arithmetic error (first wrong step re-verified) | 145 (26.4%) | 12 (3.4%) |
| underderived final answer | 33 | 27 |
| verbosity/truncation at frozen budget | 20 (3.6%) | 77 (22.1%) |
| no derivation emitted | — | 2 |

Read: the dominant failure is a derivation chain that exists but is broken
— not blank answers, not truncation on gsm8k, not format collapse. Both
arms share a hard core (185/182 rows wrong on both; same-wrong-value only
44/15), so a backbone-level error mass is NOT adapter-specific — adapter
has simply LOST the bulk of the base's margin on top of it.

## 3. The adapter's MC gain mechanism (why science went UP)

Adapter-fixed rows (base-failing, n=578 across MC) are dominated by
TRUNCATION: base truncated at the 32-token MC budget on 255/281 arc_easy,
234/234 arc_challenge, 49/63 sciq failures; the adapter answers within
budget (medians 30/32/24 tokens, near-zero truncation). The T30 gain on MC
is therefore primarily a verbosity-policy effect inside a 32-token budget —
consistent with the T30 corpus's bounded, short targets (sciq 40 words
median, math 49–72; targets over 1600 chars were REJECTED at build).

## 4. The T30 mixture mechanism (supervision shape, Phase 4 discovery)

Frozen T30 corpus (n=2910 train): sciq 1152 (39.6%), gsm8k 806,
math-competition 779, synthetic 173. REASONING_BUDGETS (math 1600 /
science 700 / general 400 chars) REJECT over-length targets at build, so
the corpus contains ONLY terse math derivations (median 49 gsm8k / 72 math
words; the base model writes far longer chains — its math500 failures
median 1024 tokens). Supervision never showed the model a long, explicit,
verified derivation; the adapter moved its style toward the corpus mode,
and the measured failure modes (Section 2) are exactly that underderivation
signature. The mango-sft-v2-L1 lineage confirms the deployed adapter NEVER
saw protocol-shaped supervision (adapter was trained from sciencemath-sft-v1
only; no training_manifest protocol records).

## 5. Hypotheses (directive H1–H6), verdicts and evidence

H1 — protocol overfitting: NOT the driver. MANGO_MARKERS scan over both
arms' rows: 626 rows with protocol vocabulary — vocabulary alone does not
separate arms from correctness, and the deployed adapter never trained on
protocol data. Verdict: no.

H2 — capability damage vs style-policy failure: **PARTIAL — style-
suppression confirmed, full destruction refuted.** derive_explicit
recovers 24/80 (30.0%) of adapter-wrong items (gsm8k 20/60, math500
4/20), all 24 with natural stop. The un-recovered ~70% overlaps the
both-arms-wrong core plus derivation-present-but-wrong rows — recorded,
not averaged away.

H3 — data imbalance: CONTRIBUTES. T30 math share 54% of records but with a
1600-char rejection cap; MC/short-form sciq dominated target density;
drills+fresh-mixture candidates directly rebalance (Candidate A/B).

H4 — sequence-length/truncation: **REFUTED as the driver.** Probe
budget_1024 EXACTLY equals control_frozen (0/80 both, truncation 2/60 gsm8k
and 4/20 math500; generations greedy-identical, median 105.5 tokens on
both conditions): more budget with the identical prompt recovers nothing.

H5 — final-answer supervision weakness: **SUPPORTED.** The explicit
derivation instruction flips 24/80 adapter-failed items to correct (all
natural stops, derived-mode median 136.5 tokens vs 105.5); the corpus never
modeled long chains (Section 4), so derivation was never rewarded.

H6 — multiple-choice specialization: CONTRIBUTES through the 32-token
budget interaction (Section 3) and through MC-style bounded targets being
the adapter's dominant learned surface form; addressed by Candidate B's
explicit MC-format slice which supervises that mode ALONGSIDE long
derivations, rather than removing it.

## 6. Phase 2 probe (deterministic GPU probe over adapter-wrong/base-right math)

80 items (gsm8k 60 / math500 20 — the adapter-wrong & base-right head of the
frozen scored rows, item_id sort), three conditions, batch 8, greedy,
shared tokenizer/chat template:

| condition | gsm8k | math500 | combined |
|---|---|---|---|
| control_frozen (512/1024 budget) | 0/60 | 0/20 | **0.0%** |
| budget_1024 (1024-budget, same prompt) | 0/60 | 0/20 | **0.0%** |
| derive_explicit (+ step-by-step instruction, 1024) | 20/60 (33.3%) | 4/20 (20.0%) | **30.0%** |

Generation stats: control and budget_1024 are greedy-identical (both
median 105.5 output tokens, truncation ≤ 2/60 gsm8k and 4/20 math500); in
derive_explicit every one of the 24 recovered items ends with
finish_reason=stop, and the derived-mode median rises only to 136.5 tokens.

Verdicts (full machine-readable record: `T32_PHASE2_HYPOTHESES.json`):
- **H2/H5 as above** — style-policy failure, addressable by mixture, NOT
  budget, NOT protocol overfitting, NOT full capability destruction.

## 7. What the repair targets (links to the mixtures)

From Sections 2–5 the causal chain is: (a) short-only derivation supervision
+ (b) bounded-answer style dominance produced (c) broken chains on hard math
+ (d) a 32-token-budget MC bonus. Candidate A adds long-form, VERIFIED math
supervision (fresh gsm8k/MATH + machine-verified drills) on replayed T30;
Candidate B adds the same PLUS protocol/abstain/MC-mode slices so both modes
are explicitly supervised (Phase 5 verified math content for every
structured record); Candidate C tests the pure optimization-intensity
hypothesis unchanged corpus.