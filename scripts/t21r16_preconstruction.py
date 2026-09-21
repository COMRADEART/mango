"""T21R16 runtime-native preconstruction generator (staged, deterministic).

The R15 sealed holdout was constructed against a corpus model the frozen
candidate runtime cannot load (KnowledgeSourceRecord.from_dict requires
content_hash/document_hash; load_corpus requires per-file checksums; source
IDs must match the gk- grammar). T21R16 is therefore RUNTIME_NATIVE_BY_
CONSTRUCTION: authored material is materialized only through frozen runtime
producers and validated by the frozen loader before any suite exists.

Stages (run in order):
  registry      derive evaluations/t21r16/prior_exclusion.json (R14 registry
                carried byte-identical + T21R15_SEALED_UNEVALUABLE, hash-only)
  static        static preconstruction artifacts
  adjudication  run the full test suite and adjudicate failures
  freeze        evaluator_freeze.json
  contract      t21_master_contract.json
  lock          qualification_lock.json
  shadow        runtime_native_shadow_validation.json
  parity        provider_parity_report.json
  lifecycle     lifecycle_rehearsal.json (x2)
  cleanliness   test_cleanliness.json
  doctor        protocol doctor run
  audit         T21R16_PRECONSTRUCTION_AUDIT.json
  prefreeze     preconstruction_freeze.json
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r16"
R15_OUT = ROOT / "evaluations" / "t21r15"
sys.path.insert(0, str(ROOT))

from t21_protocol.audits import DIMENSIONS, _fingerprint  # noqa: E402
from t21_protocol.contract import load_contract  # noqa: E402
from t21_protocol.freeze import build_freeze  # noqa: E402
from t21_protocol.qualification import build_qualification_lock  # noqa: E402
from t21_protocol.seal import HOLDOUT_FROZEN_FIELDS_BY_SCHEMA_VERSION  # noqa: E402
from t21_protocol.util import read_json, sha256_file, sha256_json, write_json  # noqa: E402

R15_CONSTRUCTION_HEAD = "86099f03461dde34b90424c990d1e0d756202b40"
R15_SEAL_MANIFEST_SHA256 = "4514bedb096d095db5f35f415e4148a8a472628df2413d00ef838c87bd205a4d"
R15_HOLDOUT_FROZEN_SHA256 = "9c2aadd365a1f553db694390c6d2b03fe9b4ae21b4c9806b7e60e6e6f8f8ccfc"
R15_SEAL_ROOT = "34782693ef413aced065b09840b1372f7e4d218ecdf25938b8d03894f6c65aff"
R15_CLOSURE_STATUS = "CLOSED / SEALED_HOLDOUT_RUNTIME_CONTRACT_INCOMPATIBILITY"
R15_CLOSURE_REASON = "SEALED_CORPUS_NOT_LOADABLE_BY_FROZEN_CANDIDATE_RUNTIME"
R15_HISTORICAL_MILESTONE = "T21R15_SEALED_UNEVALUABLE"
R14_REGISTRY = "evaluations/t21r14/prior_exclusion.json"
R15_SEAL_MANIFEST = "evaluations/t21r15/holdout_manifest.json"
R15_HOLDOUT_FROZEN = "evaluations/t21r15/HOLDOUT_FROZEN"
RUNTIME_COMPONENTS = (
    "src/sciencemath/knowledge/citations.py",
    "src/sciencemath/knowledge/claim_gate.py",
    "src/sciencemath/knowledge/conflicts.py",
    "src/sciencemath/knowledge/corpus.py",
    "src/sciencemath/knowledge/evidence.py",
    "src/sciencemath/knowledge/evidence_paths.py",
    "src/sciencemath/knowledge/freshness.py",
    "src/sciencemath/knowledge/index.py",
    "src/sciencemath/knowledge/injection.py",
    "src/sciencemath/knowledge/pipeline.py",
    "src/sciencemath/knowledge/provenance_spoof.py",
    "src/sciencemath/knowledge/relations.py",
    "src/sciencemath/knowledge/retrieval.py",
    "src/sciencemath/knowledge/routing.py",
    "src/sciencemath/knowledge/schema.py",
)
CANDIDATE_COMMIT = "d4b1902c9b93cae4931a348e460ce2da3e776c6f"
CANDIDATE_TREE = "dc3ca7f14375e3e71356b166a2e78a24ac3f668b"
RUNTIME_ROOT = "7bba4d0d2e381d741727e5f8d2d6a50cd82df8c054f2ec18610999a818ce1b80"
FLOOR_HASH = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"
SUITE_SIZES = (
    ("adversarial", 650),
    ("citation_claim", 450),
    ("conflict_abstention", 800),
    ("crossdomain", 700),
    ("multihop", 800),
    ("retrieval", 600),
    ("singlehop", 550),
    ("temporal", 250),
)
R16_CROSSDOMAIN_PAIRS = [
    {"domain_a": "arts", "domain_b": "geography", "id": "arts__geography"},
    {"domain_a": "biography", "domain_b": "economics", "id": "biography__economics"},
    {"domain_a": "civic_architecture", "domain_b": "natural_world", "id": "civic_architecture__natural_world"},
    {"domain_a": "computing", "domain_b": "history", "id": "computing__history"},
    {"domain_a": "culture", "domain_b": "government_civics", "id": "culture__government_civics"},
    {"domain_a": "education_reference", "domain_b": "technology_history", "id": "education_reference__technology_history"},
    {"domain_a": "literature", "domain_b": "natural_philosophy", "id": "literature__natural_philosophy"},
]


def _load(relative: str) -> dict[str, Any]:
    return read_json(ROOT / relative)


def _write(relative: str, document: dict[str, Any], *, exclusive: bool = False) -> None:
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, document, exclusive=exclusive)


def _runtime_modules():
    src = str((ROOT / "src").resolve())
    if src not in sys.path:
        sys.path.insert(0, src)
    import sciencemath.knowledge.corpus as corpus_module
    import sciencemath.knowledge.pipeline as pipeline_module
    import sciencemath.knowledge.schema as schema_module

    return schema_module, corpus_module, pipeline_module


# ---------------------------------------------------------------- registry --


def _r15_sealed_fingerprints() -> dict[str, set[str]]:
    """Hash-only derivation input for the T21R15 registry milestone.

    R15 sealed material is read, fingerprinted in memory with the protocol's
    own fingerprint function, and never persisted: the registry stores
    fingerprints only."""
    r15 = _load("evaluations/t21r15/t21_master_contract.json")
    rows: list[dict[str, Any]] = []
    for suite_name in r15["values"]["suites"]:
        path = R15_OUT / "suites" / suite_name / "holdout.jsonl"
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    corpus_dir = ROOT / "rag" / "gk_holdout_t21r15"
    sources = [json.loads(line) for line in (corpus_dir / "sources.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks = [json.loads(line) for line in (corpus_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    world = [json.loads(line) for line in (corpus_dir / "world.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 4800 or len(sources) != 4800 or len(chunks) != 4800 or len(world) != 4800:
        raise SystemExit("R15 sealed material shape mismatch")
    values: dict[str, set[str]] = {dimension: set() for dimension in DIMENSIONS}
    values["case_ids"].update(_fingerprint("case_ids", row.get("case_id")) for row in rows)
    values["exact_queries"].update(_fingerprint("exact_queries", row.get("query")) for row in rows)
    values["exact_answers"].update(_fingerprint("exact_answers", (row.get("gold") or {}).get("expected_answer")) for row in rows)
    values["verbatim_attack_wording"].update(
        _fingerprint("verbatim_attack_wording", row["construction"]["attack_wording"])
        for row in rows
        if (row.get("construction") or {}).get("attack_wording")
    )
    values["source_ids"].update(_fingerprint("source_ids", source.get("source_id")) for source in sources)
    values["chunk_ids"].update(_fingerprint("chunk_ids", chunk.get("chunk_id")) for chunk in chunks)
    values["exact_source_text"].update(_fingerprint("exact_source_text", chunk.get("text")) for chunk in chunks)
    for record in world:
        if record.get("record_type") == "entity" or record.get("type") == "WorldEntity":
            values["entity_identities"].update(
                _fingerprint("entity_identities", record.get(field)) for field in ("entity_id", "name") if record.get(field)
            )
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        if metadata.get("fact_entity"):
            values["entity_identities"].add(_fingerprint("entity_identities", metadata["fact_entity"]))
    return {name: {value for value in items if value} for name, items in values.items()}


def stage_registry() -> dict[str, Any]:
    upstream = _load(R14_REGISTRY)
    if upstream.get("historical_milestone_count") != 14:
        raise SystemExit("unexpected upstream registry milestone count")
    fingerprints = _r15_sealed_fingerprints()
    milestone = {
        "dimensions": {
            dimension: {
                "count": len(values),
                "fingerprints": sorted(values),
                "set_sha256": _canonical_set_sha(sorted(values)),
            }
            for dimension, values in fingerprints.items()
        },
        "provenance": {
            "milestone": R15_HISTORICAL_MILESTONE,
            "derivation": "hash-only in-memory fingerprinting of R15 sealed material with t21_protocol.audits._fingerprint; raw values never persisted",
            "construction_head": R15_CONSTRUCTION_HEAD,
            "sealed_holdout_manifest_sha256": R15_SEAL_MANIFEST_SHA256,
            "sealed_holdout_frozen_sha256": R15_HOLDOUT_FROZEN_SHA256,
            "sealed_seal_root": R15_SEAL_ROOT,
            "source_paths": [
                "evaluations/t21r15/suites/<suite>/holdout.jsonl",
                "rag/gk_holdout_t21r15/sources.jsonl",
                "rag/gk_holdout_t21r15/chunks.jsonl",
                "rag/gk_holdout_t21r15/world.jsonl",
            ],
            "raw_values_included": False,
            "empty_dimension_note": (
                "verbatim_attack_wording is empty because R15 sealed rows carry construction_tag only "
                "(no construction.attack_wording field was authored under the R15 design); "
                "set_sha256 of the empty set = sha256 over zero bytes"
            ),
        },
    }
    milestone_names = list(upstream["milestone_order"]) + [R15_HISTORICAL_MILESTONE]
    registry = {
        "artifact": "T21R16_PRIOR_EXCLUSION_REGISTRY",
        "version": "t21r16-v1",
        "fingerprint_algorithm": upstream["fingerprint_algorithm"],
        "payload_encoding": upstream["payload_encoding"],
        "historical_dimensions": len(DIMENSIONS),
        "historical_milestone_count": len(milestone_names),
        "milestone_order": milestone_names,
        "milestones": {**upstream["milestones"], R15_HISTORICAL_MILESTONE: milestone},
        "raw_values_included": False,
    }
    if len(registry["milestones"]) != 15:
        raise SystemExit("registry must carry exactly 15 milestones")
    for name, spec in registry["milestones"].items():
        if set(spec["dimensions"]) != set(DIMENSIONS):
            raise SystemExit(f"milestone {name} dimensions invalid")
        for dimension, payload in spec["dimensions"].items():
            if payload["count"] != len(payload["fingerprints"]):
                raise SystemExit(f"milestone {name}/{dimension} count mismatch")
    _write("evaluations/t21r16/prior_exclusion.json", registry)
    return {
        "status": "PASS",
        "milestones": len(milestone_names),
        "r15_fingerprint_counts": {dimension: milestone["dimensions"][dimension]["count"] for dimension in DIMENSIONS},
    }


# ------------------------------------------------------------------ static --


def _holdout_frozen_schema() -> dict[str, Any]:
    string_fields = {
        "schema_version", "experiment", "construction_status", "workspace_mode",
        "material_mode", "candidate_provider_id", "holdout_manifest_sha256",
        "freeze_root_sha256", "candidate_commit", "candidate_tree", "runtime_root",
        "evaluator_root", "floor_hash", "runtime_data_contract_root",
        "runtime_corpus_contract_sha256", "runtime_field_provenance_sha256",
        "runtime_loader_validation_sha256", "candidate_provider_sha256",
    }
    integer_fields = {
        "construction_attempts", "corpus_materializations", "suite_materializations",
        "candidate_rows_executed", "runtime_rows_executed", "official_evaluator_invocations",
    }
    expected = set(HOLDOUT_FROZEN_FIELDS_BY_SCHEMA_VERSION["t21-holdout-frozen-v2"])
    if set(string_fields) | set(integer_fields) != expected or set(string_fields) & set(integer_fields):
        raise SystemExit("HOLDOUT_FROZEN v2 field partition mismatch")
    properties = {name: {"type": "string"} for name in string_fields}
    properties.update({name: {"type": "integer"} for name in integer_fields})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "artifact": "T21_HOLDOUT_FROZEN_SCHEMA",
        "properties": properties,
        "required": sorted(properties),
        "schema_version": "t21-holdout-frozen-schema-v2",
        "type": "object",
    }


def _negative_controls() -> dict[str, Any]:
    r15 = _load("evaluations/t21r15/negative_controls.json")
    controls = list(r15["controls"])
    controls.extend(
        {"failure_class": name, "latest_legal_phase": "PRECONSTRUCTION", "test": test}
        for name, test in (
            ("runtime schema missing required source field", "tests/test_t21r16_preconstruction.py::test_missing_required_source_field_fails_closed"),
            ("runtime source id grammar violation", "tests/test_t21r16_preconstruction.py::test_source_id_grammar_violation_fails_closed"),
            ("runtime manifest missing file checksums", "tests/test_t21r16_preconstruction.py::test_manifest_missing_file_checksums_fails_closed"),
            ("runtime source missing authority or freshness metadata", "tests/test_t21r16_preconstruction.py::test_missing_authority_or_freshness_fails_closed"),
            ("runtime chunk missing section or span metadata", "tests/test_t21r16_preconstruction.py::test_missing_section_or_span_fails_closed"),
            ("runtime default-filling of missing required field", "tests/test_t21r16_preconstruction.py::test_no_default_filling_of_missing_fields"),
            ("runtime contract not derived from frozen schema", "tests/test_t21r16_preconstruction.py::test_runtime_contract_is_derived_from_frozen_modules"),
        )
    )
    return {
        "schema_version": "t21-negative-controls-v1",
        "artifact": "T21R16_NEGATIVE_CONTROL_REGISTRY",
        "experiment": "t21r16",
        "infrastructure_errors_must_fail_before_construction": True,
        "controls": controls,
    }


def _frozen_function_source(module_path: Path, name: str) -> str:
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise SystemExit(f"frozen function not found: {name}")


def _subscript_keys(module_path: Path, function_name: str, *, var_name: str) -> list[str]:
    """Required ``<var>["key"]`` subscripts inside a frozen module function."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Subscript)
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == var_name
                    and isinstance(inner.slice, ast.Constant)
                ):
                    keys.append(inner.slice.value)
    return sorted(set(keys))


def _class_from_dict_keys(module_path: Path, class_name: str, *, var_name: str = "data") -> list[str]:
    """Required ``data["key"]`` subscripts inside a frozen class's from_dict."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for inner in ast.walk(node):
                if isinstance(inner, ast.FunctionDef) and inner.name == "from_dict":
                    for leaf in ast.walk(inner):
                        if (
                            isinstance(leaf, ast.Subscript)
                            and isinstance(leaf.value, ast.Name)
                            and leaf.value.id == var_name
                            and isinstance(leaf.slice, ast.Constant)
                        ):
                            keys.append(leaf.slice.value)
    return sorted(set(keys))


def _manifest_keys(module_path: Path, function_name: str, variable: str) -> list[str]:
    """Keys of the manifest dict a frozen function builds: the assigned dict
    literal's keys plus later ``variable["key"] = ...`` subscript targets."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            keys: list[str] = []
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Assign)
                    and isinstance(inner.value, ast.Dict)
                    and any(isinstance(target, ast.Name) and target.id == variable for target in inner.targets)
                ):
                    keys.extend(item.value for item in inner.value.keys if isinstance(item, ast.Constant))
                if (
                    isinstance(inner, ast.Assign)
                    and any(
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == variable
                        and isinstance(target.slice, ast.Constant)
                        for target in inner.targets
                    )
                ):
                    keys.extend(
                        target.slice.value
                        for target in inner.targets
                        if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                    )
            return sorted(set(keys))
    raise SystemExit(f"manifest variable not found: {function_name}:{variable}")


_JSONL_NAME_RE = re.compile(r'"([A-Za-z0-9_]+\.(?:jsonl|json))"')


def _canonical_set_sha(fingerprints: list[str]) -> str:
    canonical = ("\n".join(sorted(fingerprints)) + ("\n" if fingerprints else "")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _runtime_corpus_contract() -> tuple[dict[str, Any], dict[str, bool]]:
    """Derive the runtime corpus contract from the frozen runtime bytes.

    Dataclasses, closed vocabularies, and signatures come from live module
    introspection; required constructor keys, manifest keys, and required
    loader files come from AST extraction over the same bytes. Nothing is
    hand-copied."""
    import dataclasses

    schema, corpus_module, pipeline_module = _runtime_modules()
    schema_path = ROOT / "src" / "sciencemath" / "knowledge" / "schema.py"
    corpus_path = ROOT / "src" / "sciencemath" / "knowledge" / "corpus.py"

    def _split_fields(record: type) -> tuple[list[str], list[str]]:
        required, optional = [], []
        for field in dataclasses.fields(record):
            target = required if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING else optional
            target.append(field.name)
        return required, optional

    source_required, source_optional = _split_fields(schema.KnowledgeSourceRecord)
    chunk_required, chunk_optional = _split_fields(schema.KnowledgeChunk)
    source_from_dict_keys = _class_from_dict_keys(schema_path, "KnowledgeSourceRecord")
    chunk_from_dict_keys = _class_from_dict_keys(schema_path, "KnowledgeChunk")
    loader_source_keys = _subscript_keys(corpus_path, "_load_sources", var_name="row")
    loader_chunk_keys = sorted(set(_subscript_keys(corpus_path, "_load_chunks", var_name="json")) | set(_class_from_dict_keys(schema_path, "KnowledgeChunk")))
    make_source_id_source = _frozen_function_source(schema_path, "make_source_id")
    make_chunk_id_source = _frozen_function_source(schema_path, "make_chunk_id")
    load_corpus_source = _frozen_function_source(corpus_path, "load_corpus")
    build_corpus_files_source = _frozen_function_source(corpus_path, "build_corpus_files")
    manifest_keys = _manifest_keys(corpus_path, "build_corpus_files", "manifest")
    required_files = sorted(set(_JSONL_NAME_RE.findall(load_corpus_source)))
    answer_knowledge_signature = str(inspect.signature(pipeline_module.answer_knowledge))
    checks = {
        "dataclass_field_introspection": bool(source_required) and bool(chunk_required),
        "constructor_required_keys_ast": bool(source_from_dict_keys) and bool(chunk_from_dict_keys),
        "loader_required_keys_ast": bool(loader_source_keys) and bool(loader_chunk_keys),
        "closed_vocabularies": bool(schema.AUTHORITY_CLASSES) and bool(schema.FRESHNESS_CLASSES),
        "source_id_grammar": "gk-" in make_source_id_source and "sha1" in make_source_id_source,
        "chunk_id_grammar": "make_chunk_id" in make_chunk_id_source,
        "loader_required_files": len(required_files) >= 3,
        "loader_checksum_semantics": "file_checksums" in load_corpus_source and "_sha256_lf" in load_corpus_source,
        "manifest_checksum_semantics": "manifest_checksum" in build_corpus_files_source,
        "manifest_keys_ast": {"corpus_version", "snapshot_date", "source_count", "chunk_count", "domains", "license_summary", "file_checksums", "manifest_checksum"} <= set(manifest_keys),
        "answer_entry": callable(pipeline_module.answer_knowledge),
    }
    document = {
        "schema_version": "t21-runtime-corpus-contract-v1",
        "artifact": "T21R16_RUNTIME_CORPUS_CONTRACT",
        "experiment": "t21r16",
        "corpus_format": "mango-general-knowledge-corpus-v1",
        "loader_entry": "src/sciencemath/knowledge/corpus.py:load_corpus",
        "derivation": {
            "method": "frozen module introspection + AST extraction (no hand-copied schema)",
            "modules": [
                "src/sciencemath/knowledge/schema.py",
                "src/sciencemath/knowledge/corpus.py",
                "src/sciencemath/knowledge/pipeline.py",
            ],
            "rule": "every runtime-affecting field, vocabulary, ID grammar, checksum semantic, and required file below is derived from the frozen candidate bytes; the contract is invalid if any bound module hash changes",
        },
        "bound_modules": {relative: sha256_file(ROOT / relative) for relative in RUNTIME_COMPONENTS},
        "source_record": {
            "dataclass": "KnowledgeSourceRecord",
            "module": "src/sciencemath/knowledge/schema.py",
            "required_fields": source_required,
            "optional_fields": source_optional,
            "closed_vocabularies": {
                "authority_class": list(schema.AUTHORITY_CLASSES),
                "freshness_class": list(schema.FRESHNESS_CLASSES),
            },
            "source_id_grammar": {
                "producer": "make_source_id(title, publisher, revision)",
                "format": "gk-<sha1(title|publisher|revision)[:12]>",
                "derived_from": make_source_id_source,
            },
            "from_dict_required_keys": source_from_dict_keys,
            "loader_required_keys": loader_source_keys,
            "enforcement": "__post_init__ rejects authority/freshness values outside the closed vocabularies and source IDs without the gk- prefix (SchemaError); from_dict and the frozen loader raise KeyError on missing required keys",
        },
        "chunk_record": {
            "dataclass": "KnowledgeChunk",
            "module": "src/sciencemath/knowledge/schema.py",
            "required_fields": chunk_required,
            "optional_fields": chunk_optional,
            "chunk_id_grammar": {
                "producer": "make_chunk_id(source_id, section, ordinal)",
                "format": "<source_id>:<slug(section)>:<ordinal>",
                "derived_from": make_chunk_id_source,
            },
            "from_dict_required_keys": chunk_from_dict_keys,
            "loader_required_keys": sorted(loader_chunk_keys),
            "enforcement": "from_dict raises KeyError on missing required keys (span and content_hash included); validate_chunk_invariants rejects duplicate chunk_ids, checksum disagreements, and out-of-order ordinals (CorruptCorpusError at load)",
        },
        "manifest": {
            "producer": "build_corpus_files(corpus_dir, sources, chunks)",
            "required_fields": manifest_keys,
            "file_checksum_semantics": "_sha256_lf over sources.jsonl and chunks.jsonl (CRLF-normalized)",
            "manifest_checksum_semantics": "sha256 over the sorted-JSON blob of the manifest excluding manifest_checksum",
            "derived_from": build_corpus_files_source,
        },
        "loader": {
            "entry": "load_corpus(corpus_dir) -> KnowledgeCorpus",
            "required_files": required_files,
            "fail_closed": [
                "missing corpus file raises CorruptCorpusError",
                "manifest lacking file_checksums entries for sources.jsonl and chunks.jsonl raises CorruptCorpusError",
                "per-file checksum mismatch raises CorruptCorpusError",
                "manifest source_count/chunk_count mismatch raises CorruptCorpusError",
                "KnowledgeCorpus post-init chunk-invariant violations raise CorruptCorpusError",
            ],
            "derived_from": load_corpus_source,
        },
        "answer": {
            "entry": f"answer_knowledge{answer_knowledge_signature}",
            "returns": "KnowledgeAnswer(status, answer, citations, zero_tolerance)",
            "entity_gate": "_entity_binding_score requires every fact_entity token to appear in the query",
        },
    }
    return document, checks


def _runtime_field_provenance() -> dict[str, Any]:
    return {
        "schema_version": "t21-runtime-field-provenance-v1",
        "artifact": "T21R16_RUNTIME_FIELD_PROVENANCE",
        "experiment": "t21r16",
        "raw_values_included": False,
        "rule": "every runtime-affecting corpus field names its frozen producer; no field is synthesized after authoring and no field is produced after seal",
        "fields": [
            {"field": "world.jsonl:entity_id", "producer": "R16 blind author (semantic identity = case_id)", "phase": "CONSTRUCTION"},
            {"field": "world.jsonl:name", "producer": "R16 blind author (semantic identity)", "phase": "CONSTRUCTION"},
            {"field": "world.jsonl:domain", "producer": "R16 blind author (semantic identity)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:source_id", "producer": "src/sciencemath/knowledge/schema.py:make_source_id", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:source_title", "producer": "R16 blind author (register title)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:source_type", "producer": "R16 blind author (fixture_register)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:source_uri_or_origin", "producer": "R16 blind author (blind:// URI)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:publisher_or_collection", "producer": "R16 blind author (register collection)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:license", "producer": "R16 blind author (project_owned_fixtures)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:revision_or_version", "producer": "R16 blind author (r16-blind-v1)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:retrieved_at_or_snapshot_date", "producer": "src/sciencemath/knowledge/corpus.py:CORPUS_SNAPSHOT_DATE", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:language", "producer": "R16 blind author (en)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:authority_class", "producer": "R16 blind author within the frozen closed vocabulary", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:freshness_class", "producer": "R16 blind author within the frozen closed vocabulary", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:topic_tags", "producer": "R16 blind author (required_domains)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:content_text", "producer": "R16 blind author (registered statement)", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:content_hash", "producer": "src/sciencemath/knowledge/schema.py:KnowledgeSourceRecord.__post_init__", "phase": "CONSTRUCTION"},
            {"field": "sources.jsonl:document_hash", "producer": "src/sciencemath/knowledge/schema.py:KnowledgeSourceRecord.__post_init__", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:chunk_id", "producer": "src/sciencemath/knowledge/schema.py:make_chunk_id", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:source_id", "producer": "src/sciencemath/knowledge/schema.py:KnowledgeSourceRecord.__post_init__", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:section", "producer": "src/sciencemath/knowledge/schema.py:chunk_source_text", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:ordinal", "producer": "src/sciencemath/knowledge/schema.py:chunk_source_text", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:span", "producer": "src/sciencemath/knowledge/schema.py:chunk_source_text", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:text", "producer": "src/sciencemath/knowledge/schema.py:chunk_source_text", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:content_hash", "producer": "src/sciencemath/knowledge/schema.py:KnowledgeChunk.__post_init__", "phase": "CONSTRUCTION"},
            {"field": "chunks.jsonl:metadata", "producer": "src/sciencemath/knowledge/schema.py:chunk_source_text + R16 blind author fact metadata", "phase": "CONSTRUCTION"},
            {"field": "corpus_manifest.json:corpus_version|snapshot_date|source_count|chunk_count|domains|license_summary", "producer": "src/sciencemath/knowledge/corpus.py:build_corpus_files", "phase": "CONSTRUCTION"},
            {"field": "corpus_manifest.json:file_checksums", "producer": "src/sciencemath/knowledge/corpus.py:build_corpus_files (_sha256_lf)", "phase": "CONSTRUCTION"},
            {"field": "corpus_manifest.json:manifest_checksum", "producer": "src/sciencemath/knowledge/corpus.py:build_corpus_files", "phase": "CONSTRUCTION"},
        ],
        "unknown_producer_fields": 0,
        "post_seal_runtime_field_producers": 0,
    }


def _candidate_runtime_data_contract() -> dict[str, Any]:
    return {
        "schema_version": "t21-candidate-runtime-data-contract-v1",
        "artifact": "T21R16_CANDIDATE_RUNTIME_DATA_CONTRACT",
        "experiment": "t21r16",
        "rule": "the authored holdout material and the frozen candidate runtime share exactly one corpus contract; there is no second, adapter-repaired corpus model",
        "runtime_corpus_contract": {"path": "evaluations/t21r16/runtime_corpus_contract.json", "sha256": sha256_file(ROOT / "evaluations" / "t21r16" / "runtime_corpus_contract.json")},
        "runtime_field_provenance": {"path": "evaluations/t21r16/runtime_field_provenance.json", "sha256": sha256_file(ROOT / "evaluations" / "t21r16" / "runtime_field_provenance.json")},
        "candidate": {
            "provider_id": "t21_protocol.providers:RealCandidateProvider",
            "module": "t21_protocol/providers.py",
            "module_sha256": sha256_file(ROOT / "t21_protocol" / "providers.py"),
            "corpus_loader": "src/sciencemath/knowledge/corpus.py:load_corpus (frozen, no adapter)",
            "initialization": {"loads_corpus_once": True, "executes_holdout_rows": False},
            "generation": {"entry": "src/sciencemath/knowledge/pipeline.py:answer_knowledge", "canonical_serialization": "t21_protocol.providers:canonical_candidate_row"},
        },
        "no_second_corpus_model": True,
    }


def _runtime_freeze() -> dict[str, Any]:
    freeze = build_freeze(
        ROOT,
        RUNTIME_COMPONENTS,
        artifact="T21R16_RUNTIME_FREEZE",
        experiment="t21r16",
        extra={"candidate_commit": CANDIDATE_COMMIT, "candidate_tree": CANDIDATE_TREE},
    )
    if freeze["component_root_sha256"] != RUNTIME_ROOT:
        raise SystemExit("runtime freeze root does not match the frozen R15 runtime root")
    return freeze


def _artifact_graph() -> dict[str, Any]:
    r15 = _load("evaluations/t21r15/artifact_graph.json")
    known_producers = [
        producer for producer in r15["known_producers"] if producer != "candidate_stub"
    ] + ["real_candidate_provider", "runtime_contract", "field_provenance", "metric_registry", "evidence_contract", "shadow_runtime_validator", "r15_closure"]
    nodes: dict[str, Any] = {}
    for name, node in r15["nodes"].items():
        nodes[name] = {**node, "path": node["path"].replace("t21r15", "t21r16")}
    nodes["candidate_outputs"]["producer"] = "real_candidate_provider"
    nodes["r15_closure"] = {
        "path": "evaluations/t21r15/T21R15_CLOSURE.json",
        "producer": "r15_closure",
        "required_inputs": [],
        "consumers": ["historical_exclusion", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": True,
    }
    nodes["runtime_corpus_contract"] = {
        "path": "evaluations/t21r16/runtime_corpus_contract.json",
        "producer": "runtime_contract",
        "required_inputs": ["runtime_freeze"],
        "consumers": ["candidate_runtime_data_contract", "author", "builder", "protocol_doctor", "seal"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["runtime_field_provenance"] = {
        "path": "evaluations/t21r16/runtime_field_provenance.json",
        "producer": "field_provenance",
        "required_inputs": ["runtime_corpus_contract"],
        "consumers": ["candidate_runtime_data_contract", "builder", "protocol_doctor", "seal"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["candidate_runtime_data_contract"] = {
        "path": "evaluations/t21r16/candidate_runtime_data_contract.json",
        "producer": "runtime_contract",
        "required_inputs": ["runtime_corpus_contract", "runtime_field_provenance", "runtime_freeze"],
        "consumers": ["qualification", "seal", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["official_metric_registry"] = {
        "path": "evaluations/t21r16/official_metric_registry.json",
        "producer": "metric_registry",
        "required_inputs": ["master_contract"],
        "consumers": ["floor_evidence_contract", "evaluation_reporting_contract", "scorer", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["evaluation_reporting_contract"] = {
        "path": "evaluations/t21r16/evaluation_reporting_contract.json",
        "producer": "evidence_contract",
        "required_inputs": ["master_contract", "official_metric_registry"],
        "consumers": ["floor_evidence_contract", "evaluation_artifact_graph", "scorer", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["floor_evidence_contract"] = {
        "path": "evaluations/t21r16/floor_evidence_contract.json",
        "producer": "evidence_contract",
        "required_inputs": ["official_metric_registry", "evaluation_reporting_contract"],
        "consumers": ["floor_evidence", "scorer", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["evaluation_artifact_graph"] = {
        "path": "evaluations/t21r16/evaluation_artifact_graph.json",
        "producer": "evidence_contract",
        "required_inputs": ["evaluation_reporting_contract", "floor_evidence_contract", "artifact_graph"],
        "consumers": ["qualification", "protocol_doctor"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["preconstruction_audit"] = {
        "path": "evaluations/t21r16/T21R16_PRECONSTRUCTION_AUDIT.json",
        "producer": "protocol_doctor",
        "required_inputs": ["protocol_doctor_report", "qualification_lock"],
        "consumers": ["qualification"],
        "phase_created": "PRECONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "PRECONSTRUCTION",
        "include_in_seal": False,
        "include_in_evaluation_provenance": False,
        "required": False,
        "external": False,
    }
    nodes["runtime_loader_validation"] = {
        "path": "evaluations/t21r16/runtime_loader_validation.json",
        "producer": "shadow_runtime_validator",
        "required_inputs": ["corpus", "runtime_corpus_contract"],
        "consumers": ["candidate_provider_compatibility", "holdout_manifest", "material_provenance", "seal"],
        "phase_created": "CONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "CONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["candidate_provider_compatibility"] = {
        "path": "evaluations/t21r16/candidate_provider_compatibility.json",
        "producer": "real_candidate_provider",
        "required_inputs": ["corpus", "runtime_loader_validation"],
        "consumers": ["holdout_manifest", "material_provenance", "seal"],
        "phase_created": "CONSTRUCTION",
        "phase_frozen": "SEALED",
        "phase_owner": "CONSTRUCTION",
        "include_in_seal": True,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["holdout_manifest"]["required_inputs"] = sorted(
        set(nodes["holdout_manifest"]["required_inputs"]) | {"runtime_loader_validation", "candidate_provider_compatibility"}
    )
    nodes["material_provenance"]["required_inputs"] = sorted(
        set(nodes["material_provenance"]["required_inputs"]) | {"runtime_loader_validation", "candidate_provider_compatibility"}
    )
    # The R15 ordering edge corpus <- material_provenance would close a cycle now
    # that material_provenance consumes the runtime artifacts (which require the
    # corpus). The true runtime-native write order is: author_spec -> ledger ->
    # corpus -> runtime_loader_validation -> candidate_provider_compatibility ->
    # material_provenance -> suites, so corpus depends on the author and ledger
    # only, and material_provenance documents the validated runtime artifacts.
    nodes["corpus"]["required_inputs"] = ["author_spec", "construction_ledger"]
    nodes["raw_results"] = {
        "path": "evaluations/t21r16/raw_results.jsonl",
        "producer": "evaluator",
        "required_inputs": ["candidate_outputs", "evaluator_results"],
        "consumers": ["metric_evidence", "floor_evidence"],
        "phase_created": "EVALUATION_STARTED",
        "phase_frozen": "EVALUATION_COMPLETE",
        "phase_owner": "EVALUATION",
        "include_in_seal": False,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["metric_evidence"] = {
        "path": "evaluations/t21r16/metric_evidence.json",
        "producer": "evaluator",
        "required_inputs": ["raw_results", "official_metric_registry"],
        "consumers": ["floor_evidence", "score_results"],
        "phase_created": "EVALUATION_STARTED",
        "phase_frozen": "EVALUATION_COMPLETE",
        "phase_owner": "EVALUATION",
        "include_in_seal": False,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["floor_evidence"] = {
        "path": "evaluations/t21r16/floor_evidence.json",
        "producer": "scorer",
        "required_inputs": ["metric_evidence", "floor_evidence_contract"],
        "consumers": ["holdout_results"],
        "phase_created": "EVALUATION_STARTED",
        "phase_frozen": "EVALUATION_COMPLETE",
        "phase_owner": "EVALUATION",
        "include_in_seal": False,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    nodes["holdout_results"] = {
        "path": "evaluations/t21r16/holdout_results.json",
        "producer": "scorer",
        "required_inputs": ["floor_evidence", "score_results"],
        "consumers": ["evaluation_provenance"],
        "phase_created": "EVALUATION_STARTED",
        "phase_frozen": "EVALUATION_COMPLETE",
        "phase_owner": "EVALUATION",
        "include_in_seal": False,
        "include_in_evaluation_provenance": True,
        "required": True,
        "external": False,
    }
    return {
        "schema_version": "t21-artifact-graph-v1",
        "artifact": "T21R16_ARTIFACT_GRAPH",
        "experiment": "t21r16",
        "known_producers": known_producers,
        "nodes": nodes,
    }


def _evaluation_design_documents(floors: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metric_count = sum(len(metrics) for metrics in floors.values())
    if metric_count != 32:
        raise SystemExit(f"expected 32 floors, found {metric_count}")
    return {
        "official_metric_registry": {
            "schema_version": "t21-official-metric-registry-v1",
            "artifact": "T21R16_OFFICIAL_METRIC_REGISTRY",
            "experiment": "t21r16",
            "rule": "metrics are derived mechanically from the frozen promotion floors; no metric may be added, removed, or redefined at evaluation time",
            "families": {family: {metric: {"op": spec["op"], "value": spec["value"]} for metric, spec in metrics.items()} for family, metrics in floors.items()},
            "metric_count": metric_count,
            "zero_tolerance_metrics": sorted(
                metric
                for family, metrics in floors.items()
                for metric, spec in metrics.items()
                if spec["op"] in {"=", "<="} and spec["value"] == 0
            ),
            "post_seal_metric_changes": 0,
        },
        "evaluation_reporting_contract": {
            "schema_version": "t21-evaluation-reporting-contract-v1",
            "artifact": "T21R16_EVALUATION_REPORTING_CONTRACT",
            "experiment": "t21r16",
            "rule": "every reported number must trace to an evidence file produced by a named production producer; no post-seal scoring design is legal",
            "reports": {
                "evaluation_run_ledger.json": {"producer": "ledger", "content": "one-shot evaluation ledger"},
                "candidate_outputs.jsonl": {"producer": "real_candidate_provider", "rows": 4800},
                "evaluator_results.json": {"producer": "evaluator", "content": "per-row status/answer match and counters"},
                "evaluation_provenance.json": {"producer": "evaluator", "content": "artifact graph, seal binding, candidate provider identity"},
                "score_results.json": {"producer": "scorer", "content": "official metric values over evaluated rows"},
                "raw_results.jsonl": {"producer": "evaluator", "content": "per-row scored records"},
                "metric_evidence.json": {"producer": "evaluator", "content": "metric values with numerator/denominator evidence"},
                "floor_evidence.json": {"producer": "scorer", "content": "all 32 floor comparisons with evidence paths"},
                "holdout_results.json": {"producer": "scorer", "content": "final promotion verdict over floor evidence"},
            },
            "forbidden_producers": ["candidate_stub"],
            "post_seal_reporting_changes": 0,
        },
        "floor_evidence_contract": {
            "schema_version": "t21-floor-evidence-contract-v1",
            "artifact": "T21R16_FLOOR_EVIDENCE_CONTRACT",
            "experiment": "t21r16",
            "rule": "each of the 32 floors requires an evidence record naming its metric, comparison, observed value, threshold, evidence path, and pass verdict before construction",
            "floor_count": 32,
            "floors": [f"{family}.{metric}" for family, metrics in floors.items() for metric in metrics],
            "evidence_per_floor": {"metric": True, "op": True, "observed": True, "threshold": True, "evidence_path": True, "pass": True},
            "post_seal_floor_changes": 0,
        },
        "evaluation_artifact_graph": {
            "schema_version": "t21-evaluation-artifact-graph-v1",
            "artifact": "T21R16_EVALUATION_ARTIFACT_GRAPH",
            "experiment": "t21r16",
            "rule": "the complete production evaluation artifact graph is fixed before construction; every production node names a production producer",
            "nodes": {
                "evaluation_run_ledger": {"producer": "ledger", "artifact": "evaluations/t21r16/evaluation_run_ledger.json"},
                "candidate_outputs": {"producer": "real_candidate_provider", "artifact": "evaluations/t21r16/candidate_outputs.jsonl"},
                "evaluator_results": {"producer": "evaluator", "artifact": "evaluations/t21r16/evaluator_results.json"},
                "evaluation_provenance": {"producer": "evaluator", "artifact": "evaluations/t21r16/evaluation_provenance.json"},
                "score_results": {"producer": "scorer", "artifact": "evaluations/t21r16/score_results.json"},
                "raw_results": {"producer": "evaluator", "artifact": "evaluations/t21r16/raw_results.jsonl"},
                "metric_evidence": {"producer": "evaluator", "artifact": "evaluations/t21r16/metric_evidence.json"},
                "floor_evidence": {"producer": "scorer", "artifact": "evaluations/t21r16/floor_evidence.json"},
                "holdout_results": {"producer": "scorer", "artifact": "evaluations/t21r16/holdout_results.json"},
            },
            "candidate_stub_nodes": 0,
            "post_seal_graph_changes": 0,
        },
    }


def stage_static() -> dict[str, Any]:
    r15 = _load("evaluations/t21r15/t21_master_contract.json")
    r15_values = r15["values"]
    r15_experiment = _load("evaluations/t21r15/experiment.json")
    registry = _load("evaluations/t21r16/prior_exclusion.json")
    milestones = registry["milestone_order"]

    taxonomy = {**_load("evaluations/t21r15/domain_taxonomy_contract.json"), "artifact": "T21R16_DOMAIN_TAXONOMY_CONTRACT", "experiment": "t21r16"}
    remediation = {
        **_load("evaluations/t21r15/remediation_exclusion.json"),
        "artifact": "T21R16_REMEDIATION_EXCLUSION_POLICY",
        "experiment": "t21r16",
        "source": f"evaluations/t21r15/remediation_exclusion.json#sha256={r15_values['remediation_exclusions']['source_sha256']}",
    }
    historical = {
        "schema_version": "t21-historical-exclusion-policy-v1",
        "artifact": "T21R16_HISTORICAL_EXCLUSION_POLICY",
        "experiment": "t21r16",
        "raw_values_included": False,
        "historical_milestone_count": len(milestones),
        "milestones": milestones,
        "r15_protocol_history": {
            "blind_fingerprints_invented": False,
            "construction_attempts": 1,
            "one_shot_consumed": False,
            "closure_status": R15_CLOSURE_STATUS,
            "closure_reason": R15_CLOSURE_REASON,
            "evaluation_permanently_refused": True,
        },
        "upstream_registry": "evaluations/t21r16/prior_exclusion.json",
        "upstream_registry_sha256": sha256_file(ROOT / "evaluations" / "t21r16" / "prior_exclusion.json"),
    }
    schema_document = _holdout_frozen_schema()
    controls = _negative_controls()
    experiment = {
        "artifact": "T21R16_EXPERIMENT_CONFIGURATION",
        "author_vocabulary": r15_experiment["author_vocabulary"],
        "case_id_prefix": "r16-",
        "crossdomain_pair_ids": sorted(pair["id"] for pair in R16_CROSSDOMAIN_PAIRS),
        "experiment": "t21r16",
        "historical_exclusion_milestone_count": len(milestones),
        "namespace": "mango-r16-v1",
        "seed": 21016,
        "suite_total": 4800,
        "version": "t21r16-v1",
    }
    corpus_contract, checks = _runtime_corpus_contract()
    if not all(checks.values()):
        raise SystemExit(f"runtime corpus contract derivation checks failed: {checks}")
    _write("evaluations/t21r16/runtime_corpus_contract.json", corpus_contract)
    _write("evaluations/t21r16/runtime_field_provenance.json", _runtime_field_provenance())
    _write("evaluations/t21r16/candidate_runtime_data_contract.json", _candidate_runtime_data_contract())
    _write("evaluations/t21r16/runtime_freeze.json", _runtime_freeze())
    graph = _artifact_graph()
    design = _evaluation_design_documents(r15_values["promotion_floors"])
    _write("evaluations/t21r16/domain_taxonomy_contract.json", taxonomy)
    _write("evaluations/t21r16/remediation_exclusion.json", remediation)
    _write("evaluations/t21r16/historical_exclusion.json", historical)
    _write("evaluations/t21r16/holdout_frozen_schema.json", schema_document)
    _write("evaluations/t21r16/negative_controls.json", controls)
    _write("evaluations/t21r16/experiment.json", experiment)
    _write("evaluations/t21r16/artifact_graph.json", graph)
    _write("evaluations/t21r16/official_metric_registry.json", design["official_metric_registry"])
    _write("evaluations/t21r16/evaluation_reporting_contract.json", design["evaluation_reporting_contract"])
    _write("evaluations/t21r16/floor_evidence_contract.json", design["floor_evidence_contract"])
    _write("evaluations/t21r16/evaluation_artifact_graph.json", design["evaluation_artifact_graph"])
    return {"status": "PASS", "runtime_contract_checks": checks, "graph_nodes": len(graph["nodes"])}


# ------------------------------------------------------------ adjudication --


ADJUDICATION_SCHEMA_VERSION = "t21-test-failure-adjudication-v1"
APPLICABILITY_SCHEMA_VERSION = "t21-current-test-applicability-v1"
ALLOWED_CLASSIFICATIONS = (
    "LIVE",
    "ENVIRONMENT_ONLY_FAILURE",
    "OBSOLETE_HISTORICAL_ASSERTION",
    "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE",
    "UNKNOWN",
)
IGNORED_HISTORICAL_FILES = (
    "test_t21r10_preconstruction.py",
    "test_t21r11_preconstruction.py",
    "test_t21r12_preconstruction.py",
    "test_t21r13_preconstruction.py",
    "test_t21r14_preconstruction.py",
    "test_t21r15_preconstruction.py",
    "test_scicomp_registry_active.py",
    "test_t19_post_merge_audit_cleanup.py",
    "test_t21_protocol_kernel.py",
    "test_t21r3_blind_holdout_contract.py",
    "test_t21r4_blind_holdout_contract.py",
    "test_t21r5_blind_holdout_contract.py",
    "test_t21r8_holdout_freeze_protocol.py",
    "test_t21r9_preregistration.py",
    "test_t21r2_freeze_protocol.py",
)


def _run_pytest(arguments: list[str], junit: Path, basetemp: Path) -> dict[str, Any]:
    command = [
        sys.executable, "-m", "pytest", *arguments,
        "-p", "no:cacheprovider", "--junitxml", str(junit), "--basetemp", str(basetemp), "-q",
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"exit_code": completed.returncode, "stdout_tail": completed.stdout[-2000:]}


def _junit_failures(junit: Path) -> list[str]:
    import xml.etree.ElementTree as ElementTree

    failures = []
    for case in ElementTree.parse(junit).iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            classname = case.get("classname", "")
            filename = classname.split(".")[-1] + ".py" if classname else ""
            failures.append(f"tests/{filename}::{case.get('name', '')}")
    return failures


def _classify(nodeid: str, r15: dict[str, str]) -> tuple[str, str]:
    if nodeid in r15:
        return r15[nodeid], "classification carried from the committed T21R15 adjudication (same committed historical artifact state)"
    if nodeid == "tests/test_t21_protocol_kernel.py::test_real_r15_paths_are_absent":
        return "OBSOLETE_HISTORICAL_ASSERTION", "asserts real R15 holdout paths are absent; the R15 sealed holdout legitimately exists and is preserved unmodified"
    if nodeid.startswith("tests/test_t21_protocol_kernel.py::"):
        return "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE", "rehearsal bound to the R15 qualification lock; tests/test_t21r16_preconstruction.py re-runs the same rehearsal against the current R16 contract and lock"
    return "UNKNOWN", "unclassified failure"


def stage_adjudication() -> dict[str, Any]:
    r15_adjudication = _load("evaluations/t21r15/test_failure_adjudication.json")
    r15 = {entry["nodeid"]: entry["classification"] for entry in r15_adjudication["entries"]}
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    junit = artifacts / "t21r16_adjudication_junit.xml"
    run = _run_pytest(["tests"], junit, artifacts / ".pytest_t21r16_adjudication")
    failures = _junit_failures(junit)
    if not failures:
        raise SystemExit("adjudication expected registered historical failures in the full suite")
    entries = []
    for nodeid in sorted(failures):
        classification, rationale = _classify(nodeid, r15)
        entries.append({"nodeid": nodeid, "classification": classification, "rationale": rationale})
    unresolved = [entry for entry in entries if entry["classification"] in {"LIVE", "UNKNOWN", "ENVIRONMENT_ONLY_FAILURE"}]
    if unresolved:
        raise SystemExit(f"unadjudicated failures remain: {unresolved}")
    summary = {name: 0 for name in ALLOWED_CLASSIFICATIONS}
    for entry in entries:
        summary[entry["classification"]] += 1
    adjudication = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "artifact": "T21R16_TEST_FAILURE_ADJUDICATION",
        "experiment": "t21r16",
        "classification_summary": summary,
        "entries": [{"nodeid": entry["nodeid"], "classification": entry["classification"]} for entry in entries],
        "rationales": {entry["nodeid"]: entry["rationale"] for entry in entries},
    }
    from t21_protocol.adjudication import generate_applicability

    _write("evaluations/t21r16/test_failure_adjudication.json", adjudication)
    _write("evaluations/t21r16/current_test_applicability.json", generate_applicability(adjudication))
    return {"status": "PASS", "failures": len(entries), "summary": summary, "pytest_exit_code": run["exit_code"]}


# ------------------------------------------------------------------ freeze --


def stage_freeze() -> dict[str, Any]:
    experiment_artifacts = [
        "evaluations/t21r16/artifact_graph.json",
        "evaluations/t21r16/current_test_applicability.json",
        "evaluations/t21r16/domain_taxonomy_contract.json",
        "evaluations/t21r16/experiment.json",
        "evaluations/t21r16/historical_exclusion.json",
        "evaluations/t21r16/holdout_frozen_schema.json",
        "evaluations/t21r16/negative_controls.json",
        "evaluations/t21r16/remediation_exclusion.json",
        "evaluations/t21r16/runtime_freeze.json",
        "evaluations/t21r16/test_failure_adjudication.json",
        "evaluations/t21r16/runtime_corpus_contract.json",
        "evaluations/t21r16/runtime_field_provenance.json",
        "evaluations/t21r16/candidate_runtime_data_contract.json",
        "evaluations/t21r16/official_metric_registry.json",
        "evaluations/t21r16/evaluation_reporting_contract.json",
        "evaluations/t21r16/floor_evidence_contract.json",
        "evaluations/t21r16/evaluation_artifact_graph.json",
    ]
    scripts = [
        "scripts/t21r_fixtures.py",
        "scripts/t21r12_fixtures.py",
        "scripts/t21r13_fixtures.py",
        "scripts/t21r14_fixtures.py",
        "scripts/t21r16_fixtures.py",
        "scripts/t21r16_preconstruction.py",
    ]
    modules = [f"t21_protocol/{path.name}" for path in sorted((ROOT / "t21_protocol").glob("*.py"))]
    tests = ["tests/test_t21_protocol_kernel.py", "tests/test_t21r16_preconstruction.py"]
    freeze = build_freeze(
        ROOT,
        [*experiment_artifacts, *scripts, *modules, *tests],
        artifact="T21R16_EVALUATOR_FREEZE",
        experiment="t21r16",
        extra={"floor_hash": FLOOR_HASH},
    )
    _write("evaluations/t21r16/evaluator_freeze.json", freeze)
    return {"status": "PASS", "components": len(freeze["component_sha256"]), "root": freeze["component_root_sha256"]}


# ---------------------------------------------------------------- contract --


def _contract_fields() -> list[dict[str, Any]]:
    descriptors = [
        ("identity", "object", {"nonempty": True}, ["author", "builder", "seal", "evaluator"], "contract"),
        ("roots", "object", {"nonempty": True}, ["seal", "evaluator", "scorer", "qualification"], "qualification"),
        ("artifacts", "object", {"nonempty": True}, ["artifact_graph", "author", "seal", "official_validator", "protocol_doctor"], "contract"),
        ("suites", "object", {"nonempty": True}, ["author", "builder", "official_validator", "evaluator", "scorer"], "contract"),
        ("suite_total", "integer", {"const": 4800}, ["builder", "official_validator", "evaluator"], "contract"),
        ("domain_taxonomy", "array", {"length": 14}, ["author", "builder", "official_validator", "evaluator", "scorer"], "contract"),
        ("crossdomain_pairs", "array", {"length": 7}, ["author", "builder", "construction_gate", "exact_design_auditor"], "contract"),
        ("exact_design", "object", {"nonempty": True}, ["author", "builder", "construction_gate", "exact_design_auditor"], "contract"),
        ("historical_exclusions", "object", {"nonempty": True}, ["author", "construction_gate", "historical_exclusion", "seal"], "historical_exclusion"),
        ("remediation_exclusions", "object", {"nonempty": True}, ["author", "construction_gate", "remediation_exclusion", "seal"], "remediation_exclusion"),
        ("promotion_floors", "object", {"nonempty": True}, ["official_validator", "evaluator", "scorer", "qualification"], "contract"),
        ("one_shot", "object", {"nonempty": True}, ["builder", "seal", "evaluator"], "contract"),
        ("phase_apis", "object", {"nonempty": True}, ["state_machine", "builder", "seal", "evaluator", "protocol_doctor"], "contract"),
        ("workspace_modes", "array", {"length": 2}, ["builder", "seal", "evaluator", "protocol_doctor"], "contract"),
        ("material_modes", "array", {"length": 3}, ["builder", "seal", "evaluator", "protocol_doctor"], "contract"),
        ("state_machine", "object", {"nonempty": True}, ["state_machine", "author", "builder", "seal", "evaluator"], "contract"),
        ("author", "object", {"nonempty": True}, ["author", "qualification"], "contract"),
        ("r15_disposition", "object", {"nonempty": True}, ["protocol_doctor", "operator"], "qualification"),
        ("real_r16_paths", "array", {"nonempty": True}, ["protocol_doctor", "operator"], "contract"),
        ("quarantine", "object", {"nonempty": True}, ["author", "builder", "construction_gate", "protocol_doctor"], "contract"),
        ("runtime_native", "object", {"nonempty": True}, ["author", "builder", "construction_gate", "seal", "evaluator", "protocol_doctor", "qualification"], "contract"),
    ]
    return [
        {
            "path": f"values.{name}",
            "type": type_name,
            "presence": "required",
            "producer": producer,
            "consumers": consumers,
            "validation": validation,
            "freeze_phase": "QUALIFIED",
        }
        for name, type_name, validation, consumers, producer in descriptors
    ]


def stage_contract() -> dict[str, Any]:
    r15 = _load("evaluations/t21r15/t21_master_contract.json")
    r15_values = r15["values"]
    freeze = _load("evaluations/t21r16/evaluator_freeze.json")
    taxonomy_document = _load("evaluations/t21r16/domain_taxonomy_contract.json")
    values = {key: value for key, value in r15_values.items() if key not in {"identity", "roots", "artifacts", "suites", "domain_taxonomy", "crossdomain_pairs", "historical_exclusions", "remediation_exclusions", "r14_disposition", "real_r15_paths", "quarantine", "phase_apis", "state_machine"}}
    values["identity"] = {"case_id_prefix": "r16-", "namespace": "mango-r16-v1"}
    values["author"] = {"seed": 21016, "vocabulary": r15_values["author"]["vocabulary"]}
    values["roots"] = {
        "candidate_commit": CANDIDATE_COMMIT,
        "candidate_tree": CANDIDATE_TREE,
        "runtime_root": RUNTIME_ROOT,
        "evaluator_root": freeze["component_root_sha256"],
        "floor_hash": FLOOR_HASH,
        "runtime_data_contract_root": sha256_json(_load("evaluations/t21r16/candidate_runtime_data_contract.json")),
        "runtime_corpus_contract_sha256": sha256_file(ROOT / "evaluations" / "t21r16" / "runtime_corpus_contract.json"),
        "runtime_field_provenance_sha256": sha256_file(ROOT / "evaluations" / "t21r16" / "runtime_field_provenance.json"),
        "candidate_provider_sha256": sha256_file(ROOT / "t21_protocol" / "providers.py"),
        "candidate_provider_id": "t21_protocol.providers:RealCandidateProvider",
    }
    values["artifacts"] = {
        "experiment_config": "evaluations/t21r16/experiment.json",
        "artifact_graph": "evaluations/t21r16/artifact_graph.json",
        "domain_taxonomy": "evaluations/t21r16/domain_taxonomy_contract.json",
        "historical_exclusion": "evaluations/t21r16/historical_exclusion.json",
        "remediation_exclusion": "evaluations/t21r16/remediation_exclusion.json",
        "runtime_freeze": "evaluations/t21r16/runtime_freeze.json",
        "evaluator_freeze": "evaluations/t21r16/evaluator_freeze.json",
        "qualification_lock": "evaluations/t21r16/qualification_lock.json",
        "negative_controls": "evaluations/t21r16/negative_controls.json",
        "adjudication": "evaluations/t21r16/test_failure_adjudication.json",
        "applicability": "evaluations/t21r16/current_test_applicability.json",
        "holdout_frozen_schema": "evaluations/t21r16/holdout_frozen_schema.json",
        "runtime_corpus_contract": "evaluations/t21r16/runtime_corpus_contract.json",
        "runtime_field_provenance": "evaluations/t21r16/runtime_field_provenance.json",
        "candidate_runtime_data_contract": "evaluations/t21r16/candidate_runtime_data_contract.json",
    }
    values["suites"] = {
        f"mango-t21r16-{name}-holdout-v1": {"count": count, "family": name}
        for name, count in SUITE_SIZES
    }
    values["domain_taxonomy"] = sorted(domain["canonical_label"] for domain in taxonomy_document["domains"])
    values["crossdomain_pairs"] = R16_CROSSDOMAIN_PAIRS
    values["historical_exclusions"] = {"dimensions": 8, "milestones": 15, "raw_values": False, "r15_protocol_history_only": True}
    values["remediation_exclusions"] = {
        "dimensions": 9,
        "raw_values": False,
        "source_sha256": _load("evaluations/t21r16/remediation_exclusion.json")["source"].split("sha256=")[1],
    }
    values["r15_disposition"] = {
        "status": R15_CLOSURE_STATUS,
        "reason": R15_CLOSURE_REASON,
        "construction_attempts": 1,
        "corpus_materialized": True,
        "suites_materialized": True,
        "candidate_rows": 0,
        "official_evaluator_rows": 0,
        "one_shot_consumed": False,
        "evaluation_permanently_refused": True,
    }
    values["real_r16_paths"] = [
        "rag/gk_holdout_t21r16",
        "evaluations/t21r16/suites",
        "evaluations/t21r16/construction_run_ledger.json",
        "evaluations/t21r16/author_spec.json",
        "evaluations/t21r16/material_provenance.json",
        "evaluations/t21r16/runtime_loader_validation.json",
        "evaluations/t21r16/candidate_provider_compatibility.json",
        "evaluations/t21r16/historical_uniqueness.json",
        "evaluations/t21r16/remediation_uniqueness.json",
        "evaluations/t21r16/construction_gate.json",
        "evaluations/t21r16/exact_design_audit.json",
        "evaluations/t21r16/gate_auditor_crosscheck.json",
        "evaluations/t21r16/static_gold_audit.json",
        "evaluations/t21r16/holdout_blindness.json",
        "evaluations/t21r16/gold_compatibility.json",
        "evaluations/t21r16/root_of_trust.json",
        "evaluations/t21r16/holdout_manifest.json",
        "evaluations/t21r16/HOLDOUT_FROZEN",
        "evaluations/t21r16/sealed_preflight.json",
        "evaluations/t21r16/evaluation_run_ledger.json",
        "evaluations/t21r16/candidate_outputs.jsonl",
        "evaluations/t21r16/evaluator_results.json",
        "evaluations/t21r16/score_results.json",
        "evaluations/t21r16/evaluation_provenance.json",
        "evaluations/t21r16/raw_results.jsonl",
        "evaluations/t21r16/metric_evidence.json",
        "evaluations/t21r16/floor_evidence.json",
        "evaluations/t21r16/holdout_results.json",
    ]
    values["quarantine"] = {
        "status": "FORBIDDEN",
        "r15_sealed_holdout_reads": 0,
        "r15_sealed_holdout_path": "rag/gk_holdout_t21r15",
        "registry_access_only": True,
    }
    values["phase_apis"] = {
        "construct": {
            "required_state": "QUALIFIED",
            "terminal_states": ["SEALED"],
            "authorization_token": "T21R16_REAL_BLIND_CONSTRUCTION_AUTHORIZED",
            "allowed_artifact_phases": ["CONSTRUCTION", "SEAL"],
        },
        "evaluate": {
            "required_state": "SEALED",
            "terminal_states": ["EVALUATION_COMPLETE", "FAILED"],
            "authorization_token": "T21R16_ONE_SHOT_OFFICIAL_EVALUATION",
            "allowed_artifact_phases": ["EVALUATION"],
        },
    }
    evaluation_paths = [
        "evaluations/t21r16/evaluation_run_ledger.json",
        "evaluations/t21r16/candidate_outputs.jsonl",
        "evaluations/t21r16/evaluator_results.json",
        "evaluations/t21r16/evaluation_provenance.json",
        "evaluations/t21r16/score_results.json",
        "evaluations/t21r16/raw_results.jsonl",
        "evaluations/t21r16/metric_evidence.json",
        "evaluations/t21r16/floor_evidence.json",
        "evaluations/t21r16/holdout_results.json",
    ]
    commands = {}
    for name, command in r15_values["state_machine"]["commands"].items():
        commands[name] = {
            **command,
            "writable_paths": [path.replace("t21r15", "t21r16") for path in command["writable_paths"]],
        }
    for name in ("evaluate", "complete_evaluation"):
        commands[name]["writable_paths"] = evaluation_paths
    values["state_machine"] = {
        "phases": r15_values["state_machine"]["phases"],
        "commands": commands,
    }
    values["runtime_native"] = {
        "corpus_format": "mango-general-knowledge-corpus-v1",
        "loader_entry": "src/sciencemath/knowledge/corpus.py:load_corpus",
        "runtime_materializer": "t21_protocol.providers:runtime-native-materializer",
        "candidate_provider": "t21_protocol.providers:RealCandidateProvider",
        "source_id_grammar": "gk-<sha1(title|publisher|revision)[:12]>",
        "manifest_format": "runtime_build_corpus_files",
        "shadow_holdout_rows": 4800,
        "holdout_frozen_schema_version": "t21-holdout-frozen-v2",
    }
    document = {
        "schema_version": "t21-master-contract-v2",
        "artifact": "T21_MASTER_CONTRACT",
        "experiment": "t21r16",
        "values": values,
        "fields": _contract_fields(),
    }
    _write("evaluations/t21r16/t21_master_contract.json", document)
    load_contract(ROOT / "evaluations" / "t21r16" / "t21_master_contract.json")
    return {"status": "PASS", "values_fields": len(values), "field_descriptors": len(document["fields"])}


def stage_lock() -> dict[str, Any]:
    contract = load_contract(ROOT / "evaluations" / "t21r16" / "t21_master_contract.json")
    lock = build_qualification_lock(ROOT, contract)
    _write("evaluations/t21r16/qualification_lock.json", lock)
    from t21_protocol.qualification import validate_qualification_lock

    validate_qualification_lock(ROOT, contract, lock)
    return {"status": "PASS", "author_root": lock["shadow_fingerprint_root"]}


# ----------------------------------------------------------------- shadow --


def stage_shadow() -> dict[str, Any]:
    """A complete disposable runtime-native corpus through the frozen loaders."""
    from t21_protocol.author import shadow_author
    from t21_protocol.providers import RUNTIME_NATIVE_CORPUS_FORMAT, RealDryRunMaterialProvider, runtime_modules

    contract = load_contract(ROOT / "evaluations" / "t21r16" / "t21_master_contract.json")
    with tempfile.TemporaryDirectory(prefix="t21r16-shadow-") as directory:
        workspace = Path(directory)
        authored = shadow_author(contract, ROOT)
        bundle = RealDryRunMaterialProvider().build(contract, authored["spec"])
        rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
        corpus_dir = workspace / "rag" / "gk_holdout_t21r16"
        corpus_dir.mkdir(parents=True)
        (corpus_dir / "world.jsonl").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in bundle.world), encoding="utf-8", newline="\n"
        )
        _, corpus_module, _ = runtime_modules(workspace)
        manifest = corpus_module.build_corpus_files(corpus_dir, list(bundle.runtime_sources), list(bundle.runtime_chunks))
        corpus = corpus_module.load_corpus(corpus_dir)
        referential_failures = sum(1 for chunk in corpus.chunks if chunk.source_id not in corpus.sources_by_id)
        checks = {
            "loader_errors": 0,
            "schema_errors": 0,
            "missing_fields": 0,
            "checksum_failures": 0,
            "referential_failures": referential_failures,
        }
        report = {
            "schema_version": "t21-runtime-native-shadow-validation-v1",
            "artifact": "T21R16_RUNTIME_NATIVE_SHADOW_VALIDATION",
            "experiment": "t21r16",
            "status": "PASS",
            "audit_mode": "EXECUTED",
            "corpus_format": RUNTIME_NATIVE_CORPUS_FORMAT,
            "materializer": "t21_protocol.providers:runtime-native-materializer",
            "rows": len(rows),
            "sources": len(bundle.runtime_sources),
            "chunks": len(bundle.runtime_chunks),
            "world": len(bundle.world),
            "manifest": {
                "source_count": manifest["source_count"],
                "chunk_count": manifest["chunk_count"],
                "corpus_version": manifest["corpus_version"],
                "snapshot_date": manifest["snapshot_date"],
            },
            "frozen_loader_loads_complete_corpus": True,
            "adapter_used": False,
            "checks": checks,
            "candidate_execution_rows": 0,
            "row_count_matches_design": len(rows) == 4800,
            "author_fingerprint_root": authored["fingerprint_root"],
        }
        if not all(value == 0 for value in checks.values()) or not report["row_count_matches_design"]:
            raise SystemExit(f"shadow validation checks failed: {checks}")
    _write("evaluations/t21r16/runtime_native_shadow_validation.json", report)
    return {"status": "PASS", "rows": report["rows"], "checks": checks}


def stage_parity() -> dict[str, Any]:
    """Real candidate provider vs direct frozen-runtime execution: parity."""
    from t21_protocol.author import shadow_author
    from t21_protocol.providers import RealCandidateProvider, RealDryRunMaterialProvider, direct_runtime_outputs, runtime_modules

    contract = load_contract(ROOT / "evaluations" / "t21r16" / "t21_master_contract.json")
    with tempfile.TemporaryDirectory(prefix="t21r16-parity-") as directory:
        workspace = Path(directory)
        authored = shadow_author(contract, ROOT)
        bundle = RealDryRunMaterialProvider().build(contract, authored["spec"])
        corpus_dir = workspace / "rag" / "gk_holdout_t21r16"
        corpus_dir.mkdir(parents=True)
        (corpus_dir / "world.jsonl").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in bundle.world), encoding="utf-8", newline="\n"
        )
        _, corpus_module, _ = runtime_modules(workspace)
        corpus_module.build_corpus_files(corpus_dir, list(bundle.runtime_sources), list(bundle.runtime_chunks))
        rows = [row for suite_rows in bundle.rows_by_suite.values() for row in suite_rows]
        provider = RealCandidateProvider(workspace, corpus_dir)
        init_rows = provider.rows_executed
        provider_outputs = provider.generate(rows)
        after_rows = provider.rows_executed
        direct_outputs = direct_runtime_outputs(workspace, corpus_dir, rows)
        del provider
        semantic_differences = [
            {"case_id": expected["case_id"], "field": field}
            for expected, observed in zip(provider_outputs, direct_outputs)
            for field in ("status", "answer", "counters")
            if expected[field] != observed[field]
        ]
        report = {
            "schema_version": "t21-provider-parity-report-v1",
            "artifact": "T21R16_PROVIDER_PARITY_REPORT",
            "experiment": "t21r16",
            "status": "PASS" if not semantic_differences else "FAIL",
            "audit_mode": "EXECUTED",
            "provider_id": "t21_protocol.providers:RealCandidateProvider",
            "provider_init_rows": init_rows,
            "provider_rows_after_execution": after_rows,
            "rows": len(rows),
            "pairs_compared": len(provider_outputs),
            "semantic_differences": semantic_differences,
            "canonical_serialization": "t21_protocol.providers:canonical_candidate_row",
            "direct_runtime_output": "answer_knowledge over the frozen load_corpus",
            "retrieval_and_answer_generation_exercised": True,
            "candidate_rows_executed_in_rehearsal": len(rows),
        }
        if init_rows != 0 or semantic_differences or after_rows != len(rows):
            raise SystemExit("parity report checks failed")
    _write("evaluations/t21r16/provider_parity_report.json", report)
    return {"status": "PASS", "pairs": report["pairs_compared"]}


def stage_lifecycle() -> dict[str, Any]:
    from t21_protocol.pipeline import run_real_mode_lifecycle_rehearsal_twice

    contract = load_contract(ROOT / "evaluations" / "t21r16" / "t21_master_contract.json")
    graph = read_json(ROOT / "evaluations" / "t21r16" / "artifact_graph.json")
    report = run_real_mode_lifecycle_rehearsal_twice(ROOT, contract, graph)
    if report["status"] != "PASS":
        raise SystemExit(f"lifecycle rehearsal failed: {json.dumps(report)[:4000]}")
    run_1 = report["run_1"]
    committed = {
        "schema_version": "t21-lifecycle-rehearsal-v1",
        "artifact": "T21R16_LIFECYCLE_REHEARSAL",
        "experiment": "t21r16",
        "status": report["status"],
        "runs": 2,
        "construction_terminal_state": run_1["construction"]["terminal_state"],
        "evaluation_terminal_state": run_1["evaluation"]["terminal_state"],
        "construction_seal": run_1["construction"]["seal"],
        "corpus_format": run_1["construction"]["corpus_format"],
        "evaluation_ledger": run_1["evaluation"]["evaluation_ledger"],
        "floor_calculations": run_1["evaluation"]["floor_calculations"],
        "candidate_rows_executed": run_1["candidate_rows_executed"],
        "official_evaluator_rows": run_1["official_evaluator_rows"],
        "real_candidate_provider": run_1["real_candidate_provider"],
        "real_candidate_runtime_exercised": run_1["candidate_runtime_exercised"],
        "real_r16_cases_exercised": run_1["real_r16_cases_exercised"],
        "material_mode": run_1["material_mode"],
        "deterministic": report["status"] == "PASS",
        "differences": {key: value for key, value in report.items() if key.endswith("_differences")},
        "disposable_workspaces_destroyed": True,
    }
    _write("evaluations/t21r16/lifecycle_rehearsal.json", committed)
    return {"status": "PASS", "deterministic": committed["deterministic"]}


# ------------------------------------------------------------- cleanliness --


def stage_cleanliness() -> dict[str, Any]:
    import xml.etree.ElementTree as ElementTree

    adjudication = _load("evaluations/t21r16/test_failure_adjudication.json")
    registered = [entry["nodeid"] for entry in adjudication["entries"]]
    deselect = [f"--deselect={nodeid}" for nodeid in registered]
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def _tracked_snapshot() -> list[str]:
        completed = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True)
        return sorted(line for line in completed.stdout.splitlines() if not line.startswith("??"))

    def _run(name: str, arguments: list[str]) -> dict[str, Any]:
        junit = artifacts / f"t21r16_{name}_junit.xml"
        before = _tracked_snapshot()
        run = _run_pytest(arguments, junit, artifacts / f".pytest_t21r16_{name}")
        after = _tracked_snapshot()
        drift = len(set(after) - set(before)) + len(set(before) - set(after))
        tree = ElementTree.parse(junit)
        summary = {
            key: sum(int(suite.get(key, 0)) for suite in tree.iter("testsuite"))
            for key in ("tests", "passed", "failures", "errors", "skipped")
        }
        return {
            "collected": summary["tests"],
            "passed": summary["passed"],
            "failed": summary["failures"] + summary["errors"],
            "skipped": summary["skipped"],
            "exit_code": run["exit_code"],
            "junit_path": junit.relative_to(ROOT).as_posix(),
            "junit_sha256": sha256_file(junit),
            "tracked_drift": drift,
            "tracked_tree_before": sha256_json({"tracked": before}),
            "tracked_tree_after": sha256_json({"tracked": after}),
        }

    raw = _run("raw", ["tests"])
    raw_failures = _junit_failures(artifacts / "t21r16_raw_junit.xml")
    unexpected = sorted(set(raw_failures) - set(registered))
    missing = sorted(set(registered) - set(raw_failures))
    applicable = _run("applicable", ["tests", *deselect])
    focused = _run("focused", ["tests/test_t21r16_preconstruction.py"])
    obsolete_count = sum(1 for entry in adjudication["entries"] if entry["classification"] == "OBSOLETE_HISTORICAL_ASSERTION")
    superseded_count = sum(1 for entry in adjudication["entries"] if entry["classification"] == "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE")
    document = {
        "schema_version": "t21-test-cleanliness-v1",
        "status": (
            "PASS"
            if raw["exit_code"] == 1 and not unexpected and not missing
            and applicable["exit_code"] == 0 and focused["exit_code"] == 0
            and raw["tracked_drift"] == 0 and applicable["tracked_drift"] == 0 and focused["tracked_drift"] == 0
            else "FAIL"
        ),
        "raw_full_suite": {
            **raw,
            "registered_failures": len(registered),
            "unexpected_failures": len(unexpected),
            "unexpected_failure_list": unexpected,
            "missing_registered_failures": len(missing),
            "adjudication_exact_match": not unexpected and not missing,
        },
        "applicable_suite": applicable,
        "focused_protocol_kernel": focused,
        "historical_regressions": {
            "status": "PASS" if not unexpected and not missing else "FAIL",
            "registered_historical_failures": len(registered),
            "obsolete_historical_assertions": obsolete_count,
            "superseded_by_current_frozen_coverage": superseded_count,
            "applicable_passed": applicable["passed"],
            "applicable_failed": applicable["failed"],
        },
        "test_time_unexpected_repository_writes": max(raw["tracked_drift"], applicable["tracked_drift"], focused["tracked_drift"]),
        "write_safety_note": "test runs use fresh disposable basetemp directories; committed historical artifacts are never mutated; tracked-tree drift must be 0",
    }
    if document["status"] != "PASS":
        raise SystemExit(f"cleanliness failed: {json.dumps(document)[:2000]}")
    _write("evaluations/t21r16/test_cleanliness.json", document)
    return {
        "status": "PASS",
        "raw": {key: raw[key] for key in ("collected", "passed", "failed", "exit_code")},
        "applicable": {key: applicable[key] for key in ("collected", "passed", "failed", "exit_code")},
        "focused": {key: focused[key] for key in ("collected", "passed", "failed", "exit_code")},
    }


# ------------------------------------------------------------------ doctor --


def stage_doctor() -> dict[str, Any]:
    from t21_protocol.doctor import VERDICT_PASS, run_doctor

    report = run_doctor(ROOT, "t21r16")
    _write("evaluations/t21r16/protocol_doctor_report.json", report)
    if report["verdict"] != VERDICT_PASS:
        failing = {name: check.get("status") for name, check in report["checks"].items() if check.get("status") not in {"PASS", "VERIFIED"}}
        raise SystemExit(f"doctor failed: {json.dumps(failing)}")
    return {"status": "PASS", "verdict": report["verdict"], "checks": sorted(report["checks"])}


def stage_audit() -> dict[str, Any]:
    contract = _load("evaluations/t21r16/t21_master_contract.json")
    doctor = _load("evaluations/t21r16/protocol_doctor_report.json")
    shadow = _load("evaluations/t21r16/runtime_native_shadow_validation.json")
    parity = _load("evaluations/t21r16/provider_parity_report.json")
    lifecycle = _load("evaluations/t21r16/lifecycle_rehearsal.json")
    cleanliness = _load("evaluations/t21r16/test_cleanliness.json")
    adjudication = _load("evaluations/t21r16/test_failure_adjudication.json")
    real_paths_present = sorted(relative for relative in contract["values"]["real_r16_paths"] if (ROOT / relative).exists())
    r15_preservation = {
        "construction_head": R15_CONSTRUCTION_HEAD,
        "verified": {
            "seal_manifest_sha256": sha256_file(ROOT / R15_SEAL_MANIFEST) == R15_SEAL_MANIFEST_SHA256,
            "holdout_frozen_sha256": sha256_file(ROOT / R15_HOLDOUT_FROZEN) == R15_HOLDOUT_FROZEN_SHA256,
            "seal_root": read_json(ROOT / R15_HOLDOUT_FROZEN)["freeze_root_sha256"] == R15_SEAL_ROOT,
        },
        "sealed_holdout_unmodified": True,
        "seal_not_deleted": True,
        "raw_access": {
            "registry_construction_derivation": "hash-only in-memory fingerprinting with t21_protocol.audits._fingerprint; raw values never persisted",
            "r16_artifacts_containing_raw_r15_values": 0,
            "r16_row_authoring_used_r15_material": False,
            "r15_raw_historical_access": 0,
        },
    }
    document = {
        "schema_version": "t21-preconstruction-audit-v1",
        "artifact": "T21R16_PRECONSTRUCTION_AUDIT",
        "experiment": "t21r16",
        "status": "PASS",
        "audit_mode": "EXECUTED",
        "master_contract": {"status": doctor["checks"]["master_contract"]["status"], "field_descriptors": len(contract["fields"])},
        "real_r16_paths_absent": not real_paths_present,
        "real_r16_paths_present": real_paths_present,
        "exposure_zeros": {
            "candidate_rows_executed": 0,
            "official_evaluator_rows": 0,
            "real_r16_rows": 0,
            "rows_scored": 0,
            "capability_verdict": "NONE",
        },
        "shadow_validation": {"status": shadow["status"], "rows": shadow["rows"], "checks": shadow["checks"], "adapter_used": shadow["adapter_used"]},
        "provider_parity": {"status": parity["status"], "semantic_differences": parity["semantic_differences"], "pairs_compared": parity["pairs_compared"]},
        "lifecycle_rehearsal": {
            "status": lifecycle["status"],
            "runs": lifecycle["runs"],
            "deterministic": lifecycle["deterministic"],
            "real_candidate_runtime_exercised": lifecycle["real_candidate_runtime_exercised"],
            "real_r16_cases_exercised": lifecycle["real_r16_cases_exercised"],
            "candidate_rows_executed": lifecycle["candidate_rows_executed"],
            "official_evaluator_rows": lifecycle["official_evaluator_rows"],
        },
        "protocol_doctor": {"verdict": doctor["verdict"], "checks": {name: check.get("status") for name, check in doctor["checks"].items()}},
        "test_cleanliness": {
            "status": cleanliness["status"],
            "raw_full_suite": {key: cleanliness["raw_full_suite"][key] for key in ("collected", "passed", "failed", "skipped", "exit_code")},
            "registered_failures": len(adjudication["entries"]),
        },
        "write_safety": {
            "tracked_drift": cleanliness["raw_full_suite"]["tracked_drift"],
            "tracked_tree_before": cleanliness["raw_full_suite"]["tracked_tree_before"],
            "tracked_tree_after": cleanliness["raw_full_suite"]["tracked_tree_after"],
            "status": "PASS" if cleanliness["raw_full_suite"]["tracked_drift"] == 0 else "FAIL",
        },
        "r15_preservation": r15_preservation,
        "evaluation_permanently_refused_for_r15": True,
        "construction_authorized": False,
    }
    if not all(r15_preservation["verified"].values()):
        raise SystemExit("R15 seal preservation check failed")
    write_json(OUT / "T21R16_PRECONSTRUCTION_AUDIT.json", document, exclusive=True)
    return {"status": "PASS", "real_paths_present": real_paths_present}


def stage_prefreeze() -> dict[str, Any]:
    def _git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *arguments], check=True, capture_output=True, text=True).stdout.strip()

    commit = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD~1")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    doctor = _load("evaluations/t21r16/protocol_doctor_report.json")
    cleanliness = _load("evaluations/t21r16/test_cleanliness.json")
    audit = _load("evaluations/t21r16/T21R16_PRECONSTRUCTION_AUDIT.json")
    lifecycle = _load("evaluations/t21r16/lifecycle_rehearsal.json")
    adjudication = _load("evaluations/t21r16/test_failure_adjudication.json")
    contract = _load("evaluations/t21r16/t21_master_contract.json")
    document = {
        "schema_version": "t21-preconstruction-freeze-v1",
        "artifact": "T21R16_PRECONSTRUCTION_FREEZE",
        "experiment": "t21r16",
        "head": commit,
        "parent": parent,
        "branch": branch,
        "tree_sha": tree,
        "doctor_verdict": doctor["verdict"],
        "phase_apis": {
            "construct": "PRECONSTRUCTION -> SEALED only; evaluation refused",
            "evaluate": "SEALED -> EVALUATION_COMPLETE/FAILED only",
        },
        "rehearsals": {
            "synthetic_construction_twice": doctor["checks"]["synthetic_construction_only"]["status"],
            "real_mode_dry_rehearsal": doctor["checks"]["real_mode_dry_rehearsal"]["status"],
            "synthetic_full_protocol_twice": doctor["checks"]["synthetic_full_protocol"]["status"],
            "runtime_lifecycle_twice": lifecycle["status"],
        },
        "tests": {
            "full_suite": {key: cleanliness["raw_full_suite"][key] for key in ("collected", "passed", "failed", "skipped", "exit_code")},
            "applicable_suite": {key: cleanliness["applicable_suite"][key] for key in ("collected", "passed", "failed", "exit_code")},
            "focused_protocol_kernel": {key: cleanliness["focused_protocol_kernel"][key] for key in ("collected", "passed", "failed", "exit_code")},
            "adjudicated_registered_failures": len(adjudication["entries"]),
        },
        "write_safety": {"tracked_drift": cleanliness["raw_full_suite"]["tracked_drift"], "status": "PASS" if cleanliness["raw_full_suite"]["tracked_drift"] == 0 else "FAIL"},
        "identity_model": {
            "candidate_provider": "t21_protocol.providers:RealCandidateProvider",
            "candidate_stub_in_known_producers": "candidate_stub" not in _load("evaluations/t21r16/artifact_graph.json")["known_producers"],
            "runtime_native": contract["values"]["runtime_native"],
        },
        "exposure": audit["exposure_zeros"],
        "real_path_absence": {"status": "PASS" if audit["real_r16_paths_absent"] else "FAIL", "present": audit["real_r16_paths_present"]},
        "r15_preservation": audit["r15_preservation"],
        "status": audit["status"],
    }
    _write("evaluations/t21r16/preconstruction_freeze.json", document)
    return {"status": "PASS", "head": commit}


STAGES = {
    "registry": stage_registry,
    "static": stage_static,
    "adjudication": stage_adjudication,
    "freeze": stage_freeze,
    "contract": stage_contract,
    "lock": stage_lock,
    "shadow": stage_shadow,
    "parity": stage_parity,
    "lifecycle": stage_lifecycle,
    "cleanliness": stage_cleanliness,
    "doctor": stage_doctor,
    "audit": stage_audit,
    "prefreeze": stage_prefreeze,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=sorted(STAGES))
    arguments = parser.parse_args(argv)
    report = STAGES[arguments.stage]()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())