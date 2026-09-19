"""Hash-only T21R11 prior exclusion and candidate uniqueness audit."""
from __future__ import annotations

import argparse
import ast
import base64
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r11"
FINGERPRINT_PATH = OUT_DIR / "prior_exclusion.json"
REMEDIATION_PATH = OUT_DIR / "remediation_exclusion.json"
DIMENSIONS = (
    "case_ids", "entity_identities", "source_ids", "chunk_ids",
    "exact_queries", "exact_answers", "exact_source_text",
    "verbatim_attack_wording",
)
MILESTONES = (
    "T21", "T21R", "T21R2", "T21R3", "T21R4", "T21R5", "T21R6",
    "T21R7", "T21R8_DIAGNOSTIC", "T21R9_SEALED", "T21R10_SEALED",
)
SEALED_R10_COMMIT = "9f63d94ecd68299f0397e98048bb29bef937220d"
OFFICIAL_R10_COMMIT = "247f13656a8392472b0c669d6e1c113071979a62"
R10_FINGERPRINT_PATH = ROOT / "evaluations" / "t21r10" / \
    "prior_exclusion_fingerprints.json"
R10_SEALED_CORPUS = "rag/gk_holdout_t21r10"
R10_SEALED_SUITES = "evaluations/t21r10/suites"
REMEDIATION_DIR = ROOT / "evaluations" / "t21r11_diagnostics"
REMEDIATION_TEST = ROOT / "tests" / "test_t21r11_remediation.py"
REMEDIATION_DIMENSIONS = (*DIMENSIONS, "relations")


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
        (row.get("request") or {}).get("query") or row.get("query"))
        for row in rows)
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


def remediation_fingerprint_material(
    sources: list[dict], chunks: list[dict], rows: list[dict]
) -> dict[str, set[str]]:
    """Fingerprint the historical dimensions plus relation vocabulary."""
    result = fingerprint_material(sources, chunks, rows)
    relations = {
        _exact((chunk.get("metadata") or {}).get("fact_attribute"))
        for chunk in chunks
        if (chunk.get("metadata") or {}).get("fact_attribute")
    }
    for row in rows:
        construction = row.get("construction") or {}
        relations.update(_exact(value) for value in
                         construction.get("canonical_relations") or [])
    result["relations"] = {
        _fingerprint("relations", value) for value in relations if value}
    return result


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


def extract_r10_sealed_material(target: Path, commit: str) -> dict:
    """Extract sealed R10 material only into a disposable hash workspace.

    Raw R10 values never enter a committed artifact and are never made
    available to the R11 world or suite builders.  Only SHA-256 fingerprints
    and source-blob identities leave this function.
    """
    specs: list[tuple[str, Path]] = []
    for name in ("sources.jsonl", "chunks.jsonl", "world.jsonl"):
        specs.append((f"{R10_SEALED_CORPUS}/{name}", target / name))
    tree = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit,
         R10_SEALED_SUITES], cwd=ROOT, text=True).splitlines()
    for path in tree:
        if not path.endswith("/holdout.jsonl"):
            continue
        relative = path[len(R10_SEALED_SUITES):].lstrip("/")
        specs.append((path, target / "suites" / relative))
    extracted = []
    for git_path, file_path in specs:
        blob = subprocess.check_output(["git", "show", f"{commit}:{git_path}"],
                                       cwd=ROOT)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(blob)
        extracted.append({"identity": f"git:{commit}/{git_path}",
                          "sha256": hashlib.sha256(blob).hexdigest()})
    return {"sealed_commit": commit, "extracted": extracted,
            "raw_material_committed": False}


def build_fingerprint_artifact(r10_fingerprint_path: Path,
                               r10_sealed_material: Path) -> dict:
    """Build the 11-milestone R11 historical hash-only exclusion set."""
    r10_artifact = json.loads(
        r10_fingerprint_path.read_text(encoding="utf-8"))
    expected_prior = set(MILESTONES) - {"T21R10_SEALED"}
    if set(r10_artifact.get("milestones") or {}) != expected_prior:
        raise ValueError("R10 fingerprint artifact milestone set mismatch")
    for name in expected_prior:
        milestone = r10_artifact["milestones"][name]
        dimensions = milestone.get("dimensions") or {}
        if set(dimensions) != set(DIMENSIONS):
            raise ValueError(f"dimension set mismatch for carried {name}")
        for dimension in DIMENSIONS:
            _decode(dimensions[dimension])  # refuse corrupt carried payloads
    milestones: dict[str, dict] = {name: r10_artifact["milestones"][name]
                                   for name in sorted(expected_prior)}
    sources, chunks, rows, paths = _load_material(
        r10_sealed_material / "suites", r10_sealed_material)
    world_path = r10_sealed_material / "world.jsonl"
    world = _load_jsonl(world_path) if world_path.exists() else []
    fingerprints = fingerprint_material(sources, chunks, rows, world)
    dimensions = {}
    for dimension, values in fingerprints.items():
        dimensions[dimension] = _encode(values)
        dimensions[dimension]["normalization"] = (
            "NFKC+casefold+whitespace" if dimension == "entity_identities"
            else "NFKC exact UTF-8")
    milestones["T21R10_SEALED"] = {
        "non_promotional": True,
        "raw_material_committed": False,
        "sealed_commit": SEALED_R10_COMMIT,
        "official_commit": OFFICIAL_R10_COMMIT,
        "official_result": "T21R10_OFFICIAL_EVALUATION_FAIL",
        "source_artifacts": [{
            "identity": f"git:{SEALED_R10_COMMIT}/" +
            path.relative_to(r10_sealed_material).as_posix(),
            "sha256": _sha(path),
        } for path in paths],
        "dimensions": dimensions,
    }
    return {
        "artifact": "T21R11_PRIOR_EXCLUSION_FINGERPRINTS",
        "version": 1,
        "fingerprint_algorithm": "SHA-256",
        "payload_encoding": "gzip+base64 newline-delimited lowercase hex",
        "raw_values_included": False,
        "milestones": milestones,
    }


def _test_fixture_values(path: Path) -> dict[str, set[str]]:
    """Extract only typed fixture literals from the open remediation test."""
    values = {dimension: set() for dimension in REMEDIATION_DIMENSIONS}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func.id if isinstance(node.func, ast.Name) else ""
        if called == "_chunk" and len(node.args) >= 4:
            text = node.args[3]
            if isinstance(text, ast.Constant) and isinstance(text.value, str):
                values["exact_source_text"].add(_exact(text.value))
            for keyword in node.keywords:
                if not isinstance(keyword.value, ast.Constant):
                    continue
                value = keyword.value.value
                if keyword.arg == "fact_entity":
                    values["entity_identities"].add(_entity(value))
                elif keyword.arg == "fact_value":
                    values["exact_answers"].add(_exact(value))
                elif keyword.arg == "fact_attribute":
                    values["relations"].add(_exact(value))
        elif called == "answer_knowledge" and node.args and isinstance(
                node.args[0], ast.Constant):
            values["exact_queries"].add(_exact(node.args[0].value))
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str) and argument.value.startswith("gk-r11-"):
                values["source_ids"].add(_exact(argument.value))
    return values


def build_remediation_artifact() -> dict:
    """Hash open DEV/VALIDATION diagnostics and remediation test fixtures."""
    sources = _load_jsonl(REMEDIATION_DIR / "world" / "sources.jsonl")
    chunks = _load_jsonl(REMEDIATION_DIR / "world" / "chunks.jsonl")
    rows = _load_jsonl(REMEDIATION_DIR / "dev_suites.jsonl") + \
        _load_jsonl(REMEDIATION_DIR / "validation_suites.jsonl")
    fingerprints = remediation_fingerprint_material(sources, chunks, rows)
    test_values = _test_fixture_values(REMEDIATION_TEST)
    for dimension, values in test_values.items():
        fingerprints.setdefault(dimension, set()).update(
            _fingerprint(dimension, value) for value in values if value)
    # Injection payloads are open material and are fingerprinted without
    # importing them into future builders.
    sys.path.insert(0, str(ROOT / "scripts"))
    import t21r11_diag_world as diagnostic_world
    fingerprints["verbatim_attack_wording"].update(
        _fingerprint("verbatim_attack_wording", value)
        for value in diagnostic_world.INJECTION_SENTENCES.values())
    dimensions = {}
    for dimension in REMEDIATION_DIMENSIONS:
        dimensions[dimension] = _encode(fingerprints.get(dimension, set()))
        dimensions[dimension]["normalization"] = (
            "NFKC+casefold+whitespace" if dimension == "entity_identities"
            else "NFKC exact UTF-8")
    source_paths = [
        REMEDIATION_DIR / "world" / "sources.jsonl",
        REMEDIATION_DIR / "world" / "chunks.jsonl",
        REMEDIATION_DIR / "dev_suites.jsonl",
        REMEDIATION_DIR / "validation_suites.jsonl",
        REMEDIATION_TEST,
    ]
    return {
        "artifact": "T21R11_OPEN_REMEDIATION_EXCLUSION",
        "class": "OPEN_REMEDIATION_MATERIAL",
        "version": 1,
        "fingerprint_algorithm": "SHA-256",
        "payload_encoding": "gzip+base64 newline-delimited lowercase hex",
        "raw_values_included": False,
        "dimensions": dimensions,
        "source_artifacts": [{
            "path": path.relative_to(ROOT).as_posix(), "sha256": _sha(path)}
            for path in source_paths],
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


def validate_remediation_artifact(artifact: dict) -> dict[str, set[str]]:
    if artifact.get("artifact") != "T21R11_OPEN_REMEDIATION_EXCLUSION" or \
            artifact.get("class") != "OPEN_REMEDIATION_MATERIAL" or \
            artifact.get("raw_values_included") is not False:
        raise ValueError("open-remediation exclusion identity/policy mismatch")
    dimensions = artifact.get("dimensions") or {}
    if set(dimensions) != set(REMEDIATION_DIMENSIONS):
        raise ValueError("open-remediation dimension set mismatch")
    return {dimension: _decode(dimensions[dimension])
            for dimension in REMEDIATION_DIMENSIONS}


def audit_candidate(sources: list[dict], chunks: list[dict], rows: list[dict],
                    artifact: dict) -> dict:
    current = fingerprint_material(sources, chunks, rows)
    return audit_fingerprint_sets(current, artifact)


def audit_open_remediation(sources: list[dict], chunks: list[dict],
                           rows: list[dict], artifact: dict) -> dict:
    current = remediation_fingerprint_material(sources, chunks, rows)
    excluded = validate_remediation_artifact(artifact)
    overlap = {dimension: sorted(current[dimension] & excluded[dimension])
               for dimension in REMEDIATION_DIMENSIONS}
    counts = {dimension: len(values)
              for dimension, values in overlap.items()}
    total = sum(counts.values())
    return {
        "artifact": "T21R11_REMEDIATION_UNIQUENESS_AUDIT",
        "status": "UNIQUE" if total == 0 else "OVERLAP",
        "overlap_counts": counts,
        "overlap_total": total,
        "dimensions_checked": list(REMEDIATION_DIMENSIONS),
        "runtime_execution_count": 0,
    }


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
        "artifact": "T21R11_UNIQUENESS_AUDIT",
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
    global SEALED_R10_COMMIT
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-fingerprints", action="store_true")
    parser.add_argument("--r10-sealed-commit", default=SEALED_R10_COMMIT)
    parser.add_argument("--r10-material", type=Path,
                        help="pre-extracted R10 sealed material directory "
                             "(overrides extraction from the sealed commit)")
    arguments = parser.parse_args()
    if arguments.build_fingerprints:
        SEALED_R10_COMMIT = arguments.r10_sealed_commit
        with tempfile.TemporaryDirectory(prefix="t21r11-r10-fingerprints-") as \
                tmp:
            material = Path(tmp) / "sealed_r10"
            if arguments.r10_material is not None:
                material = arguments.r10_material
            else:
                extract_r10_sealed_material(
                    material, arguments.r10_sealed_commit)
            document = build_fingerprint_artifact(R10_FINGERPRINT_PATH,
                                                  material)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        FINGERPRINT_PATH.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
        remediation = build_remediation_artifact()
        REMEDIATION_PATH.write_text(
            json.dumps(remediation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
        print(json.dumps({
            "prior_path": str(FINGERPRINT_PATH),
            "prior_sha256": _sha(FINGERPRINT_PATH),
            "remediation_path": str(REMEDIATION_PATH),
            "remediation_sha256": _sha(REMEDIATION_PATH),
        }, indent=2))
        return 0
    sys.path.insert(0, str(ROOT / "scripts"))
    import t21r11_construction_audit as construction
    sources, chunks, rows_by_suite = construction.load_candidate()
    rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
    artifact = json.loads(FINGERPRINT_PATH.read_text(encoding="utf-8"))
    prior = audit_candidate(sources, chunks, rows, artifact)
    remediation = audit_open_remediation(
        sources, chunks, rows,
        json.loads(REMEDIATION_PATH.read_text(encoding="utf-8")))
    report = {
        "artifact": "T21R11_UNIQUENESS_AUDIT",
        "status": "UNIQUE" if prior["status"] == "UNIQUE" and
        remediation["status"] == "UNIQUE" else "OVERLAP",
        "prior": prior,
        "open_remediation": remediation,
        "runtime_execution_count": 0,
    }
    path = OUT_DIR / "holdout_uniqueness.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "UNIQUE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
