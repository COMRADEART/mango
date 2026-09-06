# T8 final report — capacity scaling and migration selection

**Decision: DO_NOT_MIGRATE. Retain Mango-v0.1 (Qwen3-1.7B + T3 adapter).**
The resumed capacity-selection study is closed with a negative migration
decision. Qwen3-4B-Instruct-2507 is the strongest balanced follow-up candidate,
but it does not clear the existing migration gate. No Mango-v0.2 is promoted.

## Verified completion

- Five capacity runs: 131 unique questions each, 655 predictions total.
  Independent metric recomputation agrees with all five summaries.
- Two finalists, two T4 arms each: 150 unique questions per arm, 600 total.
  Exact suite-ID coverage, model IDs and aggregate comparisons verified.
- Two finalists, NORAG and adopted G RAG arms: 58 unique eligible questions
  each, 232 total. All stored aggregate metrics recompute exactly.
- Frozen capacity, tool and RAG question checksums verified. No recorded
  execution errors in the integration predictions.
- Full test suite: **707 passed**, zero failures/errors (`final_tests.xml`).
- Both Qwen3-4B training-smoke checkpoints reloaded successfully, with all
  504 adapter tensors matching exactly, active adapters and finite logits.

`scripts/t8_final_audit.py` produces `final_audit.json`, including result-file
SHA-256 hashes, coverage, recomputed integration metrics and migration decisions.
`scripts/t8_verify_reload.py` provides the independent checkpoint reload check.

## Selection evidence

| Model | Capacity overall | Math | Science | Decision |
|---|---:|---:|---:|---|
| Qwen3-1.7B control | 0.815 | 0.862 | 0.800 | Retain current base |
| Qwen3-4B-Instruct-2507 | 0.815 | 0.793 | 0.833 | Do not migrate |
| Phi-4-mini-instruct | 0.571 | 0.862 | 0.500 | Do not migrate |
| Phi-4-mini-reasoning | 0.807 | 0.793 | 0.900 | Do not migrate |
| SmolLM3-3B | 0.739 | 0.759 | 0.667 | Do not migrate |

The existing migration gate requires three capacity wins, at least 0.03 overall
gain, and no math/science regression beyond 0.05. Qwen3-4B ties overall and
regresses 0.069 in math. Phi reasoning also regresses 0.069 in math and does
not improve overall. The other candidates have larger overall/science losses.
The final audit recomputes these decisions from the saved capability vectors.

Qwen3-4B improves decomposition, compositional/counterfactual performance and
measured uncertainty. Its self-correction net is negative (-0.227), including
11/12 overcorrections under false FAIL feedback. The uncertainty diagnostic
also identifies phrase-detection limitations for Phi reasoning. Diagnostic
interpretations did not alter the frozen scoring rule.

## Finalist integration results

| Model | T4 no-tool | T4 tool | Tool gain | RAG NORAG | RAG G | RAG gain |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-4B | 70/150 | 113/150 | +28.67 pp | 33/58 | 34/58 | +1.72 pp |
| Phi reasoning | 83/150 | 103/150 | +13.33 pp | 24/58 | 29/58 | +8.62 pp |

Qwen invokes tools on 82% of T4 questions; Phi on 21.33%. These are matched
within-model integration comparisons, not proof of passing the model-only
migration gate or a fresh comparison with the deployed Mango-v0.1 pipeline.
T4 and capacity accuracies use different questions and prompts.

The verifier self-test passes 150 gold cases and has zero false passes on 638
wrong cases. That validates the deterministic verifier, not end-to-end factual
accuracy. RAG citation aggregates show zero fabricated/unsupported/invalid
references. Qwen G has citations on 12 questions; Phi G has none, so Phi's zero
count does not demonstrate citation coverage. Both score zero on source attribution.

The RAG suite has 82 questions, but only 58 belong to generation categories;
16 domain-routing and 8 retrieval-relevance items are outside these arms.
Earlier progress percentages using 82 as the generation denominator were incorrect.

## Training feasibility and limitations

Qwen3-4B completed three optimizer steps on the first 24 frozen SFT examples,
rank 32, 1024-token truncation cap, micro-batches 1 and 2. Both checkpoints
saved successfully. The original dry-run script did not implement its advertised
reload check; this closure separately verified reloads and exact adapter tensors
in `training_feasibility/reload_verification.json`.

This is a short local training smoke test, not sustained full-length training.
The truncation cap does not establish that examples occupied all 1024 tokens.
Peak reserved memory was 5760 MiB for batch 1 and 6544 MiB for batch 2 against
6140 MiB device memory. Batch 2 completed but is not established as comfortably
resident within 6 GB; memory accounting/shared-memory behavior needs further
measurement before selecting a production batch size. These are feasibility
checkpoints, not quality-evaluated releases.

## Scope of closure

- No candidate passed migration, so migration-dependent SFT adaptation,
  Mango-v0.2 training and promotion were not activated. Production configuration
  remains on the existing model/adapter; no candidate was installed as active.
- The researched Qwen3-8B stretch has no runtime probe/evaluation artifact and
  is excluded from measured conclusions. Its feasibility is not claimed here.
- Some runs record null revisions. Local config fingerprints and decoding
  profiles exist, but exact future reproduction has a commit-pinning limitation.
- Phi reasoning used the recorded 2048-token exception, versus 1024 for other
  candidates. This is not an equal-token-cost comparison.
- The preliminary `PARETO_ANALYSIS.md` local-efficiency claim is not used in
  this decision. Its producer labels disk size as a VRAM denominator and averages
  only a subset of dimensions; that field is not measured gain per GB GPU memory.
- This report closes the saved study and its executed arms. It does not claim
  every researched candidate or a new executive-system experiment was run.

`FINAL_DECISION.json` records retention and conditional work not activated.
No evaluation/training job needs resuming for this closed selection study.
