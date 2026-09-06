# Evaluation metrics — qwen3-1.7b+t3

*Questions:* 188  
*Overall accuracy:* 0.5638  
*Macro category accuracy:* 0.4333  
*Math macro:* 0.34  
*Science macro:* 0.7667  

| metric | value |
|---|---|
| correct | 106 |
| extraction_success_rate | 0.9362 |
| invalid_response_rate | 0.0638 |
| refusal_rate | 0.0 |
| avg_latency_s | 20.487 |
| median_latency_s | 8.791 |
| avg_input_tokens | 88.9 |
| avg_output_tokens | 170.9 |
| peak_vram_bytes | 2284549632 |

## Per-category accuracy

| category | accuracy |
|---|---|
| algebra | 0.325 |
| arithmetic | 0.775 |
| general_science | 0.7667 |
| geometry | 0.2 |
| instruction_following | 1.0 |
| probability_statistics | 0.2 |
| trigonometry_precalculus | 0.2 |
| uncertainty_calibration | 0.0 |

## Failure counts

- EXTRACTION_FAILURE: 12
- TRUNCATED_OUTPUT: 4
- WRONG_ANSWER: 66
