"""Hash-only T21R9 prior exclusion and candidate uniqueness audit."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r9"
FINGERPRINT_PATH = OUT_DIR / "prior_exclusion_fingerprints.json"
DIMENSIONS = (
    "case_ids", "entity_identities", "source_ids", "chunk_ids",
    "exact_queries", "exact_answers", "exact_source_text",
    "verbatim_attack_wording",
)
MILESTONES = (
    "T21", "T21R", "T21R2", "T21R3", "T21R4", "T21R5", "T21R6",
    "T21R7", "T21R8_DIAGNOSTIC",
)
HISTORICAL = {
    "T21": (ROOT / "evaluations" / "t21" / "suites",
            ROOT / "rag" / "gk_corpus"),
    "T21R": (ROOT / "evaluations" / "t21r" / "suites",
             ROOT / "rag" / "gk_holdout_t21r"),
    "T21R2": (ROOT / "evaluations" / "t21r2" / "suites",
              ROOT / "rag" / "gk_holdout_t21r2"),
    "T21R3": (ROOT / "evaluations" / "t21r3" / "suites",
              ROOT / "rag" / "gk_holdout_t21r3"),
    "T21R4": (ROOT / "evaluations" / "t21r4" / "suites",
              ROOT / "rag" / "gk_holdout_t21r4"),
    "T21R5": (ROOT / "evaluations" / "t21r5" / "suites",
              ROOT / "rag" / "gk_holdout_t21r5"),
    "T21R6": (ROOT / "evaluations" / "t21r6" / "suites",
              ROOT / "rag" / "gk_holdout_t21r6"),
    "T21R7": (ROOT / "evaluations" / "t21r7" / "suites",
              ROOT / "rag" / "gk_holdout_t21r7"),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _rows(suites_dir: Path) -> tuple[list[dict], list[Path]]:
    paths = sorted(suites_dir.glob("*/*.jsonl"))
    paths = [path for path in paths
             if path.name in {"dev.jsonl", "final.jsonl", "holdout.jsonl"}]
    return ([row for path in paths for row in _load_jsonl(path)], paths)


def _exact(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def _entity(value: object) -> str:
    return " ".join(_exact(value).casefold().split())


def _fingerprint(dimension: str, value: object) -> str:
    normalized = _entity(value) if dimension == "entity_identities" \
        else _exact(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def material_values(sources: list[dict], chunks: list[dict],
                    rows: list[dict], world: list[dict] | None = None) \
        -> dict[str, set[str]]:
    world = world or []
    values = {dimension: set() for dimension in DIMENSIONS}
    values["case_ids"].update(_exact(row.get("case_id")) for row in rows)
    values["source_ids"].update(_exact(source.get("source_id"))
                                for source in sources)
    values["chunk_ids"].update(_exact(chunk.get("chunk_id"))
                               for chunk in chunks)
    values["exact_queries"].update(_exact(
        (row.get("request") or {}).get("query")) for row in rows)
    values["exact_answers"].update(_exact(answer) for row in rows
        for answer in ((row.get("gold") or {}).get(
            "expect_answer_contains") or []))
    values["exact_source_text"].update(_exact(chunk.get("text"))
                                       for chunk in chunks)
    values["verbatim_attack_wording"].update(_exact(
        (row.get("construction") or {}).get("attack_wording")) for row in rows
        if (row.get("construction") or {}).get("attack_wording"))
    values["entity_identities"].update(_entity(
        (chunk.get("metadata") or {}).get("fact_entity")) for chunk in chunks
        if (chunk.get("metadata") or {}).get("fact_entity"))
    for record in world:
        if record.get("type") == "WorldEntity" or record.get("record_type") \
                == "entity":
            values["entity_identities"].update(_entity(record.get(field))
                for field in ("entity_id", "name") if record.get(field))
    return {name: {value for value in dimension_values if value != ""}
            for name, dimension_values in values.items()}


def fingerprint_material(sources: list[dict], chunks: list[dict],
                         rows: list[dict], world: list[dict] | None = None) \
        -> dict[str, set[str]]:
    values = material_values(sources, chunks, rows, world)
    return {dimension: {_fingerprint(dimension, value)
                        for value in dimension_values}
            for dimension, dimension_values in values.items()}


def _encode(fingerprints: set[str]) -> dict:
    ordered = sorted(fingerprints)
    payload = ("\n".join(ordered) + ("\n" if ordered else "")).encode()
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    return {
        "count": len(ordered),
        "normalization": "NFKC+casefold+whitespace" if False else None,
        "set_sha256": hashlib.sha256(payload).hexdigest(),
        "fingerprints_gzip_base64": base64.b64encode(compressed).decode(),
    }


def _decode(document: dict) -> set[str]:
    try:
        compressed = base64.b64decode(
            document["fingerprints_gzip_base64"], validate=True)
        payload = gzip.decompress(compressed)
        text = payload.decode("ascii")
    except (KeyError, ValueError, OSError, UnicodeError) as exc:
        raise ValueError(f"invalid fingerprint payload: {exc}") from exc
    values = [line for line in text.splitlines() if line]
    if values != sorted(set(values)) or any(
            len(value) != 64 or any(char not in "0123456789abcdef"
                                    for char in value) for value in values):
        raise ValueError("fingerprints are not canonical sorted SHA-256 values")
    if len(values) != int(document.get("count", -1)):
        raise ValueError("fingerprint count mismatch")
    canonical = ("\n".join(values) + ("\n" if values else "")).encode()
    if hashlib.sha256(canonical).hexdigest() != document.get("set_sha256"):
        raise ValueError("fingerprint set hash mismatch")
    return set(values)


def _load_material(suites_dir: Path, corpus_dir: Path) \
        -> tuple[list[dict], list[dict], list[dict], list[Path]]:
    rows, suite_paths = _rows(suites_dir)
    sources_path = corpus_dir / "sources.jsonl"
    chunks_path = corpus_dir / "chunks.jsonl"
    world_path = corpus_dir / "world.jsonl"
    sources = _load_jsonl(sources_path)
    chunks = _load_jsonl(chunks_path)
    world = _load_jsonl(world_path) if world_path.exists() else []
    paths = [*suite_paths, sources_path, chunks_path]
    if world_path.exists():
        paths.append(world_path)
    return sources, chunks, rows, paths


def build_fingerprint_artifact(r8_snapshot: Path) -> dict:
    milestones: dict[str, dict] = {}
    for name, (suites, corpus) in HISTORICAL.items():
        sources, chunks, rows, paths = _load_material(suites, corpus)
        world_path = corpus / "world.jsonl"
        world = _load_jsonl(world_path) if world_path.exists() else []
        fingerprints = fingerprint_material(sources, chunks, rows, world)
        dimensions = {}
        for dimension, values in fingerprints.items():
            dimensions[dimension] = _encode(values)
            dimensions[dimension]["normalization"] = (
                "NFKC+casefold+whitespace" if dimension ==
                "entity_identities" else "NFKC exact UTF-8")
        milestones[name] = {
            "source_artifacts": [{
                "identity": path.relative_to(ROOT).as_posix(),
                "sha256": _sha(path),
            } for path in paths],
            "dimensions": dimensions,
        }

    suites = r8_snapshot / "final_candidate" / "suites"
    corpus = r8_snapshot / "world"
    sources, chunks, rows, paths = _load_material(suites, corpus)
    world = _load_jsonl(corpus / "world.jsonl")
    fingerprints = fingerprint_material(sources, chunks, rows, world)
    dimensions = {}
    for dimension, values in fingerprints.items():
        dimensions[dimension] = _encode(values)
        dimensions[dimension]["normalization"] = (
            "NFKC+casefold+whitespace" if dimension == "entity_identities"
            else "NFKC exact UTF-8")
    milestones["T21R8_DIAGNOSTIC"] = {
        "non_promotional": True,
        "raw_material_committed": False,
        "source_artifacts": [{
            "identity": "preserved-diagnostic-snapshot/" +
            path.relative_to(r8_snapshot).as_posix(),
            "sha256": _sha(path),
        } for path in paths],
        "dimensions": dimensions,
    }
    return {
        "artifact": "T21R9_PRIOR_EXCLUSION_FINGERPRINTS",
        "version": 1,
        "fingerprint_algorithm": "SHA-256",
        "payload_encoding": "gzip+base64 newline-delimited lowercase hex",
        "raw_values_included": False,
        "milestones": milestones,
    }


def validate_artifact(artifact: dict) -> dict[str, dict[str, set[str]]]:
    if artifact.get("raw_values_included") is not False:
        raise ValueError("fingerprint artifact raw-value policy is invalid")
    if set(artifact.get("milestones") or {}) != set(MILESTONES):
        raise ValueError("fingerprint artifact milestone set mismatch")
    decoded: dict[str, dict[str, set[str]]] = {}
    for milestone in MILESTONES:
        dimensions = artifact["milestones"][milestone].get("dimensions") or {}
        if set(dimensions) != set(DIMENSIONS):
            raise ValueError(f"dimension set mismatch for {milestone}")
        decoded[milestone] = {dimension: _decode(dimensions[dimension])
                              for dimension in DIMENSIONS}
    return decoded


def audit_candidate(sources: list[dict], chunks: list[dict], rows: list[dict],
                    artifact: dict) -> dict:
    current = fingerprint_material(sources, chunks, rows)
    return audit_fingerprint_sets(current, artifact)


def audit_fingerprint_sets(current: dict[str, set[str]],
                           artifact: dict) -> dict:
    prior = validate_artifact(artifact)
    if set(current) != set(DIMENSIONS):
        raise ValueError("candidate fingerprint dimension set mismatch")
    overlap = {milestone: {
        dimension: sorted(current[dimension] & prior[milestone][dimension])
        for dimension in DIMENSIONS} for milestone in MILESTONES}
    overlap_counts = {milestone: {dimension: len(values)
                                  for dimension, values in dimensions.items()}
                      for milestone, dimensions in overlap.items()}
    total = sum(count for dimensions in overlap_counts.values()
                for count in dimensions.values())
    return {
        "artifact": "T21R9_UNIQUENESS_AUDIT",
        "status": "UNIQUE" if total == 0 else "OVERLAP",
        "overlap_counts": overlap_counts,
        "overlap_total": total,
        "milestones_checked": list(MILESTONES),
        "dimensions_checked": list(DIMENSIONS),
        "fingerprint_artifact_sha256": _sha(FINGERPRINT_PATH)
        if FINGERPRINT_PATH.exists() else None,
        "runtime_execution_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-fingerprints", action="store_true")
    parser.add_argument("--r8-snapshot", type=Path)
    arguments = parser.parse_args()
    if arguments.build_fingerprints:
        if arguments.r8_snapshot is None:
            raise SystemExit("--r8-snapshot is required")
        document = build_fingerprint_artifact(arguments.r8_snapshot)
        FINGERPRINT_PATH.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
        print(json.dumps({"path": str(FINGERPRINT_PATH),
                          "sha256": _sha(FINGERPRINT_PATH)}, indent=2))
        return 0
    sys.path.insert(0, str(ROOT / "scripts"))
    import t21r9_construction_audit as construction
    sources, chunks, rows_by_suite = construction.load_candidate()
    rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
    artifact = json.loads(FINGERPRINT_PATH.read_text(encoding="utf-8"))
    report = audit_candidate(sources, chunks, rows, artifact)
    path = OUT_DIR / "holdout_uniqueness.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "UNIQUE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
