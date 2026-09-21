"""Contract-driven synthetic/real materializer; no version-specific rules."""
from __future__ import annotations

from itertools import cycle
from pathlib import Path
from typing import Any, Iterator

from .util import sha256_json, write_json, write_jsonl


def _design_sequence(requirements: dict[str, int]) -> Iterator[str]:
    for tag, count in requirements.items():
        for _ in range(count):
            yield tag


def build_rows(contract: Any, author_spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
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
            row: dict[str, Any] = {
                "case_id": case_id,
                "suite_family": family,
                "query": f"Synthetic qualification query {case_id}",
                "mode": "retrieval" if family == "retrieval" else "answer",
                "gold": {
                    "required_domains": required_domains,
                    "expect_status": "ANSWER",
                    "expected_answer": f"Synthetic qualification answer {case_id}",
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
