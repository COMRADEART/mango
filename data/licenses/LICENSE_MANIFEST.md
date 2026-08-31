# Dataset License Manifest

One row per dataset. The `Decision` column is enforced by
`src/sciencemath/datasets/licenses.py` — the pipeline is deny-by-default: a
dataset absent from `data/manifests/datasets.json`, or whose license has not
been verified against its primary source, is EXCLUDED from training.

Verification standard applied here: the license is marked VERIFIED only when
the license statement was read from the dataset's primary page (Hugging Face
dataset card / Kaggle dataset page) on the date listed.

| Dataset | Provider | Reference | License | Verified | Training use | Redistribution | Eval only | Decision | Checked |
|---|---|---|---|---|---|---|---|---|---|
| gsm8k | huggingface | [openai/gsm8k](https://huggingface.co/datasets/openai/gsm8k) | MIT | yes | yes | yes | no | ALLOWED | 2026-08-31 |
| math-competition | huggingface | [hendrycks/competition_math](https://huggingface.co/datasets/hendrycks/competition_math) | MIT | yes | yes | yes | no | ALLOWED | 2026-08-31 |
| ai2-arc | huggingface | [allenai/ai2_arc](https://huggingface.co/datasets/allenai/ai2_arc) | CC-BY-SA-4.0 | yes | yes | yes | yes | ALLOWED (eval only) | 2026-08-31 |
| sciq | huggingface | [allenai/sciq](https://huggingface.co/datasets/allenai/sciq) | CC-BY-NC-3.0 | yes | yes | yes (non-commercial only) | no | ALLOWED (non-commercial) | 2026-08-31 |
| kaggle-unverified-candidates | kaggle | (slug added only after license verification) | Unknown | no | no | no | no | EXCLUDED | 2026-08-31 |

## Verification notes

* **gsm8k** — MIT, per the dataset card: "The GSM8K dataset is licensed
  under the MIT License." Grade-school math word problems (~7.5k train).
  Use: training + evaluation. Do not train on its test split (the pipeline's
  fingerprint/near-duplicate contamination check also guards this).
* **math-competition** — MIT, per the Hendrycks et al. MATH dataset card.
  Competition math across algebra, counting & probability, geometry,
  intermediate algebra, number theory, prealgebra, precalculus.
  NOTE: this dataset uses a loading script; with `datasets>=3.x` you may
  need `datasets<3.4` or a parquet mirror. Do not silence the failure —
  record a blocker instead.
* **ai2-arc** — CC-BY-SA-4.0 per the model card metadata. Grade-school
  science questions. Reserved evaluation-only (`eval_only: true`) because it
  is a recognized public benchmark; never enters training.
* **sciq** — CC-BY-NC-3.0 per the dataset card: attribution + non-commercial,
  no additional restrictions. SciQ crowdsourced science QA with
  supporting evidence. Use permitted for this non-commercial research
  project; do not use the corpus commercially.
* **kaggle-unverified-candidates** — placeholder. Kaggle hosts datasets under
  many different licenses (CC0, CC-BY, CC-BY-SA, CC-BY-NC, "Other", and
  dataset-specific terms). A Kaggle dataset must NOT be downloaded or trained
  on until: (1) its exact license is read from the dataset page, (2) an entry
  with `license_status: APPROVED` and verification metadata is added here and
  in `data/manifests/datasets.json`, including the `kaggle_slug`.

## Incompatible / unknown

- **kaggle-unverified-candidates** (status=REVIEW_REQUIRED): license not
  verified (license_verified=false). Excluded from training by default.

## Rules

1. Never train on a dataset whose row does not read ALLOWED.
2. Never relax `license_status` in `datasets.json` without reading the
   license text at the source and updating `checked_on`.
3. ShareAlike-licensed corpora that get mixed into training outputs may
   obligate ShareAlike distribution of derived datasets — recorded here, not
   silently ignored.