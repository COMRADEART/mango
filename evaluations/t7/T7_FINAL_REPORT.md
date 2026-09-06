# Mango — T7 Status Report (FINAL)

## STATUS

**NOT PROMOTED** — the executive layer as a whole is net-negative on
Mango-v0.1 (7 of 8 pre-registered gates measured; 5 failed). Mango-v0.1
remains the model. No weights changed at any point in T7.

## Executive summary

T7 tested the hypothesis: **can a bounded executive plan → execute →
observe → verify → re-plan loop improve Mango's generalization and
correctness WITHOUT changing model weights?** The executive layer
(`src/sciencemath/executive/`) was built and verified (T7.1–T7.35), the
evaluation suite `mango-executive-eval-v1` was authored, adversarially
reviewed, and frozen (T7.20), and the pre-registered matched OFF/ON
experiment + ablations A–G were run on the unchanged Mango-v0.1
checkpoint (Qwen/Qwen3-1.7B + unmerged T3 LoRA).

**The answer is NO for the current model.** The executive feature set
costs −9.8 pp overall (62.75% → 52.94%). Attribution (ablations):

- The regression comes from the **plan/execute scaffold itself**: it
  replaces the model's own compact direct computation with a
  fixed multi-step structure. This is the third independent confirmation
  of the same lesson (T5R decomposition −33 pp, T6 L1 SFT −16.6 pp):
  **the 1.7B degrades under added structure**.
- The verify / distractor-filter / correction-gate layers contributed
  **exactly 0.0 pp** each (C = D = F = G = E on the matched subset) —
  not because they are valuable-but-neutral, but because the layers
  they depend on rarely engage: the model **never** emitted a valid
  plan (first-attempt validity 0.0, fallback rate 0.94), so the
  deterministic fallback plan — which is REASON-only — drove almost
  every run, and **0 tool calls** were made in any arm (the T5 lesson
  repeats: the calculator is never delegated to).
- The correction gate **never fired** in any arm (0 corrections used):
  verdicts rarely reach FAILED-with-external-artifact on this model.
- The executive earned genuine, measurable wins: uncertainty recall
  0.11 → 0.44 with precision held (0.73), tool-failure robustness
  0.83 → 1.00 (structured error observations turn a tool crash into a
  recoverable answer), 0 fabricated citations, no simple-class
  regression, and 0 corrections that broke a correct answer.

- **No weights changed.** Mango-v0.1 remains the model in either outcome.
- Gates were recorded in `configs/executive.yaml` BEFORE the final
  comparison and were not modified afterwards.

## Executive layer (T7.1–T7.35)

- **Typed state machine, fail-closed** (`state.py`): states RECEIVED →
  CLASSIFYING → PLANNING → EXECUTING ⇄ OBSERVING → VERIFYING →
  REPLANNING → SYNTHESIZING → COMPLETE / INSUFFICIENT_EVIDENCE /
  FAILED / BUDGET_EXHAUSTED; every transition validated; BFS
  `_legal_path` routing; malformed state dicts rejected (missing
  `status` is a TransitionError, not an implicit RECEIVED).
- **Problem classification** (`classify_route` composed): MATH / SCIENCE
  / MIXED / GENERAL × SIMPLE / MULTI_STEP / OPEN_ENDED × NONE /
  MATH_TOOL / RETRIEVAL / BOTH / UNKNOWN.
- **Compact structured understanding** (`understand.py`): knowns /
  unknowns / constraints / missing — extractive spans only, no hidden
  CoT.
- **Distractor filter** (T7.5): REQUIRED / SUPPORTING / IRRELEVANT /
  CONFLICTING / UNKNOWN; IRRELEVANT sentences excluded from step
  context.
- **Plan schema** (`plan.py`): actions ONLY REASON / RETRIEVE /
  MATH_TOOL / CHECK / SYNTHESIZE; unique ids; DAG-acyclic;
  MAX_PLAN_STEPS = 6 (budget-honored); model plan → schema-feedback
  retry → deterministic fallback; first-attempt / retry validity
  recorded separately (T7.23).
- **Step execution** (`execute.py`): compact step context (goal +
  included facts + dependency observations — including retrieved chunk
  TEXT, so the model can read its evidence); errors-as-observations;
  fixed action space (anything else REJECTED).
- **Budgets on every axis** (`budgets.py`): model_calls / tool_calls /
  retrievals / replans / plan_attempts / steps_executed / elapsed_s /
  max_step_seconds / input/output tokens; `>=` cap semantics; pre-step
  guards (a reached cap funds no call); step-time enforced between
  steps (a hung generation cannot be preempted mid-call — recorded
  limitation); exhaustion → explicit BUDGET_EXHAUSTED terminal state.
- **Verification, deterministic-first** (`verify.py`): math answers vs
  tool recomputation (calculator's `ToolResult.result` dict compared by
  VALUE); retrieval claims via bracketed chunk-id citations (corpus
  ids contain colons; source-prefixed forms like `[w:c1]` for `c1` are
  anchored, unknown ids are fabricated → FAILED); absence of citations
  is UNKNOWN, not FAILED. The model is never asked "is this right?".
- **Replanning** (`replan.py`): event-triggered only
  (VERIFICATION_FAILED / RETRIEVAL_INSUFFICIENT / DEPENDENCY_INVALID /
  CONTRADICTION); max 2; loop detection via plan fingerprints → STALLED;
  CONTRADICTION is terminal (declined as CONFLICTING_EVIDENCE), never a
  replan (re-executing a plan cannot fix a textual contradiction);
  RETRIEVAL_INSUFFICIENT amendments force a RETRIEVE step so the
  replacement actually re-queries.
- **Deterministic stopping reasons** (T7.14): SOLVED_VERIFIED /
  SOLVED_UNVERIFIED / INSUFFICIENT_INFORMATION / CONFLICTING_EVIDENCE /
  STALLED / BUDGET_EXHAUSTED / SYSTEM_ERROR.
- **Categorical uncertainty ONLY** (`uncertainty.py`): VERIFIED /
  STRONGLY_SUPPORTED / PARTIALLY_SUPPORTED / UNCERTAIN /
  INSUFFICIENT_INFORMATION / CONFLICTING_EVIDENCE — derived from
  observable signals (empty retrieval, failed verification,
  contradictions, missing quantities); no confidence percentages.
- **Self-correction ONLY on external contradictory evidence**
  (`correction.py`): FAILED verdict + specific contradicting artifact;
  max 1 per run; structured correction contract; explicit "Unchanged:"
  escape (overcorrection protection is a measured metric).
- **Checkpoint durability** (T7.28/T7.30): per-step checkpoint saves;
  resume restores completed steps/observations/tool results and never
  re-executes a completed tool call or retrieval.
- **Prohibitions honored**: no arbitrary Python execution, no
  autonomous web browsing, no simulation environments, no Lean/Z3, no
  persistent cross-run memory, no multi-model swarms, no expert LoRAs,
  no self-modifying code, no larger-model migration.

## Round-2 adversarial review (54 agents) — findings fixed

18 confirmed findings; all fixed and regression-tested. Highlights
(critical):
- Real corpus chunk ids contain colons (`wiki-18716923:intro_x:0`) —
  the citation regex excluded them, so every real citation was
  unparseable.
- The calculator's `ToolResult.result` is a dict — verification was
  comparing the extracted answer against the dict repr (every math
  answer FAILED).
- Retrieved chunk TEXT never reached any model prompt (ids only).
- Checkpoint resume was write-only; budget axes had off-by-one and
  dead axes; replan re-arm wiped or skipped steps; conflict detector
  over- and under-flagged (recalibrated to 8/8 on the frozen
  contradictory class, 0 false positives on the other 94 items).

## Round-3 adversarial review — findings fixed (pre-launch)

11 confirmed findings; all fixed and regression-tested
(`tests/test_t7_eval_metrics.py`). Critical:
- **OFF arm was tokenizing bare prompts** while every ON arm and every
  T5R/T6 baseline uses the chat template — an unmatched comparison.
  First launch stopped ~6 questions in, purged, fixed
  (`render_for_model` in `run_off_arm`), smoke-verified, relaunched.
- Gates now evaluate ONLY on a complete matched run (identical
  full-suite question-id sets; skipped with an explicit reason
  otherwise).
- **G6 measures the declared T7.36 net gain** from recorded
  correction events (fixes − breaks) — the old decline-FP proxy is
  diagnostic only.
- **G8 counts fabricated citations only where evidence was supplied**
  (harness-injected retrieval failures excluded; unaudited runs
  reported separately); the SYNTH prompt no longer seeds a literal
  `[c1]` example id.
- Honest-decline semantics: SYSTEM_ERROR / BUDGET_EXHAUSTED /
  extraction-failures are NOT declines; prose hedging with a committed
  answer is NOT a decline.
- Ablation analyzer dedupes duplicate ids and restricts E to each
  ablation arm's exact question set (subset-vs-full mixing fixed).

## Suite (T7.20) — mango-executive-eval-v1

- **FROZEN**: `evaluations/executive-suite/v1/` — never trained on.
- 102 questions across 11 classes: simple 12, multi_step_math 12,
  multi_hop_science 12, mixed 12, distractor 12, missing_info 10,
  contradictory 8, counterfactual 6, tool_failure 6, retrieval_failure
  6, self_correction 6.
- Per-question SHA-256 checksums, verified at freeze; author + adversarial
  verification workflow rounds (all 11 classes verified PASS; ~10 items
  rewritten after verification rejected them).

## Matched experiment (T7.19/T7.38)

- Same checkpoint (Mango-v0.1), same frozen suite, same generation
  config; the ONLY difference between arms is the executive feature set.
- Arms: A_off (canonical eval prompt, no executive machinery) and
  E_full_executive on all 102 items; ablations B_plan_only,
  C_plan_tools, D_plan_exec_verify, F_no_distractor_filter,
  G_no_correction_gate on the 72-item diagnostic subset.
- Gates pre-registered in `configs/executive.yaml` before the final
  comparison.
- Completeness verified: all arms full coverage, no duplicate ids, no
  0 SYSTEM_ERROR runs anywhere.

### Gates (pre-registered — evaluated AFTER results, thresholds unchanged)

| Gate | Metric | Threshold | Measured | Pass |
|---|---|---|---|---|
| G1 | accuracy.overall ON−OFF | ≥ +3.0 pp | −9.80 pp | ❌ |
| G2 | accuracy.distractor ON−OFF | ≥ +5.0 pp | −8.33 pp | ❌ |
| G3 | uncertainty.precision (ON) | ≥ 0.5 | 0.727 | ✅ |
| G4 | uncertainty.recall (ON) | ≥ 0.5 | 0.444 | ❌ |
| G5 | plan.first_attempt_validity (ON) | ≥ 0.3 | 0.0 | ❌ |
| G6 | correction.net_gain (ON) | > 0 | 0 (0 used) | ❌ |
| G7 | accuracy.simple regression | ≤ 5.0 pp | 0.0 pp | ✅ |
| G8 | citations.fabricated (ON) | = 0 | 0 (0 unaudited) | ✅ |

**Decision: NOT PROMOTED** — Mango-v0.1 remains the model either way.

### Per-class accuracy, matched full suite (A_off → E_full_executive)

| Class | OFF | ON | Δ |
|---|---|---|---|
| simple | 0.92 | 0.92 | 0 |
| multi_step_math | 0.83 | 0.67 | −17 pp |
| mixed | 0.67 | 0.42 | −25 pp |
| multi_hop_science | 0.42 | 0.25 | −17 pp |
| self_correction | 0.83 | 0.33 | −50 pp |
| distractor | 0.92 | 0.83 | −8 pp |
| tool_failure | 0.83 | 1.00 | **+17 pp** |
| retrieval_failure | 0.50 | 0.50 | 0 |
| counterfactual | 1.00 | 1.00 | 0 |
| missing_info | 0.00 | 0.00 | 0 (measured by uncertainty, not accuracy) |
| contradictory | 0.00 | 0.00 | 0 (decline-design) |

Uncertainty: OFF precision 1.00 / recall 0.11 → ON precision 0.73 /
recall 0.44 (tp 2→8, fp 0→3, fn 16→10).

### Ablations (B..G vs E on the matched 72-item diagnostic subset)

E on the subset: 47.22% (its 52.94% full-suite figure includes
simple/counterfactual/retrieval classes not in the subset).

| Arm | Removes | Accuracy | Δ vs E | Avg latency | Avg in-tok | model/tool/retr calls |
|---|---|---|---|---|---|---|
| B_plan_only | tools+exec+verify+corr+filter (plan + REASON only) | 51.39% | **+4.17 pp** | 246.6 s | 302 | 272 / 0 / 0 |
| C_plan_tools | verify+corr+filter | 47.22% | 0.00 | 31.8 s | 376 | 271 / 0 / 14 |
| D_plan_exec_verify | corr+filter | 47.22% | 0.00 | 27.5 s | 381 | 273 / 0 / 14 |
| E_full_executive | — | 47.22% | — | 19.9 s | 401 | 278 / 0 / 15 |
| F_no_distractor_filter | distractor filter | 47.22% | 0.00 | 19.2 s | 401 | 278 / 0 / 15 |
| G_no_correction_gate | correction gate | 47.22% | 0.00 | 15.3 s | 399 | 277 / 0 / 15 |

Reading:
- **The scaffold is the cost.** B (plan-only, no tools) is +4.17 pp
  over E and the whole stack is still far below OFF. Removing the
  tool/verify layers doesn't recover OFF-level accuracy — the
  plan→execute loop itself is what displaces the model's own
  computation (self_correction −50 pp, mixed −25 pp vs OFF).
- **Verify / distractor-filter / correction layers are inert here**:
  removing each changes nothing (deltas exactly 0.0) because their
  triggers almost never fire — 0 valid model plans (fallback 0.94),
  0 tool calls, 0 corrections. Distinguishing "neutral" from
  "unexercised": these are **unexercised**, not validated-neutral.
- **B's +4.17 pp is real but bought at 12× latency** (246.6 s vs 19.9 s)
  and it loses the tool-failure robustness pathway.
- B uncertainty precision 1.0 vs 0.727 for tool-enabled arms — the 3
  uncertainty FPs in C..G come from the tool/execution pathway.

### Cost accounting (T7.39)

Full-suite averages (102 items):

| Arm | avg latency | avg in-tokens | avg out-tokens | total model calls |
|---|---|---|---|---|
| A_off | 7.9 s | 78 | 66 | 102 |
| E_full_executive | 19.9 s (subset) | 401 (subset) | 53 (subset) | 278 (subset) |

The executive costs ~2.5–5× latency and ~5× input tokens per item
(depending on arm) while scoring −9.8 pp. Only B is dramatically
worse on cost (246.6 s) because tool delegation never happens and the
model re-derives everything in long REASON chains.

## Tests

- pytest: **657 passed / 0 failed / 0 errors / 0 skipped** (JUnit-verified;
  floor was 560 at T5R close, 591 at T6 close)
- Regression tests added for every round-2 finding (citation colon
  ids, source-prefix anchoring, dict tool payloads, master switch,
  forced-retrieval amendment, retrieval-history survival, budget
  semantics, checkpoint resume, correction contract) and round-3
  findings (declined semantics, measured correction net gain,
  citation scoping, gate completeness, subset-vs-full ablation deltas).

## Artifacts

- `src/sciencemath/executive/` — the layer (runner, state, plan,
  understand, budgets, execute, verify, replan, uncertainty,
  correction, checkpoint, llm, failures)
- `configs/executive.yaml` — budgets + pre-registered gates + ablations
- `evaluations/executive-suite/v1/` — frozen suite (102 q, checksums)
- `scripts/run_executive_eval.py` — arms runner (resume-safe,
  chat-templated OFF arm, completeness-guarded gates)
- `scripts/analyze_t7_ablations.py` — ablation deltas vs E (id-matched)
- `evaluations/t7/exec_results/mango-v0.1/` — predictions (7 arms,
  full coverage), metrics.json, gate_decision.json, ablation_analysis.json,
  trajectories, checkpoints
- Stale smoke artifacts archived to
  `evaluations/t7/exec_results/_stale_smoke_archive/` (never reused:
  the arms runner resume-skips existing question ids)

## Honest limitations

- **The central negative result is a model-capacity result, not a
  layer-correctness result.** Every mechanism was unit- and
  regression-tested; on the frozen suite the 1.7B cannot plan (validity
  0.0), does not delegate to tools (0 calls), and rarely triggers
  verification failure with external artifacts (0 corrections). The
  layers are implemented and unexercised — a stronger base model is
  the prerequisite for this architecture to have a chance.
- The executive's genuine wins (uncertainty recall +33 pp at held
  precision, tool-failure robustness +17 pp, zero fabricated citations)
  are real but were not enough to overcome the scaffold's accuracy cost.
- Plan-timeout enforcement works between steps only — a hung generation
  cannot be preempted mid-call (recorded design limitation).
- Uncertainty metrics on the OFF arm use frozen T6
  `signals_uncertainty` semantics on raw text; ON uses committed-answer
  semantics — the asymmetry is documented and the gated metrics are
  ON-only.
- G6 measured 0 net gain partly because the correction gate never
  fired — the gate cannot demonstrate value the trigger never reaches.
- The ablation subset (72 items) is small per class (6–12), so single
  class deltas carry ±1-question granularity.

## T8

Not started — per directive, T7 ends here. The T7 evidence argues the
next capacity investment should be the model, not more scaffolding.