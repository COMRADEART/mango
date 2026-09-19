"""Preregistered, runtime-independent T21R9 blind-suite materializer."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "evaluations" / "t21r9" / \
    "holdout_construction_contract.json"
DEFAULT_OUTPUT = ROOT / "evaluations" / "t21r9" / "suites"
AUTHORIZATION_PHRASE = "T21R9_BLIND_CONSTRUCTION_AUTHORIZED"


def validate_suite_spec(specification: dict, contract: dict) \
        -> dict[str, list[dict]]:
    rows = specification.get("rows")
    if not isinstance(rows, list):
        raise ValueError("suite specification rows must be a list")
    expected = contract["suite_target_exact"]
    grouped = {suite_id: [] for suite_id in expected}
    case_ids: set[str] = set()
    queries: set[str] = set()
    for row in rows:
        suite_id = str(row.get("suite_id") or "")
        if suite_id not in grouped:
            raise ValueError(f"unknown suite ID: {suite_id}")
        case_id = str(row.get("case_id") or "")
        query = str((row.get("request") or {}).get("query") or "")
        if not case_id or not query or not isinstance(row.get("gold"), dict):
            raise ValueError("every row requires case_id, request.query, and gold")
        if case_id in case_ids or query in queries:
            raise ValueError("case IDs and exact queries must be unique")
        if case_id.casefold().startswith("pre9q-"):
            raise ValueError("disposable pre9q cases are forbidden in blind data")
        annotation = row.get("construction") or {}
        if "initial_window_chunk_ids" in annotation:
            raise ValueError("builders may not declare initial retrieval windows")
        case_ids.add(case_id)
        queries.add(query)
        clean = dict(row)
        clean.pop("suite_id", None)
        grouped[suite_id].append(clean)
    actual = {suite_id: len(suite_rows)
              for suite_id, suite_rows in grouped.items()}
    if actual != expected:
        raise ValueError(f"exact suite counts differ: {actual} != {expected}")
    return grouped


def materialize_suites(specification: dict, output: Path,
                       contract: dict) -> dict:
    grouped = validate_suite_spec(specification, contract)
    if output.exists():
        raise FileExistsError(f"refusing to replace existing suites: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="t21r9-suites-", dir=output.parent))
    try:
        for suite_id, rows in grouped.items():
            suite_dir = temporary / suite_id
            suite_dir.mkdir()
            payload = "".join(json.dumps(
                row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
            (suite_dir / "holdout.jsonl").write_text(
                payload, encoding="utf-8", newline="\n")
        os.replace(temporary, output)
    except BaseException:
        for path in sorted(temporary.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        temporary.rmdir()
        raise
    return {suite_id: len(rows) for suite_id, rows in grouped.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--authorization", required=True)
    arguments = parser.parse_args()
    if arguments.authorization != AUTHORIZATION_PHRASE:
        raise SystemExit("T21R9 blind construction is not authorized")
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    specification = json.loads(arguments.private_spec.read_text(
        encoding="utf-8"))
    result = materialize_suites(specification, arguments.output, contract)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
