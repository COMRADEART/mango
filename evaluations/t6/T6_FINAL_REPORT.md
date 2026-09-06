# Mango — T6 Status Report (FINAL)

## STATUS

**PARTIAL** — per T6.28: Mango-v0.2 was NOT promoted (Level 1 checkpoint
failed the pre-declared regression gates decisively); Mango-v0.1 is
retained as the best checkpoint. T6 = PARTIAL is the explicitly acceptable
outcome. All T6 *infrastructure* milestones (T6.0–T6.23) are complete and
verified; the *model improvement* objective (T6.28) was attempted,
measured, and honestly rejected by the pre-declared gates.

## Capability matrix (T6.1)

- 81 capability tracks across 7 families (mathematics, physics,
  chemistry, biology, earth_space, scientific_reasoning, cross_domain)
- `src/sciencemath/curriculum/capabilities.py`; initial matrix snapshot
  `evaluations/t6/capability_matrix_initial.json`
- Matrix update semantics: monotone best-checkpoint tracking with
  acquired / at-risk / regressed states

## Eval core (T6.2/T6.3) — mango-eval-core-v1

- **FROZEN before any curriculum training**, outside all training corpora
- 151 questions; all 16 categories (7–12 each); checksummed + verified
- Generalization splits: IID 98 / COMPOSITIONAL 18 / OUT_OF_TEMPLATE 23 /
  CROSS_DOMAIN 12
- Routing labels: TOOL 83 / RETRIEVAL 21 / BOTH 2 / NONE 36 /
  INSUFFICIENT_INFO 9
- Built by 8 author agents + adversarial verifier agents; 152 authored,
  151 kept, 1 rejected (answer leaked in stem); 0 contamination flags
- `evaluations/eval-core/v1/` (checksums verified)

## Corpus (T6.4–T6.9) — mango-sft-v2 Level 1

- **FROZEN**: `training/curriculum/mango-sft-v2/level1/` (checksums
  verified); frozen `sciencemath-sft-v1` untouched (checksum test green)
- 889 examples = 754 new (615 deterministic generated + 139 authored
  science) + 135 replay (15.2%)
- 100% of records verified: T4 parse gate + tool cross-check
  (generators, 175/175 across 3 seeds) or verbatim corpus grounding
  (authored science, 176/176 after 4 verifier-rejected drops)
- Contamination vs eval-core-v1 + suite-v1: **0 flags**
- Token mixture (measured, Qwen tokenizer): mathematics 0.564 /
  sciences 0.410 / general 0.026 vs targets 0.50/0.35/0.15 — general
  12.4pp under target (structural: no general-domain corpus at L1;
  recorded, not silently accepted)

## Curriculum (T6.5–T6.15, T6.17–T6.27)

- Eight levels declared (`levels.py`), validated; L1 executed
- Difficulty 1–5 enforced per level and per track
- Replay buffer: 135 L1 records from frozen v1, stratified, excluding
  stage questions, train-only
- Promotion protocol: `training/curriculum/promotion_log.jsonl`;
  gates pre-declared in `configs/curriculum.yaml` (9 absolute-pp
  dimensions) BEFORE any training; Pareto checkpointing over 8-dim
  capability vectors with balanced_best
- Concise format (`Answer: \boxed{...}` + short visible steps); no
  hidden CoT (decomposition schema rejects long goals)
- Counterfactual suite: 145 frozen variants (49 change_value
  tool-recomputed, 95 add_distractor, 1 alter_unit)
- Failure memory: 11 error types; populated with 65 baseline + L1
  failure records
- Dry runs (T6.20): per-stage, blocking; caught a real lineage-config
  mismatch on L1's first run (target_modules list-order comparison bug —
  fixed to order-independent; no training executed against a mismatched
  config)
- Unified adapter lineage (T6.21): `mango-v0.2-L1` LoRA seeded from
  parent `sciencemath-v0.1-t3` after config-match verification

## Metrics deltas (mango-eval-core-v1, closed-book, greedy, seed 42)

| dim | mango-v0.1 | mango-v0.2-L1 | delta |
|---|---|---|---|
| overall | 0.5695 | 0.4040 | **−16.6 pp** |
| math_macro | 0.6774 | 0.4516 | **−22.6 pp** |
| science_macro | 0.5400 | 0.5200 | −2.0 pp |
| cross_domain | 0.5000 | 0.2500 | **−25.0 pp** |
| compositional | 0.6667 | 0.3333 | **−33.3 pp** |
| tool_routing | 0.7425 | 0.7425 | 0.0 (deterministic arm) |
| retrieval_routing | 0.5644 | 0.5644 | 0.0 (deterministic arm) |
| extraction | 0.9868 | 1.0000 | +1.3 pp |
| uncertainty | 0.0000 | 0.0000 | 0.0 |
| RAG arm accuracy | 0.2609 | 0.2174 | −4.3 pp |
| fabricated citations | 0 | 0 | T5R firewall intact |

Generalization splits (baseline → L1): COMPOSITIONAL 0.667→0.333,
OUT_OF_TEMPLATE 0.522→0.478, CROSS_DOMAIN 0.417→0.250.

Self-correction (T6.18): baseline correction 0.092 / overcorrection
0.154 → L1 correction 0.022 (regressed). Baseline decomposition
JSON-valid 0.10, routing agreement 0.0 (plan ability is an L2+ target;
not achieved at L1).

Counterfactual (T6.17): baseline pass 0.4828 (add_distractor 0.505,
change_value 0.429, alter_unit 1.0); L1 pass 0.2414 (add_distractor
0.274, change_value 0.163, alter_unit 1.0) — robustness regressed in
lockstep with the core-suite damage.

## Retention (T4/T5R/T6 capability protection)

- T4 tool protections: 0 false-PASS tolerance unchanged; tool_check
  re-verification active in eval-core build; full T4 test files green in
  final pytest (see Tests)
- T5R retrieval firewall: citation integrity **0 fabricated citations**
  in all RAG-arm measurements (baseline 23 items, L1 23 items); frozen
  RAG eval semantics preserved
- T6 capability retention: the curriculum pipeline itself did NOT mask
  the regression — the frozen core suite measured it directly; gates
  REJECTed it

## Best checkpoint

**Mango-v0.1** (Qwen/Qwen3-1.7B + unmerged T3 adapter
`training/adapters/sciencemath-v0.1-t3`), measured on
mango-eval-core-v1: overall 0.5695 / math 0.6774 / science 0.5400 /
extraction 0.9868.

## Mango-v0.2 promotion (T6.28)

**NOT PROMOTED — REJECTED by pre-declared gates.**

- L1 training measured: 850 train / 39 val, 108 steps, 2 epochs @ 5e-5
  (exactly as declared), final train loss 0.2834, best eval loss 0.2295,
  964.9 s, peak VRAM 4.72 GB
- L1 core eval: −16.6 pp overall, −22.6 pp math_macro, −33.3 pp
  compositional, −25.0 pp cross_domain — far beyond the 5 pp gates
- Failure characterization: the concise-format fine-tune overwrote
  careful multi-step arithmetic. Examples: boxed answer 14400 vs its own
  prose 1440; 150×2⁸ computed as 12000; "12 − 8 = 12". Trained tracks
  improved (biology 6/10→8/10, earth_space 1/8→3/8) while
  arithmetic-heavy categories collapsed (algebra 12/12→7/12, physics
  5/12→2/12)
- Per `configs/curriculum.yaml` ("levels may stop early if a gate
  fails"), no further curriculum levels were trained: L2–L8 from the same
  parent with the same corpus style would repeat the damage with no
  supporting evidence
- Formal decision recorded: `training/curriculum/promotion_log.jsonl`
  entry 1 = REJECT, violated gates [overall, math_macro, cross_domain,
  compositional]; Pareto front contains both checkpoints (neither
  dominates), balanced_best = mango-v0.1;
  `evaluations/t6/core_results/mango-v0.2-L1/gate_decision.json`

## Tests (T6.29)

- New: `tests/test_curriculum_core.py` — 31 tests green (taxonomy,
  matrix, levels, generators, replay, gates, Pareto, decomposition,
  routing metrics, counterfactuals + scoring, failure memory, eval-core
  schema/freeze/contamination, corpus integrity, v1 immutability)
- Full suite exact count: see `## Tests` in the session report /
  pytest output captured at closure (exact summary recorded below)

**EXACT PYTEST SUMMARY (2026-09-04, closure):**
`pytest tests/` → **591 passed, 0 failed, 0 errors, 0 skipped**
(12.8 s; junitxml `artifacts/t6_final_tests.xml`; T6.0 floor was 560
passing — 31 new curriculum tests added, all historical tests intact)

## Weaknesses (measured)

1. **Uncertainty signaling: 0.0000** on both checkpoints (0/8
   INSUFFICIENT_INFO items) — the model never declines to answer
2. **Counterfactual robustness 0.4828** — distractors derail ~half of
   simple quantitative questions
3. **Curriculum-style SFT regresses general math capability** at this
   scale (1.7 B, 6 GB): 889 terse-format examples × 2 epochs damaged
   arithmetic fidelity and multi-step reasoning more than it added
   knowledge
4. General-domain token share structurally under target at L1 (0.026 vs
   0.15) — no general-domain corpus exists in the project yet
5. Self-correction is net harmful at baseline (correction 0.092 <
   overcorrection 0.154); L1 made it worse (0.022)
6. Structured plan emission (decomposition schema): JSON-valid 0.10 —
   the small checkpoint cannot follow plan-format instructions zero-shot

## Ready for T7?

**YES — with Mango-v0.1.** T6 formally closes PARTIAL with all
infrastructure validated (entry gate PASS: 560/560 tests, tools, RAG,
checksums; 31 new curriculum tests; frozen suites verified). The
checkpoint decision is explicit: Mango-v0.1 retained. T7's executive
layer does not depend on a v0.2 promotion; its matched-baseline design
(T7.33) compares the same checkpoint with the executive layer on/off.

STOP — T6 closed. No T8+ work started.