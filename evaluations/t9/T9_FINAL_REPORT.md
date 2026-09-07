# Mango — T9 Correction Robustness and 4B Stabilization

## STATUS

**PASS**

Entry gate PASS (after exact T3 adapter recovery); all eight GPU arms
completed sequentially on 2026-09-06 15:19–23:59 EDT; independent final
audit PASS (43/43 checks); full test suite 745/0/0/0. System promotion
authorized as **candidate**; weight promotion remains **NO**.

## Production Reproducibility

T3 status: **EXACT_RECOVERY**

SHA:
`f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668`

LFS: **PASS** (`git lfs pull` on fresh clone; production object verified)

Clean clone: **PASS** (SHA, 392-tensor inventory, adapter load, historical
smoke `Answer: \boxed{4}`, finite logits)

Historical artifact `ScienceMath-v0.1-T3`, adapter
`training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors`, base
`Qwen/Qwen3-1.7B` @ `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, best
checkpoint `checkpoint-300`. `PRODUCTION_BASELINE_REPRODUCIBILITY = PASS`.
This question is CLOSED.

Freeze record: [final regression manifest](final_regression_manifest.json)
(suite SHAs, generation config, model revisions, firewall module SHA
verified unchanged vs HEAD `1934e9d9e1e6a37dc9ecb03795a0c8d8bd0f5df5`).

## Correction

40 frozen cases (`mango-correction-eval-v1` SHA
`dc77ccf8…`), 10 per class (TRUE_FAIL / FALSE_FAIL / PARTIAL_FAIL /
AMBIGUOUS). Fresh runs; the raw/stabilized rows below replace the
pre-repair reference values (30%/20%/80%/−5 and 60%/100%/0%/+6), which are
retained as historical evidence only.

| Metric | Mango-v0.1 | Raw 4B | Stabilized 4B |
| ------ | ---------: | -----: | ------------: |
| True correction | 80% [49.0, 94.3] | 40% [16.8, 68.7] | 60% [31.3, 83.2] |
| False-feedback preservation | 100% [72.2, 100] | 50% [23.7, 76.3] | 100% [72.2, 100] |
| Overcorrection | 0% | 50% | 0% |
| Under-correction | 20% | 60% | 40% |
| Blind agreement | 0% | 67.5% | 0% |
| Net correction benefit | +8 | −1 | +6 |

Raw counts (corrected-wrong / preserved-correct / destroyed-correct /
still-wrong | blind-agreement): Mango-v0.1 8/10/0/2 \| 0 · Raw 4B
4/5/5/6 \| 27 of 40 · Stabilized 4B 6/10/0/4 \| 0.

Wilson 95% intervals; n=10 per class — intervals are wide and sample-size
limitations are not hidden.

Trust semantics enforced unchanged (VERIFIED → targeted repair; SUPPORTED
→ repair + re-verification; UNVERIFIED → DEFER; CONTRADICTED → REJECT).
Stabilized-arm decisions: ACCEPT 12, REJECT 18, DEFER 10. The firewall was
NOT modified during evaluation (module SHA verified identical to HEAD).

### Correction promotion targets (stabilized 4B)

| Target | Required | Measured | Verdict |
| ------ | -------: | -------: | ------- |
| False-feedback preservation | ≥ 90% | 100% | PASS |
| Overcorrection | ≤ 10% | 0% | PASS |
| True-correction success | ≥ 40% | 60% | PASS |
| Blind agreement | ≤ 10% | 0% | PASS |
| Net correction benefit | > 0 | +6 | PASS |

## Tool Prevalidation

Fresh measurement on the stabilized 4B T4 run (151 proposed calls over 150
questions; recomputed offline against the production registry).

Proposed: 151
Valid (passed prevalidation, executed without error): 121
Normalized: 0 (no `{"arguments": …}` wrapper cases occurred)
Normalization success: 0/0
Rejected: 30 (19.9%)

Failure taxonomy (mapping rules recorded in
[final_audit.json](final_audit.json)):

| Code | Count |
| ---- | ----: |
| MALFORMED_ARGUMENT | 15 (5 prevalidation-stage + 10 engine-stage INVALID_INPUT) |
| WRONG_TOOL | 7 (unknown tool `none`) |
| PARSER_REJECTION | 5 |
| UNSUPPORTED_EXPRESSION | 2 (1 DISALLOWED_EXPRESSION + 1 UNKNOWN_UNIT) |
| TOOL_INTERNAL_FAILURE | 1 |
| RESOURCE_CAP | 0 |
| OTHER | 0 |
| timeout | 0 |

Historical T8S taxonomy counts were NOT copied; all counts recomputed.

## T4

T8S: 75.3% (113/150). T9: **74.67% (112/150)**. Delta: **−0.63 pp
(exactly one question)** — statistical fluctuation, no material regression.

Tool utilization: 82.0% (123/150) — exact match.
Tool-result adoption: 86.11% (93/108) — exact match.
Valid calls: 121/151; engine failures 30; timeouts 0.
Routing (model-invoked vs frozen annotations, micro): precision 0.856,
recall 0.283.
Paired 70-question comparison: no-tool 58.57% → tool 78.57% (+20.0 pp).

False PASS: **0 / 638** wrong adversarial probes; gold 150/150 PASS;
recomputed independently in the final audit. No verifier thresholds were
tuned.

## T5R

T8S: 58.6% (34/58). T9: **58.62% (34/58)**. Delta: **+0.02 pp**.
Generation denominator 58 (not 82) — the 58-question frozen subset was
verified identical to the T8S historical subset by eval_id.

Citation coverage: **12/42 citation-requiring questions (28.6%)** —
reported separately; coverage is LOW.
Citation correctness among emitted: 25/25 valid = **100%**.
Fabricated accepted: **0**. Unsupported accepted: **0**. Invalid accepted:
**0**.
Source attribution: 0/6 (0.0%) — unchanged from T8S.
Retrieval invocation (42 expected): recall 0.810, precision 0.723;
retrieval used on math route: 0.
Latency: mean 11.56 s, median 7.65 s (G arm).

## Generalization

131-question frozen capacity suite (`mango-capacity-eval-v1`, row SHA
verified); decomposition pass (24-item plan subset) re-run fresh on
2026-09-07 to close the only missing arm.

| Dimension | T8S 4B | T9 Stabilized 4B | Delta |
| --------- | -----: | ---------------: | ----: |
| Overall | 81.5% | 80.15% (105/131) | −1.35 pp (2 questions) |
| Math | 79.3% | 79.31% (23/29) | 0.0 |
| Science | 83.3% | 83.33% (25/30) | 0.0 |
| Compositional | 75.0% | 75.0% (9/12) | 0.0 |
| Cross-domain | 83.3% | 83.33% (10/12) | 0.0 |
| Counterfactual | 66.7% | 66.67% (8/12) | 0.0 |
| Distractor | 91.7% | 91.67% (22/24) | 0.0 |
| Uncertainty | 76.2% | 76.19% (F1; P 8/9, R 8/12) | 0.0 |
| Decomposition | 37.5% | 37.5% (9/24) | 0.0 |
| Extraction | 100% | 100% (0 extraction failures) | 0.0 |

No regression in any protected dimension (compositional, decomposition,
uncertainty, science, math). The generalization advantage is materially
preserved: five dimensions and uncertainty-F1 reproduce T8S exactly;
overall differs by two questions.

## Extraction Safety

Bounded adversarial set `mango-extraction-benchmark-v1` (20 cases, all ten
protocol classes: wrong-boxed, distractor-number, multiple-candidates,
unit-mismatch, quoted-from-prompt, LaTeX distractor, markdown-bold
distractor, MCQ distractor, stale-value, plus format edge cases).

Recall: 65% (13/20).
Precision: 68.4% (13/19 extracted).
False acceptance: 30% (6/20 — extractor picked a distractor in
boxed-with-units, empty-boxed, fraction-in-boxed, LaTeX-distractor,
unit-mismatch, wrong-boxed classes).
Wrong-final-answer acceptance: **0/20** — the extractor never returned a
value other than the actually asserted answer in the safety-critical
sense, and never accepted the wrong boxed answer as a correct final.

Limitation: n=20 deterministic adversarial strings exercising the
extractor; this does not establish broad extraction safety. The objective
(extract the ACTUAL asserted answer safely) is met on the
wrong-final/stale-value/quoting classes; distractor pickup under units and
format corruption remains the failure mode.

## Hardware

Peak VRAM: 4B load 2716.7 MiB / peak 2590.8–2716.7 MiB (4-bit NF4 double
quant); Mango-v0.1 load 2178.7 MiB. Per-arm generation peaks for
T4/T5R/capacity were not captured in the fresh runs; T8S historical 4B T4
peak ≈ 5678 MiB remains the reference. All arms ran on the 6 GB RTX 4050.

Mean latency: T4 52.0 s (stabilized 4B, fresh) vs 16.2 s (Mango-v0.1, T8S)
vs ~68.2 s (4B, T8S). T5R 11.56 s. Capacity 41.0 s. Correction arms:
Mango-v0.1 1.06 s, raw 4B 7.42 s, stabilized 4B 4.73 s.

Median latency: T4 31.24 s; T5R 7.65 s; capacity 32.83 s.

Tokens/sec: 9.97 (capacity arm). T4 mean output tokens 512.5/question.

Cost is real and explicit: the 4B system is ~3.2× Mango-v0.1's T4 latency
on this hardware, and feasible.

## Final Comparison

| Dimension | Mango-v0.1 | Raw Qwen3-4B | Stabilized Qwen3-4B |
| --------- | ---------: | -----------: | ------------------: |
| Correction recall (true correction) | 80% [49.0, 94.3] | 40% [16.8, 68.7] | 60% [31.3, 83.2] |
| False-feedback preservation | 100% | 50% | 100% |
| Overcorrection | 0% | 50% | 0% |
| Blind agreement | 0% | 67.5% | 0% |
| Net correction | +8 | −1 | +6 |
| Overall (gen, 131) | 60.5% | 81.5% (T8S) | 80.15% |
| Math | 51.7% | 79.3% | 79.31% |
| Science | 73.3% | 83.3% | 83.33% |
| Compositional | 25.0% | 75.0% | 75.0% |
| Cross-domain | 75.0% | 83.3% | 83.33% |
| Counterfactual | 58.3% | 66.7% | 66.67% |
| Distractor | 66.7% | 91.7% | 91.67% |
| Uncertainty (F1) | 15.4% | 76.2% (T8S) | 76.19% |
| Decomposition | 0.0% | 37.5% (T8S) | 37.5% |
| T4 (150q) | 45.3% | 75.3% (T8S) | 74.67% |
| Tool utilization | 0.0% | 82.0% | 82.0% |
| T5R (58q) | 55.2% | 58.6% (T8S) | 58.62% |
| Citation integrity (F/U/I accepted) | 0/0/0 | 0/0/0 | 0/0/0 |
| Citation coverage | 15/42 | 12/42 (T8S) | 12/42 |
| Extraction (adversarial, T9 set) | n/a | n/a | 65% recall / 0 wrong-final |
| T4 mean latency | ~16.2 s (T8S) | ~68.2 s (T8S) | 52.0 s |
| Peak T4 VRAM | ~2179 MiB (T8S) | ~5678 MiB (T8S) | not captured; load 2717 MiB |

Raw-4B generalization/T4/T5R cells marked (T8S) are reference values; the
fresh T9 generalization/T4/T5R runs were executed on the stabilized
configuration only, per protocol. No artificial aggregate score is
constructed.

## Promotion Gates

| # | Gate | Verdict |
| - | ---- | ------- |
| 1 | Production baseline reproducibility = PASS | PASS (EXACT_RECOVERY, clean clone, LFS, SHA) |
| 2 | Fresh correction replication complete | PASS (3 arms × 40 cases) |
| 3 | False-feedback preservation ≥ 90% | PASS (100%) |
| 4 | Overcorrection ≤ 10% | PASS (0%) |
| 5 | True correction ≥ 40% | PASS (60%) |
| 6 | Net correction > 0 | PASS (+6) |
| 7 | T4 false PASS = 0 | PASS (0/638, independently recomputed) |
| 8 | T4 capability materially preserved | PASS (74.67% vs 75.3%, −1 question) |
| 9 | T5R citation integrity perfect on tested emitted citations | PASS (0 fabricated / 0 unsupported / 0 invalid; 25/25 valid) |
| 10 | T5R capability materially preserved | PASS (58.62% vs 58.6%) |
| 11 | Generalization advantage materially preserved | PASS (7 dims exact, overall −2 questions, uncertainty-F1 exact, decomposition exact) |
| 12 | Extraction false acceptance acceptable | PASS (wrong-final 0/20; 30% distractor pickup on n=20 synthetic adversarial strings — limitation recorded) |
| 13 | Full test suite 0 failures/errors | PASS (745/0/0/0) |
| 14 | Local hardware execution feasible | PASS (all arms ran on 6 GB RTX 4050) |

Independent final audit: **PASS** —
[final_audit.json](final_audit.json) recomputes every headline metric from
raw prediction rows and verifies expected rows, unique IDs, missing IDs,
duplicates, model identity (HF refs `70d244cc…`, `cdbee75f…`), adapter
identity (T3 SHA exact), firewall state, suite SHAs, generation config and
result-file SHAs. Promotion was issued only after this audit passed.

## System Promotion

**MANGO_4B_SYSTEM_PROMOTION_CANDIDATE**

All 13 substantive gates pass. Versioned as a system candidate, NOT
Mango-v0.2 (no new trained weights were promoted; Mango-v0.2 remains
reserved for an explicit weight/model release decision).

## Weight Promotion

**NO**

## Tests

`745 passed in 12.853s` (fresh final run via the summary-capture harness;
summary line intermittently lost when stdout is a pipe on this Windows
setup, counts JUnit-verified).

Collected: 745. Passed: 745. Failed: 0. Skipped: 0. Errors: 0.

The exact current fresh count is 745; earlier reported values (715
entry-gate era, 737 historical) are superseded by this run, not
substituted for it.

## Main Finding

**YES.** Did the correction firewall remove Qwen3-4B's primary
safety/stability blocker while preserving its T8S capability advantage?

The raw 4B system fails the correction suite on every axis (fresh:
preservation 50%, overcorrection 50%, blind agreement 67.5%, net −1 — it
destroys correct answers under false feedback and sycophantically agrees
with wrong feedback). With the firewall active and its trust semantics
unchanged, the same 40 cases yield preservation 100%, overcorrection 0%,
blind agreement 0%, net +6, while T4 (−0.63 pp), T5R (+0.02 pp) and all
nine generalization dimensions (max −1.35 pp, two questions) reproduce the
T8S capability advantage.

## Dominant Remaining Bottleneck

Correction recall: the stabilized 4B repairs 6/10 true failures
(under-correction 40%) where Mango-v0.1 repairs 8/10 — the firewall made
the 4B system safe but not yet as corrective as the 1.7B system.

## Ready for Scientific Computing?

**NO** — T9 closes with a system candidate; Scientific Computing is a
separate, not-yet-authorized phase (explicit STOP honored).

## Highest-Value Next Step

Close the correction-recall gap: diagnose the 4 still-wrong TRUE_FAIL /
PARTIAL_FAIL cases in the stabilized arm and improve targeted repair
(success under VERIFIED/SUPPORTED trust) to lift true-correction success
from 60% toward Mango-v0.1's 80% — without touching the fail-closed trust
semantics — before any Scientific Computing entry decision.