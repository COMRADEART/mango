"""T12 diagnostic probe (instrument, CPU/GPU): reproduce the arm-A fidelity
b1-call OOM in isolation and identify the failing attention path.

Runs the exact failing input (b1_system + fidelity item 1, 1185 tokens)
with max_new=1 then max_new=300, printing allocated VRAM around each step
and the active attention implementation. Read-only wrt the frozen system.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import torch  # noqa: E402
import t11_scicomp_head_to_head as t11  # noqa: E402
from sciencemath.evaluation.model_loader import load_model_safely  # noqa: E402
from sciencemath.scicomp.registry import build_registry, manifest  # noqa: E402


def gib() -> float:
    return round(torch.cuda.memory_allocated() / 2**30, 3)


def main() -> int:
    tok, mdl, load = load_model_safely("Qwen/Qwen3-4B-Instruct-2507")
    if not load["ok"]:
        print("LOAD FAILED:", load["error"])
        return 1
    print("attn_implementation:", mdl.config._attn_implementation)
    print("allocated after load+smoke:", gib(), "GiB", flush=True)

    items = [json.loads(l) for l in
             (ROOT / "evaluations/t12/suites/fidelity/v1/questions.jsonl")
             .read_text(encoding="utf-8").splitlines() if l.strip()]
    q = items[0]["question"]
    lines = [
        f"- {m['name']} [{m['category']}]: {m['description']} "
        f"| required inputs: {t11.INPUT_SCHEMA.get(m['name'], 'per schema')}"
        for m in manifest(build_registry())]

    def run(tag: str, system: str, max_new: int) -> bool:
        torch.cuda.reset_peak_memory_stats()
        try:
            raw, ms = t11.chat(tok, mdl, system, q, max_new)
            print(f"{tag}: OK  allocated={gib()} GiB  "
                  f"peak={round(torch.cuda.max_memory_allocated()/2**30, 3)} "
                  f"GiB  {ms:.0f} ms  raw[:80]={raw[:80]!r}", flush=True)
            return True
        except torch.cuda.OutOfMemoryError as exc:
            msg = str(exc).split("  See documentation")[0][:220]
            print(f"{tag}: OOM  allocated_at_fail={gib()} GiB  {msg}",
                  flush=True)
            return False

    arm_a_ok = run("ARM_A_SYSTEM max_new=1", t11.ARM_A_SYSTEM, 1)
    b1_short_ok = run("b1_system     max_new=1", t11.build_b1_system(lines), 1)
    if b1_short_ok:
        b1_full_ok = run("b1_system     max_new=300",
                         t11.build_b1_system(lines), 300)
    else:
        # second attempt with a fresh generation context, same input
        b1_full_ok = run("b1_system(2nd) max_new=1",
                         t11.build_b1_system(lines), 1)
    _ = arm_a_ok
    print("probe done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())