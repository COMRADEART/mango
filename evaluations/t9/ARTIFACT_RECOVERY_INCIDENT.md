# T9 artifact recovery incident

The continuation started at current remote `main`,
`1934e9d9e1e6a37dc9ecb03795a0c8d8bd0f5df5`. The initial working tree had
untracked `.claude/` and `sciencemath/` directories. Neither was removed or modified.
`pre_repair_state.json` preserves T9 artifact hashes, metrics, status and the
passing eight-test firewall check before repairs.

## Production adapter: probable recovery

The original project copy is nested at `sciencemath/`. Its production adapter
candidate is `sciencemath/training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors`.
It is 139,512,976 bytes with newly measured SHA-256
`f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668`.

The candidate is byte-identical to the previous project's checkpoint 300.
Checkpoint 546's trainer state selects checkpoint 300 as the best checkpoint,
with evaluation loss 0.8474348783493042, matching the committed T3 manifest.
Training completed at step 546 with seed 42. Checkpoints 500 and 546 have different
weight hashes and were not substituted for the selected checkpoint.

All four requested metadata files agree as JSON with current production metadata.
All eight original dataset checksums match. The candidate has 392 float32 LoRA
tensors, 34,865,152 parameters, rank 32, alpha 64, and all expected keys and shapes
for the seven target projections across 28 Qwen3-1.7B layers. The pinned historical
base revision is `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`.

No original weight SHA was found in the inspected manifests, evaluation metadata,
training records, Git history or LFS records. These metadata and checkpoint matches
support **PROBABLE_RECOVERY**, not independently proven historical cryptographic
identity. A newly computed digest is not retroactive evidence. No candidate was
copied into production, uploaded, committed, trained, or relabeled as exact.
The historical reload smoke is evidence only; no fresh matched production baseline ran.

The repository's `.gitignore` explicitly excludes
`training/adapters/*/adapter_model.safetensors`. LFS attributes do not override
ignore rules. Git LFS 3.7.1 is configured, but neither repository's LFS history lists
this production object. Remote `main` is the only advertised branch, with no tags.
The search also inspected project checkpoints/artifacts, local LFS caches and the
available Ubuntu-24.04 project/mount inventory. No additional project backup was
found in those locations. Unknown offline backups remain outside available evidence.

## Frozen Level-1 corpus: checkout mutation

`CURRENT_FILE_MUTATED`: Git stored the authoritative LF bytes. Windows
`core.autocrlf=true` converted the JSONL files to CRLF on checkout. The prior
workspace still contains their exact expected bytes.

| File | Before repair SHA-256 | Authoritative SHA-256 |
| --- | --- | --- |
| replay.jsonl | `6a039fe504ececbb231b7bc85a15e3ccb30ee9ad13a795a025e04cca551be78f` | `521f41ad4d1e8d1e4288e8ec403fd7dfbeda18476064b3b7d9394a48b44874c2` |
| train.jsonl | `a83a41594df3f740f1cb80fe5f8931bc4468b182b5f4df4d61e649ec1661e7f0` | `432379f5dc7897f208de76daa723379983f665b9fdf44e6c23f2b59cfd093d22` |
| validation.jsonl | `e5f96cc346a9b4b229ae5b2730eeb54cf7c639906dd8aceee4e2785cd064e074` | `429b8b4294b217aefffaf025afbe22550f75254b41c53fd072a9843202407b5d` |

Replay has 135 rows in both copies. Parsed rows, ordering, IDs, sources, domains
and answers agree; exact bytes agree only after removing checkout-added CR bytes.
Both retain a final newline and are Unicode NFC. Git and prior workspace hashes
establish authority independently of semantic comparison.

The JSONL files were restored from Git. `.gitattributes` now pins this directory's
JSONL to LF and JSON metadata to its historically frozen CRLF bytes. All nine
checksummed files now match. `checksums.json` was not changed. The first full rerun
after replay repair exposed the same mutation in train.jsonl; its failure record is
preserved in `pytest_intermediate_failure.json`.

## Test inventory: omitted T8S commits

The historical `sciencemath/t8s_final_junit.xml` contains 737 passing test cases.
Thirty are in four T8S test modules committed in the prior repository, whose later
T8S commits did not reach current `main`. They were not renamed, skipped, deselected,
conditionally removed for missing weights, or deleted by the T9 implementation.

The prior test base is 707: `737 - 30`. The earlier T9 entry report's
`706 passed, 1 failed` is that base with the corpus mismatch. T9 added eight tests,
giving 715 collected and the reported `714 passed, 1 failed`. Restoring the missing
30 gives 745. All 737 historical node IDs are now present, plus exactly eight T9 IDs.

Restored the four test files and their four missing supporting modules from the
prior repository. Code restoration removed UTF-8 BOMs where present and uses LF;
Python source content is otherwise unchanged. No test assertions were weakened.
`test_inventory_reconciliation.json` contains full before/after node-ID sets,
source file hashes, source commit history and exact run output.

## Remaining gate and release policy

Final pytest: **745 passed in 14.61s**, zero failures, skips or errors.
T4 deterministic safety: **0 false PASS / 638 wrong probes**.
Frozen T4/T5R/capacity row integrity passes; all five hashes recorded in the original
T9 entry gate match the current checkout. T8S closure files were recovered as local
reference evidence, with their source hashes recorded; several final closure files
were left uncommitted in the old repository and lack an independent immutable anchor.

`PRODUCTION_BASELINE_REPRODUCIBILITY = BLOCKED`. The explicit Phase 5 stop-on-failure
instruction was retained. The later missing-adapter fallback requesting 4B regressions
was not treated as an implicit waiver of that gate. Expensive GPU regressions and the
later extraction benchmark remain unrun; historical metrics are labeled as historical.

Future releases must follow [the release artifact policy](../../docs/RELEASE_ARTIFACT_POLICY.md).
It requires weights, hashes, durable storage, pinned revisions, tensor inventory,
reload smoke, immutable manifest, evaluation hashes and clean-clone verification.
