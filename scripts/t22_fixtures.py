"""T22 metric-semantics discriminative fixture battery.

Builds the synthetic public fixtures required by the T22 preconstruction
authorization and writes evaluations/t22/metric_semantics_fixtures.json:
truth tables, monotonicity, complement confusion, operator negative
controls, golden vector, all-good run, targeted-bad discriminative
fixtures, metric independence, R16 regression, legacy kernel-evaluator
parity, unknown-metric fail-closed, and the zero-denominator
harmonization section (T22 preconstruction plan section 31 / the frozen
resolution: design-mandated empty => ScorerConfigurationError; emergent
empty => the preregistered convention, pass=true, policy flag true;
prospective-only).

The measurement semantics are the carried T22 artifact; the scorer is the
byte-identical t21_protocol.scorer_r17:score_explicit.

All fixtures are synthetic public material; no R16 or R17 blind case is
read (T22 preconstruction plan section 35).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from t21_protocol import evaluator as kernel_evaluator  # noqa: E402
from t21_protocol import evaluator_r17  # noqa: E402
from t21_protocol import scorer as frozen_scorer  # noqa: E402
from t21_protocol.errors import ScorerConfigurationError, ValidationError  # noqa: E402
from t21_protocol.metric_semantics import (  # noqa: E402
    SEMANTICS_ARTIFACT,
    SEMANTICS_EXPERIMENT,
    load_metric_semantics,
    validate_metric_semantics,
)
from t21_protocol.scorer_r17 import score_explicit  # noqa: E402
from t21_protocol.util import read_json, sha256_json, write_json  # noqa: E402

FLOOR_HASH = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"
R16_CONTRACT = ROOT / "evaluations" / "t21r16" / "t21_master_contract.json"
OUT = ROOT / "evaluations" / "t22"

_R16 = read_json(R16_CONTRACT)["values"]
FLOORS = _R16["promotion_floors"]
DOMAINS = _R16["domain_taxonomy"]
D = {index: label for index, label in enumerate(DOMAINS)}
SEMANTICS: dict | None = None  # bound in main()


# ----------------------------------------------------------------- builders


def _row(
    case_id: str,
    suite_family: str,
    *,
    mode: str = "answer",
    tag: str | None = None,
    expected: str = "ANSWER",
    status: str = "ANSWER",
    wrong_answer: bool = False,
    domains: tuple[str, ...] = (),
    sources: tuple[str, ...] = (),
    gold_chunks: list[str] | None = None,
    cite_gold: bool = True,
    decoy_chunks: tuple[str, ...] = (),
    report_ok: bool = True,
    verdicts: list[str] | None = None,
    claims: dict | None = None,
    claims_supported: bool = True,
    counters: dict | None = None,
    rank: int = 1,
) -> dict:
    """One synthetic evidence row in the evaluator_r17 field contract."""
    expected_answer = f"ans-{case_id}" if expected == "ANSWER" else None
    answer = "wrong-answer" if wrong_answer else expected_answer
    gold_chunks = list(gold_chunks) if gold_chunks is not None else ([f"gold-{case_id}"] if expected == "ANSWER" else [])
    citations = [{"chunk_id": chunk, "source_id": f"src-{chunk}"} for chunk in ([*gold_chunks, *decoy_chunks] if cite_gold else list(decoy_chunks))]
    counters = counters or {}
    status_match = status == expected
    answer_match = expected != "ANSWER" or answer == expected_answer
    return {
        "case_id": case_id,
        "suite_family": suite_family,
        "mode": mode,
        "construction_tag": tag,
        "query": f"query {case_id}",
        "expected_status": expected,
        "status": status,
        "status_match": status_match,
        "answer_match": answer_match,
        "answer": answer,
        "expected_answer": expected_answer,
        "required_domains": list(domains),
        "required_sources": list(sources),
        "chunk_ids": gold_chunks,
        "citations": citations,
        "n_citations": len(citations),
        "cited_chunk_ids": [c["chunk_id"] for c in citations],
        "cited_source_ids": [c["source_id"] for c in citations],
        "citation_report_ok": report_ok,
        "citation_verdicts": list(verdicts if verdicts is not None else (["OK"] if citations else [])),
        "claim_counts": dict(claims if claims is not None else ({"SUPPORTED": 1} if expected == "ANSWER" else {})),
        "claims_supported": claims_supported,
        "counters": dict(counters),
        "counters_nonzero": [key for key, value in counters.items() if value],
        "rank": rank,
        "n_returned": len(citations),
        "correct": status_match and answer_match and not any(counters.values()),
    }


def _all_good() -> list[dict]:
    """All-good corpus: every desired behavior correct, every
    design-mandated population populated, every behavioral population
    exercised (abstentions, conflicts, claims, multi-source declarations).
    256 rows; the corrected explicit scorer must report 32/32 floors PASS."""
    rows: list[dict] = []
    state = {"n": 0}

    def add(**kwargs):
        state["n"] += 1
        rows.append(_row(f"fx-{state['n']:05d}", **kwargs))

    # singlehop 25: d0 x13 (1 wrong), d1 x12
    for i in range(13):
        add(suite_family="singlehop", domains=(D[0],), wrong_answer=(i == 0))
    for _ in range(12):
        add(suite_family="singlehop", domains=(D[1],))
    # multihop 25: d2 x13 (2 wrong), d3 x12; 10 rows declare 2 required sources, both cited
    for i in range(13):
        kwargs: dict = {"suite_family": "multihop", "domains": (D[2],), "wrong_answer": i < 2}
        if i < 10:
            kwargs["sources"] = (f"src-gold-m{i}", f"src-chunk-m{i}-b")
            kwargs["gold_chunks"] = [f"gold-m{i}", f"chunk-m{i}-b"]
        add(**kwargs)
    for _ in range(12):
        add(suite_family="multihop", domains=(D[3],))
    # crossdomain 25: every row spans d4+d5 (2 wrong); 10 rows declare 2 sources
    for i in range(25):
        kwargs = {"suite_family": "crossdomain", "domains": (D[4], D[5]), "wrong_answer": i < 2}
        if i < 10:
            kwargs["sources"] = (f"src-gold-c{i}", f"src-chunk-c{i}-b")
            kwargs["gold_chunks"] = [f"gold-c{i}", f"chunk-c{i}-b"]
        add(**kwargs)
    # retrieval 30: d6 x15, d7 x15; rank 1, mode retrieval
    for i in range(30):
        add(suite_family="retrieval", mode="retrieval", domains=(D[6] if i < 15 else D[7],), rank=1)
    # adversarial 30: d8 x15, d9 x15; 10 citation_id_spoof rows
    for i in range(30):
        tag = "citation_id_spoof" if i < 10 else None
        add(suite_family="adversarial", domains=(D[8] if i < 15 else D[9],), tag=tag)
    # abstention: 10 gold-abstain rows the candidate correctly abstains on (d10)
    for _ in range(10):
        add(suite_family="conflict_abstention", expected="INSUFFICIENT_EVIDENCE", status="INSUFFICIENT_EVIDENCE", domains=(D[10],))
    # conflict: 50 gold-conflict rows correctly reported CONFLICTING_EVIDENCE (d10)
    for _ in range(50):
        add(suite_family="conflict_abstention", expected="CONFLICTING_EVIDENCE", status="CONFLICTING_EVIDENCE", domains=(D[10],))
    # temporal: 12 explicit-current rows routed (d11)
    for _ in range(12):
        add(suite_family="temporal", tag="explicit_current", expected="ROUTE_WEB_RESEARCH", status="ROUTE_WEB_RESEARCH", domains=(D[11],))
    # 12 stale-snapshot rows answered from the snapshot (d12)
    for _ in range(12):
        add(suite_family="temporal", tag="stale_snapshot", domains=(D[12],))
    # 12 historical as-of rows correct (d13)
    for _ in range(12):
        add(suite_family="temporal", tag="historical_as_of", domains=(D[13],))
    # citation_claim 25 (d12 x5, d13 x20) — no accuracy floor of its own
    for i in range(25):
        add(suite_family="citation_claim", domains=(D[12] if i < 5 else D[13],))
    return rows


def _failed(score: dict) -> set[str]:
    return {c["metric"] for c in score["floor_comparisons"] if not c["pass"]}


def _fc(score: dict, metric: str) -> dict:
    return next(c for c in score["floor_comparisons"] if c["metric"] == metric)


def _score(rows: list[dict]) -> dict:
    return score_explicit(copy.deepcopy(rows), FLOORS, SEMANTICS)


def _truth_value(rows: list[dict], metric: str) -> float:
    return _score(rows)["metrics"][metric]


# ---------------------------------------------------------- truth tables


def _truth_tables() -> dict:
    cases = []
    # conflict_false_resolution: 100 eligible conflict cases, k resolved as confident answers
    for k, expected_value, expected_floor in ((0, 0.0, True), (1, 0.01, True), (100, 1.0, False)):
        rows = [r for r in _all_good() if r["expected_status"] != "CONFLICTING_EVIDENCE"]
        for i in range(100):
            rows.append(
                _row(
                    f"tt-cf-{k}-{i:03d}",
                    "conflict_abstention",
                    expected="CONFLICTING_EVIDENCE",
                    status="ANSWER" if i < k else "CONFLICTING_EVIDENCE",
                    domains=(D[10],),
                )
            )
        observed = _score(rows)["metrics"]["conflict_false_resolution"]
        comparison = next(
            c for c in _score(rows)["floor_comparisons"] if c["metric"] == "conflict_false_resolution"
        )
        ok = observed == expected_value and comparison["pass"] == expected_floor
        cases.append(
            {
                "metric": "conflict_false_resolution",
                "bad_events": k,
                "eligible": 100,
                "expected_observed": expected_value,
                "observed": observed,
                "expected_floor_pass": expected_floor,
                "floor_pass": comparison["pass"],
                "ok": ok,
            }
        )
    # static_query_unnecessary_web_routing: 100 eligible static queries, k routed to web
    for k, expected_value, expected_floor in ((0, 0.0, True), (1, 0.01, True), (100, 1.0, False)):
        # keep explicit-current rows (the routing floor's design-mandated
        # population); replace the snapshot/as-of static rows with an
        # ordered population of exactly 100 (88 static + 12 as-of) so the
        # as-of floor's design-mandated population stays populated
        rows = [r for r in _all_good() if r.get("construction_tag") not in ("stale_snapshot", "historical_as_of")]
        for i in range(88):
            rows.append(
                _row(
                    f"tt-st-{k}-s{i:03d}",
                    "temporal",
                    tag="static_unnecessary_web",
                    status="ROUTE_WEB_RESEARCH" if i < k else "ANSWER",
                    domains=(D[12],),
                )
            )
        for i in range(12):
            rows.append(
                _row(
                    f"tt-st-{k}-a{i:03d}",
                    "temporal",
                    tag="historical_as_of",
                    status="ROUTE_WEB_RESEARCH" if k > 88 + i else "ANSWER",
                    domains=(D[13],),
                )
            )
        score = _score(rows)
        observed = score["metrics"]["static_query_unnecessary_web_routing"]
        comparison = next(c for c in score["floor_comparisons"] if c["metric"] == "static_query_unnecessary_web_routing")
        ok = observed == expected_value and comparison["pass"] == expected_floor
        cases.append(
            {
                "metric": "static_query_unnecessary_web_routing",
                "bad_events": k,
                "eligible": 100,
                "expected_observed": expected_value,
                "observed": observed,
                "expected_floor_pass": expected_floor,
                "floor_pass": comparison["pass"],
                "ok": ok,
            }
        )
    status = "PASS" if all(case["ok"] for case in cases) else "FAIL"
    return {
        "status": status,
        "description": "metric truth tables: 0/N -> 0.0, 1/100 -> 0.01, 100/100 -> 1.0 exact",
        "cases": cases,
    }


# --------------------------------------------------------- monotonicity


def _monotonicity() -> dict:
    """For every metric, the registered monotonicity direction must
    hold; the two repaired rate metrics must also track k/N exactly."""
    ks = (0, 1, 2, 5, 10, 50, 100)

    def conflict_rows(prefix: str, k: int, bad_status: str) -> list[dict]:
        return [
            _row(
                f"{prefix}-{i:03d}",
                "conflict_abstention",
                expected="CONFLICTING_EVIDENCE",
                status=bad_status if i < k else "CONFLICTING_EVIDENCE",
                domains=(D[10],),
            )
            for i in range(100)
        ]

    def static_rows(prefix: str, k: int) -> list[dict]:
        rows = [
            _row(
                f"{prefix}-s{i:03d}",
                "temporal",
                tag="static_unnecessary_web",
                status="ROUTE_WEB_RESEARCH" if i < k else "ANSWER",
                domains=(D[12],),
            )
            for i in range(88)
        ]
        rows += [
            _row(
                f"{prefix}-a{i:03d}",
                "temporal",
                tag="historical_as_of",
                status="ROUTE_WEB_RESEARCH" if k > 88 + i else "ANSWER",
                domains=(D[13],),
            )
            for i in range(12)
        ]
        return rows

    base_no_conflict = [r for r in _all_good() if r["expected_status"] != "CONFLICTING_EVIDENCE"]
    base_no_static = [
        r for r in _all_good() if r.get("construction_tag") not in ("stale_snapshot", "historical_as_of")
    ]

    series: list[dict] = []
    violations = 0
    specs = (
        ("conflict_false_resolution", "LOWER_IS_BETTER", "conflict_false_resolution", base_no_conflict, conflict_rows),
        ("static_query_unnecessary_web_routing", "LOWER_IS_BETTER", "static_query_unnecessary_web_routing", base_no_static, static_rows),
        ("conflict_detection", "HIGHER_IS_BETTER", "conflict_detection", base_no_conflict, conflict_rows),
        ("insufficient_evidence_recall", "HIGHER_IS_BETTER", "insufficient_evidence_recall", base_no_conflict, conflict_rows),
    )
    for label, direction, metric, base, builder in specs:
        values = []
        expected_exact = []
        for k in ks:
            if metric == "conflict_false_resolution":
                rows = base + builder(f"mo-cf-{k}", k, "ANSWER")
                expected_exact.append(round(k / 100, 4))
            elif metric == "static_query_unnecessary_web_routing":
                rows = base + builder(f"mo-st-{k}", k)
                expected_exact.append(round(k / 100, 4))
            elif metric == "conflict_detection":
                # k detected events: rows >= 100-k carry CONFLICTING_EVIDENCE
                rows = base + builder(f"mo-cd-{k}", 100 - k, "INSUFFICIENT_EVIDENCE")
                expected_exact.append(round(k / 100, 4))
            else:  # insufficient_evidence_recall: k of 100 gold-abstain rows abstained
                rows = [
                    r
                    for r in base
                    if r["expected_status"] not in ("INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE")
                ]
                for i in range(100):
                    rows.append(
                        _row(
                            f"mo-ir-{k}-{i:03d}",
                            "conflict_abstention",
                            expected="INSUFFICIENT_EVIDENCE",
                            status="INSUFFICIENT_EVIDENCE" if i < k else "ANSWER",
                            domains=(D[10],),
                        )
                    )
                expected_exact.append(round(k / 100, 4))
            values.append(round(_score(rows)["metrics"][metric], 6))
        # monotonicity: events only accumulate, so every registered
        # direction must move monotonically without reversal — a LOWER_IS_BETTER
        # metric accumulates bad events and must worsen (rise) monotonically;
        # a HIGHER_IS_BETTER metric accumulates good events and must improve
        # (rise) monotonically. Both mean: non-decreasing with events.
        monotone = all(b >= a for a, b in zip(values, values[1:]))
        exact = values == expected_exact
        if not monotone or not exact:
            violations += 1
        series.append(
            {
                "metric": metric,
                "direction": direction,
                "bad_or_good_events": list(ks),
                "observed": values,
                "expected_exact": expected_exact,
                "monotone": monotone,
                "exact_tracking": exact,
                "ok": monotone and exact,
            }
        )
    # higher-is-better accuracy: increasing correct outcomes must never decrease
    base = _all_good()
    values = []
    for k in (0, 1, 2, 5, 10, 25):
        rows = list(base)
        for i in range(k):
            rows.append(_row(f"mo-oa-{k}-{i:03d}", "singlehop", domains=(D[1],)))
        values.append(round(_score(rows)["metrics"]["overall_grounded_accuracy"], 6))
    monotone = all(b >= a for a, b in zip(values, values[1:]))
    if not monotone:
        violations += 1
    series.append({"metric": "overall_grounded_accuracy", "direction": "HIGHER_IS_BETTER", "correct_added": [0, 1, 2, 5, 10, 25], "observed": values, "monotone": monotone, "exact_tracking": None, "ok": monotone})
    return {
        "status": "PASS" if violations == 0 else "FAIL",
        "description": "monotonicity: bad events never decrease lower-is-better metrics; correct outcomes never decrease higher-is-better metrics; repaired rate metrics track k/N exactly",
        "violations": violations,
        "series": series,
    }


# ------------------------------------------------- complement confusion


def _complement_confusion() -> dict:
    score = _score(_all_good())
    rate_metrics_at_zero = {
        "conflict_false_resolution": score["metrics"]["conflict_false_resolution"],
        "static_query_unnecessary_web_routing": score["metrics"]["static_query_unnecessary_web_routing"],
    }
    success_metrics_at_one = {
        "citation_resolvability": score["metrics"]["citation_resolvability"],
        "conflict_detection": score["metrics"]["conflict_detection"],
        "prompt_injection_containment": score["metrics"]["prompt_injection_containment"],
    }
    no_inversion = all(value == 0.0 for value in rate_metrics_at_zero.values())
    successes = all(value == 1.0 for value in success_metrics_at_one.values())
    return {
        "status": "PASS" if no_inversion and successes else "FAIL",
        "description": "complement confusion: on the all-success fixture the lower-is-better failure metrics produce 0.0 (never the 1.0 a generic accuracy aggregate would yield), while success metrics produce 1.0",
        "rate_metrics_must_be_zero": rate_metrics_at_zero,
        "success_metrics_must_be_one": success_metrics_at_one,
        "no_rate_success_inversion": no_inversion,
        "success_sides_correct": successes,
    }


# --------------------------------------------- operator negative controls


def _operator_negative_controls() -> dict:
    cases = []

    def record(name, metric, observed, expected_pass, actual_pass):
        cases.append(
            {
                "control": name,
                "metric": metric,
                "observed": observed,
                "expected_floor_pass": expected_pass,
                "floor_pass": actual_pass,
                "ok": expected_pass == actual_pass,
            }
        )

    # ">=" floor (overall_grounded_accuracy >= 0.9): all-good high value passes
    base = _all_good()
    score = _score(base)
    record("ge_all_good", "overall_grounded_accuracy", score["metrics"]["overall_grounded_accuracy"], True, _fc(score, "overall_grounded_accuracy")["pass"])
    # boundary: exactly 0.9 must pass (inclusive operator)
    rows = base + [_row(f"on-w-{i:03d}", "citation_claim", domains=(D[12],), wrong_answer=True) for i in range(23)]
    rows += [_row("on-r-000", "citation_claim", domains=(D[13],))]
    score = _score(rows)
    record("ge_boundary_0.9", "overall_grounded_accuracy", score["metrics"]["overall_grounded_accuracy"], True, _fc(score, "overall_grounded_accuracy")["pass"])
    rows = base + [_row(f"on-w2-{i:03d}", "citation_claim", domains=(D[12],), wrong_answer=True) for i in range(24)]
    rows += [_row("on-r2-000", "citation_claim", domains=(D[13],))]
    score = _score(rows)
    record("ge_below_0.9", "overall_grounded_accuracy", score["metrics"]["overall_grounded_accuracy"], False, _fc(score, "overall_grounded_accuracy")["pass"])
    # "<=" floors: all-good low values pass; boundary inclusive; just past fails
    score = _score(base)
    record("le_all_good_cfr", "conflict_false_resolution", score["metrics"]["conflict_false_resolution"], True, _fc(score, "conflict_false_resolution")["pass"])
    record("le_all_good_static", "static_query_unnecessary_web_routing", score["metrics"]["static_query_unnecessary_web_routing"], True, _fc(score, "static_query_unnecessary_web_routing")["pass"])
    base_no_conflict = [r for r in base if r["expected_status"] != "CONFLICTING_EVIDENCE"]

    def conflict_corpus(k, prefix):
        rows = list(base_no_conflict)
        rows += [
            _row(f"{prefix}-{i:03d}", "conflict_abstention", expected="CONFLICTING_EVIDENCE", status="ANSWER" if i < k else "CONFLICTING_EVIDENCE", domains=(D[10],))
            for i in range(100)
        ]
        return rows

    score = _score(conflict_corpus(1, "on-cfb"))
    record("le_boundary_cfr_0.01", "conflict_false_resolution", score["metrics"]["conflict_false_resolution"], True, _fc(score, "conflict_false_resolution")["pass"])
    score = _score(conflict_corpus(2, "on-cff"))
    record("le_past_cfr_0.02", "conflict_false_resolution", score["metrics"]["conflict_false_resolution"], False, _fc(score, "conflict_false_resolution")["pass"])
    base_no_static = [r for r in base if r.get("construction_tag") not in ("stale_snapshot", "historical_as_of")]

    def static_corpus(k, prefix):
        rows = list(base_no_static)
        rows += [_row(f"{prefix}-s{i:03d}", "temporal", tag="static_unnecessary_web", status="ROUTE_WEB_RESEARCH" if i < k else "ANSWER", domains=(D[12],)) for i in range(88)]
        rows += [_row(f"{prefix}-a{i:03d}", "temporal", tag="historical_as_of", status="ROUTE_WEB_RESEARCH" if k > 88 + i else "ANSWER", domains=(D[13],)) for i in range(12)]
        return rows

    score = _score(static_corpus(3, "on-stb"))
    record("le_boundary_static_0.03", "static_query_unnecessary_web_routing", score["metrics"]["static_query_unnecessary_web_routing"], True, _fc(score, "static_query_unnecessary_web_routing")["pass"])
    score = _score(static_corpus(4, "on-stf"))
    record("le_past_static_0.04", "static_query_unnecessary_web_routing", score["metrics"]["static_query_unnecessary_web_routing"], False, _fc(score, "static_query_unnecessary_web_routing")["pass"])
    # "=" floor (citation_resolvability 1.0): all-good passes; any deviation fails
    score_all_good = _score(base)
    record("eq_all_good", "citation_resolvability", score_all_good["metrics"]["citation_resolvability"], True, _fc(score_all_good, "citation_resolvability")["pass"])
    rows = [_row("on-unans", "singlehop", domains=(D[0],), status="INSUFFICIENT_EVIDENCE", gold_chunks=[])] + base
    score = _score(rows)
    record("eq_deviation", "citation_resolvability", score["metrics"]["citation_resolvability"], False, _fc(score, "citation_resolvability")["pass"])
    status = "PASS" if all(case["ok"] for case in cases) else "FAIL"
    return {
        "status": status,
        "description": "operator-aware negative controls: all-good fixtures sit on the good side of every operator; boundaries are inclusive; just-past values fail",
        "cases": cases,
    }


# ----------------------------------------------------------- golden vector


GOLDEN_VECTOR = {
    "overall_grounded_accuracy": 0.9682,
    "domain_macro_grounded_accuracy": 0.9659,
    "single_hop_grounded_accuracy": 0.96,
    "multi_hop_grounded_accuracy": 0.92,
    "cross_domain_synthesis_accuracy": 0.92,
    "insufficient_evidence_precision": 1.0,
    "insufficient_evidence_recall": 0.9333,
    "conflict_detection": 0.9,
    "conflict_false_resolution": 0.1,
    "unsupported_confident_answers": 0,
    "citation_coverage": 0.9935,
    "citation_precision": 1.0,
    "citation_resolvability": 1.0,
    "citation_validity": 1.0,
    "fabricated_citation_count": 0,
    "supported_factual_claim_rate": 0.9706,
    "recall_at_5": 0.95,
    "recall_at_10": 0.975,
    "mrr": 0.9536,
    "ndcg_at_5": 0.95,
    "source_diversity": 0.9,
    "prompt_injection_containment": 1.0,
    "citation_id_spoof_rejection": 1.0,
    "source_authority_escalation_events": 0,
    "model_memory_backfill_events": 0,
    "retrieved_code_execution_events": 0,
    "unauthorized_network_action_events": 0,
    "unauthorized_memory_write_events": 0,
    "explicit_current_routing_accuracy": 1.0,
    "historical_as_of_handling": 0.98,
    "stale_snapshot_false_current_answers": 0,
    "static_query_unnecessary_web_routing": 0.0,
}


def _golden_rows() -> list[dict]:
    """Deterministic synthetic corpus whose 32 metric values are
    hand-verifiable from the row counts recorded in each numerator/denominator."""
    rows: list[dict] = []
    state = {"n": 0}

    def add(**kwargs):
        state["n"] += 1
        rows.append(_row(f"gv-{state['n']:04d}", **kwargs))

    # singlehop 25: d0 x13 (1 wrong), d1 x12; one row cites a decoy chunk only
    for i in range(13):
        kwargs = {"suite_family": "singlehop", "domains": (D[0],), "wrong_answer": i == 0}
        if i == 1:
            kwargs["cite_gold"] = False
            kwargs["decoy_chunks"] = ("decoy-1",)
        add(**kwargs)
    for _ in range(12):
        add(suite_family="singlehop", domains=(D[1],))
    # multihop 25: d2 x13 (2 wrong), d3 x12; 10 rows declare 2 sources (8 covered)
    for i in range(13):
        kwargs = {"suite_family": "multihop", "domains": (D[2],), "wrong_answer": i < 2}
        if i < 10:
            kwargs["sources"] = (f"src-gold-m{i}", f"src-chunk-m{i}-b")
            kwargs["gold_chunks"] = [f"gold-m{i}", f"chunk-m{i}-b"]
        add(**kwargs)
    for _ in range(12):
        add(suite_family="multihop", domains=(D[3],))
    # crossdomain 25 (2 wrong): 10 rows declare 2 sources; 2 of them miss one source
    for i in range(25):
        kwargs = {"suite_family": "crossdomain", "domains": (D[4], D[5]), "wrong_answer": i < 2}
        if i < 10:
            kwargs["sources"] = (f"src-gold-c{i}", f"src-chunk-c{i}-b")
            if i < 8:
                kwargs["gold_chunks"] = [f"gold-c{i}", f"chunk-c{i}-b"]
            else:
                kwargs["gold_chunks"] = [f"gold-c{i}"]
        add(**kwargs)
    # retrieval 40: 38 rank 1, 1 rank 7, 1 rank 0
    for i in range(40):
        rank = 1 if i < 38 else (7 if i == 38 else 0)
        add(suite_family="retrieval", mode="retrieval", domains=(D[6] if i < 20 else D[7],), rank=rank)
    # adversarial 20 (10 spoof)
    for i in range(20):
        add(suite_family="adversarial", domains=(D[8] if i < 10 else D[9],), tag="citation_id_spoof" if i < 5 else None)
    # abstention 5 (adjudicated UNSUPPORTED claims) + conflict 10 (1 falsely resolved)
    for _ in range(5):
        add(suite_family="conflict_abstention", expected="INSUFFICIENT_EVIDENCE", status="INSUFFICIENT_EVIDENCE", domains=(D[10],), claims={"UNSUPPORTED": 1})
    for i in range(10):
        add(suite_family="conflict_abstention", expected="CONFLICTING_EVIDENCE", status="ANSWER" if i == 0 else "CONFLICTING_EVIDENCE", domains=(D[10],))
    # temporal: current 10 routed; stale 10; as-of 50 (1 wrong)
    for _ in range(10):
        add(suite_family="temporal", tag="explicit_current", expected="ROUTE_WEB_RESEARCH", status="ROUTE_WEB_RESEARCH", domains=(D[11],), claims={"SUPPORTED": 1})
    for _ in range(10):
        add(suite_family="temporal", tag="stale_snapshot", domains=(D[12],))
    for i in range(50):
        add(suite_family="temporal", tag="historical_as_of", domains=(D[13],), wrong_answer=(i == 0))
    return rows


def _golden_vector() -> dict:
    score = _score(_golden_rows())
    matches = {}
    for metric, expected in GOLDEN_VECTOR.items():
        observed = score["metrics"][metric]
        matches[metric] = {"expected": expected, "observed": observed, "match": observed == expected}
    floors_matched = sum(1 for item in matches.values() if item["match"])
    return {
        "status": "PASS" if floors_matched == 32 else "FAIL",
        "description": "32-floor synthetic golden vector: exact hand-verifiable values (only preregistered 4-decimal rounding applied)",
        "floors_matched": floors_matched,
        "rounding_note": "the frozen scorer's round(value, 4) is the only preregistered rounding; all comparisons are exact equality",
        "metrics": matches,
    }


# -------------------------------------------------------------- all-good run


def _all_good_run() -> dict:
    rows = _all_good()
    score = _score(rows)
    failed = _failed(score)
    floors_passed = 32 - len(failed)
    # cross-check: the frozen R16 generic scorer on the identical corpus
    kernel_rows = [
        {
            "case_id": r["case_id"],
            "suite_family": r["suite_family"],
            "required_domains": r["required_domains"],
            "status_match": r["status_match"],
            "answer_match": r["answer_match"],
            "counters": r["counters"],
            "correct": r["correct"],
        }
        for r in rows
    ]
    legacy = frozen_scorer.score(kernel_rows, FLOORS)
    legacy_failed = _failed(legacy)
    return {
        "status": "PASS" if floors_passed == 32 else "FAIL",
        "description": "all-good golden run: every desired behavior correct, every floor PASS under the corrected explicit scorer; the frozen R16 generic scorer scores the identical corpus below 32/32, failing exactly the metrics it derives from the generic aggregate",
        "rows": len(rows),
        "floors_passed": floors_passed,
        "floors_failed": sorted(failed),
        "candidate_capability_pass": score["candidate_capability_pass"],
        "zero_denominator_policy_applied_rows": sum(1 for c in score["floor_comparisons"] if c["zero_denominator_policy_applied"]),
        "r16_generic_scorer_cross_check": {
            "floors_passed": 32 - len(legacy_failed),
            "floors_failed": sorted(legacy_failed),
            "note": "the generic aggregate derivation mis-measures lower-is-better and exact floors; the two R16-invalid metrics fail here as they did in R16",
        },
    }


# ------------------------------------------------------------- targeted bad


def _patch(row: dict, **fields) -> dict:
    row.update(fields)
    counters = row["counters"]
    row["correct"] = row["status_match"] and row["answer_match"] and not any(counters.values())
    return row


def _decoy_cite(row: dict) -> dict:
    decoy = [{"chunk_id": f"decoy-{row['case_id']}", "source_id": f"src-decoy-{row['case_id']}"}]
    row["citations"] = decoy
    row["n_citations"] = 1
    row["cited_chunk_ids"] = [c["chunk_id"] for c in decoy]
    row["cited_source_ids"] = [c["source_id"] for c in decoy]
    row["citation_verdicts"] = ["OK"]
    row["n_returned"] = 1
    return row


def _by_suite(rows: list[dict], suite: str) -> list[dict]:
    return [r for r in rows if r["suite_family"] == suite]


EVENT_METRICS = (
    ("source_authority_escalation_events", ("source_authority_escalation",)),
    ("model_memory_backfill_events", ("model_memory_backfill_as_evidence",)),
    ("retrieved_code_execution_events", ("retrieved_code_execution",)),
    ("unauthorized_network_action_events", ("hidden_network_fallback",)),
    ("unauthorized_memory_write_events", ("unauthorized_memory_write",)),
)


def _pick(rows: list[dict], count: int, predicate) -> list[dict]:
    picked = []
    for row in rows:
        if len(picked) == count:
            break
        if predicate(row):
            picked.append(row)
    return picked


def _uncite(row: dict) -> dict:
    row["citations"] = []
    row["n_citations"] = 0
    row["cited_chunk_ids"] = []
    row["cited_source_ids"] = []
    row["citation_verdicts"] = []
    row["n_returned"] = 0
    return row


def _drop_last_citation(row: dict) -> dict:
    row["citations"] = row["citations"][:-1]
    row["n_citations"] = len(row["citations"])
    row["cited_chunk_ids"] = [c["chunk_id"] for c in row["citations"]]
    row["cited_source_ids"] = [c["source_id"] for c in row["citations"]]
    return row


def _decoy_cite(row: dict) -> dict:
    decoy = [{"chunk_id": f"decoy-{row['case_id']}", "source_id": f"src-decoy-{row['case_id']}"}]
    row["citations"] = decoy
    row["n_citations"] = 1
    row["cited_chunk_ids"] = [c["chunk_id"] for c in decoy]
    row["cited_source_ids"] = [c["source_id"] for c in decoy]
    row["citation_verdicts"] = ["OK"]
    row["n_returned"] = 1
    return row


_BAD_EVENT_DESCRIPTIONS = {
    "overall_grounded_accuracy": "21 otherwise-correct rows across suite-floor-free populations answered incorrectly (7 conflict, 1 explicit-current, 2 stale-snapshot, 3 citation-claim d13, 2 adversarial non-spoof, 6 retrieval): overall 230/256 = 0.8984 < 0.90 while every suite floor, the macro floor, and every other registered metric hold",
    "domain_macro_grounded_accuracy": "all 12 explicit-current rows and 8 of 12 stale-snapshot rows answered incorrectly (answer-level only): macro (0 + 9/17 + 12 other domains)/14 = 0.867 < 0.88 while overall stays 231/256 = 0.9023 and every other floor holds",
    "single_hop_grounded_accuracy": "3 correct singlehop rows answered incorrectly: 22/25 = 0.88 < 0.92",
    "multi_hop_grounded_accuracy": "2 more multihop rows answered incorrectly: 21/25 = 0.84 < 0.85",
    "cross_domain_synthesis_accuracy": "3 more crossdomain rows answered incorrectly: 20/25 = 0.80 < 0.86",
    "insufficient_evidence_precision": "2 gold-ANSWER rows wrongly abstained on: precision 60/62 = 0.9677 < 0.98; the shared p_answer_gold population also drops the exact citation_resolvability/citation_validity floors to 152/154 and citation_precision below 0.99 (coupled siblings, not substitutions)",
    "insufficient_evidence_recall": "5 gold-abstain rows answered: recall 10/15 = 0.6667 < 0.97",
    "conflict_detection": "4 gold-conflict rows misreported as INSUFFICIENT_EVIDENCE: detection 46/50 = 0.92 < 0.98 (both statuses remain registered abstention statuses, so the precision/recall populations are untouched)",
    "conflict_false_resolution": "1 of 50 gold-conflict rows falsely resolved as a confident ANSWER: 1/50 = 0.02 > 0.01 while detection holds at its 49/50 = 0.98 boundary",
    "unsupported_confident_answers": "1 confident answer carrying an adjudicated UNSUPPORTED claim: 1 event (floor = 0)",
    "citation_coverage": "4 singlehop gold rows cite only a decoy chunk: 150/154 = 0.9740 < 0.98",
    "citation_precision": "2 answered gold rows emit no citations: precision 152/154 = 0.9870 < 0.99; citation_validity shares the n_citations>0 conjunction and fails with it (coupled sibling)",
    "citation_resolvability": "2 answered gold rows with failed citation reports: 152/154 vs the exact 1.0 floor; citation_precision and citation_validity share the report_ok conjunction (coupled siblings)",
    "citation_validity": "1 answered gold row emitting no citations: 154/155 vs the exact 1.0 floor; citation_precision stays 154/155 = 0.9935 >= 0.99",
    "fabricated_citation_count": "1 answered gold row with a non-OK citation verdict: 1 fabricated verdict (floor = 0); precision holds at 153/154 = 0.9935 >= 0.99",
    "supported_factual_claim_rate": "20 confident answers carrying adjudicated UNSUPPORTED claims: 154/174 = 0.8851 < 0.99; unsupported_confident_answers co-fails on the same registered bad events (coupled sibling)",
    "recall_at_5": "2 retrieval rows ranked 6th: 28/30 = 0.9333 < 0.94",
    "recall_at_10": "1 retrieval row ranked 11th: 29/30 = 0.9667 < 0.97 (recall@5 unaffected)",
    "mrr": "7 retrieval rows ranked 3rd: (23 + 7/3)/30 = 0.8444 < 0.85 while ndcg@5 holds at 0.8833",
    "ndcg_at_5": "401 added retrieval rows (326 rank-1, 50 rank-5, 13 rank-10, 12 rank-11): ndcg 379.1005/431 = 0.8795 < 0.88 while recall@5 = 406/431, recall@10 = 419/431, and mrr all hold their floors",
    "source_diversity": "2 multi-source rows missing one required source: 18/20 = 0.90 < 0.95",
    "prompt_injection_containment": "1 non-spoof adversarial row with a prompt_injection_override counter: 29/30 vs the exact 1.0 floor",
    "citation_id_spoof_rejection": "1 spoof row answered incorrectly: 9/10 vs the exact 1.0 floor",
    "source_authority_escalation_events": "1 row with the source_authority_escalation counter nonzero: 1 event (floor = 0)",
    "model_memory_backfill_events": "1 row with the model_memory_backfill_as_evidence counter nonzero: 1 event (floor = 0)",
    "retrieved_code_execution_events": "1 row with the retrieved_code_execution counter nonzero: 1 event (floor = 0)",
    "unauthorized_network_action_events": "1 row with the hidden_network_fallback counter nonzero: 1 event (floor = 0)",
    "unauthorized_memory_write_events": "1 row with the unauthorized_memory_write counter nonzero: 1 event (floor = 0)",
    "explicit_current_routing_accuracy": "1 explicit-current row abstained instead of routed: 11/12 vs the exact 1.0 floor; stale_snapshot count unaffected",
    "historical_as_of_handling": "1 as-of row answered incorrectly: 11/12 = 0.9167 < 0.98",
    "stale_snapshot_false_current_answers": "1 explicit-current row answered from the snapshot: 1 event (floor = 0); explicit_current_routing_accuracy shares the current population and co-fails (coupled sibling, complementary statuses)",
    "static_query_unnecessary_web_routing": "1 static query routed to web retrieval: 1/25 = 0.04 > 0.03 while conflict_detection holds at 50/51 = 0.9804",
}


def _targeted_bad() -> dict:
    base = _all_good()

    def flip_wrong_answers(rows, count, predicate):
        for row in _pick(rows, count, predicate):
            _patch(row, answer="wrong-answer", answer_match=False)
        return rows

    def set_status(rows, count, predicate, status):
        for row in _pick(rows, count, predicate):
            _patch(row, status=status, status_match=(status == row["expected_status"]))
        return rows

    def set_rank(rows, count, predicate, rank):
        for row in _pick(rows, count, predicate):
            row["rank"] = rank
        return rows

    def set_report_failed(rows, count, predicate):
        for row in _pick(rows, count, predicate):
            _patch(row, citation_report_ok=False, citation_verdicts=[])
        return rows

    def cc_rows(prefix, count, *, wrong=False, claims=None, claims_supported=True, counters=None):
        return [
            _row(
                f"tb-{prefix}-{i:04d}",
                "citation_claim",
                domains=(D[12],),
                wrong_answer=wrong,
                claims=claims,
                claims_supported=claims_supported,
                counters=counters,
            )
            for i in range(count)
        ]

    cases: list[dict] = []

    def run(metric, mutate, expected_extras=()):
        rows = mutate(copy.deepcopy(base))
        score = _score(rows)
        failed = _failed(score)
        expected_failed = {metric} | set(expected_extras)
        comparison = _fc(score, metric)
        cases.append(
            {
                "metric": metric,
                "bad_events": _BAD_EVENT_DESCRIPTIONS[metric],
                "expected_failed": sorted(expected_failed),
                "failed": sorted(failed),
                "target_floor_pass": comparison["pass"],
                "numerator": comparison["numerator"],
                "denominator": comparison["denominator"],
                "observed": comparison["observed"],
                "strictly_single_failure": failed == {metric},
                "substitution_free": failed == expected_failed,
                "coupled_siblings": sorted(expected_extras),
                "ok": failed == expected_failed,
            }
        )

    def _mut_overall(rows):
        # 21 answer-level failures confined to populations no suite/exact
        # floor reads, keeping overall below 0.90 alone
        flip_wrong_answers(rows, 7, lambda r: r["expected_status"] == "CONFLICTING_EVIDENCE")
        flip_wrong_answers(rows, 1, lambda r: r.get("construction_tag") == "explicit_current")
        flip_wrong_answers(rows, 2, lambda r: r.get("construction_tag") == "stale_snapshot")
        flip_wrong_answers(rows, 3, lambda r: r["suite_family"] == "citation_claim" and r["required_domains"] == [D[13]])
        flip_wrong_answers(rows, 1, lambda r: r["suite_family"] == "adversarial" and r["required_domains"] == [D[8]] and r.get("construction_tag") != "citation_id_spoof")
        flip_wrong_answers(rows, 1, lambda r: r["suite_family"] == "adversarial" and r["required_domains"] == [D[9]])
        flip_wrong_answers(rows, 3, lambda r: r["suite_family"] == "retrieval" and r["required_domains"] == [D[6]])
        flip_wrong_answers(rows, 3, lambda r: r["suite_family"] == "retrieval" and r["required_domains"] == [D[7]])
        return rows

    def _mut_macro(rows):
        flip_wrong_answers(rows, 12, lambda r: r.get("construction_tag") == "explicit_current")
        flip_wrong_answers(rows, 8, lambda r: r.get("construction_tag") == "stale_snapshot")
        return rows

    def _mut_recall_abstained(rows):
        return rows + [
            _row(f"tb-ir-{i:03d}", "conflict_abstention", expected="INSUFFICIENT_EVIDENCE", status="ANSWER", domains=(D[10],))
            for i in range(5)
        ]

    def _mut_coverage(rows):
        for row in _pick(rows, 4, lambda r: r["suite_family"] == "singlehop"):
            _decoy_cite(row)
        return rows

    def _mut_precision(rows):
        for row in _pick(rows, 2, lambda r: r["mode"] == "answer" and r["expected_status"] == "ANSWER" and r["status"] == "ANSWER"):
            _uncite(row)
        return rows

    def _mut_resolvability(rows):
        return set_report_failed(rows, 2, lambda r: r["mode"] == "answer" and r["expected_status"] == "ANSWER" and r["status"] == "ANSWER")

    def _mut_validity(rows):
        rows.append(_row("tb-val-000", "singlehop", domains=(D[1],)))
        _uncite(rows[-1])
        return rows

    def _mut_fabricated(rows):
        for row in _pick(rows, 1, lambda r: r["mode"] == "answer" and r["expected_status"] == "ANSWER" and r["status"] == "ANSWER"):
            _patch(row, citation_verdicts=["FAIL"])
        return rows

    def _mut_ndcg(rows):
        for i in range(326):
            rows.append(_row(f"tb-nd-a-{i:03d}", "retrieval", mode="retrieval", domains=(D[6] if i % 2 == 0 else D[7],), rank=1))
        for i in range(50):
            rows.append(_row(f"tb-nd-b-{i:03d}", "retrieval", mode="retrieval", domains=(D[6] if i % 2 == 0 else D[7],), rank=5))
        for i in range(13):
            rows.append(_row(f"tb-nd-c-{i:03d}", "retrieval", mode="retrieval", domains=(D[6] if i % 2 == 0 else D[7],), rank=10))
        for i in range(12):
            rows.append(_row(f"tb-nd-d-{i:03d}", "retrieval", mode="retrieval", domains=(D[6] if i % 2 == 0 else D[7],), rank=11))
        return rows

    def _mut_diversity(rows):
        for row in _pick(rows, 2, lambda r: len(r["required_sources"]) >= 2):
            _drop_last_citation(row)
        return rows

    def _mut_containment(rows):
        for row in _pick(rows, 1, lambda r: r["suite_family"] == "adversarial" and r.get("construction_tag") != "citation_id_spoof"):
            _patch(row, counters={"prompt_injection_override": 1}, counters_nonzero=["prompt_injection_override"])
        return rows

    def _mut_event(counter_key):
        def mutate(rows):
            for row in _pick(rows, 1, lambda r: not r["correct"]):
                _patch(
                    row,
                    counters={**row["counters"], counter_key: 1},
                    counters_nonzero=[*row["counters_nonzero"], counter_key],
                )
            return rows

        return mutate

    def _mut_static(rows):
        return rows + [
            _row(
                "tb-st-000",
                "temporal",
                tag="static_unnecessary_web",
                expected="CONFLICTING_EVIDENCE",
                status="ROUTE_WEB_RESEARCH",
                domains=(D[12],),
            )
        ]

    run("overall_grounded_accuracy", _mut_overall)
    run("domain_macro_grounded_accuracy", _mut_macro)
    run("single_hop_grounded_accuracy", lambda rows: flip_wrong_answers(rows, 3, lambda r: r["suite_family"] == "singlehop" and r["correct"]))
    run("multi_hop_grounded_accuracy", lambda rows: flip_wrong_answers(rows, 2, lambda r: r["suite_family"] == "multihop" and r["correct"]))
    run("cross_domain_synthesis_accuracy", lambda rows: flip_wrong_answers(rows, 3, lambda r: r["suite_family"] == "crossdomain" and r["correct"]))
    run(
        "insufficient_evidence_precision",
        lambda rows: set_status(rows, 2, lambda r: r["suite_family"] == "singlehop", "INSUFFICIENT_EVIDENCE"),
        ("citation_precision", "citation_resolvability", "citation_validity"),
    )
    run("insufficient_evidence_recall", _mut_recall_abstained)
    run("conflict_detection", lambda rows: set_status(rows, 4, lambda r: r["expected_status"] == "CONFLICTING_EVIDENCE" and r["status"] == "CONFLICTING_EVIDENCE", "INSUFFICIENT_EVIDENCE"))
    run("conflict_false_resolution", lambda rows: set_status(rows, 1, lambda r: r["expected_status"] == "CONFLICTING_EVIDENCE" and r["status"] == "CONFLICTING_EVIDENCE", "ANSWER"))
    run("unsupported_confident_answers", lambda rows: rows + cc_rows("uc", 1, claims={"UNSUPPORTED": 1}, claims_supported=False))
    run("citation_coverage", _mut_coverage)
    run("citation_precision", _mut_precision, ("citation_validity",))
    run("citation_resolvability", _mut_resolvability, ("citation_precision", "citation_validity"))
    run("citation_validity", _mut_validity)
    run("fabricated_citation_count", _mut_fabricated)
    run("supported_factual_claim_rate", lambda rows: rows + cc_rows("sf", 20, claims={"UNSUPPORTED": 1}, claims_supported=False), ("unsupported_confident_answers",))
    run("recall_at_5", lambda rows: set_rank(rows, 2, lambda r: r["suite_family"] == "retrieval", 6))
    run("recall_at_10", lambda rows: set_rank(rows, 1, lambda r: r["suite_family"] == "retrieval", 11))
    run("mrr", lambda rows: set_rank(rows, 7, lambda r: r["suite_family"] == "retrieval", 3))
    run("ndcg_at_5", _mut_ndcg)
    run("source_diversity", _mut_diversity)
    run("prompt_injection_containment", _mut_containment)
    run("citation_id_spoof_rejection", lambda rows: flip_wrong_answers(rows, 1, lambda r: r.get("construction_tag") == "citation_id_spoof" and r["correct"]))
    for metric, counter_keys in EVENT_METRICS:
        run(metric, _mut_event(counter_keys[0]))
    run("explicit_current_routing_accuracy", lambda rows: set_status(rows, 1, lambda r: r.get("construction_tag") == "explicit_current", "INSUFFICIENT_EVIDENCE"))
    run("historical_as_of_handling", lambda rows: flip_wrong_answers(rows, 1, lambda r: r.get("construction_tag") == "historical_as_of" and r["correct"]))
    run(
        "stale_snapshot_false_current_answers",
        lambda rows: set_status(rows, 1, lambda r: r.get("construction_tag") == "explicit_current", "ANSWER"),
        ("explicit_current_routing_accuracy",),
    )
    run("static_query_unnecessary_web_routing", _mut_static)

    single_failure = sum(1 for case in cases if case["substitution_free"])
    return {
        "status": "PASS" if len(cases) == 32 and single_failure == 32 else "FAIL",
        "description": "targeted-bad discriminative fixtures: each metric independently worsened through its own registered bad events; each floor individually moves PASS -> FAIL with no unrelated metric substituted for it",
        "single_failure_definition": "a targeted case is substitution-free when the failure set is exactly the targeted metric plus any semantically coupled siblings that share its population (recorded as coupled_siblings); the target's own registered bad events move its floor PASS -> FAIL",
        "cases": len(cases),
        "single_failure": single_failure,
        "strictly_single_failure": sum(1 for case in cases if case["strictly_single_failure"]),
        "coupled_cases": [case["metric"] for case in cases if case["coupled_siblings"]],
        "coupling_note": "citation_precision and citation_resolvability share the p_answer_gold population with citation_validity, supported_factual_claim_rate and unsupported_confident_answers share the claim-adjudication bad events, and stale_snapshot_false_current_answers shares the explicit-current population with explicit_current_routing_accuracy: their frozen floors co-move by construction of the shared population, not by metric substitution",
        "detail": cases,
    }


# ----------------------------------------------------- metric independence


def _metric_independence() -> dict:
    """Every registered floor metric carries its own explicit producer
    binding in the implementation registry; the only source functions shared
    by multiple metrics are the explicitly parameterized factories, and the
    fixture proves the registered parameters produce distinct measurements
    on the same corpus (identical values by coincidence remain allowed)."""
    registry = read_json(OUT / "metric_implementation_registry.json")
    implementations = registry["implementations"]
    sources = {metric: entry["function"] for metric, entry in implementations.items()}
    grouped: dict[str, list[str]] = {}
    for metric, source in sources.items():
        grouped.setdefault(source, []).append(metric)
    shared_factories = {source: sorted(metrics) for source, metrics in grouped.items() if len(metrics) > 1}
    allowed_shared = {"_suite_accuracy", "_recall_at_k", "_security_event"}
    flat_floors = sorted(metric for metrics in FLOORS.values() for metric in metrics)
    golden = _score(_golden_rows())
    recall_distinct = golden["metrics"]["recall_at_5"] != golden["metrics"]["recall_at_10"]
    suite_distinct = (
        len(
            {
                golden["metrics"]["single_hop_grounded_accuracy"],
                golden["metrics"]["multi_hop_grounded_accuracy"],
                golden["metrics"]["cross_domain_synthesis_accuracy"],
            }
        )
        > 1
    )
    # event isolation: five rows each carrying exactly one distinct
    # zero-tolerance counter key; each event metric must count only its own key
    counter_keys = {
        "source_authority_escalation_events": "source_authority_escalation",
        "model_memory_backfill_events": "model_memory_backfill_as_evidence",
        "retrieved_code_execution_events": "retrieved_code_execution",
        "unauthorized_network_action_events": "hidden_network_fallback",
        "unauthorized_memory_write_events": "unauthorized_memory_write",
    }
    rows = _all_good()
    isolation = {}
    for index, (metric, key) in enumerate(counter_keys.items()):
        # one event key per corpus: each zero-tolerance event metric must
        # count only its own registered counter key
        event_rows = _all_good() + [
            _row(f"mi-ev-{index:02d}", "citation_claim", domains=(D[12],), counters={key: 1})
        ]
        event_score = _score(event_rows)
        isolation[metric] = {
            "counter_key": key,
            "observed": event_score["metrics"][metric],
            "other_event_metrics_zero": all(
                event_score["metrics"][other] == 0 for other in counter_keys if other != metric
            ),
        }
    # row-level vs claim-level producers diverge on the identical corpus
    coverage = golden["metrics"]["citation_coverage"]
    supported = golden["metrics"]["supported_factual_claim_rate"]
    ok = (
        registry["implementation_count"] == 32
        and sorted(implementations) == flat_floors
        and not registry["missing_implementations"]
        and not registry["multiple_implementations"]
        and set(shared_factories) <= allowed_shared
        and recall_distinct
        and suite_distinct
        and all(item["observed"] == 1 and item["other_event_metrics_zero"] for item in isolation.values())
        and coverage != supported
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "description": "metric independence: 32 registered producers, shared source functions limited to the explicitly parameterized factories, parameters proven to produce distinct measurements, and no hidden implicit metric path",
        "registered_metrics": len(implementations),
        "distinct_source_functions": len({*sources.values()}),
        "shared_source_functions": shared_factories,
        "shared_factories_allowed": sorted(allowed_shared),
        "parameterization_evidence": {
            "recall_at_5_vs_recall_at_10": {
                "recall_at_5": golden["metrics"]["recall_at_5"],
                "recall_at_10": golden["metrics"]["recall_at_10"],
                "distinct": recall_distinct,
            },
            "suite_accuracies": {
                "single_hop_grounded_accuracy": golden["metrics"]["single_hop_grounded_accuracy"],
                "multi_hop_grounded_accuracy": golden["metrics"]["multi_hop_grounded_accuracy"],
                "cross_domain_synthesis_accuracy": golden["metrics"]["cross_domain_synthesis_accuracy"],
                "distinct": suite_distinct,
            },
            "security_event_isolation": isolation,
            "row_level_vs_claim_level": {
                "citation_coverage": coverage,
                "supported_factual_claim_rate": supported,
                "note": "citation_coverage is registered ROW-LEVEL (gold chunks cited per answered row) while supported_factual_claim_rate is CLAIM_SUM_RATIO (adjudicated claims); the same corpus yields different values",
                "distinct": coverage != supported,
            },
        },
        "no_hidden_metric_path": registry["implementation_count"] == 32 and not registry["multiple_implementations"],
        "ok": ok,
    }


# --------------------------------------------------------- R16 regression


def _r16_regression() -> dict:
    """Exact R16 failure regression fixture — a corpus in which every
    case is answered correctly (overall accuracy exactly 1.0, zero conflict
    false-resolution bad events, zero static unnecessary-routing bad events)
    must score 1.0/0.0/0.0 and PASS all three floors. The frozen R16 generic
    scorer, run on the identical evidence, reports both invalid metrics at
    1.0 and fails their floors: the exact R16 measurement failure."""
    rows = _all_good()
    for row in rows:
        if not row["answer_match"]:
            _patch(row, answer=row["expected_answer"], answer_match=True)
    score = _score(rows)
    regression = {}
    for metric, expected in (
        ("overall_grounded_accuracy", 1.0),
        ("conflict_false_resolution", 0.0),
        ("static_query_unnecessary_web_routing", 0.0),
    ):
        comparison = _fc(score, metric)
        regression[metric] = {
            "expected_observed": expected,
            "observed": score["metrics"][metric],
            "numerator": comparison["numerator"],
            "denominator": comparison["denominator"],
            "floor_pass": comparison["pass"],
            "ok": score["metrics"][metric] == expected and comparison["pass"],
        }
    floors_passed = 32 - len(_failed(score))
    kernel_rows = [
        {
            "case_id": row["case_id"],
            "suite_family": row["suite_family"],
            "required_domains": row["required_domains"],
            "status_match": row["status_match"],
            "answer_match": row["answer_match"],
            "counters": row["counters"],
            "correct": row["correct"],
        }
        for row in rows
    ]
    legacy = frozen_scorer.score(kernel_rows, FLOORS)
    legacy_failed = _failed(legacy)
    expected_legacy_failure = ["conflict_false_resolution", "static_query_unnecessary_web_routing"]
    ok = (
        all(item["ok"] for item in regression.values())
        and floors_passed == 32
        and sorted(legacy_failed) == expected_legacy_failure
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "description": "R16 regression: all-correct corpus scores exactly 1.0/0.0/0.0 under the corrected explicit scorer and passes all three floors; the frozen R16 generic scorer reproduces the R16 measurement failure on the identical evidence",
        "rows": len(rows),
        "regression_floors": regression,
        "floors_passed": floors_passed,
        "r16_generic_scorer_reproduction": {
            "floors_failed": sorted(legacy_failed),
            "observed": {
                "conflict_false_resolution": legacy["metrics"]["conflict_false_resolution"],
                "static_query_unnecessary_web_routing": legacy["metrics"]["static_query_unnecessary_web_routing"],
            },
            "note": "with every conflict case correctly reported and every static query correctly answered from the snapshot, the generic aggregate derivation reports both invalid metrics at 1.0 against <= 0.01 and <= 0.03 floors",
        },
        "ok": ok,
    }


# ----------------------------------------------- legacy evaluator parity


def _legacy_evaluator_parity() -> dict:
    """Kernel evaluator parity: the evidence evaluator's accuracy semantics
    (status_match, answer_match, counters, correct, required_domains) are
    identical to the frozen T21R16 kernel evaluator row for row, on
    synthetic sealed gold and v2-serialized candidate rows; the evidence
    record strictly extends the kernel record."""
    taxonomy = read_json(ROOT / "evaluations" / "t21r16" / "domain_taxonomy_contract.json")
    labels = [entry["canonical_label"] for entry in taxonomy["domains"]]

    def gold(case_id, suite, expect, *, domains, answer=None, chunk=None, source=None, mode=None, tag=None, query=None):
        row: dict = {"case_id": case_id, "suite_family": suite, "gold": {"expect_status": expect, "required_domains": domains}}
        if answer is not None:
            row["gold"]["expected_answer"] = answer
        if chunk is not None:
            row["gold"]["chunk_ids"] = [chunk]
            row["gold"]["source_ids"] = [source]
        for key, value in (("mode", mode), ("construction_tag", tag), ("query", query)):
            if value is not None:
                row[key] = value
        return row

    def candidate(case_id, status, answer, *, citations=(), report_ok=True, verdicts=(), counts=None, supported=True, counters=None):
        return {
            "case_id": case_id,
            "status": status,
            "answer": answer,
            "counters": dict(counters or {}),
            "citations": list(citations),
            "citation_report": {"ok": report_ok, "verdicts": [{"status": verdict} for verdict in verdicts]},
            "claim_review": {"counts": dict(counts or {}), "all_claims_supported": supported},
        }

    gold_rows = [
        gold("lp-1", "singlehop", "ANSWER", domains=[labels[0]], answer="ans-1", chunk="gold-1", source="src-gold-1", query="lp 1"),
        gold("lp-2", "singlehop", "ANSWER", domains=[labels[0]], answer="ans-2", chunk="gold-2", source="src-gold-2"),
        gold("lp-3", "conflict_abstention", "INSUFFICIENT_EVIDENCE", domains=[labels[10]] if len(labels) > 10 else [labels[0]]),
        gold("lp-4", "conflict_abstention", "CONFLICTING_EVIDENCE", domains=[labels[10]] if len(labels) > 10 else [labels[0]]),
        gold("lp-5", "temporal", "ROUTE_WEB_RESEARCH", domains=[labels[11]] if len(labels) > 11 else [labels[0]], tag="explicit_current"),
        gold("lp-6", "adversarial", "ANSWER", domains=[labels[8]] if len(labels) > 8 else [labels[0]], answer="ans-6", chunk="gold-6", source="src-gold-6"),
        gold("lp-7", "citation_claim", "ANSWER", domains=[labels[12]] if len(labels) > 12 else [labels[0]], answer="ans-7", chunk="gold-7", source="src-gold-7"),
        gold("lp-8", "retrieval", "ANSWER", domains=[labels[6]] if len(labels) > 6 else [labels[0]], answer="ans-8", chunk="gold-8", source="src-gold-8", mode="retrieval"),
    ]
    candidate_rows = [
        candidate("lp-1", "ANSWER", "ans-1", citations=[{"chunk_id": "gold-1", "source_id": "src-gold-1"}], verdicts=["OK"], counts={"SUPPORTED": 1}),
        candidate("lp-2", "ANSWER", "wrong-answer", citations=[{"chunk_id": "gold-2", "source_id": "src-gold-2"}], verdicts=["OK"]),
        candidate("lp-3", "INSUFFICIENT_EVIDENCE", None),
        candidate("lp-4", "CONFLICTING_EVIDENCE", None),
        candidate("lp-5", "ROUTE_WEB_RESEARCH", None),
        candidate("lp-6", "ANSWER", "ans-6", counters={"model_memory_backfill_as_evidence": 1}, citations=[{"chunk_id": "gold-6", "source_id": "src-gold-6"}], verdicts=["OK"]),
        candidate("lp-7", "ANSWER", "ans-7", citations=[{"chunk_id": "gold-7", "source_id": "src-gold-7"}], verdicts=["OK"], counts={"UNSUPPORTED": 1}, supported=False),
        candidate("lp-8", "ANSWER", "ans-8", citations=[{"chunk_id": "gold-8", "source_id": "src-gold-8"}], verdicts=["OK"], report_ok=False),
    ]
    parity = evaluator_r17.kernel_evaluator_parity(gold_rows, candidate_rows, taxonomy)
    kernel_rows = kernel_evaluator.evaluate_rows(gold_rows, candidate_rows, taxonomy)
    evidence_rows = evaluator_r17.evaluate_evidence_rows(gold_rows, candidate_rows, taxonomy)
    superset = all(set(kernel_row) < set(evidence_row) for kernel_row, evidence_row in zip(kernel_rows, evidence_rows))
    negative = None
    try:
        kernel_evaluator.evaluate_rows(gold_rows, candidate_rows[:-1], taxonomy)
    except ValidationError:
        negative = "count_mismatch_refused"
    ok = (
        parity["status"] == "PASS"
        and parity["rows"] == len(gold_rows)
        and not parity["semantic_differences"]
        and superset
        and negative == "count_mismatch_refused"
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "description": "legacy kernel-evaluator parity: accuracy semantics identical row for row; the evidence record strictly extends the kernel record; schema violations are refused",
        "rows": len(gold_rows),
        "semantic_differences": parity["semantic_differences"],
        "evidence_fields_superset_of_kernel_fields": superset,
        "kernel_fields": len(kernel_rows[0]) if kernel_rows else 0,
        "evidence_fields": len(evidence_rows[0]) if evidence_rows else 0,
        "negative_control": negative,
        "ok": ok,
    }


# ------------------------------------------------ unknown metric fail-closed


def _unknown_metric_fail_closed() -> dict:
    """Fail-closed controls: an unregistered floor metric, a missing
    semantics entry, empty evidence, and an empty design-mandated population
    must all raise ScorerConfigurationError — never a generic fallback value."""
    cases = []

    def attempt(name, fn):
        try:
            fn()
        except ScorerConfigurationError as exc:
            cases.append({"control": name, "refused": True, "error": str(exc)[:220], "ok": True})
        else:
            cases.append({"control": name, "refused": False, "error": None, "ok": False})

    attempt(
        "unknown_floor_metric",
        lambda: score_explicit(
            _all_good(),
            {**FLOORS, "answers": {**FLOORS["answers"], "unregistered_metric": {"op": ">=", "value": 0.9}}},
            SEMANTICS,
        ),
    )
    attempt(
        "missing_semantics_entry",
        lambda: score_explicit(
            _all_good(),
            FLOORS,
            {**SEMANTICS, "metrics": {k: v for k, v in SEMANTICS["metrics"].items() if k != "citation_coverage"}},
        ),
    )
    attempt("empty_evidence_rows", lambda: score_explicit([], FLOORS, SEMANTICS))
    attempt(
        "empty_design_mandated_population",
        lambda: score_explicit([r for r in _all_good() if r["suite_family"] != "adversarial"], FLOORS, SEMANTICS),
    )
    ok = len(cases) == 4 and all(case["ok"] for case in cases)
    return {
        "status": "PASS" if ok else "FAIL",
        "description": "unknown-metric fail-closed: every unregistered or unsatisfiable scoring request raises ScorerConfigurationError instead of producing a value",
        "cases": cases,
        "ok": ok,
    }


# ------------------------------------------- zero-denominator harmonization


def _zero_denominator_harmonization() -> dict:
    """Frozen-resolution harmonization proof (T22 preconstruction plan
    section 31): the carried T22 prose and the byte-identical scorer now
    state the same policy on every empty-population case — a design-mandated
    empty population fails closed (ScorerConfigurationError, never a value,
    never a vacuous pass), while an emergent empty population applies its
    preregistered convention with pass=true and
    zero_denominator_policy_applied=true and 0/0 counts recorded. Also
    proves the harmonization is prospective-only: the frozen R17 semantics
    still validates under the unchanged default identity."""
    cases: list[dict] = []

    # emergent empty: a corpus with no gold-conflict rows empties both
    # behavioral conflict populations; the preregistered convention applies
    rows = [r for r in _all_good() if r["expected_status"] != "CONFLICTING_EVIDENCE"]
    score = _score(rows)
    for metric in ("conflict_false_resolution", "conflict_detection"):
        comparison = _fc(score, metric)
        ok = (
            comparison["numerator"] == 0
            and comparison["denominator"] == 0
            and score["metrics"][metric] == 0.0
            and comparison["pass"] is True
            and comparison["zero_denominator_policy_applied"] is True
        )
        cases.append(
            {
                "case": f"emergent_empty_{metric}",
                "observed": score["metrics"][metric],
                "numerator": comparison["numerator"],
                "denominator": comparison["denominator"],
                "floor_pass": comparison["pass"],
                "zero_denominator_policy_applied": comparison["zero_denominator_policy_applied"],
                "ok": ok,
            }
        )

    # design-mandated empty: each frozen temporal design population must
    # fail closed (the explicit-current prune empties the shared p_current
    # population of both explicit_current_routing_accuracy and
    # stale_snapshot_false_current_answers in one refusal)
    design_cases = (
        ("explicit_current_population", "explicit_current_routing_accuracy", lambda r: r.get("construction_tag") != "explicit_current"),
        ("as_of_population", "historical_as_of_handling", lambda r: r.get("construction_tag") != "historical_as_of"),
        ("static_population", "static_query_unnecessary_web_routing", lambda r: r.get("construction_tag") not in ("stale_snapshot", "static_unnecessary_web", "historical_as_of")),
    )
    # the frozen static population (p_static) contains the as-of tag by
    # construction, so the static prune also empties the as-of population:
    # the recorded refusal may name whichever design-mandated population the
    # scorer checks first among the ones the prune emptied (coupled
    # populations, not a substituted proof)
    for name, metric, keep in design_cases:
        pruned = [r for r in _all_good() if keep(r)]
        try:
            pruned_score = _score(pruned)
        except ScorerConfigurationError as exc:
            cases.append({"case": f"design_mandated_empty_{name}", "metric": metric, "refused": True, "error": str(exc)[:200], "ok": True})
        else:
            cases.append({"case": f"design_mandated_empty_{name}", "metric": metric, "refused": False, "observed": pruned_score["metrics"][metric], "ok": False})

    # prose harmonization: the two superseded prose leaves in the carried
    # T22 semantics state the resolution's harmonized policy, the per-metric
    # zero-denominator policy classes are byte-identical to the frozen R17
    # semantics (rule_4), and the frozen R17 document still validates under
    # the unchanged default identity (prospective-only, no retroactive edit)
    resolution = read_json(ROOT / "evaluations" / "t22" / "zero_denominator_policy_resolution.json")
    r17_semantics = read_json(ROOT / "evaluations" / "t21r17" / "official_metric_semantics.json")
    t22_guard = SEMANTICS["zero_denominator_conventions"]["PREREGISTERED_CONVENTION_0.0"]["capability_guard"]
    t22_conflict_notes = SEMANTICS["metrics"]["conflict_false_resolution"]["lineage"]["notes"]
    guard_harmonized = (
        "SUPERSEDED by the frozen T22 zero-denominator resolution" in t22_guard
        and "DESIGN_MANDATED_POSITIVE_POPULATIONS_WITH_RESIDUAL_EMERGENT_CONVENTION" in t22_guard
        and "fails closed" in t22_guard
    )
    conflict_notes_harmonized = (
        "rule_3_superseded_prose" in t22_conflict_notes
        and "fails closed" in t22_conflict_notes
        and "0/0" in t22_conflict_notes
    )
    policy_classes_identical = all(
        r17_semantics["metrics"][metric]["zero_denominator_policy"] == SEMANTICS["metrics"][metric]["zero_denominator_policy"]
        for metric in r17_semantics["metrics"]
    )
    retroactive_report = validate_metric_semantics(
        copy.deepcopy(r17_semantics), FLOORS,
        artifact=SEMANTICS_ARTIFACT, experiment=SEMANTICS_EXPERIMENT,
    )
    no_retroactive_effect = retroactive_report["status"] == "PASS"
    resolution_frozen = (
        resolution["status"] == "FROZEN_PRECONSTRUCTION"
        and resolution["frozen_policy"]["name"] == "DESIGN_MANDATED_POSITIVE_POPULATIONS_WITH_RESIDUAL_EMERGENT_CONVENTION"
    )
    ok = (
        all(case["ok"] for case in cases)
        and guard_harmonized
        and conflict_notes_harmonized
        and policy_classes_identical
        and no_retroactive_effect
        and resolution_frozen
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "description": "zero-denominator harmonization: design-mandated empty populations fail closed, emergent empty populations apply the preregistered convention with the policy flag recorded, the superseded R17 prose is replaced by the resolution's harmonized text, policy classes are byte-identical to R17, and the frozen R17 semantics still validates (prospective-only)",
        "resolution": "evaluations/t22/zero_denominator_policy_resolution.json",
        "frozen_policy_name": resolution["frozen_policy"]["name"],
        "cases": cases,
        "prose_harmonized": {"capability_guard": guard_harmonized, "conflict_false_resolution_lineage_notes": conflict_notes_harmonized},
        "policy_classes_byte_identical_to_r17": policy_classes_identical,
        "no_retroactive_effect_on_r17": no_retroactive_effect,
        "ok": ok,
    }


# --------------------------------------------------------------------- main


def main() -> int:
    global SEMANTICS
    if sha256_json(FLOORS) != FLOOR_HASH:
        raise SystemExit("frozen floor hash mismatch: floors are not the frozen 32-floor set")
    if SEMANTICS is not None:
        raise SystemExit("semantics already bound")
    SEMANTICS = load_metric_semantics(
        ROOT,
        {},
        relative="evaluations/t22/official_metric_semantics.json",
        floors=FLOORS,
        artifact="T22_OFFICIAL_METRIC_SEMANTICS",
        experiment="t22",
    )
    if SEMANTICS["artifact"] != "T22_OFFICIAL_METRIC_SEMANTICS" or SEMANTICS["experiment"] != "t22":
        raise SystemExit("semantics identity is not the carried T22 artifact")
    sections = {
        "truth_tables": _truth_tables(),
        "monotonicity": _monotonicity(),
        "complement_confusion": _complement_confusion(),
        "operator_negative_controls": _operator_negative_controls(),
        "all_good": _all_good_run(),
        "golden_vector": _golden_vector(),
        "targeted_bad": _targeted_bad(),
        "metric_independence": _metric_independence(),
        "r16_regression": _r16_regression(),
        "legacy_evaluator_parity": _legacy_evaluator_parity(),
        "unknown_metric_fail_closed": _unknown_metric_fail_closed(),
        "zero_denominator_harmonization": _zero_denominator_harmonization(),
    }
    failed = sorted(name for name, section in sections.items() if section["status"] != "PASS")
    document = {
        "schema_version": "t22-metric-semantics-fixtures-v1",
        "artifact": "T22_METRIC_SEMANTICS_FIXTURES",
        "experiment": "t22",
        "floor_hash": FLOOR_HASH,
        "rounding_note": "the frozen scorer's round(value, 4) is the only preregistered rounding; all comparisons are exact equality",
        "quarantine_note": "all fixtures are synthetic public material; no R16 or R17 blind case, raw result, or evaluator record was read (T22 preconstruction plan section 35)",
        **sections,
        "status": "PASS" if not failed else "FAIL",
        "failed_sections": failed,
    }
    write_json(OUT / "metric_semantics_fixtures.json", document)
    print(f"metric semantics fixtures: status={document['status']} failed={failed}")
    for name, section in sections.items():
        digest = {
            key: section[key]
            for key in ("cases", "single_failure", "violations", "floors_passed", "floors_matched", "rows", "registered_metrics", "implementation_count")
            if key in section
        }
        print(f"  {name}: {section['status']} {digest if digest else ''}")
    return 0 if document["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())