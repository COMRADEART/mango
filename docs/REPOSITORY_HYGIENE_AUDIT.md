# Repository Hygiene Audit — 2026-09-09

Post-T12 provenance reconciliation pass. T12 closure (commit fe5987e + evidence
21b83e4) is authoritative and untouched; no frozen artifact, engine file, or T12
evaluation output was modified. No retraining, no GPU evaluation reruns, no T13.

## Method

Every untracked item was classified from evidence, not assumption: nested-repo
`git log`/`cat-file` comparison against the outer (authoritative) repo history,
`git grep` at HEAD for references from committed milestone gates/audits, and test
import analysis. Nothing was deleted.

## Classification table

| Path | Type | Provenance | Needed for reproduction? | Decision | Reason |
| ---- | ---- | ---------- | ------------------------ | -------- | ------ |
| `docs/RELEASE_ARTIFACT_POLICY.md` | T9 policy doc | Written during T9 reproducibility recovery; accurately reflects current policy (release bundle, LFS verification, recovery classification) | Yes — governs future releases | COMMIT | User pre-approved; no conflicting policy exists |
| `scripts/t8s_finalize.py`, `t8s_metrics.py`, `t8s_vectors_pareto.py` | T8S eval scripts | T8S milestone; imported by `tests/test_t8s_*.py` (collected in the 926-count pytest); referenced by committed T8S-era junit inventories | Yes — reproduce T8S metrics/finalize/pareto | COMMIT | Required by current test suite and historical reports |
| `scripts/t9_decomp_pass.py`, `t9_final_audit.py`, `t9_repair_validation.py`, `t9_repro_audit.py`, `t9_t3_provenance.py`, `t9_t3_search_sources.py` | T9 audit/repro scripts | T9 milestone; listed in committed `evaluations/t9/test_inventory_reconciliation.json` and T9 gate files | Yes — reproduce T9 43/43 audit | COMMIT | Historical milestone reports are not reproducible without them |
| `scripts/build_extraction_benchmark.py`, `run_extraction_benchmark.py` | Benchmark builders | Built `mango-extraction-benchmark-v1` used by committed T11/T12 protection-extraction legs | Yes — reproduce extraction-leg benchmark | COMMIT | Referenced by committed T11 evidence chain |
| `src/sciencemath/evaluation/repro.py` | Source module | T8S/T9 repro module; imported by `tests/test_t8s_pareto.py` and `tests/test_t8s_repro.py` | Yes — current pytest depends on it | COMMIT | Omitted accidentally; tree did not match the tested state |
| `tests/test_t11_security.py` | Test module | T11/T12 security battery instrument — the 35 tests cited in the committed T12 audit gate `t12.31_security_zero_violations` | Yes — T12 audit evidence cites this file by path | COMMIT | Protects current security behavior; omission was accidental |
| `tests/test_t8s_finalize.py`, `test_t8s_metrics.py`, `test_t8s_pareto.py`, `test_t8s_repro.py` | Test modules | T8S tests, collected in the standing 926-count pytest (files were on disk during every recorded count) | Yes | COMMIT | Committing adds zero new collected tests; not count inflation |
| `check_progress.py`, `generate_t4_summary.py` | Utility scripts | T4/T8 progress + summary helpers; both cited by path in committed `evaluations/t11/t11_entry_gate.json` and `evaluations/t12/t12_entry_gate.json` working-tree inventories | Yes (gates cite them) | COMMIT | Named in committed gate records; tiny, self-contained |
| `evaluations/t9/runs/t11-protect-ext/` | Eval run artifacts | T11 protection-extraction run (mango-extraction-benchmark-v1, wrong-final-acceptance 0.0, 20 questions); referenced by committed `T11_FINAL_REPORT.md`, `t11/final_audit.json`, `t11_protection_battery.py` | Yes — committed T11 evidence | COMMIT | Misplaced under `t9/runs` at creation time; path kept as-recorded |
| `evaluations/t9/t3_clean_clone_validation.json` | Provenance evidence | T9 clean-clone LFS retrieval validation (adapter sha f57b2fd4…, GitHub clone of 6f99420); referenced by committed `t9_entry_gate_final.json`; found only as untracked file inside nested `mango/` | Yes | COMMIT | Copied out of `mango/` before archiving so the referenced evidence lives in the authoritative repo |
| `.claude/scheduled_tasks.lock` | Runtime lock | Session-runtime scheduler lock file; regenerated on every session | No | GITIGNORE | Runtime artifact, never content |
| `mango/` | Nested git repository | Duplicate workspace copy of the outer repo's own history: HEAD `5ce04b3` "Finalize T9 entry gate" is hash-identical to an outer-repo commit; all 4 sampled commits (`5ce04b3`, `6f99420`, `a2b25b0`, `1934e9d`) exist in outer history. One untracked file (`evaluations/t9/t3_clean_clone_validation.json`) copied to outer `evaluations/t9/` first | No — fully represented by outer history | ARCHIVE_OUTSIDE_REPO | Do not commit a duplicate 6.8 GB repository tree; history + untracked file preserved in archive |
| `sciencemath/` | Nested git repository | Historical T0–T8S workspace repo. Shares early lineage with outer repo up to `a2b25b0`, then diverges: 4 T8S commits (`1d5db3d`, `8e8d5e1`, `595fbfd`, `2a03f7b`) exist ONLY here, plus uncommitted T8S report modifications | History: no (unique commits live only here); workspace: archived intact | ARCHIVE_OUTSIDE_REPO | Contains unique T8S milestone history not represented anywhere else — preserved whole, never deleted; documented per release policy ("T8S commits left in another local repository") |
| `temp_clean_clone/mango/` | Clean clone | T9 clean-clone validation clone at `6f99420` (commit exists in outer history); its validation output was `t3_clean_clone_validation.json` (now committed) | No — validation output already committed | ARCHIVE_OUTSIDE_REPO | Temporary validation material per T9 policy; not a duplicate record |

## Archive location

All archived material moved (same-volume rename — not copied, not deleted) to:

```
C:\Users\allam\Documents\new\_archive\nested-repos-2026-09-09\
├── mango\              (6.8 GB, nested repo, HEAD 5ce04b3)
├── sciencemath\        (8.0 GB, nested repo, HEAD 2a03f7b + uncommitted T8S report edits)
└── temp_clean_clone\   (6.8 GB, validation clone at 6f99420)
```

Retention: indefinite until explicitly discarded by the user. `sciencemath/` is
the sole holder of T8S-unique history and must not be deleted without its commits
being preserved elsewhere first.

## Known non-issues

`git status` showed ` M` on three `training/curriculum/mango-sft-v2/level1/*.jsonl`
files with an empty `git diff HEAD` — line-ending/stat-cache phantom state;
`git checkout --` restored clean status with zero content change (verified empty
diff before and after).

## Test effect

Committing pre-existing test files changes nothing about collection: the standing
926-collected count already included them. Full pytest was rerun after the commit;
see `evaluations` records and the session report for the exact result.