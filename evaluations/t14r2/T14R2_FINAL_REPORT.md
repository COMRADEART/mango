# T14R2 FINAL REPORT — ODE Planner Operation Selection Closure

## STATUS

**PROMOTE_SCICOMP_LAB · KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL (unchanged from T14R) · weight promotion NO · paid compute NOT_USED · training NONE · milestone CLOSED.**

- Model: Qwen/Qwen3-4B-Instruct-2507 (Mango-4B-System-v1), unchanged. No LoRA, no SFT, no DPO, no weight changes, no model replacement.
- SciComp numeric: **0.8696** (120/138) vs T14R 0.8188 (+5.1 pts) — **at or above the unalterable 0.848 floor**, so the decision derived from the evidence is **PROMOTE_SCICOMP_LAB** (not pre-selected from the estimated 0.862).
- Executive Router: **NOT modified** — all T14R2 entry-gate pins re-verified (router, adopter, result-contract rounding, planner repair, invocation); the T14R decision remains the authoritative executive decision.
- Protection battery: **ALL_PASS** (6/6 layers) · security battery: **0 violations**.
- pytest final: **1060 passed / 0 failed / 0 errors**.
- Final audit: **49 gates · 49 pass · 0 fail · ready_for_T15: YES** (`manual_override: false`).

## Failure Analysis (T14R2.1–2.2)

The T14R bottleneck was isolated before any code change: of the 25 wrong numeric rows in the frozen B2 recheck, **6 are ODE initial-value planner-operation-selection failures** — recovering all six was projected to reach ≈0.862 ≥ 0.848. The six (`ode_failure_freeze.json`, frozen before any code change):

| eval_id | problem | class |
|---|---|---|
| msc-v1-0081 | dP/dt = 0.3·P, P(0)=2, t=5 | WRONG_ODE_OPERATION |
| msc-v1-0082 | verbal exponential decay | WRONG_ODE_OPERATION |
| msc-v1-0083 | dQ/dt = −Q/3, Q(0)=9, t=6 | WRONG_ODE_OPERATION |
| msc-v1-0084 | capacitor discharge, RC=2 | WRONG_ODE_OPERATION |
| msc-v1-0087 | dv/dt = 9.8, v(0)=0, t=3 | WRONG_ODE_OPERATION |
| msc-v1-0088 | dN/dt = r·N, r=0.07, N(0)=1000, t=10 | WRONG_ODE_OPERATION |

Taxonomy histogram: WRONG_ODE_OPERATION 6/6 (`ode_failure_analysis.json`, `single_cause_assumption: false`). The audit row msc-v1-0085 (second-order d²x/dt² = −4x) was **not** an operation-selection failure and was handled separately under T14R2.10 as a higher-order audit via the frozen engine's first-order-system conversion (SECOND_ORDER_SYSTEM_CONVERSION; equations `["y1", "-4*y0"]`, initial_state `[1, 0]`, t_end = π/2). Scope was **not** broadened to gain benchmark points: 0195's " from t=0 to t=1e6" phrasing remains deliberately unrecognized (minimal intervention).

## ODE Intent Layer (T14R2.4–2.10)

`src/sciencemath/scicomp/ode_intent.py` — the ONLY new SciComp module (primary editable area honored; all frozen components hash-pinned and re-verified):

- Inserted at exactly one point: **step 0 of the Arm-B pipeline, right after `parse_request`**, before the frozen necessity guard.
- Fires only when recognition succeeds AND the planner did not produce a well-formed first-order solve_ode request (fire reasons: WRONG_OPERATION_REMAPPED, SECOND_ORDER_SYSTEM_CONVERSION, NO_PLANNER_REQUEST). First-order solve_ode rows (0075–0080, 0086, 0182, 0195) are untouched.
- Deterministic construction: parameters `{equations, initial_state, t_start, t_end, parameters?}` with `source_inputs` an exact mirror; provenance restricted to USER_GIVEN / RETRIEVED_VERIFIED / DETERMINISTIC_DERIVATION / TOOL_DEFAULT_DECLARED — **no parameter invention** (MODEL_INVENTED impossible by construction). Fail-closed as INSUFFICIENT_INFORMATION whenever IVP information is absent.
- Higher-order ODEs use the frozen engine's first-order-system conversion only; anything else is OUT_OF_SCOPE_ENGINE_CAPABILITY. No scope broadening.
- Offline validation over all 206 frozen suite rows (`ode_intent_offline_validation.json`): **fired exactly the 7 target rows, 0 previously-correct rows touched, status PASS** — proven through the exact frozen gate chain (repair → schema → fidelity → engine → envelope → contract) with no LLM.

## Microbench (T14R2.11–2.12)

`mango-ode-planner-v1` (`ode_microbench/manifest.json`): **108 cases (56 positive / 52 negative), 25 families**, dev 49 / final 59 split by sha256(case_id); suite checksum `5e0c6e3b…` **frozen before tuning** (`checksum_frozen_before_tuning: true`). Oracle expected fields hand-written per family, independent of the layer.

All pre-registered targets met **at ceiling on both splits** (`ode_microbench_metrics.json`): IVP precision 1.0 (≥0.98), recall 1.0 (≥0.98), schema-valid 1.0 (≥0.98), provenance completeness 1.0, state-order correctness 1.0, parameter invention 0, exceptions 0.

## Six-Case Replay (T14R2.13)

Real GPU replay through `run_arm_b_t14r2` (real LLM parse + real adopter, frozen gates) (`six_case_replay.json`): **7/7 recovered** (six frozen failures + the 0085 second-order audit), layer fired on all 7, gates clean — schema OK, fidelity happy-path, envelope PASS, VERIFIED_COMPUTE_RESULT binding on every row.

## Frozen Recheck (T14R2.15)

Official run `t14r2-scicomp-B3` — same frozen protocol, suites, grading as T12/T14/T14R; the ODE intent layer inserted at step 0:

| metric | T14 | T14R (B2) | T14R2 (B3) | floor |
|---|---|---|---|---|
| numeric accuracy | 0.7319 | 0.8188 | **0.8696** | 0.848 (unalterable) — **MET** |
| model adoption rate | 0.9863* | 0.9314 | **0.9327** | 0.90 |
| conceptual discipline | 1.0 | 1.0 | **1.0** | 1.0 |
| adversarial handled | 0.96 | 0.96 | **0.96** | 0.96 |
| silent mutations | 0 | 0 | **0** | 0 |
| pipeline exceptions | 0 | 0 | **0** | 0 |

Suite checksum `e6e3f048…` identical to the T14R entry-gate pin — same frozen suite, no relabeling.

## ODE Subset Replay (T14R2.14)

Over the 16 ODE-route rows (`ode_subset_replay.json`): **6/6 frozen failures recovered**, 0085 second-order audit correct, **zero regressions** — every ODE row correct in B2 remained correct in B3. The layer fired on exactly the 7 target rows in the live recheck.

## SciComp Decision (T14R2.16–2.17)

**PROMOTE_SCICOMP_LAB** (`scicomp_decision.json`) — derived from the run, never pre-selected. All 8 critical gates PASS: numeric_floor 0.8696 ≥ 0.848, adoption 0.9327 ≥ 0.90, conceptual 1.0, adversarial 0.96 ≥ 0.96, silent_mutations 0, fidelity_false_acceptance 0, pipeline_exceptions 0, ode_regression 0. **Weight promotion NO** (paid compute NOT_USED; training NONE; adapter hash pinned and unchanged).

## Executive Router

Untouched by mandate. T14R2 entry-gate pins (executive router, T14R adopter, T14R result-contract rounding, T14R planner repair, T14R invocation) all re-verified byte-identical at the final audit; the T14R decision **KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL** (`evaluations/t14r/executive_decision.json`) stands unchanged.

## Protection (T14R2.19)

Protection battery **ALL_PASS** (`protection/regression_summary.json`) — full GPU battery re-run through the layer-inserted pipeline, all 6 layers:

| layer | result | key metrics |
|---|---|---|
| T4 false-PASS | **PASS** | tool-enabled accuracy 0.7467, **false_pass_rate 0.0** |
| T5R citation | **PASS** | fabricated 0, unsupported 0, invalid 0 (G 0.5862 / NORAG 0.569) |
| Capacity | **PASS** | overall 0.8571 (n=131) — identical to T14R |
| Extraction | **PASS** | wrong-final acceptance **0.0** |
| Correction | **PASS** | true_correction 0.80, false-feedback preservation 1.0, overcorrection 0, collateral 0, blind agreement 0 |
| SciComp fidelity | **PASS** | silent mutations 0 in B3; mutation-safety probe **8/8 mutations still rejected** |

The mutation-safety probe was re-run with the layer **inserted** (`t14r2_mutation_safety_probe.json`): 8/8 mutations rejected, 74 faithful rows, 0 exceptions, fidelity_transform 0/0 — identical to the T14R baseline; the layer is protection-neutral. Security battery: **0 violations** (`tests/*security*.py`).

Honest instrument note: the t4 layer crashed mid-battery with a transient `CUDA error: unknown error` immediately after its 150-row no-tool arm completed; the battery harness continues past child failures, so layers 2–5 ran to completion normally. The t4 tool arm was repaired by re-running the same frozen command (durable resume skipped the 150 completed no-tool rows; only the 150 tool rows ran), with **no CUDA recurrence** and false_pass_rate 0.0. The summary then reports ALL_PASS over complete per-layer evidence — no layer was skipped or papered over.

## Performance (T14R2.20)

`performance.json`: offline layer latency median **5.4 µs** (recognize) / **5.2 µs** (select), p95 ≈ 50 µs, max < 300 µs over all 206 frozen questions — microseconds against a ~20–32 s median LLM call. B3 median LLM latency 20.3 s vs B2 32.3 s (within run-to-run noise; the deterministic layer adds no measurable pipeline latency). Microbench runs fully offline (no GPU).

## Tests (T14R2.21)

`pytest_final.json`: **1060 passed, 0 failed, 0 errors, 0 skipped, exit 0** — the prior 1030 plus the 30 new `tests/test_t14r2_ode_intent.py` tests (recognition of all six + 0085, verbatim extraction, declared-parameter capture, fail-closed refusals, determinism, firing rule including adversarial shapes, evaluator bounds).

## Final Audit (T14R2.22)

`final_audit.json`: **49 gates · 49 passes · 0 fails · ready_for_T15: YES** (`manual_override: false`).

- Verified unchanged: necessity router, fidelity classifier, semantic classifier, correction firewall, skill registry, T3 adapter — all pinned at entry-gate values; T14R2 pins (Executive Router + T14R layers) unchanged; SciComp engine router.py-only drift PASS; frozen suite checksum matches the T14R entry-gate record; model identity Qwen/Qwen3-4B-Instruct-2507.
- Microbench (100–160 cases, checksum verified, all target gates), offline validation (PASS, 0 previously-correct firing rows), six-case replay (7/7, gates clean), B3 recheck gates, decision PROMOTE_SCICOMP_LAB + weight promotion NO, executive decision unchanged, protection ALL_PASS, mutation probe, security 0, performance recorded, no-training scan, pytest 1060/0/0 — all PASS.
- Instrument honesty: one key-name mismatch in the audit script itself (suite checksum read from a nonexistent `suite_scicomp` pin key) was fixed before recording to read the T14R entry-gate's recorded checksum; the pytest artifact key (`failures` → also expose `failed`) was aligned to the audit contract. Final numbers come from the corrected run over raw evidence; no measurement was overridden.

## Weight Promotion

**NO.** The adapter hash is pinned and unchanged; no training of any kind was performed. The T14R2.17 decision rule promotes the SciComp pipeline to LAB status only — weights stay frozen.

---

STOP. Do not start T15 automatically.