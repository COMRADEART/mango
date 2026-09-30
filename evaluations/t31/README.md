# T31 evidence pack — public comparability

This directory is the T31 evaluation pack: everything needed to check, or
re-run, the base-vs-adapter comparison of the released Mango T30 adapter
against its frozen base model. The headline document is
[`reports/MANGO_T31_PUBLIC_COMPARABILITY_REPORT.md`](reports/MANGO_T31_PUBLIC_COMPARABILITY_REPORT.md).

| Path | What it holds |
|---|---|
| `config/t31_frozen_config.json` | The frozen evaluation configuration and its `config_sha256`. |
| `manifests/environment.json` | Python, torch, CUDA, transformers, datasets versions and the resolved dependency set. |
| `raw/<arm>/<benchmark>.jsonl` | One row per item per arm: the prompt, the raw generation, token counts, finish reason, latency. Nothing is discarded, including incorrect and truncated generations. |
| `scored/<arm>/<benchmark>.jsonl` | The same rows with the extracted answer, the scorer verdict, `schema_valid` and `content_valid`, and the error category. |
| `source/<module>.py` | A verbatim copy of the measurement code — the prompt policy, the answer extractors, the scorers, the loaders, the frozen configuration module — so a reader can inspect what produced a number without hunting a revision. Covered by `SHA256SUMS` like every other file. |
| `analysis.json` | Per-benchmark summaries, paired outcomes, McNemar's exact test, clustered bootstrap intervals, error taxonomy. |
| `contamination.json` | The measured overlap of every evaluated item against the training corpus, with the corpus summary. |
| `t32_diagnostic_handoff.jsonl` | Items where the two arms disagree (or both fail), for a later remediation stage. Diagnostic only — nothing was trained on it during T31. |
| `gates.json` | The fifteen gate results, decided from the evidence above. |
| `SHA256SUMS` | SHA256 of every file in this pack except itself. `python -m sciencemath.comparability verify` recomputes it. |

## What the two arms are

* **base** — `Qwen/Qwen3-1.7B` at revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`.
* **adapter** — the same model with the frozen Mango T30 adapter attached
  (`ComradeRt/Mango-T30-1.7B` at revision
  `ad4bac714e442ca5c9b20420847fcadad61a6123`, weights sha256
  `f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668`).

Both arms receive identical items, prompts, chat template, decoding settings,
answer extractor, scorer, token budget and seed. The only variable is whether
the adapter is attached.

## What "the brief's `evaluation/t31/`" became

The task brief sketched a pack at `evaluation/t31/{configs,prompts,scorers,results,raw,reports,manifests}` and asked that repository conventions win where they exist. This repository already keeps evaluation artifacts under the plural `evaluations/<task>/`, so the pack lives here as `evaluations/t31/`. Prompts and scorers are code, not data, and live in `src/sciencemath/comparability/prompts.py` and `scorers.py`; those modules — and their siblings the loaders and extractors depend on — are copied verbatim into `source/` and hashed in `SHA256SUMS`, so the code that produced the numbers travels with them. The brief's `results/{base,adapter}` is realised as `scored/{base,adapter}` (the paired comparison itself is in `analysis.json`), and there is no `integrated/` arm because T31 did not re-run the integrated system — its frozen T30 results are cited in the top-level README, not re-measured here.

## What the configuration hash does and does not pin

`config_sha256` pins every setting that produced the rows, and each row carries it so a run that changed a setting halfway through is caught rather than averaged. Within that configuration, `prompt_policy_hash` covers the prompt *literals* (`PROMPT_POLICY`, `SYSTEM_PROMPT`) only. It does not cover how an item is rendered into those templates. That gap is closed outside the configuration: every raw row records its rendered `user_prompt` and a `prompt_sha256` over it, and the renderer itself is in `source/` and hashed. A change to the option-rendering code is therefore visible per row and in the manifest, even though it would not move the frozen configuration hash — a limitation stated here rather than left for a reader to discover.

## Reading the numbers

Accuracy is `content_valid`: the extracted answer matched the reference. It is
never `schema_valid` (format compliance). The two are cross-tabulated in the
report so they cannot be conflated. A generation that could not be read at all
is an *extraction failure*, counted separately from a wrong answer, and both
count as incorrect — neither is removed from the denominator.

See the top-level `README.md`, section 9, for what these results do **not**
claim.
