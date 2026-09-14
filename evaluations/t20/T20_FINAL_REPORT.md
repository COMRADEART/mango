# T20 FINAL REPORT — Multi-Agent Orchestration

_Recorded 2026-09-14T20:26:42.942972+00:00_

## 0. Promotion decision

**PROMOTE_ORCHESTRATION_SKILL**

| Item | Value |
| --- | --- |
| Authority | COORDINATE_INTERNAL_WORK_ONLY |
| Executive Router | EXPERIMENTAL — not promoted, not claimed by T20 |
| External action | Out of scope for T20 (T24) |
| Autonomous workflow engine | Out of scope for T20 (T25) |
| Applied | already applied (ORCHESTRATION is ACTIVE) |

## 1. Scope and constraints

- Bounded multi-agent orchestration coordinating specialist agents over validated T19 plans: role manifests, handoff contracts, independent verification, budgets, checkpoint/resume, and bounded recovery. No training, no weight changes, no base-model migration, no paid APIs. Frozen promotion evaluation ran with NETWORK OFF on fixture providers only; the Mango repo was not mutated by the evaluation (fixture providers, sandbox state, deterministic worlds).
- Executive Router hash verified bit-identical to the T19.1 freeze.
- T19 historical results untouched; the T19 stress-coverage debt remains DOCUMENTED as-is (not rewritten here).

## 2. Benchmark suites (T20.51–T20.57)

| Suite | Dev (passed/total) | FINAL (passed/total) |
| --- | --- | --- |
| mango-agent-concurrency-v1 | 60/60 | 60/60 |
| mango-agent-handoff-v1 | 75/75 | 75/75 |
| mango-agent-recovery-v1 | 75/75 | 75/75 |
| mango-agent-verifier-v1 | 100/100 | 100/100 |
| mango-orchestration-core-v1 | 130/130 | 130/130 |
| mango-orchestration-eval-v1 | 210/210 | 210/210 |
| mango-orchestration-long-horizon-v1 | 6/6 | 30/30 |

**680/680 FINAL cases pass; dev split identical.**

Long-horizon FINAL: **30/30** strict scenarios (15–30 tasks, ≥3 skills, ≥2 dependency edges, ≥1 observation-triggered replan, ≥1 verifier-requested revision, ≥1 parallel branch, ≥1 recovery path each).

## 3. Baselines (T20.58/T20.59)

| Suite | T20 pass | T20 complete (gold-COMPLETE) | A: T19 sequential | B: naive dispatcher | B spurious completions | B false-complete | T20 claim rejections |
| --- | --- | --- | --- | --- | --- | --- |
| mango-agent-concurrency-v1 | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 0 | 0 |
| mango-agent-handoff-v1 | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 0 | 0 |
| mango-agent-recovery-v1 | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 25 | 0 |
| mango-orchestration-core-v1 | 100.0% | 100.0% | 100.0% | 100.0% | 10 | 60 | 60 |
| mango-orchestration-eval-v1 | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 20 | 0 |
| mango-orchestration-long-horizon-v1 | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 30 | 0 |

Reading: the naive dispatcher claims completion everywhere, including cases the contract requires to BLOCK (spurious completions) and accepts every adversarial or under-evidenced worker claim (false completions). T20 fabricates **zero** completions, contains adversarial claims the baselines accept, and recovers at least as well as T19 sequential on failure-injected cases, with independent verification coverage the baselines cannot have (0 verifications by construction).

## 4. Preregistered floors (T20.60)

Floors check: **PASS** (17 checks).

- ✅ suite:mango-agent-concurrency-v1: total=120>=100 pass_rate=1.000>=0.95
- ✅ suite:mango-agent-handoff-v1: total=150>=120 pass_rate=1.000>=0.95
- ✅ suite:mango-agent-recovery-v1: total=150>=100 pass_rate=1.000>=0.95
- ✅ suite:mango-agent-verifier-v1: total=200>=150 pass_rate=1.000>=0.95
- ✅ suite:mango-orchestration-core-v1: total=260>=220 pass_rate=1.000>=0.98
- ✅ suite:mango-orchestration-eval-v1: total=420>=350 pass_rate=1.000>=0.95
- ✅ suite:mango-orchestration-long-horizon-v1: total=36>=30 pass_rate=1.000>=0.95
- ✅ false_complete_le_b:mango-agent-concurrency-v1: t20=0 baseline_b=0
- ✅ false_complete_le_b:mango-agent-handoff-v1: t20=0 baseline_b=0
- ✅ false_complete_le_b:mango-agent-recovery-v1: t20=0 baseline_b=25
- ✅ recovery_ge_a:mango-agent-recovery-v1: t20=1.000 baseline_a=1.000
- ✅ false_complete_le_b:mango-orchestration-core-v1: t20=0 baseline_b=60
- ✅ adversarial_contained:mango-orchestration-core-v1: 20/20 contained
- ✅ recovery_ge_a:mango-orchestration-core-v1: t20=1.000 baseline_a=1.000
- ✅ false_complete_le_b:mango-orchestration-eval-v1: t20=0 baseline_b=20
- ✅ false_complete_le_b:mango-orchestration-long-horizon-v1: t20=0 baseline_b=30
- ✅ parallel_batches:mango-orchestration-long-horizon-v1: batch_cases=30

## 5. Zero-tolerance gate (T20.61)

Gate: **PASS** — 440 run-mode FINAL cases, 0 violations. All 24 counters exactly zero on every run; event-log replay equivalent.

## 6. Protection battery (T20.62)

Status: **ALL_PASS** — hash identity of all frozen components (including the Executive Router) verified; security pytest subset green; mutation-safety probe pass; published suite checksums match the tuning_closed freeze.

## 7. Performance (T20.80)

Long-horizon FINAL scenarios with ≥2-task parallel batches: **30/30**. Per-suite mean steps recorded in `results/performance.json`.

## 8. Full pytest battery

Full battery (all suites, including the six new T20 test files): **1574 passed, 0 failures, 0 errors, 2 intentional skips** — see `pytest_final_t20.xml`.

## 9. Final audit (T20.81)

Audit: **PASS** (31 checks, 0 failed).

## 10. Claims

- **Allowed claim:** coordination of bounded specialist agents over validated plans, with independent verification, budgets, and containment.
- **Forbidden claim (not made):** "Mango can autonomously operate external systems."
- The Executive Router remains EXPERIMENTAL; T20 neither promotes nor claims it.

## 11. STOP

T20 is closed with this report. **Do not start T21 automatically.**
