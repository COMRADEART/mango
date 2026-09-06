# T2 BASELINE COMPARISON

*Generated:* 2026-09-02T20:27:35.893279+00:00  
*Suite:* sciencemath-eval-v1 (frozen)  
*Rule:* every number below is read from measured artifacts in `evaluations/base/<slug>/metrics.json`; nothing is quoted from papers or model cards.

| candidate | model (mode — role) | status | overall | math macro | science macro | primary macro | extraction | invalid/refusal | extr.fail/trunc | med latency s | avg out tok |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | Qwen/Qwen3-1.7B — THINKING — PRIMARY | COMPLETE | 0.6543 | 0.4900 | 0.8500 | 0.6700 | 0.7979 | 0.1968/0.0106 | 37/5 | 139.4740 | 2106.0000 |
| B | Qwen/Qwen2.5-Math-1.5B-Instruct — PRIMARY COMPARATOR | COMPLETE | 0.6064 | 0.6200 | 0.4167 | 0.5183 | 0.9415 | 0.0532/0.0053 | 10/2 | 20.9400 | 393.0000 |
| A:non_thinking | Qwen/Qwen3-1.7B — NON-THINKING — SECONDARY DIAGNOSTIC | COMPLETE | 0.6862 | 0.5850 | 0.7667 | 0.6759 | 0.9681 | 0.0319/0.0000 | 6/12 | 24.4830 | 365.8000 |

The two Qwen3-1.7B rows are the SAME model in different generation modes; they are reported separately and never combined. The non-thinking row is a reliability diagnostic, NOT a selectable base and NOT a replacement for the primary.

## Caveats recorded with this baseline

- 4-bit NF4 quantized inference (recorded per run in `model_metadata.json`); base weights untouched, no LoRA/train.
- Scoring is deterministic string/numeric matching only; no LLM judging, no symbolic equivalence checking (T4 SymPy verifier arrives later).
- Categories with count 0 in the suite are excluded from macro averages and marked INSUFFICIENT_VERIFIED_EVAL_DATA in the suite manifest.
- Qwen3-1.7B runs in thinking mode with seeded sampling (temp 0.6 / top_p 0.95 / top_k 20, seed 42); Qwen2.5-Math greedy. Modes are recorded per run and never compared as identical protocols.

## Recommendation (deterministic rules, see file header)

- `recommendation`: **Qwen/Qwen3-1.7B**
- `decision_rule`: highest primary_macro (math+science macro)
- `margin`: 0.1517
- `tie_break_support`: None

This is a recommendation; commit it with `python scripts/compare_baseline.py --commit` which fills `configs/model.yaml` selected.model_id.
