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

## 2026-10-01 11:43–11:52 — abrupt death of the handoff chain mid-step, event unknown

* The external chain (PID 38464) and its train-B subprocess (PID 34160)
  disappeared abruptly between 11:43:21 (last `train_B_log.txt` write,
  step 574/702) and 11:52. No traceback, no OOM message, no chain-step
  failure log — a hard-kill signature (both processes stopped mid-flight
  with no Python unwinding). This was the external terminal's tree; if
  that console itself was another agent session's background task, the
  same idle-reaper applies to it that killed the first three A trainings.
  GPU TDR and CUDA OOM are possible but would normally leave a traceback;
  none exists. New consumers appeared on the GPU around this period:
  brave.exe (×2), EpicGamesLauncher, EOSOverlayRenderer — ~2379 MiB of the
  6141 MiB card now held by non-training apps.
* State preserved: `training/checkpoints/t32-B-task-balanced/checkpoint-500`
  (~82% of steps; 500/702, optimizer.pt present ⇒ torch-gate blocks direct
  resume). Loss at death: step 570 log shows loss 0.6031, lr 9.12e-06,
  epoch 1.63 — falling normally, no divergence.
* A's adapter (complete) and dev-A evidence are committed (a2ad f89); B's
  receipt was not reached. Chain relaunch resumes B from checkpoint-500;
  because optimizer.pt is unloadable under the pinned torch, the
  predeclared fallback applies: strip optimizer.pt/scheduler.pt from
  checkpoint-500, resume model-only, disclose the re-created schedule
  (warmup replay ~17/17 + cosine re-extended over the remaining ~128
  steps) in the B receipt and final report. ~128 steps remain of B.

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

## Codex candidate B recovery

Resuming checkpoint-500 after the interruption at logged step 574. Optimizer and scheduler files were already absent. Archived rng_state.pth because the same pinned torch safety gate also blocks RNG pickle loading. Safetensors weights and trainer metadata are retained; optimizer, scheduler, and RNG are recreated. This changes optimization history and reproducibility; see B_RECOVERY_RECORD.json. No torch safety gate is bypassed.


## Recovery regression review

The full suite recorded 54 failures, 11 errors, 4438 passes and one skip. Sixty-two failed/error test IDs match the frozen T31 closure run; three additional IDs were reviewed. The whole-workspace import audit includes active training/log changes; the isolated unchanged protocol/fixtures audit passed with zero writes. Two state-engine concurrency tests had Windows os.replace PermissionError; both passed the focused rerun without runtime changes. Four T32 infrastructure tests also passed in that rerun (six passed total). Original results remain preserved; see isolated_import_audit_result.json and recovery_focused_junit.xml.


The redundant whole-workspace audit rerun was stopped after the isolated import audit and focused concurrency/handoff checks completed. It did not produce a complete JUnit report; recovery_focused_junit.xml and isolated_import_audit_result.json are the completed rerun evidence.

