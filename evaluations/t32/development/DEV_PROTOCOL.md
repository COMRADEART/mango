# T32 Development Protocol (PREDECLARED — written before any candidate is trained or dev-evaluated)

Froze: this file + the dev-set files it names were created and hashed BEFORE
the first T32 candidate training run. The ablation candidates are described in
Phase 6 of the T32 directive; the dev protocol below is deliberately defined
up front so candidate selection cannot be shaped by results already seen.

Anything not written here does not influence selection.

## 1. Development sets

| slice | file | n | provenance | benchmark tag (frozen scorer path) |
|---|---|---|---|---|
| dev_gsm8k | training/t32/dev_sets/dev_gsm8k.jsonl | 200 | fresh GSM8K **train** records, seed 42 shuffled head | gsm8k (numeric) |
| dev_math | training/t32/dev_sets/dev_math.jsonl | 200 | fresh MATH train records, subject-stratified | math500 (boxed math) |
| dev_sciq | training/t32/dev_sets/dev_sciq.jsonl | 150 | raw SciQ train rows, fingerprint-gated vs T31 eval + T30 corpus | sciq (frozen MC option construction) |
| dev_arc_easy | training/t32/dev_sets/dev_arc_easy.jsonl | 120 | ARC-Easy **train** rows (eval_only license: measurement only, never training) | arc_easy |
| dev_arc_challenge | training/t32/dev_sets/dev_arc_challenge.jsonl | 80 | ARC-Challenge train rows (same terms) | arc_challenge |

Dev items reuse the frozen benchmark *tags* (gsm8k / math500 / ...) purely so
the frozen scorer paths and frozen prompt policy apply verbatim. The tags are
scoring-path selectors; every dev record's true provenance is on the item row.
No T31 evaluation item (or near-duplicate, Jaccard ≥ 0.90) may enter any dev
set or training mixture; gates are recorded in
training/t32/pools/contamination_report.json and per-mixture manifests.

Every dev question fingerprint is recorded in
training/t32/dev_sets/dev_excluded_fingerprints.json and is excluded from
every T32 training mixture.

## 2. Development evaluation protocol (identical for every arm)

* Model arms: the base model (anchor), the T30 adapter (reference), each T32
  candidate. Same base revision 70d244cc for all; adapters applied via the
  frozen T31 loader path.
* Prompts: frozen T31 prompt policy verbatim (same templates, same system
  prompt = none, enable_thinking=False, same chat template via the shared
  tokenizer).
* Decoding: greedy; budgets identical to the frozen per-benchmark budgets
  (gsm8k 512 / math500-tagged 1024 / MC 32).
* Scoring: the frozen scorer (`score_row`) over the same benchmark kinds.
* Dev eval runs BEFORE any candidate's final-locked evaluation and is the
  ONLY place iterative signals are read from.

## 3. Metrics recorded per arm

For each arm: `acc_gsm8k_dev`, `acc_math_dev`, `acc_mc_dev`
(weighted mean over the ARC slices), `acc_sciq_dev`, `math_dev_mean`
(= average of `acc_gsm8k_dev` and `acc_math_dev`), extraction-failure rate,
truncation rate per slice, and median/mean output tokens on the math slices
(style-restoration indicator).

## 4. Reference anchors (measured before candidates)

The base arm and the T30 adapter arm are dev-evaluated first. Every candidate
is judged by its DELTAS vs the T30 adapter anchor
(`Δmath_dev_mean`, `Δmc_dev`, `Δsciq_dev`) — never against the base directly,
because the mission is repair of the T30 regression, and the base anchors the
magnitude interpretation only.

## 5. Candidate eligibility gates (predeclared numeric thresholds)

A candidate is ELIGIBLE only if ALL of:

1. **Math restoration (material):** `math_dev_mean ≥ (T30 anchor) + 5.0 pp`.
   The two math dev slices track together in the report; the gate uses the
   mean, and the report must show both slices separately (a candidate that
   lifts one slice while collapsing the other must not hide it).
2. **MC preservation (no collapse):** `acc_mc_dev ≥ (T30 anchor) − 3.0 pp`.
3. **Science preservation (no collapse):** `acc_sciq_dev ≥ (T30 anchor) − 3.0 pp`.
4. **Contamination:** the candidate's training mixture passed the recorded
   direct + near fingerprint gates (0 direct, 0 near retained).
5. **Reproducibility:** training manifest with dataset sha256s, hyper-
   parameters, seed, and adapter output sha256 recorded in the candidate
   directory.

Threshold rationale: 3.0 pp ≈ the 95% CI half-width of the MC dev slices
(200 items ⇒ ±~6.9 pp at 95%; the anchor-comparison design shares items, so
paired deltas are much tighter — the 3.0 pp bound is the paired-noise
allowance, and the FINAL locked evaluation remains the arbiter of claim).
5.0 pp on math dev mean is the predeclared definition of "materially
improves" at dev scale.

## 6. Selection rule (predeclared)

Among eligible candidates: select the one with the HIGHEST `math_dev_mean`;
ties broken by (a) smaller |Δmc_dev|, then (b) smaller |Δsciq_dev|, then
(c) earlier experiment index in the directive's preferred order
(mixture < optimization < structure).

If NO candidate is eligible: the final locked evaluation still runs ONE
candidate — the one with the highest `math_dev_mean` overall (the mission's
diagnostic value stands regardless) — and the final decision reflects the
measured outcome (see the final decision policy below).

Selection never uses T31 evaluation scores (dev only, per directive).

## 7. Final locked evaluation policy (predeclared; mirrors the directive)

* ONE final locked evaluation: the frozen T31 model-only methodology, run
  exactly once against base + T30 + T32 with identical prompts, chat
  template, budgets, decoding, benchmark membership, and extractor.
* T32 arm rows are generated fresh under the identical frozen config; the
  base and T30 columns reuse the frozen T31 rows for the same items (same
  prompts/membership/scorer), stated in the report.
* Change nothing because of the result.
* **Final decision classes** (per directive):
  - `MANGO_T32_MATH_REMEDIATION_PASS` — GSM8K AND MATH-500 BOTH materially
    improve vs T30 (Δ ≥ +5.0 pp on BOTH, predeclared), and the preservation
    floor holds (see below).
  - `MANGO_T32_MATH_REMEDIATION_PARTIAL` — math restores materially on at
    least one final benchmark and not both, or preservation floor partially
    violated with math restoration standing (a real tradeoff, reported as
    one, never averaged away).
  - `MANGO_T32_MATH_REMEDIATION_NO_EFFECT` — no material math recovery.
  - `MANGO_T32_MATH_REMEDIATION_REGRESSION` — math or MC/science gets
    materially worse than T30.
* **Preservation floor:** ARC-Easy / ARC-Challenge / SciQ reported
  independently. Preservation holds iff, per ARC benchmark, T32 keeps ≥ 50%
  of T30's measured gain over the base (T32 − base ≥ 0.5 × (T30 − base)),
  and SciQ does not fall below the base by more than 1.0 pp. Report each
  benchmark's Δ vs T30 and Δ vs base; never pool across them.
* **Statistics:** paired 2×2 tables per benchmark (both-correct / T30-only /
  T32-only / neither), McNemar's exact test for paired deltas, effect size
  reported with the tables.

## 8. Candidate training recipes (registered before training; Phase 6)

Controlled variables are pinned at the T30 recipe (rank 32, alpha 64,
dropout 0.05, targets q,k,v,o,gate,up,down, lr 1e-4, cosine, seq 1024,
effective batch 16, seed 42, NF4 double-quant) unless a candidate's
definition changes exactly the named variables, and every change is recorded
in the candidate's manifest.

* **Candidate A `t32-A-math-restore` (Experiment 1: mixture only):** full
  frozen T30 train corpus replayed unchanged + fresh verified math additions
  (fresh GSM8K train +600, fresh MATH train +600 subject-stratified,
  +400 machine-generated and programmatically verified arithmetic drill
  records with explicit step lines). Optimization held ≈ constant vs T30
  (epochs 2 on the larger mixture ≈ T30's total optimization steps); every
  other variable identical to T30.
* **Candidate B `t32-B-task-balanced` (Experiment 1b: mixture, task-
  conditional styles):** A's mixture + the frozen mango-sft-v2 level1
  curriculum (850 CC0-1.0 self-authored records, re-gated), + a
  protocol-envelope math slice (150 authored records whose structured
  wrappers are validated for schema AND whose math final answers are
  programmatically verified; a record failing either check is dropped, per
  Phase 5), + a small verified abstain/refuse slice (30) and
  recovery/replan slice (20), + an MC-format slice (300 letter-choice science
  records built from SciQ train distractors, gated) so the terse
  bounded-answer mode the MC gain depends on is explicitly supervised
  alongside the restored derivational mode.
* **Candidate C `t32-C-conservative` (Experiment 2: optimization intensity):**
  the EXACT frozen T30 train corpus; only learning rate changed 1e-4 → 3e-5
  (epochs 3 unchanged). If the regression is displacement-by-optimization
  intensity, C recovers without touching the mixture at all.

Order of training: A, then B, then C (directive's preferred experiment
order; mixture experiments before optimization-structure experiments). Each
candidate's dev evaluation runs after its training completes; no candidate's
dev numbers influence another's training recipe.

## 9. No-peeking rule

During dev iteration, the frozen T31 final comparison scores (gsm8k/math500/
arc/sciq T31 test rows) are NOT re-read for tuning or selection. Selection
uses only `training/t32/dev_sets/`-derived numbers and the recorded anchors.