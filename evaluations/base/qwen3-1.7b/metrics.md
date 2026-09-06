# Evaluation metrics — qwen3-1.7b

*Questions:* 188  
*Overall accuracy:* 0.6543  
*Macro category accuracy:* 0.5406  
*Math macro:* 0.49  
*Science macro:* 0.85  

| metric | value |
|---|---|
| correct | 123 |
| extraction_success_rate | 0.7979 |
| invalid_response_rate | 0.1968 |
| refusal_rate | 0.0106 |
| avg_latency_s | 220.411 |
| median_latency_s | 139.474 |
| avg_input_tokens | 84.9 |
| avg_output_tokens | 2106.0 |
| peak_vram_bytes | 2284549632 |
| model_load_vram_bytes | 2284549632 |

## Per-category accuracy

| category | accuracy |
|---|---|
| algebra | 0.4 |
| arithmetic | 0.85 |
| general_science | 0.85 |
| geometry | 0.4 |
| instruction_following | 0.9 |
| probability_statistics | 0.4 |
| trigonometry_precalculus | 0.4 |
| uncertainty_calibration | 0.125 |

## Failure counts

- EXTRACTION_FAILURE: 37
- REFUSAL: 2
- TRUNCATED_OUTPUT: 5
- WRONG_ANSWER: 21
