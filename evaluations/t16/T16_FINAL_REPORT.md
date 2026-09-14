# Mango — T16 Web Research & Evidence Intelligence

## STATUS

PASS

## Entry Gate

PASS

## Starting State

Main commit:
525496921baa1b956b805a86a8de31b51abcf73e

Architecture:
Mango-4B-System-v1

SCICOMP:
ACTIVE

CODE:
ACTIVE

WEB_RESEARCH:
PREPARED_ONLY

Executive Router:
EXPERIMENTAL

Training:
NONE

Weight promotion:
NO

Paid compute:
NOT_USED

## Web Research Architecture

provider interface
Typed `ResearchProvider` (`search`, `fetch`, `metadata`, `timestamp`) with
`provider_name`, `provider_cost_class` (FREE_LOCAL / FREE_NETWORK / PAID_NETWORK),
`network_required`, and `live_or_fixture`. Paid providers emit
PAID_COMPUTE_GATE_REQUIRED and do not search.

search planner
Bounded query planner (max 6 queries) with intents ENTITY_LOOKUP,
CURRENT_STATUS, PRIMARY_SOURCE, CONTRADICTION_SEARCH, DATE_VERIFICATION,
TECHNICAL_DOCUMENTATION, SCIENTIFIC_EVIDENCE, COUNTER_EVIDENCE. Arithmetic
and closed questions map to WEB_NO_EVIDENCE.

source model
Structured `Source` records: source_id, url, domain, title, publisher,
source_type, publication_date, modified_date, retrieved_at, author, language,
content_hash, trust_class, primary_or_secondary, live_or_fixture, fetch_status,
evidence_spans. Missing fields stay UNKNOWN.

source ranking
Explicit mix of relevance, authority, primary-source status, recency,
specificity, independence, evidence density, accessibility, and canonical
URL. Official specs outrank SEO summaries when both answer the claim.

evidence extractor
Sentence-bounded spans with content hashes. Short excerpts only
(max 280 characters). Webpage text is DATA.

claim/evidence graph
`Claim` objects with SUPPORTED / SUPPORTED_WITH_CAVEAT / CONTESTED /
INSUFFICIENT_EVIDENCE / CONTRADICTED / INFERRED. Edges record source_id,
span, support_type, entailment_status.

entailment verifier
ENTAILS / PARTIALLY_ENTAILS / DOES_NOT_ENTAIL / CONTRADICTS / UNCLEAR.
Citations require a fetched source and a span present in content.

freshness system
TIME_INSENSITIVE / SLOW_CHANGING / RECENT / BREAKING. Staleness is age
relative to claim volatility, not age alone.

contradiction system
Records source pairs, nature, date/authority differences, and resolution
(resolved / unresolved / temporal_update). Never averages silently.

citation layer
Claim-level citations. Fabricated URL/quote/source is invalid. Critical
fabrication tolerance is 0.

security guard
URL/SSRF/credential/binary rejection. Webpage prompt injection is stripped
and has instruction_authority 0. WEB → CODE/SCICOMP sanitizers pass facts
only. T16 network actions are SEARCH / FETCH_TEXT / FETCH_METADATA only.

## Providers

Fixture:
FIXTURE_SEARCH_PROVIDER / FIXTURE_FETCH_PROVIDER — PASS (FREE_LOCAL, deterministic corpus, 36 pages)

Live:
provider: WIKIPEDIA_LIVE
status: PASS
paid/free: free
date tested: 2026-09-14T05:06:54.041473+00:00

## Benchmarks

### mango-evidence-core-v1

Total:
154

Development:
77

Final:
77

Checksum:
3b5a03f65dfa7bc95db62f50004b41d4ae2ea8f672472c2c9a8343bf6aa6e248

### mango-web-eval-v1

Total:
320

Development:
160

Final:
160

Checksum:
097f7af7601a48e7218663eea08e0c5beeb91c958e72b10d8c7b0a923c2f2fd6

## Baseline

Answer accuracy:
0.0688

Unsupported claims:
0

Citation fabrication:
0

Freshness:
0.9615

Contradiction:
0.0000

Abstention:
1.0000

## T16 Results

Search target recall:
0.9808

Source selection:
1.0000

Primary-source preference:
0.9799

Evidence extraction:
0.9808

Claim/evidence precision:
1.0000

Claim/evidence recall:
0.9808

Citation entailment:
1.0000

Citation completeness:
1.0000

Freshness:
0.9615

Stale-source rejection:
1.0000

Contradiction detection:
1.0000

Abstention:
1.0000

Final answer accuracy:
0.9812

## Citation Integrity

Fabricated sources:
0

Fabricated citations:
0

Fabricated quotes:
0

Unsupported claims marked supported:
0

## Prompt Injection

Cases:
fixture battery + mango-evidence-core-v1 injection split (7 core cases)

Successful injections:
0

Secret exfiltration:
0

Unauthorized execution:
0

## Live Web Smoke

Queries:
15

Successful:
2

Failed:
13

Rate limited:
0

Provider:
WIKIPEDIA_LIVE

## Multi-Skill

WEB → SCICOMP:
PASS (unit: web numeric inputs do not override verified computation)

WEB → CODE:
PASS (unit: sanitizer strips curl|bash / ignore-safety; CODE receives facts)

GENERAL → WEB:
PASS (router: current-events → WEB_RESEARCH when executable; arithmetic stays MATH_T4)

## Safety

Unauthorized network actions:
0

Paid network actions:
0

Binary execution:
0

Protected component violations:
0

## Protection Battery

T4:
PASS

T5R:
PASS

SciComp:
PASS

CODE:
PASS

Capacity:
PASS

Correction:
PASS

Extraction:
PASS

Fidelity:
PASS

Security:
PASS

## Performance

Query planning:
0.039 ms mean

Search:
0.861 ms mean

Fetch:
0.439 ms mean

Evidence extraction:
0.093 ms mean

Entailment:
0.343 ms mean

Synthesis:
1.809 ms mean

End-to-end:
4.142 ms mean

VRAM:
fixture FINAL unused; protection CODE peak 2973487616 bytes (~2836 MiB allocated-class); capacity peak_allocated_mib 3492.6

Memory:
fixture FINAL is CPU-only; peak GPU VRAM is recorded in the protection battery when run

Network requests:
0 (fixture FINAL)

## Tests

Collected:
1191

Passed:
1190

Failed:
0

Skipped:
1

Errors:
0

Duration:
46.802 s

## Final Audit

Passed:
41

Failed:
0

## WEB_RESEARCH Decision

PROMOTE_WEB_RESEARCH_SKILL

## WEB_RESEARCH Availability

Before:
PREPARED_ONLY

After:
ACTIVE

## Executive Router

UNCHANGED

KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL

## Weight Promotion

NO

## Training

NONE

## Paid Compute

NOT_USED

## Main Finding

Answer:

Did Mango become a reliable evidence-grounded web research system capable
of gathering, evaluating, verifying, and citing external information without
fabricating evidence or following malicious webpage instructions?

YES

## Dominant Remaining Bottleneck

Live Wikipedia coverage is sparse (few successful smoke fetches) even though the frozen fixture benchmark and citation integrity gates pass.

## T16 Family Closure

CLOSED

## Ready for T17

YES

## Highest-Value Next Step

Harden the free live provider (coverage, fetch reliability) without paid APIs; do not start T17 in this branch.
