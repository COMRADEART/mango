#!/usr/bin/env python3
"""T21R12 immutable closure + permanent official-eval refusal."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path.cwd()
OUT12 = ROOT / "evaluations" / "t21r12"
SCRIPTS = ROOT / "scripts"

PRE = "85312e530891a9f6fe9915894b0e6eb3a9b63bea"
FAILED = "6b449c05a14c2dc5de04ab96242f65caed9e6ca9"
FAILED_TREE = "219886fb167e5d1b41e7750d8a0ab7d119663834"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ledger = OUT12 / "construction_run_ledger.json"
    fail_cls = OUT12 / "construction_failure_classification.json"
    corpus = ROOT / "rag" / "gk_holdout_t21r12"
    specs = OUT12 / "_private_specs"

    # Refuse mutating preserved artifacts — only ADD closure
    for p in [ledger, fail_cls]:
        if not p.is_file():
            raise SystemExit(f"missing preserved artifact: {p}")

    corpus_hashes = {}
    for name in ("corpus_manifest.json", "sources.jsonl", "chunks.jsonl", "world.jsonl"):
        path = corpus / name
        if path.is_file():
            corpus_hashes[name] = sha(path)
    if (corpus / "corpus_manifest.json").is_file():
        manifest = json.loads((corpus / "corpus_manifest.json").read_text(encoding="utf-8"))
        corpus_hashes["manifest_checksum"] = manifest.get("manifest_checksum")
        corpus_hashes["source_count"] = manifest.get("source_count")
        corpus_hashes["chunk_count"] = manifest.get("chunk_count")

    spec_hashes = {}
    for path in sorted(specs.glob("*")):
        if path.is_file():
            spec_hashes[path.name] = sha(path)

    closure = {
        "artifact": "T21R12_CLOSURE",
        "version": "t21r12-closure-v1",
        "status": "CLOSED_NON_PROMOTIONAL_CONSTRUCTION_INFRASTRUCTURE_FAILURE",
        "project_state": "CLOSED / NON_PROMOTIONAL_CONSTRUCTION_INFRASTRUCTURE_FAILURE",
        "failure_class": "FROZEN_CONTRACT_SUITE_MATERIALIZER_SCHEMA_INCOMPATIBILITY",
        "stage": "suite_materialization",
        "construction_attempts": 1,
        "corpus_materializations": 1,
        "suite_materializations": 0,
        "automatic_retry": False,
        "repair_attempted": False,
        "regeneration_attempted": False,
        "seal_attempted": False,
        "official_evaluation_executed": False,
        "candidate_rows_executed": 0,
        "runtime_rows_executed": 0,
        "candidate_capability_result": "NONE",
        "bindings": {
            "preconstruction_commit": PRE,
            "failed_construction_commit": FAILED,
            "failed_construction_tree": FAILED_TREE,
            "branch": "origin/t21r12-construction-failed",
            "construction_run_ledger_sha256": sha(ledger),
            "construction_failure_classification_sha256": sha(fail_cls),
            "corpus_hashes": corpus_hashes,
            "private_spec_fingerprints": spec_hashes,
        },
        "official_evaluation_policy": {
            "status": "PERMANENTLY_REFUSED",
            "refusal_code": "T21R12_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED",
            "reason": "NO_VALID_SEALED_HOLDOUT",
            "candidate_rows_on_invocation": 0,
        },
        "immutable_preserved_paths": [
            "evaluations/t21r12/construction_run_ledger.json",
            "evaluations/t21r12/construction_failure_classification.json",
            "rag/gk_holdout_t21r12/",
            "evaluations/t21r12/_private_specs/",
        ],
    }
    path = OUT12 / "T21R12_CLOSURE.json"
    if path.exists():
        raise SystemExit("T21R12_CLOSURE.json already exists — refuse overwrite")
    path.write_text(json.dumps(closure, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print("wrote", path, sha(path))

    # Patch official eval refusal
    official = SCRIPTS / "t21r12_official_eval.py"
    text = official.read_text(encoding="utf-8")
    if "T21R12_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED" not in text:
        helper = '''
def _refuse_if_invalid_holdout_closed() -> None:
    """Permanent refusal: R12 never sealed a valid holdout."""
    import json
    from pathlib import Path
    closure_path = Path(__file__).resolve().parents[1] / "evaluations" / "t21r12" / "T21R12_CLOSURE.json"
    if not closure_path.is_file():
        raise SystemExit("T21R12_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED: NO_VALID_SEALED_HOLDOUT (closure missing)")
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    status = str(closure.get("status") or "")
    if "CLOSED" not in status:
        raise SystemExit("T21R12_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED: NO_VALID_SEALED_HOLDOUT")
    raise SystemExit("T21R12_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED: NO_VALID_SEALED_HOLDOUT")

'''
        # Insert after imports / before first def main or at module level before main
        if "def main" in text:
            text = text.replace("def main", helper + "def main", 1)
        # Call at start of main
        text = re.sub(
            r"(def main\([^)]*\)[^:]*:\n)",
            r"\1    _refuse_if_invalid_holdout_closed()\n",
            text,
            count=1,
        )
        # Also gate _preflight if present
        if "def _preflight" in text and "_refuse_if_invalid_holdout_closed()" not in text[text.find("def _preflight"):text.find("def _preflight")+400]:
            text = re.sub(
                r"(def _preflight\([^)]*\)[^:]*:\n)",
                r"\1    _refuse_if_invalid_holdout_closed()\n",
                text,
                count=1,
            )
        official.write_text(text, encoding="utf-8", newline="\n")
        print("patched", official)
    else:
        print("official eval already refused")

    # Verify refusal without creating eval ledger
    import subprocess, sys
    proc = subprocess.run([sys.executable, str(official)], cwd=str(ROOT), capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "T21R12_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED" not in out and proc.returncode == 0:
        # try with --help or bare; may need args — still should refuse in main
        print("refusal probe returncode", proc.returncode, "out", out[:500])
    else:
        print("refusal ok", proc.returncode)
    # ensure no evaluation ledger created
    for name in ("evaluation_run_ledger.json", "raw_results.jsonl", "holdout_results.json"):
        if (OUT12 / name).exists():
            raise SystemExit(f"refusal created exposure artifact: {name}")
    print("CLOSURE_OK", sha(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
