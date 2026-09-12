# T14R FINAL REPORT — SciComp Planner Reliability and Executive Router Closure

## STATUS

**KEEP_SCICOMP_EXPERIMENTAL · KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL · weight promotion NO · paid compute NOT_USED · milestone CLOSED.**

- Model: Qwen/Qwen3-4B-Instruct-2507 (Mango-4B-System-v1), unchanged. No LoRA, no SFT, no weight changes.
- SciComp numeric: **0.8188** (113/138) vs T14 0.7319 (+8.7 pts) — below the unalterable 0.848 floor, so Decision A = KEEP.
- Executive router: frozen v1 recheck bit-identical to T14; corrected v2 suite (dedupe only, thresholds unchanged) meets every quality threshold with **zero router changes** — Decision B = KEEP (quality gates on the frozen v1 suite fail; all criticals pass).
- Protection battery: **ALL_PASS** (6/6 layers, 0 failures) · security battery: **0 violations**.
- pytest final: **1030 passed / 0 failed / 0 errors**.
- Final audit: **34 gates · 33 pass · 1 fail** — the sole fail is the genuine `scicomp_numeric_floor` (0.8188 < 0.848 unalterable), consistent with Decision A.

## Failure Analysis

T14's 37 incorrect numeric rows decomposed (T14R.2 forensics, `evaluations/t14r/t14_numeric_failure_analysis.json`): PROVENANCE_MISSING 8, PROVENANCE_WRONG 10, PLANNER_SCHEMA_FAILURE 11, ENGINE_REJECT 4, NUMERICAL_WARNING 1, RESULT_MISREAD 1, NO_INVOCATION 1, OTHER 1.

Replay recovery on the frozen suite (T14R.14, `replay_recovery_report.json`, B2 = official run): **22 recovered / 15 unchanged-wrong / 10 regressed** over 138 numeric rows.

- PROVENANCE_MISSING: **8/8 recovered** — the deterministic provenance repair layer closes this class completely.
- PLANNER_SCHEMA_FAILURE: 6/11 recovered.
- PROVENANCE_WRONG: 5/10 recovered.
- ENGINE_REJECT: 3/4 recovered.
- Regressions (10) decompose exhaustively: 7 spec-conformant fail-closed refusals on non-PASS envelopes (6 NUMERICAL_WARNING + 1 INVALID_INPUT — T14 scored these "right" only by asserting warning values as authoritative, a suite-gold/tension documented in the milestone mandate), 2 adopter output truncations (msc-v1-0114, msc-v1-0115), 1 empty final (msc-v1-0018). **Zero silent mutations, zero fidelity false-accepts, zero pipeline exceptions.**

## Planner Provenance

`repair_planner_request` (T14R.3/T14R.4, deterministic, value-preserving) closed the provenance classes: 8/8 PROVENANCE_MISSING and 5/10 PROVENANCE_WRONG recovered; repair fired on 132 invocations with 0 unknown-provenance admissions left open.

Critical hardening found by the replay itself (commit 57c0207): repair step 7's numbers-positional string rewrite could rewrite a **broken source expression** ("2x +" → "2x") with a false SOURCE_ALIGNED binding, bypassing the frozen fidelity gate's src→param classification — msc-v1-0194 then executed a value the question never gave. Fix: string-vs-string rewrites now require whitespace-only change, definition-prefix strip, or canonical AST equality; "2x +" is no longer rewritten and fidelity correctly PARAMETER_FIDELITY_FAILs the request. Two regression tests added (`test_string_source_rewrite_never_masks_broken_input`, `test_string_definition_strip_still_aligned`). msc-v1-0194 fixed in the live B2 run (correct, no invocation, no assertion).

## Result Adoption

Adoption microbench `mango-scicomp-adoption-v1` (T14R.12-13, pre-registered): verified_result_adoption **1.0** (≥0.98), wrong_result_field_selection **0**/127, unit_loss **0**/6, stale_answer_retention **0**/127, false_authoritative_adoption **0**, rounding_policy_violations **0.0** (≤0.01). All six targets met at ceiling.

Replay adoption (B2): **0.9314** (floor 0.90 PASS); histogram ADOPTED 96 / RESULT_IGNORED 2 / RESULT_MISREAD 4. The T14-era failure mode — misreading which envelope field is authoritative — is gone at the instrument level (classify_adoption now keys off the contract's authoritative_field).

## Rounding

Deterministic display: the result contract supplies the display value; the adopter is instructed to use it when the question asks for a rounding and never to invent precision of its own. Measured: rounding_policy_violations 0.0 on the microbench; zero precision-fabrication rows in the B2 replay. One residual instrument note: msc-v1-0030 (0.9999993 vs gold 1.0 at atol 1e-7) is an engine-accuracy edge, not a rounding violation.

## SciComp

Official frozen recheck run `t14r-scicomp-B2` (same frozen protocol, suites, grading as T12/T14; T14R layers inserted at exactly two points — repair before the schema gate, result contract before the adopter):

| metric | T14 | T14R (B2) | floor |
|---|---|---|---|
| numeric accuracy | 0.7319 | **0.8188** | 0.848 (unalterable) |
| model adoption rate | 0.9863* | **0.9314** | 0.90 |
| conceptual discipline | 1.0 | **1.0** | 1.0 |
| adversarial handled | 0.96 | **0.96** | 0.96 |
| adversarial false-answer rate | — | **0.0** | — |
| silent mutations | 0 | **0** | 0 |
| pipeline exceptions | 0 | **0** | 0 |

*adopted-measured under the T14 instrument (no authoritative_field); not directly comparable to the contract-keyed B2 instrument, both above floor.

## SciComp Decision

**KEEP_SCICOMP_EXPERIMENTAL** (`scicomp_decision.json`). Exactly one critical gate fails: `numeric_floor` (0.8188 < 0.848). All other criticals pass: adoption, conceptual, adversarial, silent_mutation (0), fidelity_false_acceptance (0), pipeline_exceptions (0). Numeric ≫ 0.5, so REJECT does not apply. One failed critical gate = no promotion.

## Executive MISSED_TOOL Analysis

24 MISSED_TOOL rows (23 final + 1 dev) decomposed (`executive_missed_tool_analysis.json`): **20 SUITE_DUPLICATE_ARTIFACT + 4 AVAILABLE_TOOL_MISSED.**

- SUITE_DUPLICATE_ARTIFACT: the T14 suite builder records each of the 18 no-tool questions twice (no_tool_tasks/GENERAL + numeric_scicomp/SCICOMP/COMPUTE_REQUIRED), producing contradictory duplicate gold. This is a benchmark defect, not a router defect — 20 of the 24 misses.
- AVAILABLE_TOOL_MISSED (4): 3 SCIENCE_RAG factual lookups + 1 MATH_T4 ("What is 25% of 80?"). All sit behind the frozen necessity layer (NO_COMPUTE → GENERAL); repairing them would require loosening no-tool behavior, which the milestone forbids.

## Top-2 Audit

Top-2 route accuracy failures are an **emission gap, not a ranking gap**: the router emits a single ranked candidate; secondary_skills appear on only 4/215 final-split traces. There is no second candidate to credit — top2 == primary by construction.

## Executive Router

Frozen v1 recheck (checksum-pinned): **bit-identical to T14** (`bit_identical_to_T14: true`). Corrected v2 suite (`t14r_build_exec_suite_v2.py`, drops the 20 duplicate-gold rows only, 304→284, thresholds unchanged):

| metric | v2 measured | threshold |
|---|---|---|
| top-2 route accuracy | **0.9824** | ≥ 0.92 |
| tool-required recall | **0.9714** | ≥ 0.90 |
| no-tool specificity | **1.0** | ≥ 0.90 |
| criticals (hallucinated tools, paid-route, bypass, unavailable-as-executed, depth) | **all 0** | 0 |

## Executive Router Decision

**KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL** (`executive_decision.json`). On the frozen v1 suite the quality gates fail (top2_route_accuracy, tool_required_recall) — so no promotion; all critical gates pass, so no rejection. Router repair: **NONE_JUSTIFIED** — the corrected evidence shows the router already meets every threshold once the benchmark artifact is removed, and the 4 genuine misses are behind the frozen necessity layer. No recall inflation by routing to non-executable capabilities.

## Protection

Protection battery **ALL_PASS** (`protection/regression_summary.json`) — full GPU battery re-run through the repaired pipeline, all 6 layers:

| layer | result | key metrics |
|---|---|---|
| T4 false-PASS | **PASS** | tool-enabled accuracy 0.7467, **false_pass_rate 0.0** |
| T5R citation | **PASS** | fabricated 0, unsupported 0, invalid 0 (G 0.5862 / NORAG 0.569) |
| Capacity | **PASS** | overall 0.8571 (n=131) |
| Extraction | **PASS** | wrong-final acceptance **0.0** |
| Correction | **PASS** | true_correction 0.80, false-feedback preservation 1.0, overcorrection 0, collateral 0, blind agreement 0 |
| SciComp fidelity | **PASS** | silent mutations 0 in B2; mutation-safety probe **8/8 mutations still rejected** |

Security battery: **0 violations** (`tests/*security*.py`, junit in `protection/`).

Honest instrument note: the first summary run reported a false `scicomp_fidelity` FAIL because the mirror script still pointed at run B1 (which predates the 0194 masking fix) and used a fail-closed default of 1 for a summary key the T14R runner does not write; the probe schema was also misread. Corrected to read the official B2 run (measured silent mutations: 0) and the actual probe result (8/8); re-run → ALL_PASS. No measurement was overridden — the corrected script reads raw evidence.

## Tests

`pytest_final.json`: **1030 passed, 0 failed, 0 errors, 0 skipped, exit 0** (includes the two new string-rewrite masking regression tests).

## Final Audit

`final_audit.json`: **34 gates · 33 passes · 1 fail · ready_for_T15: NO** (`manual_override: false`).

- Verified unchanged: necessity router, fidelity classifier, semantic classifier, correction firewall, skill registry, T3 adapter hashes — all pinned at entry-gate values; SciComp engine router.py-only drift check PASS; adoption-bench suite checksum PASS; model identity Qwen/Qwen3-4B-Instruct-2507.
- All 6 adoption-bench metrics PASS; all SciComp replay gates PASS except the numeric floor; executive recheck bit-identical to T14 with all criticals 0, corrected v2 evidence PASS, no-recall-inflation PASS; protection ALL_PASS; security 0; no-training PASS (adapter hash + clean git scan); no-paid-compute PASS; pytest 1030/0/0 PASS.
- Sole fail: **`scicomp_numeric_floor`** — 0.8188 < 0.848 (unalterable). This is the genuine, decision-consistent critical failure that drives Decision A = KEEP_SCICOMP_EXPERIMENTAL; it is recorded, not overridden.
- Instrument honesty: two bugs were found and fixed in the audit script itself before recording — a stale B1 run path (adversarial 0.92 vs official B2 0.96) and a falsy-zero evaluation trap (`0 or 1`) that falsely failed `rounding_policy_violations` (0.0 ≤ 0.01) and `exec_criticals_frozen_v1` (all six critical metrics are in fact clean). Final numbers above are from the corrected run over raw evidence.

## Weight Promotion

**NO.** The adapter hash is pinned and unchanged; no training of any kind was performed; Decision A and Decision B both forbid promotion regardless.

## Paid Compute

**NOT_USED.** All evaluation compute ran on local CPU + RTX 4050. Paid routes emit PAID_COMPUTE_GATE_REQUIRED only; zero paid-route violations in the executive recheck.

## Main Finding

The T14R repair layers are real and additive where they claim scope: deterministic provenance repair closes PROVENANCE_MISSING entirely (8/8) and the verified-result contract lifts numeric accuracy +8.7 pts (0.7319 → 0.8188) with zero silent mutations, zero fidelity false-accepts, and zero exceptions — while a defect the repair itself exposed (string-rewrite masking of broken expressions, msc-v1-0194) was found and closed rather than papered over. What remains below the 0.848 floor is no longer provenance or adoption: it is the planner choosing the wrong **operation**. The executive router, independently, already meets every threshold — its T14 failure was two-thirds benchmark artifact and one-third frozen-layer behavior the milestone forbids touching.

## Dominant Remaining Bottleneck

**Planner operation selection for ODE initial-value problems.** Of the 25 incorrect numeric rows in B2, 7 are ADOPTED-but-wrong — and 6 of those 7 are ODE final-state questions ("dP/dt = 0.3·P, P(0)=2: what is P at t=5?") that the planner routed to `definite_integral`. The engine faithfully computes — and the envelope verifies — the accumulated change ∫, not the solution y(t) = y₀·e^{kt}; the now-disciplined adopter then adopts the verified-but-wrong-quantity value with full certainty (e.g., msc-v1-0081: engine 3.75 vs expected 8.963; msc-v1-0083: 23.35 vs 1.218). The remaining 18 wrong rows split into 5 no-invocation fail-closed rows, 9 engine-not-PASS rows (NUMERICAL_WARNING/INVALID_INPUT refusals), and 2 RESULT_IGNORED/MISREAD — none of which is an adoption failure. The pipeline is trustworthy end-to-end; it computes the wrong quantity and trusts itself doing it.

## Ready for T15

**NO — one critical gate remains unmet.** The milestone itself closed cleanly: both decisions are recorded (A: KEEP_SCICOMP_EXPERIMENTAL, B: KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL), protection is ALL_PASS, security is clean, no training occurred, no paid compute was used, every frozen component hash verifies, and the router needs no repair. But the unalterable SciComp numeric floor (0.848) is still unmet at 0.8188 — the same critical gate that forces Decision A to KEEP also blocks T15 readiness, and per the milestone rule it is recorded rather than waived. The path to readiness is specific and quantified (see Highest-Value Next Step): recovering the 6-row ODE routing cluster alone yields ≈ 0.862 ≥ 0.848.

## Highest-Value Next Step

**Add ODE initial-value operation selection to the planner layer** (a dedicated solve-ODE/final-state operation — or planner-prompt guidance mapping "d y/dt = f(y), y(0)=y₀, what is y at t" to solution-form semantics rather than `definite_integral`). Arithmetic: the numeric deficit is 0.848 − 0.8188 = 0.0292 ≈ 4 rows on 138; the ODE cluster alone is 6 rows, so recovering it yields ≈ 0.862 ≥ 0.848. It is the single largest recoverable block (6 of 25 wrong rows), it is entirely in a primary-editable component (structured-request construction), and it does not touch any frozen layer.

---

STOP. Do not start T15.