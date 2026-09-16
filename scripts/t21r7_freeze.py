"""Freeze the future T21R7 blind holdout after every preregistered gate.

This script is committed before holdout construction.  It refuses to create
``HOLDOUT_FROZEN`` unless the exact construction contract is fully satisfied
by the static audit, the physical suite counts agree with that audit, and the
remaining freeze prerequisites pass.  It must not be run during the current
preregistration-only phase.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from t21r7_construction_gate import (  # noqa: E402
    CONTRACT_PATH,
    assert_static_audit_passes,
    load_contract,
)
from t21r7_construction_audit import measure_candidate  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r7"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r7"
MARKER = OUT_DIR / "HOLDOUT_FROZEN"
MANIFEST = OUT_DIR / "holdout_manifest.json"

REQUIRED_REPORTS = {
    "runtime_freeze": OUT_DIR / "runtime_freeze.json",
    "evaluator_freeze": OUT_DIR / "evaluator_freeze.json",
    "validation_contract": OUT_DIR / "validation_contract.json",
    "construction_contract": CONTRACT_PATH,
    "static_gold_audit": OUT_DIR / "static_gold_audit.json",
    "holdout_uniqueness": OUT_DIR / "holdout_uniqueness.json",
    "blindness_audit": OUT_DIR / "blindness_audit.json",
}
CORPUS_FILES = (
    "world.jsonl", "sources.jsonl", "chunks.jsonl", "corpus_manifest.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def _require_prerequisites() -> None:
    if MARKER.exists() or MANIFEST.exists():
        raise SystemExit("T21R7 holdout already frozen or freeze was started")
    missing = [f"{label}: {path}" for label, path in REQUIRED_REPORTS.items()
               if not path.exists()]
    missing += [f"corpus: {name}" for name in CORPUS_FILES
                if not (CORPUS_DIR / name).exists()]
    if missing:
        raise SystemExit("freeze prerequisites missing: " + "; ".join(missing))


def main() -> int:
    _require_prerequisites()

    # Mandatory construction gate: validates contract SHA, recomputes every
    # check, rejects missing checks, and requires every result to be PASS.
    try:
        construction = assert_static_audit_passes()
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(
            f"construction contract audit is not a complete PASS: {exc}"
        ) from exc

    # Do not trust copied counters: derive the construction metrics again
    # from the exact candidate corpus and suite files being frozen.
    measured = measure_candidate()
    if measured["metrics"] != construction["metrics"]:
        raise SystemExit(
            "candidate construction metrics differ from the static audit"
        )

    uniqueness = _load_json(REQUIRED_REPORTS["holdout_uniqueness"])
    if uniqueness.get("verdict") != "UNIQUE":
        raise SystemExit("holdout uniqueness audit is not UNIQUE")
    blindness = _load_json(REQUIRED_REPORTS["blindness_audit"])
    if blindness.get("status") != "PASS":
        raise SystemExit("blindness audit is not PASS")

    contract = load_contract()
    suite_blocks: dict[str, dict] = {}
    physical_total = 0
    for short_name, rule in contract["suite_target_minimums"].items():
        suite_id = rule["suite_id"]
        path = OUT_DIR / "suites" / suite_id / "holdout.jsonl"
        if not path.exists():
            raise SystemExit(f"suite missing: {suite_id}")
        rows = _load_jsonl(path)
        count = len(rows)
        audited = int(construction["metrics"]["suite_rows"][short_name])
        if count != audited:
            raise SystemExit(
                f"suite count differs from construction audit: {suite_id} "
                f"physical={count} audited={audited}"
            )
        physical_total += count
        suite_blocks[suite_id] = {
            "rows": count,
            "sha256": _sha256(path),
        }
    if physical_total != int(construction["metrics"]["total_rows"]):
        raise SystemExit("physical total differs from construction audit")

    frozen_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "milestone": "T21R7 blind holdout freeze",
        "frozen_at": frozen_at,
        "holdout_total": physical_total,
        "construction_requirements_evaluated": construction[
            "requirements_evaluated"],
        "construction_requirements_passed": construction[
            "requirements_passed"],
        "freeze_inputs": {
            label: {"path": path.relative_to(ROOT).as_posix(),
                    "sha256": _sha256(path)}
            for label, path in REQUIRED_REPORTS.items()
        },
        "corpus": {
            name: {"path": (CORPUS_DIR / name).relative_to(ROOT).as_posix(),
                   "sha256": _sha256(CORPUS_DIR / name)}
            for name in CORPUS_FILES
        },
        "suites": suite_blocks,
        "one_shot_rule": (
            "Exactly one official evaluation after HOLDOUT_FROZEN; no "
            "preview, smoke test, sample execution, repair, or rerun."
        ),
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    MANIFEST.write_text(manifest_text, encoding="utf-8", newline="\n")
    manifest_sha = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    MARKER.write_text(json.dumps({
        "HOLDOUT_FROZEN": True,
        "frozen_at": frozen_at,
        "holdout_manifest_sha256": manifest_sha,
        "holdout_total": physical_total,
        "construction_contract_sha256": construction[
            "construction_contract_sha256"],
        "rule": manifest["one_shot_rule"],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"HOLDOUT_FROZEN total={physical_total} sha256={manifest_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
