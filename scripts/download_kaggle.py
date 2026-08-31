"""Download an approved dataset via the Kaggle CLI or Hugging Face `datasets`,
STRICTLY gated by the license manifest (deny-by-default).

Rules enforced here:
  * The dataset name must exist in data/manifests/datasets.json with
    license_status=APPROVED and license_verified=true; otherwise we refuse
    to download.
  * Kaggle credentials come from the kaggle CLI config (~/.kaggle/kaggle.json
    or KAGGLE_USERNAME/KAGGLE_KEY env vars). Never embed credentials here.

Usage:
  python scripts/download_kaggle.py --dataset gsm8k            # via HF datasets
  python scripts/download_kaggle.py --dataset some-kaggle-slug --provider kaggle
"""
from __future__ import annotations

import argparse
import json
import os

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, setup_logging  # noqa: E402

from sciencemath.datasets.licenses import (  # noqa: E402
    manifest_by_name,
    load_dataset_manifest,
)


def _require_approved(name: str, manifest: list[dict]) -> dict:
    entry = manifest_by_name(manifest).get(name)
    if entry is None:
        raise SystemExit(
            f"REFUSED: '{name}' is not in data/manifests/datasets.json. "
            f"Add an entry (default status REVIEW_REQUIRED), verify the "
            f"license, then re-run.")
    if not entry.get("license_verified") or entry.get("license_status") != "APPROVED":
        raise SystemExit(
            f"REFUSED: '{name}' has license_status="
            f"{entry.get('license_status')} / verified="
            f"{entry.get('license_verified')}. Resolve the license first "
            f"(see data/licenses/LICENSE_MANIFEST.md).")
    return entry


def _download_hf(entry: dict, out: Path) -> Path:
    from datasets import load_dataset  # type: ignore

    hf_id = entry.get("hf_id") or entry.get("name")
    extras = entry.get("hf_kwargs") or {}
    log.info("downloading Hugging Face dataset %s (%s)...", hf_id, entry.get("license"))
    ds = load_dataset(hf_id, **extras)
    out.mkdir(parents=True, exist_ok=True)
    for split_name, split in ds.items():
        path = out / f"{entry['name']}__{split_name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for row in split:
                f.write(json.dumps(dict(row), ensure_ascii=False, default=str) + "\n")
        log.info("wrote %s (%d rows)", path, len(split))
    manifest_file = out / f"{entry['name']}.sources.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    return out


def _download_kaggle(entry: dict, out: Path) -> Path:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi  # type: ignore
    except ImportError:
        raise SystemExit("kaggle CLI not installed: pip install kaggle "
                         "(credentials live in %USERPROFILE%\\.kaggle\\kaggle.json)")
    api = KaggleApi()
    api.authenticate()   # reads ~/.kaggle/kaggle.json; raises if missing
    out.mkdir(parents=True, exist_ok=True)
    log.info("downloading Kaggle dataset %s (%s)...",
             entry.get("kaggle_slug"), entry.get("license"))
    api.dataset_download_files(entry["kaggle_slug"], path=str(out),
                               unzip=True, quiet=False)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="dataset name in datasets.json")
    ap.add_argument("--provider", choices=["huggingface", "kaggle"], default=None)
    args = ap.parse_args()

    log = setup_logging("download_kaggle")
    manifest = load_dataset_manifest(DATA_DIR / "manifests" / "datasets.json")
    entry = _require_approved(args.dataset, manifest)
    provider = args.provider or entry.get("provider", "huggingface")

    out = DATA_DIR / "raw"
    if provider == "huggingface":
        _download_hf(entry, out)
    elif provider == "kaggle":
        _download_kaggle(entry, out)
    else:
        raise SystemExit(f"unknown provider {provider!r}")
    print(f"STATUS: PASS - downloaded '{entry['name']}' via {provider} "
          f"(license {entry.get('license')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())