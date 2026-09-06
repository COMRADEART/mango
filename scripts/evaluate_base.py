"""T2 base-model evaluation entry point.

Runs the FROZEN suite (sciencemath-eval-v1) on an untouched base candidate and
writes the full artifact set under evaluations/base/<model_slug>/ :
  manifest.json, predictions.jsonl, metrics.json, metrics.md,
  failures.jsonl, hardware.json, generation_config.json,
  model_metadata.json, run.log

Rules enforced here:
  * the suite checksum (checksum.json) is re-verified before ANY generation;
    a mismatch aborts the run — no baseline is valid against a tampered suite
  * inference only: no LoRA, no training, no adapters, no weight changes
  * nothing is tuned per model based on performance; generation settings come
    from each model's OWN documented recommendations (recorded verbatim)
  * resume: re-running the same candidate skips eval_ids already in
    predictions.jsonl

Examples (PowerShell):
  python scripts/evaluate_base.py --candidate A        # Qwen3-1.7B (thinking)
  python scripts/evaluate_base.py --candidate B        # Qwen2.5-Math-1.5B
  python scripts/evaluate_base.py --candidate A --limit 5   # smoke run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import CONFIG_DIR, REPO_ROOT  # noqa: E402

from sciencemath.evaluation.runner import evaluate_model  # noqa: E402
from sciencemath.utils.io_utils import load_json, load_yaml, write_json  # noqa: E402

EVAL_DIR = REPO_ROOT / "evaluations"
SUITE_DIR = EVAL_DIR / "suite" / "v1"
BASE_DIR = EVAL_DIR / "base"

# Generation settings: each model's own documented recommendation, recorded
# verbatim in generation_config.json. NOT tuned on eval performance.
# Qwen3 thinking mode sampling per Qwen3 model card (greedy discouraged):
#   temperature 0.6, top_p 0.95, top_k 20. Seed pinned for reproducibility.
GENERATION_PRESETS = {
    "A": {
        "mode": "thinking",
        "enable_thinking": True,
        "generation": {
            "seed": 42, "do_sample": True, "temperature": 0.6,
            "top_p": 0.95, "top_k": 20, "max_new_tokens": 4096,
        },
        "max_seq_tokens": 8192,
        "prompt_note": "Qwen3 chat template with enable_thinking=True; "
                       "gradable text is taken after the closing reasoning tag",
        # Recorded configuration change (user-approved 2026-08-31, BEFORE the
        # 4096 baseline started): max_new_tokens 2048 -> 4096. The 2048
        # budget truncated ~34% of thinking outputs (all 25 extraction
        # failures in the partial run were exactly-2048 cutoffs; finished
        # answers scored 91.1%), i.e. the metric measured the token budget,
        # not the model. Measurement-validity fix, NOT performance tuning:
        # applied uniformly to all 188 questions; prompts/questions unchanged;
        # the 2048 partial run is archived at
        # evaluations/base/qwen3-1.7b/archive_max2048_budget/ as provenance.
        "config_change_note": "max_new_tokens 2048->4096 (measurement "
                              "validity; truncation was the dominant error "
                              "mode in the archived partial run)",
    },
    "A_non_thinking": {
        "mode": "non_thinking",
        "enable_thinking": False,
        "generation": {
            "seed": 42, "do_sample": False, "temperature": None,
            "top_p": None, "top_k": None, "max_new_tokens": 1024,
        },
        "max_seq_tokens": 8192,
        "prompt_note": "Qwen3 chat template with enable_thinking=False "
                       "(secondary comparison run, not part of primary table)",
    },
    "B": {
        "mode": "cot",
        "enable_thinking": None,
        "generation": {
            "seed": 42, "do_sample": False, "temperature": None,
            "top_p": None, "top_k": None, "max_new_tokens": 1024,
        },
        "max_seq_tokens": 4096,
        "prompt_note": "greedy decoding per Qwen2.5-Math model card; CoT "
                       "convention \\boxed{} (no TIR: T4 tools out of T2 scope)",
    },
    "C": {
        "mode": "cot",
        "enable_thinking": None,
        "generation": {
            "seed": 42, "do_sample": False, "temperature": None,
            "top_p": None, "top_k": None, "max_new_tokens": 1024,
        },
        "max_seq_tokens": 8192,
        "prompt_note": "greedy decoding (general instruct baseline)",
    },
}


def verify_suite(suite_dir: Path) -> dict:
    """Recompute SHA-256 of every frozen file and compare to checksum.json."""
    checksum = load_json(suite_dir / "checksum.json")
    problems = []
    for name, recorded in sorted(checksum["files"].items()):
        p = suite_dir / name
        if not p.exists():
            problems.append({"file": name, "problem": "MISSING"})
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != recorded:
            problems.append({"file": name, "problem": "HASH_MISMATCH",
                             "recorded": recorded, "actual": actual})
    extra = sorted(p.name for p in suite_dir.iterdir() if p.is_file()
                   and p.name not in checksum["files"]
                   and p.name != "checksum.json")
    report = {"suite_version": checksum["suite_version"],
              "frozen_at": checksum["frozen_at"],
              "verified": not problems, "problems": problems,
              "files": sorted(checksum["files"]),
              "extra_unlisted_files": extra,
              "verified_at": datetime.now(timezone.utc).isoformat()}
    return report


def candidate_from_config(candidate_key: str) -> dict:
    cfg = load_yaml(CONFIG_DIR / "model.yaml")
    matches = [c for c in cfg.get("candidates", [])
               if c.get("candidate_key") == candidate_key]
    if not matches:
        raise SystemExit(
            f"candidate key {candidate_key!r} not found in configs/model.yaml "
            f"(allowed: {[c.get('candidate_key') for c in cfg.get('candidates', [])]})")
    return matches[0]


def record_environment() -> dict:
    """Snapshot the T2 runtime environment into evaluations/t2_environment.json."""
    import torch
    import transformers

    from sciencemath.utils.hardware import full_report

    env = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "torch_cuda_available": torch.cuda.is_available(),
        "torch_cuda_version": (torch.version.cuda if torch.cuda.is_available()
                               else None),
        "transformers": transformers.__version__,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "vram_total_bytes": (int(torch.cuda.get_device_properties(0).total_memory)
                             if torch.cuda.is_available() else None),
        "hardware_report": full_report().to_dict(),
    }
    try:
        import bitsandbytes
        env["bitsandbytes"] = bitsandbytes.__version__
    except Exception as exc:
        env["bitsandbytes"] = f"unavailable ({exc})"
    try:
        import datasets

        env["datasets"] = datasets.__version__
    except Exception:
        env["datasets"] = "unavailable"
    write_json(EVAL_DIR / "t2_environment.json", env)
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, choices=["A", "B", "C"],
                        help="candidate key from configs/model.yaml")
    parser.add_argument("--variant", choices=["primary", "non_thinking"],
                        default="primary",
                        help="A only: primary thinking run or secondary "
                             "non_thinking comparison run")
    parser.add_argument("--limit", type=int, default=None,
                        help="evaluate only the first N questions (smoke test "
                             "only; marked PARTIAL/limited in the manifest)")
    parser.add_argument("--4bit", dest="quantized", action="store_true",
                        default=True)
    parser.add_argument("--no-4bit", dest="quantized", action="store_false",
                        help="load in bf16 instead of 4-bit NF4")
    args = parser.parse_args()

    preset_key = args.candidate if args.variant == "primary" else \
        f"{args.candidate}_non_thinking"
    preset = GENERATION_PRESETS[preset_key]
    cand = candidate_from_config(args.candidate)
    model_id = cand["name"]
    model_slug = model_id.split("/")[-1].lower() + (
        "_non_thinking" if args.variant == "non_thinking" else "")
    out_dir = BASE_DIR / model_slug

    # ---- gate 1: frozen suite integrity ----
    suite_check = verify_suite(SUITE_DIR)
    if not suite_check["verified"]:
        write_json(out_dir / "manifest.json", {
            "model_id": model_id, "status": "SUITE_VERIFICATION_FAILED",
            "suite_check": suite_check})
        print(f"ABORTED: frozen suite {suite_check.get('suite_version')} "
              f"checksum verification failed: {suite_check['problems']}")
        return 8

    # ---- gate 2: license APPROVED in the model manifest ----
    model_manifest = load_json(EVAL_DIR / "model_manifest.json")
    entry = model_manifest.get("models", {}).get(model_id)
    if entry is None or entry.get("license_status") != "APPROVED":
        write_json(out_dir / "manifest.json", {
            "model_id": model_id, "status": "LICENSE_GATE_FAILED",
            "license_status": None if entry is None else
            entry.get("license_status")})
        print(f"ABORTED: {model_id} is not license-APPROVED in "
              f"evaluations/model_manifest.json (T2 refuses to run unapproved "
              f"models).")
        return 9

    env = record_environment()

    # ---- run (resume-capable; artifacts inside runner.evaluate_model) ----
    result = evaluate_model(
        model_id=model_id,
        mode=preset["mode"],
        model_slug=model_slug,
        suite_dir=SUITE_DIR,
        out_dir=out_dir,
        generation=preset["generation"],
        quantized_4bit=args.quantized,
        enable_thinking=preset["enable_thinking"],
        max_seq_tokens=preset["max_seq_tokens"],
        limit=args.limit,
    )

    # ---- post-run manifest additions (suite + environment provenance) ----
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        manifest.update({
            "candidate_key": args.candidate,
            "variant": args.variant,
            "suite_check": suite_check,
            "license_status": entry.get("license_status"),
            "license": cand.get("license"),
            "prompt_note": preset["prompt_note"],
            "config_change_note": preset.get("config_change_note"),
            "t2_environment": str(EVAL_DIR / "t2_environment.json"),
            "suite_version": suite_check.get("suite_version"),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        write_json(manifest_path, manifest)

    # keep a copy of the run log with the artifacts
    log_src = REPO_ROOT / "training" / "logs"
    logs = sorted(log_src.glob("*.log"), key=lambda p: p.stat().st_mtime)
    if logs:
        shutil.copy2(logs[-1], out_dir / "run.log")

    status = result.get("status")
    print(json.dumps({"status": status,
                      "model": model_id,
                      "out_dir": str(out_dir),
                      "n_predictions": result.get("n_predictions"),
                      "overall_accuracy":
                          (result.get("metrics") or {}).get("overall_accuracy")},
                         indent=2))
    return 0 if status == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())