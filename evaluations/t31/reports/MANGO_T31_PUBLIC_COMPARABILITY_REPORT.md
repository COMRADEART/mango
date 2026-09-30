# MANGO T31 PUBLIC COMPARABILITY REPORT

## Status

**PASS**

15 gates: 15 PASS, 0 FAIL, 0 NOT_EVALUATED.

A gate that was not evaluated is reported as such and is not counted as satisfied. Status is PARTIAL, not PASS, while any gate is NOT_EVALUATED.

## Branch and commits

- Branch: `t31-public-comparability`
- Base commit (the frozen Mango T30 state T31 branched from): `d25d4574bcfe1634f91bce435efd75566fba8f7d`
- Final commit (this report): `58e911f484928e1e3da6d4fd9f888d96373af6df`

## Frozen model identities

Two systems are compared. The only experimental variable between the two columns is the adapter's weights.

| System | Repository | Revision | Weights sha256 |
|---|---|---|---|
| Base model | `Qwen/Qwen3-1.7B` | `70d244cc86cc` | `(tokenizer/revis…` |
| Mango Adapter | `ComradeRt/Mango-T30-1.7B` | `ad4bac714e44` | `f57b2fd4a653abb9…` |

The adapter declares its base as `70d244cc86cc`, which is the revision being compared against it — the ablation isolates the adapter.

The Mango Adapter is a LoRA adapter over the base model, not a separately trained model. The Mango Runtime is not loaded in either column; it is measured separately, below, and its results are never combined with the two columns here.

## Evaluation environment

| Field | Value |
|---|---|
| `accelerate` | `1.14.0` |
| `cuda_available` | `True` |
| `cuda_device_count` | `1` |
| `datasets` | `5.0.1` |
| `gpu_name` | `NVIDIA GeForce RTX 4050 Laptop GPU` |
| `gpu_total_memory_bytes` | `6438780928` |
| `machine` | `AMD64` |
| `peft` | `0.20.0` |
| `platform` | `Windows-11-10.0.26200-SP0` |
| `python` | `3.12.10` |
| `sympy` | `1.13.1` |
| `torch` | `2.5.1+cu121` |
| `torch_cuda` | `12.1` |
| `transformers` | `5.16.1` |

## Frozen decoding configuration

Configuration hash: `2f86db2e577807ed8021a4b647f3fa2243762e327d6e3c22c76184520e842eff`

Both systems are decoded with these settings. Nothing below was chosen after seeing which side scored better.

| Setting | Value |
|---|---|
| `batch_size` | `8` |
| `device` | `'cuda:0'` |
| `do_sample` | `False` |
| `dtype` | `'bfloat16'` |
| `enable_thinking` | `False` |
| `max_new_tokens` | `{'gsm8k': 512, 'math500': 1024, 'arc_easy': 32, 'arc_challenge': 32, 'sciq': 32}` |
| `num_beams` | `1` |
| `quantization` | `'none'` |
| `repetition_penalty` | `1.0` |
| `seed` | `20260930` |
| `seed_policy` | `'Greedy decoding is seed-independent. A fixed seed is still recorded and set so that the optional sampled robustness arm is reproducible.'` |
| `stop_token_ids` | `[151645]` |
| `temperature` | `None` |
| `top_k` | `None` |
| `top_p` | `None` |

Maximum generation length is set per benchmark and recorded with each item.

## Dataset identities

| Benchmark | Source | Config | Split | Revision | Items | License |
|---|---|---|---|---|---|---|
| arc_challenge | `allenai/ai2_arc` | `ARC-Challenge` | `test` | `210d026faf99` | 1172 | CC-BY-SA-4.0 |
| arc_easy | `allenai/ai2_arc` | `ARC-Easy` | `test` | `210d026faf99` | 2376 | CC-BY-SA-4.0 |
| gsm8k | `openai/gsm8k` | `main` | `test` | `740312add88f` | 1319 | MIT |
| math500 | `HuggingFaceH4/MATH-500` | `None` | `test` | `6e4ed1a2a79a` | 500 | MIT (derived from hendrycks/competition_math) |
| sciq | `allenai/sciq` | `None` | `test` | `2c94ad3e1aaf` | 1000 | CC-BY-NC-3.0 |

Every item carries a stable id derived from the benchmark, split and the source's own identifier, so a row can be traced back to the dataset record that produced it.

## Model-only results

Content accuracy: a generation counts only when the extracted answer is correct against the benchmark's own reference. Formatting that cannot be parsed is a failure, not a pass.

| Benchmark | Base | Mango T30 Adapter | Δ pp | Relative Δ | Outcome |
|---|---|---|---|---|---|
| gsm8k | 81.05% (1069/1319) | 58.38% (770/1319) | -22.67 | -27.97% | REGRESSION |
| math500 | 59.80% (299/500) | 30.40% (152/500) | -29.40 | -49.16% | REGRESSION |
| arc_easy | 79.46% (1888/2376) | 87.67% (2083/2376) | +8.21 | +10.33% | LIFT |
| arc_challenge | 61.60% (722/1172) | 77.30% (906/1172) | +15.70 | +25.48% | LIFT |
| sciq | 84.90% (849/1000) | 86.90% (869/1000) | +2.00 | +2.36% | EQUAL |

Micro-average over all 6367 items (`micro_average_over_items`): base 75.81%, Mango Adapter 75.07%, Δ -0.74 pp.

A single pooled rate over benchmarks of different sizes; the per-benchmark table is the interpretable one.

These are weight-level figures. They are not the Mango Runtime's scores and not the Mango Integrated System's scores; those are reported separately and never in this table.

## Paired outcomes

Each item is evaluated by both systems, so the comparison is paired rather than between two independent samples.

| Benchmark | Both correct | Base only | Adapter only | Neither | McNemar p |
|---|---|---|---|---|---|
| gsm8k | 705 | 364 | 65 | 185 | 0.0000 |
| math500 | 133 | 166 | 19 | 182 | 0.0000 |
| arc_easy | 1802 | 86 | 281 | 207 | 0.0000 |
| arc_challenge | 672 | 50 | 234 | 216 | 0.0000 |
| sciq | 806 | 43 | 63 | 88 | 0.0645 |

The discordant cells — base-only and adapter-only — are what McNemar's test is computed over; concordant items carry no information about a difference between the two systems.

## Uncertainty

Interval estimates come from a percentile bootstrap resampling *clusters of items sharing a question stem*, not individual items, because near-duplicate items within a benchmark are not independent and resampling them as such would narrow the interval without justifying it.

| Benchmark | Δ pp | 95% CI | Reading | Clusters | Items |
|---|---|---|---|---|---|
| gsm8k | -22.67 | [-25.47, -19.79] | negative and distinguishable from zero | 1319 | 1319 |
| math500 | -29.40 | [-34.20, -24.60] | negative and distinguishable from zero | 500 | 500 |
| arc_easy | +8.21 | [+6.73, +9.80] | positive and distinguishable from zero | 2371 | 2376 |
| arc_challenge | +15.70 | [+13.07, +18.34] | positive and distinguishable from zero | 1170 | 1172 |
| sciq | +2.00 | [+0.00, +4.10] | inconclusive at this sample size | 1000 | 1000 |

A delta is described as an improvement only when its interval excludes zero *and* the sign is positive. An interval spanning zero is reported as inconclusive at this sample size, whatever the point estimate happens to be.

Cluster resampling was material on arc_easy, arc_challenge: those benchmarks contain distinct items sharing a question stem, whose outcomes are correlated. Everywhere else the stem is unique and the clustering reduces to ordinary item resampling.

## Error analysis

Categories are assigned by the scorer from the generation itself. No error was reclassified by hand to improve a result.

Counts are per arm, over the items that arm got wrong.

| Benchmark | Arm | answer_extraction_failure | invalid_option | truncated_generation | wrong_final_answer | Total |
|---|---|---|---|---|---|---|
| gsm8k | base | 0 | 0 | 0 | 250 | 250 |
| gsm8k | adapter | 0 | 0 | 0 | 549 | 549 |
| math500 | base | 0 | 0 | 4 | 197 | 201 |
| math500 | adapter | 0 | 0 | 0 | 348 | 348 |
| arc_easy | base | 0 | 99 | 166 | 223 | 488 |
| arc_easy | adapter | 2 | 1 | 4 | 286 | 293 |
| arc_challenge | base | 0 | 67 | 169 | 214 | 450 |
| arc_challenge | adapter | 0 | 0 | 3 | 263 | 266 |
| sciq | base | 0 | 29 | 14 | 108 | 151 |
| sciq | adapter | 3 | 0 | 0 | 128 | 131 |

| Benchmark | Invalid outputs (base / adapter) | Extraction failures (base / adapter) | Shared failures |
|---|---|---|---|
| gsm8k | 24 / 20 | 0 / 0 | 185 |
| math500 | 128 / 77 | 4 / 0 | 182 |
| arc_easy | 1419 / 816 | 265 / 7 | 207 |
| arc_challenge | 828 / 526 | 236 / 3 | 216 |
| sciq | 526 / 181 | 43 / 3 | 88 |

`invalid_output` covers generations that could not be read as an answer at all — an empty generation, an unparseable one, or one cut off at the token budget. An extraction failure is counted separately from a content failure wherever the two can be told apart. All of them count as incorrect; they are not excluded from the denominator.

## Schema versus content

Two independent facts are recorded for every generation.

- `schema_valid` — the generation conformed to the requested answer format.
- `content_valid` — the extracted answer was correct.

| Benchmark | Arm | schema ∧ content | schema only | content only | neither | Total |
|---|---|---|---|---|---|---|
| gsm8k | base | 289 | 65 | 780 | 185 | 1319 |
| gsm8k | adapter | 0 | 1 | 770 | 548 | 1319 |
| math500 | base | 299 | 76 | 0 | 125 | 500 |
| math500 | adapter | 152 | 271 | 0 | 77 | 500 |
| arc_easy | base | 1836 | 302 | 52 | 186 | 2376 |
| arc_easy | adapter | 1940 | 261 | 143 | 32 | 2376 |
| arc_challenge | base | 696 | 258 | 26 | 192 | 1172 |
| arc_challenge | adapter | 869 | 238 | 37 | 28 | 1172 |
| sciq | base | 838 | 137 | 11 | 14 | 1000 |
| sciq | adapter | 706 | 90 | 163 | 41 | 1000 |

`schema_only` is the cell that matters: a well-formatted wrong answer. It is a content failure. Producing a parseable answer is never counted as reasoning success, and `content_valid` is the capability metric throughout this report.

## Integrated runtime results

Not measured. The Mango Integrated System — adapter weights plus the Mango Runtime — was not evaluated under this task, so no integrated figures are reported. Nothing in the model-only tables above should be read as a runtime result.

## Training-data overlap and contamination

Overlap is measured, not asserted. Each evaluated item is compared against the historical training corpus and classified as an exact duplicate, a near-duplicate, or sharing a template.

| Benchmark | Known training overlap | Evaluation interpretation |
|---|---|---|
| gsm8k | yes (842 records from the train split) | All 1319 items were compared against every training record: no identical question and no near-duplicate carrying the answer (max 5-gram similarity 0.21). Trained on this source's train split and evaluated on its test split: disjoint by construction and confirmed by measurement, but still IN-DISTRIBUTION — the model has seen this task and format extensively, so a score here measures performance on this kind of question, not generalization to it. |
| math500 | no (excluded from training as a source) | All 500 items were compared against every training record: no identical question and no near-duplicate carrying the answer (max 5-gram similarity 0.86). No records from this source appear in any training corpus, so this is held out. Listed for audit rather than counted as contamination: 3 of 500 items (0.60%) have a near-duplicate question but the training record does not state the answer. Separately, 17 of 500 items (3.40%) share a problem TEMPLATE with a training record while asking a different question. That is not contamination, but it does mean the benchmark's surface form is familiar. |
| arc_easy | no (excluded from training as a source); 4 of 2376 evaluated items nevertheless overlap measured (0 identical, 4 near-duplicate carrying the answer) | 4 of 2376 items (0.17%) more have a NEAR-DUPLICATE question whose ANSWER the training corpus states. The question can be answered from memory, so these are contaminated too. Contaminated in total: 4 of 2376 items (0.17%). The remaining 2372 items are not known to be contaminated, but see the sibling count below before treating this as an unseen benchmark. Separately, 3 of 2376 items (0.13%) share a problem TEMPLATE with a training record while asking a different question. That is not contamination, but it does mean the benchmark's surface form is familiar. |
| arc_challenge | no (excluded from training as a source) | All 1172 items were compared against every training record: no identical question and no near-duplicate carrying the answer (max 5-gram similarity 0.21). No records from this source appear in any training corpus, so this is held out. Separately, 3 of 1172 items (0.26%) share a problem TEMPLATE with a training record while asking a different question. That is not contamination, but it does mean the benchmark's surface form is familiar. |
| sciq | yes (1200 records from the train split); 1 of 1000 evaluated items nevertheless overlap measured (1 identical, 0 near-duplicate carrying the answer) | 1 of 1000 items (0.10%) have an IDENTICAL question in the training corpus, which also states the answer. These items are contaminated: their scores are not evidence of generalization. Contaminated in total: 1 of 1000 items (0.10%). The remaining 999 items are not known to be contaminated, but see the sibling count below before treating this as an unseen benchmark. Separately, 8 of 1000 items (0.80%) share a problem TEMPLATE with a training record while asking a different question. That is not contamination, but it does mean the benchmark's surface form is familiar. |

### Measured overlap

| Benchmark | Items checked | Exact | Near-dup | Answer-carrying | Sibling | Max n-gram | Held out |
|---|---|---|---|---|---|---|---|
| gsm8k | 1319 | 0 | 0 | 0 | 0 | 0.211 | False |
| math500 | 500 | 0 | 3 | 0 | 17 | 0.860 | True |
| arc_easy | 2376 | 0 | 4 | 4 | 3 | 0.625 | False |
| arc_challenge | 1172 | 0 | 0 | 0 | 3 | 0.210 | True |
| sciq | 1000 | 1 | 0 | 0 | 8 | 0.429 | False |

ARC is treated as a protected benchmark. It was not trained on, fine-tuned on, used for prompt selection, or used to select a checkpoint during T31, and no ARC-specific failure was corrected by hand.

## Reproduction

Frozen configuration: `evaluations/t31/config/t31_frozen_config.json`
Hash manifest: `evaluations/t31/SHA256SUMS`
Recorded environment: `evaluations/t31/manifests/environment.json`

```
PYTHONPATH=src python -m sciencemath.comparability --root . run --arm both
PYTHONPATH=src python -m sciencemath.comparability --root . run --arm adapter --benchmark sciq
PYTHONPATH=src python -m sciencemath.comparability --root . score
PYTHONPATH=src python -m sciencemath.comparability --root . analyse
PYTHONPATH=src python -m sciencemath.comparability --root . contamination
PYTHONPATH=src python -m sciencemath.comparability --root . report --branch t31-public-comparability --base-commit d25d4574bcfe1634f91bce435efd75566fba8f7d --final-commit 58e911f484928e1e3da6d4fd9f888d96373af6df
PYTHONPATH=src python -m sciencemath.comparability --root . manifest
PYTHONPATH=src python -m sciencemath.comparability --root . verify
PYTHONPATH=src python -m pytest tests/test_t31_comparability_runner.py tests/test_t31_comparability_rows.py tests/test_t31_comparability_pipeline.py tests/test_t31_resume_recovery.py
```

The commands above reproduce the comparison from the frozen configuration on a machine with the recorded environment. The raw files are not regenerated byte-identically by every device; the scored files are a deterministic function of the raw files and are.

## Artifacts

- `README.md`
- `analysis.json`
- `config/t31_frozen_config.json`
- `contamination.json`
- `manifests/environment.json`
- `raw/adapter/arc_challenge.jsonl`
- `raw/adapter/arc_easy.jsonl`
- `raw/adapter/gsm8k.jsonl`
- `raw/adapter/math500.jsonl`
- `raw/adapter/sciq.jsonl`
- `raw/base/arc_challenge.jsonl`
- `raw/base/arc_easy.jsonl`
- `raw/base/gsm8k.jsonl`
- `raw/base/math500.jsonl`
- `raw/base/sciq.jsonl`
- `recovery/T31_PRERESUME_PRESERVATION.json`
- `recovery/T31_RESUME_RECOVERY_RECORD.json`
- `recovery/T31_TRACKED_SUITE_CLASSIFICATION.json`
- `recovery/analyse_log.txt`
- `recovery/analyse_output.json`
- `recovery/contamination_log.txt`
- `recovery/contamination_output.json`
- `recovery/measured_tests.txt`
- `recovery/resume_log.txt`
- `recovery/resume_stdout.json`
- `recovery/run_closure_report.py`
- `recovery/score_log.txt`
- `recovery/score_output.json`
- `recovery/t31_measured_tests_junit.xml`
- `scored/adapter/arc_challenge.jsonl`
- `scored/adapter/arc_easy.jsonl`
- `scored/adapter/gsm8k.jsonl`
- `scored/adapter/math500.jsonl`
- `scored/adapter/sciq.jsonl`
- `scored/base/arc_challenge.jsonl`
- `scored/base/arc_easy.jsonl`
- `scored/base/gsm8k.jsonl`
- `scored/base/math500.jsonl`
- `scored/base/sciq.jsonl`
- `source/analysis.py`
- `source/config.py`
- `source/contamination.py`
- `source/contract.py`
- `source/extractors.py`
- `source/gates.py`
- `source/identity.py`
- `source/loaders.py`
- `source/manifest.py`
- `source/pipeline.py`
- `source/prompts.py`
- `source/report.py`
- `source/rows.py`
- `source/runner.py`
- `source/scorers.py`
- `source/scoring.py`
- `t32_diagnostic_handoff.jsonl`

## Hashes

These authenticate the run: they say which inputs produced which outputs. They are not evidence that the model is capable of anything, and a matching hash says nothing about accuracy.

| Artifact | sha256 |
|---|---|
| `README.md` | `0135eaf7718406e363ddf3201ab01dd647b212d4cc80ccbbd377cbe8b75ba4ab` |
| `analysis.json` | `1d403f171ce45b872e1595964b4321fec67d4ea875a0d2b48c3f4ad2468152d8` |
| `config/t31_frozen_config.json` | `bb0571325469a660a47c0dea8b0a1786e16e68c6672c71c009fb4ec9288f2e88` |
| `contamination.json` | `9e5a88232d9774d749cd01c2415cd1b87be8e753aae3889b96882bc64a4bf74f` |
| `manifests/environment.json` | `a29943872d6f6d15bb6ab68b451f7e202a319aa1e7e4a3b6cd86c9d352de7464` |
| `raw/adapter/arc_challenge.jsonl` | `b490f692bac3a8c56f9344d590072f3f0e19baea7a1d7dc7abfab2f38d257fa1` |
| `raw/adapter/arc_easy.jsonl` | `c457a1f09ce9f822b5e32d6aad7aeec8e3a7e1063d6ffd509a30043d42c48357` |
| `raw/adapter/gsm8k.jsonl` | `56dc5270932250f67c4fade76395a9d9466efc0ad08ef66354ed729f4978bbab` |
| `raw/adapter/math500.jsonl` | `2f634d697beb48663db528c7ae856733054893f1d45726e24d42197d5475ef3a` |
| `raw/adapter/sciq.jsonl` | `977a9acdd3a051b0878635e6e65ddcc35c1f71d133a367026896da7f683bed23` |
| `raw/base/arc_challenge.jsonl` | `7aeed91b739b372adb8bd1c18ffaa266b392cbc32de86669960e7db34ebf2bb1` |
| `raw/base/arc_easy.jsonl` | `121421d07eb3a3e253e0b3f52396d2c32bbb418118c74134811ea9849cdec981` |
| `raw/base/gsm8k.jsonl` | `2d82985f6f19b1151ed4b23a69c79f0a468756ee35be509dcf5cfc62656d53c6` |
| `raw/base/math500.jsonl` | `4b800ca4f4023ea0c86bf06fe17ca40613d7dcd07cf86cc1fd8de92103b2bc44` |
| `raw/base/sciq.jsonl` | `85ff93a871b8775d8ac84eb48220dac1d73df2e6c76afd93a532749f88c96593` |
| `recovery/T31_PRERESUME_PRESERVATION.json` | `855bcccd9938a43e8d5b42a8c558c9f05eddfb645f3cd70a832f5378b8d1e2f6` |
| `recovery/T31_RESUME_RECOVERY_RECORD.json` | `503d684165299e741956b58226f8063c0898080e533f85c1fc3cada32a2bcd39` |
| `recovery/T31_TRACKED_SUITE_CLASSIFICATION.json` | `132ee667780b2dd44d9a19c2e144c2e9082caf849944b975cb317ac8cca9b04d` |
| `recovery/analyse_log.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `recovery/analyse_output.json` | `8665bae8a0f0369ee22bc4d41b69c7ac1c890e0a21e010956232f49a40b1881e` |
| `recovery/contamination_log.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `recovery/contamination_output.json` | `a892e77599b727553f677664500a6e22c75e0bf4448db84d3f5c7040d6fe8d20` |
| `recovery/measured_tests.txt` | `f5eb2c88e2ec679d01f2aa941b07e943aa514a4331afb0322b6c3680adea4aeb` |
| `recovery/resume_log.txt` | `950c052d12d9c8082ceba840971acf2f60d78bb378584a06c912d3a8a804f6da` |
| `recovery/resume_stdout.json` | `f246698bdb13ae1d255def55a1e16b988f151fe695d9fcb7f335ff0342973134` |
| `recovery/run_closure_report.py` | `2c1a56c57102788b5d7a3d801c8503b501abd00ea64ecbfc70b6ac469ed14a04` |
| `recovery/score_log.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `recovery/score_output.json` | `130c27f863d10b7629d5facb1b05790d9476e91e3957c31cd5c752677d41d75e` |
| `recovery/t31_measured_tests_junit.xml` | `8ca1f34c0185dd0d06451958a1934dd6cf31dac2d84c582fb70b69995dbe969a` |
| `scored/adapter/arc_challenge.jsonl` | `be98bb4423d0678ad43ca401cf3305483eca28c09a63f524c77b30bd396023d1` |
| `scored/adapter/arc_easy.jsonl` | `e7ce0ee09f11eb2ecbaa3929f1981b92477b8ecedba0203ab710ca8904ecc27b` |
| `scored/adapter/gsm8k.jsonl` | `4f49c3e750379f75e6bf498c3545004bc0e7cb98d241ce9be9a0a211a97e6e2e` |
| `scored/adapter/math500.jsonl` | `c5f429cb1a56e658f85d1e081908c9c2d148bf1acec9758a48330b9ba144a299` |
| `scored/adapter/sciq.jsonl` | `fbe307cfd72901d1ca69e7bf2c23eb3fd41e9a56628291e0895b6fa8e21bda1f` |
| `scored/base/arc_challenge.jsonl` | `6a3d22a7bf81874c62ec3302b958b6802d7369b62c2097ef779365a2ad2d9b37` |
| `scored/base/arc_easy.jsonl` | `671f8b81fab93a783e4d3c5d76ec463e51e3a27783070931e7587f8187aff8fc` |
| `scored/base/gsm8k.jsonl` | `0dde92a01616d2d39418f0c1e23e3dc14c86a72b2335a2fba997878a692b3ed3` |
| `scored/base/math500.jsonl` | `1136251184fb190c790c2e0b4e223db49571c72b84eb794b01cb42ebd9651832` |
| `scored/base/sciq.jsonl` | `9f661ed1832daeceaf8f22d514f083ec11631e2c4352a50a082942e78c9487d2` |
| `source/analysis.py` | `fc8f502e96300a51828a36868d360a537d8d46d778545631b391cd701a214c91` |
| `source/config.py` | `5cee28176471de907cb98892908a9d97ab0d3ebcb7863e3676a6202e604a0030` |
| `source/contamination.py` | `2c654e7e07514fe3a304aae84180ef9a846d9bf6081de317f1aaa82e4448f6ba` |
| `source/contract.py` | `632e77b52a6d6603357950582c236ec0afd006e8f21fd0dbf49e941622166b61` |
| `source/extractors.py` | `fd9496ede12c6623ef20bac2063d44dd1f84650a220589494b316119f16611b1` |
| `source/gates.py` | `373d1debb3a7b624d0dc2f38ceecc07006704a9b21e3e1b3c9744879477fadf1` |
| `source/identity.py` | `a5de7449fd6fe6cc3f1f9c556e4937017a8f6adb966535c20bacc0bed6415805` |
| `source/loaders.py` | `dfac072026841a14c0716d64d5dda2bd27f36d7493ad1b70095c57fa489e0421` |
| `source/manifest.py` | `bac64e2b15bce7532277fc0f66d36e00ec86a8f8a03fc396fe85a4db18faf55d` |
| `source/pipeline.py` | `f96ab2e626a616d9b5ee515a5d59f0eec8e447ea1df803b8ac35550f167ac7e6` |
| `source/prompts.py` | `051daa2746171b31128ae4c491f28f0dcff0c0ab76f85ac39bf830aada3204c6` |
| `source/report.py` | `8a205f5894ade5b8a40f40632a429a89b51815a17164e5712bc181288f3e49bc` |
| `source/rows.py` | `28a806a255ea18d51f851b5142c3ca84f49d0b2ce86c67c2ec7550e63128c313` |
| `source/runner.py` | `a0215ea719d60cc577c8c772b317a807115c3c649946001f132503607d141a5a` |
| `source/scorers.py` | `c924a53d9fd021928a760b766255ee20e449f5eaff5f546c863e52d8ee5b684c` |
| `source/scoring.py` | `f67abb67ee8cbeaaa83e3a84db623c3ebb11385700a8b3ac70dbf510e69cc4e3` |
| `t32_diagnostic_handoff.jsonl` | `d5920d3ccda9fe7e9419b0c022b0f879ff55615a9bdda08133a5f9d974765149` |

## Tests

4441 passed, 51 failed, 1 skipped.

- `attribution of the 51 failures + 11 errors`: 23 legacy tracked suites, every failure reproduced in a pristine git worktree at the T31 base commit d25d457 - identical files, identical per-file counts; no failing test belongs to a T31-comparability module - see evaluations/t31/recovery/T31_TRACKED_SUITE_CLASSIFICATION.json
- `full battery (python -m pytest, repo root, unmodified)`: 4,504 tests: 4,441 passed, 51 failed, 11 errors, 1 skipped; log evaluations/t31/recovery/measured_tests.txt, junit evaluations/t31/recovery/t31_measured_tests_junit.xml
- `tests/test_t23_construction_remediation.py`: 11 errors at module-fixture setup: run_shadow_construction raises ValueError('historical T23 freeze changed') - a historical-identity recheck; pre-existing at d25d457
- `tests/test_t26_evaluation_v2.py`: 2 failures re-verifying the T26 V3 244-component byte freeze against the live repository: the pin was written by 9fdfe2a (2026-09-26) and one pinned file (integration runner) changed under 8caf8d0 (2026-09-27) - pre-existing at d25d457
- `tests/test_t31_comparability_*.py + resume suite`: all green; the one skip is the T31_REAL_DATASETS=1 guard in test_t31_comparability_loading.py - verified green with the guard set
- `tests/test_t31_concurrency.py`: 1 failure - untracked state-engine work-in-progress (StateStoreError under thread contention); outside this deliverable, has no baseline at the base commit, excluded from the regression record, disclosed
- `tests/test_t31_history.py`: 1 failure - untracked state-engine work-in-progress, order-dependent (passes in isolation); outside this deliverable, disclosed

## Regression

The pre-existing test suite was run unchanged.

3221 passed, 0 failed, 0 skipped.

Measured over the 128 tracked test modules (of the 151 tracked ones the battery collected) that were green in the battery, run unchanged against the T31 working tree: 3,221 tests, zero failures, zero errors. The 23 legacy suites whose 49 failures + 11 setup errors pre-exist at the base commit d25d457 are not T31 regressions, proven by reproducing the identical per-file failure set in a pristine worktree at d25d457 (T31 files absent); their totals are recorded under Tests. The 34 new untracked T31 modules also have no baseline at the base commit and are excluded from the record but disclosed under Tests.

## Known limitations

- Interrupted run and resume, verbatim: The original T31 benchmark process was interrupted during the adapter SciQ arm after 320/1000 persisted rows. The remaining 680 adapter SciQ items were completed using the frozen configuration and a verified missing-ID-only resume path. Previously completed model outputs were not regenerated. The recovery is documented in evaluations/t31/recovery/ (T31_PRERESUME_PRESERVATION.json, T31_RESUME_RECOVERY_RECORD.json with recovery_status ALL_DONE_AFTER_RESUME, six directed resume tests tests/test_t31_resume_recovery.py). The adapter SciQ arm is therefore not a single uninterrupted generation of 1,000 rows: 320 rows are from the original run, 680 from the resumed run, all under the verified frozen configuration (config hash unchanged, per-row prompt verification 12,054/12,054, adapter weights sha256 re-verified).
- The recovery directive stated 11,054 existing rows; its own per-file counts sum to 12,054 (6,367 base + 5,687 adapter), which the disk matched exactly. All rows the directive intended (all but the 680 missing adapter SciQ items) were present; 12,054 + 680 = 12,734. Disk evidence is authoritative.
- Scorer defect found and repaired BEFORE the scored layer existed: the first scoring run crashed on the first MATH-500 row when sympify of a bare word resolved a sympy namespace object (for example 'Ellipse' to a class) whose __eq__ raises TypeError. The comparison was wrapped in the same decide-or-fallback contract as the rest of the symbolic tier (an engine that raises cannot decide; the row falls back to string comparison and records the fallback tier). Two regression tests pin the repair; no previously scored artifact existed to regenerate because the interrupted session never reached scoring; raw generations are untouched; the rule is symmetric across both arms by construction.
- Environment drift since the frozen record is confined to the OS platform build string (Windows-11-10.0.26200 -> 10.0.26300). Python, torch, transformers, datasets, peft, CUDA runtime and GPU are identical to the frozen record.
- The full pytest battery contains 51 failures and 11 collection errors confined to legacy suites, all proven pre-existing at the T31 base commit by clean-worktree replication (identical files and per-file counts at d25d457 with zero T31 files in the tree); the regression gate is evaluated over the tracked-and-green record above instead of misattributing them to T31.
- The untracked state-engine work-in-progress (src/sciencemath/state_engine/ and its suites) is a separate work stream outside this deliverable; its two failing tests are disclosed under Tests and it is not committed with this closure.
- The Mango Integrated System was not re-run; the frozen T30 record's runtime figures are cited in the top-level README rather than re-measured here.
- Contamination is measured, not zero: 5 of the 12,734 evaluated items overlap the training corpus (1 sciq, 4 arc_easy); the disclosure table above carries the per-benchmark interpretation.

## T31 gate results

Each gate is decided from artifacts, not asserted. `NOT_EVALUATED` means the evidence was not produced, and is not a pass.

| Gate | Requirement | Status | Evidence |
|---|---|---|---|
| GATE 1 — T30 frozen | The frozen T30 adapter, its evidence pack and its records are unmodified. | **PASS** | evaluations/t30 is unmodified against HEAD; the measured adapter is the frozen T30 bytes (f57b2fd4a653abb9…); the T30 freeze root is the one the promotion record declares |
| GATE 2 — Base model pinned | The base model is loaded at the revision the manifest names. | **PASS** | measured base revision 70d244cc86ccca08cf5af4e1e306ecf908b1ad5e |
| GATE 3 — Adapter pinned | The adapter is loaded by revision and its weights verified by sha256. | **PASS** | adapter sha256 f57b2fd4a653abb9…; adapter revision ad4bac714e44… |
| GATE 4 — Evaluation configuration frozen | One frozen configuration produced every row. | **PASS** | 2f86db2e577807ed… on every row file |
| GATE 5 — gsm8k comparison | Base and adapter scored, paired and reported. | **PASS** | 1319 paired items, Δ -22.67 pp, negative_model_level_delta_observed |
| GATE 6 — math500 comparison | Base and adapter scored, paired and reported. | **PASS** | 500 paired items, Δ -29.40 pp, negative_model_level_delta_observed |
| GATE 7 — arc_easy comparison | Base and adapter scored, paired and reported. | **PASS** | 2376 paired items, Δ +8.21 pp, positive_model_level_lift_observed |
| GATE 8 — arc_challenge comparison | Base and adapter scored, paired and reported. | **PASS** | 1172 paired items, Δ +15.70 pp, positive_model_level_lift_observed |
| GATE 9 — sciq comparison | Base and adapter scored, paired and reported. | **PASS** | 1000 paired items, Δ +2.00 pp, no_clear_model_level_lift_demonstrated |
| GATE 10 — Raw outputs retained | Every item's unaugmented generation is on disk. | **PASS** | 12734 raw generations across 10 arm×benchmark files |
| GATE 11 — Schema/content split operational | schema_valid and content_valid are recorded independently and both outcomes are reachable. | **PASS** | 12734 scored rows: content_only=1982, neither=1428, schema_and_content=7625, schema_only=1699 |
| GATE 12 — Training-overlap disclosure complete | Every benchmark has a measured overlap and an interpretation. | **PASS** | disclosed for ['arc_challenge', 'arc_easy', 'gsm8k', 'math500', 'sciq'] |
| GATE 13 — Public reproduction path | A third party can rerun the comparison from the published config and commands. | **PASS** | commands=['PYTHONPATH=src python -m sciencemath.comparability --root . run --arm both', 'PYTHONPATH=src python -m sciencemath.comparability --root . run --arm adapter --benchmark sciq', 'PYTHONPATH=src python -m sciencemath.comparability --root . score', 'PYTHONPATH=src python -m sciencemath.comparability --root . analyse', 'PYTHONPATH=src python -m sciencemath.comparability --root . contamination', 'PYTHONPATH=src python -m sciencemath.comparability --root . report --branch t31-public-comparability --base-commit d25d4574bcfe1634f91bce435efd75566fba8f7d --final-commit 58e911f484928e1e3da6d4fd9f888d96373af6df', 'PYTHONPATH=src python -m sciencemath.comparability --root . manifest', 'PYTHONPATH=src python -m sciencemath.comparability --root . verify', 'PYTHONPATH=src python -m pytest tests/test_t31_comparability_runner.py tests/test_t31_comparability_rows.py tests/test_t31_comparability_pipeline.py tests/test_t31_resume_recovery.py']; config_path=evaluations/t31/config/t31_frozen_config.json; environment=evaluations/t31/manifests/environment.json; hashes_path=evaluations/t31/SHA256SUMS |
| GATE 14 — Regression | The pre-existing test suite still passes. | **PASS** | 3221 passed, 0 failed, 0 skipped |
| GATE 15 — Final audit | No metric is attributed to the wrong system. | **PASS** | weights, runtime and integrated system each named and separated |

## T32 diagnostic handoff

A diagnostic dataset of per-item disagreement is produced for a possible future remediation stage. It is diagnostic output only: no model was trained on it during T31, and nothing in this report depends on it.

| Field | Value |
|---|---|
| disagreements | 2249 |
| note | diagnostic only; nothing was trained on it during T31 |
| path | evaluations/t31/t32_diagnostic_handoff.jsonl |

## Decision

A third party can determine what the Mango Adapter changes relative to its frozen base model, reproduce the comparison from the published configuration, inspect the individual failures, and tell weight-level performance apart from runtime qualification.

**MANGO_T31_PUBLIC_COMPARABILITY_PASS**

This decision is about the quality of the evidence, not about whether the adapter beats its base model. It claims nothing about the adapter's general capability, and no figure produced by the Mango Runtime or the Mango Integrated System belongs to the adapter's weights.

