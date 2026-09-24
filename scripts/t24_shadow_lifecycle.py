#!/usr/bin/env python3
"""Run the two T24 disposable E2E rehearsals and register their fingerprints.

No real T24 path or private namespace is touched. The only private stores and
workspaces are TemporaryDirectory roots outside the repository, destroyed after
each run. Afterward the rehearsal-exclusive fingerprints are registered in the
exclusion registry, the author lock is regenerated, and the public-safe report
is written. The report carries hashes, counts, and fingerprints only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from t21_protocol.util import read_json, sha256_file  # noqa: E402

T24 = ROOT / "evaluations" / "t24"


def _general_context():
    from sciencemath.executive.runner import ExecContext
    from sciencemath.training.attach import load_base_with_adapter

    config = read_json(T24 / "production_provider_config.json")
    adapter = ROOT / config["general_adapter"]
    if sha256_file(adapter) != config["general_adapter_sha256"]:
        raise ValueError("frozen GENERAL adapter bytes changed")
    adapter_manifest = read_json(adapter.parent / "artifact_manifest.json")
    if adapter_manifest["base_revision"] != config["general_base_revision"]:
        raise ValueError("GENERAL base revision differs from frozen provider config")
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch

    torch.set_num_threads(min(4, os.cpu_count() or 4))
    print("loading pinned GENERAL runtime", file=sys.stderr, flush=True)
    tokenizer, model, info = load_base_with_adapter(
        config["general_model"], str(adapter.parent), quantized_4bit=False)
    if not info.get("ok") or not info.get("adapter_state", {}).get("adapter_active"):
        raise ValueError(f"qualified GENERAL runtime unavailable: {info.get('error')}")
    return ExecContext(model=model, tokenizer=tokenizer,
                       generation=dict(config["general_generation"]))


def _register_fingerprints(fingerprints: dict[str, list[str]]) -> None:
    from t21_protocol.util import sha256_json

    document = {"schema_version": "t24-dimension-fingerprint-set-v1",
                "artifact": "T24_DISPOSABLE_REHEARSAL_FINGERPRINTS",
                "experiment": "t24", "raw_values_included": False,
                "dimensions": {name: sorted(set(values))
                               for name, values in sorted(fingerprints.items())},
                "dimension_counts": {name: len(set(values))
                                     for name, values in sorted(fingerprints.items())}}
    (T24 / "rehearsal_exclusion_fingerprints.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    registry_path = T24 / "t24_exclusion_sources.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    binding = registry["sources"]["t24_disposable_rehearsal"]
    binding["path"] = "evaluations/t24/rehearsal_exclusion_fingerprints.json"
    binding["sha256"] = sha256_file(T24 / "rehearsal_exclusion_fingerprints.json")
    registry["rehearsal_registration"] = {
        "registered": True, "registration_stage": "POST_REHEARSAL",
        "registered_dimensions": sorted(fingerprints),
        "note": "corpus identities are public shared material and are not "
                "rehearsal-exclusive"}
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8", newline="\n")
    from t24_protocol.exclusions import load_exclusion_sources

    forbidden = load_exclusion_sources(ROOT, registry)
    counts = {name: len(values) for name, values in forbidden.items()}
    if sum(counts.values()) < 100:
        raise ValueError(f"registered rehearsal fingerprints lost: {counts}")
    print("rehearsal fingerprints registered:", counts, file=sys.stderr, flush=True)


def main() -> None:
    from t24_protocol.lock import expected_lock, verify_lock
    from t24_protocol.shadow import run_two_rehearsals

    author_lock_sha256 = sha256_file(T24 / "author_lock.json")
    context = _general_context()
    report = run_two_rehearsals(ROOT, general_context=context,
                                author_lock_sha256=author_lock_sha256)
    if report["status"] != "PASS":
        raise ValueError(f"T24 disposable rehearsals failed: {report['comparisons']}")
    _register_fingerprints(report["rehearsal_fingerprints"])
    (T24 / "author_lock.json").write_text(
        json.dumps(expected_lock(), indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    verify_lock()
    (T24 / "production_shadow_lifecycle_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    runs = report["runs"]
    print(json.dumps({"runs": [run["status"] for run in runs],
                      "rows": runs[0]["rows"],
                      "construction_semantic_diff": report["comparisons"]["construction_semantic_diff"],
                      "manifest_commitment_diff": report["comparisons"]["manifest_commitment_diff"],
                      "evaluation_semantic_diff": report["comparisons"]["evaluation_semantic_diff"],
                      "metric_diff": report["comparisons"]["metric_diff"],
                      "graph_diff": report["comparisons"]["graph_diff"],
                      "router_floor_pass_count": runs[0]["router_floor_pass_count"],
                      "protected_t22_floors": runs[0]["protected_t22_floors"],
                      "real_namespace_touched": False,
                      "report": "evaluations/t24/production_shadow_lifecycle_report.json"},
                     indent=1))
    print("T24 REHEARSALS PASS", flush=True)


if __name__ == "__main__":
    main()