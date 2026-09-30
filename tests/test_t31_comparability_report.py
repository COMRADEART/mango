"""T31 tests, brief category 22 (report generation) and the gate list.

Two properties are being pinned here.

**The decision cannot be chosen.** It is derived from gate statuses, and a
gate that was never evaluated renders as ``NOT_EVALUATED`` and forces the
overall status to PARTIAL. A test that only ever fed the renderer a complete,
all-green input would not distinguish "the decision follows the gates" from
"the decision was passed in", so the PARTIAL and FAIL paths are exercised
directly.

**The report passes its own audit.** GATE 15 reads the rendered text back and
checks that no number is attributed to the wrong system. That check is
worthless if the report we actually emit fails it, so the last test renders a
report and runs the audit over the result.
"""
from __future__ import annotations

import pytest

from sciencemath.comparability import analysis as A
from sciencemath.comparability import gates as G
from sciencemath.comparability import report as R
from sciencemath.comparability.contract import EXTRACTION_OK

REQUIRED_SECTIONS = (
    "## Status",
    "## Branch and commits",
    "## Frozen model identities",
    "## Evaluation environment",
    "## Frozen decoding configuration",
    "## Dataset identities",
    "## Model-only results",
    "## Paired outcomes",
    "## Uncertainty",
    "## Error analysis",
    "## Schema versus content",
    "## Integrated runtime results",
    "## Training-data overlap and contamination",
    "## Reproduction",
    "## Artifacts",
    "## Hashes",
    "## Tests",
    "## Regression",
    "## Known limitations",
    "## T31 gate results",
    "## T32 diagnostic handoff",
    "## Decision",
)

CONFIG_HASH = "a" * 64

ALL_BENCHMARKS = ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq")

#: A cross-tabulation that is not degenerate, and the per-benchmark raw counts
#: a complete run would leave: both are what a green gate requires, so a
#: fixture that supplies placeholders here would be testing the failure path.
MIXED_ROWS = ([{"schema_valid": True, "content_valid": True}] * 3
              + [{"schema_valid": True, "content_valid": False}] * 1)

#: A report snippet that satisfies the GATE 15 audit, so the fixture can
#: exercise a fully-evaluated gate list rather than leaving that gate open.
GOOD_TEXT = (R.HEADING + "\n\n## Integrated runtime results\n\n"
             "The Mango Adapter, the Mango Runtime and the Mango Integrated "
             "System are reported separately.\n")


def outcome(*, benchmark="gsm8k", item_id="i0", base=True, adapter=True,
            cluster=None, base_error=None, adapter_error=None):
    return A.PairedOutcome(
        item_id=item_id, benchmark=benchmark, cluster=cluster or item_id,
        base_correct=base, adapter_correct=adapter,
        base_error=base_error, adapter_error=adapter_error,
        base_extraction=EXTRACTION_OK, adapter_extraction=EXTRACTION_OK)


def summary(benchmark="gsm8k", *, n=4, base_only=0, adapter_only=0, both=None,
            schema_base=None, schema_adapter=None):
    both = n - base_only - adapter_only if both is None else both
    outcomes = [outcome(benchmark=benchmark, item_id=f"c{i}")
                for i in range(both)]
    outcomes += [outcome(benchmark=benchmark, item_id=f"b{i}", base=True,
                         adapter=False, adapter_error="wrong_final_answer")
                 for i in range(base_only)]
    outcomes += [outcome(benchmark=benchmark, item_id=f"a{i}", base=False,
                         adapter=True, base_error="wrong_reasoning")
                 for i in range(adapter_only)]
    return A.benchmark_summary(
        outcomes,
        schema_content_base=schema_base or {
            "schema_and_content": both, "schema_only": base_only,
            "content_only": 0, "neither": 0},
        schema_content_adapter=schema_adapter or {
            "schema_and_content": both, "schema_only": adapter_only,
            "content_only": 0, "neither": 0})


def gate_evidence(summaries=None, *, text=GOOD_TEXT, **overrides):
    from sciencemath.comparability.identity import BENCHMARK_IDENTITIES

    # Default to all five benchmarks: the per-benchmark gates read the summary
    # table, so a fixture whose summaries cover only one would leave four gates
    # unevaluated while its completeness data claimed otherwise.
    summaries = (summaries if summaries is not None
                 else [summary(name) for name in ALL_BENCHMARKS])
    pairs = [(arm, name) for name in ALL_BENCHMARKS
             for arm in ("base", "adapter")]
    base = dict(
        config_hash=CONFIG_HASH,
        adapter_sha256="f" * 64, adapter_pinned_sha256="f" * 64,
        base_revision="70d244cc", pinned_base_revision="70d244cc",
        adapter_revision="ad4bac71", pinned_adapter_revision="ad4bac71",
        t30_tree_clean=True,
        t30_freeze_sha256="d5671bc0", t30_pinned_freeze_sha256="d5671bc0",
        completeness={f"{arm}:{name}": {"complete": True}
                      for arm, name in pairs},
        raw_counts={f"{arm}:{name}": BENCHMARK_IDENTITIES[name]["expected_items"]
                    for arm, name in pairs},
        scored_counts={"rows": {f"{arm}:{name}": MIXED_ROWS
                                for arm, name in pairs}},
        row_config_hashes={f"{arm}:{name}": {CONFIG_HASH}
                           for arm, name in pairs},
        schema_content_crosstab={"schema_and_content": 30, "schema_only": 10,
                                 "content_only": 0, "neither": 0},
        summaries={s["benchmark"]: s for s in summaries},
        contamination={"table": [{"benchmark": name}
                                 for name in ALL_BENCHMARKS]},
        reproduction={"commands": ["python -m sciencemath.comparability run"],
                      "config_path": "evaluations/t31/config.json",
                      "hashes_path": "evaluations/t31/SHA256SUMS"},
        regression={"passed": 330, "failed": 0, "skipped": 1},
        report_text=text,
    )
    base.update(overrides)
    return G.GateEvidence(**base)


def inputs(summaries=None, gates=None, **overrides):
    summaries = (summaries if summaries is not None
                 else [summary(name) for name in ALL_BENCHMARKS])
    values = dict(
        branch="t31-public-comparability", base_commit="d25d457",
        final_commit="deadbee",
        config={
            "models": {
                "base": {"repo_id": "Qwen/Qwen3-1.7B", "revision": "70d244cc"},
                "adapter": {"repo_id": "ComradeRt/Mango-T30-1.7B",
                            "revision": "ad4bac71", "weights_sha256": "f" * 64,
                            "declared_base_revision": "70d244cc"},
            },
            # The key names are the frozen config's own, so the renderer is
            # tested against the artifact it will actually be handed.
            "decoding_primary": {"do_sample": False, "batch_size": 8},
            "benchmarks": {"gsm8k": {"repo_id": "openai/gsm8k",
                                     "config": "main", "split": "test",
                                     "revision": "abc123",
                                     "expected_items": 1319,
                                     "license": "MIT"}},
        },
        config_hash=CONFIG_HASH,
        environment={"python": "3.13.0", "torch": "2.5.1+cu121"},
        summaries=summaries,
        aggregate=A.aggregate(summaries),
        contamination={"table": [
            {"benchmark": "gsm8k", "known_training_overlap": "no",
             "evaluation_interpretation": "held out",
             "items_compared": 1319, "measured_exact_overlap": 0,
             "measured_near_overlap": 0, "measured_answer_carried_overlap": 0,
             "measured_sibling_overlap": 0, "max_gram_similarity": 0.31,
             "held_out": "yes"}]},
        gates=gates if gates is not None else G.evaluate(gate_evidence(summaries)),
        hashes={"config.json": "b" * 64},
        tests={"passed": 330, "failed": 0, "skipped": 1},
        regression={"passed": 330, "failed": 0, "skipped": 1},
        t32={"disagreements": 12},
        reproduction={"commands": ["python -m sciencemath.comparability run"],
                      "config_path": "evaluations/t31/config.json",
                      "hashes_path": "evaluations/t31/SHA256SUMS"},
        artifacts=["evaluations/t31/raw/base/gsm8k.jsonl"],
    )
    values.update(overrides)
    return R.ReportInputs(**values)


# ---------------------------------------------------------------------------
# the report renders what the brief requires
# ---------------------------------------------------------------------------
def test_every_required_section_is_present():
    text = R.render(inputs())
    for section in REQUIRED_SECTIONS:
        assert section in text, section
    assert text.startswith(R.HEADING)


def test_the_configuration_tables_render_their_contents():
    """A heading with an empty table under it satisfies a section check while
    telling a reader nothing. The renderer must read the frozen config's own
    key names — ``decoding_primary`` and ``benchmarks`` — not a private pair."""
    text = R.render(inputs())
    assert "| `do_sample` |" in text
    assert "openai/gsm8k" in text
    assert "1319" in text


def test_the_report_carries_exactly_one_decision_token():
    text = R.render(inputs())
    tokens = [token for token in
              ("MANGO_T31_PUBLIC_COMPARABILITY_PASS",
               "MANGO_T31_PUBLIC_COMPARABILITY_PARTIAL",
               "MANGO_T31_PUBLIC_COMPARABILITY_FAIL")
              if token in text]
    assert len(tokens) == 1


def test_the_results_table_has_the_briefs_columns():
    summaries = [summary("gsm8k"), summary("math500")]
    render = "".join(R.results_table(summaries))
    assert "| Benchmark | Base | Mango T30 Adapter | Δ pp |" in render
    assert "gsm8k" in render and "math500" in render


def test_an_empty_result_set_is_refused_rather_than_tabulated():
    """A table with a header and no rows reads as a benchmark that scored
    nothing, which is exactly the reading the brief forbids."""
    with pytest.raises(R.ReportError):
        R.results_table([])


# ---------------------------------------------------------------------------
# negative deltas are rendered, not softened
# ---------------------------------------------------------------------------
def test_a_regression_is_reported_as_one():
    regressed = summary("gsm8k", n=10, base_only=6, adapter_only=0)
    assert regressed["delta_pp"] < 0
    text = R.render(inputs(summaries=[regressed]))
    assert "REGRESSION" in text
    assert f"{regressed['delta_pp']:+.2f}" in text


def test_a_tie_is_reported_as_equal_rather_than_as_a_lift():
    tied = summary("gsm8k", n=10, base_only=3, adapter_only=3)
    assert tied["comparison"] == "no_clear_model_level_lift_demonstrated"
    assert "EQUAL" in R.render(inputs(summaries=[tied]))


def test_an_uncertain_delta_is_not_called_an_improvement():
    """The brief's rule: a higher adapter number is not by itself a finding."""
    one_item = summary("gsm8k", n=40, base_only=1, adapter_only=2)
    reading = R.uncertainty_reading(one_item)
    assert reading != "positive and distinguishable from zero"


# ---------------------------------------------------------------------------
# uncertainty is derived from the interval, not stored beside it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("low,high,expected", [
    (-1.0, 2.0, "inconclusive at this sample size"),
    (0.5, 3.0, "positive and distinguishable from zero"),
    (-3.0, -0.5, "negative and distinguishable from zero"),
])
def test_the_uncertainty_reading_follows_the_interval(low, high, expected):
    fake = {"uncertainty": {"ci_low_pp": low, "ci_high_pp": high}}
    assert R.uncertainty_reading(fake) == expected


def test_a_missing_interval_says_so_rather_than_guessing():
    assert R.uncertainty_reading({}) == "not estimated"


# ---------------------------------------------------------------------------
# schema and content are tabulated separately
# ---------------------------------------------------------------------------
def test_a_well_formatted_wrong_answer_is_visible_in_the_table():
    """The cell the brief's separation exists to expose."""
    formatted_wrong = summary("gsm8k", n=6, base_only=2, adapter_only=0,
                              schema_base={"schema_and_content": 4,
                                           "schema_only": 2,
                                           "content_only": 0, "neither": 0})
    text = R.render(inputs(summaries=[formatted_wrong]))
    assert "schema only" in text
    assert "| gsm8k | base | 4 | 2 | 0 | 0 | 6 |" in text


def test_a_missing_cross_tabulation_is_dashed_not_zeroed():
    """Zero and "not recorded" are different findings."""
    missing = summary("gsm8k", schema_base=None, schema_adapter=None)
    missing["schema_content"] = {"base": None, "adapter": None}
    text = R.render(inputs(summaries=[missing]))
    assert "| gsm8k | base | — | — | — | — | — |" in text


# ---------------------------------------------------------------------------
# the gates
# ---------------------------------------------------------------------------
def test_a_gate_with_no_evidence_is_not_evaluated_rather_than_passing():
    gates = G.evaluate(G.GateEvidence())
    assert all(gate.status == G.NOT_EVALUATED for gate in gates)
    assert G.overall(gates) == "PARTIAL"


def test_all_fifteen_gates_are_named_and_ordered():
    gates = G.evaluate(gate_evidence())
    assert [gate.number for gate in gates] == list(range(1, 16))
    assert all(gate.status != G.NOT_EVALUATED for gate in gates)
    assert G.overall(gates) == G.PASS


def test_a_failing_gate_makes_the_whole_run_fail():
    gates = G.evaluate(gate_evidence([summary()], t30_tree_clean=False))
    assert G.overall(gates) == "FAIL"
    assert G.evaluate(gate_evidence([summary()], t30_tree_clean=False))[0].status \
        == G.FAIL


def test_a_row_carrying_another_configuration_hash_fails_gate_4():
    evidence = gate_evidence([summary()])
    evidence.row_config_hashes = {"base:gsm8k": {"b" * 64}}
    gate = G.evaluate(evidence)[3]
    assert gate.number == 4 and gate.status == G.FAIL


def test_a_raw_file_short_of_its_own_benchmark_fails_gate_10():
    """Checked per benchmark, so capturing one suite fully and another not at
    all cannot pass on a total."""
    evidence = gate_evidence([summary()])
    evidence.raw_counts = {"base:gsm8k": 1319, "adapter:gsm8k": 3}
    gate = G.evaluate(evidence)[9]
    assert gate.number == 10 and gate.status == G.FAIL


def test_a_degenerate_schema_content_split_fails_gate_11():
    """Two flags that never differ are not two facts."""
    evidence = gate_evidence([summary()])
    evidence.scored_counts = {"rows": {"base:gsm8k": [
        {"schema_valid": True, "content_valid": True}] * 4}}
    evidence.schema_content_crosstab = {"schema_and_content": 4,
                                        "schema_only": 0, "content_only": 0,
                                        "neither": 0}
    gate = G.evaluate(evidence)[10]
    assert gate.number == 11 and gate.status == G.FAIL
    assert "degenerate" in gate.evidence


def test_an_uncomputed_cross_tabulation_is_not_a_pass():
    """Scored rows without a cross-tabulation is missing evidence, not a
    healthy split — reading the empty dict as 'not degenerate' would pass the
    gate on nothing."""
    evidence = gate_evidence([summary()])
    evidence.scored_counts = {"rows": {"base:gsm8k": MIXED_ROWS}}
    evidence.schema_content_crosstab = {}
    assert G.evaluate(evidence)[10].status == G.NOT_EVALUATED


def test_an_incomplete_benchmark_fails_its_own_gate():
    evidence = gate_evidence([summary()])
    evidence.completeness["adapter:gsm8k"] = {"complete": False}
    gate = G.evaluate(evidence)[4]
    assert gate.number == 5 and gate.status == G.FAIL


def test_a_single_arm_cannot_satisfy_a_benchmark_gate():
    """A comparison gate needs both arms; one arm complete is not a
    comparison."""
    evidence = gate_evidence([summary()])
    del evidence.completeness["adapter:gsm8k"]
    assert G.evaluate(evidence)[4].status == G.NOT_EVALUATED


# ---------------------------------------------------------------------------
# the identity pins compare measured against intended, not a constant to itself
# ---------------------------------------------------------------------------
def test_gate_2_fails_when_the_measured_base_revision_differs():
    """The pin is only a check if the two sides come from different places."""
    evidence = gate_evidence([summary()])
    evidence.base_revision = "deadbeef"           # rows generated elsewhere
    gate = G.evaluate(evidence)[1]
    assert gate.number == 2 and gate.status == G.FAIL
    assert "deadbeef" in gate.evidence


def test_gate_2_is_not_evaluated_without_a_measured_revision():
    evidence = gate_evidence([summary()])
    evidence.base_revision = None
    assert G.evaluate(evidence)[1].status == G.NOT_EVALUATED


def test_gate_3_fails_when_the_measured_adapter_bytes_differ():
    evidence = gate_evidence([summary()])
    evidence.adapter_sha256 = "0" * 64
    gate = G.evaluate(evidence)[2]
    assert gate.number == 3 and gate.status == G.FAIL


def test_gate_3_fails_when_the_adapter_revision_differs():
    """The bytes match but the revision loaded is another: still a different
    experiment, and the gate must say so rather than checking the hash alone."""
    evidence = gate_evidence([summary()])
    evidence.adapter_revision = "0000dead"
    assert G.evaluate(evidence)[2].status == G.FAIL


def test_gate_3_is_not_evaluated_with_no_measurement():
    evidence = gate_evidence([summary()])
    evidence.adapter_sha256 = None
    evidence.adapter_revision = None
    assert G.evaluate(evidence)[2].status == G.NOT_EVALUATED


def test_gate_1_fails_when_the_measured_adapter_is_not_the_t30_bytes():
    evidence = gate_evidence([summary()])
    evidence.adapter_sha256 = "0" * 64
    gate = G.evaluate(evidence)[0]
    assert gate.number == 1 and gate.status == G.FAIL


def test_gate_1_fails_when_the_t30_freeze_root_has_drifted():
    evidence = gate_evidence([summary()])
    evidence.t30_freeze_sha256 = "b" * 64
    assert G.evaluate(evidence)[0].status == G.FAIL


def test_gate_1_is_not_evaluated_without_any_evidence():
    assert G._gate_1(G.GateEvidence()).status == G.NOT_EVALUATED


def test_observed_identity_is_read_from_the_rows_not_the_manifest():
    rows = {"base:gsm8k": [{"model_revision": "rev-a"}],
            "adapter:gsm8k": [{"model_revision": "rev-a",
                               "adapter_revision": "rev-adapt",
                               "adapter_sha256": "abc"}]}
    assert G._observed_identity(rows) == {"base_revision": "rev-a",
                                          "adapter_revision": "rev-adapt",
                                          "adapter_sha256": "abc"}


def test_two_revisions_under_one_name_fail_rather_than_pick_one():
    rows = {"base:gsm8k": [{"model_revision": "rev-a"},
                           {"model_revision": "rev-b"}]}
    assert G._observed_identity(rows)["base_revision"] == "rev-a, rev-b"


def test_observed_identity_is_empty_without_rows():
    assert G._observed_identity({}) == {"base_revision": None,
                                        "adapter_revision": None,
                                        "adapter_sha256": None}


# ---------------------------------------------------------------------------
# gate 14 reads the key the producer actually writes
# ---------------------------------------------------------------------------
def test_gate_14_fails_when_the_regression_record_reports_failures():
    evidence = gate_evidence([summary()])
    evidence.regression = {"passed": 330, "failed": 37, "skipped": 1}
    gate = G.evaluate(evidence)[13]
    assert gate.number == 14 and gate.status == G.FAIL


def test_gate_14_rejects_a_record_that_omits_the_failure_count():
    """A nonzero 'passed' with no failure count has not demonstrated that none
    failed: missing evidence, so NOT_EVALUATED, not a PASS from an absence."""
    evidence = gate_evidence([summary()])
    evidence.regression = {"passed": 330}
    assert G.evaluate(evidence)[13].status == G.NOT_EVALUATED


def test_gate_14_fails_when_the_suite_ran_nothing():
    """Zero passed is not green."""
    evidence = gate_evidence([summary()])
    evidence.regression = {"passed": 0, "failed": 0, "skipped": 0}
    assert G.evaluate(evidence)[13].status == G.FAIL


def test_gate_14_passes_only_on_an_explicit_zero():
    evidence = gate_evidence([summary()])
    evidence.regression = {"passed": 330, "failed": 0, "skipped": 1}
    assert G.evaluate(evidence)[13].status == G.PASS


def test_gate_14_is_not_evaluated_without_a_record():
    evidence = gate_evidence([summary()])
    evidence.regression = {}
    assert G.evaluate(evidence)[13].status == G.NOT_EVALUATED


# ---------------------------------------------------------------------------
# gate 10 is closed over the whole arm×benchmark set
# ---------------------------------------------------------------------------
def test_gate_10_fails_when_an_arm_benchmark_file_is_absent():
    """One suite, one arm, retained in full, must not satisfy a gate about
    retaining every generation of both arms."""
    evidence = gate_evidence([summary()])
    evidence.raw_counts = {"base:gsm8k": 1319}
    gate = G.evaluate(evidence)[9]
    assert gate.number == 10 and gate.status == G.FAIL
    assert "adapter:gsm8k" in gate.evidence


def test_gate_10_passes_on_the_full_cross_product():
    assert G.evaluate(gate_evidence([summary()]))[9].status == G.PASS


# ---------------------------------------------------------------------------
# the reproduction section says only what it printed
# ---------------------------------------------------------------------------
def test_the_reproduction_section_prints_the_commands_and_says_so():
    text = R.render(inputs())
    assert "python -m sciencemath.comparability run" in text
    assert "The commands above" in text


def test_the_reproduction_section_does_not_claim_commands_it_did_not_print():
    text = R.render(inputs(reproduction={"config_path": "c.json",
                                         "hashes_path": "SHA256SUMS"}))
    assert "The commands above" not in text
    assert "no verbatim reproduction recipe" in text


# ---------------------------------------------------------------------------
# gate 15 reads the report back
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("adjective", list(G.BANNED_ADJECTIVES))
def test_gate_15_catches_an_unsupported_adjective(adjective):
    text = (R.HEADING + "\n\n## Integrated runtime results\n\nThe Mango "
            "Adapter, the Mango Runtime and the Mango Integrated System are "
            f"all {adjective}.\n")
    assert G._gate_15(G.GateEvidence(report_text=text)).status == G.FAIL


def test_gate_15_catches_a_runtime_figure_wearing_the_accuracy_label():
    text = (R.HEADING + "\n\n## Integrated runtime results\n\nThe Mango "
            "Adapter, the Mango Runtime and the Mango Integrated System: "
            "integrated runtime accuracy reached 91%.\n")
    gate = G._gate_15(G.GateEvidence(report_text=text))
    assert gate.status == G.FAIL
    assert "pairs a runtime figure with accuracy" in gate.evidence


def test_gate_15_passes_a_disclaimer_that_keeps_them_apart():
    text = (R.HEADING + "\n\n## Integrated runtime results\n\nThese are not "
            "model accuracy. The Mango Adapter, the Mango Runtime and the "
            "Mango Integrated System are each reported separately.\n")
    assert G._gate_15(G.GateEvidence(report_text=text)).status == G.PASS


def test_the_rendered_report_passes_its_own_audit():
    """The audit is only meaningful if the report we emit satisfies it."""
    text = R.render(inputs())
    assert G._gate_15(G.GateEvidence(report_text=text)).status == G.PASS


def test_the_rendered_report_names_all_three_systems():
    text = R.render(inputs()).lower()
    for name in ("mango adapter", "mango runtime", "mango integrated system"):
        assert name in text
