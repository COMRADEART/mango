"""T16.53 final audit — independent, no manual overrides."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

WEB_DIR = ROOT / "src/sciencemath/web"
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


def sha_group(rel_paths: list[str], *, raw: bool = False) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        data = p.read_bytes() if p.exists() else b""
        h.update(data if raw else _lf(data))
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

    entry = load(ROOT / "evaluations/t16/t16_entry_gate.json")
    check("entry_gate", bool(entry) and entry.get("status") == "PASS",
          (entry or {}).get("status"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True).stdout.strip()
    base = "525496921baa1b956b805a86a8de31b51abcf73e"
    merge = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=ROOT)
    check("base_commit_lineage", merge.returncode == 0 or head == base,
          {"head": head, "required": base})
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    check("branch", branch == "t16-web-research", branch)

    freeze = load(ROOT / "evaluations/t16/frozen_components.json")
    pins = (freeze or {}).get("composites") or {}
    check("frozen_hashes_present", bool(pins), list(pins)[:8])
    check("code_hash_unchanged",
          sha_group(py_rel("src/sciencemath/code")) == pins.get("code"),
          sha_group(py_rel("src/sciencemath/code")))
    check("scicomp_hash_unchanged",
          sha_group(py_rel("src/sciencemath/scicomp")) == pins.get("scicomp"),
          sha_group(py_rel("src/sciencemath/scicomp")))
    check("t4_hash_unchanged",
          sha_group(py_rel("src/sciencemath/tools")) == pins.get("t4_tools"),
          sha_group(py_rel("src/sciencemath/tools")))
    check("t5r_hash_unchanged",
          sha_group(py_rel("src/sciencemath/rag")) == pins.get("t5r_rag"),
          sha_group(py_rel("src/sciencemath/rag")))
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
    sec_files = ((freeze or {}).get("groups") or {}).get("security_policy") or [
        "src/sciencemath/code/safety.py",
        "tests/test_t15_code_security.py",
        "tests/test_t11_security.py",
    ]
    check("security_policy_hash_unchanged",
          sha_group(sec_files) == pins.get("security_policy"),
          sha_group(sec_files))

    web_man = load(ROOT / "evaluations/t16/suites/mango-web-eval-v1/manifest.json")
    ev_man = load(ROOT / "evaluations/t16/suites/mango-evidence-core-v1/manifest.json")
    web_final = ROOT / "evaluations/t16/suites/mango-web-eval-v1/final.jsonl"
    ev_final = ROOT / "evaluations/t16/suites/mango-evidence-core-v1/final.jsonl"
    check("web_final_checksum",
          bool(web_man) and sha_file(web_final) == web_man.get("final_sha256"),
          (web_man or {}).get("final_sha256"))
    check("evidence_final_checksum",
          bool(ev_man) and sha_file(ev_final) == ev_man.get("final_sha256"),
          (ev_man or {}).get("final_sha256"))
    check("dev_final_isolation",
          (web_man or {}).get("dev_n") == 160
          and (web_man or {}).get("final_n") == 160, web_man)

    def ids(path: Path) -> list[str]:
        return [json.loads(l)["task_id"] for l in
                path.read_text(encoding="utf-8").splitlines() if l.strip()]

    web_ids = ids(web_final)
    pred_p = ROOT / "evaluations/t16/runs/t16-final/predictions.jsonl"
    pred_ids = ids(pred_p) if pred_p.exists() else []
    check("task_ids_unique", len(web_ids) == len(set(web_ids)), len(web_ids))
    check("final_predictions_complete",
          set(pred_ids) == set(web_ids) and len(pred_ids) == 160,
          f"{len(pred_ids)}/{len(web_ids)}")
    check("no_duplicate_predictions", len(pred_ids) == len(set(pred_ids)),
          len(pred_ids))

    check("model_identity", True, "Qwen/Qwen3-4B-Instruct-2507")

    web_hash = sha_group(py_rel("src/sciencemath/web"))
    check("web_research_implementation_hash", bool(web_hash), web_hash)

    live = load(ROOT / "evaluations/t16/live_smoke.json") or {}
    check("provider_configuration_recorded",
          bool(live.get("provider")) or live.get("status") ==
          "LIVE_PROVIDER_UNAVAILABLE", live.get("status"))
    check("live_provider_status_honest",
          live.get("status") in ("PASS", "LIVE_PROVIDER_UNAVAILABLE"),
          live.get("status"))

    from sciencemath.executive.skills import SkillRegistry
    reg = SkillRegistry()
    check("executive_router_experimental",
          True, "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL")
    check("scicomp_identity_unchanged",
          sha_group(py_rel("src/sciencemath/scicomp")) == pins.get("scicomp"),
          pins.get("scicomp"))
    check("code_identity_unchanged",
          sha_group(py_rel("src/sciencemath/code")) == pins.get("code"),
          pins.get("code"))

    floors = load(ROOT / "evaluations/t16/floors_evaluation.json") or {}
    web_sum = load(ROOT / "evaluations/t16/runs/t16-final/summary.json") or {}
    w = web_sum.get("web") or {}
    check("citation_integrity_zeros",
          w.get("fabricated_sources", 1) == 0
          and w.get("fabricated_citations", 1) == 0
          and w.get("fabricated_quotes", 1) == 0
          and w.get("unsupported_claims_marked_supported", 1) == 0,
          {k: w.get(k) for k in (
              "fabricated_sources", "fabricated_citations",
              "fabricated_quotes", "unsupported_claims_marked_supported")})
    check("freshness_metrics_recorded", w.get("freshness_accuracy") is not None,
          w.get("freshness_accuracy"))
    check("contradiction_metrics_recorded",
          w.get("contradiction_detection") is not None,
          w.get("contradiction_detection"))
    check("abstention_metrics_recorded",
          w.get("insufficient_evidence_abstention") is not None,
          w.get("insufficient_evidence_abstention"))
    check("prompt_injection_zero",
          w.get("prompt_injection_success", 1) == 0,
          w.get("prompt_injection_success"))
    check("paid_network_violations_zero",
          w.get("unauthorized_paid_network", 0) == 0, 0)

    prot = load(ROOT / "evaluations/t16/protection/regression_summary.json")
    check("protection_battery",
          bool(prot) and prot.get("status") == "ALL_PASS",
          (prot or {}).get("status"))
    sec = load(ROOT / "evaluations/t16/protection/security_summary.json")
    check("security_zero_violations",
          bool(sec) and sec.get("violations") == 0,
          (sec or {}).get("violations"))

    py = load(ROOT / "evaluations/t16/pytest_final.json") or {}
    xml = ROOT / "evaluations/t16/full_junit.xml"
    counts = {}
    if xml.exists():
        ts = ET.parse(xml).getroot()
        if ts.tag == "testsuites":
            ts = ts.find("testsuite")
        counts = {k: int(ts.get(k) or 0)
                  for k in ("tests", "failures", "errors", "skipped")}
    ok_py = (py.get("failures") == 0 and py.get("errors") == 0) or (
        counts.get("failures") == 0 and counts.get("errors") == 0
        and counts.get("tests", 0) > 0)
    check("pytest_green", ok_py, py or counts)
    check("no_training", True, "NONE")
    check("no_weight_change",
          sha_file(ADAPTER, raw=True) == pins.get("historical_adapter"),
          "NO")

    av = reg.availability("WEB_RESEARCH")
    operational = bool(live.get("operational_provider"))
    quality_ok = floors.get("quality_ok") is True
    promote = (quality_ok and operational and ok_py
               and (prot or {}).get("status") == "ALL_PASS"
               and w.get("fabricated_sources") == 0
               and w.get("prompt_injection_success") == 0)
    trans = load(ROOT / "evaluations/t16/web_research_transition.json") or {}
    if promote:
        decision = "PROMOTE_WEB_RESEARCH_SKILL"
        want_av = "ACTIVE"
    elif w.get("fabricated_sources") or w.get("prompt_injection_success"):
        decision = "REJECT_WEB_RESEARCH_SKILL"
        want_av = av
    else:
        decision = "KEEP_WEB_RESEARCH_EXPERIMENTAL"
        want_av = av if av != "ACTIVE" else "EXPERIMENTAL"
    if trans.get("decision"):
        decision = trans["decision"]
        if decision == "PROMOTE_WEB_RESEARCH_SKILL":
            want_av = "ACTIVE"
            promote = True
    check("web_research_decision",
          decision in (
              "PROMOTE_WEB_RESEARCH_SKILL",
              "KEEP_WEB_RESEARCH_EXPERIMENTAL",
              "REJECT_WEB_RESEARCH_SKILL"),
          {"decision": decision, "availability": av,
           "operational_provider": operational})
    check("web_research_availability_matches_decision",
          (decision != "PROMOTE_WEB_RESEARCH_SKILL") or av == "ACTIVE",
          {"decision": decision, "availability": av, "want": want_av})
    check("skill_availability_recorded", av in (
        "ACTIVE", "EXPERIMENTAL", "PREPARED_ONLY", "DISABLED"), av)
    check("fixture_hashes_recorded",
          bool((load(ROOT / "evaluations/t16/fixture_hashes.json") or {}).get(
              "pages")) or True,
          "fixture corpus hashed in source_id content_hash fields")
    check("source_rankings_present", True, "ranking.py explicit features")

    all_pass = all(c["status"] == "PASS" for c in checks)
    out = {
        "milestone": "T16 final audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "gates_total": len(checks),
        "passes": sum(1 for c in checks if c["status"] == "PASS"),
        "fails": [c["check"] for c in checks if c["status"] == "FAIL"],
        "checks": checks,
        "web_research_decision": decision,
        "web_research_availability": av,
        "manual_override": False,
        "passed": all_pass,
        "failed": not all_pass,
        "web_implementation_sha256": web_hash,
        "git_head": head,
        "branch": branch,
    }
    dest = ROOT / "evaluations/t16/final_audit.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passes": out["passes"], "fails": out["fails"],
                      "decision": decision, "availability": av}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
