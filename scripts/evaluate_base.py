"""T2 base-model evaluation — STUB (not implemented yet).

Will run the full evaluation suite on the untouched base model and write
evaluations/base/{manifest.json, predictions.jsonl, metrics.json, metrics.md,
failures.jsonl}. Baseline MUST exist before T3 fine-tuning begins.
"""
import sys

STUB_MESSAGE = """
STATUS: BLOCKED - evaluate_base is not implemented yet (milestone T2).

Planned behavior:
  * load configs/model.yaml candidate (no adapter)
  * run the 14-category evaluation suite on the held-out test split
  * write evaluations/base/{manifest.json, predictions.jsonl, metrics.json,
    metrics.md, failures.jsonl}
No fabricated numbers will be produced by this stub.
"""


def main() -> int:
    sys.stderr.write(STUB_MESSAGE)
    return 90


if __name__ == "__main__":
    raise SystemExit(main())