# Mango — T14 Executive Router & Skill Registry

## STATUS

PARTIAL

## Entry Gate

PASS

## Starting Architecture

Mango-4B-System-v1

## T14A — Necessity Router Repair

T13 blocked numeric rows: 45
Recovered: 45 (34 COMPUTE_REQUIRED, 11 COMPUTE_HELPFUL)
Still blocked: 0
Right→wrong: 9

## Necessity Benchmark

Total: 275
Final split: 192
Checksum: b96da421ae5cbc333d9a6a6637a14347b1c1ce3be78eb56a820925b964ee4a62

COMPUTE_REQUIRED precision: 1.0
COMPUTE_REQUIRED recall: 1.0
NO_COMPUTE precision: 0.7538
NO_COMPUTE recall: 1.0
Unnecessary compute: 0.0
Missed compute: 0.0

## SciComp Recheck

T11 numeric: 0.8478
T12 numeric: 0.7029
T13 numeric: 0.7464
T14 numeric: 0.7319

Adoption: 0.9863
Conceptual: 1.0
Adversarial: 0.96
Silent mutations: 0
Exceptions: 0

## SciComp Decision

KEEP_SCICOMP_EXPERIMENTAL

## T14B — Executive Router

Skills registered: 10
Active: 4 (GENERAL, MATH_T4, SCIENCE_RAG, NO_TOOL)
Experimental: 2 (SCICOMP, PLANNING)
Prepared only: 4 (CODE, WEB_RESEARCH, DOCUMENT, MEMORY)
Disabled: 0

## Executive Router Benchmark

Total: 304
Final split: 215
Primary accuracy: 0.8930
Top-2 accuracy: 0.8930
Tool recall: 0.7946
No-tool specificity: 1.0
Unavailable skill rejection: 1.0
Hallucinated tools: 0
Permission violations: 0
Paid compute violations: 0

## Multi-Skill Routing

Accuracy: 1.0
Ordering correctness: 1.0
Depth violations: 0

## Protection Battery

T4: PASS (false PASS = 0.0, tool 0.7467 / no-tool 0.5, delta 0.2467)
T5R: PASS (G 0.5862 / NORAG 0.569; fabricated 0, unsupported 0, invalid 0)
Capacity: PASS (overall 0.8571, 131/131)
Correction: PASS (true 0.80, preservation 1.0, collateral 0, blind 0)
Extraction: PASS (wrong-final acceptance 0.0)
SciComp: PASS (fidelity silent mutation 0, handled 0.890)
Security: PASS (35 tests, 0 failures, 0 errors)

## Performance

Router latency: <1 ms per decision (deterministic, no model)
Total latency: scicomp median 26,977 ms; conceptual 22,636 ms; fidelity 33,230 ms
Memory: 2.5 GiB CUDA allocated (4-bit NF4 double)
VRAM: 2.72 GB load, ~3.3 GB peak during eval

## Tests

1014 collected, 1014 passed, 0 failed, 0 errors (exit 0)

## Final Audit

Passed: 43
Failed: 4 (necessity_NO_COMPUTE_precision 0.7538 < 0.98; scicomp_numeric_floor 0.7319 < 0.848; exec_top2_accuracy 0.8930 < 0.92; exec_tool_recall 0.7946 < 0.90)

## Executive Router Decision

KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL

## Weight Promotion

NO

## Paid Compute

NOT_USED

## Main Finding

1. Did T14 repair compute-necessity routing enough to safely promote SciComp? **No.** The necessity taxonomy unblocked all 45 T13 NOT_NEEDED rows (34 COMPUTE_REQUIRED, 11 COMPUTE_HELPFUL), and the conceptual suite improved to necessity accuracy 1.0 with router precision/recall 1.0. But the frozen SciComp eval scored 0.7319 — below T13's 0.7464 and far below the 0.848 floor. Unblocking more rows exposed more engine/planner misses (compute success fell to 0.695, adoption rounding drift grew). The router repair is real but not sufficient for promotion.

2. Did T14 establish a reliable Executive Router for Mango's future generalist capabilities? **Partially.** The skill registry is honest (no faked execution, paid compute blocked, unknown skills rejected, depth capped at 3) and critical safety is clean: 0 hallucinated tools, 0 unauthorized paid routes, 0 unavailable-skill executions, 0 permission bypasses. But quality floors fail: primary accuracy 0.8930 (floor 0.85 pass), top-2 0.8930 (floor 0.92 fail), tool recall 0.7946 (floor 0.90 fail). The dominant failure is MISSED_TOOL (23) — the router is conservative and under-selects tools.

## Dominant Remaining Bottleneck

SciComp engine/planner reliability on newly unblocked compute-required rows (compute success 0.695, WRONG_ROUNDING 48) — not the necessity router.

## Ready for T15

NO

## Highest-Value Next Step

Repair SciComp planner provenance emission and result-rounding discipline (WRONG_ROUNDING 48, RESULT_MISREAD) before any further promotion recheck.

STOP.
