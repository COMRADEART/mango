"""T31.14 The pipeline — the brief's ordered steps, in order.

The brief does not merely list these steps, it orders them and says why: the
loader is validated, then the scorer, then a smoke test on the base model, then
raw capture and extraction are verified, and *only then* is the configuration
frozen and hashed, and *only then* are the full runs started. The order exists
to prevent one specific failure — "Do not tune the harness based on Mango's
final score" — so the functions here are separate commands rather than one
``run_everything`` that could be pointed at the full set before the smoke test
had been read.

The smoke test writes to a scratch root under a placeholder configuration hash
on purpose. Its rows are machinery checks, not results, and letting them into
the real evidence tree would either poison a raw file with a foreign hash or
invite exactly the comparison this package refuses to make.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from sciencemath.comparability import manifest as M
from sciencemath.comparability.analysis import (
    aggregate, benchmark_summary, diagnostic_rows, pair_rows,
    schema_content_split, to_json,
)
from sciencemath.comparability.config import (
    config_hash, freeze as freeze_config, frozen_config, load_frozen,
)
from sciencemath.comparability.contract import (
    ARM_ADAPTER, ARM_BASE, ARMS, BENCHMARK_ORDER, EXTRACTION_OK,
)
from sciencemath.comparability.extractors import extract
from sciencemath.comparability.gates import GateEvidence, evaluate
from sciencemath.comparability.loaders import EvalItem, load_all
from sciencemath.comparability.report import ReportInputs, render
from sciencemath.comparability.rows import (
    EVIDENCE_ROOT, raw_path, read_rows, scored_path,
)
from sciencemath.comparability.runner import (
    iter_rows, load_arm, release_arm, verify_run,
)
from sciencemath.comparability.scoring import score_arm

SMOKE_HASH = "smoke"   # deliberately not 64 hex chars, so it cannot be mistaken
                       # for a frozen configuration's hash.


class PipelineError(RuntimeError):
    """A step cannot proceed without the one before it."""


@dataclass
class SmokeReport:
    benchmark: str
    items: int
    batches: int
    seconds: float
    items_per_second: float
    peak_vram_bytes: int | None
    extraction_failures: int
    empty_generations: int
    sample: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in (
            "benchmark", "items", "batches", "seconds", "items_per_second",
            "peak_vram_bytes", "extraction_failures", "empty_generations")}


def smoke(benchmark: str = "gsm8k", *, limit: int = 16, batch_size: int = 8,
          root: Path | None = None, arm: str = ARM_BASE,
          sample_size: int = 4) -> SmokeReport:
    """Step 3-5: run a few items through the real machinery and look at them.

    This measures throughput and peak memory, which is what decides a safe
    batch size, and it inspects the captures and the extractions rather than
    only counting them. A smoke test that reported "16 rows written" without
    showing one would pass over an extractor that reads every answer as None.
    """
    import torch

    # A scratch tree of its own: smoke rows are machinery checks, and letting
    # them into ``evaluations/t31`` would either sit under a foreign config
    # hash or invite a comparison nobody should make.
    root = root or (Path("artifacts") / "t31_smoke")
    items = load_all((benchmark,))[benchmark][:limit]
    if not items:
        raise PipelineError(f"{benchmark} loaded zero items")

    runtime = load_arm(arm)
    try:
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        rows: list[dict[str, Any]] = []
        batches = 0
        for batch in iter_rows(runtime, benchmark, items,
                               config_hash=SMOKE_HASH, batch_size=batch_size):
            rows.extend(batch)
            batches += 1
        seconds = time.perf_counter() - started
        peak = (int(torch.cuda.max_memory_allocated())
                if torch.cuda.is_available() else None)
    finally:
        release_arm(runtime)

    from sciencemath.comparability.contract import BENCHMARKS

    kind = BENCHMARKS[benchmark]["kind"]
    failures = empty = 0
    for row in rows:
        generation = row.get("raw_generation") or ""
        if not generation.strip():
            empty += 1
        if extract(items_placeholder(items, row), kind, generation).status \
                != EXTRACTION_OK:
            failures += 1

    return SmokeReport(
        benchmark=benchmark, items=len(rows), batches=batches,
        seconds=round(seconds, 3),
        items_per_second=round(len(rows) / seconds, 3) if seconds else 0.0,
        peak_vram_bytes=peak,
        extraction_failures=failures, empty_generations=empty,
        sample=[_smoke_sample(row) for row in rows[:sample_size]])


def items_placeholder(items: Sequence[EvalItem], row: dict[str, Any]) -> EvalItem:
    """The item a captured row belongs to, by id. A smoke row with no matching
    item is a real failure of the capture, not something to skip past."""
    for item in items:
        if item.item_id == row.get("item_id"):
            return item
    raise PipelineError(
        f"a captured row carries item_id {row.get('item_id')!r}, which is not "
        f"in the loaded suite — the capture is not attributable")


def _smoke_sample(row: dict[str, Any]) -> dict[str, Any]:
    generation = (row.get("raw_generation") or "").strip()
    return {
        "item_id": row.get("item_id"),
        "gold": row.get("gold"),
        "finish_reason": row.get("finish_reason"),
        "output_tokens": row.get("output_tokens"),
        "generation_head": generation[:120],
    }


def freeze(root: Path | None = None, *,
           benchmarks: Sequence[str] = BENCHMARK_ORDER) -> str:
    """Steps 6-7: compute the suite hashes, freeze the configuration, hash it.

    The suite hashes are computed here rather than taken from a record, so a
    configuration cannot vouch for items it was not measured against.
    """
    root = root or Path(".")
    items = load_all(tuple(benchmarks))
    runtime = load_arm(ARM_BASE)
    try:
        template = M.chat_template_sha256(runtime.tokenizer)
    finally:
        release_arm(runtime)

    config = frozen_config(suite_hashes=M.suite_hashes(items),
                           chat_template_sha256=template)
    digest = freeze_config(M.config_path(root), config)
    M.write_artifact(M.environment_path(root), "T31_ENVIRONMENT_MANIFEST",
                     {**M.environment_record(),
                      "dependencies": M.dependency_record()})
    return digest


def run_arm(arm: str, root: Path | None = None, *,
            benchmarks: Sequence[str] = BENCHMARK_ORDER,
            batch_size: int | None = None,
            thinking: bool = False,
            progress=None) -> dict[str, int]:
    """Step 8, one arm, over whole suites.

    There is no partial mode. ``run_benchmark`` refuses a suite shorter than
    the pinned item count, so a limited run could not be scored anyway — and
    a partial run that *could* be scored is the thing the brief's
    fail-nonvacuity rule exists to prevent. Partial runs are the smoke test's
    job, and they go to a scratch tree.
    """
    root = root or Path(".")
    config = load_frozen(M.config_path(root))
    digest = config["config_sha256"]
    if arm not in ARMS:
        raise PipelineError(f"unknown arm {arm!r}; expected one of {ARMS}")

    items_by_benchmark = load_all(tuple(benchmarks))
    batch = batch_size or config["decoding_primary"]["batch_size"]
    runtime = load_arm(arm)
    written: dict[str, int] = {}
    try:
        for name in benchmarks:
            written[name] = _run_one(
                runtime, name, items_by_benchmark[name], config_hash=digest,
                batch_size=batch, thinking=thinking, root=root,
                on_batch=progress)
    finally:
        release_arm(runtime)
    return written


def _run_one(runtime, benchmark, items, *, config_hash, batch_size, thinking,
             root, on_batch):
    from sciencemath.comparability.runner import run_benchmark

    max_new_tokens = None
    if thinking:
        from sciencemath.comparability.config import decoding_policy
        max_new_tokens = decoding_policy(thinking=True)["max_new_tokens"][benchmark]
    progress = run_benchmark(
        runtime, benchmark, items, config_hash=config_hash,
        batch_size=batch_size, enable_thinking=thinking, root=root,
        max_new_tokens=max_new_tokens, on_batch=on_batch)
    return progress.generated


def score(root: Path | None = None, *,
          benchmarks: Sequence[str] = BENCHMARK_ORDER) -> dict[str, int]:
    root = root or Path(".")
    items_by_benchmark = load_all(tuple(benchmarks))
    written: dict[str, int] = {}
    for name in benchmarks:
        for arm in ARMS:
            result = score_arm(name, arm, items_by_benchmark[name], root=root)
            written[f"{arm}:{name}"] = result.scored
    return written


def analyse(root: Path | None = None, *,
            benchmarks: Sequence[str] = BENCHMARK_ORDER
            ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pair the arms, summarize, and write the analysis and the T32 handoff."""
    root = root or Path(".")
    items_by_benchmark = load_all(tuple(benchmarks))
    summaries: list[dict[str, Any]] = []
    handoff: list[dict[str, Any]] = []

    for name in benchmarks:
        base_rows, _ = read_rows(scored_path(root, ARM_BASE, name))
        adapter_rows, _ = read_rows(scored_path(root, ARM_ADAPTER, name))
        if not base_rows or not adapter_rows:
            raise PipelineError(
                f"{name}: scored rows are missing for one or both arms "
                f"({len(base_rows)} base, {len(adapter_rows)} adapter); "
                f"refusing to summarize a benchmark that was not run")
        outcomes = pair_rows(base_rows, adapter_rows, benchmark=name)
        summary = benchmark_summary(
            outcomes,
            extraction_base={"failures": sum(
                1 for row in base_rows
                if row.get("extraction_status") != EXTRACTION_OK)},
            extraction_adapter={"failures": sum(
                1 for row in adapter_rows
                if row.get("extraction_status") != EXTRACTION_OK)},
            invalid_base=sum(1 for row in base_rows if row.get("invalid_output")),
            invalid_adapter=sum(1 for row in adapter_rows
                                if row.get("invalid_output")),
            schema_content_base=schema_content_split(base_rows),
            schema_content_adapter=schema_content_split(adapter_rows))
        summaries.append(summary)
        handoff.extend(diagnostic_rows(outcomes, base_rows, adapter_rows))

    payload = {
        "benchmarks": summaries,
        "aggregate": aggregate(summaries),
        "decoding": _decoding_record(root),
    }
    M.write_artifact(M.analysis_path(root), "T31_PAIRED_ANALYSIS", payload)
    M.write_lines(M.handoff_path(root),
                  [to_json(row).replace("\n", " ") for row in handoff])
    return summaries, payload["aggregate"]


def _decoding_record(root: Path) -> dict[str, Any]:
    config = load_frozen(M.config_path(root))
    return {"config_sha256": config["config_sha256"],
            "decoding_primary": config["decoding_primary"]}


def contamination(root: Path | None = None, *,
                  benchmarks: Sequence[str] = BENCHMARK_ORDER
                  ) -> dict[str, Any]:
    """Measure overlap of the evaluated items against the training corpus."""
    from sciencemath.comparability.contamination import (
        disclosure_table, load_corpus, measure_overlap, summarize,
    )

    root = root or Path(".")
    items_by_benchmark = load_all(tuple(benchmarks))
    records, corpus = load_corpus(root)
    overlaps = measure_overlap(records, items_by_benchmark)
    payload = {"table": disclosure_table(overlaps),
               "summary": summarize(overlaps, corpus),
               "corpus": corpus.to_dict()}
    M.write_artifact(M.contamination_path(root), "T31_CONTAMINATION_DISCLOSURE",
                     payload)
    return payload


def build_report(root: Path | None = None, *, branch: str = "",
                 base_commit: str = "", final_commit: str = "",
                 tests: dict[str, Any] | None = None,
                 regression: dict[str, Any] | None = None,
                 limitations: Sequence[str] = (),
                 commands: Sequence[str] = (),
                 integrated: dict[str, Any] | None = None,
                 t30_tree_clean: bool | None = None) -> dict[str, Any]:
    """Render the report, decide the gates from evidence, and write both."""
    root = root or Path(".")
    config = load_frozen(M.config_path(root))
    digest = config["config_sha256"]

    # GATE 1's "T30 frozen" clause is decided from git rather than from a flag
    # the caller may forget: an omitted ``--t30-tree-clean`` used to leave the
    # clause unevaluated, so a dirty T30 tree would read as "no evidence"
    # instead of failing. An explicit argument still wins when supplied.
    if t30_tree_clean is None:
        t30_tree_clean = _t30_tree_clean(root)
    # The prompt, extractor and scorer source goes into the pack before the
    # report is rendered, so it is listed and hashed like every other artifact.
    M.snapshot_sources(root)

    summaries, aggregate_payload = analyse(root)

    contamination_payload = M.read_json(M.contamination_path(root))
    handoff = _read_lines(M.handoff_path(root))

    raw_counts = {}
    for name in BENCHMARK_ORDER:
        for arm in ARMS:
            rows, _ = read_rows(raw_path(root, arm, name))
            raw_counts[f"{arm}:{name}"] = len(rows)
    scored_rows: dict[str, list[dict[str, Any]]] = {}
    row_hashes: dict[str, set[str]] = {}
    for name in BENCHMARK_ORDER:
        for arm in ARMS:
            rows, _ = read_rows(scored_path(root, arm, name))
            scored_rows[f"{arm}:{name}"] = rows
            row_hashes[f"{arm}:{name}"] = {str(row.get("config_hash"))
                                           for row in rows}

    items_by_benchmark = load_all()
    completeness = verify_run(items_by_benchmark, root=root, config_hash=digest)

    reproduction = {
        "config_path": _rel(root, M.config_path(root)),
        "hashes_path": _rel(root, M.evidence_root(root) / M.SUMS_NAME),
        "environment": _rel(root, M.environment_path(root)),
        "commands": list(commands),
    }
    gate_evidence = GateEvidence.from_run(
        config=config, config_hash=digest,
        completeness={key: value.to_dict() for key, value in
                      completeness.items()},
        raw_counts=raw_counts,
        scored_counts={"rows": scored_rows},
        row_config_hashes=row_hashes,
        summaries={summary["benchmark"]: summary for summary in summaries},
        contamination=contamination_payload,
        reproduction=reproduction,
        regression=regression or {},
        report_text="",
        t30_tree_clean=t30_tree_clean,
        t30_freeze_sha256=_t30_recorded_freeze(root),
    )
    gate_evidence.schema_content_crosstab = _totals(scored_rows)

    # GATE 15 reads the rendered report back, so the report is rendered twice:
    # once with the gate list decided but the audit still open, then the audit
    # is run over that text, then the report is re-rendered with the decided
    # gates. The prose does not depend on the gate table, so the second render
    # differs from the first only in that table and the decision line.
    provisional_gates = evaluate(gate_evidence)
    provisional = render(_report_inputs(
        config, digest, summaries, aggregate_payload, contamination_payload,
        provisional_gates, branch, base_commit, final_commit, tests, regression,
        limitations, reproduction, root, handoff, integrated))
    gate_evidence.report_text = provisional
    gates = evaluate(gate_evidence)

    text = render(_report_inputs(
        config, digest, summaries, aggregate_payload, contamination_payload,
        gates, branch, base_commit, final_commit, tests, regression, limitations,
        reproduction, root, handoff, integrated))
    M.write_artifact(M.gates_path(root), "T31_GATE_RESULTS",
                     {"gates": [gate.to_dict() for gate in gates]})
    destination = M.report_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    from sciencemath.comparability.gates import overall
    return {"status": overall(gates), "gates": [gate.to_dict() for gate in gates],
            "report": str(destination)}


def _totals(scored_rows: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    totals = {"schema_and_content": 0, "schema_only": 0, "content_only": 0,
              "neither": 0}
    for rows in scored_rows.values():
        for key, value in schema_content_split(rows).items():
            totals[key] += value
    return totals


def _read_lines(path: Path) -> list[dict[str, Any]]:
    import json

    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rel(base: Path, path: Path) -> str:
    """A path as a reader of the pack would write it: relative to the repo."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:                             # pragma: no cover
        return path.as_posix()


def _t30_tree_clean(root: Path) -> bool | None:
    """Whether the frozen T30 directory is unmodified against HEAD.

    ``None`` when git cannot be asked — not a repository, or git absent — so
    the gate reports NOT_EVALUATED rather than a clean tree nobody checked.
    The protected path is derived from the promotion record's own location, so
    the check and the record cannot drift apart.
    """
    import subprocess

    from sciencemath.comparability.identity import T30_PROMOTION_RECORD

    protected = "/".join(T30_PROMOTION_RECORD.split("/")[:2])
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--", protected],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return None
    if result.returncode != 0:                     # pragma: no cover
        return None
    return not result.stdout.strip()


def _t30_recorded_freeze(root: Path) -> str | None:
    """The freeze root the T30 promotion record still declares, if readable.

    Read back from the record rather than hardcoded, so GATE 1 catches a record
    whose declared freeze root has been edited — a change the git-clean check
    would miss if it happened before the commit under test.
    """
    import json

    from sciencemath.comparability.identity import T30_PROMOTION_RECORD

    path = root / T30_PROMOTION_RECORD
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):                  # pragma: no cover
        return None
    return (record.get("freeze_identity") or {}).get("freeze_sha256")


def _report_inputs(config, digest, summaries, aggregate_payload, contamination,
                   gates, branch, base_commit, final_commit, tests, regression,
                   limitations, reproduction, root, handoff, integrated):
    return ReportInputs(
        branch=branch or "(unrecorded)",
        base_commit=base_commit or "(unrecorded)",
        final_commit=final_commit or "(unrecorded)",
        config=config, config_hash=digest, environment=config.get("environment", {}),
        summaries=summaries, aggregate=aggregate_payload,
        contamination=contamination, gates=gates,
        hashes=M.collect(root), tests=tests or {},
        regression=regression or {}, integrated=integrated,
        t32={"disagreements": len(handoff),
             "path": _rel(root, M.handoff_path(root)),
             "note": "diagnostic only; nothing was trained on it during T31"},
        limitations=list(limitations),
        reproduction=reproduction or {},
        artifacts=sorted(M.collect(root)))


def verify(root: Path | None = None) -> dict[str, Any]:
    """The completeness check a reader would run before trusting the pack."""
    root = root or Path(".")
    config = load_frozen(M.config_path(root))
    items_by_benchmark = load_all()
    completeness = verify_run(items_by_benchmark, root=root,
                              config_hash=config["config_sha256"])
    ok, problems = M.verify_sums(root)
    return {
        "complete": all(entry.complete for entry in completeness.values()),
        "benchmarks": {key: entry.to_dict() for key, entry in
                       completeness.items()},
        "sums_ok": ok, "sums_problems": problems,
        "config_sha256": config["config_sha256"],
    }
