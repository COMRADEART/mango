# MANGO T33 VERIFIED DERIVATION REPORT

## Status

FAIL — REGRESSION. `MANGO_T33_VERIFIED_DERIVATION_FAIL`

## T32 baseline

T32 is closed as MANGO_T32_MATH_REMEDIATION_FAIL. Historical generations, prompts, scorer, membership, runtime and evidence remain byte-identical to the T33 entry snapshot. Base/T30/T32 final columns reuse the frozen, item-paired historical scored generations; only T33 final generations are fresh. This is the same reuse methodology documented in T32, not a fresh rerun of historical models.

## Entry audit

The historical report’s Final model identities block is the T31 baseline identity. T32’s selected adapter identity is separate. T32 closure was uncommitted/untracked at entry: no final closure commit exists. The last committed tip and exact closure-file hashes are recorded below, rather than inventing a final commit.

```json
{
  "t31_final_commit": "5a646aec4205a21ad83de7d07f7a63fbbce98b0c",
  "t32_branch": "t32-math-remediation",
  "t32_final_committed_tip": "9aa8072bdd22de0f5c1c2a3149354103ded3139d",
  "t32_final_commit": null,
  "t32_final_commit_explanation": "T32 closure is present as dirty/untracked evidence at this tip; no commit containing the final closure exists. The source snapshot and file hashes identify its actual final state.",
  "t32_selected_candidate": "t32-A",
  "t32_adapter_sha256": "64c2787f3457526ccd5aee571a0c106b8dc67b820886260714d3f55169318acb",
  "t32_training_receipt_sha256": "0471232acaf14f31d318241dcfdf4e75424cb46561c2b61852c017f6f0aded36",
  "t32_final_report_sha256": "87ed997c4932642df3bb172ff4083697e491e87861ee2e5c1a69885624300fa2",
  "report_identity_explanation": "The Final model identities block references the frozen T31 baseline. Its branch, final_commit and report_sha256 are T31 identities; the separately stated T32 adapter SHA is the T32 model identity.",
  "historical_outputs_modified": false
}
```

The two new/unclassified IDs were test_concurrent_observations_lose_nothing_and_never_mix and test_the_event_log_never_gains_a_torn_line. Both and the two unresolved closure concurrency IDs were reproduced with Windows state_index.json PermissionError. The State Engine and tests are pre-T33 untracked WIP absent from both historical commits; commit-level source equality cannot be established. Frozen T31 failure IDs, T32 traces, entry source hashes and fresh focused JUnit reports provide the classification evidence. No State Engine redesign was performed. See entry/REGRESSION_CLASSIFICATION.json and SOURCE_COMPARISON.json.

## Dataset

1,069 independently exact-checked math problems across all 16 required families; 224 explicitly incorrect/corrected repair pairs; 300 source-gold SciQ direct-response records. Source pool contained 1,152 math candidates: 83 near-development duplicates were removed. Direct factual records rely on legitimate training-source gold labels; they are not claimed to have arithmetic verification.

A has 1,593 training presentations. B/C each have 1,893; Stage D repeats 300 identical verified derivations, and B/C additionally interleave 300 direct science records. One sequential curriculum pass is used for each candidate, with uninterrupted optimizer/scheduler across stages. Detailed per-family character/token median, p75, p90, p95 and maximum are in development/lengths_A.json, lengths_B.json and lengths_C.json and every training receipt. No target clipping, premise shortening or dropped-overlength record occurred.

Family counts (unique verified math):

```json
{
  "arithmetic": 72,
  "fractions": 61,
  "percentages": 70,
  "ratios": 72,
  "rates": 72,
  "multi-step word problems": 72,
  "linear equations": 71,
  "systems of equations": 72,
  "algebraic manipulation": 72,
  "sequences": 71,
  "geometry": 70,
  "probability": 65,
  "counting": 72,
  "number theory": 55,
  "basic combinatorics": 32,
  "competition-style algebra": 70
}
```

## Derivation supervision

The assistant target numbers each state update, displays its exact expression and value, includes an explicit verification reminder, then closes with Final answer: \boxed{value}. Prompt tokens are masked; all response tokens carry ordinary causal cross-entropy loss. Repair examples put the deliberately wrong proposal in the user prompt and supervise only the diagnosis and corrected derivation. This is correction SFT, not a preference/DPO loss. All mathematical equations and endpoints are re-evaluated exactly; selected families also use independent equation solving, combinatorial counts or equivalent identities.

```text
Find the number of positive divisors of 2^9 * 3^7, then exclude the divisor 1. How many remain?
Show a concise explicit derivation: retain the premises, update each intermediate state, verify the result, then give the final answer.

ASSISTANT:
1. Count independent exponent choices including zero: (9+1)*(7+1) = 80
2. Remove the specified divisor: 80-1 = 79
Check: each state uses the previous updated value; exact operations agree with the requested endpoint.
Final answer: \boxed{79}
```

## Output-mode decoupling

B/C add natural-language task instructions requesting retained premises, updated intermediate states and a verified endpoint for derive examples. Direct MC prompts request one correct option letter with no derivation; assistant targets contain only that letter. Stage D alternates derivation and direct science records. No runtime routing, hidden-chain product dependency, new special token, final prompt change or scorer change is introduced. A uses natural math/correction prompts and no direct science replay.

## Candidate A/B/C

| Candidate | LR | Records | Steps | Train seconds | Adapter SHA-256 |
|---|---:|---:|---:|---:|---|
| A | 0.0001 | 1593 | 100 | 1184.8 | bdb6752d9fe9da1f047cac4cd03d6cbd7036b39007db9f4967106b8f980e7b0b |
| B | 0.0001 | 1893 | 119 | 1768.1 | fbe3e1256b32614be8788822925ecab08d990073d20a109f4cc377b85b5d6938 |
| C | 3e-05 | 1893 | 119 | 1946.9 | 057ae900f7b951fd6d4d8eba4101830f2951b545da5bd8a8a3c6d8e3259d7614 |

Qwen3-1.7B pinned revision; T32-A starting LoRA; rank 32, alpha 64, dropout .05, q/k/v/o/gate/up/down; NF4 double quantization, bf16; sequence 2048, batch 1, accumulation 16, seed 42, AdamW, cosine scheduler, 3% warmup, gradient clipping 1.0. C changes only LR from 1e-4 to 3e-5. A/B’s extra MC rows increase total steps; this is explicitly disclosed rather than presented as equal compute.

An isolated three-step longest-example feasibility test verified memory/throughput before the valid full run. Its exact duration and peak allocation are in FEASIBILITY.json. Full training memory/throughput, dataset hashes, base weight hashes, checkpoint files, complete configs, loss history, environment and resume history are recorded per candidate. No model-only resume is treated as equivalent training. The initial unfinished A attempt was invalidated before development measurement because correction pairs did not isolate the stated error taxonomy. Old data/protocol/logs/checkpoints are preserved; the valid candidate restarted entirely from T32-A with fresh optimizer/scheduler/RNG. See invalid-corpus-v1/INVALIDATION.json.

| Development suite | T32-A | T33-A | T33-B | T33-C |
|---|---:|---:|---:|---:|
| gsm-style | 63.54 | 47.92 | 47.92 | 51.04 |
| competition-style | 37.50 | 21.88 | 27.08 | 33.33 |
| ARC-style MC | 90.62 | 78.12 | 87.50 | 71.88 |
| ARC-Challenge-style MC | 78.12 | 64.06 | 79.69 | 56.25 |
| SciQ-style MC | 90.62 | 81.25 | 85.42 | 77.08 |
| math-short | 60.42 | 66.67 | 52.08 | 50.00 |
| math-medium | 43.75 | 50.00 | 41.67 | 20.83 |
| math-long | 25.00 | 10.42 | 14.58 | 6.25 |

## Candidate selection

The 560-item development membership and selection rules were frozen before candidate results: +5 pp independently on GSM-style and competition-style versus T32-A; strictly positive short/long math deltas; each MC suite within -2 pp versus T32-A; invalid output <=5% per suite; clean contamination and regressions. Ranking uses the minimum of the two math deltas, then long-math accuracy, then lower invalid-output fraction, then A/B/C order. No final test result enters selection. If none eligible, the predeclared diagnostic fallback selects exactly one but cannot earn PASS.

```json
{
  "selected": "t33-C",
  "selected_eligible": false,
  "selection_type": "DIAGNOSTIC_INELIGIBLE_FALLBACK",
  "protocol_sha256": "368a7c8f5ac87223ad2adc1fe8d3b4f7ae86c4a3ab11e896728d8cebbf9ae31e",
  "candidates": {
    "t33-A": {
      "eligible": false,
      "checks": {
        "gsm_material": false,
        "competition_material": false,
        "short_improves": true,
        "long_improves": false,
        "arc_easy_preserved": false,
        "arc_challenge_preserved": false,
        "sciq_preserved": false,
        "format": false,
        "contamination": true,
        "t33_regressions": true
      },
      "deltas_pp": {
        "gsm-style": -15.624999999999995,
        "competition-style": -15.625,
        "ARC-style MC": -12.5,
        "ARC-Challenge-style MC": -14.0625,
        "SciQ-style MC": -9.375,
        "math-short": 6.25,
        "math-medium": 6.25,
        "math-long": -14.583333333333332
      },
      "ranking": [
        -15.625,
        0.10416666666666667,
        -0.048214285714285716,
        -65
      ]
    },
    "t33-B": {
      "eligible": false,
      "checks": {
        "gsm_material": false,
        "competition_material": false,
        "short_improves": false,
        "long_improves": false,
        "arc_easy_preserved": false,
        "arc_challenge_preserved": true,
        "sciq_preserved": false,
        "format": true,
        "contamination": true,
        "t33_regressions": true
      },
      "deltas_pp": {
        "gsm-style": -15.624999999999995,
        "competition-style": -10.416666666666668,
        "ARC-style MC": -3.125,
        "ARC-Challenge-style MC": 1.5625,
        "SciQ-style MC": -5.2083333333333375,
        "math-short": -8.333333333333325,
        "math-medium": -2.0833333333333313,
        "math-long": -10.416666666666666
      },
      "ranking": [
        -15.624999999999995,
        0.14583333333333334,
        -0.0,
        -66
      ]
    },
    "t33-C": {
      "eligible": false,
      "checks": {
        "gsm_material": false,
        "competition_material": false,
        "short_improves": false,
        "long_improves": false,
        "arc_easy_preserved": false,
        "arc_challenge_preserved": false,
        "sciq_preserved": false,
        "format": false,
        "contamination": true,
        "t33_regressions": true
      },
      "deltas_pp": {
        "gsm-style": -12.5,
        "competition-style": -4.166666666666669,
        "ARC-style MC": -18.75,
        "ARC-Challenge-style MC": -21.875,
        "SciQ-style MC": -13.541666666666663,
        "math-short": -10.416666666666663,
        "math-medium": -22.916666666666664,
        "math-long": -18.75
      },
      "ranking": [
        -12.5,
        0.0625,
        -0.05357142857142857,
        -67
      ]
    }
  },
  "final_results_used_for_selection": false
}
```

## Final identities

Base revision: 70d244cc86ccca08cf5af4e1e306ecf908b1ad5e. Base weight SHA-256 values: {"model-00001-of-00002.safetensors": "169ad53ec313c3a34b06c0809216e4fc072cce444a5d4ff2b59690d064130ed5", "model-00002-of-00002.safetensors": "912becff8d60672aa8628ef08c05898d9adf17c2ad4ae3caf99b065622fdeff9"}. T30 revision ad4bac714e442ca5c9b20420847fcadad61a6123; weights f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668. T32 selected t32-A weights 64c2787f3457526ccd5aee571a0c106b8dc67b820886260714d3f55169318acb. T33 selected t33-C weights 057ae900f7b951fd6d4d8eba4101830f2951b545da5bd8a8a3c6d8e3259d7614. Full selection/data/training/config freeze: SELECTED_FREEZE.json.

## Final benchmark table

| Benchmark | Base | T30 | T32 | T33 | Δ T33 vs T32 | Δ T33 vs T30 | Δ T33 vs Base |
|---|---:|---:|---:|---:|---:|---:|---:|
| GSM8K | 81.05 | 58.38 | 62.40 | 53.68 | -8.72 | -4.70 | -27.37 |
| MATH-500 | 59.80 | 30.40 | 31.80 | 24.60 | -7.20 | -5.80 | -35.20 |
| ARC-Easy | 79.46 | 87.67 | 88.97 | 71.51 | -17.47 | -16.16 | -7.95 |
| ARC-Challenge | 61.60 | 77.30 | 76.54 | 59.81 | -16.72 | -17.49 | -1.79 |
| SciQ | 84.90 | 86.90 | 88.80 | 72.90 | -15.90 | -14.00 | -12.00 |

## Math restoration

Both math benchmarks meet T30 +5 pp and strictly exceed T32: False. Stretch targets GSM8K >=68%: False; MATH-500 >=38%: False. These are endpoint accuracy measurements, not proof-level reasoning claims.

## MC/science preservation

{"arc_easy": false, "arc_challenge": false, "sciq": false}. Floors are assessed separately at T30 -2 pp. T32 deltas are independently displayed above.

## Paired analysis

| Benchmark / reference | Both right | Reference-only right | T33-only right | Both wrong | Δ pp [95% CI] | Exact McNemar p |
|---|---:|---:|---:|---:|---|---:|
| GSM8K / base | 651 | 418 | 57 | 193 | -27.37 [-30.251, -24.487] | 6.57769e-69 |
| GSM8K / t30 | 561 | 209 | 147 | 402 | -4.70 [-7.493, -1.908] | 0.00119436 |
| GSM8K / t32 | 592 | 231 | 116 | 380 | -8.72 [-11.447, -5.991] | 6.59024e-10 |
| MATH-500 / base | 116 | 183 | 7 | 194 | -35.20 [-39.636, -30.764] | 2.1007e-45 |
| MATH-500 / t30 | 79 | 73 | 44 | 304 | -5.80 [-10.01, -1.59] | 0.00934076 |
| MATH-500 / t32 | 92 | 67 | 31 | 310 | -7.20 [-11.029, -3.371] | 0.000354534 |
| ARC-Easy / base | 1480 | 408 | 219 | 269 | -7.95 [-9.995, -5.914] | 3.8749e-14 |
| ARC-Easy / t30 | 1619 | 464 | 80 | 213 | -16.16 [-17.973, -14.351] | 9.12292e-67 |
| ARC-Easy / t32 | 1645 | 469 | 54 | 208 | -17.47 [-19.217, -15.715] | 1.31812e-83 |
| ARC-Challenge / base | 531 | 191 | 170 | 280 | -1.79 [-4.968, 1.384] | 0.292498 |
| ARC-Challenge / t30 | 649 | 257 | 52 | 214 | -17.49 [-20.255, -14.728] | 9.42481e-34 |
| ARC-Challenge / t32 | 659 | 238 | 42 | 233 | -16.72 [-19.353, -14.094] | 2.09979e-34 |
| SciQ / base | 670 | 179 | 59 | 92 | -12.00 [-14.931, -9.069] | 3.07038e-15 |
| SciQ / t30 | 688 | 181 | 41 | 90 | -14.00 [-16.788, -11.212] | 3.51962e-22 |
| SciQ / t32 | 703 | 185 | 26 | 86 | -15.90 [-18.571, -13.229] | 9.47735e-31 |

Paired differences use the established per-item normal 95% interval and exact two-sided binomial McNemar method; no benchmark pooling.

## Reasoning metrics

Each suite separately reports final correctness, output completion, invalid output, truncation, numeric-equation correctness, exact-expression state accuracy, final-answer consistency with an observed final-state equation, and measurement coverage. Output completion means a natural stop with an extractable answer; it does not establish semantic reasoning completion. Final-answer consistency is measured only when the final expected expression is explicitly observed and the extracted endpoint is numeric. The parser only accepts bounded numeric arithmetic; unparseable symbolic work is unmeasured, never silently called correct. Global semantic premise retention and constraint satisfaction are not established by numeric equation matches. See each *_metrics.json and the per-row derivation_audit.

```json
{
  "gsm-style": {
    "n": 96,
    "accuracy": 0.5104166666666666,
    "truncation_fraction": 0.0,
    "invalid_output_fraction": 0.0,
    "completion_fraction": 1.0,
    "numeric_equations_observed": 185,
    "numeric_equation_accuracy": 0.8702702702702703,
    "exact_expression_states_observed": 0,
    "exact_expression_state_accuracy": null,
    "exact_expression_state_coverage": null,
    "final_answer_consistency_observed_count": 0,
    "final_answer_consistency_fraction": null,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 24,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  },
  "competition-style": {
    "n": 96,
    "accuracy": 0.3333333333333333,
    "truncation_fraction": 0.010416666666666666,
    "invalid_output_fraction": 0.0,
    "completion_fraction": 0.9895833333333334,
    "numeric_equations_observed": 64,
    "numeric_equation_accuracy": 0.171875,
    "exact_expression_states_observed": 0,
    "exact_expression_state_accuracy": null,
    "exact_expression_state_coverage": null,
    "final_answer_consistency_observed_count": 0,
    "final_answer_consistency_fraction": null,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 53,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  },
  "ARC-style MC": {
    "n": 64,
    "accuracy": 0.71875,
    "truncation_fraction": 0.265625,
    "invalid_output_fraction": 0.125,
    "completion_fraction": 0.6875,
    "numeric_equations_observed": 0,
    "numeric_equation_accuracy": null,
    "exact_expression_states_observed": 0,
    "exact_expression_state_accuracy": null,
    "exact_expression_state_coverage": null,
    "final_answer_consistency_observed_count": 0,
    "final_answer_consistency_fraction": null,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 0,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  },
  "ARC-Challenge-style MC": {
    "n": 64,
    "accuracy": 0.5625,
    "truncation_fraction": 0.421875,
    "invalid_output_fraction": 0.234375,
    "completion_fraction": 0.53125,
    "numeric_equations_observed": 0,
    "numeric_equation_accuracy": null,
    "exact_expression_states_observed": 0,
    "exact_expression_state_accuracy": null,
    "exact_expression_state_coverage": null,
    "final_answer_consistency_observed_count": 0,
    "final_answer_consistency_fraction": null,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 0,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  },
  "SciQ-style MC": {
    "n": 96,
    "accuracy": 0.7708333333333334,
    "truncation_fraction": 0.11458333333333333,
    "invalid_output_fraction": 0.07291666666666667,
    "completion_fraction": 0.875,
    "numeric_equations_observed": 0,
    "numeric_equation_accuracy": null,
    "exact_expression_states_observed": 0,
    "exact_expression_state_accuracy": null,
    "exact_expression_state_coverage": null,
    "final_answer_consistency_observed_count": 0,
    "final_answer_consistency_fraction": null,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 0,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  },
  "math-short": {
    "n": 48,
    "accuracy": 0.5,
    "truncation_fraction": 0.0,
    "invalid_output_fraction": 0.0,
    "completion_fraction": 1.0,
    "numeric_equations_observed": 64,
    "numeric_equation_accuracy": 0.71875,
    "exact_expression_states_observed": 18,
    "exact_expression_state_accuracy": 0.8888888888888888,
    "exact_expression_state_coverage": 0.17142857142857143,
    "final_answer_consistency_observed_count": 4,
    "final_answer_consistency_fraction": 1.0,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 18,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  },
  "math-medium": {
    "n": 48,
    "accuracy": 0.20833333333333334,
    "truncation_fraction": 0.0,
    "invalid_output_fraction": 0.0,
    "completion_fraction": 1.0,
    "numeric_equations_observed": 187,
    "numeric_equation_accuracy": 0.7433155080213903,
    "exact_expression_states_observed": 60,
    "exact_expression_state_accuracy": 0.8833333333333333,
    "exact_expression_state_coverage": 0.24096385542168675,
    "final_answer_consistency_observed_count": 9,
    "final_answer_consistency_fraction": 1.0,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 48,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  },
  "math-long": {
    "n": 48,
    "accuracy": 0.0625,
    "truncation_fraction": 0.0,
    "invalid_output_fraction": 0.0,
    "completion_fraction": 1.0,
    "numeric_equations_observed": 304,
    "numeric_equation_accuracy": 0.75,
    "exact_expression_states_observed": 82,
    "exact_expression_state_accuracy": 0.8658536585365854,
    "exact_expression_state_coverage": 0.18594104308390022,
    "final_answer_consistency_observed_count": 3,
    "final_answer_consistency_fraction": 1.0,
    "premise_retention_errors": "unmeasured globally; outcome-stratified qualitative audit only",
    "arithmetic_state_errors_observed": 76,
    "constraint_satisfaction": "endpoint score and exact-state observations; no full-proof claim"
  }
}
```

| Suite / state | Completion % | Numeric-equation accuracy % | Equations observed | Exact-state accuracy % | Exact-state coverage % | Final consistency % | Consistency observations |
|---|---:|---:|---:|---:|---:|---:|---:|
| math-short / t32-A | 100.00 | 84.81 | 79 | 100.00 | 20.95 | 100.00 | 6 |
| math-short / t33-C | 100.00 | 71.88 | 64 | 88.89 | 17.14 | 100.00 | 4 |
| math-medium / t32-A | 100.00 | 77.37 | 190 | 92.31 | 5.22 | unmeasured | 0 |
| math-medium / t33-C | 100.00 | 74.33 | 187 | 88.33 | 24.10 | 100.00 | 9 |
| math-long / t32-A | 100.00 | 74.25 | 299 | 100.00 | 4.08 | unmeasured | 0 |
| math-long / t33-C | 100.00 | 75.00 | 304 | 86.59 | 18.59 | 100.00 | 3 |
| gsm-style / t32-A | 100.00 | 82.63 | 190 | unmeasured | unmeasured | unmeasured | 0 |
| gsm-style / t33-C | 100.00 | 87.03 | 185 | unmeasured | unmeasured | unmeasured | 0 |
| competition-style / t32-A | 93.75 | 49.33 | 75 | unmeasured | unmeasured | unmeasured | 0 |
| competition-style / t33-C | 98.96 | 17.19 | 64 | unmeasured | unmeasured | unmeasured | 0 |

Accuracy of intermediate states is conditional on observed expressions; coverage is disclosed independently. Semantic retention/constraint failures are assessed in the deterministic qualitative samples rather than inferred from endpoint or equation accuracy.

## Trace audit

Deterministic outcome-stratified samples include T32 wrong/T33 right, T32 right/T33 wrong, base right/T33 wrong, long-math successes/failures and ARC preserved/regressed. TRACE_SAMPLES.md retains full generations; TRACE_REVIEW.json records explicit observations for dropped premises, running totals, substitutions, loops, premature answers, truncation and endpoint inconsistency.

```json
{
  "review_status": "COMPLETE",
  "reviewed_by": "session Claude Code (manual review per directive phase: target trace audit)",
  "source": "evaluations/t33/TRACE_SAMPLES.md",
  "sample_count": 24,
  "sample_groups": [
    {
      "benchmark": "gsm8k",
      "group": "t32_wrong_t33_right",
      "items": [
        "t31-gsm8k-06b5b5dcbb41",
        "t31-gsm8k-09f4a934bf73"
      ]
    },
    {
      "benchmark": "gsm8k",
      "group": "t32_right_t33_wrong",
      "items": [
        "t31-gsm8k-001e092a011a",
        "t31-gsm8k-00ada270dd6f"
      ]
    },
    {
      "benchmark": "gsm8k",
      "group": "base_right_t33_wrong",
      "items": [
        "t31-gsm8k-001e092a011a",
        "t31-gsm8k-0073a3c25214"
      ]
    },
    {
      "benchmark": "math500",
      "group": "t32_wrong_t33_right",
      "items": [
        "t31-math500-0baabc521e23",
        "t31-math500-15fc93fd27db"
      ]
    },
    {
      "benchmark": "math500",
      "group": "t32_right_t33_wrong",
      "items": [
        "t31-math500-00a7be5d6e30",
        "t31-math500-01b1258edf9f"
      ]
    },
    {
      "benchmark": "math500",
      "group": "base_right_t33_wrong",
      "items": [
        "t31-math500-013c07aba3bd",
        "t31-math500-01b1258edf9f"
      ]
    },
    {
      "benchmark": "arc_easy",
      "group": "ARC_preserved",
      "items": [
        "t31-arc_easy-001194ee270e",
        "t31-arc_easy-002d4867714c"
      ]
    },
    {
      "benchmark": "arc_easy",
      "group": "ARC_regressed",
      "items": [
        "t31-arc_easy-00f02b479850",
        "t31-arc_easy-0197f0fb8a6c"
      ]
    },
    {
      "benchmark": "arc_challenge",
      "group": "ARC_preserved",
      "items": [
        "t31-arc_challenge-0023eeaec118",
        "t31-arc_challenge-02673549496a"
      ]
    },
    {
      "benchmark": "arc_challenge",
      "group": "ARC_regressed",
      "items": [
        "t31-arc_challenge-0004953a0c79",
        "t31-arc_challenge-0137edcf18bd"
      ]
    },
    {
      "benchmark": "math-long (dev)",
      "group": "long_math_success",
      "items": [
        "t33-synth-368fd174e88ec815b4d4",
        "t33-synth-8b4ec8cd7a453a13532a"
      ]
    },
    {
      "benchmark": "math-long (dev)",
      "group": "long_math_failure",
      "items": [
        "t33-synth-03b7a220954e515902a8",
        "t33-synth-05d36f01db881001dd0e"
      ]
    }
  ],
  "coverage_note": "All 24 outcome-stratified samples (12 groups x 2) were read in full from TRACE_SAMPLES.md. Counts below describe the audit set only; global quantities live in FINAL_SCORES.json, dev metrics, and PAIRED_ANALYSIS.json and are not extrapolated from this sample.",
  "required_categories": {
    "dropped_premises": {
      "observed_in_audit": true,
      "observations": [
        "t31-gsm8k-001e092a011a (t33 wrong): '20% of 50' was not converted to 10; the model subtracted the literal 20 from the running total. The premise's quantifier was dropped while the surface operation (subtraction) was retained.",
        "t31-arc_challenge-0137edcf18bd (t33 wrong): the question's core premise (deep-sea organisms produce light) was re-labeled as a generic 'biotic factors include all living things' preamble before any engagement with the specific premise, and the budget expired before an answer."
      ],
      "note": "premise_retention remains NOT_AUTOMATICALLY_ESTABLISHED in the frozen derivation audit by design; these are qualitative audit findings, not global measurements."
    },
    "failed_running_totals": {
      "observed_in_audit": true,
      "observations": [
        "t33-synth-03b7a220954e515902a8 (long_math_failure): the very first state was corrupted by a division arithmetic slip \u2014 (97-7)/6 = 90/6 stated as 16 instead of 15 \u2014 and every subsequent chained operation inherited the wrong state (final 469 vs gold 481). The chain mechanics (each op consuming the previous result) were followed correctly throughout; the failure is arithmetic, not procedural.",
        "t33-synth-05d36f01db881001dd0e (long_math_failure): after a correct probability setup (30/38 * 29/37 = 870/1369), fraction bookkeeping slipped in the chained operations (e.g. '13710/1369-2 = 13482/1369' instead of 10972/1369; '438/10+7 = 478/10' style improper-fraction addition in the sibling failure).",
        "t31-gsm8k-00ada270dd6f (t33 wrong): a compensating pair of invented state updates (+5 then -5 relative to what the problem stated) produced a net offset from the true total."
      ],
      "note": "On both math-long successes (t33-synth-368fd174..., t33-synth-8b4ec8cd...), every chained operation consumed the previous result correctly end-to-end, including a fraction-free state. The trained state-threading format itself works on-distribution; failures are arithmetic/bookkeeping slips inside it."
    },
    "wrong_substitutions": {
      "observed_in_audit": true,
      "observations": [
        "t31-gsm8k-001e092a011a (t33 wrong): the percent premise ('20% of 50') was substituted into the computation as its unprocessed surface value (20) \u2014 substitution of the wrong quantity, not a downstream arithmetic error.",
        "t31-math500-013c07aba3bd (t33 wrong): the running-total logic was correct, but the wrong positional state was substituted into the endpoint \u2014 the third sequence term (3^3) was boxed instead of the requested term (18; gold 45). Correct process, wrong state selection for the requested answer."
      ],
      "note": "Where algebra substitution was required (t31-math500-01b1258edf9f), the model skipped intermediate substitution arithmetic entirely and asserted an endpoint inconsistent with its own equation \u2014 see endpoint_inconsistency below."
    },
    "repetition_loops": {
      "observed_in_audit": true,
      "observations": [
        "Positive effect on t33: in t31-math500-0baabc521e23 the t32 arm entered a degenerate multiple-enumeration loop and hit the 1024-token budget (finish=length, wrong); the t33 arm produced a compact correct derivation and stopped. In t31-math500-15fc93fd27db the base and t30 arms both degenerated into loops that truncated; t33 answered correctly.",
        "No repetition loop was observed in any of the 24 t33-generated samples; loop-type finish=length failures visible in this audit belong to the base/t30/t32 comparison arms, not t33."
      ],
      "note": "This is the clearest replicable win attributable to the verified-derivation training: the enumerated-step + state-threading format replaced loop-prone enumeration habits."
    },
    "premature_answers": {
      "observed_in_audit": true,
      "observations": [
        "t31-math500-01b1258edf9f (t33 wrong): the model asserted the endpoint ('Solving for x, we find x=68') without performing the intermediate solving steps, and the asserted value (68) contradicts the equation it had itself stated one line earlier (whose root is 56). This is a premature endpoint assertion, not a derivation with a later arithmetic slip.",
        "t31-gsm8k-0073a3c25214 (t33 wrong): the derivation line '(90-3)/7-1=11' appears with no preceding work that could produce it \u2014 the answer was effectively asserted via an unexplained expression (gold 13)."
      ],
      "note": "The compressed one-liner style seen here is a style regression relative to the trained format: on in-distribution math-long failures (03b7a220, 05d36f01) the model DID enumerate steps; on out-of-distribution math500 items it sometimes reverts to the answer-first style."
    },
    "truncation": {
      "observed_in_audit": true,
      "observations": [
        "MC budget interaction is the dominant regression mechanism visible in the audit: in t31-arc_easy-0197f0fb8a6c the t33 arm began option-elimination reasoning ('B is incorrect... C is incorrect...') \u2014 derivation-style behavior leaking into direct mode \u2014 and the 32-token budget truncated it before any answer was emitted (invalid).",
        "t31-arc_challenge-0137edcf18bd (t33 wrong): same mechanism with a definition-first preamble ('Biotic factors include all living things...') truncating before any answer.",
        "t31-arc_challenge-0023eeaec118 (preserved): a justification-first response had its box truncated mid-'\\text{A' at the 32-token budget; the scorer still recovered A. t33 was one budget-hazard away from being counted wrong.",
        "On preserved ARC samples, t33's direct mode usually emits the boxed answer early (t31-arc_easy-001194ee270e) or completes cleanly within budget (t31-arc_challenge-02673549496a: finish=stop, correct, cleaner than the t30/t32 length finishes on the same item).",
        "No truncation was observed in any audited math500/gsm8k t33 arm."
      ],
      "note": "The 16 ARC losses concentrated in these two leakage/truncation shapes plus confident wrong-option naming; the frozen 32-token budget and frozen scorer were not modified and must not be."
    },
    "endpoint_inconsistency": {
      "observed_in_audit": true,
      "observations": [
        "t31-math500-00a7be5d6e30 (t33 wrong): the derivation correctly produced the quadratic (x+2)(x-1)=0, then boxed -1 \u2014 dropping the root -2 and boxing a value the stated factorization does not admit. Answer/reasoning inconsistency.",
        "t31-math500-01b1258edf9f (t33 wrong): boxed x=68 contradicts the model's own stated equation (root 56).",
        "t33-synth-05d36f01db881001dd0e (long_math_failure): the final state was stated as a fraction (105856.5/1369) but the boxed answer dropped the denominator (105856.5) \u2014 the endpoint is inconsistent with the derivation's own final state.",
        "These are all T33-fresh endpoint failures of the kind the frozen derivation audit flags as final_answer_consistency violations where the final state is observed; they persisted despite verification-style training."
      ],
      "note": "Verified arithmetic at training time did not eliminate endpoint inconsistency at generation time; the model is not checking its own box against its own last step."
    }
  },
  "additional_observed_mechanisms": {
    "style_leak_into_direct_mode": "Derivation-trained formatting (enumeration, elimination, preambles) appears in MC (direct-mode) outputs at test time; combined with the frozen 32-token MC budget this produces unanswered (invalid) outputs and truncation-hazard answers. Directly consistent with the -17.5pp/-16.7pp ARC deltas and elevated ARC invalid fractions in the dev/locked metrics.",
    "knowledge_reversion_on_mc": "In t31-arc_easy-00f02b479850 and t31-arc_challenge-0004953a0c79 the t33 arm confidently named a wrong option (C and D respectively) where the t32 arm (and in the latter case even base and t30) were correct \u2014 the math-curriculum retraining overwrote some MC option-discrimination knowledge rather than merely changing format.",
    "skipped_intermediate_arithmetic_compression": "On out-of-distribution math items the model sometimes compresses to an answer-first one-liner (01b1258edf9f) instead of enumerating states \u2014 the decoupling is imperfect in the direction of old short-answer policy on new-style prompts.",
    "win_side_attribution": "Wins come from (a) loop avoidance replacing degenerate enumeration (2/2 math500 t32-wrong wins and the base-arm loops), (b) faithful state threading on chained operations (both long-math successes and gsm8k 09f4a934bf73), and (c) cleaner percentage handling (gsm8k 06b5b5dcbb41). None of the audited wins came from improved symbolic manipulation."
  },
  "hypothesis_verdict_from_traces": "The verified-derivation curriculum taught a correct, loop-resistant state-threading format that works in-distribution (math-long successes) and reduces degenerate loops out-of-distribution. It did NOT restore mathematical capability: failures persist as arithmetic slips inside the correct format, premise-quantification failures, and endpoint inconsistencies (asserted endpoints contradicting the model's own derivation), and the curriculum actively damaged MC behavior via style leakage into direct mode and knowledge reversion \u2014 all at frozen budgets and frozen scorer. Consistent with the predeclared FAIL decision path; see DECISION.json when written."
}
```

## Contamination

Complete normalized-fingerprint and character-4-gram Jaccard >=0.90 comparisons against all 6,367 T31 final questions, without a candidate-pair scan cap or common-shingle shortcut. Both full presented prompts and canonical original question stems are checked; all retained records are clean. Training is also excluded from all original T32 development sets and newly frozen T33 suites. Removed records retain source/provenance/fingerprints and match IDs in training/t33/removed. Checksums and counts are in CONTAMINATION.json and DATA_VERIFICATION.json.

## Tests/regression

{"total": 4514, "passed": 4453, "failures": 49, "errors": 11, "skipped": 1}. Classification: {"PRE_EXISTING": 60}. Globally green repository: False. Original legacy failures remain visible.

```json
{
  "tests.test_t31_concurrency::test_concurrent_observations_lose_nothing_and_never_mix": {
    "final_measured_result": "PASS",
    "final_classification": "ENVIRONMENT_SPECIFIC",
    "entry_reproduced": true
  },
  "tests.test_t31_concurrency::test_the_event_log_never_gains_a_torn_line": {
    "final_measured_result": "PASS",
    "final_classification": "ENVIRONMENT_SPECIFIC",
    "entry_reproduced": true
  },
  "tests.test_t31_concurrency::test_readers_never_see_a_half_published_state": {
    "final_measured_result": "PASS",
    "final_classification": "ENVIRONMENT_SPECIFIC",
    "entry_reproduced": true
  },
  "tests.test_t31_concurrency::test_concurrent_transitions_are_all_durable": {
    "final_measured_result": "PASS",
    "final_classification": "ENVIRONMENT_SPECIFIC",
    "entry_reproduced": true
  }
}
```

## Artifacts

- scripts/t33_*.py: entry audit, deterministic construction, exact verification, strict training, frozen evaluation, selection, paired/trace analysis, regression classification and report/pack verification.
- training/t33/: verified records, contrastive pairs, direct source-gold records, removed records, frozen dev suites and candidate data.
- training/adapters/t33-A, t33-B, t33-C and training/checkpoints/t33-*; complete LoRA weights, manifests and full-state checkpoint history.
- evaluations/t33/: provenance, frozen-file map, protocol, contamination, feasibility, candidate receipts/dev raw rows/metrics, selection freeze, final raw scored rows, paired statistics, deterministic samples, manual audit, test JUnit/log/classifications, gate/decision/pack checks.
- SHA256SUMS: exact evidence and relevant source/data/model hashes; PACK_VERIFICATION.json: verification results.

## Known limitations

- The unique synthetic math corpus uses 16 authored family templates with parameter variation and composed operation chains. Synthetic length suites share generator structure; real GSM/competition development suites independently constrain candidate selection.
- Longer synthetic exercises use an explicit transformation score after a core family problem. This tests state tracking, but is narrower than natural competition proofs and semantic premise retention.
- Verification checks exact equations/endpoints and selected independent identities. It does not establish proof validity for arbitrary future model output.
- The direct science data uses source labels and carries the inherited SciQ license; no LLM correctness judgment is used as a math verifier.
- The experiment is one fixed curriculum pass on a local 6 GB RTX 4050. It does not isolate prompt conditioning from MC replay within A versus B; C isolates only learning rate.
- Each candidate uses one seed and one valid training run. Paired endpoint confidence intervals capture evaluation-item uncertainty, not training-seed variability or independent experiment replication.
- Numeric trace audit coverage is incomplete. Reported equation accuracy is conditional on measurable expressions, and coverage is disclosed separately.
- Final benchmark token budgets stay frozen at 512/1024/32. Longer training targets receive no extra evaluation budget.
- Historical base/T30/T32 final generations are reused. Historical evidence is preserved rather than regenerated or rewritten.
- State Engine WIP has no commit-based historical source identity. Explicit frozen-file hashes and reproduced environment failures are provided; legacy failures prevent a globally green claim.

## Gates

| Gate | Result |
|---|---|
| GATE 1 | PASS |
| GATE 2 | PASS |
| GATE 3 | PASS |
| GATE 4 | PASS |
| GATE 5 | PASS |
| GATE 6 | PASS |
| GATE 7 | PASS |
| GATE 8 | PASS |
| GATE 9 | PASS |
| GATE 10 | PASS |
| GATE 11 | PASS |
| GATE 12 | PASS |
| GATE 13 | PASS |
| GATE 14 | PASS |
| GATE 15 | PASS |

Gates 9–13 measure completion/preservation evidence; capability success requires the separate math/preservation/eligibility floors above.

## Decision

`MANGO_T33_VERIFIED_DERIVATION_FAIL`

T33 is closed. T34 was not started.
