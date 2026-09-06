# Science Source License Manifest — Mango T5

Companion to `data/science_sources/source_registry.json`. Records the
licensing facts behind each source's registry status. Deny-by-default:
any source not covered here — or whose verification below is missing —
is BLOCKED for all Mango usage.

Semantics of the `approved_for_*` flags are Mango **usage policy** (see
registry `field_semantics`); this manifest records what the *licenses*
actually permit and what verification has been done.

| source_id | status | license (as verified) | local index | redistribution | training | verification state |
|---|---|---|---|---|---|---|
| wikipedia_en | APPROVED | CC BY-SA 4.0 (article text) | YES | no (Mango policy: share-alike burden) | no (T5 policy: retrieval-only) | license fact well-established; per-chunk attribution pipeline implemented in T5 ingestion |
| openstax | REVIEW_REQUIRED | CC BY 4.0 believed, per-book verification pending | no | no | no | NOT VERIFIED — needs per-book license check incl. media assets before ingestion |
| nasa_public | APPROVED* | U.S. Government public domain (per-dataset caveats) | yes (connector pending) | yes | yes | policy pre-approved; no ingestion in T5; verify per-dataset when connector lands |
| noaa_public | APPROVED* | U.S. Government public domain (per-dataset caveats) | yes (connector pending) | yes | yes | policy pre-approved; no ingestion in T5; verify per-dataset when connector lands |
| ncbi_pubmed_abstracts | REVIEW_REQUIRED | publisher-copyrighted abstracts; NLM bulk-redistribution restrictions | no | no | no | NOT VERIFIED — NLM redistribution policy requires explicit human review |
| pmc_open_access | REVIEW_REQUIRED | per-article (CC BY / CC BY-NC / CC0 / publisher) | no | no | no | NOT VERIFIED — needs per-article license resolution step |
| arxiv | RETRIEVAL_ONLY | metadata CC0; full text varies per paper | no (durable indexing not approved) | no | no | metadata terms well-established; per-paper license audit required before any indexing |
| sciencedirect | BLOCKED | proprietary | no | no | no | denied by policy |

\* "APPROVED" for nasa_public/noaa_public is a pre-approval of the usage
category (public-domain government sources). No bytes from these sources
are ingested in T5 — the connectors do not exist yet. When a connector is
built, per-dataset verification must be recorded here before indexing.

## Attribution string format used by the corpus

Every chunk in `rag/corpus/` carries an `attribution` field. For
Wikipedia (the only ingested source in T5):

```
Text from Wikipedia (en), article "<TITLE>", revision <REVID>,
retrieved <YYYY-MM-DD>, <URL>. Licensed CC BY-SA 4.0.
```

The corpus as a whole is an internal retrieval artifact of the Mango
project and is NOT redistributed; `approved_for_redistribution=false`
for every currently ingested source.

## Gate behavior (enforced in code, see src/sciencemath/rag/source_registry.py)

1. Unknown `source_id` → denied for every usage.
2. Missing/unknown `status` → denied.
3. `REVIEW_REQUIRED`/`BLOCKED` → denied for retrieval and indexing.
4. `RETRIEVAL_ONLY` → live retrieval allowed, durable indexing denied.
5. `APPROVED` without `approved_for_local_index=true` → indexing denied.
6. Any flag/status change requires a registry version bump (change_log).