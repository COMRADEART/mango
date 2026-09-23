"""Produce a hash-only T22 exclusion anchor; never emit historical row values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t23/t22_exclusion_anchor.json"
FIELDS = {"case_ids": ("case_id",), "exact_queries": ("query",),
          "source_ids": ("source_id",), "chunk_ids": ("chunk_id",),
          "entity_identities": ("source_title",),
          "exact_source_text": ("text", "content_text"),
          "exact_answers": ("answer",)}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    suites = sorted((ROOT / "evaluations/t22/suites").glob("*/holdout.jsonl"))
    if len(suites) != 8:
        raise SystemExit("T22 suite anchor set incomplete")
    files = suites + [ROOT / f"rag/gk_holdout_t22/{name}"
                      for name in ("sources.jsonl", "chunks.jsonl", "corpus_manifest.json")]
    fingerprints: dict[str, set[str]] = {key: set() for key in FIELDS}
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    if path.name == "corpus_manifest.json":
                        break
                    raise
                if not isinstance(row, dict):
                    continue
                for dimension, fields in FIELDS.items():
                    for field in fields:
                        value = row.get(field)
                        if isinstance(value, str) and value:
                            fingerprints[dimension].add(digest(value))
                gold = row.get("gold")
                if isinstance(gold, dict):
                    for value in gold.values():
                        if isinstance(value, str) and value:
                            fingerprints["exact_answers"].add(digest(value))
    output = {
        "schema_version": "t23-t22-hash-only-anchor-v1",
        "raw_values_included": False,
        "source_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in files},
        "fingerprints": {key: sorted(values) for key, values in fingerprints.items()},
    }
    OUT.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"source_count": len(files),
                      "fingerprint_counts": {k: len(v) for k, v in fingerprints.items()},
                      "anchor_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
