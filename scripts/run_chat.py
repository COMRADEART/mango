"""T6 integrated chat CLI — STUB (not implemented yet).

Will provide the local assistant: base model + LoRA adapter + math tools
(SymPy verification) + Wikipedia RAG with source attribution, exposing
/math /science /rag /tools /sources /status modes and concise|student|
detailed explanation levels.
"""
import sys

STUB_MESSAGE = """
STATUS: BLOCKED - run_chat is not implemented yet (milestone T6).
The integrated assistant combines: trained adapter (T3) + math tools (T4)
+ Wikipedia RAG (T5). Run the earlier milestones first.
"""


def main() -> int:
    sys.stderr.write(STUB_MESSAGE)
    return 90


if __name__ == "__main__":
    raise SystemExit(main())