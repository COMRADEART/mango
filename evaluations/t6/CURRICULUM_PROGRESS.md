# T6 Curriculum Progress Dashboard (Mango)

**Rule (T6.27): this dashboard reports MEASURED values only.** No
projected, extrapolated, or estimated numbers appear here. Every value
names the artifact it was read from. Updated: 2026-09-04.

## Milestone status

| Sub-milestone | Status | Evidence |
|---|---|---|
| T6.0 entry gate | PASS — T6 UNBLOCKED | `evaluations/t6_entry_gate.json` (560/560 tests, all frozen checksums OK, adapter active, tools OK, RAG OK) |
| T6.1 capability taxonomy + matrix | DONE | `src/sciencemath/curriculum/capabilities.py` (81 tracks, 7 families); `evaluations/t6/capability_matrix_initial.json` |
| T6.2/T6.3 mango-eval-core-v1 | FROZEN | `evaluations/eval-core/v1/` — 151 questions, 16/16 categories, checksums verified, contamination 0 flags vs training corpora + frozen suites |
| T6.4 mango-sft-v2 | STAGE 1 FROZEN | `training/curriculum/mango-sft-v2/level1/` (checksums verified); frozen `sciencemath-sft-v1` untouched |
| T6.5 eight curriculum levels | DECLARED | `src/sciencemath/curriculum/levels.py` (L1–L8, validated) |
| T6.6 verified examples | ENFORCED | generators: T4 parse gate + tool cross-check (3 seeds, 175/175); authored science: 176/176 verbatim corpus grounding + verifier review (4 dropped) |
| T6.7 difficulty scale 1–5 | ENFORCED | per-level difficulty ranges; per-track ranges in taxonomy |
| T6.8 token mixture | MEASURED (L1) | see below |
| T6.9 replay buffer | DONE | 135/889 L1 records (15.2%); composition in `replay_report.json` |
| T6.10 promotion protocol | READY | `training/curriculum/promotion_log.jsonl` (empty — no curriculum checkpoint evaluated yet) |
| T6.11 pre-declared gates | FROZEN | `configs/curriculum.yaml` (9 absolute-pp dimensions) |
| T6.12 Pareto checkpointing | READY | `curriculum.gates` (8-dimension vectors, dominance, balanced_best) |
| T6.13 concise reasoning format | ENFORCED | `Answer: \boxed{...}` + short visible steps in all generated target responses |
| T6.14 decomposition schema | BUILT | `curriculum.decomposition.py` + strategy eval arm (not yet run on a checkpoint) |
| T6.15 routing metrics | BUILT | `curriculum.routing.py` + deterministic route arm in `scripts/run_core_eval.py` |
| T6.16 strategy generalization | MEASURED (baseline) | `evaluations/t6/strategy_results/mango-v0.1/` — decomposition JSON-valid 0.10, routing agreement 0.0 |
| T6.17 counterfactual testing | FROZEN + MEASURED (baseline) | suite `evaluations/t6/counterfactual/v1/` (145 variants, checksums verified); baseline pass 0.4828 |
| T6.18 self-correction eval | MEASURED (baseline) | correction 0.092 / overcorrection 0.154 (net harmful at baseline) |
| T6.19 failure memory | BUILT + ARMED | `training/curriculum/failure_memory.jsonl` (populated by core eval; 11 error types) |
| T6.20 dry runs | DONE (T3 protocol) | T3 dry run in entry gate; per-stage dry run wired into `scripts/run_curriculum_stage.py` |
| T6.21 unified adapter | WIRED | stage training initializes LoRA from parent adapter (`train.run_training(init_from_adapter=...)`) |
| T6.22 artifact layout | WIRED | `training/curriculum/mango-v0.2/levelN/`, `training/adapters/mango-v0.2-LN` |
| T6.23 science factual protection | CONFIGURED | `science_factual_protection` in curriculum.yaml; grounding gates active |
| T6.24 tool protection | PRESERVED | 0 false-PASS tolerance unchanged; tool_check re-verification in eval-core build |
| T6.25 retrieval protection | PRESERVED | T5R firewall untouched; frozen rag eval rerun required for promotion |
| T6.26 efficiency metrics | TRACKED | per-stage training summaries (VRAM, time, examples) |
| T6.27 this dashboard | LIVE | this file |
| T6.28 Mango-v0.2 promotion | **REJECTED — v0.1 retained** | promotion_log.jsonl entry 1: decision REJECT, violated gates [overall, math_macro, cross_domain, compositional]; Pareto balanced_best = mango-v0.1; T6 = PARTIAL |
| T6.29 tests | 31/31 curriculum-core green | full-suite exact count captured at closure (see T6_FINAL_REPORT.md) |

## mango-eval-core-v1 (frozen 2026-09-04, before first curriculum training)

- 151 questions; all 16 categories (7–12 each); splits IID 98 /
  COMPOSITIONAL 18 / OUT_OF_TEMPLATE 23 / CROSS_DOMAIN 12; routing labels
  TOOL 83 / RETRIEVAL 21 / BOTH 2 / NONE 36 / INSUFFICIENT_INFO 9
- Build: 8 author agents + adversarial verifier agents (workflow
  wf_32e82c1d-a6f); 152 authored, 151 kept, 1 excluded (answer leaked in
  question stem); 0 contamination flags
- Suite lives outside all training corpora; re-checked at every corpus
  freeze

## Checkpoint results on mango-eval-core-v1

| Checkpoint | overall | math_macro | science_macro | cross_domain | compositional | tool_routing | retrieval_routing | extraction | uncertainty | status |
|---|---|---|---|---|---|---|---|---|---|---|
| mango-v0.1 (baseline) | 0.5695 | 0.6774 | 0.5400 | 0.5000 | 0.6667 | 0.7425 | 0.5644 | 0.9868 | 0.0000 | gate baseline (closed-book 151/151 graded; RAG arm 0.2609 on 23 items, 0 fabricated citations) |
| mango-v0.2-L1 | 0.4040 | 0.4516 | 0.5200 | 0.2500 | 0.3333 | 0.7425 | 0.5644 | 1.0000 | 0.0000 | **REJECTED** (gates: overall −16.6pp, math −22.6pp, compositional −33.3pp, cross_domain −25pp vs 5pp limits; RAG 0.2174, 0 fabricated) |

(Row fills from `evaluations/t6/core_results/<label>/metrics.json` when
each eval completes. No value is entered before it is measured.)

## Strategy evals (T6.14/T6.18, frozen suite subsets)

| Checkpoint | decomp JSON-valid | decomp schema-valid | decomp routing agree | correction rate | overcorrection rate |
|---|---|---|---|---|---|
| mango-v0.1 (baseline) | 0.10 (n=20) | 0.10 | 0.00 | 0.092 (of 65 wrong) | 0.154 (of 65 sampled correct) |
| mango-v0.2-L1 | 0.00 (n=20) | 0.00 | n/a | 0.022 (of 90 wrong) | 0.213 (of 61 sampled correct) |

(Read from `evaluations/t6/strategy_results/<label>/metrics.json`.)

## Counterfactual robustness (T6.17, frozen suite)

| Checkpoint | overall pass | add_distractor (n=95) | change_value (n=49) | alter_unit (n=1) |
|---|---|---|---|---|
| mango-v0.1 (baseline) | 0.4828 | 0.5053 | 0.4286 | 1.0 |
| mango-v0.2-L1 | 0.2414 | 0.2737 | 0.1633 | 1.0 |

(Read from `evaluations/t6/counterfactual/results/<label>/metrics.json`.
Pass = model answer behaves as the perturbation demands: distractor
ignored / value sensitivity / unit sensitivity.)

## Level 1 stage corpus (mango-sft-v2, frozen)

- 889 examples: 754 new (615 deterministic generated + 139 authored
  science) + 135 replay from frozen sciencemath-sft-v1 (15.2%)
- 11 tracks, 58–70 examples each (`domain_distribution.json`)
- Contamination vs eval-core-v1 + suite-v1: 0 flags
- Token mixture (measured, Qwen tokenizer): mathematics 0.564 /
  sciences 0.410 / general 0.026 vs targets 0.50/0.35/0.15
  → **measured deviation**: general 12.4pp under target; math/science
  ratio 1.37. Recorded, not silently accepted (T6.8 requires tracked
  composition; the shortfall is structural — no general-domain corpus at
  L1; watch at L2).

## Level 1 training (mango-v0.2-L1, measured)

- Dry run (T6.20): PASS after lineage-config fix (see issues log); real
  run: 850 train / 39 val examples, 108 steps, 2 epochs
- final_train_loss 0.2834; best_eval_loss 0.2295; train_time 964.9 s
- peak VRAM 4.72 GB (RTX 4050 6 GB, micro-batch 1)
- adapter `training/adapters/mango-v0.2-L1` — LoRA seeded from parent
  `training/adapters/sciencemath-v0.1-t3` (unified adapter lineage, T6.21)

## Environment (measured at entry gate)

- RTX 4050 Laptop 6 GB; Qwen3-1.7B 4-bit NF4; micro-batch 1 (T3 protocol)
- T3 measured throughput ~0.72 s/example-epoch → L1 (889 ex × 2 epochs)
  expected ≈ 21 min GPU (projection, not a measured result — the
  measured value will be recorded in the L1 training summary)

## Failures / issues log

- L1 dry run (T6.20) caught a real blocker on its first run: the
  parent-adapter lineage check compared `target_modules` as ORDERED
  lists — the T3 adapter and the stage config list the same 7 modules in
  different order → false mismatch. Fixed to an order-independent
  comparison; stage relaunched (the dry run did its job: nothing trained
  against a mismatched config)
- `run_core_eval.py` first run crashed in post-processing (make_record
  required `verification_evidence`); closed-book predictions were intact,
  routing+RAG arms re-run with `--skip-closed-book` (deterministic + 85 s)
  — no GPU work repeated
- Baseline uncertainty dimension measured 0.0000 (0/8): the model never
  signals insufficient information — largest single capability gap found
  on the frozen suite
- Baseline RAG accuracy 0.2609 on 23 retrieval/BOTH items (0 fabricated
  citations) — retrieval grounding intact, answer extraction weak
- Baseline counterfactual pass rate 0.4828 — the model is distracted by
  irrelevant sentences half the time and misses value changes 57% of the
  time (change_value requires BOTH the recomputed answer AND that the
  answer actually changed)
- `run_strategy_evals.py` crashed on `CORRECTION_INSTRUCTION.format()`
  (literal \boxed{...} braces interpreted as format fields); fixed with a
  literal `.replace()` — strategy arm re-run
- Generation smoke quirk (entry gate): terse-prompt generation answered
  "1" not "180" (greedy decoding quirk on a 0-shot terse prompt; not
  gated, recorded in t6_entry_gate.json notes)
- Authored science records dropped by verifier review: 4/180 (wrong
  answer vs question, unresolved quote referent, 2 over-long answers)
- eval-core: 1 item rejected by adversarial verifier (answer leaked in
  question stem); 17 items needed recorded track remaps into the frozen
  taxonomy