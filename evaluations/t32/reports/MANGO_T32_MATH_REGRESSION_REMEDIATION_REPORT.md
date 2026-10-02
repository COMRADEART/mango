# MANGO T32 MATH REGRESSION REMEDIATION REPORT

## Status

FAIL — NO_EFFECT. `MANGO_T32_MATH_REMEDIATION_FAIL`

## T31 baseline

T31 remains closed. Base and T30 columns reuse its frozen model-only scored generations. T32 generations are fresh, with identical prompts, membership, budgets, decoder and scorer.

## Root-cause analysis

### H1_protocol_overfitting

NOT_THE_DRIVER

T32_PHASE1_TAXONOMY.json protocol_vocabulary_scan + training/adapters/mango-v0.2-L1 lineage check

Evidence for: ["626 rows show protocol vocabulary (MANGO_MARKERS) across both arms"]

Evidence against: ["the deployed T30 adapter never trained on protocol data (its lineage: sciencemath-sft-v1 -> T3 recipe only; mango-sft-v2-L1 is a separate lineage that does NOT back the release adapter)", "protocol-vocabulary rows appear on BOTH arms; being wrong is not explained by vocabulary presence"]

### H2_catastrophic_forgetting

PARTIAL — style-suppression confirmed, full capability destruction REFUTED

derive_explicit recovers 24/80 (30.0%) of adapter-wrong items (gsm8k 20/60=33.3%, math500 4/20=20.0%), all 24 with finish_reason=stop: the derivation ability is present in the weights and suppressed by short-form prompting. The un-recovered ~70% overlaps the both-arms-wrong core plus derivation-present-but-wrong rows; those are depth/chain errors the mixture must also address.

Evidence for: ["derive_explicit 24/80 recovered vs control 0/80"]

Evidence against: ["not all failures recover (70% remain under explicit derivation) — so partial capability damage on harder chains cannot be excluded; recorded, not averaged away"]

### H3_data_imbalance

CONTRIBUTES

training/datasets/sciencemath-sft-v1 manifests + sft_format.REASONING_BUDGETS + build_target contracts

Evidence for: ["T30 train corpus 2910 records: sciq 1152 (39.6%), gsm8k 806, math-competition 779, synthetic 173", "REASONING_BUDGETS (math 1600 / science 700 / general 400 chars) REJECT over-length targets at build: the corpus contains ONLY terse derivations; median target words gsm8k 49 / math-comp 72 / sciq 40", "answer_types: free_text 1152 vs numeric 845 vs expression 779 — short-form answer types dominate"]

Evidence against: ["math records still = 53% of the corpus by count; imbalance alone may not explain the size of the drop"]

### H4_sequence_length_truncation

REFUTED as the driver

probe results control_frozen vs budget_1024; T32_PHASE1_TAXONOMY truncation_all_rows

Evidence for: ["math500 adapter-wrong rows: 22.1% carry a truncation label — a real minority mode"]

Evidence against: ["probe budget_1024 EXACTLY equals control_frozen (0/80 both) with truncation 2/60 gsm8k, 4/20 math500: more budget with identical prompts recovers nothing", "control and budget_1024 generations are greedy-identical (both median 105.5 tokens); the adapter stops, it does not ram"]

### H5_final_answer_supervision_weakness

SUPPORTED

probe derive_explicit condition; corpus shape (H3 evidence)

Evidence for: ["explicit derivation instruction flips 24/80 adapter-failed items to correct, all natural stops", "derived-mode median tokens 136.5 vs 105.5 — the model extends its chain when told and finishes within budget", "T30 supervision never modeled long chains (1600-char build rejection + short median targets): final-answer shortcuts were never punished nor derivations rewarded"]

Evidence against: ["recovery is partial (30%): the harder tail needs stronger supervision than an instruction provides"]

### H6_multiple_choice_specialization

CONTRIBUTES (interaction effect)

T32_PHASE1_TAXONOMY adapter_gains base_failure_modes (MC truncation shares)

Evidence for: ["adapter-fixed MC rows are truncation-dominated: 255/281 arc_easy, 234/234 arc_challenge, 49/63 sciq base failures fixed at <=32-token budgets (adapter medians 30/32/24 tokens)", "the adapter's learned surface form is bounded answers, suppressing chains on math prompts from the same corpus signal"]

Evidence against: ["MC gains are a verbosity-policy effect at the frozen 32-token budget; nothing yet shows the MC modes and derivation modes are mutually exclusive — Candidate B supervises both explicitly"]

## Training changes

A adds verified math to the frozen T30 corpus and uses two epochs. B adds task-conditional protocol and MC examples to A. C keeps the exact T30 corpus and three epochs, with learning rate reduced from 1e-4 to 3e-5. The same 1.7B base and LoRA architecture are used throughout.

See `manifests/T32_TRAINING_RECEIPT.json` for exact configs, dataset counts, seeds, software, duration, quantization and weight hashes.

## Candidate ablation

| Candidate | GSM8K dev | Math dev | Math mean | MC dev | SciQ dev | Eligible |
|---|---:|---:|---:|---:|---:|---|
| t32-A | 68.00 | 33.50 | 50.75 | 86.50 | 90.00 | False |
| t32-B | 66.50 | 29.00 | 47.75 | 86.00 | 92.00 | False |
| t32-C | 67.00 | 30.00 | 48.50 | 85.50 | 88.67 | False |

## Candidate selection

`t32-A`: NO candidate eligible; final locked evaluation runs the highest math_dev_mean overall (DEV_PROTOCOL §6 fallback). Eligibility and tie-break thresholds were declared before training in `development/DEV_PROTOCOL.md`.

## Final model identities

{
  "final_commit": "5a646aec4205a21ad83de7d07f7a63fbbce98b0c",
  "branch": "t31-public-comparability (pushed to origin, NOT merged)",
  "base_repo_id": "Qwen/Qwen3-1.7B",
  "base_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
  "t30_adapter_repo_id": "ComradeRt/Mango-T30-1.7B",
  "t30_adapter_revision": "ad4bac714e442ca5c9b20420847fcadad61a6123",
  "t30_adapter_weights_sha256": "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
  "frozen_config_sha256": "2f86db2e577807ed8021a4b647f3fa2243762e327d6e3c22c76184520e842eff",
  "prompt_policy_hash": "3625ff07bbb3d9075c774502d4d2bc32cb441bc710c073fd7bb78f79b714899c",
  "report_sha256": "04a878dd0ae0f4a01f8875c33af2dd57b691ea49672e5d4e5965a2a70d7cdcde",
  "decision": "MANGO_T31_PUBLIC_COMPARABILITY_PASS (15/15 gates)"
}

T32 adapter SHA-256: `64c2787f3457526ccd5aee571a0c106b8dc67b820886260714d3f55169318acb`.

## Final benchmark table

| Benchmark | Base % | T30 % | T32 % | Δ vs T30 pp | Δ vs base pp |
|---|---:|---:|---:|---:|---:|
| gsm8k | 81.05 | 58.38 | 62.40 | +4.02 | -18.65 |
| math500 | 59.80 | 30.40 | 31.80 | +1.40 | -28.00 |
| arc_easy | 79.46 | 87.67 | 88.97 | +1.30 | +9.51 |
| arc_challenge | 61.60 | 77.30 | 76.54 | -0.77 | +14.93 |
| sciq | 84.90 | 86.90 | 88.80 | +1.90 | +3.90 |

## Paired analysis

Exact McNemar tests and paired-delta normal 95% intervals are recorded per benchmark in `paired/T32_PAIRED_ANALYSIS.json`. Intervals use the variance of per-item paired correctness differences; no scores are pooled.

## Math restoration

GSM8K: +4.02 pp. MATH-500: +1.40 pp. Both meet the +5 pp floor: False.

## Capability preservation

{"arc_easy": true, "arc_challenge": true, "sciq": true}

## Trace audit

`final/T32_TRACE_AUDIT_t32-A.md` contains deterministic samples of T30-wrong/T32-right, T30-right/T32-wrong and base-right/T32-wrong for both math and ARC benchmarks.

{
  "artifact": "T32_QUALITATIVE_REVIEW",
  "review_status": "COMPLETE",
  "sampling": "GSM8K: three smallest IDs per outcome group, eight unique items. MATH-500: two smallest IDs per outcome group, six unique items. Post-selection qualitative samples; candidate selection was already frozen. ARC-Easy: two smallest IDs per outcome group, six unique items. ARC-Challenge: two smallest IDs per outcome group, five unique items (one overlap). The larger retained trace audit supplies additional context.",
  "benchmarks_reviewed": [
    "gsm8k",
    "math500",
    "arc_easy",
    "arc_challenge"
  ],
  "gsm8k": {
    "outcome_population": {
      "t30_wrong_t32_right": 176,
      "t30_right_t32_wrong": 123,
      "base_right_t32_wrong": 320
    },
    "actual_reasoning_recovery": [
      {
        "item_id": "t31-gsm8k-021666193ea2",
        "observation": "T32 correctly applies the net first-stop change and second-stop removal to reach 100; T30 repeatedly reapplies the first-stop figures and answers 167."
      },
      {
        "item_id": "t31-gsm8k-02464a7e6ee9",
        "observation": "T32 computes 180 minutes and divides by the 30-minute drinking interval to reach 6; T30 uses inconsistent rate conversions and answers 2.25."
      },
      {
        "item_id": "t31-gsm8k-049740b453aa",
        "observation": "T32 computes two pounds of supplies costing 20, revenue 40, and net profit 20; T30 miscomputes the material cost and answers 40."
      }
    ],
    "reasoning_regressions": [
      {
        "item_id": "t31-gsm8k-0263fba48ddc",
        "observation": "T32 subtracts the transferred apples from Boris but omits adding them to Beck, giving 13 rather than 3."
      },
      {
        "item_id": "t31-gsm8k-09f4a934bf73",
        "observation": "T32 computes the half-pile theft but never subtracts it from the running banana count, giving 65 rather than 43."
      },
      {
        "item_id": "t31-gsm8k-0bd224446d7c",
        "observation": "T32 omits the extra 11 points in Nikita's score, giving 417 rather than 428."
      }
    ],
    "persistent_base_gap": [
      {
        "item_id": "t31-gsm8k-0073a3c25214",
        "observation": "The base accounts for annual operating cost and strict positive profit; T32 invents a denominator of 9 and answers 10 rather than 13."
      },
      {
        "item_id": "t31-gsm8k-023f4e1c7199",
        "observation": "The base correctly solves the simultaneous linear relations; T32 repeatedly substitutes terms, forms an incorrect equation, and declares no solution."
      }
    ],
    "format_vs_content": "T30 and T32 both produce boxed answers in all reviewed items. The sample gains change intermediate arithmetic and the final numerical answer, rather than merely restoring extraction compatibility.",
    "protocol_intrusion": "No Mango planning/handoff schema or coordination language was observed in the eight reviewed T32 GSM8K generations. This is a sample observation, not a corpus-wide absence claim.",
    "reasoning_style": "Several correct T32 traces are shorter than T30's incorrect traces; brevity alone does not explain success. Regressions show omitted premises despite valid boxed formatting.",
    "scope_limit": "Outcome-stratified qualitative sample; not representative of overall prevalence."
  },
  "math500": {
    "outcome_population": {
      "t30_wrong_t32_right": 46,
      "t30_right_t32_wrong": 39,
      "base_right_t32_wrong": 156
    },
    "format_vs_content": "Both gains contain valid boxed endpoints and improved intermediate reasoning. One sampled regression is truncation/extraction failure; another violates the digit-sum constraint despite valid formatting.",
    "protocol_intrusion": "No Mango planning or handoff schema was observed in these six T32 samples; this does not establish corpus-wide absence.",
    "scope_limit": "Outcome-stratified sample is qualitative. Frozen benchmark scores assess answer endpoints, not proof validity; two T30 endpoint matches in this sample contain invalid derivations.",
    "persistent_base_gap": [
      {
        "observation": "T30 and T32 use the end-to-end difference 72 as an adjacent arithmetic-sequence difference, giving 81 instead of the mean 45.",
        "item_id": "t31-math500-013c07aba3bd"
      },
      {
        "observation": "T32 derives allowable exponent ranges 0..2 and 0..1 for x cubed dividing 10 factorial, but counts four rather than multiplying three by two. Its intermediate setup improves while the endpoint remains wrong.",
        "item_id": "t31-math500-033e9ead6dae"
      }
    ],
    "actual_reasoning_recovery": [
      {
        "observation": "T32 correctly counts nine four-mile walks in February, yielding 36. T30 adds an unjustified extra walk and answers 40.",
        "item_id": "t31-math500-0b44398fcec3"
      },
      {
        "observation": "T32 parameterizes n=3k+1 and m=32-4k, then minimizes |31-7k| to obtain 3. T30 drops terms in its algebra and answers 0.",
        "item_id": "t31-math500-0c188bd66bb8"
      }
    ],
    "reasoning_regressions": [
      {
        "observation": "T32 repeats its logarithm analysis until the 1024-token limit and supplies no valid final answer. T30 matches gold 501 but its derivation drops 4/x and admits invalid logarithm arguments; its scored endpoint does not demonstrate correct reasoning.",
        "item_id": "t31-math500-03592e465db4"
      },
      {
        "observation": "T32 falsely treats all 15 listed two-digit primes as having digit sum eight. T30 matches gold count 3 but lists composite 44 and omits 53; the endpoint match masks invalid reasoning.",
        "item_id": "t31-math500-089a90557aba"
      }
    ]
  },
  "arc_easy": {
    "actual_reasoning_recovery": [
      {
        "observation": "T32 selects the correct invention sequence: printing press, microscope, telephone; T30 chooses another sequence.",
        "item_id": "t31-arc_easy-00f02b479850"
      },
      {
        "observation": "T32 identifies the red-giant stage instead of T30 quasar. Both explanations truncate at the frozen 32-token budget but their answer endpoints are extractable.",
        "item_id": "t31-arc_easy-08b4696f6b96"
      }
    ],
    "format_vs_content": "Sample gains change selected concepts and remain extractable under the frozen budget. Short answer-only traces limit causal interpretation of some losses.",
    "persistent_base_gap": [
      {
        "observation": "T32 and T30 choose A instead of color and mass after melting a crayon; T32 provides no explanatory trace.",
        "item_id": "t31-arc_easy-09245b5ef023"
      },
      {
        "observation": "Both adapters identify commensalism instead of mutualism despite the question describing benefit to both organisms.",
        "item_id": "t31-arc_easy-10bf86fe982e"
      }
    ],
    "scope_limit": "Outcome-stratified qualitative sample; short or truncated explanations cannot establish full reasoning validity.",
    "outcome_population": {
      "t30_wrong_t32_right": 67,
      "base_right_t32_wrong": 63,
      "t30_right_t32_wrong": 36
    },
    "protocol_intrusion": "No Mango planning or handoff schema observed in six sampled T32 generations.",
    "reasoning_regressions": [
      {
        "observation": "T32 gives only C instead of gold B for protein transport; no derivation is available to establish its mechanism.",
        "item_id": "t31-arc_easy-0c72be11a481"
      },
      {
        "observation": "T32 attributes an iguana tail to camouflage instead of swimming, despite T30 correctly identifying swimming.",
        "item_id": "t31-arc_easy-171c79971c3d"
      }
    ]
  },
  "arc_challenge": {
    "protocol_intrusion": "No Mango planning or handoff schema observed in the five sampled T32 outputs.",
    "persistent_base_gap": [
      {
        "observation": "Both adapters choose A instead of the ice-floating consequence of the less dense crystal structure.",
        "item_id": "t31-arc_challenge-031eeab00110"
      },
      {
        "observation": "The heat-versus-electromagnetic regression also loses a base-correct endpoint.",
        "item_id": "t31-arc_challenge-04e28c0e53d4"
      }
    ],
    "outcome_population": {
      "t30_right_t32_wrong": 45,
      "t30_wrong_t32_right": 36,
      "base_right_t32_wrong": 46
    },
    "format_vs_content": "Includes conceptual gains and losses plus an answer/explanation inconsistency in T30. Frozen 32-token traces and answer-only outputs limit mechanism conclusions.",
    "actual_reasoning_recovery": [
      {
        "observation": "T32 selects apple core as fastest to decay. T30 discusses decay correctly in part but boxes A, illustrating endpoint/explanation inconsistency.",
        "item_id": "t31-arc_challenge-0402fa99f016"
      },
      {
        "observation": "T32 selects crust heated by nearby magma; T30 incorrectly selects crust reaching deep into Earth.",
        "item_id": "t31-arc_challenge-103db695de32"
      }
    ],
    "reasoning_regressions": [
      {
        "observation": "T32 answers heat instead of electromagnetic energy for producing light; T30 identifies electromagnetic waves.",
        "item_id": "t31-arc_challenge-04e28c0e53d4"
      },
      {
        "observation": "T32 selects fur color as least inheritable, with no explanation. Its endpoint regresses from T30; mechanism cannot be established.",
        "item_id": "t31-arc_challenge-0518b2af9184"
      }
    ],
    "scope_limit": "Outcome-stratified qualitative sample; no prevalence or proof-validity claim."
  }
}

## Contamination audit

{
  "artifact": "T32_CONTAMINATION_REPORT",
  "schema_version": "t32-mixture-v1",
  "gate": "T32 fresh pool vs all T31 evaluation item questions (base-arm scored rows; both arms share frozen membership)",
  "run_at": "2026-09-30T22:56:12.689193+00:00",
  "stage_order": [
    "1. pools.py: direct fingerprint exclusion vs T30 corpus (train+validation) and T31 eval questions",
    "2. THIS GATE: near-leakage (4-gram shingle Jaccard >= 0.90, the T30-build parameters) vs T31 eval questions; direct re-check"
  ],
  "eval_questions_total": 6367,
  "candidates_checked": 21445,
  "direct_leakage_found": 0,
  "near_leakage_found": 0,
  "records_removed": 0,
  "removals_by_source_kind": {},
  "removed_records": [],
  "kept": 21445,
  "remediation": "contaminated records (direct and near >= 0.90 Jaccard) REMOVED from the T32 pool before any mixture use; full removal list in fresh_pool_removed.jsonl",
  "kept_sha256": "720e36b06aee7f08a5957fe9f6ad1d7915933a30a12012f1ac14cfa3103f38e6",
  "passed_after_remediation": true
}

## Tests

PYTHONPATH=src python -m pytest --basetemp=tests/.pytest_tmp_t32_handoff --junitxml=evaluations/t32/development/regression_junit.xml

4438 passed, 65 failures/errors, 1 skipped.

## Regression classification

61 failed test IDs also failed in the T31 closure run; 2 were reviewed as environment/concurrency failures with passing isolated or focused checks; 2 remain new or unclassified. Original failures are retained. Details: `reports/T32_REGRESSION_CLASSIFICATION.json`.

## Artifacts

Diagnostics, development rows and selection, fresh final generations with scored fields, paired analysis, trace samples, frozen candidate manifests, training receipt, gate results and SHA256SUMS are retained. Final raw text is preserved on every scored row.

## Known limitations

The base/T30 arms reuse historical frozen generations rather than fresh runs. The development protocol omitted a model-generated schema-validity metric, so schema preservation is not established. Diagnostic hypotheses are observational and the explicit-derivation probe uses a selected failure set. Paired normal intervals are approximate. Training checkpoint interruptions and restart history are disclosed in the operational notes and receipt. Candidate B resumed model weights at step 500 with recreated optimizer, scheduler and RNG after interruption at step 574; its altered optimization history limits interpretation as a pure mixture ablation. Outcome-stratified trace samples have been reviewed; they are not prevalence estimates. Frozen endpoint scores do not validate intermediate reasoning, and sampled T30 gold-matching answers sometimes contain invalid derivations. Root-cause labels are observational interpretations rather than causal proof. The final focused concurrency check passed nine tests and failed two with Windows os.replace PermissionError in unchanged frozen state-index publication; see reports/T32_CONCURRENCY_REVIEW.json. These remain unresolved and the regression gate fails.

## Gate results

| Gate | Result |
|---|---|
| 1 | PASS |
| 2 | PASS |
| 3 | PASS |
| 4 | PASS |
| 5 | PASS |
| 6 | PASS |
| 7 | PASS |
| 8 | PASS |
| 9 | PASS |
| 10 | PASS |
| 11 | PASS |
| 12 | PASS |
| 13 | PASS |
| 14 | FAIL |
| 15 | PASS |

## Decision

`MANGO_T32_MATH_REMEDIATION_FAIL`
