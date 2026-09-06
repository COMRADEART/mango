# Evaluation metrics — mango-v0.1

*Questions:* 145  
*Overall accuracy:* 0.4828  
*Macro category accuracy:* 0.456  
*Math macro:* 0.4577  
*Science macro:* 0.4996  

| metric | value |
|---|---|
| correct | 70 |
| extraction_success_rate | 0.9931 |
| invalid_response_rate | 0.0069 |
| refusal_rate | 0.0 |
| avg_latency_s | 11.298 |
| median_latency_s | 9.318 |
| avg_input_tokens | 88.1 |
| avg_output_tokens | 112.1 |
| peak_vram_bytes | 2284549632 |

## Per-category accuracy

| category | accuracy |
|---|---|
| algebra | 0.75 |
| biology | 0.8 |
| calculus | 0.4444 |
| chemistry | 0.5455 |
| earth_space | 0.0 |
| geometry | 0.3636 |
| interdisciplinary | 0.375 |
| math_foundation | 0.65 |
| mixed_quantitative | 0.5714 |
| physics | 0.2778 |
| probability_statistics | 0.2727 |
| tool_routing | 0.4615 |
| trig | 0.4167 |

## Failure counts

- EXTRACTION_FAILURE: 1
- TRUNCATED_OUTPUT: 1
- WRONG_ANSWER: 73
