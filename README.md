# Mango

**Mango** is a local-first scientific reasoning model specializing in
mathematics and science, combining learned reasoning, deterministic
mathematical verification, scientific retrieval, and evidence-backed
answering.

Current version: **Mango-v0.1** (balanced SFT foundation).

> Historical note: this project began as `ScienceMath-v0.1`. All frozen
> artifacts from that era (`sciencemath-eval-v1`, `sciencemath-sft-v1`,
> historical manifests, evaluation directories, and adapter directories)
> keep their original names — renaming them would break checksums and
> reproducibility. Every artifact created from the T4 milestone onward uses
> Mango naming.

A compact local reasoning system: a QLoRA fine-tune of `Qwen/Qwen3-1.7B`
plus (from T4 on) deterministic SymPy math verification and tool use, and
(from T5 on) a scientific RAG layer with source attribution. Designed for a
**6 GB VRAM** GPU, works on Kaggle/Colab, and detects hardware to choose
safe settings automatically.

**Status: milestones T0–T3 complete** (repository foundation, dataset
pipeline, base-model selection + baseline evaluation, first balanced SFT
adapter + comparison). T4 (mathematical verification/tool-use) is next.
See [Milestones](#milestones).

---

## 1. What Mango is

A training and evaluation pipeline (not a wrapper around a cloud API) that:

* solves mathematics problems and explains solutions step by step,
* verifies numeric/symbolic answers with deterministic tools (SymPy /
  Python), not model self-belief — from T4,
* answers science questions augmented by RAG over curated scientific
  sources with citations and explicit uncertainty — from T5,
* distinguishes retrieved facts from computed answers,
* runs fully locally after training.

Core design principles: **correctness > verbosity, verification >
confidence, balanced science + math > one-domain benchmark chasing,
evidence > hallucination, reproducibility > impressive demos.**

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
   T3: train_lora.py QLoRA 4-bit NF4 ─► training/adapters/* (unmerged)
       evaluate_tuned.py ──► evaluations/tuned/ + BASE vs TUNED comparison
   T4: constrained math tools (calculator / SymPy / units / numerics)
       + PASS/FAIL/UNKNOWN verifier + tool router   (next)
   T5: Wikipedia/scientific ingest ─► chunked corpus ─► retrieval + citations
   T6: integrated assistant = adapter + tools + RAG + verification
```

Target long-term shape (built incrementally, one milestone at a time):

```
USER QUESTION → ROUTER → MATH PATH (reasoning + SymPy/calculator/units)
                      → SCIENCE PATH (reasoning + scientific RAG + citations)
              → MANGO REASONER → VERIFICATION LAYER → FINAL VERIFIED ANSWER
```

Key design rules enforced in code, not by convention:

* **Deny-by-default licensing** — `src/sciencemath/datasets/licenses.py`:
  any dataset not explicitly APPROVED (with verified license text) is
  excluded from training, and `download_*` scripts refuse unapproved names.
* **Fail-loud contamination** — split builders refuse to emit files when
  direct train/eval leakage is found; the T3 corpus freeze runs a direct +
  near-duplicate contamination gate against the frozen eval suite and
  records every removal.
* **No fake artifacts** — unimplemented milestones exit with a clear
  "BLOCKED" status; nothing pretends to train or evaluate.
* **No silent checkpoint selection** — best checkpoint by validation loss,
  overfitting flags recorded, catastrophic-forgetting gate declared in
  config *before* any tuned evaluation is seen.

## 3. Hardware requirements

| Environment | Requirement |
|---|---|
| Development (this repo's target) | Windows 11, NVIDIA GPU with ~6 GB VRAM (tested on RTX 4050 Laptop, compute capability 8.9), CUDA torch |
| Kaggle / Colab | Any free GPU tier works (P4/T4 ≈ 16 GB — comfortably above target) |
| CPU-only | Preprocessing, evaluation-logic tests, and dataset tooling work; training requires a GPU (see tests and `hardware.py`) |

`src/sciencemath/utils/hardware.py` measures VRAM and picks conservative
QLoRA settings (batch size, precision, 4-bit quantization, model size
ceiling). At ≤4 GB it disables training entirely. Settings always come from
*measured* hardware, never hard-coded. T3 additionally measured worst-case
VRAM directly (micro-batch 2 OOMs at seq 1024 on 6 GB; micro-batch 1 peaks
at 4.69 GB) — see `training/smoke/t3_dry_run/vram_probe.json`.

## 4. Installation

Windows PowerShell (first-class):

```powershell
cd C:\path\to\sciencemath
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .                # core (numpy, pyyaml, sympy)
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
> --index-url https://download.pytorch.org/whl/cu121`).

## 5. Dataset setup

All corpora go through the same pipeline; nothing downloads or trains
without license approval:

```powershell
python scripts/download_kaggle.py --dataset gsm8k      # HF-backed, MIT-verified
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
3. Regenerate `data/licenses/LICENSE_MANIFEST.md`.
4. Only then can the dataset scripts use it.

## 6. Kaggle authentication

Install kaggle CLI and put credentials in `%USERPROFILE%\.kaggle\kaggle.json`
(from kaggle.com → Account → Create New API Token) — **never in the repo**.

## 7. Hugging Face authentication

A free account is sufficient for everything in this project. Set
`$env:HF_TOKEN` for the session or use `huggingface-cli login` for a
persistent (not repo-committed) credential. Nothing in the codebase reads
or writes token files.

## 8. Wikipedia ingestion (T5)

```powershell
python scripts/ingest_wikipedia.py    # BLOCKED stub until T5
```

Design is pinned in `configs/rag.yaml`: curated subject seeds (never a
blind dump), ~650-token chunks preserving section headings, per-chunk
metadata (title, pageid, URL, section, revision, license attribution,
chunk_id). Wikipedia stays a **RAG source** — it is never dumped into
training weights.

## 9. Preprocessing

Quality gates implemented (all covered by tests): exact / normalized /
near-duplicate removal, malformed-answer rejection, empty-field and length
checks, unsupported-character handling, licensed source filtering, and
schema validation. A validation report
(`data/processed/dataset_validation.{json,md}`) aggregates counts by
domain/subject/source/difficulty plus duplicate, rejection, exclusion, and
split statistics.

## 10. Baseline evaluation (T2 — complete)

`python scripts/evaluate_base.py` evaluated candidate bases on the frozen
188-question suite `evaluations/suite/v1` (`sciencemath-eval-v1`). The
selected base is **Qwen/Qwen3-1.7B** (decision in
`evaluations/base/SELECTION_DECISION.md`).

T2 operational baseline (Qwen3-1.7B, non-thinking): overall **68.62%**,
math macro **58.50%**, science macro **76.67%**, extraction success
**96.81%**. The thinking mode suffered token-budget exhaustion (36/37
extraction failures) and is retained as a secondary diagnostic only.

## 11. Training (T3 — complete)

`python scripts/train_lora.py` trains a QLoRA adapter. Defaults in
`configs/training.yaml`: 4-bit NF4 QLoRA (double quant), seq len 1024,
micro-batch 1 × grad-accum 16 (validated by measured dry-run + worst-case
probe), LoRA r=32/α=64 across all 7 linear projections, gradient
checkpointing, bf16, eval-based best-checkpoint selection
(`load_best_model_at_end` on eval_loss), and a declared
catastrophic-forgetting gate. The first adapter,
`training/adapters/sciencemath-v0.1-t3/` (historical name preserved), is
saved unmerged with a full manifest (base revision, dataset checksums,
loss history, environment, seed, git commit).

## 12. Tuned evaluation + comparison (T3)

```powershell
python scripts/evaluate_tuned.py    # frozen-suite eval of base+adapter
python scripts/compare_tuned.py    # T3_COMPARISON.md + failure analysis
```

The evaluation protocol (non-thinking, greedy, seed 42, max_seq_tokens
8192) is **declared in `configs/training.yaml` before any tuned results are
seen**, as is the forgetting gate: science macro must not drop more than
5 pp below the 76.67% reference (i.e. ≥ 71.67%), or `SCIENCE_REGRESSION`
fires.

## 13. Building the RAG index (T5)

```powershell
python scripts/build_rag_index.py    # BLOCKED stub until T5
```

## 14. Local chat (T6)

```powershell
python scripts/run_chat.py    # BLOCKED stub until T6
```

Planned interface: `/math /science /rag /tools /sources /status` modes,
`concise|student|detailed` explanation levels, verifier output
(`Verification: PASS/FAIL/UNKNOWN`) and `/sources` listing for retrieved
citations. No arbitrary shell execution is exposed through the chat
interface.

## 15. Testing

```powershell
python -m pytest        # 181 tests: no GPU, no downloads
```

Covers: schema validation, normalization, license gating, deduplication,
split generation, leakage detection, hardware recommendations, JSONL IO,
SFT formatting (budgets, closures, no `think` blocks), tokenization/label
masking, corpus freeze + checksums, contamination gate, mix-contract
quota sampling, training-config validation, checkpoint resume + manifest
provenance, LoRA attach + adapter-state detection, comparison metrics,
and the catastrophic-forgetting gate.

## 16. Known limitations (as of T3)

* The tuned adapter's full 188-question evaluation is the authoritative
  result; see `evaluations/tuned/` and `T3_COMPARISON.md` for real numbers.
* Single-pass SFT only — no curriculum, no tool use, no RAG yet. The model
  has no deterministic verification layer until T4.
* Near-duplicate detection is character-4-gram Jaccard — solid for copied
  text, weak for heavy paraphrases; exact leakage checking is authoritative.
* Training corpora remain small (2.9k examples); sciq is CC-BY-NC-3.0
  (non-commercial) and AI2 ARC is evaluation-only.
* Wikipedia RAG and the chat CLI are not implemented yet; their scripts
  exit with a `BLOCKED` code instead of pretending.

## 17. Licensing / attribution

* This repository's code: MIT (see `pyproject.toml`).
* Datasets: `data/licenses/LICENSE_MANIFEST.md` is the source of truth, is
  verified against primary sources with dates, and is enforced in code.
  Anything unverified is `REVIEW_REQUIRED` and excluded from training.
* License posture of verified entries: gsm8k (MIT), MATH (MIT),
  AI2 ARC (CC-BY-SA-4.0, **evaluation only**), SciQ (CC-BY-NC-3.0,
  non-commercial), synthetic-sft-v1 (MIT, project-generated).
* Wikipedia RAG output (T5) will carry CC-BY-SA attribution per chunk.

## 18. Roadmap

| Version | Concept |
|---|---|
| Mango-v0.1 | Balanced SFT foundation (**this release**) |
| Mango-v0.2 (T4) | Math verification + deterministic tools |
| Mango-v0.3 (T5) | Wikipedia/scientific RAG |
| Mango-v0.4 | Expanded high-quality science knowledge |
| Mango-v0.5 (T6-era) | Hard mathematics curriculum |
| Mango-v0.6 | Scientific computation/tool use |
| Mango-v0.7 | Preference/reasoning optimization |
| Mango-v0.8 | Verified synthetic curriculum |
| Mango-v0.9 | Larger-base/distillation experiments |
| Mango-v1.0 | Stable balanced science/math release |

## Milestones

| Milestone | Status |
|---|---|
| T0 — Repository foundation, configs, hardware detection, tests | **PASS** |
| T1 — Dataset pipeline (schema, licenses, normalization, dedup, splits, leakage, reports) | **PASS** |
| T2 — Base model selection + baseline evaluation | **PASS** |
| T3 — QLoRA training + tuned evaluation + comparison | **complete — see T3_COMPARISON.md** |
| T4 — Math verification + constrained tools (SymPy) | next |
| T5 — Scientific RAG | stubs (BLOCKED) |
| T6 — Integrated assistant CLI | stubs (BLOCKED) |
| T7 — v1.0 release | — |