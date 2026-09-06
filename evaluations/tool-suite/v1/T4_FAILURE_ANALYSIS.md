# Mango — T4 Failure Analysis

Evaluation: `mango-tool-eval-v1` (150 questions), model `Qwen/Qwen3-1.7B`
(Mango-v0.1 base, non-thinking), both arms through the identical harness.
Sources: `notool/predictions.jsonl`, `tool/predictions.jsonl`,
`tool/tool_calls.jsonl`, deterministic verifier selftest and router metrics.

---

## 1. No-tool arm failure modes (44 non-PASS of 150)

| Mode | Count | Classification |
|---|---|---|
| UNKNOWN — no_answer_extracted | 18 | **generation budget**: output truncated at 1024 tokens before any `\boxed{}`; extraction heuristic (not the model's math) failed |
| UNKNOWN — no_answer | 5 | generation budget (empty/overlong output) |
| FAIL — numeric | 9 | genuine model arithmetic/reasoning errors |
| FAIL — symbolic_equivalence | 6 | genuine model algebra errors |
| FAIL — normalized_string | 3 | genuine wrong text answer |
| FAIL — solution_set / mcq_value / mcq_letter | 3 | genuine wrong answers |

**Dominant no-tool failure mode is truncation, not wrong math**: 23/44
non-PASS rows (52%) are UNKNOWN caused by the 1024-token generation budget
exhausted on long chain-of-thought. This is a harness/generation-budget
limitation of the Mango-v0.1 base model's verbose style, and it caps the
measurable ceiling of both arms equally (same budget in both).

Categories hit hardest by truncation: `trigonometry_precalculus`
(5 UNKNOWN of 10), `units` (5 UNKNOWN of 10), `symbolic` (3), `equations` (3).

## 2. Tool-enabled arm failure modes (44 non-PASS of 150 — FINAL arm, 1024 tokens/round)

Classification (`scripts/classify_t4_failures.py` on saved rows + audit log):

| Dominant failure type | Count | Share of non-PASS | Share of 150 |
|---|---|---|---|
| MODEL_REASONING_FAILURE | 24 | 54.5% | 16.0% |
| EXTRACTION_FAILURE | 18 | 40.9% | 12.0% |
| VERIFIER_UNKNOWN | 1 | 2.3% | 0.7% |
| TOOL_ARGUMENT_EXTRACTION | 1 | 2.3% | 0.7% |
| TOOL_TIMEOUT / TOOL_ENGINE_ERROR / MODEL_IGNORED_TOOL_RESULT / other | 0 | 0% | 0% |

Extraction-failure sub-causes (18):
- 8 MCQ format shift: under the tool-protocol prompt the model wraps correct
  answers in markdown bold ("**D. the length of the day**." / "\text{A}") and
  the trailing-anchor MCQ extractor does not parse them (0 tool calls involved
  — pure prompt-format artifact). All 8 are `general_science`.
- 11 truncation/no-answer: 1024-token budget exhausted on chain-of-thought
  (same ceiling as the no-tool arm).
- 2 LaTeX formatting: model echoed tool output as "\cos(x)"/"-\sin(x)" — the
  tool result itself was CORRECT (deterministic derivative of sin/cos); the
  answer normalization missed the LaTeX backslash form.
- 1 sentence-form answer: "4 feet is equal to 48 inches." — the unit
  conversion was CORRECT (4 ft = 48 in); extraction missed the embedded value.

The single TOOL_ARGUMENT_EXTRACTION case (ev1-b37cc0b86619): the model passed
a full equation ("x^2 + y^2 + Dx + Ey + F = 0") to symbolic_math `factor`,
which is an expression tool — deterministic PARSE_ERROR rejection, then the
model answered from its own (wrong) algebra.

**Key attribution result: zero tool-engine failures.** In 25 tool calls,
24 returned ok and 1 was deterministically rejected (PARSE_ERROR on
malformed input). There were 0 timeouts, 0 INVALID_INPUT, 0 unsafe-input
rejections, 0 cases of a correct tool result being ignored or misread into a
wrong PASS/FAIL. The three tool-involved UNKNOWNs above are extraction/
normalization artifacts, not tool defects.

## 2b. Superseded 320-token run — methodology history

`tool_320budget_superseded/` is **SUPERSEDED — INVALID FOR PERFORMANCE
COMPARISON**. The first tool arm ran with a 320-token/round generation budget
against the no-tool arm's 1024, breaking budget parity: 126/150 questions
ended after round 1 (the protocol loop stops when no tool call is emitted)
and 64/150 were non-PASS with 43 EXTRACTION_FAILUREs — truncation confounded
the measurement, producing an apparent −13.3pp that does not measure tool
effectiveness. The run is kept for audit only and excluded from all final
metrics and deltas. The final arm (1024 tokens/round, var inference active)
is the ONLY eligible tool-enabled comparison.

## 3. Router analysis (deterministic, suite-level)

- Invocation precision **0.88** (30 tp / 4 fp), recall **1.0** (0 fn).
- All 4 false positives are ONE pattern: arithmetic-shaped equations
  ("Solve for x: 2x - 7 = -25") route **both** `equation_solver` (correct)
  and `calculator` (redundant but harmless). No FP routed a tool to pure
  science prose.
- Decision: **router left unchanged.** Recall 1.0 is the priority per the
  T4 directive (missing a needed verification tool is more serious than an
  unnecessary safe call); the FP pattern is benign redundancy, and a
  suppress-calculator-when-solver-routed rule risks recall on legitimate
  calculator-plus-solver questions without measurable benefit.
- `math_routing_coverage` on heterogeneous competition math (plausible
  annotation): 0.32 — the router honestly declines to route most free-form
  competition questions rather than guessing. These questions still run
  tool-enabled through the protocol prompt.

## 4. Verifier (deterministic, adversarial)

- Gold answers: 150/150 PASS (gold_pass_rate 1.0, gold UNKNOWN 0.0).
- Wrong-answer adversarial cases: **638 perturbations/garbage cases**,
  false PASS **0**, wrong-UNKNOWN 0.47% (3 cases).
- Critical gate: **PASS** — no unexplained false-PASS path is known after
  the 30-defect adversarial review and fix cycle.

## 5. Known tool-layer limitations (from the 30-defect review, fixed or open)

Fixed this round (regression-tested in `tests/test_t4_regressions.py`):
timeout wall-clock enforcement, symbolic resource bombs (factorial/power/
literal caps), fixed-sample-point false PASS, shared sample value across
symbols, complex-branch false PASS, empty-solution-set false PASS,
membership argument swap, multi-comma numbers, unit-bearing/bare-number
mismatches, percent-vs-quantity false PASS, pressure dimensions, bare-digit
unit exponents, equation solver real-root drop, quintic list-solve, dead
`==` branch, calculator TypeError/factorial/timeout, numerical overflow,
matrix inverse cap, symbolic integral bounds, MCQ trailing-letter anchor,
ToolCallLogger concurrency, newline ambiguity, `^o` regex.

Open limitations (documented, not defects):
- Cofactor determinant/inverse capped at 8x8 (no LU decomposition yet).
- Calculator caps results at 1e100; exact big-integer arithmetic beyond
  that is rejected (OVERFLOW) rather than computed.
- Unit registry is fixed (~120 units); unknown units are deterministic
  errors, never guesses.
- Temperature is treated as non-factor-comparable against bare numbers
  (UNKNOWN), not affine-normalized.
- Equation systems are ';'-separated only (comma systems unsupported).