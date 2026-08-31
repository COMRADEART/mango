"""T3 QLoRA training — STUB (not implemented yet).

Refuses with a clear, non-fake error instead of pretending to train.
Implemented in milestone T3; will consume configs/training.yaml, the
canonical splits from data/{train,validation}/, save a LoRA adapter under
training/adapters/sciencemath-v0.1/ and a full training manifest.
"""
import sys

STUB_MESSAGE = """
STATUS: BLOCKED - training_lora is not implemented yet (milestone T3).

Refusing to continue: no training has been performed, and no artifacts will
be fabricated. Prerequisites:
  1. T2 baseline evaluation artifacts in evaluations/base/ (required by the
     "base evaluation first" rule).
  2. Approved training splits in data/train/ (see build_splits.py).
"""


def main() -> int:
    sys.stderr.write(STUB_MESSAGE)
    return 90  # distinct exit code: "blocked, deliberately not implemented"


if __name__ == "__main__":
    raise SystemExit(main())