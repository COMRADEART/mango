"""One-shot T21R13 official runner with a public data-only preflight API."""
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

import t21r13_freeze_holdout as seal_protocol  # noqa: E402
import t21r13_run_eval as evaluator  # noqa: E402


EXECUTION_PHRASE = "T21R13_ONE_SHOT_OFFICIAL_EVALUATION"


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
    out = root / "evaluations" / "t21r13"
    return Paths(
        root=root, out=out, corpus=root / "rag" / "gk_holdout_t21r13",
        suites=out / "suites", manifest=out / "holdout_manifest.json",
        marker=out / "HOLDOUT_FROZEN",
        ledger=out / "evaluation_run_ledger.json",
        raw=out / "raw_results.jsonl", results=out / "holdout_results.json")



def _refuse_if_invalid_holdout_closed(paths: Paths):
    """Permanent tombstone: invalid unevaluated holdout may never be officially evaluated."""
    closure_path = paths.out / "T21R13_CLOSURE.json"
    if not closure_path.is_file():
        return None
    try:
        closure = _json(closure_path)
    except (OSError, ValueError, TypeError) as exc:
        return {
            "status": "T21R13_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED",
            "defects": [f"unreadable T21R13_CLOSURE.json: {exc}"],
            "runtime_execution_count": 0,
            "ledger_written": False,
            "candidate_rows_executed": 0,
        }
    status = str(closure.get("status") or "")
    if status in {
        "CLOSED_INVALID_UNEVALUATED_HOLDOUT",
        "INVALID_UNEVALUATED_HOLDOUT",
    } or "INVALID_UNEVALUATED_HOLDOUT" in status:
        return {
            "status": "T21R13_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED",
            "defects": [
                "T21R13 holdout is CLOSED_INVALID_UNEVALUATED_HOLDOUT; "
                "official evaluation is permanently refused",
                f"closure_reason={closure.get('reason')}",
            ],
            "runtime_execution_count": 0,
            "ledger_written": False,
            "candidate_rows_executed": 0,
            "closure_status": status,
        }
    return None

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _row_count(path: Path) -> int:
    return sum(bool(line.strip()) for line in path.read_text(
        encoding="utf-8").splitlines())


def _preflight(paths: Paths) -> dict:
    refused = _refuse_if_invalid_holdout_closed(paths)
    if refused is not None:
        return refused
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
        f"evaluations/t21r13/{name}" for name in
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

    # Preflight step 5 (T21R13 repair): the ACTUAL frozen runtime must be
    # able to load the sealed corpus before any exposure ledger can exist.
    # This is a read-only compatibility load, not a holdout-row execution:
    # it executes 0 evaluation rows and writes no artifact.
    corpus_load = verify_corpus_loadability(paths)
    if corpus_load["status"] != "PASS":
        defects.extend(f"corpus compatibility: {defect}"
                       for defect in corpus_load["defects"])

    return {
        "artifact": "T21R13_OFFICIAL_PREFLIGHT",
        "status": "PASS" if not defects else "FAIL",
        "defects": list(dict.fromkeys(defects)),
        "holdout_manifest_sha256": _sha(paths.manifest),
        "corpus_compatibility": corpus_load,
        "runtime_execution_count": 0,
        "ledger_written": False,
    }


def verify_corpus_loadability(paths: Paths) -> dict:
    """Load the sealed corpus with the ACTUAL frozen runtime load_corpus.

    Refuses before ledger creation on any incompatibility (T21R9 repair):
    a runtime-incompatible corpus must fail preflight, never consume the
    one-shot exposure.
    """
    try:
        from sciencemath.knowledge.corpus import (
            load_corpus, verify_content_hashes,
        )
        corpus = load_corpus(paths.corpus)
    except Exception as exc:  # CorruptCorpusError and any loader failure
        return {"status": "FAIL", "source_count": 0, "chunk_count": 0,
                "runtime_evaluation_rows": 0,
                "defects": [f"load_corpus refused the sealed corpus: {exc}"]}
    try:
        manifest = _json(paths.corpus / "corpus_manifest.json")
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "FAIL", "source_count": 0, "chunk_count": 0,
                "runtime_evaluation_rows": 0,
                "defects": [f"unreadable corpus manifest: {exc}"]}
    defects: list[str] = []
    supplied_manifest_checksum = manifest.get("manifest_checksum")
    checksum_document = dict(manifest)
    checksum_document.pop("manifest_checksum", None)
    computed_manifest_checksum = hashlib.sha256(json.dumps(
        checksum_document, sort_keys=True,
        ensure_ascii=False).encode("utf-8")).hexdigest()
    if supplied_manifest_checksum != computed_manifest_checksum:
        defects.append("corpus manifest checksum mismatch")
    defects.extend(verify_content_hashes(corpus.sources, corpus.chunks))
    if manifest.get("source_count") != len(corpus.sources):
        defects.append("loaded source count does not match manifest "
                       "source_count")
    if manifest.get("chunk_count") != len(corpus.chunks):
        defects.append("loaded chunk count does not match manifest "
                       "chunk_count")
    return {
        "status": "PASS" if not defects else "FAIL",
        "defects": defects,
        "source_count": len(corpus.sources),
        "chunk_count": len(corpus.chunks),
        "manifest_source_count": manifest.get("source_count"),
        "manifest_chunk_count": manifest.get("chunk_count"),
        "runtime_evaluation_rows": 0,
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
        "artifact": "T21R13_OFFICIAL_EXPOSURE_LEDGER",
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
        raise SystemExit("T21R13 preflight failed: " + "; ".join(
            report["defects"]))
    try:
        _write_ledger(paths, "started")
    except FileExistsError:
        raise SystemExit(
            "T21R13 one-shot ledger already exists after preflight: another "
            "invocation holds the exposure; refusing to execute any holdout "
            "row") from None
    try:
        from sciencemath.knowledge.corpus import load_corpus
        # Re-load after preflight already proved compatibility; the ledger
        # exists at this point only because the full preflight (including
        # the corpus compatibility gate) passed.
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
            raise SystemExit("official T21R13 runtime exposure is not authorized")
        return execute(build_paths())
    report = preflight()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

