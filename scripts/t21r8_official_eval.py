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
  * runs a NON-RUNTIME preflight BEFORE the exposure ledger is created: the
    frozen-holdout, manifest-hash, qualification, evaluator-freeze, scoring-
    semantics, runtime-composite, corpus-domain, and suite-parse checks all
    pass (and no answer_knowledge/runtime row executes) before any exposure
    artifact exists, so a preflight failure can never consume the one-shot
    holdout;
  * only after preflight PASS writes the ledger with
    ``official_runtime_exposures = 1`` immediately before the first runtime
    row;
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r8_run_eval as evaluator  # noqa: E402
from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from t21r4_freeze_runtime import RUNTIME_GROUPS, sha_group  # noqa: E402


COMMAND = "python scripts/t21r8_official_eval.py"
# The evaluator source identity is a repo-level constant: qualification and
# the evaluator freeze always hash the committed evaluator file, never a
# fixture-local copy.
EVALUATOR_PATH = ROOT / "scripts" / "t21r8_run_eval.py"


@dataclass(frozen=True)
class Paths:
    """Filesystem layout for one candidate tree (repo root by default)."""

    root: Path

    @property
    def out_dir(self) -> Path:
        return self.root / "evaluations" / "t21r8"

    @property
    def suites_dir(self) -> Path:
        return self.out_dir / "suites"

    @property
    def corpus_dir(self) -> Path:
        return self.root / "rag" / "gk_holdout_t21r8"

    @property
    def manifest_path(self) -> Path:
        return self.out_dir / "holdout_manifest.json"

    @property
    def marker_path(self) -> Path:
        return self.out_dir / "HOLDOUT_FROZEN"

    @property
    def out_path(self) -> Path:
        return self.out_dir / "holdout_results.json"

    @property
    def raw_path(self) -> Path:
        return self.out_dir / "raw_results.jsonl"

    @property
    def ledger_path(self) -> Path:
        return self.out_dir / "evaluation_run_ledger.json"

    @property
    def contract_path(self) -> Path:
        return self.out_dir / "validation_contract.json"

    @property
    def semantics_path(self) -> Path:
        return self.out_dir / "scoring_semantics.json"

    @property
    def runtime_freeze_path(self) -> Path:
        return self.out_dir / "runtime_freeze.json"

    @property
    def evaluator_freeze_path(self) -> Path:
        return self.out_dir / "evaluator_freeze.json"

    @property
    def qualification_path(self) -> Path:
        return self.out_dir / "evaluator_qualification.json"


def build_paths(root: Path) -> Paths:
    return Paths(root=root)


PATHS = build_paths(ROOT)
EXPOSURE_ARTIFACTS = ("ledger_path", "raw_path", "out_path")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_rows(paths: Paths, suite: str) -> list[dict]:
    path = paths.suites_dir / suite / "holdout.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def _check_qualification(paths: Paths) -> dict:
    qualification = _load_json(paths.qualification_path)
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


def _check_freeze(paths: Paths) -> dict:
    if not paths.marker_path.exists() or not paths.manifest_path.exists():
        raise SystemExit(
            "HOLDOUT_FROZEN or holdout manifest is missing; the official "
            "one-shot exposure may not start without the frozen holdout")
    _check_qualification(paths)
    manifest = _load_json(paths.manifest_path)
    for info in manifest["freeze_inputs"].values():
        path = paths.root / info["path"]
        if not path.exists() or _sha256(path) != info["sha256"]:
            raise SystemExit(
                f"T21R8_FREEZE_VIOLATION: {info['path']} changed")
    for info in manifest["corpus"].values():
        path = paths.root / info["path"]
        if not path.exists() or _sha256(path) != info["sha256"]:
            raise SystemExit(
                f"T21R8_FREEZE_VIOLATION: {info['path']} changed")
    for suite, info in manifest["suites"].items():
        path = paths.suites_dir / suite / "holdout.jsonl"
        if not path.exists() or _sha256(path) != info["sha256"]:
            raise SystemExit(f"T21R8_FREEZE_VIOLATION: suite {suite} changed")

    evaluator_freeze = _load_json(paths.evaluator_freeze_path)
    if evaluator_freeze["evaluator_source_sha256"] != _sha256(
            EVALUATOR_PATH):
        raise SystemExit(
            "T21R8_FREEZE_VIOLATION: evaluator source hash differs from the "
            "evaluator freeze")
    contract = _load_json(paths.contract_path)
    evaluator.validate_semantics_artifacts(contract, evaluator_freeze)

    runtime_freeze = _load_json(paths.runtime_freeze_path)
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


def _preflight(paths: Paths) -> tuple[dict, object]:
    """Non-runtime preflight gate: everything is verified BEFORE the official
    exposure ledger exists.  No answer_knowledge/runtime row executes here;
    any failure refuses the launch and leaves the frozen holdout unconsumed
    (``official_runtime_exposures`` stays 0)."""
    for name in EXPOSURE_ARTIFACTS:
        if getattr(paths, name).exists():
            raise SystemExit(
                "T21R8_ONE_SHOT_CONSUMED: ledger or result artifact already "
                "exists; the official holdout exposure is never repeated")
    manifest = _check_freeze(paths)

    corpus = load_corpus(paths.corpus_dir)
    _validate_corpus_domains(corpus)

    expected_suites = set(evaluator.SUITES)
    if set(manifest["suites"]) != expected_suites:
        raise SystemExit(
            "T21R8_FREEZE_VIOLATION: holdout manifest suite set differs from "
            f"the expected suite set {sorted(expected_suites)}")
    for suite in evaluator.SUITES:
        try:
            rows = _load_rows(paths, suite)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SystemExit(
                f"T21R8_FREEZE_VIOLATION: suite {suite} does not parse: "
                f"{exc}") from exc
        if not rows:
            raise SystemExit(
                f"T21R8_FREEZE_VIOLATION: suite {suite} has no rows")
        for row in rows:
            if row.get("mode") not in ("retrieval", "answer"):
                raise SystemExit(
                    f"T21R8_FREEZE_VIOLATION: suite {suite} carries a row "
                    f"with unknown mode {row.get('mode')!r}")
    return manifest, corpus


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


def _write_ledger(paths: Paths, start: str, end: str, exit_code: int | None,
                  result_sha: str | None, error: str | None,
                  phase: str) -> None:
    marker = _load_json(paths.marker_path) if paths.marker_path.exists() \
        else {}
    document = {
        "milestone": "T21R8 official evaluation run ledger",
        "phase": phase,
        "holdout_freeze_timestamp": marker.get("frozen_at"),
        "holdout_manifest_sha256": _sha256(paths.manifest_path)
        if paths.manifest_path.exists() else None,
        "evaluator_freeze_hash": _sha256(paths.evaluator_freeze_path),
        "runtime_freeze_hash": _sha256(paths.runtime_freeze_path),
        "launcher_sha256": _sha256(Path(__file__)),
        "raw_results_sha256": _sha256(paths.raw_path)
        if paths.raw_path.exists() else None,
        "evaluation_start": start,
        "evaluation_end": end,
        "command": COMMAND,
        "exit_code": exit_code,
        "result_artifact_sha256": result_sha,
        "official_runtime_exposures": 1,
        "exposure_rule": (
            "The first production-runtime exposure of every T21R8 row is "
            "this official evaluation. A NON-RUNTIME preflight runs first "
            "and refuses without writing any artifact on failure; only "
            "after preflight PASS is the ledger created, immediately before "
            "the first runtime row. A crash after the first row begins "
            "consumes the one permitted exposure and forces "
            "T21R8_EVALUATOR_INVALID; the same holdout may NOT be rerun."
        ),
        "error": error,
    }
    paths.ledger_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")


def evaluate(paths: Paths, corpus) -> tuple[str, dict]:
    contract = _load_json(paths.contract_path)
    evaluator._r6.SUITES = list(evaluator.SUITES)

    zero_totals: dict[str, int] = {}
    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    all_answer_rows: list[dict] = []
    all_rows_all: list[tuple[str, list[dict], list[dict]]] = []

    with paths.raw_path.open("x", encoding="utf-8", newline="\n") \
            as raw_handle:
        for suite in evaluator.SUITES:
            rows = _load_rows(paths, suite)
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
        "holdout_manifest_sha256": _sha256(paths.manifest_path),
        "raw_results_sha256": _sha256(paths.raw_path),
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
    paths.out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    return _sha256(paths.out_path), document


def main(paths: Paths = PATHS) -> int:
    # Cheap early refusal; preflight enforces the same invariant again right
    # before the exposure begins.  The ledger's exposure count is >= 1 only
    # while the ledger file itself exists, so artifact absence subsumes it.
    for name in EXPOSURE_ARTIFACTS:
        if getattr(paths, name).exists():
            raise SystemExit(
                "T21R8_ONE_SHOT_CONSUMED: ledger or result artifact already "
                "exists; the official holdout exposure is never repeated")
    start = datetime.now(timezone.utc).isoformat()
    result_sha: str | None = None
    exit_code: int | None = None
    error: str | None = None
    # NON-RUNTIME preflight: any failure here exits BEFORE the ledger exists,
    # so official_runtime_exposures remains 0 and the frozen holdout is not
    # consumed.
    _manifest, corpus = _preflight(paths)
    # Preflight PASSED.  The one official exposure begins NOW: the ledger is
    # written immediately before the first runtime row.
    _write_ledger(paths, start, start, None, None, None, "preregistered")
    try:
        result_sha, result = evaluate(paths, corpus)
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
        if paths.out_path.exists() and result_sha is None:
            result_sha = _sha256(paths.out_path)
        _write_ledger(paths, start, end, exit_code, result_sha, error,
                      "completed")

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