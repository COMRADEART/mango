# T8 — Model Landscape (research/t8_model_landscape.md)

Milestone: T8 — Capacity Scaling, Base-Model Migration, and Mango-v0.2 Selection
Date: 2026-09-04

## Method

Metadata was researched FRESH from live huggingface.co model cards, raw
config.json files, and commit histories on 2026-09-04 (no remembered
metadata). Six research agents each produced a field report; separate
adversarial verifier agents then re-fetched the live pages to confirm
license ids and fine-tuning/redistribution rights. Everything here is
traceable to the per-candidate source lists.

Gate policy is deny-by-default: APPROVED requires a verified permissive
license with confirmed training + redistribution rights; anything else is
REVIEW_REQUIRED or BLOCKED. Structured form: evaluations/t8/model_manifest.json.

## Summary table

| # | Model | Params | License (verified) | Context | NF4 est. | Fits 6 GB | Training base | Notes |
|---|-------|-------:|--------------------|--------:|---------:|-----------|---------------|-------|
| Qwen/Qwen3-1.7B | 1.7B | apache-2.0 | 32k | ~3.5 GB | yes | APPROVED | control; dual-mode thinking |
| microsoft/Phi-4-mini-instruct | 3.8B | mit | 128k | ~3.7 GB | yes | APPROVED | math-tuned lineage, general instruct |
| microsoft/Phi-4-mini-reasoning | 3.8B | mit | 128k | ~4.5 GB | yes | APPROVED | COMPARATOR ONLY — forced long-CoT |
| Qwen/Qwen3-4B-Instruct-2507 | 4.0B | apache-2.0 | 262k | ~3.3 GB | yes | APPROVED | non-thinking 2507 instruct line |
| HuggingFaceTB/SmolLM3-3B | 3.0B | apache-2.0 (tag; no LICENSE file) | 128k | ~2.5 GB | yes | REVIEW_REQUIRED | dual-mode; NoPE; no LICENSE file found |
| Qwen/Qwen3-8B | 8.0B | apache-2.0 | 40k | ~7.5 GB | NO | n/a (hardware) | inference-only stretch; offload profile only |

## Key findings

- **Qwen3-4B-Instruct-2507** is the strongest current Qwen 3-4B instruct
  (Apache-2.0, 262k context, non-thinking line; newer Qwen3.5-class small
  models were checked and do not exist as of 2026-09-04). Untied embeddings
  mean the full NF4 footprint is unusually small (~3.3 GB est.).
- **Phi-4-mini-instruct** (MIT) is a serious general 3.8B candidate with
  math-tuned lineage; card notes limited factual capacity at 3.8B and
  recommends RAG for facts — directly relevant to Mango's T5R arm.
  Use `attn_implementation="eager"` or SDPA on the 4050 (flash attention
  path targets A100-class); template uses `<|end|>` eos.
- **Phi-4-mini-reasoning** (MIT) emits mandatory long-CoT `illage`-style
  reasoning blocks; expected to hurt concise science answers and latency.
  Included as comparator per the T8 protocol, NOT as a base candidate.
- **SmolLM3-3B** (HF tag apache-2.0) — verification found **no LICENSE file
  in the repo** (2026-09-04). Deny-by-default => REVIEW_REQUIRED for
  training-base use; local eval-only permitted.
- **Gemma-3-4b-it** was assessed and NOT shortlisted: Gemma custom license
  terms require review and its terms are materially more restrictive for
  training/redistribution than apache/MIT.
- **Qwen3-8B** stretch: NF4 weights alone ~4.5-5.5 GB plus KV cache and
  runtime overhead do NOT fit 6 GB cleanly; and 8B QLoRA does not fit the
  4050 at all. Inference-only with CPU-offload profile at most.
- Qwen3-1.7B control card explicitly warns against greedy decoding
  (endless-repetition degradation) — this is a MATERIAL exception to the
  matched greedy protocol; recorded per T8.7 and handled in the runner
  configuration for the control arm.

## Verbatim field reports

### Candidate 0 (Control) — Qwen/Qwen3-1.7B

FIELD REPORT — Qwen/Qwen3-1.7B (control/baseline), verified against live huggingface.co pages 2026-09-04.

EXACT HF MODEL ID: Qwen/Qwen3-1.7B (base counterpart: Qwen/Qwen3-1.7B-Base). Part of the Qwen3 collection.

REVISION: Latest main commit = 70d244c ("Create LICENSE" by littlebird13, committed 2025-07-26). No version tags on the repo.

RELEASE DATE: Model card/paper published May 14, 2025 (arXiv 2505.09388, Qwen3 Technical Report); most recent commit 2025-07-26. Downloads last month: ~3.57M.

PARAMETERS: 1.7B (1.4B non-embedding per card; safetensors panel reports ~2B total params, BF16). Hidden size 2048, 28 layers, intermediate 6144.

NF4 FOOTPRINT: ~2.03B params at 0.5 byte/param (NF4) plus double-quant metadata gives roughly 1.0-1.2 GB for weights alone. Realistic total VRAM for 4-bit inference on the 6 GB card (weights + KV cache at short/medium context + activations + LoRA adapters + CUDA/torch runtime overhead on Windows) is approximately 3-4 GB. Comfortably fits 6 GB even without offloading; device_map="auto" will place everything on GPU at modest context lengths. fits_6gb = true.

ARCHITECTURE: Qwen3 dense decoder, model_type "qwen3", Qwen3ForCausalLM. Attention: GQA — 16 query heads, 8 KV heads, head_dim 128; SDPA/flash recommended (config has no attn-implementation pin; attention_bias=false, attention_dropout=0.0). SwiGLU (hidden_act silu), RMSNorm eps 1e-06, rope_theta 1,000,000, rope_scaling null (YaRN supported as an override to extend context), sliding_window null, max_position_embeddings 40,960 (32K context + 8K generation buffer). tie_word_embeddings = true (no separate lm_head — good for LoRA: no lm_head adapter needed). No deepstack entries.

INSTRUCTION TUNING STATUS: Instruct/post-trained — NOT the base model; card training stage says "Pretraining and Post-training", a conversational chat model. The base is the separate Qwen/Qwen3-1.7B-Base repo. There is no -instruct suffix on the id; the default Qwen/Qwen3-1.7B IS the instruct variant.

REASONING/THINKING MODE: Dual-mode (hybrid thinking + non-thinking in one model) — not reasoning-only. Controlled via tokenizer.apply_chat_template(..., enable_thinking=True/False); True is the DEFAULT. Soft switches "/think" and "/no_think" in prompts are honored only when enable_thinking=True. Thinking output is wrapped in a think-tag block; token id 151668 marks the closing tag; the reasoning span must be excluded from multi-turn chat history. Not a forced long-CoT model.

CONTEXT LENGTH: Native 32,768 per the card (config max_position_embeddings 40,960); card recommends 32,768 output tokens normally and 38,912 for hard math/code benchmarks. YaRN rope_scaling can extend beyond native.

LICENSE: apache-2.0 (exact id on the model card sidebar and HF metadata). Permissive: commercial use allowed, fine-tuning/QLoRA allowed, redistribution of derivatives allowed under standard Apache-2.0 terms (retain NOTICE/license). No extra restrictions stated. Project deny-by-default license gate should PASS.

TOKENIZER/CHAT TEMPLATE: Standard Qwen3 tokenizer (byte-level BPE family, ~151k vocab) with a Jinja2 chat template present on the repo. Mango's apply_chat_template usage works; the enable_thinking flag is supported. Gotcha: strip the thinking block from conversation history in multi-turn chat. 100+ languages supported.

TRANSFORMERS COMPATIBILITY: Card requires transformers >= 4.51.0 (older versions raise KeyError: 'qwen3'). Environment transformers 5.16.1 satisfies this; Qwen3 is a first-class architecture in both 4.x (>=4.51) and 5.x. Card shows plain AutoModelForCausalLM usage; vllm >= 0.8.5 and sglang >= 0.4.6.post1 also listed.

PEFT COMPATIBILITY (LoRA target module names that exist in this architecture): q_proj, k_proj, v_proj, o_proj (attention) and gate_proj, up_proj, down_proj (SwiGLU MLP) — exactly the Mango target set. 662 adapters and 1,074 finetunes already exist in the model tree, confirming PEFT compatibility in the wild. tie_word_embeddings=true means there is no lm_head module to target.

BITSANDBYTES 4-BIT NF4 COMPATIBILITY: No architecture-specific incompatibility for the dense Qwen3 line — bnb_4bit_quant_type="nf4" with double quantization works. Known generic gotchas (bnb GitHub issues 1780 and 1141): (a) quantization temporary buffers can inflate peak memory until torch.cuda.empty_cache() is called; (b) a transformers memory regression was fixed around v4.52 — 5.16.1 is past it; (c) do NOT call prepare_model_for_kbit_training for inference-only use (it casts to fp32 and adds overhead); (d) reports were dominated by the Qwen3 MoE variants (30B-A3B), not the dense 1.7B. bitsandbytes 0.50.2 has native Windows wheels.

6 GB VRAM FEASIBILITY (NF4, RTX 4050 Laptop): Yes. Weights ~1.1 GB NF4; KV cache is small thanks to GQA (8 KV heads x 128 head_dim x 28 layers x 2 = about 57 KB per token in bf16, roughly 0.06 GB per 1K context tokens); LoRA adapters are tiny; Windows/torch runtime overhead is roughly 1.5-2 GB. Total is approximately 3-4 GB at 4-8K context. Fully inside 6 GB with margin for QLoRA-style training loops; no CPU offload needed for inference.

VOCAB/EMBEDDING: vocab_size 151,936; hidden_size 2,048; tie_word_embeddings true so embedding parameters (~311M) are shared with the output head and counted once.

WINDOWS/DTYPE/QUANTIZATION GOTCHAS: (1) DO NOT use greedy decoding — the card explicitly warns it causes performance degradation and endless repetition. Use the card's sampling settings: thinking mode Temperature=0.6, TopP=0.95, TopK=20, MinP=0; non-thinking mode Temperature=0.7, TopP=0.8, TopK=20, MinP=0; presence_penalty up to 1.5 mitigates repetition (high values may cause language mixing). (2) Exclude thinking content from multi-turn history. (3) torch_dtype is bfloat16 in config; RTX 4050 (Ada) supports bf16 natively — for bnb use bnb_4bit_compute_dtype=torch.bfloat16 (float16 also works). (4) KeyError: 'qwen3' only if transformers < 4.51 — not applicable at 5.16.1. (5) PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True is recommended for tight VRAM. (6) BF16 safetensors on disk are ~4 GB, larger than the NF4 runtime footprint — size the download/cache accordingly.

**License verification**: apache-2.0 — eligibility: APPROVED. No discrepancies.

Sources: https://huggingface.co/Qwen/Qwen3-1.7B, https://huggingface.co/Qwen/Qwen3-1.7B/raw/main/config.json, https://huggingface.co/Qwen/Qwen3-1.7B/commits/main, https://github.com/bitsandbytes-foundation/bitsandbytes/issues/1780, https://github.com/TimDettmers/bitsandbytes/issues/1141, https://huggingface.co/docs/bitsandbytes/v0.45.4/reference/nn/linear4bit

### Candidate 1 — General reasoning 3-4B: microsoft/Phi-4-mini-instruct

# microsoft/Phi-4-mini-instruct — field report

## Identity
- **Exact HF id**: `microsoft/Phi-4-mini-instruct`
- **Revision/tag**: latest main commit `cfbefacb99257ffa30c83adab238a50856ac3083` ("Update README.md (#43)", 2025-12-10). Weights were uploaded at "Added model files" `618e63e60172e9efa181cbfeee9d7012e5b2ad66` (2025-02-19); no version tags are used on this repo.
- **Release/update date**: initial release 2025-02-19; last README-only update 2025-12-10 (weights unchanged since Feb 2025).

## Size & architecture
- **Parameter count**: card text says 3.8B; repo safetensors metadata lists ~4.0B params (BF16). Treat as ~3.84B.
- **config.json (fetched raw)**: `model_type: "phi3"`, `architectures: ["Phi3ForCausalLM"]` — there is NO separate "phi4mini" architecture class in transformers; it uses the phi3 stack. hidden_size 3072, 32 layers, 24 attention heads, **8 KV heads (GQA)**, `tie_word_embeddings: true` (shared input/output embedding), torch_dtype bfloat16, hidden_act silu, rms_norm_eps 1e-05.
- **Attention**: grouped-query attention; the card recommends flash attention (tested on A100/A6000/H100, i.e. compute capability >= 8.0). On lower-CC hardware you must pass `attn_implementation="eager"`. Note: RTX 4050 is CC 8.9, so SDPA/flash-path is fine on it.
- **RoPE**: type `longrope`, theta 10000.0, partial_rotary_factor 0.75, 48-value long_factor array (max_position_embeddings 131072; original_max_position 4096; sliding_window 262144).
- **Vocab / embeddings**: vocab_size **200,064**; embedding matrix = 200064 x 3072 ≈ 0.615B params ≈ **1.23 GB in bf16** (tied, so one matrix serves input + LM head).

## Tuning status / reasoning mode
- **Instruct-tuned general model** (supervised + function-calling). Repo name carries no suffix but it IS an instruct model.
- **Reasoning mode: none.** No dual-mode, no forced long CoT, no `enable_thinking` flag anywhere on the card. The reasoning sibling, `microsoft/Phi-4-mini-reasoning`, is a separate model.
- **Derivation direction — IMPORTANT correction to the brief**: the brief said the card shows Phi-4-mini-instruct "derives from Phi-4-mini-reasoning". Fetched live card says otherwise: it only lists mini-reasoning as a sibling via a Phi-4-family navigation link, and states "The model belongs to the Phi-4 model family". The actual relationship runs the other way — Phi-4-mini-reasoning (Apr 2025) was built on top of Phi-4-mini-instruct. Phi-4-mini-instruct is NOT a reasoning-tuned derivative.

## Context length
- **128K tokens** (131072), via LongRoPE; no additional rope-scaling needed at 128K. Long multi-turn conversations can drift/repeat per the card.

## License & rights
- **License**: `mit` — identical in the YAML frontmatter (`license: mit`) and on the card. MIT license file included in repo.
- **Commercial use**: yes ("intended for broad multilingual commercial and research use"). **Fine-tuning**: yes (card ships `sample_finetune.py` using TRL + Accelerate; 190 adapters / 118 finetunes exist downstream). **Redistribution**: yes under MIT, keep the copyright notice. No extra terms, no use restrictions, no accept-gate.

## Tokenizer / chat template
- Custom 200K-vocab BPE tokenizer. Chat format is the Phi-3-style scheme: user/assistant role tags, turns closed with `<|end|>` (not `<|im_end|>`/`<|eot_id|>`). Tool calls are wrapped in `<|tool|>` / `<|/tool|>` tokens in the system prompt. Extra **placeholder tokens** exist for downstream fine-tuning.
- No `enable_thinking` flag / no thinking-mode template branches. `tokenizer.apply_chat_template` works normally. Qwen3-style thinking-block handling is NOT present.

## Compatibility
- **transformers**: card pins `transformers==4.49.0` and states "Phi-4 family has been integrated in the `4.49.0` version of `transformers`" — that is the known minimum-version note (there is no separate phi4mini arch entry; the model rides the phi3 code path). `trust_remote_code=True` is requested by the card, though with model_type phi3 recent transformers load it natively without remote code. User's **transformers 5.16.1 is far above the minimum** — phi3 is a long-established arch, but verify nothing in the 5.x major bumped default attn/rope behavior; pass `attn_implementation="sdpa"` explicitly if unsure.
- **Recommended stack on card**: torch 2.5.1, flash_attn 2.7.4.post1, accelerate 1.3.0 — user's torch 2.5.1+cu121 matches; flash_attn wheels for Windows are painful, so use SDPA (built-in) instead.
- **PEFT/LoRA**: no card-declared target modules, but the architecture is a standard dense transformer using the phi3 naming convention, so the known-valid `target_modules` are `qkv_proj`, `o_proj`, `gate_up_proj`, `down_proj` — **not** the Qwen-style split names (`q_proj`/`k_proj`/`v_proj` do not exist here; phi3 fuses QKV into `qkv_proj`, and gate+up into `gate_up_proj`). Mango's default list (q/k/v/o/gate/up/down proj) must be adapted to ["qkv_proj", "o_proj", "gate_up_proj", "down_proj"] or LoRA will attach to nothing / error.
- **bitsandbytes 4-bit NF4**: no known arch-specific issues — phi3/Phi3ForCausalLM is standard bnb-quantizable. User's bnb 0.50.2 works on Windows (>=0.43 needed). Key bnb behavior: **Embedding layers are not quantized** — with tied embeddings the 200K-vocab matrix stays bf16 (~1.2 GB), which dominates the footprint.

## VRAM estimate (NF4, 6 GB RTX 4050)
- Non-embedding params ≈ 3.84B − 0.62B ≈ 3.2B → NF4 ≈ 3.2B x 0.55 B ≈ **1.8 GB** (weights + quant states).
- Tied embedding in bf16 ≈ **1.2 GB**.
- CUDA context + activations + small KV cache (GQA: 8 KV heads x 128 head-dim x 32 layers ≈ 0.5 MB/token ≈ 0.5 GB at 32k context) → **total ≈ 3.3–4 GB peak**, comfortably inside 6 GB. bnb's default of keeping embeddings unquantized is already near-optimal here.
- **Fits 6 GB: yes**, full NF4 inference with room for a 16–32k context.

## Known gotchas
- Flash attention default assumes A100/A6000/H100-class GPUs; on other hardware pass `attn_implementation="eager"` per the card (SDPA on Ampere+ is the practical Windows choice).
- `<|end|>`-style template: do NOT mix in Qwen-style stop tokens; use the template's emitted eos (`<|end|>`).
- Limited factual capacity at 3.8B (card suggests RAG for facts); hallucinated function names/URLs in tool calling; multi-turn jailbreak susceptibility; repetition drift in long conversations.
- Windows: no special dtype gotchas beyond using bf16 weights source (compute in fp16 is fine on 4050); bnb NF4 works with the user's version pins.
- 48-value LongRoPE long_factor is config-side — no manual rope config needed.

**License verification**: mit — eligibility: APPROVED. No discrepancies.

Sources: https://huggingface.co/microsoft/Phi-4-mini-instruct, https://huggingface.co/microsoft/Phi-4-mini-instruct/raw/main/README.md, https://huggingface.co/microsoft/Phi-4-mini-instruct/raw/main/config.json, https://huggingface.co/api/models/microsoft/Phi-4-mini-instruct/commits/main, https://huggingface.co/microsoft/Phi-4-mini-flash-reasoning, https://localllms.dev/llm/microsoftphi-4-mini-instruct/

### Candidate 2 — Math/reasoning comparator: microsoft/Phi-4-mini-reasoning

FIELD REPORT — microsoft/Phi-4-mini-reasoning (verified live on huggingface.co, 2026-09-04)

1. MODEL IDENTITY
- Exact HF id: microsoft/Phi-4-mini-reasoning
- Revision: latest main commit = 0e3b1e2 ("Update README.md (#4)"), Dec 10, 2025. No version tags/releases visible — main branch only. Weight-upload commits: 661e722 "added model files", Apr 29, 2025; README updates May 1, 2025.
- Release date: April 2025 (model card); weights uploaded Apr 29–30, 2025; last touched Dec 10, 2025. Card says "Trained in February 2024" — a card typo; data cutoff is February 2025, release April 2025.

2. CORE QUESTION — GENERAL ASSISTANT SUITABILITY: NOT SUITABLE
- This is a long-CoT MATH reasoning specialist. Model card states verbatim: "This model is designed and tested for math reasoning only" and warns of factual incorrectness because 3.8B "does not have the capacity to store too much factual knowledge."
- There is NO dual-mode and NO enable_thinking flag (that is a Qwen3 concept). R1-distilled SFT makes verbose chain-of-thought its single behavior: it emits think blocks wrapping the trace before the answer on essentially every response, trained-in, not mode-gated. Traces on hard problems run 3,000–6,000 tokens; card recommends max_new_tokens=32768, do_sample=True, temperature=0.8, top_p=0.95.
- General chat, science/factual Q&A, summarization, and non-English are out of distribution. Recommended system prompt: "Your name is Phi, an AI math expert developed by Microsoft." Known long-conversation drift (repetitive/inconsistent responses) noted by the community. Benchmarks: AIME'24 57.5, MATH-500 94.6, GPQA-Diamond 52.0. Training: 150B tokens distilled from DeepSeek-R1 synthetic math (~30B tokens verified math, 8 rollouts/problem).

3. PARAMS / SIZE
- 3.8B per card; safetensors metadata lists 4B params, BF16 (~3.82B; tied embeddings make the vocab block large relative to the trunk).
- NF4 weights: 3.82B x 0.5 B = ~1.91 GB + bnb quantization state ~ 2.2–2.4 GB. BF16 safetensors ~7.6 GB — does NOT fit 6 GB unquantized.

4. ARCHITECTURE (config.json, live-fetched)
- Phi3ForCausalLM, model_type "phi3", dense decoder-only Transformer. hidden 3072, 32 layers, 24 Q heads / 8 KV heads (GQA), intermediate 8192, silu, RMSNorm eps 1e-5, tie_word_embeddings=true, torch_dtype bfloat16, no attention bias, no dropout.
- LongRoPE: max_position_embeddings=131072 (128K native), original_max_position_embeddings=4096, rope_theta 10000, partial_rotary_factor 0.75, 48-entry long/short_factor arrays, sliding_window 262144. 128K is native via baked-in LongRoPE factors; no separate user-facing rope-scaling toggle.
- PEFT target_modules (standard Phi3 names, all exist): "qkv_proj" (fused QKV — Phi-3/Phi-4-mini use a FUSED qkv_proj, not separate q_proj/k_proj/v_proj), "o_proj", "gate_up_proj" (fused gate+up), "down_proj". CRITICAL for Mango: your current q/k/v/o/gate/up/down-proj LoRA list does NOT match this arch — separate q_proj/k_proj/v_proj and gate_proj/up_proj do not exist. Use ["qkv_proj","o_proj","gate_up_proj","down_proj"] (minimum viable: qkv_proj + o_proj + down_proj).
- vocab_size 200,064 with tied input/output embeddings: embedding block ~0.61B params shared between embed and lm_head (~0.31 GB in NF4).

5. LICENSE
- MIT — stated identically in the model card License section ("The model is licensed under the MIT license") and in HF repo metadata (tag: mit). No extra terms on the card.
- Fine-tuning allowed: yes (MIT grants derivative rights; card lists 20 community finetunes and 7 adapters).
- Commercial use: yes. Redistribution: yes, under MIT terms (retain copyright notice). No usage caps, no naming requirement, no acceptable-use addendum.

6. TOKENIZER / CHAT TEMPLATE
- Vocab 200,064 (200K vocabulary vs 32K for Phi-3.5-Mini); placeholder tokens extendable to the vocab limit. bos/eos/pad all = id 199999; end-of-turn special token is <|end|>.
- Chat template: Phi-3/4 style with system/user/assistant turns delimited by <||>role<||> markers and <|end|> terminators; compatible with tokenizer.apply_chat_template. Reasoning traces are emitted inside think-tag blocks before the final answer — trained-in, so every response carries long CoT. Card's rendered view truncated the exact template string; verify from tokenizer_config.json at runtime.
- Windows note: card default is Flash Attention 2 (tested on A100/H100). On the RTX 4050 use attn_implementation="sdpa" (or "eager") — do not attempt to build flash-attn on Windows; sdpa on torch 2.5.1+cu121 handles GQA fine.

7. RUNTIME COMPATIBILITY (Mango environment)
- Card pins transformers==4.51.3, torch 2.5.1, accelerate 1.3.0, flash_attn 2.7.4.post1; config written with transformers_version 4.50.0. Mango has transformers 5.16.1 — phi3 is a first-class core architecture and remains supported in v5, so AutoModelForCausalLM + device_map="auto" should load, but the card was only tested against 4.51.3; treat 5.16.1 as untested-by-Microsoft and verify LongRoPE handling did not drift in v5.
- peft 0.20.0 + bitsandbytes 0.50.2: no known arch-specific NF4 breakage for phi3 (Phi-3 family is widely used with bnb NF4; 38 community quantized variants include 4-bit builds). bnb 0.50.2 on CUDA 12.1 is fine. Watch item: NF4 + tie_word_embeddings is supported but quantizing the shared embedding can slightly degrade math accuracy.
- Python 3.12.10 is fine for all four libraries.

8. 6 GB VRAM / NF4 FEASIBILITY — YES
- NF4 weights ~2.2–2.4 GB. KV cache (GQA: 32 layers x 8 KV heads x 128 head_dim, bf16) = 128 KB/token: 8K tokens ~1.0 GB, 16K ~2.0 GB. Activations + CUDA context ~0.6–0.9 GB.
- Estimate ~3.8–4.5 GB at 8K context, ~5.5 GB at 16K context: fits fully inside 6 GB with headroom at 8K-token contexts. The card's 32768 max_new_tokens recommendation will NOT fit on 6 GB — cap max_new_tokens ~4096–8192 and context ~8–12K. Consequence: multi-KB think blocks may get truncated mid-reasoning on hard problems.

9. WINDOWS / DTYPE / QUANT GOTCHAS
- No flash-attn on Windows: attn_implementation="sdpa"/"eager".
- Native dtype bfloat16; RTX 4050 supports bf16 — do not force float16 (overflow risk in LongRoPE-scaled attention).
- NF4 + tied embeddings + LongRoPE: no reported breakage, but quantized-embedding accuracy loss is a generic bnb concern — spot-check a few math items after quantization.
- Escape hatch: GGUF Q4_K_M (bartowski) is 2.49 GB; Ollama ships a ~3.2 GB build — a zero-torch fallback if the transformers/NF4 route misbehaves.

BOTTOM LINE: Math-only long-CoT specialist (R1-distilled, always verbose, no thinking-mode toggle), MIT-licensed, 3.8B, 128K context, NF4 fits comfortably in 6 GB (~2.3 GB weights, ~4.5 GB total at 8K context), PEFT targets are the fused qkv_proj/o_proj/gate_up_proj/down_proj (Mango's current target list must change), and Microsoft explicitly documents it as unfit for general/factual assistant use — for that role Phi-4-mini-instruct is the closer candidate.

**License verification**: MIT — eligibility: APPROVED. No discrepancies.

Sources: https://huggingface.co/microsoft/Phi-4-mini-reasoning, https://huggingface.co/microsoft/Phi-4-mini-reasoning/commits/main, https://huggingface.co/microsoft/Phi-4-mini-reasoning/raw/main/config.json, https://huggingface.co/microsoft/Phi-4-mini-reasoning/blob/main/README.md, https://tinyweights.dev/posts/run-phi-4-mini-reasoning-locally/, https://docs.vultr.com/models/microsoft-phi-4/phi-4-mini-reasoning/nvidia

### Candidate 3 — Current Qwen 3-4B class: Qwen/Qwen3-4B-Instruct-2507

# Qwen 3B-4B Class Landscape (checked 2026-09-04, live HF fetches)

## Variants checked and licenses (ALL Apache-2.0)
1. **Qwen/Qwen3-4B-Instruct-2507** — apache-2.0. Non-thinking-only instruct. Latest main commit `cdbee75` ("Update tokenizer_config.json", 2025-09-17); initial release commit 2025-08-05. 3.54M downloads/month.
2. **Qwen/Qwen3-4B-Thinking-2507** — apache-2.0. Thinking-only (auto-inserts <think>; token id 151668 splits thinking). Stronger on math (AIME25 81.3 vs Instruct's 47.4) but forced long CoT → slow and VRAM-heavy for an interactive local assistant.
3. **Qwen/Qwen3-4B** (original hybrid dual-mode) — apache-2.0. Dual-mode with enable_thinking hard switch + /think /no_think soft switch, but only 32K native context (131K YaRN, factor 4.0) and clearly superseded by the 2507 releases (e.g. non-thinking Arena-Hard 9.5 → 43.4, ZebraLogic 35.2 → 80.2).
4. **Qwen/Qwen3.5-4B** (released 2026-03-02, newest 3-4B-class model) — apache-2.0. Dual-mode (thinking by default; non-thinking via chat_template_kwargs {"enable_thinking": false}). Strongest benchmarks in class (GPQA-D 76.2, HMMT 74-77, MMLU-Pro 79.1, IFEval 89.8, 262K native → ~1M YaRN). **BUT incompatible with the Mango stack as-is**: (a) it is MULTIMODAL — "Causal Language Model with Vision Encoder", ~5B safetensors params (BF16+F32, ~1B vision tower), loaded via AutoProcessor / AutoModelForMultimodalLM, not AutoModelForCausalLM; (b) hybrid architecture 8x(3x(Gated DeltaNet→FFN)→1x(Gated Attention→FFN)) — the DeltaNet blocks have no standard q/k/v/o projections, so the current PEFT target_modules list only covers 1-in-4 blocks plus vision; (c) card requires transformers from git main at card time (Mar 2026) — transformers 5.16.1 may now support it but unverified; (d) bitsandbytes 0.50.2 (late-2024) predates this arch — NF4 on Gated DeltaNet untested, and peft 0.20.0 / bnb 0.50.2 both lag the arch. Community GGUFs note its tiny KV cache (~5x smaller than dense 4B), so it is the post-upgrade candidate, not the current pick.
5. **Qwen3.6 / Qwen3.8 (Apr/Aug 2026)** — NO 3-4B dense releases exist. Smallest are Qwen3.6-27B, Qwen3.6-35B-A3B, Qwen3.8-27B, Qwen3.8-2.4T-A95B. The 3-4B class tops out at Qwen3.5-4B. Qwen-Drive-1.0-4B is a driving VLM, not a general assistant.

## RECOMMENDATION: Qwen/Qwen3-4B-Instruct-2507
Strongest verified non-thinking instruct in the 3-4B class, and the only top-tier candidate that drops into Mango's existing stack unchanged (Qwen3ForCausalLM via AutoModelForCausalLM, standard LoRA projections, tokenizer.apply_chat_template without any thinking flags, proven bnb NF4 ecosystem: 300+ quantizations, 5,647 adapters on HF).

Exact fields:
- **HF id**: Qwen/Qwen3-4B-Instruct-2507
- **Revision/tag**: latest main commit cdbee75 (2025-09-17); no version tags
- **Release**: 2025-08-05 (initial commit)
- **Params**: 4.0B total, 3.6B non-embedding; BF16 safetensors
- **Architecture**: Qwen3ForCausalLM (qwen3), dense, 36 layers, GQA 32 Q heads / 8 KV heads, hidden 2560, rope_theta 5,000,000, tie_word_embeddings=true
- **Tuning status**: fully instruct/post-trained; non-thinking ONLY — card states it does not generate

**License verification**: apache-2.0 — eligibility: APPROVED. No discrepancies.

Sources: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507, https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507, https://huggingface.co/Qwen/Qwen3-4B, https://huggingface.co/Qwen/Qwen3.5-4B, https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/commits/main, https://huggingface.co/Qwen, https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/config.json, https://github.com/QwenLM/Qwen3.8

### Candidate 4 — Alternative architecture: HuggingFaceTB/SmolLM3-3B

# Alternative-architecture 3-4B general instruct models (non-Qwen, non-Phi) — HF landscape, fetched live 2026-09-04

## RECOMMENDATION: HuggingFaceTB/SmolLM3-3B
Strongest alternative-architecture ~3-4B instruct candidate whose license is unambiguously acceptable for Mango's deny-by-default license gating. It is also the best fit for Mango's exact stack (AutoModelForCausalLM, tokenizer.apply_chat_template with enable_thinking, PEFT LoRA on q/k/v/o/gate/up/down, bnb NF4, 6 GB VRAM).

### Recommended model fields
- exact HF model id: `HuggingFaceTB/SmolLM3-3B` (instruct; base is `HuggingFaceTB/SmolLM3-3B-Base`)
- revision/tag: main commit `a07cc9a04f16550a088caea529712d1d335b0ac1` (from HF API); no version tag
- release/update date: created 2025-07-08 (release announced 2025-07-08 in the HF blog); repo lastModified 2025-09-10
- parameters: 3,075,098,624 total (safetensors, BF16, 6.18 GB on disk). 4-bit NF4 footprint estimate ≈ 2.5 GB (roughly: ~2.81B non-embedding params at ~0.55 B/param with NF4+double-quant ≈ 1.55 GB, plus the tied embedding/lm_head matrix 128256x2048 kept in bf16 ≈ 0.53 GB, plus runtime/KV overhead). Comfortably inside 6 GB.
- architecture: SmolLM3 family (`SmolLM3ForCausalLM`, model_type `smollm3`); decoder-only with GQA (16 Q heads, 4 KV heads) and NoPE — RoPE removed from every 4th layer (9 of 36 layers, `no_rope_layers` array with interval 4), rope_theta 5,000,000 on the remaining layers; all 36 layers are full attention (sliding_window: null, use_sliding_window: false); hidden 2048, intermediate 11008, RMSNorm, SiLU. PEFT target modules `q_proj/k_proj/v_proj/o_proj/gate_proj/up_proj/down_proj` all exist under the standard Llama-style naming — Mango's existing config works unchanged; note NoPE affects positional encoding only, not the projection names.
- instruction tuning: yes — full instruct model: mid-training on 140B reasoning tokens, SFT, then APO (Anchored Preference Optimization); supports tool calling (`xml_tools`, `python_tools`)
- reasoning/thinking mode: DUAL MODE — extended thinking enabled by default; controllable via `/think` and `/no_think` system-prompt flags or the `enable_thinking` kwarg in `apply_chat_template` (a system-prompt flag overrides the kwarg — handle this in Mango's template application; force `/no_think` (or enable_thinking=False) for non-reasoning evals)
- context length: 65,536 native (max_position_embeddings 65536); up to 128k (docs mention 128k/256k) via YaRN rope_scaling (type "yarn", factor 2.0+) applied at config level
- license: `apache-2.0` — identical in the model-card metadata and HF license metadata; no gating, no acceptance flow
- commercial / training-derivative rights: yes — Apache-2.0 permits commercial use, fine-tuning, derivative models, and redistribution; HF tree shows 144 finetunes, 50 adapters, 112 quantizations, 4 merges as of the fetch. No extra terms, no prohibited-use policy, no flow-down obligations.
- tokenizer/chat template: Llama 3.2 tokenizer (128K tiktoken base + 28K multilingual tokens) with bos removed; standard BPE, no SentencePiece special handling; vocab 128256. Chat template with `enable_thinking` kwarg; eos 128012 (config) / 128001 (tokenizer doc), pad 128004. `tokenizer.apply_chat_template` works as-is.
- transformers compatibility: modeling code introduced in v4.53.0 (card says "make sure to upgrade your transformers version"); Mango's 5.16.1 is well above the floor, so recent-transformers compatibility is a non-issue.
- PEFT compatibility: standard Llama-style module names (q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj); HF docs publish an official BitsAndBytesConfig NF4 example for this exact model, so the quantize+LoRA (QLoRA) path is first-class. tied_word_embeddings=true is the only wrinkle — do not target the embedding/lm_head with LoRA (it is shared and left in bf16 by bnb anyway).
- bitsandbytes NF4: no arch-specific failure reports found; NF4 with double quant is the officially documented path in the HF docs. bnb 0.50.2 predates SmolLM3 support? — no: SmolLM3 support lives in transformers (>=4.53), not bnb, and bnb quantizes standard nn.Linear layers, so 0.50.2 works; if anything fails it would be resolved by the transformers version, which Mango already exceeds.
- 6 GB NF4 feasibility: yes, with large headroom (~2.5 GB weights+overheads at zero/short context; KV cache grows with context — 4 KV heads x 36 layers is small, but at 64k+ context budget the cache accordingly).
- vocab/embedding: vocab_size 128256, hidden 2048, tied embeddings (single ~0.53 GB bf16 matrix).
- Windows/dtype/quant gotchas: BF16 checkpoint — RTX 4050 (Ada) supports bf16, fine. No fp16 overflow issues reported. Main gotchas: (1) thinking mode is ON by default — a `/no_think` or enable_thinking=False must be set for non-reasoning tasks or evals will measure long-CoT; (2) do not pass a bos_token in tokenization (tokenizer has bos removed); (3) YaRN long-context use requires manually setting rope_scaling in the config; (4) the card's example uses flash_attention_2, which is not available on Windows — omit it (sdpa is the default and works).

## Runner-up: google/gemma-3-4b-it (fetched live)
- License: `gemma` (Gemma Terms of Use, last modified April 2026) — NOT Apache. Commercial use and fine-tuning ARE permitted ("Model Derivatives" explicitly include fine-tunes/distillations), BUT it is a gated repo, and redistribution carries flow-down obligations (embed the Prohibited Use Policy as an enforceable term, pass the Gemma Terms to recipients, Notice file, mark modified files); Google retains unilateral termination and term-update rights. For a deny-by-default pipeline this is "conditionally acceptable" with extra compliance work, not clean.
- Specs: 4B params (3.88B text: 675M embedding + 3,209M non-embedding, plus 417M SigLIP vision encoder), BF16, `Gemma3ForConditionalGeneration` (multimodal image-text-to-text), 34 layers, hidden 2560, GQA 8Q/4KV heads, 5:1 local-sliding-window(1024):global attention interleaving, RoPE 10k local / 1M global with factor-8 scaling for 128K context, QK-norm, vocab 262,144 (SentencePiece shared with Gemini 2.0). Instruct via `-it`. No thinking/reasoning mode. Requires transformers>=4.50.0. NF4 estimate ≈ 4.0-4.5 GB (embedding alone ~1.34 GB in bf16, vision tower included) — fits 6 GB but tighter, and the vision tower + ConditionalGeneration class complicates AutoModelForCausalLM loading and Mango's PEFT LoRA config. Quality edge over SmolLM3 on general/multimodal benchmarks, but license friction + multimodal plumbing make it the weaker process fit.
- Gemma 3 raw config fetched 401 (gated), so the 4B specifics above are corroborated from the Gemma 3 Technical Report (arXiv 2503.19786) and google/gemma_pytorch config.py rather than the HF config file.

## Other candidates screened and excluded
- allenai/OLMo-2-0425-3B-Instruct (Apache-2.0, ~3B, Apr 2025): genuinely open (data+weights) but benchmark-weaker than SmolLM3/Gemma at this size; its HF pages returned 401 on fetch, so details are from search summaries only (medium confidence).
- ibm-granite/granite-4.0-micro (fetched live): Apache-2.0, 3B dense, 128K context, instruct, released 2025-10-02; solid but enterprise/RAG-focused, no reasoning mode, and generally rated below SmolLM3 on general instruction quality per the comparison sources. Note: the Granite 4.0 family's MoE siblings (h-tiny/h-small) are hybrid Mamba2-attention architectures — avoid for PEFT LoRA target_modules simplicity; micro (dense) is fine but is not the strongest.
- LG EXAONE 3.5 2.4B: best-in-class instruction following for its size but EXAONE 1.1-NC license is research-only / non-commercial — fails the license gate outright.
- TII Falcon 3 3B: TII Falcon-LLM License 2.0 (commercial-with-terms) and weakest quality of the set (MMLU ~56-58); Falcon 3 7B exceeds the size budget.
- Phi-4-mini 3.8B (MIT) and Llama 3.2 3B noted for completeness but excluded per the non-Qwen/non-Phi brief and prior scoping.

## Bottom line
SmolLM3-3B wins on: cleanest license (Apache-2.0, ungated, no flow-down), full dual-mode reasoning (matches Mango's enable_thinking template handling), official NF4 QLoRA-documented path, standard Llama-style PEFT target names (zero config changes), ~2.5 GB NF4 footprint (3.5+ GB headroom on the 4050), and transformers>=4.53 floor already satisfied by Mango's 5.16.1. Runner-up Gemma-3-4b-it offers a quality/multimodal edge but gated Gemma-license compliance work, a vision tower in the checkpoint, and a tighter 6 GB budget.

**License verification**: apache-2.0 — eligibility: APPROVED. The repo contains no LICENSE file at all (tree shows only weights/config/tokenizer files; .../blob/main/LICENSE returns 404). The apache-2.0 designation rests solely on the HF metadata tag and the model card's link to the standard Apache 2.0 text, not a bundled license file. Tag itself matches the claimed license.

Sources: https://huggingface.co/HuggingFaceTB/SmolLM3-3B, https://huggingface.co/HuggingFaceTB/SmolLM3-3B/raw/main/config.json, https://huggingface.co/api/models/HuggingFaceTB/SmolLM3-3B, https://huggingface.co/blog/smollm3, https://huggingface.co/docs/transformers/model_doc/smollm3, https://huggingface.co/google/gemma-3-4b-it, https://ai.google.dev/gemma/terms, https://ai.google.dev/gemma/docs/core/model_card_3

### Stretch — Qwen/Qwen3-8B (inference-only)

# Stretch candidates, ~7-8B, NF4 on 6 GB (researched 2026-09-04)

## Recommendation: Qwen/Qwen3-8B (dense text model, Apache-2.0)

### Verdict
- **Full-GPU NF4 residency in 6 GB: NOT practical.** Estimated total at 4k context is ~7-8 GB. Works only with device_map="auto" CPU offload of a few layers (compatible with the Mango stack, but generation drops to roughly 2-5 tok/s). Viable as an inference-only stretch for science/math QA at 4k context with offload, not as a comfortably resident model.
- **Training 8B on this GPU: infeasible.** Even 8B QLoRA realistically needs ~10-14+ GB (4-bit weights + unquantized embeddings + adapters + optimizer + activations). No fine-tuning of this candidate on the RTX 4050 6 GB; the 1.7B-4B class is the training ceiling.

### Field report — Qwen/Qwen3-8B
- **Exact HF model id:** Qwen/Qwen3-8B (base: Qwen/Qwen3-8B-Base).
- **Revision/tag:** latest main commit b968826 ("Create LICENSE", 2025-07-26). No version tag. First weights upload 47719a2 2025-04-28; initial commit 2025-04-27.
- **Release/update date:** repo created 2025-04-27, weights 2025-04-28 (Qwen3 Technical Report, arXiv 2505.09388, 2025-05-14); last repo modification 2025-07-26.
- **Parameter count:** 8.2B total; 6.95B non-embedding (36 layers, hidden 4096, intermediate 12288). **NF4 footprint:** non-embedding ~6.95B x ~0.55 B/param (NF4 + double quant) ~ 3.8 GB; embeddings + untied lm_head (1.25B params) stay bf16 under transformers' default not-convert handling ~ +2.5 GB, giving ~5.2 GB with embeddings also 4-bit'd, ~6.3 GB as-loaded; add KV cache and runtime overhead.
- **Architecture:** Qwen3 dense causal LM, class Qwen3ForCausalLM, GQA (32 Q heads / 8 KV heads, head_dim 128), rope_theta 1e6, no sliding window, no MoE.
- **PEFT target_modules (all exist in this arch, already Mango's set):** q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj.
- **Instruction tuning:** fully post-trained instruct/conversational (tool calling); not base.
- **Reasoning mode:** dual-mode. enable_thinking=True default emits a thinking block (open tag "think", close tag "/think" in angle brackets) containing long CoT; hard switch enable_thinking=False in apply_chat_template; soft per-turn /think and /no_think tags in the prompt. Recommended sampling: thinking T=0.6, TopP=0.95, TopK=20; non-thinking T=0.7, TopP=0.8, TopK=20; greedy decoding warned against (repetition loops). For short-answer QA evals set enable_thinking=False or strip the thinking block from output.
- **Context length:** 32,768 native (config max_position_embeddings 40960, rope_scaling null); 131,072 with YaRN factor 4.0. 4k context is well inside native; no rope scaling needed.
- **License:** apache-2.0 on both the model card and HF license metadata; LICENSE file added in commit b968826. Commercial use: yes. Fine-tuning/derivatives: yes. Redistribution: yes (keep license/NOTICE). No extra terms.
- **Tokenizer / chat template:** Qwen2-style BPE (tiktoken/GPT-derived), vocab 151,936, untied lm_head. Standard Jinja2 chat template with the enable_thinking flag — Mango's tokenizer.apply_chat_template path works unchanged.
- **Transformers compatibility:** card requires transformers >= 4.51.0 (older versions raise KeyError: 'qwen3'). Installed 5.16.1 satisfies this. Also vllm >= 0.8.5, sglang >= 0.4.6.post1.
- **bitsandbytes NF4:** dense Qwen3 4B/8B/14B load fine; documented 4-bit problems cluster on MoE variants (Qwen3-Next-80B OOM mid-load; Qwen3-30B-A3B sometimes using more VRAM than bf16 on transformers-dev regressions). bitsandbytes 0.50.2 bundles Windows CUDA DLLs (the old missing libbitsandbytes_cuda124.dll failure was fixed by 0.43.2). Use bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=bfloat16 (RTX 4050 is Ampere so bf16 compute is right; fp16 only helps pre-Ampere), SDPA attention.
- **Windows/dtype gotchas:** pre-quantized third-party NF4 checkpoints can silently pin their own bnb_4bit_compute_dtype from config (transformers issue 47378) — prefer quantizing from the official bf16 repo; if load OOMs, let device_map="auto" place 2-4 layers on CPU.

### VRAM arithmetic at 4k context (6 GB budget)
- KV cache: 36 layers x 8 KV heads x 128 head_dim x 2 (K+V) x 2 bytes x 4096 tokens ~ 0.6 GB (GQA keeps this small).
- Weights ~5.2-6.3 GB + KV 0.6 GB + CUDA context/activations ~0.7-1 GB = ~7-8 GB total, hence nf4_vram_estimate_gb 7.5 → exceeds 6 GB; offloading ~1-1.5 GB of weights to CPU makes it fit, at a large speed cost. Community GGUF numbers agree: Q4_K_M totals ~6.8 GB at 8k context; even llama.cpp needs Q3_K_M (~5.7 GB) to stay under 6.

### Alternatives surveyed (~7-8B)
- **deepseek-ai/DeepSeek-R1-0528-Qwen3-8B** — MIT license, card explicitly says commercial use and distillation supported; DeepSeek-R1-0528 CoT distilled onto Qwen3-8B Base; same 8.2B footprint, so the same 6 GB verdict (offload-only). Reasoning-only — no non-thinking mode; always produces long CoT, which hurts short-answer QA timing; shares the R1-0528 tokenizer config, and the card says use this repo's config files, not Qwen3's. Best pick only if a forced-long-CoT comparison arm is wanted.
- **No newer Qwen 8B.** As of 2026-09 the Qwen org page shows no Qwen3.5/Qwen4 8B instruct. The small-model slot moved to Qwen3.5-9B/4B/2B/0.8B (2026-03, Apache-2.0) — but these are unified vision-language hybrid Gated DeltaNet + sparse-MoE models requiring AutoProcessor / AutoModelForMultimodalLM and transformers from git main; they break Mango's AutoModelForCausalLM + dense-LoRA pipeline and are a worse NF4 fit (~10B safetensors incl. vision encoder). Qwen4 architecture is only previewed via Qwen3.8-Flash-Next (125B-A6B MoE, 180B safetensors — far too large); the 2026 Qwen3.8 family is 27B and up.
- Llama-3.1-8B-Instruct (Llama Community License, weaker math) and Mistral-7B (restrictive research terms) are not recommended.

### Bottom line for Mango
Qwen3-8B is the right stretch candidate on every compatibility axis (license, transformers >= 4.51, PEFT, bnb, identical chat-template workflow to the 1.7B) and the wrong one only on VRAM. Treat T8.4 as an offloaded NF4 inference smoke test (~2-5 tok/s expected), record fits_6gb = false for full residency, and note that a fully resident 4k-context model on this GPU tops out around the 4B class.

**License verification**: apache-2.0 — eligibility: APPROVED. No discrepancies.

Sources: https://huggingface.co/Qwen/Qwen3-8B, https://huggingface.co/Qwen/Qwen3-8B/raw/main/config.json, https://huggingface.co/Qwen/Qwen3-8B/commits/main, https://huggingface.co/api/models/Qwen/Qwen3-8B, https://huggingface.co/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B, https://huggingface.co/Qwen/Qwen3.5-9B, https://huggingface.co/Qwen?sort_models=downloads, https://huggingface.co/ikarius/Qwen3-8B-Abliterated-NF4

