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
| 2026-10-01 01:4x | reap #3 of train A (step 144, run b83w1hwrg, PID 34176) | partial checkpoints archived by the handoff chain below |

## handoff audit 2026-10-01 (session resumed from compaction)

An independent continuation (not launched by this session) took over after
reap #3: a pytest regression run (PID 10788, junit: `regression_junit.xml`),
a chain process (`scripts/t32_chain.py --wait-pid 34176`, PID 38464) and —
after the wait — its own fresh candidate-A training (PID 38400, training
start 02:11:45, `resumed_from=None`, 552 steps, warmup 17: recipe exact).
The handoff archived the killed run's partial checkpoints instead of
resuming them; no optimizer-loading bypass. This matches the predeclared
fallback policy and removes training from any harness background-task reaper.

Diffs were reviewed AS DATA against the predeclared DEV_PROTOCOL:

* **Verified correct**: final_eval's join hash `sha256("\x00" + prompt_text)`
  reproduces the frozen `rows.py` convention exactly (`system_prompt + "\x00"
  + user_prompt`; verified against a real frozen row — my earlier plain
  `sha256(prompt_text)` would NOT have joined the frozen rows). Its
  preservation-manifest and candidate-freeze gates verify live; the manifest
  pins 80 frozen-evidence hashes, all 80 verified true by this session.
  chain's `--wait-pid` + checkpoint archive behavior; selection's artifact
  receipt; dev_eval's extra slice metrics (truncation/extraction/token stats)
  and persisted-id integrity guards (additive); trace_audit's category-based
  sampling (qualitative display only; measurement untouched).
* **Inert**: dev_eval's tokenizer padding side / pad token — the frozen
  runner sets the same values itself.
* **Repaired by this session** (closure.py was created by the handoff):
  PASS token is reachable per the directive token rule (was hardcoded down
  to PARTIAL; "do not force PASS from a tradeoff" is not "never emit PASS");
  gates 7–12 and 15 are computed from real evidence (per-benchmark join
  identity and pack hashability) instead of hardcoded `True`; hypothesis
  report lines fall back `detail` -> `evidence`. The gate-failure cap on a
  numerically-earned PASS is retained.
