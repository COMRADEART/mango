#!/usr/bin/env bash
# T13.18-26 GPU queue — phase 2 (after the T13.17 scicomp-B replay exits).
# Identical frozen suites/labels logic as run_t12_final_arms.sh, with
# t13-* labels; only the fidelity classifier underneath has changed.
set -x
cd "$(dirname "$0")/.."
export PYTHONPATH=src
LOG=evaluations/t13/runs/t13_driver.log
{
  echo "=== T13 phase-2 start $(date) ==="
  python scripts/t12_scicomp_eval.py --suite conceptual --arm B --label t13-t18-conceptual-B 2>&1 | grep -v "Loading weights"
  echo "=== conceptual B done $(date) ==="
  python scripts/t8_t4_arm.py --model Qwen/Qwen3-4B-Instruct-2507 --label t13-protect-t4 --max-new-tokens 1024 2>&1 | grep -v "Loading weights"
  echo "=== T4 done $(date) ==="
  MANGO_EVAL_MODEL=Qwen/Qwen3-4B-Instruct-2507 python scripts/run_rag_eval_t5r.py --suite frozen --variants NORAG,G --out-dir evaluations/t13/protection/t5r 2>&1 | grep -v "Loading weights"
  echo "=== T5R done $(date) ==="
  python scripts/run_capacity_eval.py --model Qwen/Qwen3-4B-Instruct-2507 --label t13-protect-cap --out evaluations/t13/protection/cap 2>&1 | grep -v "Loading weights"
  echo "=== capacity done $(date) ==="
  python scripts/run_extraction_benchmark.py --model Qwen/Qwen3-4B-Instruct-2507 --label t13-protect-ext 2>&1 | grep -v "Loading weights"
  echo "=== extraction done $(date) ==="
  python scripts/t10_run_correction_v2.py --model Qwen/Qwen3-4B-Instruct-2507 --label t13-protect-correction --arm t10 --split final 2>&1 | grep -v "Loading weights"
  echo "=== correction done $(date) ==="
  echo "=== ALL T13 PHASE-2 RUNS COMPLETE $(date) ==="
} >> "$LOG" 2>&1