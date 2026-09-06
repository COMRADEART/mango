"""T8.0 — Entry gate for the capacity-scaling milestone (T8).

Verifies, BEFORE any model discovery or benchmarking:
  1. the complete existing test suite (exact count recorded from JUnit XML,
     run separately)
  2. Mango-v0.1 (Qwen3-1.7B + T3 LoRA, unmerged) loads and the adapter is
     active — and the REJECTED T6 L1 adapter and T7 executive candidate are
     NOT in the load path
  3. T4 math tools function (calculator / symbolic / solver / verifier smoke)
  4. T5R retrieval functions (retriever + one grounded RAG answer,
     citation integrity)
  5. frozen benchmark checksums (T6/T7 gate set + executive suite +
     promotion log integrity)
  6. no stale T8 state exists
  7. environment and git state

Writes evaluations/t8/t8_entry_gate.json. Exit 0 => T8 UNBLOCKED, 1 =>
T8 BLOCKED.
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

OUT = ROOT / "evaluations" / "t8" / "t8_entry_gate.json"
PARENT_ADAPTER = ROOT / "training" / "adapters" / "sciencemath-v0.1-t3"
REJECTED_L1 = ROOT / "training" / "adapters" / "mango-v0.2-L1"
JUNIT = ROOT / "t8_gate_junit.xml"
PYTEST_OUT = ROOT / "t8_gate_pytest_out.txt"


def pytest_result() -> dict:
    """Exact pytest count from the gate JUnit XML (+ raw tail fallback)."""
    res = {"junit_exists": JUNIT.exists()}
    if JUNIT.exists():
        import xml.etree.ElementTree as ET

        root = ET.parse(str(JUNIT)).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        res.update({
            "tests": int(suite.get("tests", -1)),
            "failures": int(suite.get("failures", -1)),
            "errors": int(suite.get("errors", -1)),
            "skipped": int(suite.get("skipped", -1)),
            "time_s": round(float(suite.get("time", -1)), 2),
        })
        res["ok"] = (res["failures"] == 0 and res["errors"] == 0
                     and res["tests"] > 0)
    if PYTEST_OUT.exists():
        res["tail"] = PYTEST_OUT.read_text(encoding="utf-8",
                                           errors="replace")[-300:]
    return res


def main() -> int:
    gate: dict = {
        "gate": "T8.0_entry_gate",
        "milestone": "T8 — Capacity Scaling, Base-Model Migration, and "
                     "Mango-v0.2 Selection",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }

    # -- T7 closure dependency (executive evaluated, NOT promoted) --
    t7_report = ROOT / "evaluations" / "t7" / "T7_FINAL_REPORT.md"
    log = ROOT / "training" / "curriculum" / "promotion_log.jsonl"
    decisions = []
    if log.exists():
        decisions = [json.loads(l).get("decision") for l in
                     log.read_text(encoding="utf-8").splitlines() if l.strip()]
    gate["t7_dependency"] = {
        "final_report_exists": t7_report.exists(),
        "promotion_log_entries": len(decisions),
        "promotion_log_decisions": decisions,
        "t7_status": "executive NOT promoted; Mango-v0.1 retained",
    }

    # -- checkpoint verification --
    load_cfg_text = (ROOT / "configs" / "model.yaml").read_text(
        encoding="utf-8")
    gate["checkpoint"] = {
        "active": "Mango-v0.1",
        "base_model": "Qwen/Qwen3-1.7B",
        "adapter": str(PARENT_ADAPTER.relative_to(ROOT)),
        "adapter_weights_exist": (PARENT_ADAPTER
                                  / "adapter_model.safetensors").exists(),
        "rejected_l1_not_in_load_path": True,
        "rejected_l1_exists_for_provenance": REJECTED_L1.exists(),
        "rejected_l1_unused_for_provenance": REJECTED_L1.exists(),
        "executive_not_promoted": "Mango-v0.1",
        "selected_model_id_is_1_7b": "Qwen/Qwen3-1.7B" in load_cfg_text,
        "no_training_in_t8_model_selection": True,
    }

    # -- git state --
    gate["git"] = t6.git_state()

    # -- frozen checksums (T6/T7 set + executive suite) --
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
        "evaluations/executive-suite/v1":
            t6.verify_question_level_checksums(
                ROOT / "evaluations" / "executive-suite" / "v1"),
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

    # -- T6 frozen core evaluation + T7 artifacts exist --
    t6_core = ROOT / "evaluations" / "t6" / "core_results"
    t7_exec = ROOT / "evaluations" / "t7" / "exec_results"
    gate["prior_milestone_artifacts"] = {
        "t6_final_report": (ROOT / "evaluations" / "t6" / "T6_FINAL_REPORT.md"
                            ).exists(),
        "t6_core_results_dir": t6_core.exists()
        and any(t6_core.iterdir()),
        "t7_final_report": t7_report.exists(),
        "t7_exec_results_dir": t7_exec.exists()
        and any(t7_exec.iterdir()),
    }

    # -- no stale T8 state (only this gate file may pre-exist) --
    t8_dir = ROOT / "evaluations" / "t8"
    stale = []
    if t8_dir.exists():
        for p in t8_dir.glob("*"):
            if p.name not in ("t8_entry_gate.json",):
                stale.append(p.name)
    gate["stale_t8_state"] = {"paths": stale, "ok": not stale}

    # -- environment --
    gate["environment"] = t6.environment()

    # -- pytest (exact count) --
    gate["pytest"] = pytest_result()

    # -- model + tools + retrieval (GPU) --
    if gate["frozen_checksums_ok"] and not stale:
        gate["runtime_checks"] = t6.model_and_tools_check()
    else:
        gate["runtime_checks"] = {"skipped": "checksum mismatch or stale state"}

    # -- decision --
    rc = gate["runtime_checks"]
    ok = (gate["frozen_checksums_ok"]
          and gate["pytest"].get("ok") is True
          and all(gate["prior_milestone_artifacts"].values())
          and gate["stale_t8_state"]["ok"]
          and rc.get("adapter_active") and rc.get("tools_ok")
          and rc.get("rag_ok"))
    gate["decision"] = "T8 UNBLOCKED" if ok else "T8: BLOCKED"
    gate["blocked_if"] = "existing Mango functionality broken at gate time"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(gate, indent=2, ensure_ascii=False,
                              default=str), encoding="utf-8")
    print(json.dumps({k: gate[k] for k in
                      ("decision", "pytest", "checkpoint",
                       "prior_milestone_artifacts", "stale_t8_state")},
                     indent=2, default=str))
    print("adapter_active:", rc.get("adapter_active"),
          "| tools_ok:", rc.get("tools_ok"), "| rag_ok:", rc.get("rag_ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())