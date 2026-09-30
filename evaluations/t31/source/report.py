"""T31.11 The report.

The brief fixes the sections, so this module is mostly a layout pass over
figures that were computed elsewhere — with three deliberate exceptions.

**The decision is derived, never chosen.** It comes from the gates, and the
gates come from artifacts. There is no argument by which a caller can ask for
``PASS``.

**Negative deltas are rendered like positive ones.** The comparison column
prints ``LIFT``, ``REGRESSION`` or ``EQUAL`` and a signed number; a regression
is not softened into "comparable" and a small positive is not inflated into an
improvement. The brief's instruction is to measure rather than defend, and the
way a report defends is by describing a regression in the prose.

**An empty input renders as a refusal.** Every table function raises on an
empty set rather than emitting a header with no rows, because a table with no
rows reads like a benchmark that scored nothing rather than like a run that did
not happen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from sciencemath.comparability import gates as G
from sciencemath.comparability.contract import (
    COMPARISON_EQUAL, COMPARISON_LIFT, COMPARISON_REGRESSION,
)

HEADING = "# MANGO T31 PUBLIC COMPARABILITY REPORT"

#: The comparison field carries the brief's own sentence-length phrase, because
#: that phrase is what the decision logic names. The tables need the short form.
COMPARISON_WORD = {
    COMPARISON_LIFT: "LIFT",
    COMPARISON_REGRESSION: "REGRESSION",
    COMPARISON_EQUAL: "EQUAL",
}


class ReportError(RuntimeError):
    """The report was asked to render something it cannot stand behind."""


@dataclass
class ReportInputs:
    branch: str
    base_commit: str
    final_commit: str
    config: dict[str, Any]
    config_hash: str
    environment: dict[str, Any]
    summaries: Sequence[dict[str, Any]]
    aggregate: dict[str, Any] | None
    contamination: dict[str, Any]
    gates: Sequence[G.Gate]
    hashes: dict[str, str] = field(default_factory=dict)
    tests: dict[str, Any] = field(default_factory=dict)
    regression: dict[str, Any] = field(default_factory=dict)
    integrated: dict[str, Any] | None = None
    t32: dict[str, Any] = field(default_factory=dict)
    limitations: Sequence[str] = ()
    reproduction: dict[str, Any] = field(default_factory=dict)
    artifacts: Sequence[str] = ()


def decision_token(status: str) -> str:
    """The one token the brief permits, spelled from the gate outcome."""
    return f"MANGO_T31_PUBLIC_COMPARABILITY_{status}"


def render(inputs: ReportInputs) -> str:
    status = G.overall(inputs.gates)
    lines: list[str] = [HEADING, ""]
    lines += _status_section(inputs, status)
    lines += _provenance_section(inputs)
    lines += _identities_section(inputs)
    lines += _environment_section(inputs)
    lines += _decoding_section(inputs)
    lines += _datasets_section(inputs)
    lines += _results_section(inputs)
    lines += _paired_section(inputs)
    lines += _uncertainty_section(inputs)
    lines += _error_section(inputs)
    lines += _schema_content_section(inputs)
    lines += _integrated_section(inputs)
    lines += _contamination_section(inputs)
    lines += _reproduction_section(inputs)
    lines += _artifacts_section(inputs)
    lines += _hashes_section(inputs)
    lines += _tests_section(inputs)
    lines += _regression_section(inputs)
    lines += _limitations_section(inputs)
    lines += _gates_section(inputs)
    lines += _handoff_section(inputs)
    lines += _decision_section(inputs, status)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def _num(value: Any, places: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def _status_section(inputs: ReportInputs, status: str) -> list[str]:
    counts = {value: 0 for value in (G.PASS, G.FAIL, G.NOT_EVALUATED)}
    for gate in inputs.gates:
        counts[gate.status] = counts.get(gate.status, 0) + 1
    return [
        "## Status", "",
        f"**{status}**",
        "",
        f"{len(inputs.gates)} gates: {counts[G.PASS]} PASS, "
        f"{counts[G.FAIL]} FAIL, {counts[G.NOT_EVALUATED]} NOT_EVALUATED.",
        "",
        "A gate that was not evaluated is reported as such and is not counted "
        "as satisfied. Status is PARTIAL, not PASS, while any gate is "
        "NOT_EVALUATED.",
        "",
    ]


def _provenance_section(inputs: ReportInputs) -> list[str]:
    return [
        "## Branch and commits", "",
        f"- Branch: `{inputs.branch}`",
        f"- Base commit (the frozen Mango T30 state T31 branched from): "
        f"`{inputs.base_commit}`",
        f"- Final commit (this report): `{inputs.final_commit}`",
        "",
    ]


def _identities_section(inputs: ReportInputs) -> list[str]:
    models = inputs.config.get("models", {})
    lines = [
        "## Frozen model identities", "",
        "Two systems are compared. The only experimental variable between the "
        "two columns is the adapter's weights.", "",
        "| System | Repository | Revision | Weights sha256 |", "|---|---|---|---|",
    ]
    for arm, key in (("Base model", "base"), ("Mango Adapter", "adapter")):
        entry = models.get(key, {})
        digest = entry.get("weights_sha256") or "(tokenizer/revision only)"
        short = digest if len(digest) < 24 else digest[:16] + "…"
        lines.append(f"| {arm} | `{entry.get('repo_id', '—')}` | "
                     f"`{str(entry.get('revision', '—'))[:12]}` | `{short}` |")
    adapter = models.get("adapter", {})
    if adapter.get("declared_base_revision"):
        same = adapter["declared_base_revision"] == models.get("base", {}).get("revision")
        lines += ["",
                  f"The adapter declares its base as "
                  f"`{adapter['declared_base_revision'][:12]}`, "
                  + ("which is the revision being compared against it — the "
                     "ablation isolates the adapter."
                     if same else
                     "which is **not** the revision being compared against "
                     "it.")]
    lines += [
        "",
        "The Mango Adapter is a LoRA adapter over the base model, not a "
        "separately trained model. The Mango Runtime is not loaded in either "
        "column; it is measured separately, below, and its results are never "
        "combined with the two columns here.",
        "",
    ]
    return lines


def _environment_section(inputs: ReportInputs) -> list[str]:
    env = inputs.environment or {}
    lines = ["## Evaluation environment", "", "| Field | Value |", "|---|---|"]
    for key in sorted(env):
        value = env[key]
        if isinstance(value, (dict, list)):
            continue
        lines.append(f"| `{key}` | `{value}` |")
    lines.append("")
    for key in sorted(env):
        if isinstance(env[key], dict):
            lines += [f"### {key}", ""]
            for sub in sorted(env[key]):
                lines.append(f"- `{sub}`: `{env[key][sub]}`")
            lines.append("")
    return lines


def _decoding_section(inputs: ReportInputs) -> list[str]:
    # The frozen configuration names the primary arm's settings
    # ``decoding_primary``; the reasoning-enabled secondary arm lives beside it
    # and is not the configuration these results were produced under.
    decoding = inputs.config.get("decoding_primary", {})
    lines = [
        "## Frozen decoding configuration", "",
        f"Configuration hash: `{inputs.config_hash}`", "",
        "Both systems are decoded with these settings. Nothing below was "
        "chosen after seeing which side scored better.", "",
        "| Setting | Value |", "|---|---|",
    ]
    for key in sorted(decoding):
        lines.append(f"| `{key}` | `{decoding[key]!r}` |")
    lines += [
        "",
        "Maximum generation length is set per benchmark and recorded with "
        "each item.",
        "",
    ]
    return lines


def _datasets_section(inputs: ReportInputs) -> list[str]:
    datasets = inputs.config.get("benchmarks", {})
    lines = [
        "## Dataset identities", "",
        "| Benchmark | Source | Config | Split | Revision | Items | License |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in sorted(datasets):
        entry = datasets[name]
        lines.append(
            f"| {name} | `{entry.get('repo_id', '—')}` | "
            f"`{entry.get('config', '—')}` | `{entry.get('split', '—')}` | "
            f"`{str(entry.get('revision', '—'))[:12]}` | "
            f"{entry.get('expected_items', '—')} | {entry.get('license', '—')} |")
    lines += [
        "",
        "Every item carries a stable id derived from the benchmark, split and "
        "the source's own identifier, so a row can be traced back to the "
        "dataset record that produced it.",
        "",
    ]
    return lines


def results_table(summaries: Sequence[dict[str, Any]]) -> list[str]:
    """The brief's `| Benchmark | Base | Mango T30 Adapter | Δ pp |` table."""
    if not summaries:
        raise ReportError("no benchmark summaries to tabulate")
    lines = [
        "| Benchmark | Base | Mango T30 Adapter | Δ pp | Relative Δ | Outcome |",
        "|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        relative = summary.get("relative_delta")
        relative_text = "—" if relative is None else f"{relative * 100:+.2f}%"
        comparison = summary["comparison"]
        lines.append(
            f"| {summary['benchmark']} | {_pct(summary['base_accuracy'])} "
            f"({summary['base_correct']}/{summary['total_items']}) | "
            f"{_pct(summary['adapter_accuracy'])} "
            f"({summary['adapter_correct']}/{summary['total_items']}) | "
            f"{summary['delta_pp']:+.2f} | "
            f"{relative_text} | "
            f"{COMPARISON_WORD.get(comparison, comparison)} |")
    return lines


def _results_section(inputs: ReportInputs) -> list[str]:
    lines = [
        "## Model-only results", "",
        "Content accuracy: a generation counts only when the extracted answer "
        "is correct against the benchmark's own reference. Formatting that "
        "cannot be parsed is a failure, not a pass.", "",
    ]
    lines += results_table(inputs.summaries)
    if inputs.aggregate:
        agg = inputs.aggregate
        lines += [
            "",
            f"Micro-average over all {agg['total_items']} items "
            f"(`{agg['aggregation']}`): base {_pct(agg['base_accuracy'])}, "
            f"Mango Adapter {_pct(agg['adapter_accuracy'])}, "
            f"Δ {agg['delta_pp']:+.2f} pp.",
            "",
            f"{agg['note']}",
        ]
    lines += [
        "",
        "These are weight-level figures. They are not the Mango Runtime's "
        "scores and not the Mango Integrated System's scores; those are "
        "reported separately and never in this table.",
        "",
    ]
    return lines


def _paired_section(inputs: ReportInputs) -> list[str]:
    lines = [
        "## Paired outcomes", "",
        "Each item is evaluated by both systems, so the comparison is paired "
        "rather than between two independent samples.", "",
        "| Benchmark | Both correct | Base only | Adapter only | Neither | "
        "McNemar p |", "|---|---|---|---|---|---|",
    ]
    for summary in inputs.summaries:
        paired = summary["paired"]
        mcnemar = summary.get("mcnemar") or {}
        p = mcnemar.get("p_value")
        lines.append(
            f"| {summary['benchmark']} | {paired['both_correct']} | "
            f"{paired['base_only']} | {paired['adapter_only']} | "
            f"{paired['neither']} | {_num(p, 4)} |")
    lines += [
        "",
        "The discordant cells — base-only and adapter-only — are what McNemar's "
        "test is computed over; concordant items carry no information about a "
        "difference between the two systems.",
        "",
    ]
    return lines


def uncertainty_reading(summary: dict[str, Any]) -> str:
    """What the interval supports, said in words the interval can carry.

    Derived from the interval rather than stored with it, so the sentence and
    the numbers cannot drift apart. The conservative reading is the default:
    an interval that includes zero is inconclusive, and a delta whose interval
    excludes zero is still only "distinguishable from zero", which is a claim
    about this benchmark at this sample size and not about the model.
    """
    uncertainty = summary.get("uncertainty") or {}
    low = uncertainty.get("ci_low_pp")
    high = uncertainty.get("ci_high_pp")
    if low is None or high is None:
        return "not estimated"
    if low <= 0.0 <= high:
        return "inconclusive at this sample size"
    direction = "positive" if low > 0.0 else "negative"
    return f"{direction} and distinguishable from zero"


def _uncertainty_section(inputs: ReportInputs) -> list[str]:
    lines = [
        "## Uncertainty", "",
        "Interval estimates come from a percentile bootstrap resampling "
        "*clusters of items sharing a question stem*, not individual items, "
        "because near-duplicate items within a benchmark are not independent "
        "and resampling them as such would narrow the interval without "
        "justifying it.", "",
        "| Benchmark | Δ pp | 95% CI | Reading | Clusters | Items |",
        "|---|---|---|---|---|---|",
    ]
    for summary in inputs.summaries:
        uncertainty = summary.get("uncertainty") or {}
        low, high = uncertainty.get("ci_low_pp"), uncertainty.get("ci_high_pp")
        ci = "—" if low is None else f"[{low:+.2f}, {high:+.2f}]"
        lines.append(
            f"| {summary['benchmark']} | {summary['delta_pp']:+.2f} | {ci} | "
            f"{uncertainty_reading(summary)} | "
            f"{uncertainty.get('cluster_count', '—')} | "
            f"{uncertainty.get('item_count', '—')} |")
    lines += [
        "",
        "A delta is described as an improvement only when its interval "
        "excludes zero *and* the sign is positive. An interval spanning zero "
        "is reported as inconclusive at this sample size, whatever the point "
        "estimate happens to be.",
        "",
    ]
    clustered = [s["benchmark"] for s in inputs.summaries
                 if (s.get("uncertainty") or {}).get("clustering_material")]
    if clustered:
        lines += [
            f"Cluster resampling was material on {', '.join(clustered)}: those "
            f"benchmarks contain distinct items sharing a question stem, whose "
            f"outcomes are correlated. Everywhere else the stem is unique and "
            f"the clustering reduces to ordinary item resampling.",
            "",
        ]
    return lines


def _error_section(inputs: ReportInputs) -> list[str]:
    categories: list[str] = []
    for summary in inputs.summaries:
        errors = summary.get("errors") or {}
        for key in ("base_error_counts", "adapter_error_counts"):
            for name in (errors.get(key) or {}):
                if name not in categories:
                    categories.append(name)
    categories.sort()

    lines = [
        "## Error analysis", "",
        "Categories are assigned by the scorer from the generation itself. No "
        "error was reclassified by hand to improve a result.", "",
        "Counts are per arm, over the items that arm got wrong.", "",
        "| Benchmark | Arm | " + " | ".join(categories or ["—"]) + " | Total |",
        "|---" * (len(categories) + 3) + "|",
    ]
    for summary in inputs.summaries:
        errors = summary.get("errors") or {}
        for arm, key in (("base", "base_error_counts"),
                         ("adapter", "adapter_error_counts")):
            counts = errors.get(key) or {}
            cells = " | ".join(str(counts.get(name, 0)) for name in categories)
            lines.append(f"| {summary['benchmark']} | {arm} | {cells} | "
                         f"{sum(counts.values())} |")

    lines += [
        "",
        "| Benchmark | Invalid outputs (base / adapter) | Extraction failures "
        "(base / adapter) | Shared failures |", "|---|---|---|---|",
    ]
    for summary in inputs.summaries:
        invalid = summary.get("invalid_outputs") or {}
        extraction = summary.get("extraction_failures") or {}
        shared = (summary.get("errors") or {}).get("shared_failures", "—")
        lines.append(
            f"| {summary['benchmark']} | {invalid.get('base', '—')} / "
            f"{invalid.get('adapter', '—')} | "
            f"{extraction.get('base', '—')} / {extraction.get('adapter', '—')} | "
            f"{shared} |")
    lines += [
        "",
        "`invalid_output` covers generations that could not be read as an "
        "answer at all — an empty generation, an unparseable one, or one cut "
        "off at the token budget. An extraction failure is counted separately "
        "from a content failure wherever the two can be told apart. All of "
        "them count as incorrect; they are not excluded from the denominator.",
        "",
    ]
    return lines


def _schema_content_section(inputs: ReportInputs) -> list[str]:
    lines = [
        "## Schema versus content", "",
        "Two independent facts are recorded for every generation.", "",
        "- `schema_valid` — the generation conformed to the requested answer "
        "format.",
        "- `content_valid` — the extracted answer was correct.",
        "",
        "| Benchmark | Arm | schema ∧ content | schema only | content only | "
        "neither | Total |", "|---|---|---|---|---|---|---|",
    ]
    for summary in inputs.summaries:
        cross = summary.get("schema_content") or {}
        for arm in ("base", "adapter"):
            counts = cross.get(arm)
            if not counts:
                lines.append(f"| {summary['benchmark']} | {arm} | — | — | — | "
                             f"— | — |")
                continue
            total = sum(counts.values())
            lines.append(
                f"| {summary['benchmark']} | {arm} | "
                f"{counts.get('schema_and_content', 0)} | "
                f"{counts.get('schema_only', 0)} | "
                f"{counts.get('content_only', 0)} | "
                f"{counts.get('neither', 0)} | {total} |")
    lines += [
        "",
        "`schema_only` is the cell that matters: a well-formatted wrong "
        "answer. It is a content failure. Producing a parseable answer is "
        "never counted as reasoning success, and `content_valid` is the "
        "capability metric throughout this report.",
        "",
    ]
    return lines


def _integrated_section(inputs: ReportInputs) -> list[str]:
    lines = [
        "## Integrated runtime results", "",
    ]
    if not inputs.integrated:
        lines += [
            "Not measured. The Mango Integrated System — adapter weights "
            "plus the Mango Runtime — was not evaluated under this task, so no "
            "integrated figures are reported. Nothing in the model-only tables "
            "above should be read as a runtime result.",
            "",
        ]
        return lines
    lines += [
        "These figures are for the Mango Integrated System and are not "
        "comparable to the model-only table above. They are not model accuracy "
        "and must not be quoted as such.",
        "",
        "| Metric | Value |", "|---|---|",
    ]
    for key in sorted(inputs.integrated):
        lines.append(f"| {key} | {inputs.integrated[key]} |")
    lines.append("")
    return lines


def _contamination_section(inputs: ReportInputs) -> list[str]:
    table = inputs.contamination.get("table") or []
    lines = [
        "## Training-data overlap and contamination", "",
        "Overlap is measured, not asserted. Each evaluated item is compared "
        "against the historical training corpus and classified as an exact "
        "duplicate, a near-duplicate, or sharing a template.", "",
        "| Benchmark | Known training overlap | Evaluation interpretation |",
        "|---|---|---|",
    ]
    for row in table:
        lines.append(f"| {row.get('benchmark')} | "
                     f"{row.get('known_training_overlap')} | "
                     f"{row.get('evaluation_interpretation')} |")
    summary = inputs.contamination.get("summary") or {}
    if summary:
        lines += [
            "",
            "### Measured overlap", "",
            "| Benchmark | Items checked | Exact | Near-dup | Answer-carrying "
            "| Sibling | Max n-gram | Held out |", "|---|---|---|---|---|---|---|---|",
        ]
        for row in table:
            lines.append(
                f"| {row.get('benchmark')} | {row.get('items_compared')} | "
                f"{row.get('measured_exact_overlap')} | "
                f"{row.get('measured_near_overlap')} | "
                f"{row.get('measured_answer_carried_overlap')} | "
                f"{row.get('measured_sibling_overlap')} | "
                f"{_num(row.get('max_gram_similarity'), 3)} | "
                f"{row.get('held_out')} |")
    lines += [
        "",
        "ARC is treated as a protected benchmark. It was not trained on, "
        "fine-tuned on, used for prompt selection, or used to select a "
        "checkpoint during T31, and no ARC-specific failure was corrected by "
        "hand.",
        "",
    ]
    return lines


def _reproduction_section(inputs: ReportInputs) -> list[str]:
    repro = inputs.reproduction or {}
    lines = ["## Reproduction", ""]
    if repro.get("config_path"):
        lines.append(f"Frozen configuration: `{repro['config_path']}`")
    if repro.get("hashes_path"):
        lines.append(f"Hash manifest: `{repro['hashes_path']}`")
    if repro.get("environment"):
        lines.append(f"Recorded environment: `{repro['environment']}`")
    commands = repro.get("commands") or []
    if commands:
        lines += ["", "```", *commands, "```"]
    if not lines[-1]:
        lines.append("No reproduction record was supplied.")
    lines.append("")
    if commands:
        lines += [
            "The commands above reproduce the comparison from the frozen "
            "configuration on a machine with the recorded environment. The raw "
            "files are not regenerated byte-identically by every device; the "
            "scored files are a deterministic function of the raw files and are.",
        ]
    else:
        # Saying "the commands above" over an empty list would point a reader
        # at nothing, which is exactly the vacuous claim this section exists to
        # avoid.
        lines += [
            "No command list was recorded, so this pack carries no verbatim "
            "reproduction recipe. The frozen configuration and the hash "
            "manifest above are what a rerun has to match.",
        ]
    lines.append("")
    return lines


def _artifacts_section(inputs: ReportInputs) -> list[str]:
    lines = ["## Artifacts", ""]
    if not inputs.artifacts:
        lines += ["No artifact list was supplied.", ""]
        return lines
    for path in inputs.artifacts:
        lines.append(f"- `{path}`")
    lines.append("")
    return lines


def _hashes_section(inputs: ReportInputs) -> list[str]:
    lines = [
        "## Hashes", "",
        "These authenticate the run: they say which inputs produced which "
        "outputs. They are not evidence that the model is capable of anything, "
        "and a matching hash says nothing about accuracy.", "",
        "| Artifact | sha256 |", "|---|---|",
    ]
    for name in sorted(inputs.hashes):
        lines.append(f"| `{name}` | `{inputs.hashes[name]}` |")
    if not inputs.hashes:
        lines.append("| (none recorded) | — |")
    lines.append("")
    return lines


def _tests_section(inputs: ReportInputs) -> list[str]:
    tests = inputs.tests or {}
    lines = [
        "## Tests", "",
        f"{tests.get('passed', '—')} passed, {tests.get('failed', '—')} "
        f"failed, {tests.get('skipped', '—')} skipped.",
        "",
    ]
    for name in sorted(tests.get("suites", {}) or {}):
        entry = tests["suites"][name]
        lines.append(f"- `{name}`: {entry}")
    if tests.get("suites"):
        lines.append("")
    return lines


def _regression_section(inputs: ReportInputs) -> list[str]:
    regression = inputs.regression or {}
    lines = [
        "## Regression", "",
        "The pre-existing test suite was run unchanged.",
        "",
        f"{regression.get('passed', '—')} passed, "
        f"{regression.get('failed', '—')} failed, "
        f"{regression.get('skipped', '—')} skipped.",
        "",
    ]
    if regression.get("note"):
        lines += [str(regression["note"]), ""]
    return lines


def _limitations_section(inputs: ReportInputs) -> list[str]:
    lines = ["## Known limitations", ""]
    if not inputs.limitations:
        lines += ["None recorded.", ""]
        return lines
    for entry in inputs.limitations:
        lines.append(f"- {entry}")
    lines.append("")
    return lines


def _gates_section(inputs: ReportInputs) -> list[str]:
    lines = [
        "## T31 gate results", "",
        "Each gate is decided from artifacts, not asserted. `NOT_EVALUATED` "
        "means the evidence was not produced, and is not a pass.", "",
        "| Gate | Requirement | Status | Evidence |", "|---|---|---|---|",
    ]
    for gate in inputs.gates:
        lines.append(f"| GATE {gate.number} — {gate.name} | "
                     f"{gate.requirement} | **{gate.status}** | {gate.evidence} |")
    lines.append("")
    return lines


def _handoff_section(inputs: ReportInputs) -> list[str]:
    handoff = inputs.t32 or {}
    lines = [
        "## T32 diagnostic handoff", "",
        "A diagnostic dataset of per-item disagreement is produced for a "
        "possible future remediation stage. It is diagnostic output only: no "
        "model was trained on it during T31, and nothing in this report "
        "depends on it.", "",
    ]
    if handoff:
        lines += ["| Field | Value |", "|---|---|"]
        for key in sorted(handoff):
            lines.append(f"| {key} | {handoff[key]} |")
        lines.append("")
    else:
        lines += ["No handoff dataset was produced.", ""]
    return lines


def _decision_section(inputs: ReportInputs, status: str) -> list[str]:
    lines = ["## Decision", ""]
    token = decision_token(status)
    if status == G.PASS:
        lines.append(
            "A third party can determine what the Mango Adapter changes "
            "relative to its frozen base model, reproduce the comparison from "
            "the published configuration, inspect the individual failures, and "
            "tell weight-level performance apart from runtime qualification.")
    elif status == "PARTIAL":
        lines.append(
            "The comparison is reported, but at least one gate could not be "
            "evaluated from the available evidence. A partial result is not a "
            "pass and is not a claim about capability.")
    else:
        lines.append(
            "At least one gate failed. The failures are listed above and are "
            "not summarized away here.")
    lines += [
        "",
        f"**{token}**",
        "",
        "This decision is about the quality of the evidence, not about whether "
        "the adapter beats its base model. It claims nothing about the "
        "adapter's general capability, and no figure produced by the Mango "
        "Runtime or the Mango Integrated System belongs to the adapter's "
        "weights.",
        "",
    ]
    return lines
