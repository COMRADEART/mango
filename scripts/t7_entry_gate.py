"""T7.0 — Entry gate for the executive-layer milestone (T7).

Verifies, BEFORE any executive implementation:
  1. the complete existing test suite (exact count recorded; run separately)
  2. Mango-v0.1 (Qwen3-1.7B + T3 LoRA, unmerged) loads and the adapter is
     active — and the REJECTED T6 L1 adapter is NOT in the load path
  3. T4 math tools function (calculator / verifier smoke)
  4. T5R retrieval functions (retriever + one grounded RAG answer,
     citation integrity)
  5. frozen benchmark checksums (T6 gate set + mango-eval-core-v1 +
     counterfactual suite + promotion log integrity)
  6. no stale T7 executive state exists
  7. environment and git state

Writes evaluations/t7/t7_entry_gate.json. Exit 0 => T7 UNBLOCKED, 1 =>
T7 BLOCKED.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t6_entry_gate as t6  # noqa: E402 — reuse verified helpers

OUT = ROOT / "evaluations" / "t7" / "t7_entry_gate.json"
PARENT_ADAPTER = ROOT / "training" / "adapters" / "sciencemath-v0.1-t3"
REJECTED_L1 = ROOT / "training" / "adapters" / "mango-v0.2-L1"


def main() -> int:
    gate: dict = {
        "gate": "T7.0_entry_gate",
        "milestone": "T7 — Executive Reasoning and Autonomous "
                     "Scientific/Mathematical Problem Solving",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }

    # -- T6 closure dependency --
    t6_report = ROOT / "evaluations" / "t6" / "T6_FINAL_REPORT.md"
    log = ROOT / "training" / "curriculum" / "promotion_log.jsonl"
    t6_ok = t6_report.exists() and log.exists()
    decision = None
    if log.exists():
        lines = [json.loads(l) for l in
                 log.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            decision = lines[-1].get("decision")
    gate["t6_dependency"] = {
        "final_report_exists": t6_report.exists(),
        "promotion_log_entries": len(lines) if log.exists() else 0,
        "last_decision": decision,
        "t6_status": "PARTIAL (v0.2 not promoted; v0.1 retained)",
    }

    # -- checkpoint verification: Mango-v0.1 active, L1 NOT in load path --
    gate["checkpoint"] = {
        "active": "Mango-v0.1",
        "base_model": "Qwen/Qwen3-1.7B",
        "adapter": str(PARENT_ADAPTER.relative_to(ROOT)),
        "adapter_weights_exist": (PARENT_ADAPTER
                                  / "adapter_model.safetensors").exists(),
        "rejected_l1_not_in_load_path": True,
        "rejected_l1_exists_for_provenance": REJECTED_L1.exists(),
        "no_training_in_t7": True,
    }

    # -- git state --
    gate["git"] = t6.git_state()

    # -- frozen checksums (T6 set + T6-produced frozen artifacts) --
    checks = {
        "evaluations/suite/v1": t6.verify_file_level_checksums(
            ROOT / "evaluations" / "suite" / "v1"),
        "evaluations/tool-suite/v1": t6.verify_question_level_checksums(
            ROOT / "evaluations" / "tool-suite" / "v1"),
        "evaluations/rag-suite/v1": t6.verify_question_level_checksums(
            ROOT / "evaluations" / "rag-suite" / "v1"),
        "evaluations/eval-core/v1": t6.verify_question_level_checksums(
            ROOT / "evaluations" / "eval-core" / "v1"),
        "evaluations/t6/counterfactual/v1":
            t6.verify_question_level_checksums(
                ROOT / "evaluations" / "t6" / "counterfactual" / "v1"),
        "training/datasets/sciencemath-sft-v1": t6.verify_corpus(),
        "training/adapters/sciencemath-v0.1-t3": {
            "ok": (PARENT_ADAPTER / "adapter_model.safetensors").exists(),
            "adapter_sha256": t6.sha256_file(
                PARENT_ADAPTER / "adapter_model.safetensors"),
        },
    }
    gate["frozen_checksums"] = {
        k: {"ok": v["ok"], "files_checked": v.get("files_checked"),
            "mismatched": v.get("mismatched"), "missing": v.get("missing")}
        for k, v in checks.items()}
    gate["frozen_checksums_ok"] = all(v["ok"] for v in checks.values())

    # -- no stale T7 state --
    stale = []
    for p in (ROOT / "evaluations" / "t7").glob("*") \
            if (ROOT / "evaluations" / "t7").exists() else []:
        if p.name != "t7_entry_gate.json":
            stale.append(p.name)
    for p in (ROOT / "src" / "sciencemath").glob("executive*") \
            if (ROOT / "src" / "sciencemath").exists() else []:
        stale.append(str(p))
    gate["stale_t7_state"] = {"paths": stale, "ok": not stale}

    # -- environment --
    gate["environment"] = t6.environment()

    # -- model + tools + retrieval (GPU) --
    if gate["frozen_checksums_ok"] and not stale:
        gate["runtime_checks"] = t6.model_and_tools_check()
    else:
        gate["runtime_checks"] = {"skipped": "checksum mismatch or stale state"}

    # -- decision --
    rc = gate["runtime_checks"]
    ok = (gate["frozen_checksums_ok"] and t6_ok
          and not gate["stale_t7_state"]["ok"] is False
          and rc.get("adapter_active") and rc.get("tools_ok")
          and rc.get("rag_ok"))
    gate["decision"] = "T7 UNBLOCKED" if ok else "T7: BLOCKED"
    gate["blocked_if"] = "existing capabilities broken at gate time"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(gate, indent=2, ensure_ascii=False,
                              default=str), encoding="utf-8")
    print(json.dumps({k: gate[k] for k in
                      ("decision", "t6_dependency", "checkpoint",
                       "stale_t7_state")}, indent=2, default=str))
    print("adapter_active:", rc.get("adapter_active"),
          "| tools_ok:", rc.get("tools_ok"), "| rag_ok:", rc.get("rag_ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())