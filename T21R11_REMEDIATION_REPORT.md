# T21R11 Diagnostic Remediation Report

Date: 2026-09-18

Decision: **DIAGNOSTIC REMEDIATION COMPLETE**

Promotion decision: **NONE**. This phase used open synthetic diagnostics; it
did not construct or expose a T21R11 blind holdout. Knowledge RAG remains
experimental until a separately preregistered, frozen, one-shot evaluation.

## Scope

The remediation was selected from the failed T21R10 mechanism families:
multi-hop path resolution, cross-domain relation coverage, conflict detection
and resolution, abstention, citation/source diversity, and retrieval framing.
The exposed T21R10 holdout was not rerun or used as development data.

The independent diagnostic world contains 24 sources, 654 chunks, 140
entities, and 610 canonical facts. Its registry has zero overlap with the
earlier fixture registry and source-title set. The DEV split has 105 rows. The
VALIDATION split has 101 rows and is bound by
`validation_sha256=38e522ff9f3a612d6dfd64868b7bae915ffce49e82f0f3734fdd83d46b2be4f9`.

## Implemented repairs

- Added typed `LED_BY` relation support and repaired born-chain/frame parsing
  without weakening exact entity identity.
- Added bounded corpus-wide same-fact corroboration with exact metadata,
  relation, source, and normalized-value checks.
- Applied the source-injection firewall and audit accounting to authority
  winners and corroborators introduced from outside the initial retrieval
  window.
- Added bounded corpus-wide conflict candidates for query-grounded entities
  and attributes, including citation-correct authority-winner propagation.
- Added conservative text-level year conflict detection for metadata-mixed
  evidence windows.
- Changed conflict resolution to compare the strongest source for each value
  side, preventing a weak duplicate from causing a false resolution.
- Preserved the established multihop decision-trace vocabulary while using the
  typed evidence-path resolver.
- Repaired fail-closed diagnostic corpus construction by validating source
  record hashes.

## Diagnostic results

| Metric | DEV before | DEV after | VALIDATION before | VALIDATION after |
| --- | ---: | ---: | ---: | ---: |
| Overall grounded accuracy | 0.8553 | 1.0000 | 0.8592 | 1.0000 |
| Multi-hop accuracy (B) | 0.8095 | 1.0000 | 0.7778 | 1.0000 |
| Cross-domain accuracy (C) | 0.8276 | 1.0000 | 0.8148 | 1.0000 |
| Conflict accuracy (D) | 0.7059 | 1.0000 | 0.7059 | 1.0000 |
| Conflict detection | 0.1667 | 1.0000 | 0.1667 | 1.0000 |
| Conflict false resolution | 0.8333 | 0.0000 | 0.8333 | 0.0000 |
| Citation accuracy (F) | 0.8000 | 1.0000 | 0.9000 | 1.0000 |
| Citation precision | 0.8816 | 1.0000 | 0.8732 | 1.0000 |
| Abstention precision | 0.6471 | 1.0000 | 0.6471 | 1.0000 |
| Abstention recall | 0.5500 | 1.0000 | 0.5500 | 1.0000 |

Both regenerated splits reproduced their frozen inputs. All after-remediation
rows passed, with zero injection payload leaks, zero lineage failures, and no
nonzero zero-tolerance counters.

## Regression verification

- Focused remediation and multihop suite: **65 passed**.
- Applicable repository suite: **3,061 passed, 2 skipped, 0 failed, 0
  errors** (3,063 tests).
- Python compilation and `git diff --check`: passed.

Six historical protocol checks were intentionally excluded from the applicable
run:

- Three T21R10 preconstruction tests require the real T21R10 holdout and
  exposure artifacts to be absent. That premise is false after the completed,
  consumed T21R10 official evaluation; the same three tests failed before this
  remediation.
- Three T21R8/T21R9 frozen-current-tree identity tests correctly reject the
  intentional post-T21R10 runtime changes. The historical freeze artifacts
  were not rewritten or weakened.

## Artifacts

- `scripts/t21r11_diag_world.py`
- `scripts/t21r11_diag_suites.py`
- `scripts/t21r11_diag_run.py`
- `evaluations/t21r11_diagnostics/validation_freeze.json`
- `evaluations/t21r11_diagnostics/refreeze_record.json`
- `evaluations/t21r11_diagnostics/results/before_*`
- `evaluations/t21r11_diagnostics/results/after_*`
- `tests/test_t21r11_remediation.py`

## Boundary for the next phase

No promotion claim follows from open diagnostics. A future promotion attempt
must create a fresh T21R11 runtime/evaluator freeze and a new independent blind
holdout, then perform exactly one authorized evaluation under unchanged floors.
