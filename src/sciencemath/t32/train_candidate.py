"""T32 Phase 6 training driver: launch one candidate run through run_training.

The recipe is the FROZEN T30 config (configs/training.yaml) with only the
candidate's declared deltas applied (DEV_PROTOCOL.md §8). The driver itself
adds nothing; every override it applies is listed in the candidate's
manifest and echoed to the run summary.

Usage: PYTHONPATH=src python -m sciencemath.t32.train_candidate --candidate A
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, "src")

ROOT = Path(".")

# candidate corpus.version / dir / output paths — keyed like the candidate
# manifests written by sciencemath.t32.mixtures
CANDIDATES: dict[str, dict] = {
    "A": {
        "dir": "training/t32/candidates/t32-A-math-restore",
        "version": "t32-A-math-restore-v1",
        "output_dir": "training/checkpoints/t32-A-math-restore",
        "adapter_output_dir": "training/adapters/t32-A-math-restore",
        "num_train_epochs": 2,
        "learning_rate": None,          # unchanged (1e-4)
        "artifact_name": "Mango-T32-A-math-restore",
    },
    "B": {
        "dir": "training/t32/candidates/t32-B-task-balanced",
        "version": "t32-B-task-balanced-v1",
        "output_dir": "training/checkpoints/t32-B-task-balanced",
        "adapter_output_dir": "training/adapters/t32-B-task-balanced",
        "num_train_epochs": 2,
        "learning_rate": None,          # unchanged (1e-4)
        "artifact_name": "Mango-T32-B-task-balanced",
    },
    "C": {
        # the EXACT frozen T30 corpus; the candidate dir copy is provenance
        "dir": "training/datasets/sciencemath-sft-v1",
        "version": "sciencemath-sft-v1",
        "output_dir": "training/checkpoints/t32-C-conservative",
        "adapter_output_dir": "training/adapters/t32-C-conservative",
        "num_train_epochs": 3,          # unchanged (T30 epochs)
        "learning_rate": 3.0e-5,        # the ONLY change (1e-4 -> 3e-5)
        "artifact_name": "Mango-T32-C-conservative",
    },
}


def build_config(candidate: dict) -> dict:
    from sciencemath.utils.io_utils import load_yaml

    base = load_yaml(ROOT / "configs" / "training.yaml")
    cfg = copy.deepcopy(base)
    cfg["corpus"]["version"] = candidate["version"]
    cfg["corpus"]["dir"] = candidate["dir"]
    # checksums.json was written and verified for the fresh candidate corpora
    cfg["corpus"]["require_checksum_match"] = True
    cfg["training"]["output_dir"] = candidate["output_dir"]
    cfg["training"]["adapter_output_dir"] = candidate["adapter_output_dir"]
    cfg["training"]["num_train_epochs"] = candidate["num_train_epochs"]
    if candidate["learning_rate"] is not None:
        cfg["training"]["learning_rate"] = candidate["learning_rate"]
    overridden = {
        "corpus.dir": cfg["corpus"]["dir"],
        "training.output_dir": cfg["training"]["output_dir"],
        "training.adapter_output_dir": cfg["training"]["adapter_output_dir"],
        "training.num_train_epochs": cfg["training"]["num_train_epochs"],
        "training.learning_rate": cfg["training"]["learning_rate"],
    }
    all_other = {
        k: v for k, v in cfg["training"].items()
        if k not in {"output_dir", "adapter_output_dir",
                     "num_train_epochs", "learning_rate"}
    }
    return cfg, {"overrides_applied": overridden,
                 "everything_else": all_other}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True, choices=sorted(CANDIDATES))
    args = ap.parse_args()

    from sciencemath.training.train import run_training

    name = args.candidate
    cand = CANDIDATES[name]
    cfg, echoed = build_config(cand)

    summary = run_training(cfg, ROOT, artifact_name=cand["artifact_name"])
    if summary.get("status") != "COMPLETE":
        print(json.dumps(summary, indent=2, default=str))
        return 1

    out = ROOT / "evaluations" / "t32" / "development"
    out.mkdir(parents=True, exist_ok=True)
    record = {"candidate": cand["artifact_name"], "recipe_echo": echoed,
              "summary": summary}
    path = out / f"train_{cand['artifact_name']}.json"
    path.write_text(json.dumps(record, indent=2, default=str) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({"status": summary["status"],
                      "steps": summary.get("steps"),
                      "best_eval_loss": summary.get("best_eval_loss"),
                      "reload_ok": summary.get("reload_ok"),
                      "adapter_dir": summary.get("adapter_dir"),
                      "train_time_s": summary.get("train_time_s")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())