"""T3 tuned-model evaluation — STUB (not implemented yet).

Will run the exact same suite as evaluate_base.py against base+adapter and
write evaluations/tuned/. Requires evaluations/base/ to exist for the
BASE vs TUNED comparison.
"""
import sys

STUB_MESSAGE = """
STATUS: BLOCKED - evaluate_tuned is not implemented yet (milestone T3).
Requires: a trained adapter (train_lora.py) and evaluations/base/ results.
"""


def main() -> int:
    sys.stderr.write(STUB_MESSAGE)
    return 90


if __name__ == "__main__":
    raise SystemExit(main())