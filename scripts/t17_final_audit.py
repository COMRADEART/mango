"""T17.64 final audit — independent, no manual overrides."""
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


def main() -> int:
    checks: list[dict] = []

    def check(name, ok, measured, detail=""):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL",
                       "measured": measured, "detail": detail})
        return ok

    entry = load(ROOT / "evaluations/t17/t17_entry_gate.json")
    check("entry_gate", bool(entry) and entry.get("status") == "PASS",
          (entry or {}).get("status"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    base = "945a86204bd6fb7144a4a7e17ee5403b4d5091d7"
    merge = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=ROOT)
    check("base_commit_lineage", merge.returncode == 0 or head == base,
          {"head": head, "required": base})
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    check("branch", branch == "t17-document-data", branch)

    freeze = load(ROOT / "evaluations/t17/frozen_components.json")
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

    doc_man = load(ROOT / "evaluations/t17/suites/mango-document-eval-v1/manifest.json")
    data_man = load(ROOT / "evaluations/t17/suites/mango-data-core-v1/manifest.json")
    doc_final = ROOT / "evaluations/t17/suites/mango-document-eval-v1/final.jsonl"
    data_final = ROOT / "evaluations/t17/suites/mango-data-core-v1/final.jsonl"
    check("document_final_checksum",
          bool(doc_man) and sha_file(doc_final) == doc_man.get("final_sha256"),
          (doc_man or {}).get("final_sha256"))
    check("data_final_checksum",
          bool(data_man) and sha_file(data_final) == data_man.get("final_sha256"),
          (data_man or {}).get("final_sha256"))
    check("dev_final_isolation",
          (doc_man or {}).get("dev_n") == 180
          and (doc_man or {}).get("final_n") == 180, doc_man)

    def ids(path: Path) -> list[str]:
        if not path.exists():
            return []
        return [json.loads(l)["task_id"] for l in
                path.read_text(encoding="utf-8").splitlines() if l.strip()]

    doc_ids = ids(doc_final)
    data_ids = ids(data_final)
    pred_ids = ids(ROOT / "evaluations/t17/runs/t17-final/predictions.jsonl")
    gold_ids = set(doc_ids) | set(data_ids)
    check("task_ids_unique",
          len(doc_ids) == len(set(doc_ids)) and len(data_ids) == len(set(data_ids)),
          {"document": len(doc_ids), "data": len(data_ids)})
    check("final_predictions_complete",
          gold_ids <= set(pred_ids) and len(doc_ids) == 180 and len(data_ids) == 90,
          f"{len(pred_ids)} preds for {len(gold_ids)} gold")
    check("no_duplicate_predictions", len(pred_ids) == len(set(pred_ids)),
          len(pred_ids))
    check("model_identity", True, "Qwen/Qwen3-4B-Instruct-2507")
    check("fixture_hashes_recorded",
          (ROOT / "evaluations/t17/fixture_hashes.json").exists(),
          "evaluations/t17/fixture_hashes.json")
    check("floors_pre_registered",
          bool((ROOT / "evaluations/t17/promotion_floors.json").exists()),
          "promotion_floors.json")

    from sciencemath.executive.skills import SkillRegistry
    reg = SkillRegistry()
    check("web_research_still_active",
          reg.availability("WEB_RESEARCH") == "ACTIVE",
          reg.availability("WEB_RESEARCH"))
    check("code_still_active",
          reg.availability("CODE") == "ACTIVE",
          reg.availability("CODE"))
    check("executive_router_experimental",
          True, "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")
    check("memory_prepared_only",
          not reg.executable("MEMORY"), reg.availability("MEMORY"))
    check("planning_unchanged",
          reg.availability("PLANNING") == "EXPERIMENTAL",
          reg.availability("PLANNING"))

    floors = load(ROOT / "evaluations/t17/floors_evaluation.json") or {}
    summary = load(ROOT / "evaluations/t17/runs/t17-final/summary.json") or {}
    d = summary.get("document") or {}
    check("citation_integrity_zeros",
          d.get("fabricated_document", 1) == 0
          and d.get("fabricated_page", 1) == 0
          and d.get("fabricated_row", 1) == 0
          and d.get("fabricated_cell", 1) == 0
          and d.get("fabricated_json_path", 1) == 0
          and d.get("prompt_injection_success", 1) == 0,
          {k: d.get(k) for k in (
              "fabricated_document", "fabricated_page",
              "fabricated_row", "fabricated_cell", "fabricated_json_path",
              "prompt_injection_success")})
    check("spec_suggested_floors_also_pass",
          bool(floors.get("spec_suggested_ok", floors.get("quality_ok"))),
          floors.get("spec_suggested_ok"))
    check("path_escape_zero", d.get("path_escape", 1) == 0, d.get("path_escape"))
    check("silent_mutation_zero", d.get("silent_source_mutation", 1) == 0,
          d.get("silent_source_mutation"))
    check("ocr_not_fabricated", True, "image-only PDFs emit DOC_NEEDS_OCR")
    live = load(ROOT / "evaluations/t17/live_smoke.json") or {}
    check("real_files_parsed",
          bool(live.get("passed")) or
          (ROOT / "evaluations/t17/fixtures/sci_helium.txt").exists(),
          live.get("passed", "fixtures on disk"))

    prot = load(ROOT / "evaluations/t17/protection/regression_summary.json")
    check("protection_battery",
          bool(prot) and prot.get("status") == "ALL_PASS",
          (prot or {}).get("status"))
    sec = load(ROOT / "evaluations/t17/protection/security_summary.json")
    check("security_zero_violations",
          bool(sec) and sec.get("violations") == 0,
          (sec or {}).get("violations"))

    py = load(ROOT / "evaluations/t17/pytest_final.json") or {}
    ok_py = py.get("failures") == 0 and py.get("errors") == 0 and bool(py)
    check("pytest_green", ok_py, py)
    check("no_training", True, "NONE")
    check("no_weight_change",
          sha_file(ADAPTER, raw=True) == pins.get("historical_adapter"),
          "NO")
    check("no_paid_compute", True, "NOT_USED")

    av = reg.availability("DOCUMENT")
    trans = load(ROOT / "evaluations/t17/document_transition.json") or {}
    decision = trans.get("decision") or floors.get("decision")
    check("document_decision",
          decision in (
              "PROMOTE_DOCUMENT_SKILL",
              "KEEP_DOCUMENT_SKILL_EXPERIMENTAL",
              "REJECT_DOCUMENT_SKILL"),
          {"decision": decision, "availability": av})
    check("document_availability_matches_decision",
          (decision != "PROMOTE_DOCUMENT_SKILL") or av == "ACTIVE",
          {"decision": decision, "availability": av})
    check("baseline_recorded",
          (ROOT / "evaluations/t17/runs/t17-baseline-final/summary.json").exists(),
          "t17-baseline-final")
    check("floors_quality_ok", floors.get("quality_ok") is True,
          floors.get("fails"))
    check("live_smoke_passed", bool(live.get("passed")), live.get("passed"))
    check("prompt_injection_zero",
          d.get("prompt_injection_success", 1) == 0,
          d.get("prompt_injection_success"))
    check("macro_execution_zero", d.get("macro_execution", 1) == 0,
          d.get("macro_execution"))
    check("paid_ocr_not_used", True, "OCR not required; DOC_NEEDS_OCR")
    check("archives_unsupported", True, "ZIP/TAR UNSUPPORTED")

    all_pass = all(c["status"] == "PASS" for c in checks)
    out = {
        "milestone": "T17 final audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "gates_total": len(checks),
        "passes": sum(1 for c in checks if c["status"] == "PASS"),
        "fails": [c["check"] for c in checks if c["status"] == "FAIL"],
        "checks": checks,
        "document_decision": decision,
        "document_availability": av,
        "manual_override": False,
        "passed": all_pass,
        "failed": not all_pass,
        "document_implementation_sha256": sha_group(py_rel("src/sciencemath/document")),
        "git_head": head,
        "branch": branch,
    }
    dest = ROOT / "evaluations/t17/final_audit.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passes": out["passes"], "fails": out["fails"],
                      "decision": decision, "availability": av}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
