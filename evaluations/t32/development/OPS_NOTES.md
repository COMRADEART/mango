# T32 operational notes (running policy, recorded as decisions occur)

## 2026-10-01 — background-task reaping and checkpoint semantics

* Candidate A's first two launches were stopped by the session harness's
  idle-memory-pressure reap (host RAM spikes during tokenization; host
  itself healthy at rest). Not a command failure; the recipe was never
  reached past step ~186.
* On the second reap, `checkpoint-100` existed, but RESUME from it is
  impossible in this environment: transformers' `check_torch_load_is_safe`
  refuses to `torch.load` the checkpoint's `optimizer.pt` under the
  installed torch (< 2.6; CVE-2025-32434 gate).
* **Torch upgrade rejected**: the Phase 9 locked comparison joins fresh
  T32 rows to FROZEN T31 rows generated under the pinned torch; changing
  torch between frozen and fresh arms would confound the very delta T32
  measures. Rejected for the whole chain.
* **Decision: delete the unloadable checkpoint and restart fresh** — the
  declared recipe (warmup 17 + cosine over 552 steps) stays exact.
* **Predeclared fallback if a reap hits again mid-run**: strip
  `optimizer.pt`/`scheduler.pt` from the latest checkpoint (they are the
  only file kinds the gate blocks; model weights are safetensors), resume
  model-only, and DISCLOSE in the candidate manifest + Phase 11 receipt
  that the surviving steps ran under a re-created LR schedule (fresh
  warmup + cosine over the remaining horizon). Recipe purity is worth < 30
  min; disclosure is mandatory either way.
* Fresh-restart events are logged here as they happen.

## reap/restart log

| utc time | event | state |
|---|---|---|
| 2026-10-01 00:0x | reap #1 of train A (~step 100, first eval pass) | no checkpoint; lost ~20 min |
| 2026-10-01 00:5x | reap #2 of train A (~step 186) | checkpoint-100 present; unloadable (torch gate) |
| 2026-10-01 00:5x | decision per policy above: fresh restart | running (b83w1hwrg) |