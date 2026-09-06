"""Run one curriculum stage: dry-run gate, then real training (T6.20/T6.22).

Protocol (per milestone spec):
  * T6.20 — a training dry run MUST complete before every real job. A
    failed dry run blocks the stage.
  * T6.21 — one unified adapter: each stage's LoRA weights are
    initialized from the parent adapter (base + T3 for level 1).
  * T6.22 — artifacts under training/curriculum/mango-v0.2/level<N>/
    (checkpoints) and training/adapters/mango-v0.2-L<N> (adapter), with
    full provenance in the manifest.

Usage:
  python scripts/run_curriculum_stage.py --level 1 [--dry-run-only]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.levels import LEVELS  # noqa: E402
from sciencemath.training.config import validate_training_config  # noqa: E402
from sciencemath.training.train import run_training  # noqa: E402
from sciencemath.utils.io_utils import load_yaml, write_json  # noqa: E402

PARENT_ADAPTER = "training/adapters/sciencemath-v0.1-t3"


def stage_config(level: int) -> dict:
    ldef = LEVELS[level]
    base = load_yaml(REPO / "configs" / "training.yaml")
    cfg = copy.deepcopy(base)
    corpus_dir = f"training/curriculum/mango-sft-v2/level{level}"
    cfg["corpus"] = {
        "version": f"mango-sft-v2-level{level}",
        "dir": corpus_dir,
        "require_checksum_match": True,
    }
    t = cfg["training"]
    t["num_train_epochs"] = int(ldef["epochs"])
    t["learning_rate"] = float(ldef["learning_rate"])
    t["output_dir"] = (f"training/curriculum/mango-v0.2/level{level}"
                       "/checkpoints")
    t["adapter_output_dir"] = f"training/adapters/mango-v0.2-L{level}"
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--dry-run-only", action="store_true")
    args = ap.parse_args()
    level = args.level

    corpus_dir = REPO / "training" / "curriculum" / "mango-sft-v2" / \
        f"level{level}"
    if not (corpus_dir / "manifest.json").exists():
        print(f"stage corpus missing: {corpus_dir} — run "
              "scripts/build_curriculum_stage.py first")
        return 2

    cfg = stage_config(level)
    errors = validate_training_config(cfg)
    if errors:
        print("invalid stage config:", errors)
        return 2

    artifact = f"Mango-v0.2-L{level}"
    stage_dir = REPO / "training" / "curriculum" / "mango-v0.2" / f"level{level}"
    smoke_dir = f"training/curriculum/mango-v0.2/level{level}/smoke"

    # ---- T6.20 dry run ----
    print(f"[stage L{level}] training dry run (T6.20) ...", flush=True)
    dry = run_training(cfg, REPO, dry_run=True, dry_run_dir=smoke_dir,
                       dry_run_examples=16, dry_run_steps=3,
                       artifact_name=artifact,
                       init_from_adapter=PARENT_ADAPTER)
    write_json(stage_dir / "dry_run_report.json", dry)
    if dry.get("status") != "COMPLETE":
        print("DRY RUN FAILED — stage blocked (T6.20):", dry)
        return 1
    print(f"[stage L{level}] dry run complete "
          f"(peak_vram={dry.get('peak_vram_bytes')}B)", flush=True)
    if args.dry_run_only:
        return 0

    # ---- real run ----
    print(f"[stage L{level}] real training start ...", flush=True)
    result = run_training(cfg, REPO, artifact_name=artifact,
                          init_from_adapter=PARENT_ADAPTER)
    write_json(stage_dir / "training_summary.json", result)
    if result.get("status") != "COMPLETE":
        print("TRAINING FAILED:", result)
        return 1
    print(json.dumps({k: result[k] for k in
                      ("train_examples", "validation_examples", "steps",
                       "final_train_loss", "best_eval_loss",
                       "peak_vram_bytes", "train_time_s", "adapter_dir",
                       "parent_adapter")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())