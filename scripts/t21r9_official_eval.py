"""One-shot T21R9 official runner with a public data-only preflight API."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r9_freeze_holdout as seal_protocol  # noqa: E402
import t21r9_run_eval as evaluator  # noqa: E402


EXECUTION_PHRASE = "T21R9_ONE_SHOT_OFFICIAL_EVALUATION"


@dataclass(frozen=True)
class Paths:
    root: Path
    out: Path
    corpus: Path
    suites: Path
    manifest: Path
    marker: Path
    ledger: Path
    raw: Path
    results: Path


def build_paths(root: Path = ROOT) -> Paths:
    out = root / "evaluations" / "t21r9"
    return Paths(
        root=root, out=out, corpus=root / "rag" / "gk_holdout_t21r9",
        suites=out / "suites", manifest=out / "holdout_manifest.json",
        marker=out / "HOLDOUT_FROZEN",
        ledger=out / "evaluation_run_ledger.json",
        raw=out / "raw_results.jsonl", results=out / "holdout_results.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _row_count(path: Path) -> int:
    return sum(bool(line.strip()) for line in path.read_text(
        encoding="utf-8").splitlines())


def _preflight(paths: Paths) -> dict:
    defects: list[str] = []
    for path in (paths.ledger, paths.raw, paths.results):
        if path.exists():
            defects.append(f"one-shot exposure artifact exists: {path.name}")
    if not paths.manifest.is_file() or not paths.marker.is_file():
        return {"status": "FAIL", "defects": [
            "holdout_manifest.json or HOLDOUT_FROZEN is absent"],
            "runtime_execution_count": 0, "ledger_written": False}
    try:
        manifest = _json(paths.manifest)
        marker = _json(paths.marker)
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "FAIL", "defects": [f"invalid seal JSON: {exc}"],
                "runtime_execution_count": 0, "ledger_written": False}
    if manifest.get("schema_version") != seal_protocol.SCHEMA_VERSION or \
            marker.get("schema_version") != seal_protocol.SCHEMA_VERSION:
        defects.append("official-runner/schema mismatch")
    if marker.get("holdout_manifest_sha256") != _sha(paths.manifest):
        defects.append("HOLDOUT_FROZEN manifest binding mismatch")
    if marker.get("freeze_root_sha256") != manifest.get(
            "freeze_root_sha256"):
        defects.append("freeze-root mismatch")

    expected_inputs = {
        f"evaluations/t21r9/{name}" for name in
        (*seal_protocol.EVALUATION_INPUTS, *seal_protocol.AUDIT_FILES)
    } | {f"scripts/{name}" for name in seal_protocol.SCRIPT_INPUTS}
    actual_inputs = set(manifest.get("freeze_inputs") or {})
    if actual_inputs != expected_inputs:
        defects.append("freeze-input schema mismatch")
    for relative, identity in (manifest.get("freeze_inputs") or {}).items():
        path = paths.root / relative
        if not path.is_file() or _sha(path) != identity.get("sha256"):
            defects.append(f"freeze-input hash mismatch: {relative}")

    for name, artifact in seal_protocol.FROZEN_ARTIFACTS:
        path = paths.out / name
        if not path.is_file() or _json(path).get("artifact") != artifact:
            defects.append(f"{name} identity mismatch")
            continue
        try:
            seal_protocol.verify_component_freeze(paths.root, path, artifact)
        except (ValueError, OSError) as exc:
            defects.append(str(exc))
    qualification_path = paths.out / "preconstruction_qualification.json"
    if qualification_path.is_file():
        qualification = _json(qualification_path)
        if qualification.get("status") != "PASS" or qualification.get(
                "runtime_rows_executed") != 0:
            defects.append("qualification artifact is not a zero-runtime PASS")
    else:
        defects.append("qualification artifact missing")

    contract_path = paths.out / "holdout_construction_contract.json"
    contract = _json(contract_path) if contract_path.is_file() else {}
    expected_suites = contract.get("suite_target_exact") or {}
    manifest_suites = manifest.get("suites") or {}
    if set(manifest_suites) != set(expected_suites) or \
            set(manifest_suites) != set(evaluator.SUITES) or \
            set(manifest.get("expected_suite_ids") or []) != \
            set(evaluator.SUITES):
        defects.append("suite ID mismatch")
    for suite_id, expected_count in expected_suites.items():
        info = manifest_suites.get(suite_id) or {}
        path = paths.root / str(info.get("path") or "")
        if not path.is_file():
            defects.append(f"suite missing: {suite_id}")
            continue
        if _sha(path) != info.get("sha256"):
            defects.append(f"suite hash mismatch: {suite_id}")
        if _row_count(path) != expected_count or info.get("rows") != \
                expected_count:
            defects.append(f"suite count mismatch: {suite_id}")
    for name in seal_protocol.CORPUS_FILES:
        path = paths.corpus / name
        info = (manifest.get("corpus") or {}).get(name) or {}
        if not path.is_file() or _sha(path) != info.get("sha256"):
            defects.append(f"corpus hash mismatch: {name}")

    return {
        "artifact": "T21R9_OFFICIAL_PREFLIGHT",
        "status": "PASS" if not defects else "FAIL",
        "defects": list(dict.fromkeys(defects)),
        "holdout_manifest_sha256": _sha(paths.manifest),
        "runtime_execution_count": 0,
        "ledger_written": False,
    }


def preflight(root: Path = ROOT) -> dict:
    """Run exact future-runner validation without writing any artifact."""
    return _preflight(build_paths(root))


def _load_rows(paths: Paths) -> dict[str, list[dict]]:
    return {suite: [json.loads(line) for line in (
        paths.suites / suite / "holdout.jsonl").read_text(
            encoding="utf-8").splitlines() if line.strip()]
            for suite in evaluator.SUITES}


def _write_ledger(paths: Paths, phase: str, error: str | None = None) -> None:
    document = {
        "artifact": "T21R9_OFFICIAL_EXPOSURE_LEDGER",
        "phase": phase,
        "official_runtime_exposures": 1,
        "manifest_sha256": _sha(paths.manifest),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
    if phase == "started":
        # One-shot ownership: the started ledger must be created exclusively.
        # A concurrent invocation that reaches this point after preflight
        # loses here, before a single holdout row is executed.
        with open(paths.ledger, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
        return
    # Complete/failed updates happen only after exclusive ownership was
    # established by the started transition; a failed run never deletes it.
    paths.ledger.write_text(json.dumps(
        document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")


def execute(paths: Paths) -> int:
    report = _preflight(paths)
    if report["status"] != "PASS":
        raise SystemExit("T21R9 preflight failed: " + "; ".join(
            report["defects"]))
    try:
        _write_ledger(paths, "started")
    except FileExistsError:
        raise SystemExit(
            "T21R9 one-shot ledger already exists after preflight: another "
            "invocation holds the exposure; refusing to execute any holdout "
            "row") from None
    try:
        from sciencemath.knowledge.corpus import load_corpus
        corpus = load_corpus(paths.corpus)
        rows = _load_rows(paths)
        contract = _json(paths.out / "validation_contract.json")
        result = evaluator.evaluate(corpus, rows, paths.raw, contract)
        result["holdout_manifest_sha256"] = _sha(paths.manifest)
        result["raw_results_sha256"] = _sha(paths.raw)
        paths.results.write_text(json.dumps(
            result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
        _write_ledger(paths, "complete")
        return 0 if result["pass"] else 1
    except BaseException as exc:
        _write_ledger(paths, "failed", str(exc))
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--execute-official", action="store_true")
    parser.add_argument("--authorization")
    arguments = parser.parse_args()
    if arguments.execute_official:
        if arguments.authorization != EXECUTION_PHRASE:
            raise SystemExit("official T21R9 runtime exposure is not authorized")
        return execute(build_paths())
    report = preflight()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
