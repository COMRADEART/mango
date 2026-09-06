# Evaluation metrics — qwen2.5-math-1.5b-instruct

*Questions:* 188  
*Overall accuracy:* 0.6064  
*Macro category accuracy:* 0.5271  
*Math macro:* 0.62  
*Science macro:* 0.4167  

| metric | value |
|---|---|
| correct | 114 |
| extraction_success_rate | 0.9415 |
| invalid_response_rate | 0.0532 |
| refusal_rate | 0.0053 |
| avg_latency_s | 26.26 |
| median_latency_s | 20.94 |
| avg_input_tokens | 104.9 |
| avg_output_tokens | 393.0 |
| peak_vram_bytes | 1219921920 |
| model_load_vram_bytes | 1179743232 |

## Per-category accuracy

| category | accuracy |
|---|---|
| algebra | 0.775 |
| arithmetic | 0.925 |
| general_science | 0.4167 |
| geometry | 0.5 |
| instruction_following | 0.7 |
| probability_statistics | 0.5 |
| trigonometry_precalculus | 0.4 |
| uncertainty_calibration | 0.0 |

## Failure counts

- EXTRACTION_FAILURE: 10
- REFUSAL: 1
- TRUNCATED_OUTPUT: 2
- WRONG_ANSWER: 61
