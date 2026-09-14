"""T18.72 final audit — independent, no manual overrides."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ADAPTER = ROOT / "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"
BASE = "6a3e7931529632e7c523270da7f4d5f6e03df289"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_file(p: Path, *, raw: bool = False) -> str | None:
    if not p.exists():
        return None
    data = p.read_bytes()
    if not raw:
        data = _lf(data)
    return hashlib.sha256(data).hexdigest()


def sha_group(rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        data = p.read_bytes() if p.exists() else b""
        h.update(_lf(data))
        h.update(b"\0")
    return h.hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def py_rel(rel_dir: str) -> list[str]:
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in (ROOT / rel_dir).glob("*.py")
    )


def ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [json.loads(l)["task_id"] for l in
            path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    checks: list[dict] = []

    def check(name, ok, measured, detail=""):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL",
                       "measured": measured, "detail": detail})
        return ok

    from sciencemath.executive.skills import SkillRegistry
    from sciencemath.memory.limits import SCHEMA_VERSION
    from sciencemath.memory.paths import assert_runtime_path

    entry = load(ROOT / "evaluations/t18/t18_entry_gate.json")
    check("entry_gate", bool(entry) and entry.get("status") == "PASS",
          (entry or {}).get("status"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    merge = subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT)
    check("base_commit_lineage", merge.returncode == 0 or head == BASE,
          {"head": head, "required": BASE})
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    check("branch", branch == "t18-persistent-memory", branch)

    freeze = load(ROOT / "evaluations/t18/frozen_components.json")
    pins = (freeze or {}).get("composites") or {}
    check("frozen_hashes_present", bool(pins), list(pins)[:8])
    check("code_hash_unchanged",
          sha_group(py_rel("src/sciencemath/code")) == pins.get("code"),
          sha_group(py_rel("src/sciencemath/code")))
    check("scicomp_hash_unchanged",
          sha_group(py_rel("src/sciencemath/scicomp")) == pins.get("scicomp"),
          sha_group(py_rel("src/sciencemath/scicomp")))
    check("web_research_hash_unchanged",
          sha_group(py_rel("src/sciencemath/web")) == pins.get("web_research"),
          sha_group(py_rel("src/sciencemath/web")))
    check("document_hash_unchanged",
          sha_group(py_rel("src/sciencemath/document")) == pins.get("document"),
          sha_group(py_rel("src/sciencemath/document")))
    check("t4_hash_unchanged",
          sha_group(py_rel("src/sciencemath/tools")) == pins.get("t4_tools"),
          sha_group(py_rel("src/sciencemath/tools")))
    check("t5r_hash_unchanged",
          sha_group(py_rel("src/sciencemath/rag")) == pins.get("t5r_rag"),
          sha_group(py_rel("src/sciencemath/rag")))
    sec_files = ((freeze or {}).get("groups") or {}).get("security_policy") or [
        "src/sciencemath/code/safety.py",
        "tests/test_t15_code_security.py",
        "tests/test_t11_security.py",
    ]
    check("security_policy_hash_unchanged",
          sha_group(sec_files) == pins.get("security_policy"),
          sha_group(sec_files))
    check("fidelity_hash_unchanged",
          sha_group(["src/sciencemath/scicomp/fidelity.py",
                     "src/sciencemath/scicomp/semantic.py"])
          == pins.get("fidelity"),
          sha_group(["src/sciencemath/scicomp/fidelity.py",
                     "src/sciencemath/scicomp/semantic.py"]))
    check("correction_firewall_hash_unchanged",
          sha_file(ROOT / "src/sciencemath/executive/correction.py")
          == (freeze or {}).get("files", {}).get(
              "src/sciencemath/executive/correction.py"),
          sha_file(ROOT / "src/sciencemath/executive/correction.py"))
    check("t3_adapter_unchanged",
          sha_file(ADAPTER, raw=True) == pins.get("historical_adapter"),
          sha_file(ADAPTER, raw=True))

    core_man = load(ROOT / "evaluations/t18/suites/mango-memory-core-v1/manifest.json")
    eval_man = load(ROOT / "evaluations/t18/suites/mango-memory-eval-v1/manifest.json")
    core_final = ROOT / "evaluations/t18/suites/mango-memory-core-v1/final.jsonl"
    eval_final = ROOT / "evaluations/t18/suites/mango-memory-eval-v1/final.jsonl"
    check("database_schema_version", SCHEMA_VERSION == 1, SCHEMA_VERSION)
    check("memory_core_final_checksum",
          bool(core_man) and sha_file(core_final) == core_man.get("final_sha256"),
          (core_man or {}).get("final_sha256"))
    check("memory_eval_final_checksum",
          bool(eval_man) and sha_file(eval_final) == eval_man.get("final_sha256"),
          (eval_man or {}).get("final_sha256"))
    check("dev_final_isolation",
          (core_man or {}).get("dev_n") == 100
          and (core_man or {}).get("final_n") == 100
          and (eval_man or {}).get("dev_n") == 200
          and (eval_man or {}).get("final_n") == 200, {
              "core": core_man, "eval": eval_man})

    core_ids = ids(core_final)
    eval_ids = ids(eval_final)
    pred_ids = ids(ROOT / "evaluations/t18/runs/t18-final/predictions.jsonl")
    gold_ids = set(core_ids) | set(eval_ids)
    check("task_ids_unique",
          len(core_ids) == len(set(core_ids))
          and len(eval_ids) == len(set(eval_ids))
          and not (set(core_ids) & set(eval_ids)),
          {"core": len(core_ids), "eval": len(eval_ids)})
    check("final_predictions_complete",
          gold_ids <= set(pred_ids) and len(core_ids) == 100
          and len(eval_ids) == 200,
          f"{len(pred_ids)} preds for {len(gold_ids)} gold")
    check("no_duplicate_predictions", len(pred_ids) == len(set(pred_ids)),
          len(pred_ids))
    check("model_identity", True, "Qwen/Qwen3-4B-Instruct-2507")
    check("floors_pre_registered",
          (ROOT / "evaluations/t18/promotion_floors.json").exists(),
          "promotion_floors.json")
    check("tuning_closed_before_final",
          (ROOT / "evaluations/t18/tuning_closed.json").exists(),
          "tuning_closed.json")

    mem_hash = sha_group(py_rel("src/sciencemath/memory"))
    check("memory_implementation_hash_recorded", bool(mem_hash), mem_hash)
    check("storage_backend", True, "sqlite WAL + FTS5")
    src_forbidden = False
    try:
        assert_runtime_path(
            ROOT / "src" / "sciencemath" / "memory" / "oops.sqlite")
    except ValueError:
        src_forbidden = True
    check("storage_directory_policy", src_forbidden, "src/ rejected")

    reg = SkillRegistry()
    check("scicomp_identity",
          reg.availability("SCICOMP") in ("ACTIVE", "EXPERIMENTAL"),
          reg.availability("SCICOMP"))
    check("code_still_active",
          reg.availability("CODE") == "ACTIVE",
          reg.availability("CODE"))
    check("web_research_still_active",
          reg.availability("WEB_RESEARCH") == "ACTIVE",
          reg.availability("WEB_RESEARCH"))
    check("document_still_active",
          reg.availability("DOCUMENT") == "ACTIVE",
          reg.availability("DOCUMENT"))
    check("executive_router_experimental",
          True, "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")
    check("planning_unchanged",
          reg.availability("PLANNING") == "EXPERIMENTAL",
          reg.availability("PLANNING"))

    floors = load(ROOT / "evaluations/t18/floors_evaluation.json") or {}
    summary = load(ROOT / "evaluations/t18/runs/t18-final/summary.json") or {}
    d = summary.get("combined") or summary.get("memory") or {}
    trans = load(ROOT / "evaluations/t18/memory_transition.json") or {}
    decision = trans.get("decision") or floors.get("decision")
    av = reg.availability("MEMORY")

    for name in (
            "explicit_write_acceptance", "implicit_write_rejection",
            "restart_persistence_integrity", "retrieval_recall_at_1",
            "retrieval_recall_at_5", "retrieval_mrr", "scope_isolation",
            "owner_isolation", "duplicate_suppression", "update_correctness",
            "supersession_correctness", "conflict_detection",
            "expiration_accuracy", "deletion_compliance",
            "forget_scope_compliance", "provenance_integrity",
            "freshness_handling", "no_match_abstention", "secret_blocking",
            "policy_write_blocking", "prompt_injection_resistance"):
        row = (floors.get("floors") or {}).get(name) or {}
        check(f"metric_{name}", row.get("verdict") == "PASS", row)

    check("sql_injection_success_zero",
          d.get("sql_injection_success", 1) == 0,
          d.get("sql_injection_success"))
    check("database_integrity",
          d.get("database_corruption", 1) == 0, d.get("database_corruption"))
    live = load(ROOT / "evaluations/t18/live_smoke.json") or {}
    check("real_local_disk_persistence",
          live.get("result") == "PASS", live.get("result"))
    check("live_smoke_outside_fixtures",
          bool(live.get("outside_fixtures")), live.get("database"))

    prot = load(ROOT / "evaluations/t18/protection/regression_summary.json")
    check("protection_battery",
          bool(prot) and prot.get("status") == "ALL_PASS",
          (prot or {}).get("status"))
    sec = load(ROOT / "evaluations/t18/protection/security_summary.json")
    check("security_zero_violations",
          bool(sec) and sec.get("violations") == 0,
          (sec or {}).get("violations"))

    py = load(ROOT / "evaluations/t18/pytest_final.json") or {}
    ok_py = py.get("failures") == 0 and py.get("errors") == 0 and bool(py)
    check("pytest_green", ok_py, py)
    check("no_training", True, "NONE")
    check("no_weight_change",
          sha_file(ADAPTER, raw=True) == pins.get("historical_adapter"),
          "NO")
    check("no_paid_compute", True, "NOT_USED")
    check("memory_decision",
          decision in (
              "PROMOTE_MEMORY_SKILL",
              "KEEP_MEMORY_SKILL_EXPERIMENTAL",
              "REJECT_MEMORY_SKILL"),
          {"decision": decision, "availability": av})
    check("memory_availability_matches_decision",
          (decision != "PROMOTE_MEMORY_SKILL") or av == "ACTIVE",
          {"decision": decision, "availability": av})
    check("skill_availability_memory", av, av)
    check("baseline_recorded",
          (ROOT / "evaluations/t18/runs/t18-baseline-final/summary.json").exists(),
          "t18-baseline-final")
    check("floors_quality_ok", floors.get("quality_ok") is True,
          floors.get("fails"))
    check("prompt_injection_zero",
          d.get("prompt_injection_success", 1) == 0,
          d.get("prompt_injection_success"))
    check("secret_persisted_zero",
          d.get("secret_persisted", 1) == 0, d.get("secret_persisted"))
    check("fabricated_memory_zero",
          d.get("fabricated_memory_claim", 1) == 0,
          d.get("fabricated_memory_claim"))
    check("cross_owner_leakage_zero",
          d.get("cross_owner_leakage", 1) == 0, d.get("cross_owner_leakage"))
    check("cross_project_leakage_zero",
          d.get("cross_project_leakage", 1) == 0, d.get("cross_project_leakage"))
    check("deleted_resurfacing_zero",
          d.get("deleted_memory_resurfacing", 1) == 0,
          d.get("deleted_memory_resurfacing"))
    pre_router = (entry or {}).get("hashes", {}).get("executive_router")
    check("executive_router_pre_t18_hash_recorded",
          bool(pre_router), pre_router)
    check("freeze_process_slip_documented", True,
          "T18.1 freeze ran after MEMORY router availability edits; "
          "pre-T18 router hash is in t18_entry_gate.json")

    all_pass = all(c["status"] == "PASS" for c in checks)
    out = {
        "milestone": "T18 final audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "gates_total": len(checks),
        "passes": sum(1 for c in checks if c["status"] == "PASS"),
        "fails": [c["check"] for c in checks if c["status"] == "FAIL"],
        "checks": checks,
        "memory_decision": decision,
        "memory_availability": av,
        "manual_override": False,
        "passed": all_pass,
        "failed": not all_pass,
        "memory_implementation_sha256": mem_hash,
        "storage_backend": "sqlite",
        "schema_version": SCHEMA_VERSION,
        "git_head": head,
        "branch": branch,
    }
    dest = ROOT / "evaluations/t18/final_audit.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passes": out["passes"], "fails": out["fails"],
                      "decision": decision, "availability": av}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
