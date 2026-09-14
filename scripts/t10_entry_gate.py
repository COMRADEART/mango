"""T10.0 — Entry gate.

Verifies the T9-closed state before any T10 change:
pytest, T9 final audit, T3 adapter SHA, correction firewall SHA,
frozen suite checksums (T4 / T5R / capacity / extraction / correction-v1),
GPU idle, environment, and that MANGO_4B_SYSTEM_PROMOTION_CANDIDATE is
not the production default.

Writes evaluations/t10/t10_entry_gate.json. Any check FAIL -> exit 1.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EXPECTED = {
    "t3_adapter":
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
    "t4_suite":
        "807bb7d307c45f5160e4271388f1c2b82b5cb158610882dade3ca058ad336bef",
    "t5r_suite":
        "e74c8b1a5716ff61bdc978c9341a4592cfe902d19e5392df5204d2058e117347",
    "capacity_suite":
        "0bb6a3585ec628a54659775b30d57a852f8b7c3a2ed7f4b38c192732a2f573e1",
    "extraction_suite":
        "dd48d8e536fe23655403274e33edaa9fbe005afdb1ae0f0047445760ab16cdab",
    "correction_suite_v1":
        "dc77ccf845f539d4bf6df23964207d504962d75b56f02c981d0e15eb632a445b",
}
SUITE_PATHS = {
    "t3_adapter": "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors",
    "t4_suite": "evaluations/tool-suite/v1/questions.jsonl",
    "t5r_suite": "evaluations/rag-suite/v1/questions.jsonl",
    "capacity_suite": "evaluations/t8/capacity-suite/v1/questions.jsonl",
    "extraction_suite": "evaluations/t9/extraction-benchmark/v1/questions.jsonl",
    "correction_suite_v1": "evaluations/t9/correction-suite/v1/questions.jsonl",
}


def sha256_file(rel: str) -> str | None:
    p = REPO / rel
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, cwd=REPO).stdout.strip()
    manifest = json.loads((REPO / "evaluations/t9/final_regression_manifest.json")
                          .read_text(encoding="utf-8"))
    final_audit = json.loads((REPO / "evaluations/t9/final_audit.json")
                             .read_text(encoding="utf-8"))
    audit_all_pass = all(final_audit["checks"].values())

    fw_sha = sha256_file("src/sciencemath/executive/correction.py")
    fw_match = fw_sha == manifest["firewall_module_sha256_current"]

    suite_checks = {}
    for key, rel in SUITE_PATHS.items():
        actual = sha256_file(rel)
        suite_checks[key] = {
            "path": rel,
            "expected": EXPECTED[key],
            "actual": actual,
            "match": actual == EXPECTED[key],
        }

    # pytest fresh run is captured separately (evaluations/t10/pytest_entry.xml)
    import xml.etree.ElementTree as ET
    junit = REPO / "evaluations/t10/pytest_entry.xml"
    pytest_summary = None
    if junit.exists():
        root = ET.parse(junit).getroot()
        ts = next(root.iter("testsuite"))
        pytest_summary = {
            "tests": int(ts.get("tests")),
            "failures": int(ts.get("failures")),
            "errors": int(ts.get("errors")),
            "skipped": int(ts.get("skipped")),
            "duration_s": float(ts.get("time")),
        }

    # GPU idle check
    gpu_probe = subprocess.run(
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
         "--format=csv,noheader"], capture_output=True, text=True)
    gpu_line = gpu_probe.stdout.strip().splitlines()[-1] if gpu_probe.stdout else ""
    gpu_util = int(gpu_line.split(",")[0].strip().rstrip("%")) if gpu_line else None
    gpu_mem = 0
    if gpu_line:
        mem_str = gpu_line.split(",")[1].strip().split()[0]
        gpu_mem = int(mem_str) if mem_str.isdigit() else 0
    gpu_idle = gpu_util is not None and gpu_util <= 5 and gpu_mem <= 512

    # candidate is not production default: production model config stays
    # Qwen3-1.7B (Mango-v0.1); the 4B system is referenced only as a
    # promotion candidate, never as the configured production system.
    model_cfg = (REPO / "configs/model.yaml").read_text(encoding="utf-8")
    prod_is_17b = "model_id: Qwen/Qwen3-1.7B" in model_cfg
    gate = json.loads((REPO / "evaluations/t9/promotion_gate.json")
                      .read_text(encoding="utf-8"))
    candidate_is_not_prod = (
        prod_is_17b
        and gate["candidate_name"] == "MANGO_4B_SYSTEM_PROMOTION_CANDIDATE"
        and gate["weight_promotion_automatic"] is False
    )

    checks = {
        "pytest_green": bool(pytest_summary) and pytest_summary["failures"] == 0
                        and pytest_summary["errors"] == 0,
        "t9_final_audit_all_pass": audit_all_pass,
        "t3_adapter_sha": suite_checks["t3_adapter"]["match"],
        "firewall_module_sha_unchanged": fw_match,
        "t4_suite_checksum": suite_checks["t4_suite"]["match"],
        "t5r_suite_checksum": suite_checks["t5r_suite"]["match"],
        "capacity_suite_checksum": suite_checks["capacity_suite"]["match"],
        "extraction_suite_checksum": suite_checks["extraction_suite"]["match"],
        "correction_v1_suite_checksum": suite_checks["correction_suite_v1"]["match"],
        "gpu_idle": gpu_idle,
        "candidate_not_production_default": candidate_is_not_prod,
    }
    incident = {
        "found": "training/curriculum/mango-sft-v2/level1/checksums.json carried "
                 "CRLF-ized digests introduced by commit 5ce04b3 (recomputed in "
                 "a Windows clone with autocrlf); frozen corpus files themselves "
                 "were byte-identical to the 1934e9d blobs.",
        "resolution": "Digests restored to the canonical LF blob digests "
                      "(identical to the T9-freeze values that passed the T9 "
                      "745/0/0/0 run); .gitattributes eol=lf guard retained.",
        "resolved_before_gate": True,
    }

    gate = {
        "milestone": "T10",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "commit": commit,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "gpu_probe": gpu_line,
        },
        "pytest": pytest_summary,
        "t9_final_audit": {
            "path": "evaluations/t9/final_audit.json",
            "checks_total": len(final_audit["checks"]),
            "checks_pass": sum(final_audit["checks"].values()),
            "all_pass": audit_all_pass,
        },
        "t3_adapter": suite_checks["t3_adapter"],
        "firewall": {
            "module": "src/sciencemath/executive/correction.py",
            "sha256": fw_sha,
            "matches_t9_freeze": fw_match,
            "config_hash": manifest["firewall_config_hash"],
        },
        "suite_checksums": suite_checks,
        "candidate_not_production_default": {
            "production_model_config": "Qwen/Qwen3-1.7B (Mango-v0.1)",
            "candidate_name": gate["candidate_name"],
            "weight_promotion_automatic": gate["weight_promotion_automatic"],
            "verified": candidate_is_not_prod,
        },
        "incident_checksum_crlf": incident,
        "checks": checks,
    }
    out = REPO / "evaluations/t10/t10_entry_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": gate["status"], "checks": checks}, indent=1))
    return 0 if gate["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())