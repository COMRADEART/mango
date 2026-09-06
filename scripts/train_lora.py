"""T3 QLoRA training entry point.

Usage:
  python scripts/train_lora.py --dry-run          # T3.2 smoke (isolated dir)
  python scripts/train_lora.py                    # T3.3 real run

Refuses to run when: the config fails validation, the frozen corpus
checksums don't match, or the model.yaml selection is missing. A dry run
writes ONLY under training/smoke/ and can never be mistaken for the real
adapter artifact.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, load_configs, setup_logging  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="tiny smoke run (isolated output, real artifacts untouched)")
    ap.add_argument("--dry-run-examples", type=int, default=16)
    ap.add_argument("--dry-run-steps", type=int, default=3)
    args = ap.parse_args()

    log = setup_logging("train_lora")
    cfg = load_configs().get("training", {})

    from sciencemath.training.train import run_training

    if not args.dry_run:
        # hard safety gate: the real run requires the dry-run report to exist
        smoke = REPO_ROOT / "training" / "smoke" / "t3_dry_run" / "dry_run_report.json"
        if not smoke.exists():
            print("REFUSED: no T3.2 dry-run report at training/smoke/t3_dry_run/"
                  "dry_run_report.json. Run `python scripts/train_lora.py --dry-run` "
                  "first (memory measurement before real training is required).")
            return 91

    summary = run_training(cfg, REPO_ROOT, dry_run=args.dry_run,
                           dry_run_examples=args.dry_run_examples,
                           dry_run_steps=args.dry_run_steps)
    print(json.dumps(summary, indent=1, default=str))
    if summary.get("status") != "COMPLETE":
        return 92
    return 0


if __name__ == "__main__":
    raise SystemExit(main())