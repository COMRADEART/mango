# T2 SELECTION DECISION

*Generated:* 2026-09-02T20:27:35.893279+00:00

## Recommendation

**Qwen/Qwen3-1.7B**

- decision rule: highest primary_macro (math+science macro)
- leader: Qwen/Qwen3-1.7B (primary_macro=0.67)
- runner-up: Qwen/Qwen2.5-Math-1.5B-Instruct (margin=0.1517)
- tie-break support: None

## Factors considered (evidence in comparison.json rows)

- math accuracy, science accuracy, and their balance (primary_macro = mean of the two macro accuracies; NEITHER is optimized alone)
- extraction/reliability: extraction success, extraction failures, truncations, refusals (see per-row reliability columns)
- context length (T5 Wikipedia RAG needs headroom over the 188-question prompts)
- inference latency and token cost (median latency, avg output tokens per row)
- VRAM (4-bit NF4 load recorded per run; 6 GB RTX 4050 constraint)
- future QLoRA feasibility (base size and 4-bit load footprint)
- licensing (per evaluations/model_manifest.json; gate-enforced)
- operational stability (resume-safe runs, per-record flush, verified recomputation from saved predictions)
- suitability as SFT SUBSTRATE, not just untouched baseline score: a general model with weaker baseline math may still be the better T3 base if science capability is materially stronger, output reliability is acceptable, and math is plausibly improvable via SFT

## Secondary diagnostic (NOT selectable)

- `Qwen/Qwen3-1.7B` non-thinking run (variant=non_thinking) is a reliability/capability decomposition diagnostic only. It is reported in the comparison but excluded from recommendation eligibility because it is the same model as the primary A run.
- Purpose: separate actual math/science capability from reasoning-protocol output-closure reliability (A thinking mode had 36/37 extraction failures caused by the 4096-token budget exhausting the think block, plus 5 taxonomically-TRUNCATED_OUTPUT rows — 41/188 total budget-exhausted).
- Measured non-thinking diagnostic result (read from its metrics.json, reported for decomposition only): overall=0.6862, math_macro=0.585, science_macro=0.7667, extraction=0.9681. It is NEVER merged with the thinking primary and is not selectable.

## Eligibility / exclusion notes
- Qwen/Qwen2.5-3B-Instruct is EXCLUDED (license `qwen-research`, verified 2026-08-31; requires legal review).
- Qwen/Qwen3-4B-Instruct-2507 is a stretch candidate, NOT run automatically (unverified license flag in model manifest; memory fit for 6 GB VRAM requires dry-run validation).
- Candidate C (Qwen2.5-1.5B-Instruct) is optional and was only ranked if its run exists.

## Evidence

- `evaluations/base/<slug>/manifest.json` per-run status and config
- `evaluations/base/<slug>/metrics.json` measured metrics
- `evaluations/base/comparison.json` machine-readable comparison
- `evaluations/suite/v1/checksum.json` frozen suite integrity

## Limitations recorded

- Small frozen suite (~180 questions): treat category numbers as directional, not publishable point estimates.
- Deterministic scoring only; no symbolic equivalence (T4 adds the SymPy verifier).
- A single sampled run for Qwen3 thinking mode with seed 42; variance across seeds is not yet measured.

Status: RECOMMENDATION - becomes binding only via --commit into configs/model.yaml.
