# T10 FINAL REPORT — Correction Recall Uplift and 4B System Promotion Closure

**Date:** 2026-09-07
**Status:** COMPLETE — all T10 phases executed (T10.0–T10.25)
**Production system:** `Mango-v0.1` (Qwen3-1.7B + T3 adapter) — unchanged, untouched, not deprecated
**Candidate:** `MANGO_4B_SYSTEM_PROMOTION_CANDIDATE` (Qwen/Qwen3-4B-Instruct-2507, no Mango weight adapter)
**T9 closure honored:** no T9 work reopened; no base weights retrained; correction firewall trust semantics (`FeedbackTrust`/`CorrectionDecision` mapping in `src/sciencemath/executive/correction.py`, module sha `f6c23e3d…`) unchanged and verified byte-identical to the T9 freeze.

---

## 1. Entry gate (T10.0)

`evaluations/t10/t10_entry_gate.json` — **PASS 11/11** (exit-0 required to proceed).

- pytest full suite green at entry (T9 state)
- T9 final audit 43/43 PASS; T3 adapter SHA `f57b2fd4…` verified
- firewall module sha matches T9 freeze; 6 frozen suite checksums verified
- GPU idle; candidate is NOT the production default (production remains `Qwen/Qwen3-1.7B`)
- **Incident recorded:** commit 5ce04b3 had baked CRLF digests into `training/curriculum/mango-sft-v2/level1/checksums.json`. Canonical LF digests restored and `*.jsonl text eol=lf` added to `.gitattributes`. Recorded in the entry-gate artifact; no weights or eval data affected.

## 2. Correction benchmark v2 (T10.1–T10.5)

`mango-correction-eval-v2` — built BEFORE any system change, then frozen and checksummed.

| Property | Value |
|---|---|
| Questions | 194 (dev 97 / final 97) |
| Class balance | TRUE_FAIL 50 / FALSE_FAIL 50 / PARTIAL_FAIL 46 / AMBIGUOUS 48 |
| Domains | 12 (≥3 per class per domain) |
| Difficulty types | 10, recorded per case |
| suite sha256 | `36dbfd91d39c741941e4f0a285b7f16f46a28e0b6b2635b56dcba60e53f96c4c` |
| final-split sha256 | `a00ffa7a5ef34a289c1d513026be7b8ed1ec7107acc72b524258be036413018d` |
| dev/final question leakage | 0 |
| labels | mechanical or source-verified (sympy recomputation, production UnitConverterTool, atomic-mass arithmetic, source-verified fact tables, frozen-corpus substring support) — **no label exists only because an LLM asserted it** |

The T9 40-case v1 suite was NOT used for improvement; it remains a regression suite (§6).

## 3. Failure analysis first (T10.6)

The T9-stabilized system ran the v2 dev split BEFORE any change (`evaluations/t10/runs/qwen3-4b-t9arm-dev`): recall 52%, preservation 100%, partial repair 0%. The raw repair output of every un-repaired TRUE_FAIL was captured (`raw_repair_probe.json`) and classified (`evaluations/t10/correction_failure_analysis.json`):

| Finding | Count |
|---|---|
| REVERIFY_FALSE_NEGATIVE | **12 / 12** |
| MODEL_IGNORED_EVIDENCE | 0 |
| truncation / wrong-scope / not-attempted | 0 |

**The model produced a correct, complete boxed value in every single case; the reverify oracle rejected it every time** — LaTeX forms (`\dfrac{13}{12}`, `98\ \text{N}`, `3 \times 10^8`), dropped units (boxed `3500` vs expected `3500 g`), ASCII-vs-unicode symbols (`11x - 12` vs `11x − 12`). Repair capability was never the bottleneck; answer normalization and the absence of a deterministic patch path were. No system change was made before this taxonomy was populated.

## 4. Repair improvements (T10.7–T10.16) — `src/sciencemath/executive/repair.py`

Implemented after the taxonomy was populated, per its dominant findings. Trust semantics (T10.7) unchanged and re-used, not forked.

1. **Structured repair context (T10.8):** failed component, expected output type, original answer, evidence provenance, authoritative evidence — never a bare "try again".
2. **DETERMINISTIC_PATCH (T10.11):** when trust is VERIFIED (tool-recomputed) and the validated expected value is available, the value is applied directly — **zero LLM repair calls**.
3. **Component-scoped multi-part repair (T10.13):** only the failed part is repaired; protected parts are spliced back verbatim (collateral structurally impossible for patched parts).
4. **Bounded escalation (T10.9):** max TWO repair attempts; attempt 2 only when attempt 1 fails re-verification.
5. **Second-attempt safety (T10.10):** never a repair attempt (let alone a second) on UNVERIFIED/CONTRADICTED feedback or when the original answer passed verification.
6. **Science repair provenance (T10.14):** SUPPORTED (retrieval) repairs must be established by the evidence; the trajectory DEFERs otherwise — no retrieved statement is pasted into an answer merely because retrieval found it.
7. **Repair method labels (T10.12):** NO_REPAIR / DETERMINISTIC_PATCH / LLM_REPAIR_1 / LLM_REPAIR_2 / CITATION_PATCH / DEFER / REJECT, recorded per row.
8. **repair_evidence_strength (T10.15):** high (VERIFIED) / medium (SUPPORTED) / none — from provenance, never model self-confidence.
9. **Matcher normalization fix (from §3):** `normalize_symbolic` now folds LaTeX/symbol formatting variants; applied identically to every arm. No semantic loosening — units and values must still agree.

## 5. Final evaluation (T10.16) — 4 arms, identical final question IDs

97-question final split, never used for development. Wilson 95% CIs recorded.

| Arm | Correction recall | Preservation | Overcorrection | Blind | Ambiguous pres. | Partial-fail repair | Collateral | Net | Mean latency/question |
|---|---|---|---|---|---|---|---|---|---|
| **A Mango-v0.1** (1.7B+T3, firewall) | 0.76 [.57,.89] | 1.00 | 0.00 | 0.00 | 1.00 | 0.043 | 0.00 | +19 | 0.9 s |
| **B Raw 4B** (no firewall) | 0.48 [.30,.67] | 0.48 | 0.52 | 0.86 | 0.08 | 0.043 | 0.96 | −1 | 16.6 s |
| **C T9-stabilized 4B** | 0.60 [.41,.77] | 1.00 | 0.00 | 0.00 | 1.00 | 0.000 | 0.00 | +15 | 2.9 s |
| **D T10-improved 4B** | **0.80 [.61,.91]** | **1.00** | **0.00** | **0.00** | **1.00** | **0.783** | **0.00** | **+20** | **0.3 s** |

### Pre-registered promotion gates vs arm D (thresholds frozen before results: sha `1ea248ae…`)

| Gate | Target | Arm D | Verdict |
|---|---|---|---|
| false-feedback preservation | ≥ 0.95 | 1.00 | **PASS** |
| overcorrection | ≤ 0.05 | 0.00 | **PASS** |
| blind agreement | ≤ 0.05 | 0.00 | **PASS** |
| ambiguous preservation | ≥ 0.95 | 1.00 | **PASS** |
| correction recall | ≥ 0.80 (preferred 0.85) | 0.80 | **PASS** (target hit; preferred not reached) |
| net correction benefit | > 0 | +20 | **PASS** |
| partial-fail repair materially improved | vs arm C 0.000 | 0.783 | **PASS** |

Raw-4B replication confirms the T9 finding at larger scale: without the firewall the raw model over-corrects (52%), agrees blindly with false feedback (86%), and destroys multi-part answers (96% collateral) — the firewall is load-bearing.

**Latency (T10.22):** arm D is the fastest correction path (0.3 s/question mean, vs 2.9 s for the T9-stabilized arm) because 74% of repairs are deterministic patches with zero generation cost. Token/latency per question recorded per row.

## 6. T9-v1 regression (T10.17)

40-case v1 suite, both 4B arms, identical scoring:

| Arm | Recall | Preservation | Overcorrection | Blind | Net |
|---|---|---|---|---|---|
| T9-stabilized (re-run) | 0.60 | 1.00 | 0.00 | 0.00 | +6 |
| **T10-improved** | **0.70** | **1.00** | **0.00** | **0.00** | **+7** |

The re-run stabilized arm reproduces the T9 baseline exactly (60/100/0/0/+6); the improved arm strictly improves it. **No regression.**

## 7. Capability protection reruns (T10.18–T10.21)

Candidate = Qwen3-4B-Instruct-2507 with T4 tools / verifier / T5R / extraction layers unaltered. All four gates match the T9 baselines.

| Suite | Gate | Target | Result | Verdict |
|---|---|---|---|---|
| T10.18 T4 verifier selftest (788 cases) | verifier false-PASS rate | 0 | 0.000 (gold pass 1.000) | **PASS** |
| T10.19 T5R frozen RAG (82 q × 2 variants) | fabricated / unsupported / invalid citations | 0 / 0 / 0 | 0 / 0 / 0 (12 cited answers, all valid) | **PASS** |
| T10.20 generalization capacity (131 q) | overall accuracy floor | ≥ 0.75 | **0.840** (110/131) | **PASS** |
| T10.21 extraction benchmark (20 cases) | wrong-final-answer acceptance | 0 | 0.0 (recall 0.70, precision 0.737) | **PASS** |

Notes recorded for honesty: extraction `false_extraction_acceptance` measured 0.25 — gated metrics all pass; this secondary rate is flagged for the Scientific Computing phase. T5R: G (with retrieval+citation) 0.586 vs NORAG 0.569 — the retrieval layer's contribution is small but its citation integrity is intact. Capacity ran fresh with the T10 layers present (planning pass + self-correction pass + decomposition subset on the same candidate).

## 8. No-training constraint honored (T10.23)

No LoRA/adapter was created (`Mango-4B-Correction-Experimental` NOT created — T10.24 optional trigger not met: system-level methods achieved the target). No base weights changed. The production model remains `Mango-v0.1`.

## 9. Final audit (T10.25)

`evaluations/t10/final_audit.json` — **all 13 checks PASS** (exit 0):

| # | Check | Result |
|---|---|---|
| 1 | v2 suite integrity (byte sha + final-split digest vs frozen targets) | PASS |
| 2 | promotion targets unchanged (pre-registered sha `1ea248ae…`) | PASS |
| 3 | 4 arms on identical final question IDs (= suite final split) | PASS |
| 4 | safety gates (preservation 1.00 / overcorrection 0.00 / blind 0.00 / ambiguous 1.00) | PASS |
| 5 | capability gates (recall ≥ 0.80, net > 0) | PASS |
| 6 | partial-fail repair materially improved over arm C (0.783 > 0.000) | PASS |
| 7 | T9-v1 regression: no safety regress (70 vs 60 recall, safety flat) | PASS |
| 8 | T4 false-PASS = 0 | PASS |
| 9 | T5R citation integrity (0/0/0) | PASS |
| 10 | generalization floor (0.840 ≥ 0.75) | PASS |
| 11 | extraction wrong-final acceptance = 0 | PASS |
| 12 | repair method labels on every arm-D row | PASS |
| 13 | latency accounting (all arms, mean s/question) | PASS |

Audit-script correction recorded: check 1 initially FAILed because the audit recomputed the final-split digest from sorted eval-IDs while the builder froze it over the full final-split row objects (`scripts/t10_build_correction_v2.py:1536`); the audit now mirrors the builder's digest. The suite bytes never changed — `questions.jsonl` sha matched all three frozen records on every run, and `promotion_targets.json` remained byte-identical throughout (targets_unchanged PASS on both runs). No data or target was modified; only the audit's recomputation was fixed.

## 10. Promotion decision

**Decision: `PROMOTE_4B_SYSTEM_ARCHITECTURE`** — the 4B system architecture (Qwen3-4B-Instruct-2507 + firewall + T10 repair layer + tool/verifier/retrieval/extraction stack) is promoted as a system, named **`Mango-4B-System-v1`**.

- **Weight promotion: NO.** No new weights were trained; no adapter exists; Mango-v0.1 (Qwen3-1.7B + T3 adapter) remains the production system and is not deprecated.
- The name is `Mango-4B-System-v1` — explicitly **not** Mango-v0.2 (per constraint: no weight promotion → no version bump).
- The T10 repair layer (`src/sciencemath/executive/repair.py`) is part of the promoted system architecture; the firewall's trust semantics are unchanged from the T9 freeze.

## 11. Test evidence

Full pytest: 764 passed / 0 failed / 0 errors / 0 skipped-in-t10 (19 new T10 tests: repair escalation bound, two-attempt limit, no second attempt on UNVERIFIED/CONTRADICTED, deterministic patch, protected-component preservation, collateral-change scoring, v2 integrity, final-set isolation, promotion-target freeze, repair method labeling, normalized matching).

---

## Dominant Remaining Bottleneck

**Correction recall on SUPPORTED (retrieval-evidence) science-fail cases: the 4B sometimes fails to apply retrieved evidence even in a structured repair context, and the fail-closed DEFER leaves those answers un-repaired** (all 4 still-wrong dev TRUE_FAIL and 5 DEFER'd dev PARTIAL_FAIL were retrieval-backed; recall on VERIFIED/tool-recomputed failures is 100% by deterministic patch). Closing this gap needs either stronger retrieval grounding (provenance-aligned quoting) or a trained correction adapter — the explicitly deferred T10.24 path.

## Ready for Scientific Computing

YES — the Mango program's promotion question is closed: the 4B system architecture is promoted (below), Mango-v0.1 remains in production, and no further Mango work is required before opening Scientific Computing.

## Highest-Value Next Step

**Open Scientific Computing (T11) on the promoted Mango-4B-System-v1 architecture** — correction recall (0.80) is at its pre-registered target and its remaining headroom (retrieval-grounded repair) is a self-contained Mango workstream that should not block the next program phase.

STOP. Do not start Scientific Computing in this session.