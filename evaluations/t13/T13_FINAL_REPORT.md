# T13 FINAL REPORT — SciComp Fidelity Classifier Repair and Promotion Recheck

Milestone: T13 (from commit be2819e; T8–T12 not reopened; no retraining; Mango-v0.2 not created)
System: Qwen/Qwen3-4B-Instruct-2507 (4-bit NF4 double-quant, SDPA), T12-frozen engine + T13 semantic fidelity classifier
Report date: 2026-09-10
Prohibitions honored: no LoRA, no SFT, no preference optimization, no weight editing; no Mango-v0.2; correction firewall untouched (byte-verified, sha f6c23e3d…); T8–T12 not reopened; frozen SciComp numerical engine untouched (16/17 files byte-identical to the T12.1 freeze record; the single exception, `router.py`, is the T12-authorized routing-guard end-state, unchanged by T13); no new scientific-computing capabilities; planner not broadened; parameter-fidelity protections not weakened; the 0.848 numeric threshold unchanged.

**Decision: KEEP_SCICOMP_EXPERIMENTAL** (§14).

---

## 1. Run Integrity

- **Frozen-suite discipline held.** Scicomp v1 (e6e3f048…), fidelity-v1 (f598825c…), conceptual-v1 (16d7b4d5…) and the new T13 fidelity-transform benchmark v1 (138 final cases, frozen sha256 f3bad0f8…; manifest carries the full refreeze_history) were SHA-256-verified at load in every leg. No frozen bytes modified mid-milestone.
- **Engine freeze re-verified:** 16/17 engine files byte-identical to the T12.1 freeze record. The single exception, `router.py`, is the T12-authorized routing-guard end-state — T13 modified neither it nor any solver file. Firewall (`executive/correction.py`) and adapter byte-identical.
- **Environment interruption (classified and evidenced): T13-ENV-1 — ENVIRONMENT_INTERRUPTION.** Between T13.17 completion and the phase-2 launch, `transformers` and `huggingface_hub` were externally removed from the environment (ModuleNotFoundError at 18:27; ~-prefixed pip remnant dirs corroborate an external uninstall). Recorded in `evaluations/t13/environment_interruption.json` with the timeline, before/after package versions, and frozen-artifact verification: transformers restored to **exactly 5.16.1** (with huggingface_hub 1.30.0 per its `huggingface-hub<2.0,>=1.5.0` requirement), and all four frozen T13/T12 suite hashes re-verified unchanged afterward. Deterministic suite reproduction (greedy decoding, seed 42) independently confirmed environment fidelity: the entire protection battery reproduced T12 bit-for-bit (§11).
- **No instrument or frozen-system defects discovered in T13.** T12-DEF-1 and T12-DEF-2 were repaired as the milestone's core work (§2, §5).

## 2. The T13 Question and the Repair

T12's dominant numeric bottleneck was **T12-DEF-2**: the fidelity classifier used runtime type equality, so faithful structured restatements (matrix literal string `[ 2 1; 1 3 ]` vs `[[2,1],[1,3]]`, int vs float, unit-bearing source strings) were rejected as TYPE_CHANGED — 11 guard rejections of faithful requests, contributing to numeric 0.7029 vs the 0.848 floor.

T13 replaced that with a **semantic fidelity classifier** (`fidelity.py` + new `semantic.py`): the fidelity layer now judges scientific *meaning*; the frozen engine's `schemas.finite_number` remains the schema/TYPE authority. Nine transformation classes: EXACT, REPRESENTATION_EQUIVALENT, UNIT_EQUIVALENT, STRUCTURE_EQUIVALENT, VALUE_CHANGED, TYPE_SEMANTICS_CHANGED, INFORMATION_ADDED, INFORMATION_REMOVED, INVALID_NORMALIZATION. Comparison-only canonicalizer (nothing is rewritten for the engine), strict numeric equality (no epsilon), null ≠ zero ≠ empty, vector-length and matrix-shape safety, provenance must match, and a rule-3 guard: a numeric STRING on the structured (schema-typed) side is TYPE_SEMANTICS_CHANGED / SCHEMA_TYPE_STRING_FOR_NUMBER — never parsed.

## 3. T13.10–13 Micro-Benchmark (fidelity-transform v1, 138 frozen cases)

| Metric | Measured | Floor | Status |
|---|---|---|---|
| Equivalent recall | **1.0** | ≥ 0.98 | PASS |
| Mutation rejection | **1.0** | 1.00 | PASS |
| False acceptance | **0** | 0 | PASS |
| Exceptions | **0** | 0 | PASS |
| Class mismatches | 0 | — | PASS |

`evaluations/t13/transform_benchmark_results.json`; benchmark checksum matches freeze.

## 4. T13.14–16 Targeted Replays

- **T13.14 DEF-2 replay** (11 frozen rows): **8/11 approved** by the semantic classifier, **3 kept rejected** (t-sr-0075, t-sr-0080, t-sr-0102 — SCHEMA_TYPE_STRING_FOR_NUMBER: values faithful, structured-side types schema-invalid; the engine would reject them anyway). Evidence decided; nothing was force-approved.
- **T13.15 DEF-1 empty container** (mfid-v1-0020 replay): PASS — classifies deterministically (FIDELITY_OK, no exception); the engine still returns INVALID_INPUT. No crash, no hallucinated completion.
- **T13.16 fidelity-v1 suite replay**: **8/8 frozen mutations still rejected** (PARAMETER_FIDELITY_FAIL on every mutation), 0 classifier exceptions, suite checksum matches the T12 freeze. Mutation protection fully intact.

## 5. T13.17 Scicomp Replay (206 rows, arm B gated pipeline, greedy seed 42)

| Metric | T13 | T12 | Gate |
|---|---|---|---|
| Numeric accuracy (138-row floor set) | **103/138 = 0.7464** | 97/138 = 0.7029 | **0.848 — FAIL** |
| Adoption (PASS envelopes) | **56/58 = 0.9655** | 49/51 = 0.9608 | ≥ 0.90 PASS |
| Conceptual discipline | **1.0** | 1.0 | control 1.0 ± 0.02 PASS |
| Adversarial handled-correctly | **0.92** | 0.92 | ≥ 0.92 PASS |
| Adversarial false-answer rate | **0.04** | 0.04 | must be 0 — FAIL (T12.26b mirror) |
| Valid call rate | 1.000 (74/74) | 1.000 | — |
| Over-compute | 0.0 | 0.0 | — |
| Pipeline exceptions | **0** | 0 (4 in fidelity-B) | — |
| Silent mutations executed to PASS | **0** | 0 | absolute gate PASS |

- **Row-level vs T12: +6 recovered (msc-v1-0009–0012, t-sr-0075-equivalent class, t-sr-0078), ZERO regressions, zero fidelity rejections** of faithful requests. T12-DEF-2 over-rejection is repaired and nothing else moved.
- **Adoption taxonomy:** ADOPTED 12, WRONG_ROUNDING 44, RESULT_MISREAD 1, RESULT_IGNORED 1 — rounding drift remains the dominant post-adoption error, unchanged from T12.
- **Residual numeric-loss decomposition (unchanged bottleneck structure):** 45 router-guard blocks of numeric rows (necessity=NOT_NEEDED classification — identical count in T12 and T13, pre-existing, **out of T13 scope** by the T12 router hardening's own authorization), 8 planner-schema provenance omissions, rounding misses, and 2 rows (0080/0102) where the model did not invoke compute at all.
- **Why the numeric gate still fails:** the repair recovered everything the fidelity classifier could recover (+6 rows, +4.3 pp). The remaining 0.7464 → 0.848 gap (~20 rows) lives entirely in the router-guard necessity classification and planner provenance emission — neither is the fidelity layer, and T13's mandate explicitly excluded broadening the planner or touching the routing guard.

## 6. T13.18 Conceptual Suite Replay (100 rows, bit-identical to T12)

Abstain discipline 0.7917, necessity accuracy 0.86, over-compute 0, router precision 1.0 / recall 1.0 (TP 18, FP 0, FN 0, TN 82) — **all four summary metrics byte-identical to the T12 control run**. Conceptual-suite numeric rows: 0.8214 vs T12's 0.7857 (one additional faithful restatement recovered; consistent with the classifier repair, nothing else moved).

## 7. Routing

Conceptual-B router 1.0/1.0, floor 0.95 PASS. T4 protection leg router: invocation precision 0.882 / recall 1.0 — identical to T12.

## 8. Execution Reliability

Engine valid-call rate 1.000 (74/74 well-formed calls; 58 PASS envelopes), compute success 0.7838, 0 pipeline exceptions across all scicomp/conceptual legs.

## 9. Protection Battery (T13.18–26) — ALL_MATCH, reproduced bit-for-bit

| Layer | T13 result | T12 baseline | Status |
|---|---|---|---|
| T4 verifier | critical gate PASS, false-pass 0.0; no-tool 0.5 / tool 0.7467, delta 0.2467 | identical | MATCH |
| T5R | NORAG 0.569 / G 0.5862, citations 0, fabricated 0 | identical | MATCH |
| Capacity | overall 0.8571 (131/131) | 0.857 | MATCH |
| Extraction | wrong-final acceptance **0.0** (recall 0.70, precision 0.737) | 0.0 | MATCH |
| Correction | true_correction 0.80, preservation 1.0, overcorrection 0.0, collateral 0, blind 0, net +20 | T10/T11 baseline | MATCH |

Greedy decoding (seed 42, do_sample false) reproduced every protection leg and the conceptual suite bit-for-bit — the deterministic-reproduction property T12 established holds under the repaired classifier.

## 10. Security (T13.29)

Security battery: **35 tests, 0 failures, 0 errors, 0 skipped → 0 violations** (`evaluations/t13/security_junit.xml`).

## 11. Fresh Test Battery

Full pytest after phase 2: **952 tests collected, exit 0 — 952 passed, 0 failures** (926 T12 baseline + 26 new T13 semantic-fidelity tests covering the required matrix: int/float and tuple/list equivalence, strict fidelity, empty container, null≠zero≠empty, vector length, matrix shape, unit conversion, provenance mismatch, information insertion/removal, reordered state vectors, DEF-1 non-crash, DEF-2 recovery, false-acceptance discipline, str→str schema-type guard, inf-safe hashing). Note: the project's `-q` addopts suppress the summary line; the 952-collected + exit-0 pair is the evidence.

## 12. Performance (informational)

- Median per-question LLM ms (t13-t17-scicomp-B): 30,918.
- Fidelity classifier latency (T13.26, deterministic, no model): classify_transform median **0.0017 ms**; full check_fidelity request path (incl. schema validation + resolver) median **0.0408 ms** — negligible against multi-second generation; the layer runs once per planner request.

## 13. Final Audit

`evaluations/t13/final_audit.json` (built by `scripts/t13_final_audit.py`): **26 gates, 24 passes**. The 2 fails:

1. **t13_numeric_floor — 0.7464 < 0.848** (pre-registered threshold unchanged). Promotion-critical. Carried over from T12 close (0.7029); improved by the repair but still below floor.
2. **t13_no_fabricated_PASS — adversarial false-answer rate 0.04** (mirror of T12.26b, which also FAILED at T12 close with the same 0.04). Honest regression vs the must-be-0 requirement; recorded, not excused.

All other 24 gates PASS: suite integrity ×4, engine freeze, firewall, benchmark eq-recall/mutation-rejection/false-accepts/exceptions, DEF-2 replay, DEF-1 empty container, fidelity-suite protection, adoption, no pipeline exceptions, adversarial preserved, conceptual preserved + conceptual-suite reproduction, protection battery ×5, security, latency. The T13-ENV-1 record is embedded in the audit JSON.

## 14. Decision

**KEEP_SCICOMP_EXPERIMENTAL.**

- **PROMOTE_SCICOMP_LAB is impossible**: the numeric critical gate fails (0.7464 < 0.848) and one critical failed gate means no promotion — per the pre-registered rule, no composite score and no averaging.
- **REJECT_SCICOMP is contradicted by the evidence**: every non-numeric gate is green (adoption 0.9655, conceptual 1.0, adversarial 0.92, zero silent mutations, zero pipeline exceptions, benchmark at ceiling, protection battery fully MATCH, security 0 violations), the repair is provably additive (+6 rows, zero regressions, zero new fidelity rejections), and T12's identified defect is repaired with protection intact. Rejection would discard a measured, monotonic improvement.
- **Weight promotion: NO** (unchanged — no training occurred; the runtime is the same frozen system as T12).
- **Documented residual bottleneck (out of T13 scope):** the router-guard necessity=NOT_NEEDED classification blocking 45 numeric rows (identical to T12, authorized-hardening behavior), plus planner provenance omissions (8 rows). These — not the fidelity layer — are what separates 0.7464 from the 0.848 floor. Any future milestone targeting promotion should address the router-guard necessity classification first, with the planner-provenance emission second.

**T13 CLOSED — STOP.**