"""T3 adapter merging — STUB (optional utility).

Will merge the LoRA adapter into a full model copy under
training/adapters/sciencemath-v0.1/merged/. Not required for normal
inference (run_chat.py loads base+adapter directly).
"""
import sys

STUB_MESSAGE = """
STATUS: BLOCKED - merge_adapter is not implemented yet (milestone T3, optional).
Merging is never required for normal use; run_chat.py loads base+LoRA directly.
"""


def main() -> int:
    sys.stderr.write(STUB_MESSAGE)
    return 90


if __name__ == "__main__":
    raise SystemExit(main())