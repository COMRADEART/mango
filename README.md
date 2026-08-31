# ScienceMath-v0.1

A compact local AI assistant specialized in **mathematics and science**:
a QLoRA fine-tune of a 1.5B–4B open-weight base model, plus a deterministic
SymPy math-verification tool layer and a Wikipedia RAG system with source
attribution. Designed for a **6 GB VRAM** GPU, works on Kaggle/Colab, and
detects hardware to choose safe settings automatically.

**Status: milestones T0 + T1 complete** (repository foundation, dataset
pipeline). T2+ milestones are implemented as explicit stubs that refuse to
run rather than fake results. See [Milestones](#milestones).

---

## 1. What ScienceMath is

A training and evaluation pipeline (not a wrapper around a cloud API) that:

* solves mathematics problems and explains solutions step by step,
* verifies numeric/symbolic answers with Python/SymPy (deterministic tools,
  not model self-belief),
* answers science questions augmented by RAG over a curated Wikipedia
  corpus (with citations, and explicit uncertainty when evidence is weak),
* distinguishes retrieved facts from computed answers,
* runs fully locally after training.

## 2. Architecture

```
Kaggle / Hugging Face datasets ──► download (license-gated, REVIEW gating)
                                        │
                                        ▼
        data/raw ──► normalize_dataset ──► data/processed (canonical schema)
                                        │
                                        ▼
                          deduplicate (exact + normalized + near)
                                        │
                                        ▼
          build_splits (seeded, group-aware, domain-stratified)
                                        │   leakage check FAILS on contamination
                                        ▼
             data/{train,validation,test} + manifests/splits_summary.json
                                        │
   T2: evaluate_base.py (base model, evaluations/base/)
   T3: train_lora.py QLoRA 4-bit NF4 ─► training/adapters/sciencemath-v0.1
       evaluate_tuned.py ──► evaluations/tuned/ + BASE vs TUNED comparison
   T4: SymPy tool layer + PASS/FAIL/UNKNOWN math verifier
   T5: Wikipedia ingest ─► chunked corpus ─► FAISS index ─► retrieval + citations
   T6: run_chat.py = adapter + tools + RAG + verification + explanation levels
```

Key design rules enforced in code, not by convention:

* **Deny-by-default licensing** — `src/sciencemath/datasets/licenses.py`:
  any dataset not explicitly APPROVED (with verified license text) is
  excluded from training, and `download_*` scripts refuse unapproved names.
* **Fail-loud contamination** — `build_splits.py` refuses to emit split
  files when direct train/eval leakage is found (`LeakageError`).
* **No fake artifacts** — unimplemented milestones exit with a clear
  "BLOCKED" status; nothing pretends to train or evaluate.

## 3. Hardware requirements

| Environment | Requirement |
|---|---|
| Development (this repo's target) | Windows 11, NVIDIA GPU with ~6 GB VRAM (tested on RTX 4050 Laptop, compute capability 8.9), CUDA torch |
| Kaggle / Colab | Any free GPU tier works (P4/T4 ≈ 16 GB — comfortably above target) |
| CPU-only | Preprocessing, evaluation-logic tests, and dataset tooling work; training requires a GPU (see tests and `hardware.py`) |

`src/sciencemath/utils/hardware.py` measures VRAM and picks conservative
QLoRA settings (batch size, precision, 4-bit quantization, model size
ceiling). At ≤4 GB it disables training entirely. Settings always come from
*measured* hardware, never hard-coded.

## 4. Installation

Windows PowerShell (first-class):

```powershell
cd C:\path\to\sciencemath
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .                # core (numpy, pyyaml, sympy) — T0/T1 only
pip install -r requirements.txt # full ML + RAG stack (torch cu121 etc.)
python -m pytest                # run the test suite
```

Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -r requirements.txt
python -m pytest
```

> Torch CUDA note: install `torch` with a CUDA index if your machine has an
> NVIDIA GPU and the default wheel lacks CUDA (e.g. `pip install torch
> --index-url https://download.pytorch.org/whl/cu121`). This environment
> already ships `torch 2.5.1+cu121`, which passes `cuda.is_available()`.

## 5. Dataset setup

All corpora go through the same pipeline; nothing downloads or trains
without license approval:

```powershell
python scripts/download_kaggle.py --dataset gsm8k      # HF-backed, MIT-verified
# output lands in data/raw/, converted below with the loader mapping from
# data/manifests/datasets.json
python scripts/normalize_dataset.py --input data/raw/gsm8k__train.jsonl `
    --name gsm8k --source gsm8k --license MIT --domain mathematics `
    --question-field question --answer-field answer --solution-field solution
python scripts/deduplicate.py --name gsm8k
python scripts/build_splits.py --input data/processed/gsm8k.dedup.jsonl
```

To add a new dataset:

1. Verify its license on its source page (Kaggle/HF).
2. Add an entry to `data/manifests/datasets.json`
   (`license_status` stays `REVIEW_REQUIRED` until step 1 is done and
   recorded).
3. Regenerate `data/licenses/LICENSE_MANIFEST.md` (a generator exists in
   `src/sciencemath/datasets/licenses.py::write_license_manifest_md`).
4. Only then can `download_kaggle.py` / `normalize_dataset.py` /
   `build_splits.py` use it.

## 6. Kaggle authentication

Install kaggle CLI and put credentials in `%USERPROFILE%\.kaggle\kaggle.json`
(from kaggle.com → Account → Create New API Token) — **never in the repo**:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.kaggle" | Out-Null
# copy your downloaded kaggle.json there, e.g.:
Copy-Item "$env:USERPROFILE\Downloads\kaggle.json" "$env:USERPROFILE\.kaggle\kaggle.json"
# equivalent environment-variable form (per-process only):
#   $env:KAGGLE_USERNAME="..."  ;  $env:KAGGLE_KEY="..."
```

Linux: `mv kaggle.json ~/.kaggle/kaggle.json && chmod 600 ~/.kaggle/kaggle.json`.

## 7. Hugging Face authentication

A free account is sufficient for everything in this project (no Pro tier is
required by any component). Set the token only if you need gated models or
artifact upload:

```powershell
$env:HF_TOKEN="hf_..."      # PowerShell, current session only
python -c "from huggingface_hub import login; login(new_session=False)"   # interactive alternative
```

Linux: `export HF_TOKEN="hf_..."`. Prefer `huggingface-cli login` for a
persistent (not repo-committed) credential. The token is read from the
environment; nothing in the codebase reads or writes token files.

## 8. Wikipedia ingestion (T5)

```powershell
python scripts/ingest_wikipedia.py    # BLOCKED stub until T5
```

Design is pinned now in `configs/rag.yaml`: curated subject seeds (never a
blind dump), ~650-token chunks preserving section headings, per-chunk
metadata (title, pageid, URL, section, revision, license attribution,
chunk_id).

## 9. Preprocessing

See section 5. Quality gates implemented (all covered by tests):
exact / normalized / near-duplicate removal, malformed-answer rejection,
empty-field and length checks, unsupported-character handling, licensed
source filtering, and schema validation. A validation report
(`data/processed/dataset_validation.{json,md}`) aggregates counts by
domain/subject/source/difficulty plus duplicate, rejection, exclusion, and
split statistics.

## 10. Baseline evaluation (T2)

```powershell
python scripts/evaluate_base.py    # BLOCKED stub until T2
```

Baseline artifacts must exist under `evaluations/base/` **before** any
fine-tuning occurs (rule enforced by the T3 pipeline, not just by docs).

## 11. Training (T3)

```powershell
python scripts/train_lora.py    # BLOCKED stub until T3
```

Defaults in `configs/training.yaml` are conservative for 6 GB: 4-bit NF4
QLoRA (double quant), seq len 1024, batch 2 × grad-accum 8, LoRA r=16 across
all attention+MLP projections, gradient checkpointing, bf16 when supported
(it is, on this GPU). `hardware.auto_profile` overrides from measured VRAM.

## 12. Tuned evaluation (T3)

```powershell
python scripts/evaluate_tuned.py    # BLOCKED stub until T3; requires evaluations/base/
```

## 13. Building the RAG index (T5)

```powershell
python scripts/build_rag_index.py    # BLOCKED stub until T5
```

## 14. Local chat (T6)

```powershell
python scripts/run_chat.py    # BLOCKED stub until T6
```

Planned interface: `/math /science /rag /tools /sources /status` modes,
`concise|student|detailed` explanation levels (factual content identical
across levels), verifier output (`Verification: PASS/FAIL/UNKNOWN`) and
`/sources` listing for retrieved Wikipedia citations. No arbitrary shell
execution is exposed through the chat interface.

## 15. Testing

```powershell
python -m pytest        # 62 tests: no GPU, no downloads, <2 s
```

Covers: schema validation, normalization, license gating, deduplication,
split generation, leakage detection, report generation, hardware
recommendations (with simulated 6 GB / CPU / small-VRAM profiles), and
JSONL IO round-trips.

## 16. Known limitations (as of T1)

* **No model training or evaluation has run yet** (T2/T3 pending). No
  accuracy numbers exist and none are claimed.
* Training data coverage beyond the 4 verified sources (gsm8k, MATH, ARC,
  SciQ) is pending per-dataset license verification, especially Kaggle
  candidates.
* The MATH dataset ships a loading script; `datasets>=3.x` may require
  `trust_remote_code` (already recorded in `datasets.json`) or a parquet
  mirror. Failures must be recorded as blockers, not silenced.
* `hendrycks/competition_math` and `openai/gsm8k` answer fields carry
  LaTeX/annotations (`####` answers); T2/T4 verification must handle both.
* Near-duplicate detection is character-4-gram Jaccard — solid for copied
  text, weak for heavy paraphrases; exact leakage checking is authoritative.
* Wikipedia RAG, tools, and the chat CLI are not implemented yet; their
  scripts exit with a `BLOCKED` code instead of pretending.

## 17. Licensing / attribution

* This repository's code: MIT (see `pyproject.toml`).
* Datasets: `data/licenses/LICENSE_MANIFEST.md` is the source of truth, is
  verified against primary sources with dates, and is enforced in code.
  Anything unverified is `REVIEW_REQUIRED` and excluded from training.
* License posture of verified entries: gsm8k (MIT), MATH (MIT),
  AI2 ARC (CC-BY-SA-4.0, **evaluation only**), SciQ (CC-BY-NC-3.0,
  non-commercial).
* Wikipedia RAG output (T5) will carry CC-BY-SA attribution per chunk.

## 18. Future roadmap

* **T2** baseline model comparison (candidates pinned in
  `configs/model.yaml`: Qwen2.5-1.5B/3B-Instruct, Qwen2.5-Math-1.5B,
  Phi-3-mini) with full evaluation artifacts.
* **T3** first QLoRA adapter + BASE vs TUNED comparison report.
* **T4** SymPy tool layer + PASS/FAIL/UNKNOWN verifier + tool-use eval.
* **T5** Wikipedia RAG with attribution + retrieval quality evaluation
  (chunk-size/offset sweep guided by the eval, not a fixed guess).
* **T6** integrated assistant (modes, explanation levels, verification).
* **T7** v0.1 release: adapter, reproducible environment, release manifest.

## Milestones

| Milestone | Status |
|---|---|
| T0 — Repository foundation, configs, hardware detection, tests | **PASS** |
| T1 — Dataset pipeline (schema, licenses, normalization, dedup, splits, leakage, reports) | **PASS** |
| T2 — Base model selection + baseline evaluation | stubs (BLOCKED) |
| T3 — QLoRA training + tuned evaluation + comparison | stubs (BLOCKED) |
| T4 — Math verification (SymPy tools) | stubs (BLOCKED) |
| T5 — Wikipedia RAG | stubs (BLOCKED) |
| T6 — Integrated assistant CLI | stubs (BLOCKED) |
| T7 — v0.1 release | — |