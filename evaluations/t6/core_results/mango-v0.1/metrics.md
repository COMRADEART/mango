# Evaluation metrics — mango-v0.1

*Questions:* 151  
*Overall accuracy:* 0.5695  
*Macro category accuracy:* 0.5481  
*Math macro:* 0.7  
*Science macro:* 0.5292  

| metric | value |
|---|---|
| correct | 86 |
| extraction_success_rate | 0.9868 |
| invalid_response_rate | 0.0132 |
| refusal_rate | 0.0 |
| avg_latency_s | 14.161 |
| median_latency_s | 8.085 |
| avg_input_tokens | 82.0 |
| avg_output_tokens | 121.3 |
| peak_vram_bytes | 2284549632 |

## Per-category accuracy

| category | accuracy |
|---|---|
| algebra | 1.0 |
| biology | 0.6 |
| calculus | 0.8 |
| chemistry | 0.6 |
| earth_space | 0.125 |
| geometry | 0.5 |
| interdisciplinary | 0.5 |
| math_foundation | 0.6667 |
| mixed_quantitative | 0.625 |
| physics | 0.4167 |
| probability_statistics | 0.5 |
| retrieval_routing | 0.2857 |
| scientific_reasoning | 0.9 |
| tool_routing | 0.75 |
| trig | 0.5 |
| uncertainty_calibration | 0.0 |

## Failure counts

- EXTRACTION_FAILURE: 2
- TRUNCATED_OUTPUT: 4
- WRONG_ANSWER: 59
