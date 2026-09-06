# Mango — T9 Correction Robustness and 4B Stabilization

## STATUS

PARTIAL

The system-level correction firewall clears its correction targets, but the T9 entry gate is not clean and the required full T4, T5R, and generalization reruns are not complete. No promotion is authorized.

## Starting Systems

A: Mango-v0.1 (Qwen3-1.7B + T3 adapter). The adapter metadata exists, but its weight file is absent from the current repository, so the identical T9 baseline could not run.

B: Qwen3-4B-Instruct-2507 raw, no Mango adapter.

## Correction Suite

Questions: 40  
TRUE_FAIL: 10  
FALSE_FAIL: 10  
PARTIAL_FAIL: 10  
AMBIGUOUS: 10  
Checksum: `dc77ccf845f539d4bf6df23964207d504962d75b56f02c981d0e15eb632a445b`

All four classes contain arithmetic, algebra, equations, calculus, units, physics, chemistry, biology, mixed math/science, and retrieval-backed science.

## Baseline Correction

### Mango-v0.1

True correction: NOT_RUN (production adapter weights absent)  
False-feedback preservation: NOT_RUN  
Overcorrection: NOT_RUN  
Net: NOT_RUN

### Qwen3-4B

True correction: 30.0% (95% Wilson CI 10.8%-60.3%)  
False-feedback preservation: 20.0% (95% Wilson CI 5.7%-51.0%)  
Overcorrection: 80.0%  
Net: -5

## Stabilized Qwen3-4B

True correction: 60.0% (95% Wilson CI 31.3%-83.2%)  
False-feedback preservation: 100.0% (95% Wilson CI 72.2%-100%)  
Overcorrection: 0.0%  
Blind agreement: 0.0%  
Net: +6

## Correction Firewall

Verified feedback: eligible for targeted repair  
Supported feedback: eligible for targeted repair and re-verification  
Unverified feedback: DEFER; answer preserved  
Contradicted feedback: CORRECTION_REJECTED; answer preserved

Rejected false corrections: 10/10  
Accepted valid corrections: 6/10 TRUE_FAIL

Citation-only errors use a citation repair scope and do not authorize factual claim regeneration.

## Tool Reliability

Tool invocations: 150  
Valid: 121  
Normalized: NOT_MEASURED_ON_FRESH_MODEL_RUN  
Failures: 29  
Failure categories: MALFORMED_ARGUMENT 12; WRONG_TOOL 6; UNSUPPORTED_EXPRESSION 5; PARSER_REJECTION 5; TOOL_INTERNAL_FAILURE 1; RESOURCE_CAP 0; OTHER 0.

28 failures are model invocation errors; one is a tool implementation gap. Pre-validation now checks tool existence, JSON/type/schema shape, and resource limits, with one deterministic JSON/wrapper normalization pass.

## T4 Regression

T8S baseline: 75.3%  
T9: NOT_RUN (full inference regression outstanding)  
Delta: NOT_AVAILABLE  
False PASS: 0 on the fresh deterministic verifier safety run (638 wrong probes)

## T5R Regression

T8S baseline: 58.6%  
T9: NOT_RUN (full inference regression outstanding)  
Delta: NOT_AVAILABLE  
Citation coverage: T8S 12/58; fresh result unavailable  
Fabricated: T8S 0  
Unsupported: T8S 0  
Invalid: T8S 0

## Generalization Protection

Fresh regression: NOT_RUN. T8S reference values remain overall 81.5%, math 79.3%, science 83.3%, compositional 75.0%, cross-domain 83.3%, counterfactual 66.7%, distractor 91.7%, uncertainty 76.2%, decomposition 37.5%.

## Extraction

Before: 129/131 (98.47%) on stored 4B model-only outputs  
After: 129/131 (98.47%) on the same outputs  
False extraction acceptance: 0 in targeted new tests; broad frozen negative benchmark outstanding

## Adapter

NOT_USED

## Final Comparison

| Dimension | Mango-v0.1 | Raw 4B | Stabilized 4B |
| --------- | ---------: | -----: | ------------: |
| Correction recall | NOT_RUN | 30.0% | 60.0% |
| False-feedback preservation | NOT_RUN | 20.0% | 100.0% |
| Overcorrection | NOT_RUN | 80.0% | 0.0% |
| Net correction | NOT_RUN | -5 | +6 |
| T4 | 45.3% T8S | 75.3% T8S | NOT_RUN |
| T5R | 55.2% T8S | 58.6% T8S | NOT_RUN |
| Generalization overall | 60.5% T8S | 81.5% T8S | NOT_RUN |
| Peak load VRAM | historical | 2590.6 MiB | 2590.6 MiB |

## System Promotion

KEEP_MANGO_V0_1

## Weight Promotion

NO

## Tests

Final: `714 passed, 1 failed in 14.35s`. The sole failure is the pre-existing frozen Level-1 replay checksum mismatch; therefore the required all-tests-pass gate is not met.

## Dominant Remaining Bottleneck

other — repository reproducibility: missing production adapter weights and a mismatched frozen corpus checksum prevent a clean entry gate and baseline A.

## Ready for Scientific Computing Milestone?

NO

## Next Milestone

Highest-value corrective action: restore the exact Mango-v0.1 T3 adapter weight artifact and reconcile the Level-1 replay checksum from authoritative provenance, then run the three outstanding frozen regressions before reconsidering system promotion.
