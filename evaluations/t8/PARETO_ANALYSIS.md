# T8.13 / T8.18 — Pareto Analysis (model-only arm)

Frozen suite: `mango-capacity-eval-v1` (131 questions). Arm: model-only,
executive scaffolding disabled (T8.6). All vectors independently
recomputed from saved predictions (`recomputed_metrics.json`, all AGREE).
Decoding: card-guided profiles fixed before evaluation (T8.7), never
tuned post hoc.

Machine-readable data: `evaluations/t8/pareto_analysis.json`.

## Capability vectors (recomputed, model-only)

| Dimension | 1.7B control | Qwen3-4B-Inst | Phi-4-mini-inst | Phi-4-mini-reas | SmolLM3-3B |
|---|---:|---:|---:|---:|---:|
| overall | 0.815 | 0.815 | 0.571 | 0.807 | 0.739 |
| math | 0.862 | 0.793 | 0.862 | 0.793 | 0.759 |
| science | 0.800 | 0.833 | 0.500 | 0.900 | 0.667 |
| cross_domain | 0.917 | 0.833 | 0.417 | 0.750 | 0.750 |
| compositional | 0.667 | 0.750 | 0.167 | 0.583 | 0.583 |
| counterfactual | 0.583 | 0.667 | 0.333 | 0.583 | 0.750 |
| distractor | 0.917 | 0.917 | 0.750 | 1.000 | 0.917 |
| uncertainty | 0.267 | 0.762 | 0.600 | 0.000 | 0.375 |
| decomposition | 0.000 | 0.375 | 0.667 | 0.292 | 0.000 |
| self_correction | +0.182 | −0.227 | +0.176 | +0.043 | +0.516 |
| tool_routing | 0.000 | 0.375 | 0.667 | 0.292 | 0.000 |
| extraction | 0.975 | 1.000 | 1.000 | 0.916 | 0.899 |

## Pareto front

**All five runs are on the front** — no candidate dominates another; every
model holds at least one dimension win. Selection therefore cannot be
decided by dominance; it must weigh dimensions by the pre-registered
priority order (correctness > generalization > decomposition > ability to
exploit tools/RAG > safety > balance > uncertainty > local feasibility).

## Dimension winners (explicit)

| Category | Winner | Value | Runner-up |
|---|---|---:|---|
| **Balanced winner** | Qwen3-4B-Instruct-2507 | — | see note below |
| Math winner | Phi-4-mini-instruct (tie: 1.7B control) | 0.862 | Qwen3-4B / Phi-4-mini-reas 0.793 |
| Science winner | Phi-4-mini-reasoning | 0.900 | Qwen3-4B 0.833 |
| Decomposition winner | Phi-4-mini-instruct | 0.667 | Qwen3-4B 0.375 |
| Generalization winner | Qwen3-4B-Instruct-2507 | — | best compositional (0.750) + counterfactual (0.667) + uncertainty (0.762) among near-top overall |
| Uncertainty winner | Qwen3-4B-Instruct-2507 | 0.762 | Phi-4-mini-inst 0.600 |
| Local-efficiency winner | Qwen3-4B-Instruct-2507 | +0.026 mean gain | only candidate with positive mean capability gain |

**Balanced-winner note.** Qwen3-4B-Instruct-2507 ties the control on
overall (0.815) while being the only candidate with a *positive* mean
capability gain (+0.026) and the only one that improves the four
T6/T7-critical dims simultaneously (uncertainty +0.495, decomposition
0→0.375, compositional +0.083, counterfactual +0.083, tool_routing
0→0.375) at no VRAM/offload penalty. Its costs: math −0.069,
cross_domain −0.083, and a *negative* self-correction net (−0.227:
11/12 overcorrections under false FAIL feedback).

## Caveats that materially affect reading

1. **Phi-4-mini-reasoning uncertainty = 0.000 is a detection artifact
   plus genuine calibration failure, not the worst fabrication.** Its
   hallucinated-answer rate on unanswerable items is the best in the
   field (1/12 = 8.3%) but `signals_uncertainty` matched 0 of its
   phrasings on those items and it produced 1 false-uncertainty signal
   on an answerable item. Its "always answers with forced CoT" style
   means the standard signal list does not capture its hedging.
2. **Phi-4-mini-reasoning cost (T8.7 protocol note).** It ran with
   max_new_tokens 2048 (card-mandated long-CoT exception; all others
   1024). Per-item cost: see `recomputed_metrics.json`/run summary —
   mean generated tokens and latency are roughly 2x the instruction
   models; median latency per question ≈ 2x. Quality gains must be read
   together with ~2x generation cost.
3. **Phi-4-mini-instruct is severely split**: best decomposition
   (0.667), tool routing (0.667) and extraction (1.0) in the field, but
   catastrophic QA (overall 0.571, science 0.500, cross_domain 0.417,
   compositional 0.167). It is *not* a viable migration candidate, but
   it is existence proof that a ~4B model CAN produce valid plans and
   route tools — the executive scaffold is reachable at this scale.
4. **SmolLM3-3B** has the best counterfactual (0.750) and self-correction
   (+0.516, 0 overcorrections) but zero decomposition and the largest
   math regression (−0.103) with science −0.133.
5. **Qwen3-4B self-correction is negative** — it accepts objective
   correction on genuinely-wrong items (6 fixed) but destroys
   11/12 correct answers when told they were wrong. Control preserved
   12/12. This is a production-flow risk independent of accuracy.

## Migration recommendations (pre-registered rule)

`migration_decision()` (REGRESSION_TOLERANCE 0.05 on math/science,
WIN_DIMS_REQUIRED 3, MIN_OVERALL_GAIN 0.03):

| Candidate | Decision | Reason |
|---|---|---|
| Qwen3-4B-Instruct-2507 | DO_NOT_MIGRATE | math −0.069 exceeds 0.05 tolerance; overall delta +0.000; 4 capacity dims improved |
| Phi-4-mini-instruct | DO_NOT_MIGRATE | science −0.300; overall −0.244 |
| Phi-4-mini-reasoning | DO_NOT_MIGRATE | math −0.069; overall −0.008 |
| SmolLM3-3B | DO_NOT_MIGRATE | math −0.103, science −0.133 |

No candidate clears the pre-registered bar on the model-only arm alone.
The T4/T5R integration arms (T8.15–T8.16) on the finalists may still
change the picture via tool routing / retrieval routing / safety gates,
but the migration bar must be met with evidence, not adjusted.