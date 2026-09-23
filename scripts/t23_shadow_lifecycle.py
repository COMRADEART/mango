#!/usr/bin/env python3
"""Run two T23 disposable, nonblind production lifecycle rehearsals.

No real T23 path is written. The only workspaces are TemporaryDirectory roots;
the summary printed to stdout contains no case, gold, or candidate content.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from sciencemath.executive.runner import ExecContext  # noqa: E402
from sciencemath.training.attach import load_base_with_adapter  # noqa: E402
from t21_protocol.util import iter_jsonl, read_json, sha256_file  # noqa: E402
from t23_protocol.construction import run_shadow_construction  # noqa: E402
from t23_protocol.evaluation import run_shadow_evaluation  # noqa: E402
from t23_protocol.graph import load_graph, validate_graph  # noqa: E402
from t23_protocol.lock import verify_lock  # noqa: E402
from t23_protocol.lifecycle import verify_lifecycle  # noqa: E402


CONSTRUCTION_PRODUCTS = (
    "documents/shadow.txt",
    "rag/gk_holdout_t23/sources.jsonl",
    "rag/gk_holdout_t23/chunks.jsonl",
    "rag/gk_holdout_t23/corpus_manifest.json",
    "evaluations/t23/suites/inputs.jsonl",
    "evaluations/t23/suites/gold.jsonl",
    "evaluations/t23/construction_audits.json",
)
EVALUATION_PRODUCTS = (
    "evaluations/t23/router_decisions.jsonl",
    "evaluations/t23/router_evaluator.jsonl",
    "evaluations/t23/capability_evaluator.jsonl",
    "evaluations/t23/router_metric_evidence.json",
    "evaluations/t23/router_floor_evidence.json",
    "evaluations/t23/protected_t22_metric_evidence.json",
    "evaluations/t23/protected_t22_floor_evidence.json",
    "evaluations/t23/holdout_results.json",
)


def _product_hashes(workspace: Path, products: tuple[str, ...]) -> dict[str, str]:
    return {relative: sha256_file(workspace / relative) for relative in products}


def _evaluation_semantic_hash(workspace: Path) -> str:
    # Runtime evidence legitimately contains wall-clock latency and disposable
    # absolute paths. Compare every routed case and its capability decision,
    # status, and answer while excluding only those non-semantic fields.
    rows = []
    for output in iter_jsonl(workspace / "evaluations/t23/candidate_outputs.jsonl"):
        execution = output["selected_capability_execution"]
        rows.append({"case_id": output["case_id"],
                     "router_decision": output["router_decision"],
                     "capability": execution["capability"],
                     "status": execution["status"],
                     "answer": execution["answer"]})
    if len(rows) != 1280:
        raise ValueError("disposable evaluation did not produce 1,280 semantic rows")
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _general_context() -> ExecContext:
    config = read_json(ROOT / "evaluations" / "t23" / "production_provider_config.json")
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


def run_twice() -> dict:
    before = verify_lifecycle(ROOT, "t23")
    if before["status"] != "PASS" or before["registered_paths"] != 22 or before["present_paths"] != 0:
        raise ValueError(f"real T23 path registry invalid before shadow lifecycle: {before}")
    lock = verify_lock()
    graph = validate_graph(load_graph())
    context = _general_context()
    summaries = []
    for number in (1, 2):
        print(f"starting disposable lifecycle {number}/2", file=sys.stderr, flush=True)
        with TemporaryDirectory(prefix=f"t23-shadow-lifecycle-{number}-") as directory:
            workspace = Path(directory)
            construction = run_shadow_construction(ROOT, workspace)
            construction_hashes = _product_hashes(workspace, CONSTRUCTION_PRODUCTS)
            print(f"disposable lifecycle {number}/2 SEALED; evaluating", file=sys.stderr, flush=True)
            evaluation = run_shadow_evaluation(ROOT, workspace, general_context=context)
            evaluation_hashes = _product_hashes(workspace, EVALUATION_PRODUCTS)
            evaluation_hashes["candidate_output_semantics"] = _evaluation_semantic_hash(workspace)
            summaries.append({
                "run": number,
                "status": "PASS" if construction["status"] == evaluation["status"] == "PASS" else "FAIL",
                "construction_terminal": construction["terminal_state"],
                "construction_transitions": construction["transitions"],
                "construction_product_sha256": construction_hashes,
                "seal_status": construction["seal"]["status"],
                "evaluation_terminal": evaluation["terminal_state"],
                "evaluation_transitions": evaluation["transitions"],
                "evaluation_product_sha256": evaluation_hashes,
                "rows": evaluation["rows"],
                "router_metrics": {key: value["observed"] for key, value in evaluation["router_metrics"]["metrics"].items()},
                "router_floor_pass_count": sum(item["pass"] for item in evaluation["router_metrics"]["floors"].values()),
                "protected_t22_floors": evaluation["protected_t22_floors"],
                "provider_initialization_rows": evaluation["provider_initialization_rows"],
                "provider_parity": evaluation["provider_parity"],
                "artifact_graph": evaluation["evaluation_graph"],
                "real_t23_paths_touched": construction["real_t23_paths_touched"],
                "disposable_workspace_destroyed": True,
            })
    first, second = summaries
    after = verify_lifecycle(ROOT, "t23")
    if after["status"] != "PASS" or after["registered_paths"] != 22 or after["present_paths"] != 0:
        raise ValueError(f"real T23 path registry invalid after shadow lifecycle: {after}")
    comparisons = {
        "construction_transition_differences": int(first["construction_transitions"] != second["construction_transitions"])
        + sum(first["construction_product_sha256"][path] != second["construction_product_sha256"][path]
              for path in CONSTRUCTION_PRODUCTS),
        "evaluation_transition_differences": int(first["evaluation_transitions"] != second["evaluation_transitions"])
        + sum(first["evaluation_product_sha256"][path] != second["evaluation_product_sha256"][path]
              for path in (*EVALUATION_PRODUCTS, "candidate_output_semantics")),
        "artifact_graph_differences": int(first["artifact_graph"] != second["artifact_graph"]),
        "metric_calculation_differences": int(first["router_metrics"] != second["router_metrics"] or first["protected_t22_floors"] != second["protected_t22_floors"]),
    }
    return {"schema_version": "t23-production-shadow-lifecycle-v1",
            "artifact": "T23_PRODUCTION_SHADOW_LIFECYCLE",
            "material": "DISPOSABLE_SYNTHETIC_NONBLIND",
            "registered_real_t23_paths": after["registered_paths"],
            "real_t23_paths_touched": False,
            "real_construction_attempts": 0,
            "real_evaluation_attempts": 0,
            "real_blind_rows": 0,
            "author_fingerprint_root": lock["author_fingerprint_root"],
            "evaluation_graph": graph,
            "runs": summaries,
            "comparisons": comparisons,
            "status": "PASS" if all(run["status"] == "PASS" for run in summaries) and not any(comparisons.values()) else "FAIL"}


if __name__ == "__main__":
    report = run_twice()
    if "--write-report" in sys.argv[1:]:
        target = ROOT / "evaluations" / "t23" / "production_shadow_lifecycle_report.json"
        target.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps({"status": report["status"], "runs": len(report["runs"]),
                      "comparisons": report["comparisons"],
                      "real_t23_paths_touched": report["real_t23_paths_touched"]},
                     sort_keys=True), flush=True)
