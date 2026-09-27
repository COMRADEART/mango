#!/usr/bin/env python3
"""Build/reproduce the additive T26 GENERAL-context inspection package.

No command in this module imports or opens the real private store, constructs
an evaluation ledger, invokes the official evaluator, or executes a candidate
scenario.  Model/tokenizer dependencies are loaded solely from public frozen
artifacts before canonical factory construction-only preflight.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from t21_protocol.util import read_json, sha256_file, sha256_json  # noqa: E402
from t26_protocol.evaluation_v2 import (  # noqa: E402
    run_public_addendum_leak_scan, verify_original_v3_components,
)
from t26_protocol.official_runner import (  # noqa: E402
    GENERAL_CONTEXT_IDENTITY_PATH, IDENTITY_PATH,
    build_general_context_identity, build_official_runner_factory,
    build_runner_identity_document, inspect_general_context,
    inspect_live_provider, validate_factory_instance,
    validate_stack_attestation, verify_runner_identity_document,
)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def _production_context():
    from sciencemath.executive.runner import ExecContext
    from sciencemath.training.attach import load_base_with_adapter

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    config = read_json(ROOT / "evaluations/t25/production_provider_config.json")
    adapter = ROOT / config["general_adapter"]
    if (adapter.stat().st_size != 139512976 or
            sha256_file(adapter) != config["general_adapter_sha256"]):
        raise ValueError("qualified hydrated GENERAL adapter unavailable")
    manifest = read_json(adapter.parent / "artifact_manifest.json")
    if (manifest["base_model"] != config["general_model"] or
            manifest["base_revision"] != config["general_base_revision"]):
        raise ValueError("qualified GENERAL adapter provenance mismatch")
    import torch

    torch.set_num_threads(min(4, os.cpu_count() or 4))
    tokenizer, model, info = load_base_with_adapter(
        config["general_model"], str(adapter.parent), quantized_4bit=False)
    if not info.get("ok") or not info.get("adapter_state", {}).get("adapter_active"):
        raise ValueError(f"qualified GENERAL runtime unavailable: {info.get('error')}")
    return ExecContext(model=model, tokenizer=tokenizer,
                       generation=dict(config["general_generation"]))


def _semantic_preflight(context, provider) -> dict:
    context_identity = inspect_general_context(ROOT, context, real=True)
    provider_identity = inspect_live_provider(ROOT, provider, real=True)
    factory = build_official_runner_factory(
        ROOT, live_web_provider=provider, general_context=context, real=True)
    validate_factory_instance(factory, ROOT, real=True)
    if factory.runner_count != 0:
        raise ValueError("preflight started with nonzero candidate executions")
    stack = factory.preflight()
    validate_stack_attestation(stack, real=True)
    if factory.runner_count != 0:
        raise ValueError("factory preflight executed a candidate scenario")
    return {
        "general_context_identity_root": context_identity["identity_root"],
        "model_provenance": context_identity["model"],
        "tokenizer_identity": context_identity["tokenizer"],
        "registry_identity": context_identity["registry"],
        "retriever_identity": context_identity["retriever"],
        "generation_root": context_identity["generation"]["root"],
        "usage_root": context_identity["initial_usage"]["root"],
        "budget_root": context_identity["budgets"]["root"],
        "feature_root": context_identity["features"]["root"],
        "trajectory_policy": context_identity["trajectory_policy"],
        "checkpointer_policy": context_identity["checkpointer_policy"],
        "retrieval_k": context_identity["retrieval_k"],
        "live_provider_identity": provider_identity,
        "factory_binding": factory.binding(),
        "stack_attestation": stack,
    }


def preflight(*, build_identities: bool, output: Path) -> dict:
    from sciencemath.web.live_provider import WikipediaLiveProvider

    context = _production_context()
    if build_identities:
        _write(ROOT / GENERAL_CONTEXT_IDENTITY_PATH,
               build_general_context_identity(ROOT, context))
        _write(ROOT / IDENTITY_PATH, build_runner_identity_document(ROOT))
    else:
        verify_runner_identity_document(ROOT)
    provider = WikipediaLiveProvider(timeout_s=8.0, enabled=True)
    semantic = _semantic_preflight(context, provider)
    report = {
        "schema_version": "t26-general-context-production-preflight-v1",
        "artifact": "T26_GENERAL_CONTEXT_PRODUCTION_PREFLIGHT",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "semantic": semantic,
        "candidate_executions": 0, "web_searches": 0,
        "sealed_store_rows_read": 0, "sealed_store_accessed": False,
        "official_evaluator_invocations": 0,
    }
    _write(output, report)
    return report


def finalize(first_path: Path, second_path: Path) -> dict:
    from t26_protocol.evaluation_v4 import (
        ADDENDUM_PATH, FREEZE_PATH, REHEARSAL_PATH,
        build_addendum_document, build_addendum_freeze,
        verify_addendum_document_v3, verify_addendum_freeze_v3,
    )

    runs = [read_json(first_path), read_json(second_path)]
    if any(run.get("status") != "PASS" for run in runs):
        raise ValueError("production context preflight failed")
    equal = runs[0]["semantic"] == runs[1]["semantic"]
    if not equal:
        raise ValueError("production context preflight semantic drift")
    reproduction = {
        "schema_version": "t26-general-context-preflight-reproduction-v1",
        "artifact": "T26_GENERAL_CONTEXT_PREFLIGHT_REPRODUCTION",
        "classification": "PUBLIC_SAFE",
        "status": "PASS", "run_count": 2,
        "semantic_reproducibility": True,
        "semantic_identity_root": sha256_json(runs[0]["semantic"]),
        "runs": runs,
        "candidate_executions": 0, "web_searches": 0,
        "sealed_store_rows_read": 0, "sealed_store_accessed": False,
        "official_evaluator_invocations": 0,
    }
    _write(ROOT / REHEARSAL_PATH, reproduction)
    _write(ROOT / ADDENDUM_PATH, build_addendum_document(ROOT))
    _write(ROOT / FREEZE_PATH, build_addendum_freeze(ROOT))
    addendum = verify_addendum_document_v3(ROOT)
    freeze = verify_addendum_freeze_v3(ROOT)
    result = {
        "status": "PASS", "reproduction": reproduction,
        "general_context_identity_root":
            runs[0]["semantic"]["general_context_identity_root"],
        "runner_factory_identity_root":
            verify_runner_identity_document(ROOT)["identity_root"],
        "evaluation_implementation_sha256":
            addendum["evaluation_implementation_sha256"],
        "freeze": freeze,
    }
    return result


def reproduce_static() -> dict:
    from t26_protocol.evaluation_v3 import (
        verify_addendum_document_v2, verify_addendum_freeze_v2)
    from t26_protocol.evaluation_v4 import (
        REHEARSAL_PATH, verify_addendum_document_v3,
        verify_addendum_freeze_v3)

    original = verify_original_v3_components(ROOT)
    predecessor_addendum = verify_addendum_document_v2(ROOT)
    predecessor_freeze = verify_addendum_freeze_v2(ROOT)
    runner = verify_runner_identity_document(ROOT)
    addendum = verify_addendum_document_v3(ROOT)
    freeze = verify_addendum_freeze_v3(ROOT)
    reproduction = read_json(ROOT / REHEARSAL_PATH)
    leak = run_public_addendum_leak_scan(ROOT)
    status = "PASS" if all((
        original["status"] == "PASS",
        predecessor_freeze["status"] == "PASS",
        reproduction["status"] == "PASS",
        reproduction["semantic_reproducibility"] is True,
        freeze["status"] == "PASS", leak["status"] == "PASS",
    )) else "FAIL"
    return {
        "status": status, "original_freeze": original,
        "predecessor_addendum_schema": predecessor_addendum["schema_version"],
        "predecessor_freeze": predecessor_freeze,
        "runner_factory_identity_root": runner["identity_root"],
        "general_context_identity_root": addendum["general_context_identity_root"],
        "new_freeze": freeze, "publication_scan": leak,
        "real_private_rows_read": 0, "real_candidate_executions": 0,
        "official_evaluator_invocations": 0,
        "real_evaluation_ledger_created": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    build = sub.add_parser("build-preflight")
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("preflight")
    run.add_argument("--output", type=Path, required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--first", type=Path, required=True)
    final.add_argument("--second", type=Path, required=True)
    sub.add_parser("reproduce-static")
    args = parser.parse_args()
    if args.mode == "build-preflight":
        result = preflight(build_identities=True, output=args.output)
    elif args.mode == "preflight":
        result = preflight(build_identities=False, output=args.output)
    elif args.mode == "finalize":
        result = finalize(args.first, args.second)
    else:
        result = reproduce_static()
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
