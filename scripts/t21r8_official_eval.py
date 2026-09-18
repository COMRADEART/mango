"""T21R8 one-shot launcher for the qualified evaluator core (NOT yet runnable:
the T21R8 holdout does not exist and must not be constructed in this phase).

This file contains orchestration and integrity checks only.  All row scoring,
metric aggregation, floor comparison, and raw schemas come from the qualified
evaluator in ``scripts/t21r8_run_eval.py``.  Preregistered official command:

    python scripts/t21r8_official_eval.py

The wrapper:
  * refuses if ``HOLDOUT_FROZEN`` / ``holdout_manifest.json`` are absent;
  * refuses if the runtime or evaluator hashes differ from their freezes;
  * refuses if the official exposure ledger already records >= 1 exposure;
  * creates/writes the ledger BEFORE the first runtime row;
  * increments the official exposure exactly once;
  * writes ``raw_results.jsonl`` incrementally (flush + fsync per row);
  * never silently restarts: any existing ledger/raw/result artifact refuses
    the launch, and a crash after the first row begins consumes the one
    permitted exposure, forcing T21R8_EVALUATOR_INVALID with no rerun.

DO NOT EXECUTE during the preregistration phase.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r8_run_eval as evaluator  # noqa: E402
from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from t21r4_freeze_runtime import RUNTIME_GROUPS, sha_group  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r8"
SUITES_DIR = OUT_DIR / "suites"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r8"
MANIFEST_PATH = OUT_DIR / "holdout_manifest.json"
MARKER_PATH = OUT_DIR / "HOLDOUT_FROZEN"
OUT_PATH = OUT_DIR / "holdout_results.json"
RAW_PATH = OUT_DIR / "raw_results.jsonl"
LEDGER_PATH = OUT_DIR / "evaluation_run_ledger.json"
CONTRACT_PATH = OUT_DIR / "validation_contract.json"
SEMANTICS_PATH = OUT_DIR / "scoring_semantics.json"
RUNTIME_FREEZE_PATH = OUT_DIR / "runtime_freeze.json"
EVALUATOR_FREEZE_PATH = OUT_DIR / "evaluator_freeze.json"
QUALIFICATION_PATH = OUT_DIR / "evaluator_qualification.json"
EVALUATOR_PATH = ROOT / "scripts" / "t21r8_run_eval.py"
COMMAND = "python scripts/t21r8_official_eval.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_rows(suite: str) -> list[dict]:
    path = SUITES_DIR / suite / "holdout.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def _check_qualification() -> dict:
    qualification = _load_json(QUALIFICATION_PATH)
    if not qualification.get("qualification_passed") or \
            not qualification.get("all_metric_paths_exercised") or \
            not qualification.get("all_cases_pass") or \
            qualification.get("uncaught_exceptions") != 0:
        raise SystemExit("T21R8_EVALUATOR_INVALID: qualification is not PASS")
    if qualification.get("evaluator_source_sha256") != _sha256(
            EVALUATOR_PATH):
        raise SystemExit(
            "T21R8_EVALUATOR_INVALID: qualification source hash differs")
    return qualification


def _check_freeze() -> dict:
    if not MARKER_PATH.exists() or not MANIFEST_PATH.exists():
        raise SystemExit(
            "HOLDOUT_FROZEN or holdout manifest is missing; the official "
            "one-shot exposure may not start without the frozen holdout")
    _check_qualification()
    manifest = _load_json(MANIFEST_PATH)
    for info in manifest["freeze_inputs"].values():
        path = ROOT / info["path"]
        if not path.exists() or _sha256(path) != info["sha256"]:
            raise SystemExit(
                f"T21R8_FREEZE_VIOLATION: {info['path']} changed")
    for info in manifest["corpus"].values():
        path = ROOT / info["path"]
        if not path.exists() or _sha256(path) != info["sha256"]:
            raise SystemExit(
                f"T21R8_FREEZE_VIOLATION: {info['path']} changed")
    for suite, info in manifest["suites"].items():
        path = SUITES_DIR / suite / "holdout.jsonl"
        if not path.exists() or _sha256(path) != info["sha256"]:
            raise SystemExit(f"T21R8_FREEZE_VIOLATION: suite {suite} changed")

    evaluator_freeze = _load_json(EVALUATOR_FREEZE_PATH)
    if evaluator_freeze["evaluator_source_sha256"] != _sha256(
            EVALUATOR_PATH):
        raise SystemExit(
            "T21R8_FREEZE_VIOLATION: evaluator source hash differs from the "
            "evaluator freeze")
    contract = _load_json(CONTRACT_PATH)
    evaluator.validate_semantics_artifacts(contract, evaluator_freeze)

    runtime_freeze = _load_json(RUNTIME_FREEZE_PATH)
    for name, spec in RUNTIME_GROUPS.items():
        if sha_group(spec) != runtime_freeze["runtime_composites"][name]:
            raise SystemExit(
                f"T21R8_FREEZE_VIOLATION: runtime group {name} changed")
    return manifest


def _validate_corpus_domains(corpus) -> None:
    unknown = sorted({
        evaluator.normalize_domain(tag)
        for source in corpus.sources for tag in (source.topic_tags or [])
    } - evaluator.DOMAIN_TAXONOMY)
    if unknown:
        raise SystemExit(
            f"T21R8_EVALUATOR_INVALID: unknown corpus domains {unknown}")


def _validate_raw_schema(raw: dict, mode: str) -> None:
    expected = set(evaluator.RAW_RETRIEVAL_FIELDS if mode == "retrieval"
                   else evaluator.RAW_ANSWER_FIELDS)
    actual = set(raw)
    if actual != expected:
        raise RuntimeError(
            "T21R8_EVALUATOR_INVALID: raw schema mismatch "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )


def _write_raw(handle, raw: dict) -> None:
    handle.write(json.dumps(raw, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _write_ledger(start: str, end: str, exit_code: int | None,
                  result_sha: str | None, error: str | None,
                  phase: str) -> None:
    marker = _load_json(MARKER_PATH) if MARKER_PATH.exists() else {}
    document = {
        "milestone": "T21R8 official evaluation run ledger",
        "phase": phase,
        "holdout_freeze_timestamp": marker.get("frozen_at"),
        "holdout_manifest_sha256": _sha256(MANIFEST_PATH)
        if MANIFEST_PATH.exists() else None,
        "evaluator_freeze_hash": _sha256(EVALUATOR_FREEZE_PATH),
        "runtime_freeze_hash": _sha256(RUNTIME_FREEZE_PATH),
        "launcher_sha256": _sha256(Path(__file__)),
        "raw_results_sha256": _sha256(RAW_PATH)
        if RAW_PATH.exists() else None,
        "evaluation_start": start,
        "evaluation_end": end,
        "command": COMMAND,
        "exit_code": exit_code,
        "result_artifact_sha256": result_sha,
        "official_runtime_exposures": 1,
        "exposure_rule": (
            "The first production-runtime exposure of every T21R8 row is "
            "this official evaluation. The ledger is created before the "
            "first row; a crash after the first row begins consumes the one "
            "permitted exposure and forces T21R8_EVALUATOR_INVALID; the "
            "same holdout may NOT be rerun."
        ),
        "error": error,
    }
    LEDGER_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")


def _ledger_records_exposure() -> bool:
    if not LEDGER_PATH.exists():
        return False
    ledger = _load_json(LEDGER_PATH)
    return int(ledger.get("official_runtime_exposures") or 0) >= 1


def evaluate() -> tuple[str, dict]:
    _check_freeze()
    corpus = load_corpus(CORPUS_DIR)
    _validate_corpus_domains(corpus)
    contract = _load_json(CONTRACT_PATH)
    evaluator._r6.SUITES = list(evaluator.SUITES)

    zero_totals: dict[str, int] = {}
    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    all_answer_rows: list[dict] = []
    all_rows_all: list[tuple[str, list[dict], list[dict]]] = []

    with RAW_PATH.open("x", encoding="utf-8", newline="\n") as raw_handle:
        for suite in evaluator.SUITES:
            rows = _load_rows(suite)
            results: list[dict] = []
            for row in rows:
                if row["mode"] == "retrieval":
                    raw = evaluator.run_retrieval_row(row, corpus)
                else:
                    raw, _ = evaluator.run_answer_row(row, corpus)
                    all_answer_results.append(raw)
                    all_answer_rows.append(row)
                raw["suite"] = suite
                _validate_raw_schema(raw, row["mode"])
                results.append(raw)
                _write_raw(raw_handle, raw)

            all_rows_all.append((suite, rows, results))
            for raw in results:
                for counter in raw.get("counters_nonzero", []):
                    zero_totals[counter] = zero_totals.get(counter, 0) + 1
            block: dict = {"n": len(rows)}
            if suite == evaluator.SUITES[0]:
                block["metrics"] = evaluator.retrieval_metrics(results)
            elif suite == evaluator.SUITES[4]:
                block["metrics"] = evaluator.citation_metrics(results, rows)
            elif suite == evaluator.SUITES[5]:
                block["metrics"] = evaluator.abstention_metrics(results)
            elif suite == evaluator.SUITES[6]:
                block["metrics"] = evaluator.temporal_metrics(rows, results)
            elif suite == evaluator.SUITES[7]:
                block["metrics"] = evaluator.security_metrics(results, rows)
                block["metrics"]["containment_rate"] = \
                    evaluator.answer_correctness(results)
            else:
                categories: dict[str, list[dict]] = {}
                for row, raw in zip(rows, results):
                    categories.setdefault(row["category"], []).append(raw)
                block["metrics"] = {
                    "grounded_accuracy": evaluator.answer_correctness(results),
                    "per_category": {
                        category: round(
                            sum(1 for raw in values if raw["correct"])
                            / len(values), 4)
                        for category, values in sorted(categories.items())
                    },
                }
            per_suite[suite] = block
            print(f"{suite}: {json.dumps(block['metrics'])[:220]}")

    metrics = evaluator.aggregate_metrics(
        per_suite, all_rows_all, all_answer_results, all_answer_rows,
        evaluator.SUITES)
    comparisons = evaluator.compare_floors(metrics, contract)
    floors_all_pass = all(item["pass"] for item in comparisons)
    zero_ok = all(value == 0 for value in zero_totals.values())
    suites_ok = evaluator.suite_minimums_met(per_suite, contract)
    document = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "one_shot": True,
        "official_runtime_exposures": 1,
        "holdout_manifest_sha256": _sha256(MANIFEST_PATH),
        "raw_results_sha256": _sha256(RAW_PATH),
        "raw_results_rows": sum(len(rows) for _, rows, _ in all_rows_all),
        "corpus_manifest_checksum": corpus.manifest.get("manifest_checksum"),
        "scoring_semantics": evaluator.SCORING_SEMANTICS,
        "scoring_semantics_sha256": evaluator.scoring_semantics_sha256(),
        "scoring_semantics_path": "evaluations/t21r8/scoring_semantics.json",
        "suites": per_suite,
        "metrics": metrics,
        "floors_comparison": comparisons,
        "floors_all_pass": floors_all_pass,
        "zero_tolerance_totals": zero_totals,
        "zero_tolerance_all_zero": zero_ok,
        "suite_minimums_met": suites_ok,
        "overall_pass": floors_all_pass and zero_ok and suites_ok,
    }
    OUT_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    return _sha256(OUT_PATH), document


def main() -> int:
    if any(path.exists() for path in (LEDGER_PATH, RAW_PATH, OUT_PATH)):
        raise SystemExit(
            "T21R8_ONE_SHOT_CONSUMED: ledger or result artifact already "
            "exists; the official holdout exposure is never repeated")
    if _ledger_records_exposure():
        raise SystemExit(
            "T21R8_ONE_SHOT_CONSUMED: the official exposure ledger already "
            "records an exposure")
    start = datetime.now(timezone.utc).isoformat()
    result_sha: str | None = None
    exit_code: int | None = None
    error: str | None = None
    # The ledger is written BEFORE the first runtime row is exposed.
    _write_ledger(start, start, None, None, None, "preregistered")
    try:
        result_sha, result = evaluate()
        exit_code = 0
    except SystemExit as exc:
        exit_code = 2
        error = str(exc)
        raise
    except Exception:
        exit_code = 1
        error = traceback.format_exc()
        raise
    finally:
        end = datetime.now(timezone.utc).isoformat()
        if OUT_PATH.exists() and result_sha is None:
            result_sha = _sha256(OUT_PATH)
        _write_ledger(start, end, exit_code, result_sha, error, "completed")

    print(json.dumps({
        "official_runtime_exposures": 1,
        "rows": result["raw_results_rows"],
        "floors_all_pass": result["floors_all_pass"],
        "zero_tolerance_all_zero": result["zero_tolerance_all_zero"],
        "suite_minimums_met": result["suite_minimums_met"],
        "overall_pass": result["overall_pass"],
    }, indent=2))
    if not result["floors_all_pass"]:
        for item in result["floors_comparison"]:
            if not item["pass"]:
                print("FAIL", item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())