# Evaluation metrics — qwen3-1.7b_non_thinking

*Questions:* 188  
*Overall accuracy:* 0.6862  
*Macro category accuracy:* 0.5646  
*Math macro:* 0.585  
*Science macro:* 0.7667  

| metric | value |
|---|---|
| correct | 129 |
| extraction_success_rate | 0.9681 |
| invalid_response_rate | 0.0319 |
| refusal_rate | 0.0 |
| avg_latency_s | 32.294 |
| median_latency_s | 24.483 |
| avg_input_tokens | 88.9 |
| avg_output_tokens | 365.8 |
| peak_vram_bytes | 2284549632 |
| model_load_vram_bytes | 2284549632 |

## Per-category accuracy

| category | accuracy |
|---|---|
| algebra | 0.625 |
| arithmetic | 0.9 |
| general_science | 0.7667 |
| geometry | 0.5 |
| instruction_following | 0.7 |
| probability_statistics | 0.5 |
| trigonometry_precalculus | 0.4 |
| uncertainty_calibration | 0.125 |

## Failure counts

- EXTRACTION_FAILURE: 6
- TRUNCATED_OUTPUT: 12
- WRONG_ANSWER: 41
