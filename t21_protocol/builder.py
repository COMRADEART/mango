"""Contract-driven material builders; no version-specific orchestration."""
from __future__ import annotations

from itertools import cycle
from pathlib import Path
from typing import Any, Iterator

from .util import sha256_json, write_json, write_jsonl


def _design_sequence(requirements: dict[str, int]) -> Iterator[str]:
    for tag, count in requirements.items():
        for _ in range(count):
            yield tag


def _build_rows(
    contract: Any, author_spec: dict[str, Any], *, material_mode: str
) -> dict[str, list[dict[str, Any]]]:
    domains = author_spec["canonical_domains"]
    pairs = {pair["id"]: pair for pair in author_spec["crossdomain_pairs"]}
    rows_by_suite: dict[str, list[dict[str, Any]]] = {}
    serial = 0
    for suite_name, suite in contract.get("suites").items():
        family = suite["family"]
        count = suite["count"]
        design = contract.get("exact_design").get(family)
        if family == "crossdomain":
            tags = [pair["id"] for pair in author_spec["crossdomain_pairs"] for _ in range(design["rows_per_pair"])]
        else:
            tags = list(_design_sequence(design)) if design else [None] * count
        if len(tags) != count:
            raise ValueError(f"exact-design total differs from suite count: {family}")
        domain_cycle = cycle(domains)
        rows: list[dict[str, Any]] = []
        for index, tag in enumerate(tags):
            case_id = f"{contract.get('identity.case_id_prefix')}{serial:05d}"
            serial += 1
            required_domains = [next(domain_cycle)]
            domain_indexes = [domains.index(domain) for domain in required_domains]
            if material_mode == "SYNTHETIC":
                query = f"Synthetic qualification query {case_id}"
                answer = f"Synthetic qualification answer {case_id}"
                source_ids = [f"syn-src-{domain_index:02d}" for domain_index in domain_indexes]
                chunk_ids = [f"{source_id}:chunk-0" for source_id in source_ids]
            elif material_mode == "REAL_BLIND":
                query = f"Within blind record {case_id}, what registered value is stated?"
                answer = f"R15 registered value {serial - 1:05d}"
                source_ids = [f"r15-src-{serial - 1:05d}"]
                chunk_ids = [f"{source_ids[0]}:record-0"]
            elif material_mode == "REAL_BLIND_RUNTIME_NATIVE":
                # Semantic-fact authoring only: the registered value and its
                # canonical statement are authored blind material; runtime
                # identity fields (source/chunk IDs) are produced later by the
                # runtime-native materializer from the frozen schema, never
                # authored inline and never remapped at evaluation time.
                query = f"Within blind record {case_id}, what registered value is stated?"
                answer = f"R16 registered value {serial - 1:05d}"
                statement = f"Blind record {case_id} states the registered value {answer}."
                source_ids: list[str] = []
                chunk_ids: list[str] = []
            else:
                raise ValueError(f"unsupported material mode: {material_mode}")
            row: dict[str, Any] = {
                "case_id": case_id,
                "suite_family": family,
                "query": query,
                "mode": "retrieval" if family == "retrieval" else "answer",
                "gold": {
                    "required_domains": required_domains,
                    "expect_status": "ANSWER",
                    "expected_answer": statement if material_mode == "REAL_BLIND_RUNTIME_NATIVE" else answer,
                    "source_ids": source_ids,
                    "chunk_ids": chunk_ids,
                },
            }
            if tag is not None:
                row["construction_tag"] = tag
            if family == "crossdomain":
                pair = pairs[tag]
                row["gold"]["required_domains"] = [pair["domain_a"], pair["domain_b"]]
                row["crossdomain_pair"] = f"{pair['domain_a']}::{pair['domain_b']}"
            rows.append(row)
        rows_by_suite[suite_name] = rows
    return rows_by_suite


def build_rows(contract: Any, author_spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build qualification-only synthetic rows."""
    return _build_rows(contract, author_spec, material_mode="SYNTHETIC")


def build_real_rows(contract: Any, author_spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build newly-authored blind rows without synthetic fixture identity."""
    return _build_rows(contract, author_spec, material_mode="REAL_BLIND")


def build_real_rows_runtime_native(
    contract: Any, author_spec: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Build runtime-native blind rows: semantic facts with empty runtime IDs."""
    return _build_rows(contract, author_spec, material_mode="REAL_BLIND_RUNTIME_NATIVE")


def materialize_corpus(root: Path, contract: Any, author_spec: dict[str, Any]) -> dict[str, Any]:
    corpus = root / "rag" / f"gk_holdout_{contract.experiment}"
    corpus.mkdir(parents=True, exist_ok=False)
    domains = author_spec["canonical_domains"]
    world = [{"entity_id": f"syn-ent-{index:02d}", "domain": domain} for index, domain in enumerate(domains)]
    sources = [
        {"source_id": f"syn-src-{index:02d}", "topic_tags": [domain], "title": f"Synthetic {domain}"}
        for index, domain in enumerate(domains)
    ]
    chunks = [
        {"chunk_id": f"syn-src-{index:02d}:chunk-0", "source_id": f"syn-src-{index:02d}", "text": f"Synthetic {domain} evidence."}
        for index, domain in enumerate(domains)
    ]
    write_jsonl(corpus / "world.jsonl", world)
    write_jsonl(corpus / "sources.jsonl", sources)
    write_jsonl(corpus / "chunks.jsonl", chunks)
    manifest = {"schema_version": "t21-corpus-v1", "world": len(world), "sources": len(sources), "chunks": len(chunks)}
    write_json(corpus / "corpus_manifest.json", manifest, exclusive=True)
    return manifest


def materialize_suites(root: Path, contract: Any, rows_by_suite: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    suite_root = root / "evaluations" / contract.experiment / "suites"
    counts: dict[str, int] = {}
    for suite_name, rows in rows_by_suite.items():
        target = suite_root / suite_name
        target.mkdir(parents=True, exist_ok=False)
        counts[suite_name] = write_jsonl(target / "holdout.jsonl", rows)
        write_json(
            target / "manifest.json",
            {"schema_version": "t21-suite-v1", "suite": suite_name, "rows": len(rows), "rows_root": sha256_json(rows)},
            exclusive=True,
        )
    return counts
