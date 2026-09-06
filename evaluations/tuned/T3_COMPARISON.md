# T3 BASE vs TUNED COMPARISON

*Generated:* 2026-09-03T05:20:22.897102+00:00

- Base reference: `qwen3-1.7b_non_thinking` (T2 non-thinking diagnostic — the declared reference baseline; NOT merged with the thinking run)
- Tuned: `sciencemath-v0.1-t3` (Qwen3-1.7B + T3 LoRA adapter, unmerged)
- Same frozen suite (sciencemath-eval-v1, 188 questions), same generation protocol, deterministic scoring.

## Headline metrics

| metric | base | tuned | delta (pp) |
|---|---|---|---|
| Overall accuracy | 68.62% | 56.38% | -12.24 |
| Math macro | 58.50% | 34.00% | -24.5 |
| Science macro | 76.67% | 76.67% | 0.0 |
| Primary macro (math+science) | 61.53% | 41.11% | -20.42 |
| Extraction success | 96.81% | 93.62% | -3.19 |
| Invalid outputs | 3.19% | 6.38% | 3.19 |
| Refusals | 0.00% | 0.00% | 0.0 |

## Per-category accuracy (delta in percentage points)

| category | base | tuned | delta |
|---|---|---|---|
| algebra | 62.50% | 32.50% | -30.0 |
| arithmetic | 90.00% | 77.50% | -12.5 |
| general_science | 76.67% | 76.67% | 0.0 |
| geometry | 50.00% | 20.00% | -30.0 |
| instruction_following | 70.00% | 100.00% | 30.0 |
| probability_statistics | 50.00% | 20.00% | -30.0 |
| trigonometry_precalculus | 40.00% | 20.00% | -20.0 |
| uncertainty_calibration | 12.50% | 0.00% | -12.5 |

## Catastrophic forgetting gate

- Result: **PASS**
- Reference science macro: 0.7667
- Tuned science macro: 0.7667
- Drop: 0.0 pp (threshold 5.0 pp, declared in configs/training.yaml before evaluation)
