"""Focused T21R16 preconstruction tests (runtime-native by construction).

The R15 sealed holdout failed because its corpus model was incompatible with
the frozen candidate runtime. These tests reproduce that exact failure modes
set against the frozen runtime (fail-closed) and pin the preconstruction
artifacts. All fixture work happens in temporary workspaces; no committed
artifact is written or mutated."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r16"
R15_OUT = ROOT / "evaluations" / "t21r15"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import t21r16_fixtures as fx  # noqa: E402
from t21r16_fixtures import contract_present  # noqa: E402

if not contract_present(ROOT):
    pytest.skip("T21R16 master contract not yet present (preconstruction "
                "not started)", allow_module_level=True)

import t21r16_preconstruction as generator  # noqa: E402
from sciencemath.knowledge import corpus as corpus_module  # noqa: E402
from sciencemath.knowledge import schema as schema_module  # noqa: E402
from t21_protocol.util import sha256_file, sha256_json  # noqa: E402


def _j(relative: str) -> dict:
    return fx.load_json(ROOT, f"evaluations/t21r16/{relative}")


def _contract() -> dict:
    return fx.load_json(ROOT, "evaluations/t21r16/t21_master_contract.json")


# ------------------------------------------------------------- fixtures --


def _fixture_source(**overrides):
    fields = {
        "source_id": schema_module.make_source_id(
            "Blind fixture source", "Mango evaluation fixtures", "r16-fixture-v1"),
        "source_title": "Blind fixture source",
        "source_type": "fixture",
        "source_uri_or_origin": "project://t21r16/fixture-source",
        "publisher_or_collection": "Mango evaluation fixtures",
        "license": "CC0-equivalent project fixture",
        "revision_or_version": "r16-fixture-v1",
        "retrieved_at_or_snapshot_date": "2026-01-31",
        "language": "en",
        "authority_class": "GENERAL_REFERENCE",
        "freshness_class": "STATIC",
        "topic_tags": ["history"],
        "content_text": "Blind fixture content for loader probes. Registered value 4242.",
    }
    fields.update(overrides)
    return schema_module.KnowledgeSourceRecord(**fields)


def _fixture_chunk(source, section="Registered values", ordinal=0, text=None, **overrides):
    body = text if text is not None else (
        f"Section {ordinal}: Blind fixture statement with registered value 4242.")
    fields = {
        "chunk_id": schema_module.make_chunk_id(source.source_id, section, ordinal),
        "source_id": source.source_id,
        "section": section,
        "text": body,
        "ordinal": ordinal,
        "span": (0, len(body)),
        "metadata": {"topic_tags": list(source.topic_tags)},
    }
    fields.update(overrides)
    return schema_module.KnowledgeChunk(**fields)


def _refresh_manifest(corpus_dir: Path) -> None:
    """Recompute file checksums and the manifest checksum after a mutation so
    the loader's checksum gate passes and the schema-layer failure surfaces."""
    manifest = json.loads((corpus_dir / "corpus_manifest.json").read_text(encoding="utf-8"))
    for name in ("sources.jsonl", "chunks.jsonl"):
        data = (corpus_dir / name).read_bytes().replace(b"\r\n", b"\n")
        manifest["file_checksums"][name] = hashlib.sha256(data).hexdigest()
    manifest.pop("manifest_checksum", None)
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    manifest["manifest_checksum"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    (corpus_dir / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")


def _rewrite_rows(corpus_dir: Path, name: str, mutate) -> None:
    rows = [json.loads(line) for line in (corpus_dir / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    mutate(rows)
    text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    (corpus_dir / name).write_text(text, encoding="utf-8", newline="\n")
    _refresh_manifest(corpus_dir)


def _valid_corpus(directory: Path) -> tuple[Path, object]:
    source = _fixture_source()
    chunk = _fixture_chunk(source)
    corpus_dir = directory / "corpus"
    corpus_module.build_corpus_files(corpus_dir, [source], [chunk])
    return corpus_dir, source


def test_missing_required_source_field_fails_closed(tmp_path):
    """R15 failure mode: a source row without source_title must not load."""
    corpus_dir, _ = _valid_corpus(tmp_path)
    corpus = corpus_module.load_corpus(corpus_dir)  # sanity: the valid corpus loads
    assert corpus.source(_fixture_source().source_id) is not None
    _rewrite_rows(corpus_dir, "sources.jsonl", lambda rows: rows[0].pop("source_title"))
    with pytest.raises(KeyError):
        corpus_module.load_corpus(corpus_dir)


def test_source_id_grammar_violation_fails_closed(tmp_path):
    """R15 failure mode: source IDs outside the frozen gk- grammar are rejected."""
    with pytest.raises(schema_module.SchemaError):
        _fixture_source(source_id="r15-src-00001")
    corpus_dir, _ = _valid_corpus(tmp_path)
    _rewrite_rows(corpus_dir, "sources.jsonl", lambda rows: rows[0].__setitem__("source_id", "r15-src-00001"))
    with pytest.raises(schema_module.SchemaError):
        corpus_module.load_corpus(corpus_dir)


def test_manifest_missing_file_checksums_fails_closed(tmp_path):
    """R15 failure mode: a manifest without per-file checksums is refused."""
    corpus_dir, _ = _valid_corpus(tmp_path)
    manifest = json.loads((corpus_dir / "corpus_manifest.json").read_text(encoding="utf-8"))
    manifest.pop("file_checksums")
    (corpus_dir / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(corpus_module.CorruptCorpusError):
        corpus_module.load_corpus(corpus_dir)
    # A partial checksum table (one file only) is equally refused.
    corpus_dir2, _ = _valid_corpus(tmp_path / "second")
    manifest2 = json.loads((corpus_dir2 / "corpus_manifest.json").read_text(encoding="utf-8"))
    manifest2["file_checksums"].pop("chunks.jsonl")
    (corpus_dir2 / "corpus_manifest.json").write_text(
        json.dumps(manifest2, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(corpus_module.CorruptCorpusError):
        corpus_module.load_corpus(corpus_dir2)


def test_missing_authority_or_freshness_fails_closed(tmp_path):
    """R15 failure mode: authority/freshness outside the closed vocabularies
    (or absent) are rejected at construction, not defaulted."""
    with pytest.raises(schema_module.SchemaError):
        _fixture_source(authority_class="WIKIPEDIA")
    with pytest.raises(schema_module.SchemaError):
        _fixture_source(freshness_class="LIVE")
    corpus_dir, _ = _valid_corpus(tmp_path)
    _rewrite_rows(corpus_dir, "sources.jsonl", lambda rows: rows[0].pop("authority_class"))
    with pytest.raises(KeyError):
        corpus_module.load_corpus(corpus_dir)


def test_missing_section_or_span_fails_closed(tmp_path):
    """R15 failure mode: chunks without section/ordinal/span/content_hash are
    rejected by from_dict (R15 sealed chunks carried 4 of 8 runtime keys)."""
    corpus_dir, source = _valid_corpus(tmp_path)
    corpus_module.load_corpus(corpus_dir)  # sanity
    for missing in ("section", "span", "content_hash", "ordinal"):
        def mutate(rows, missing=missing):
            rows[0].pop(missing)
        _rewrite_rows(corpus_dir, "chunks.jsonl", mutate)
        with pytest.raises(KeyError):
            corpus_module.load_corpus(corpus_dir)
    with pytest.raises(KeyError):
        schema_module.KnowledgeChunk.from_dict({
            "chunk_id": "gk-x:s:0", "source_id": source.source_id,
            "text": "orphan", "ordinal": 0, "content_hash": "0" * 64,
        })


def test_no_default_filling_of_missing_fields(tmp_path):
    """No loader layer may synthesize or default a missing runtime field."""
    source_required = [
        "source_id", "source_title", "source_type", "source_uri_or_origin",
        "publisher_or_collection", "license", "revision_or_version",
        "retrieved_at_or_snapshot_date", "language", "authority_class",
        "freshness_class", "content_hash", "document_hash",
    ]
    for missing in source_required:
        directory = tmp_path / f"src-{missing}"
        corpus_dir, _ = _valid_corpus(directory)
        _rewrite_rows(corpus_dir, "sources.jsonl", lambda rows, m=missing: rows[0].pop(m))
        with pytest.raises(KeyError):
            corpus_module.load_corpus(corpus_dir)
    for missing in ("chunk_id", "source_id", "section", "text", "ordinal", "span", "content_hash"):
        directory = tmp_path / f"chunk-{missing}"
        corpus_dir, _ = _valid_corpus(directory)
        _rewrite_rows(corpus_dir, "chunks.jsonl", lambda rows, m=missing: rows[0].pop(m))
        with pytest.raises(KeyError):
            corpus_module.load_corpus(corpus_dir)
    # Positive control: a valid load invents nothing — every persisted field
    # round-trips byte-identically from the corpus file (the source content_hash
    # is carried as authored; the runtime recomputes only the chunk checksum,
    # which is derived from the chunk text the file itself carries).
    corpus_dir, _ = _valid_corpus(tmp_path / "positive")
    loaded = corpus_module.load_corpus(corpus_dir)
    source_row = json.loads((corpus_dir / "sources.jsonl").read_text(encoding="utf-8").splitlines()[0])
    record = loaded.sources[0]
    for key in (
        "source_id", "source_title", "source_type", "source_uri_or_origin",
        "publisher_or_collection", "license", "revision_or_version",
        "retrieved_at_or_snapshot_date", "language", "authority_class",
        "freshness_class", "content_hash", "document_hash",
    ):
        assert getattr(record, key) == source_row[key], key
    chunk_row = json.loads((corpus_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()[0])
    chunk = loaded.chunks[0]
    for key in ("chunk_id", "source_id", "section", "text", "ordinal", "content_hash"):
        assert getattr(chunk, key) == chunk_row[key], key
    assert list(chunk.span) == chunk_row["span"]
    assert chunk.content_hash == schema_module.chunk_checksum(chunk.text)


def test_runtime_contract_is_derived_from_frozen_modules():
    """The committed runtime corpus contract must equal a fresh derivation
    from the frozen runtime bytes (no hand-copied schema drifts silently)."""
    committed = _j("runtime_corpus_contract.json")
    recomputed, checks = generator._runtime_corpus_contract()
    assert all(checks.values()), checks
    assert committed == recomputed


# ------------------------------------------------- preconstruction pins --


def test_contract_runtime_native_block():
    contract = _contract()
    runtime_native = contract["values"]["runtime_native"]
    assert runtime_native == {
        "corpus_format": "mango-general-knowledge-corpus-v1",
        "loader_entry": "src/sciencemath/knowledge/corpus.py:load_corpus",
        "runtime_materializer": "t21_protocol.providers:runtime-native-materializer",
        "candidate_provider": "t21_protocol.providers:RealCandidateProvider",
        "source_id_grammar": "gk-<sha1(title|publisher|revision)[:12]>",
        "manifest_format": "runtime_build_corpus_files",
        "shadow_holdout_rows": 4800,
        "holdout_frozen_schema_version": "t21-holdout-frozen-v2",
    }
    disposition = contract["values"]["r15_disposition"]
    assert disposition["candidate_rows"] == 0
    assert disposition["official_evaluator_rows"] == 0
    assert disposition["one_shot_consumed"] is False
    assert disposition["evaluation_permanently_refused"] is True
    assert sha256_json(contract["values"]["promotion_floors"]) == fx.FLOOR_HASH


def test_real_r16_paths_absent():
    contract = _contract()
    present = [path for path in contract["values"]["real_r16_paths"] if (ROOT / path).exists()]
    assert present == []
    # The two runtime-native production artifacts stay construction-phase.
    assert not (OUT / "runtime_loader_validation.json").exists()
    assert not (OUT / "candidate_provider_compatibility.json").exists()


def test_quarantine_forbidden():
    contract = _contract()
    assert contract["values"]["quarantine"] == {
        "status": "FORBIDDEN",
        "r15_sealed_holdout_reads": 0,
        "r15_sealed_holdout_path": "rag/gk_holdout_t21r15",
        "registry_access_only": True,
    }


def test_holdout_frozen_schema_v2_partition():
    schema = _j("holdout_frozen_schema.json")
    properties = schema["properties"]
    assert len(properties) == 24
    strings = {name for name, spec in properties.items() if spec["type"] == "string"}
    integers = {name for name, spec in properties.items() if spec["type"] == "integer"}
    assert len(strings) == 18 and len(integers) == 6
    assert not (strings & integers)
    assert schema["required"] == sorted(properties)
    assert schema["additionalProperties"] is False


def test_floor_evidence_contract_covers_32_floors():
    evidence = _j("floor_evidence_contract.json")
    assert evidence["floor_count"] == 32
    assert len(evidence["floors"]) == 32
    assert set(evidence["evidence_per_floor"]) == {"metric", "op", "observed", "threshold", "evidence_path", "pass"}
    contract = _contract()
    registry = _j("official_metric_registry.json")
    zero_tolerance = registry["zero_tolerance_metrics"]
    floors = contract["values"]["promotion_floors"]
    recomputed = sorted(
        metric for metrics in floors.values() for metric, spec in metrics.items()
        if spec["op"] in {"=", "<="} and spec["value"] == 0
    )
    assert zero_tolerance == recomputed
    assert registry["metric_count"] == 32
    assert registry["post_seal_metric_changes"] == 0


def test_evaluation_graph_names_only_production_producers():
    graph = _j("evaluation_artifact_graph.json")
    assert graph["candidate_stub_nodes"] == 0
    assert len(graph["nodes"]) == 9
    allowed = {"ledger", "real_candidate_provider", "evaluator", "scorer"}
    for node in graph["nodes"].values():
        assert node["producer"] in allowed
    master_graph = _j("artifact_graph.json")
    assert "candidate_stub" not in master_graph["known_producers"]


def test_registry_carries_r15_milestone_hash_only():
    r14 = fx.load_json(ROOT, "evaluations/t21r14/prior_exclusion.json")
    registry = _j("prior_exclusion.json")
    assert registry["historical_milestone_count"] == 15
    assert registry["milestone_order"][-1] == fx.R15_HISTORICAL_MILESTONE
    assert registry["milestone_order"][:-1] == r14["milestone_order"]
    assert registry["raw_values_included"] is False
    r15 = registry["milestones"][fx.R15_HISTORICAL_MILESTONE]
    assert r15["provenance"]["raw_values_included"] is False
    assert r15["provenance"]["construction_head"] == fx.R15_CONSTRUCTION_HEAD
    assert r15["provenance"]["sealed_holdout_frozen_sha256"] == fx.R15_HOLDOUT_FROZEN_SHA256
    for name, payload in r15["dimensions"].items():
        assert payload["count"] == len(payload["fingerprints"])
        assert payload["set_sha256"] == hashlib.sha256(
            ("\n".join(sorted(payload["fingerprints"])) + "\n" if payload["fingerprints"] else "").encode("ascii")
        ).hexdigest()
        for fingerprint in payload["fingerprints"]:
            assert len(fingerprint) == 64 and fingerprint == fingerprint.lower()
    assert r15["dimensions"]["verbatim_attack_wording"]["count"] == 0
    # R14 milestones must be carried byte-identical.
    for name, milestone in r14["milestones"].items():
        assert registry["milestones"][name] == milestone


def test_r15_seal_preserved_untouched():
    assert sha256_file(R15_OUT / "holdout_manifest.json") == fx.R15_MANIFEST_SHA256
    assert sha256_file(R15_OUT / "HOLDOUT_FROZEN") == fx.R15_HOLDOUT_FROZEN_SHA256
    frozen = json.loads((R15_OUT / "HOLDOUT_FROZEN").read_text(encoding="utf-8"))
    assert frozen["freeze_root_sha256"] == fx.R15_SEAL_ROOT
    closure = fx.load_json(ROOT, "evaluations/t21r15/T21R15_CLOSURE.json")
    assert closure["preserved_hashes"]["construction_head"] == fx.R15_CONSTRUCTION_HEAD
    assert closure["status"] == fx.R15_CLOSURE_STATUS
    assert closure["reason"] == fx.R15_CLOSURE_REASON
    refusal = fx.load_json(ROOT, "evaluations/t21r15/evaluation_refusal.json")
    assert refusal["permanent"] is True
    assert refusal["designation"] == "T21R15_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED"


def test_shadow_validation_and_parity_committed():
    shadow_path = OUT / "runtime_native_shadow_validation.json"
    parity_path = OUT / "provider_parity_report.json"
    if not shadow_path.is_file() or not parity_path.is_file():
        pytest.skip("shadow/parity stages not yet run")
    shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
    assert shadow["status"] == "PASS"
    assert shadow["rows"] == 4800
    assert shadow["adapter_used"] is False
    assert all(value == 0 for value in shadow["checks"].values())
    assert shadow["candidate_execution_rows"] == 0
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    assert parity["status"] == "PASS"
    assert parity["provider_init_rows"] == 0
    assert parity["rows"] == 4800
    assert parity["pairs_compared"] == 4800
    assert parity["semantic_differences"] == []
    assert parity["retrieval_and_answer_generation_exercised"] is True