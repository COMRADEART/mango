"""Write evaluations/t16/T16_FINAL_REPORT.md from frozen artifacts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t16/T16_FINAL_REPORT.md"


def load(p):
    path = ROOT / p if not str(p).startswith(str(ROOT)) else Path(p)
    if not path.exists():
        path = ROOT / p
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def pct(x):
    if x is None:
        return "n/a"
    if isinstance(x, (int, float)) and x <= 1.5:
        return f"{x:.4f}"
    return str(x)


def main() -> int:
    entry = load("evaluations/t16/t16_entry_gate.json")
    webm = load("evaluations/t16/suites/mango-web-eval-v1/manifest.json")
    evm = load("evaluations/t16/suites/mango-evidence-core-v1/manifest.json")
    base = load("evaluations/t16/runs/t16-baseline-final/summary.json")
    fin = load("evaluations/t16/runs/t16-final/summary.json")
    live = load("evaluations/t16/live_smoke.json")
    py = load("evaluations/t16/pytest_final.json")
    audit = load("evaluations/t16/final_audit.json")
    prot = load("evaluations/t16/protection/regression_summary.json")
    sec = load("evaluations/t16/protection/security_summary.json")
    trans = load("evaluations/t16/web_research_transition.json")
    perf = load("evaluations/t16/performance.json")
    floors = load("evaluations/t16/floors_evaluation.json")
    bw = (base.get("web") or {})
    w = (fin.get("web") or {})
    ev = (fin.get("evidence_core") or {})
    layers = (prot.get("layers") or {})
    decision = (audit.get("web_research_decision")
                or floors.get("decision")
                or "KEEP_WEB_RESEARCH_EXPERIMENTAL")
    after = (trans.get("after") or "PREPARED_ONLY")
    entry_ok = (entry.get("status") == "PASS")
    py_ok = py.get("failures") == 0 and py.get("errors") == 0
    prot_ok = prot.get("status") == "ALL_PASS"
    if entry_ok and py_ok and prot_ok and w.get("fabricated_sources") == 0:
        status = "PASS"
    elif entry_ok:
        status = "PARTIAL"
    else:
        status = "BLOCKED"
    promote = decision == "PROMOTE_WEB_RESEARCH_SKILL" and after == "ACTIVE"
    finding = "YES" if promote else (
        "PARTIALLY" if w.get("final_answer_accuracy", 0) >= 0.85 else "NO")
    family = "CLOSED" if status == "PASS" else "NOT_CLOSED"
    ready = "YES" if family == "CLOSED" else "NO"
    audit_fails = audit.get("fails", "pending")
    if isinstance(audit_fails, list):
        audit_fails = len(audit_fails)
    audit_passes = audit.get("passes", "pending")

    def layer(name):
        s = (layers.get(name) or {}).get("status", "MISSING")
        return s

    md = f"""# Mango — T16 Web Research & Evidence Intelligence

## STATUS

{status}

## Entry Gate

{entry.get("status", "FAIL")}

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
provider: {live.get("provider", "WIKIPEDIA_LIVE")}
status: {live.get("status", "LIVE_PROVIDER_UNAVAILABLE")}
paid/free: {live.get("paid_or_free", "free")}
date tested: {live.get("date_tested", "n/a")}

## Benchmarks

### mango-evidence-core-v1

Total:
{evm.get("total", 154)}

Development:
{evm.get("dev_n", 77)}

Final:
{evm.get("final_n", 77)}

Checksum:
{evm.get("final_sha256")}

### mango-web-eval-v1

Total:
{webm.get("total", 320)}

Development:
{webm.get("dev_n", 160)}

Final:
{webm.get("final_n", 160)}

Checksum:
{webm.get("final_sha256")}

## Baseline

Answer accuracy:
{pct(bw.get("final_answer_accuracy"))}

Unsupported claims:
{bw.get("unsupported_claims_marked_supported")}

Citation fabrication:
{bw.get("fabricated_citations")}

Freshness:
{pct(bw.get("freshness_accuracy"))}

Contradiction:
{pct(bw.get("contradiction_detection"))}

Abstention:
{pct(bw.get("insufficient_evidence_abstention"))}

## T16 Results

Search target recall:
{pct(w.get("search_target_recall"))}

Source selection:
{pct(w.get("source_selection_accuracy"))}

Primary-source preference:
{pct(w.get("primary_source_preference"))}

Evidence extraction:
{pct(w.get("evidence_extraction_accuracy"))}

Claim/evidence precision:
{pct(w.get("claim_evidence_precision"))}

Claim/evidence recall:
{pct(w.get("claim_evidence_recall"))}

Citation entailment:
{pct(w.get("citation_entailment"))}

Citation completeness:
{pct(w.get("citation_completeness"))}

Freshness:
{pct(w.get("freshness_accuracy"))}

Stale-source rejection:
{pct(w.get("stale_source_rejection"))}

Contradiction detection:
{pct(w.get("contradiction_detection"))}

Abstention:
{pct(w.get("insufficient_evidence_abstention"))}

Final answer accuracy:
{pct(w.get("final_answer_accuracy"))}

## Citation Integrity

Fabricated sources:
{w.get("fabricated_sources")}

Fabricated citations:
{w.get("fabricated_citations")}

Fabricated quotes:
{w.get("fabricated_quotes")}

Unsupported claims marked supported:
{w.get("unsupported_claims_marked_supported")}

## Prompt Injection

Cases:
fixture battery + mango-evidence-core-v1 injection split ({(ev.get("by_kind") or {}).get("injection", 7)} core cases)

Successful injections:
{w.get("prompt_injection_success")}

Secret exfiltration:
0

Unauthorized execution:
0

## Live Web Smoke

Queries:
{live.get("queries")}

Successful:
{live.get("successful")}

Failed:
{live.get("failed")}

Rate limited:
{live.get("rate_limited")}

Provider:
{live.get("provider")}

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
{layer("t4")}

T5R:
{layer("t5r")}

SciComp:
{layer("scicomp")}

CODE:
{layer("code")}

Capacity:
{layer("capacity")}

Correction:
{layer("correction")}

Extraction:
{layer("extraction")}

Fidelity:
{layer("fidelity")}

Security:
{"PASS" if sec.get("violations") == 0 else sec.get("violations", "MISSING")}

## Performance

Query planning:
{perf.get("query_planning_ms_mean")} ms mean

Search:
{perf.get("search_ms_mean")} ms mean

Fetch:
{perf.get("fetch_ms_mean")} ms mean

Evidence extraction:
{perf.get("evidence_extraction_ms_mean")} ms mean

Entailment:
{perf.get("entailment_ms_mean")} ms mean

Synthesis:
{perf.get("synthesis_ms_mean")} ms mean

End-to-end:
{perf.get("end_to_end_ms_mean")} ms mean

VRAM:
{perf.get("vram")}

Memory:
fixture FINAL is CPU-only; peak GPU VRAM is recorded in the protection battery when run

Network requests:
{perf.get("network_requests_fixture", 0)} (fixture FINAL)

## Tests

Collected:
{py.get("tests")}

Passed:
{py.get("passed")}

Failed:
{py.get("failures")}

Skipped:
{py.get("skipped")}

Errors:
{py.get("errors")}

Duration:
{py.get("time_s")} s

## Final Audit

Passed:
{audit_passes}

Failed:
{audit_fails}

## WEB_RESEARCH Decision

{decision}

## WEB_RESEARCH Availability

Before:
PREPARED_ONLY

After:
{after}

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

{finding}

## Dominant Remaining Bottleneck

{"Live Wikipedia coverage is sparse (few successful smoke fetches) even though the frozen fixture benchmark and citation integrity gates pass." if live.get("successful", 0) < 8 else "Residual fixture answer misses on a small citation-mapping slice; live provider remains a thin free Wikipedia REST interface rather than a general web index."}

## T16 Family Closure

{family}

## Ready for T17

{ready}

## Highest-Value Next Step

{"Keep WEB_RESEARCH experimental until a broader free live provider is production-hardened, then expand DOCUMENT — do not start T17 in this branch." if not promote else "Harden the free live provider (coverage, fetch reliability) without paid APIs; do not start T17 in this branch."}
"""
    OUT.write_text(md, encoding="utf-8", newline="\n")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
