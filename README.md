# Mango

**Mango** is a local-first scientific-reasoning project: a QLoRA adapter over
`Qwen/Qwen3-1.7B`, a runtime that executes bounded multi-step internal
workflows, and an evaluation layer that measures each part separately. It runs
on a 6 GB GPU; nothing here calls a cloud API.

This README is the front door to the evidence. The authoritative public
comparison of the released adapter against its frozen base model is
[`evaluations/t31/reports/MANGO_T31_PUBLIC_COMPARABILITY_REPORT.md`](evaluations/t31/reports/MANGO_T31_PUBLIC_COMPARABILITY_REPORT.md).
Numbers below are reproduced from that report and its machine-readable
artifacts; where a number is not yet measured, this file says so rather than
estimating.

Three things are named "Mango" and they are not interchangeable:

| Name | What it is | How it is measured |
|---|---|---|
| **Mango adapter** | The released LoRA weights (`ComradeRt/Mango-T30-1.7B`) | Model-only benchmarks (section 3) |
| **Mango runtime** | The execution layer that plans, calls skills, verifies, recovers | Runtime qualification (section 4) |
| **Mango integrated system** | Adapter + runtime together | Integrated evaluation (section 5) |

A runtime result is never reported as a model result, and a model result is
never attributed to the runtime.

---

## 1. What this repository contains

A local training and evaluation pipeline, not a wrapper around a hosted model:

* **Dataset pipeline** — deny-by-default license gating, normalisation,
  deduplication, group-aware splits, and a leakage gate that refuses to emit
  training files when evaluation data is found in them.
* **Training** — 4-bit NF4 QLoRA over `Qwen/Qwen3-1.7B`, adapter saved
  unmerged, with a manifest recording base revision, dataset checksums, loss
  history, environment, seed and git commit.
* **The released adapter** — `ComradeRt/Mango-T30-1.7B`, pinned at revision
  `ad4bac714e442ca5c9b20420847fcadad61a6123`, weights
  `adapter_model.safetensors` sha256
  `f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668`.
* **Runtime qualification** — private, sealed scenario material and the
  methodology that qualifies the runtime (section 4).
* **This evaluation layer** (`src/sciencemath/comparability/`) — the T31
  public comparability harness: deterministic loaders, extractors, scorers,
  paired statistics, contamination measurement, and a report generator.

**Provenance, stated plainly.** The released T30 adapter *bytes* are the
historical first training checkpoint (`training/adapters/sciencemath-v0.1-t3/`),
re-tagged as the T30 release. The T30 promotion record pins that artifact by
sha256 only. **The T30 official evaluation never measured these weights on any
public benchmark.** T31 is the first measurement of these weights on GSM8K,
MATH-500, ARC and SciQ.

## 2. Model-only benchmarks

Model-only means: weights, tokenizer, chat template, decoding and the answer
scorer — and nothing else. No runtime, no retrieval, no tools, no
verification layer. Both arms receive identical inputs under an identical
configuration; the only experimental variable is whether the adapter is
attached.

Five benchmarks, each pinned to an exact revision. Item counts are asserted
against these numbers at load time (`check`); a suite that loads a different
number of items fails rather than proceeding.

| Benchmark | Source | Config | Split | Revision | Items | License |
|---|---|---|---|---|---|---|
| GSM8K | `openai/gsm8k` | main | test | `740312add88f781978c0658806c59bc2815b9866` | 1319 | MIT |
| MATH-500 | `HuggingFaceH4/MATH-500` | — | test | `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be` | 500 | MIT |
| ARC-Easy | `allenai/ai2_arc` | ARC-Easy | test | `210d026faf9955653af8916fad021475a3f00453` | 2376 | CC-BY-SA-4.0 |
| ARC-Challenge | `allenai/ai2_arc` | ARC-Challenge | test | `210d026faf9955653af8916fad021475a3f00453` | 1172 | CC-BY-SA-4.0 |
| SciQ | `allenai/sciq` | — | test | `2c94ad3e1aafab77146f384e23536f97a4849815` | 1000 | CC-BY-NC-3.0 |

**Frozen decoding configuration** (hash
`2f86db2e577807ed8021a4b647f3fa2243762e327d6e3c22c76184520e842eff`, identical
for both arms):

| Setting | Value |
|---|---|
| Decoding | Greedy (`do_sample=false`, `num_beams=1`, temperature/top-p/top-k unset) |
| Repetition penalty | 1.0 |
| dtype / device / quantization | bfloat16 / `cuda:0` / none |
| Max new tokens | GSM8K 512 · MATH-500 1024 · ARC-Easy 32 · ARC-Challenge 32 · SciQ 32 |
| Stop token | `<|im_end|>` (151645) |
| Seed | 20260930 (greedy is seed-independent; recorded so the optional sampled arm is reproducible) |

Greedy decoding is deterministic: the same weights and prompt produce the same
output, so a difference between the two columns is not sampling noise.

## 3. Base vs adapter comparison

The same benchmark items, prompt template, chat template, decoding settings,
answer extractor, scorer, token budget and seed, run twice: once on
`Qwen/Qwen3-1.7B` at revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`
(the frozen base), once with the frozen Mango T30 adapter attached. Accuracy is
`content_valid` — the extracted answer matched the reference — not schema
compliance.

| Benchmark | Base | Mango T30 Adapter | Δ pp |
|---|---|---|---|
| GSM8K | 0.8105 (1069/1319) | 0.5838 (770/1319) | −22.67 |
| MATH-500 | 0.5980 (299/500) | 0.3040 (152/500) | −29.40 |
| ARC-Easy | 0.7946 (1888/2376) | 0.8767 (2083/2376) | +8.21 |
| ARC-Challenge | 0.6160 (722/1172) | 0.7730 (906/1172) | +15.70 |
| SciQ | 0.8490 (849/1000) | 0.8690 (869/1000) | +2.00 (p = 0.064, n.s.) |
| **Pooled (6,367 items)** | **0.7581** | **0.7507** | **−0.74** |

The adapter improves multiple-choice QA on every science benchmark and hurts
free-form reasoning on both math benchmarks, netting to a small pooled
regression (−0.74 pp). Every negative delta is shown as measured. The report
adds per-benchmark item counts, invalid-output and extraction-failure counts,
paired outcomes (both right / base only / adapter only / both wrong),
McNemar's exact test, clustered bootstrap confidence intervals,
schema-versus-content cross-tabs and an error taxonomy. Raw generations for
every item, including incorrect ones, are retained under
`evaluations/t31/raw/`.

Interruption and recovery, stated plainly: the original T31 benchmark process
was interrupted during the adapter SciQ arm after 320/1000 persisted rows.
The remaining 680 adapter SciQ items were completed using the frozen
configuration and a verified missing-ID-only resume path — every item id
already persisted was skipped, never regenerated — and the previously
completed model outputs were not regenerated. Full evidence:
`evaluations/t31/recovery/` (pre-resume byte-preservation record, the
10-phase recovery record, and the six directed resume tests).

## 4. Runtime qualification

This section is about the **runtime**, not the weights. It is quoted from the
frozen T30 promotion record; T31 did not re-run it.

| Field | Value |
|---|---|
| Capability | Integrated Internal Task Execution |
| Verdict | QUALIFIED |
| Authority | `COORDINATE_INTERNAL_WORK_ONLY` |
| Freeze | `d5671bc059d3134675b2eb7343d3deaee58bf98ad3a6aaf66d1c61ecb54db5da` (302/302 components, unmodified) |
| Official metrics | 11 / 11 PASS (floors at 1.0, `FAIL_NONVACUITY` zero-denominator policy) |
| Critical counters | 9 counters, all 0 (authority, side-effect, gold-leakage, terminal, memory-scope, provenance, schema-bypass, retry, unverified-completion events) |

The claim, verbatim from the record: *Mango can execute bounded multi-step
internal workflows across registered skills, correctly reach verified
completion or safe terminal states, and recover/replan within frozen budgets.*

The record's own `does_not_establish` list: unbounded autonomy, external
action authority, external side-effect authority, general AGI, arbitrary tool
correctness, arbitrary scientific correctness, arbitrary mathematical
correctness, deployment/release readiness, qualification of future
descendants.

## 5. Integrated-system evaluation

Adapter **and** runtime together, on a separate sealed holdout, reported here
so that a runtime number is never confused with a model number.

| Metric | Result |
|---|---|
| Scenario completion rate | 416 / 512 = 0.8125 |
| Recovery success rate | 64 / 64 = 1.0 |
| Replan correctness rate | 96 / 96 = 1.0 |
| Safe abstention accuracy | 96 / 96 = 1.0 |
| Terminal correctness rate | 512 / 512 = 1.0 |
| Verified completion rate | 416 / 416 = 1.0 |
| Verification success rate | 3720 / 3720 = 1.0 |
| Capability selection accuracy | 3976 / 3976 = 1.0 |
| Handoff validity rate | 3304 / 3304 = 1.0 |
| Plan execution adherence | 3720 / 3720 = 1.0 |
| Plan validity rate | 512 / 512 = 1.0 |

All eleven pass at the stated floors; all nine critical counters are 0.

**These are not model accuracy.** They measure whether the integrated system
reaches correct terminal states on internal workflows. They do not say the
adapter reasons better than the base model, and they are not comparable to
section 2's benchmark accuracies.

## 6. Training-data overlap disclosure

Measured by comparing all 6367 evaluated items against every record in the
training corpus (`evaluations/t31/contamination.json`). "Overlap" is not
guessed from source names; it is measured, and the measurement is reported
even when it is zero.

| Benchmark | Known training overlap | Evaluation interpretation |
|---|---|---|
| GSM8K | **Yes** — 842 records from the `train` split (`openai/gsm8k#main [train]`) | Test split disjoint from train by construction, and 0 of 1319 items measured as overlapping. Still **in-distribution**: the model has seen this task and format extensively. A score measures this kind of question, not generalization to it. |
| MATH-500 | **No** — no file references `HuggingFaceH4/MATH-500`. Training used `EleutherAI/hendrycks_math [train]` (809 records); MATH-500 is a test subset of MATH. | Held out. 0 identical; 3 of 500 items near-duplicate without the answer in the training record; 17 share a problem template but ask a different question. |
| ARC (Easy + Challenge) | **No** — `ai2_arc` is marked `eval_only`; zero ARC records in any corpus. **But** 4 of 2376 ARC-Easy items have a near-duplicate whose answer the corpus states. | ARC-Challenge is held out (0 overlap). **ARC-Easy is not claimed held out**: 4 of 2376 items (0.17%) are contaminated and are counted as such, not excluded. |
| SciQ | **Yes** — 1200 records from the `train` split (`allenai/sciq [train]`). | In-distribution. 1 of 1000 items is *identical* to a training record that states its answer — contaminated. 999 are not known to be contaminated. This overlap is also why the released adapter is licensed CC BY-NC 4.0. |

No contaminated evaluation is presented as unseen generalization. Contaminated
items are disclosed with counts and left in the denominator; they are not
quietly dropped to improve a score.

## 7. Known limitations

* **Greedy, single-seed.** The primary comparison is one deterministic decode
  per item. It cannot show decode variance, and it is not a sampled estimate.
* **32-token budget on the multiple-choice benchmarks.** ARC-Easy,
  ARC-Challenge and SciQ allow 32 new tokens. A model that explains before
  answering can be cut off; this is applied identically to both arms and
  truncated generations are labelled `truncated_generation`, not discarded.
* **The adapter is a re-tagged first checkpoint.** Its training corpus was
  small (~4k records across sources) and single-pass. Nothing here should be
  read as evidence about later training.
* **Small samples for the widest claims.** MATH-500 has 500 items; SciQ 1000.
  Differences of a few points may not be distinguishable from zero — the
  report gives intervals and McNemar's test rather than calling a small
  positive delta an improvement.
* **Model-only means model-only.** No runtime, tools, retrieval or
  verification layer is active in section 2/3 numbers. The runtime's success
  (sections 4/5) is not evidence about the weights.
* **Contamination is disclosed, not eliminated.** See section 6; GSM8K and
  SciQ are in-distribution by design, and 4 ARC-Easy items are contaminated.
* **The configuration hash pins the prompt literals, not the renderer.** The
  frozen `prompt_policy_hash` covers the policy strings only. The code that
  renders an item into those strings is pinned instead by the per-row
  `prompt_sha256` and by the verbatim source snapshot the pack carries under
  `evaluations/t31/source/`, which `SHA256SUMS` covers.
* **Unrelated work is parked.** A separate state-engine effort exists
  untracked on disk and is intentionally excluded from T31; no T31 measurement
  includes it.

## 8. Reproduction instructions

Everything below is CPU-only except the two generation commands, which need a
CUDA GPU. Set `PYTHONPATH` to include `src` (and `tests` for the suite).

```bash
# 1-2. validate the loaders and the scorer against the real datasets
python -m sciencemath.comparability check

# 3-7. freeze and hash the configuration (writes evaluations/t31/config/)
python -m sciencemath.comparability freeze

# 8. generate and capture both arms over all five suites (GPU)
python -m sciencemath.comparability run --arm both

# score the captured rows, pair the arms, measure contamination
python -m sciencemath.comparability score
python -m sciencemath.comparability analyse
python -m sciencemath.comparability contamination

# render the report + decide the gates, then write and verify the hashes
python -m sciencemath.comparability report
python -m sciencemath.comparability manifest
python -m sciencemath.comparability verify
```

The model and adapter are loaded at the exact revisions in section 2 /
section 1; the benchmark revisions are in section 2. `report` copies the
measurement source into `evaluations/t31/source/`, and `manifest` writes
`evaluations/t31/SHA256SUMS` over the config, that source snapshot, the raw
rows, the scored rows and the report; `verify` recomputes it. Runs resume from
completed rows and reject duplicates; a partial run cannot be scored as
complete.

## 9. Non-claims

* This is not state of the art, and no benchmark here is claimed as a record.
* This does not establish general reasoning ability, AGI, or broad scientific
  or mathematical competence.
* A positive delta on these benchmarks, under this configuration, is a
  measured delta on these benchmarks — not proof of generalization to unseen
  problems.
* Runtime and integrated results (sections 4/5) are not model accuracy and
  must not be quoted as such.
* Contaminated items are disclosed; no score here is presented as fully
  unseen generalization.
* The SHA256 hashes authenticate that a published result came from the
  recorded configuration and data. They are not evidence of capability.

---

## Licensing and attribution

* This repository's code: MIT (`pyproject.toml`).
* The released adapter: **CC BY-NC 4.0** (non-commercial), a consequence of
  the SciQ training overlap disclosed in section 6.
* Datasets: `data/licenses/LICENSE_MANIFEST.md` is the source of truth and is
  enforced in code. Anything unverified is excluded from training.
* `ai2_arc` is evaluation-only (CC-BY-SA-4.0); it is never trained on.
