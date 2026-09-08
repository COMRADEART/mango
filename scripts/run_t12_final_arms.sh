#!/usr/bin/env bash
# T12.22 final arms — sequential full runs (frozen suites, checksum-verified)
set -x
cd "$(dirname "$0")/.."
export PYTHONPATH=src
LOG=evaluations/t12/runs/driver.log
mkdir -p evaluations/t12/runs
{
  echo "=== T12 final arms start $(date) ==="
  python scripts/t12_scicomp_eval.py --suite scicomp    --arm A --label t12-final-scicomp-A    2>&1 | grep -v "Loading weights"
  echo "=== scicomp A done $(date) ==="
  python scripts/t12_scicomp_eval.py --suite scicomp    --arm B --label t12-final-scicomp-B    2>&1 | grep -v "Loading weights"
  echo "=== scicomp B done $(date) ==="
  python scripts/t12_scicomp_eval.py --suite fidelity   --arm A --label t12-final-fidelity-A   2>&1 | grep -v "Loading weights"
  echo "=== fidelity A done $(date) ==="
  python scripts/t12_scicomp_eval.py --suite fidelity   --arm B --label t12-final-fidelity-B   2>&1 | grep -v "Loading weights"
  echo "=== fidelity B done $(date) ==="
  python scripts/t12_scicomp_eval.py --suite conceptual --arm B --label t12-final-conceptual-B 2>&1 | grep -v "Loading weights"
  echo "=== conceptual B done $(date) ==="
  echo "=== ALL T12 FINAL RUNS COMPLETE $(date) ==="
} >> "$LOG" 2>&1