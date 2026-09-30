"""T31.7 The runner — generation, resumption, and raw capture.

Everything expensive and non-recomputable happens here: a raw generation
cannot be recreated from a scored row, so the raw row is the primary artifact
and the scored row is derived. That ordering is what lets the report be
re-derived, and re-derived differently, without regenerating anything.

Three properties the brief asks for and how they are obtained:

**Identical conditions.** The runner has no branch that depends on the arm
beyond which weights are loaded. Prompts, chat template, budgets, batch
layout, extractor and scorer are produced by the same code for both arms, and
the items are iterated in the same order at the same batch size, so a paired
row differs from its partner in nothing observable.

**Resumability that cannot flatter a run.** Rows are appended atomically after
each batch. On restart, items already present are skipped by ``item_id``
rather than by position, so an interrupted run resumes at item granularity and
a re-run cannot double-count. A batch is written complete or not at all — a
torn write would produce a row with unset fields, which reads as a legitimate
row with a very short generation.

**No vacuous completion.** ``verify`` compares what is present against the
pinned ``expected_items`` per benchmark and against the frozen configuration
hash, and refuses to call a set complete when it is short, has duplicates, or
mixes two configurations.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from sciencemath.comparability.contract import (
    ARM_ADAPTER, ARM_BASE, ARMS, BENCHMARKS, BENCHMARK_ORDER,
)
from sciencemath.comparability.identity import (
    ADAPTER_MUST_NOT_SHIP, BENCHMARK_IDENTITIES, MODEL_IDENTITIES,
)
from sciencemath.comparability.loaders import EvalItem
from sciencemath.comparability.prompts import (
    SYSTEM_PROMPT, prompt_text, render_chat,
)
from sciencemath.comparability.rows import (
    Completeness, EVIDENCE_ROOT, append_rows, build_raw_row,
    completed_item_ids, raw_path, read_rows, validate_complete,
)


class RunnerError(RuntimeError):
    """The run cannot proceed, or the evidence it produced is not sound."""


# ---------------------------------------------------------------------------
# adapter resolution
# ---------------------------------------------------------------------------
def _hub_snapshot(repo_id: str, revision: str) -> Path:
    """The local cache snapshot for a pinned revision, or a clear failure."""
    import os

    home = os.environ.get("HF_HOME")
    root = Path(home) / "hub" if home else \
        Path.home() / ".cache" / "huggingface" / "hub"
    folder = "models--" + repo_id.replace("/", "--")
    snapshot = root / folder / "snapshots" / revision
    if not snapshot.is_dir():
        raise RunnerError(
            f"the pinned revision of {repo_id} is not in the local cache: "
            f"{snapshot}. Download it at that exact revision before running; "
            f"resolving the name instead would compare against unpinned "
            f"bytes.")
    return snapshot


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def adapter_snapshot() -> Path:
    """The T30 release adapter directory, with its bytes verified.

    The T30 promotion record pins this artifact by sha256 alone, so the hash
    is checked on every run rather than trusted. A mismatch is a hard failure:
    a different adapter is a different experiment, and a run that silently
    proceeded would be measuring something the report does not name.
    """
    identity = MODEL_IDENTITIES["adapter"]
    snapshot = _hub_snapshot(identity["repo_id"], identity["revision"])
    weights = snapshot / identity["weights_file"]
    if not weights.is_file():
        raise RunnerError(f"{identity['weights_file']} is absent from "
                          f"{snapshot}")
    actual = sha256_file(weights)
    if actual != identity["weights_sha256"]:
        raise RunnerError(
            f"the adapter bytes have changed: {weights} hashes to {actual}, "
            f"the T30 record pins {identity['weights_sha256']}. Refusing to "
            f"run a comparison against an unpinned adapter.")
    present = {entry.name for entry in snapshot.iterdir()}
    shipped = sorted(present.intersection(ADAPTER_MUST_NOT_SHIP))
    if shipped:
        raise RunnerError(
            f"the adapter ships {shipped}, so the tokenizer would no longer "
            f"be a shared constant factor between the arms. Refusing to run.")
    return snapshot


# ---------------------------------------------------------------------------
# the two arms
# ---------------------------------------------------------------------------
@dataclass
class ArmRuntime:
    """A loaded arm, plus the identities that go on every row it produces."""

    arm: str
    model: Any
    tokenizer: Any

    @property
    def is_adapter(self) -> bool:
        return self.arm == ARM_ADAPTER

    def row_identity(self) -> dict[str, Any]:
        base = MODEL_IDENTITIES[ARM_BASE]
        if not self.is_adapter:
            return {"model_id": base["repo_id"], "model_revision":
                    base["revision"], "adapter_id": None,
                    "adapter_revision": None, "adapter_sha256": None}
        adapter = MODEL_IDENTITIES[ARM_ADAPTER]
        return {"model_id": adapter["declared_base_repo_id"],
                "model_revision": adapter["declared_base_revision"],
                "adapter_id": adapter["repo_id"],
                "adapter_revision": adapter["revision"],
                "adapter_sha256": adapter["weights_sha256"]}


def _load_pretrained(cls, repo_id: str, revision: str, **kwargs):
    """Load at a pinned revision, tolerating the renamed dtype argument.

    ``torch_dtype`` became ``dtype`` in transformers 5. Both spellings are
    attempted so that the pinned bytes are loaded on either, rather than the
    version being guessed at from a number.
    """
    try:
        return cls.from_pretrained(repo_id, revision=revision, **kwargs)
    except TypeError as error:
        if "dtype" not in kwargs or "dtype" not in str(error):
            raise
        renamed = dict(kwargs)
        renamed["torch_dtype"] = renamed.pop("dtype")
        return cls.from_pretrained(repo_id, revision=revision, **renamed)


def load_arm(arm: str, *, dtype: str = "bfloat16",
             device: str = "cuda:0") -> ArmRuntime:
    """Load one arm's weights and the *shared* tokenizer.

    The tokenizer always comes from the base repository, for both arms. The
    adapter ships none — ``adapter_snapshot`` refuses to run if it ever does —
    so this is the same tokenizer object, from the same revision, on both
    sides. That is what makes the chat template a constant.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if arm not in ARMS:
        raise RunnerError(f"unknown arm {arm!r}; expected one of {ARMS}")

    base = MODEL_IDENTITIES[ARM_BASE]
    torch_dtype = getattr(torch, dtype)
    tokenizer = AutoTokenizer.from_pretrained(base["repo_id"],
                                              revision=base["revision"])
    model = _load_pretrained(AutoModelForCausalLM, base["repo_id"],
                             base["revision"], dtype=torch_dtype)
    model.to(device)
    model.eval()

    if arm == ARM_ADAPTER:
        from peft import PeftModel

        snapshot = adapter_snapshot()
        model = PeftModel.from_pretrained(model, str(snapshot),
                                          is_trainable=False)
        model.eval()

    # Left padding, so that the last real token of every sequence in a batch
    # sits at the same index and one slice recovers each item's generation.
    # Setting it on the shared tokenizer keeps the two arms identical here too.
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return ArmRuntime(arm=arm, model=model, tokenizer=tokenizer)


def release_arm(runtime: ArmRuntime) -> None:
    """Free the weights, so two arms can be run on one small card."""
    import gc

    try:
        import torch
        del runtime.model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:                            # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------
def stop_token_ids(tokenizer: Any) -> tuple[int, ...]:
    """Every id that ends a generation, from the tokenizer itself."""
    ids: list[int] = []
    eos = tokenizer.eos_token_id
    if isinstance(eos, int):
        ids.append(eos)
    elif eos:
        ids.extend(int(value) for value in eos)
    for name in ("im_end_id", "eos_token_id"):
        value = getattr(tokenizer, name, None)
        if isinstance(value, int) and value not in ids:
            ids.append(value)
    return tuple(ids)


def render_prompt(tokenizer: Any, item: EvalItem, kind: str,
                  *, enable_thinking: bool) -> tuple[str, str]:
    """``(user_text, chat_text)`` for an item. No arm parameter, by design."""
    text = prompt_text(item, kind)
    return text, render_chat(tokenizer, text, enable_thinking=enable_thinking)


def generate_batch(runtime: ArmRuntime, texts: Sequence[str], *,
                   max_new_tokens: int) -> tuple[list[str], list[str],
                                                 list[int], list[int], float]:
    """One greedy batch.

    Returns ``(generations, finish_reasons, prompt_tokens, output_tokens,
    seconds)``. Greedy decoding, one beam, no sampling: the brief prefers a
    deterministic primary arm, and determinism is what makes a paired
    comparison mean anything.
    """
    import torch

    tokenizer = runtime.tokenizer
    encoded = tokenizer(list(texts), return_tensors="pt", padding=True,
                        add_special_tokens=False)
    prompt_lengths = encoded["attention_mask"].sum(dim=1).tolist()
    padded_width = encoded["input_ids"].shape[1]
    stops = stop_token_ids(tokenizer)
    device = next(runtime.model.parameters()).device

    started = time.perf_counter()
    with torch.inference_mode():
        output = runtime.model.generate(
            **{key: value.to(device) for key, value in encoded.items()},
            max_new_tokens=max_new_tokens, do_sample=False, num_beams=1,
            repetition_penalty=1.0, use_cache=True,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=list(stops) or None)
    elapsed = time.perf_counter() - started

    generations: list[str] = []
    reasons: list[str] = []
    prompt_counts: list[int] = []
    output_counts: list[int] = []
    pad_ids = ({int(tokenizer.pad_token_id)}
               if tokenizer.pad_token_id is not None else set())
    for index in range(len(texts)):
        # With left padding every row's real tokens end at the same column, so
        # the generation starts at the padded width regardless of prompt size.
        raw = output[index][padded_width:].tolist()

        # A row's generation ends at its own stop token. Everything after that
        # is the batch's padding, emitted on the remaining decode steps for the
        # rows that finished earlier — so the row's length is the prefix up to
        # its stop, not the width of the batch's longest generation. Trimming
        # only trailing stop ids would leave the pad run in place: it would
        # report every row in a batch at the same length, and a row that had
        # finished cleanly would be labelled "length" whenever its batch
        # happened to run to the budget.
        own: list[int] = []
        stopped = False
        for token in raw:
            if token in stops:
                stopped = True
                break
            if token in pad_ids:
                break
            own.append(token)

        # The stop is counted but not decoded: the model did emit a token at
        # that step, but decoding it would put the template's end marker into
        # the recorded answer text.
        generations.append(tokenizer.decode(own, skip_special_tokens=True))
        reasons.append("length"
                       if not stopped and len(own) >= max_new_tokens else "stop")
        prompt_counts.append(int(prompt_lengths[index]))
        output_counts.append(len(own) + 1 if stopped else len(own))
    return generations, reasons, prompt_counts, output_counts, elapsed


def iter_rows(runtime: ArmRuntime, benchmark: str, items: Sequence[EvalItem], *,
              config_hash: str, batch_size: int, enable_thinking: bool = False,
              max_new_tokens: int | None = None,
              skip: set[str] | None = None) -> Iterator[list[dict]]:
    """Yield batches of raw rows for one arm and benchmark.

    Yielding a completed batch at a time is what makes resumption atomic: the
    caller appends each batch before asking for the next, so an interruption
    loses at most one batch, and never leaves a partially written row.
    """
    import torch

    spec = BENCHMARKS[benchmark]
    budget = max_new_tokens or spec["max_new_tokens"]
    skip = skip or set()
    pending = [item for item in items if item.item_id not in skip]

    for start in range(0, len(pending), batch_size):
        chunk = pending[start:start + batch_size]
        prompts = [render_prompt(runtime.tokenizer, item, spec["kind"],
                                 enable_thinking=enable_thinking)[1]
                   for item in chunk]
        try:
            generations, reasons, prompt_counts, output_counts, elapsed = \
                generate_batch(runtime, prompts, max_new_tokens=budget)
        except torch.cuda.OutOfMemoryError as error:      # pragma: no cover
            torch.cuda.empty_cache()
            raise RunnerError(
                f"out of memory generating {benchmark} at batch size "
                f"{batch_size}. The batch size is part of the frozen "
                f"configuration, so it is not adjusted here: reduce it, "
                f"re-freeze, and rerun. ({error})") from error

        share = elapsed / len(chunk)
        rows = []
        for position, item in enumerate(chunk):
            user_text, _ = render_prompt(runtime.tokenizer, item,
                                         spec["kind"],
                                         enable_thinking=enable_thinking)
            rows.append(build_raw_row(
                item, **runtime.row_identity(),
                arm=runtime.arm,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_text,
                config_hash=config_hash,
                enable_thinking=enable_thinking,
                raw_generation=generations[position],
                finish_reason=reasons[position],
                latency_s=round(share, 4),
                prompt_tokens=prompt_counts[position],
                output_tokens=output_counts[position],
                error=None))
        yield rows


# ---------------------------------------------------------------------------
# running one arm over one benchmark
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BenchmarkProgress:
    benchmark: str
    arm: str
    present_before: int
    generated: int
    expected: int

    @property
    def complete(self) -> bool:
        return self.present_before + self.generated == self.expected


def run_benchmark(runtime: ArmRuntime, benchmark: str,
                  items: Sequence[EvalItem], *, config_hash: str,
                  batch_size: int, enable_thinking: bool = False,
                  root: Path | None = None,
                  max_new_tokens: int | None = None,
                  on_batch=None) -> BenchmarkProgress:
    """Generate and capture one arm's rows for one benchmark.

    Resumes by item id. An item already present is never regenerated, so an
    interrupted run costs only the batch it was in — and a completed run
    re-invoked is a no-op rather than a duplicate.
    """
    expected = BENCHMARK_IDENTITIES[benchmark]["expected_items"]
    if len(items) != expected:
        raise RunnerError(
            f"{benchmark} loaded {len(items)} items, the pinned identity says "
            f"{expected}. A short suite would make every rate computed over "
            f"it a rate over something other than the benchmark.")

    path = raw_path(root or EVIDENCE_ROOT, runtime.arm, benchmark)
    existing, unreadable = read_rows(path)
    if unreadable:
        raise RunnerError(
            f"{path} has unparseable lines {unreadable}; resuming over "
            f"evidence that cannot be read would silently change the "
            f"denominator, so the run stops instead.")
    already = completed_item_ids(existing)
    present_before = len(already)
    rows_written = 0

    for batch in iter_rows(runtime, benchmark, items, config_hash=config_hash,
                           batch_size=batch_size,
                           enable_thinking=enable_thinking,
                           max_new_tokens=max_new_tokens, skip=already):
        rows_written += append_rows(path, batch)
        already.update(row["item_id"] for row in batch)
        if on_batch is not None:
            on_batch(benchmark, runtime.arm, len(already), expected)

    return BenchmarkProgress(benchmark=benchmark, arm=runtime.arm,
                             present_before=present_before,
                             generated=rows_written, expected=expected)


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------
def verify_arm(benchmark: str, arm: str, expected_ids: Sequence[str], *,
               root: Path | None = None) -> Completeness:
    """Completeness of one arm's raw rows for one benchmark."""
    path = raw_path(root or EVIDENCE_ROOT, arm, benchmark)
    rows, unreadable = read_rows(path)
    if unreadable:
        raise RunnerError(f"{path} has unparseable lines {unreadable}")
    return validate_complete(rows, expected_ids, arm=arm, benchmark=benchmark)


def verify_run(items_by_benchmark: dict[str, Sequence[EvalItem]], *,
               root: Path | None = None,
               config_hash: str | None = None) -> dict[str, Completeness]:
    """Completeness of every (benchmark, arm) pair, for the report's gates.

    The expected item ids are the *loaded* ones, so this checks the rows
    against the frozen suite rather than against a count: a set that reached
    the right size with the wrong items is not the benchmark. Both arms are
    checked, and a missing arm is reported as missing rather than as a zero —
    a base-only run and a base-vs-adapter comparison are different claims, and
    the report must not be able to confuse them.
    """
    root = root or EVIDENCE_ROOT
    report: dict[str, Completeness] = {}
    for benchmark in BENCHMARK_ORDER:
        ids = [item.item_id for item in items_by_benchmark[benchmark]]
        expected = BENCHMARK_IDENTITIES[benchmark]["expected_items"]
        if len(ids) != expected:
            raise RunnerError(
                f"{benchmark} was given {len(ids)} item ids to verify "
                f"against, the pinned identity says {expected}")
        for arm in ARMS:
            path = raw_path(root, arm, benchmark)
            rows, unreadable = read_rows(path)
            if unreadable:
                raise RunnerError(f"{path} has unparseable lines {unreadable}")
            completeness = validate_complete(rows, ids, arm=arm,
                                             benchmark=benchmark)
            if config_hash is not None:
                _require_config_match(path, rows, config_hash)
            report[f"{arm}:{benchmark}"] = completeness
    return report


def _require_config_match(path: Path, rows: Sequence[dict[str, Any]],
                          config_hash: str) -> None:
    """A row generated under another configuration is not part of this run."""
    mismatched = sorted({str(row.get("config_hash")) for row in rows
                         if row.get("config_hash") != config_hash})
    if mismatched:
        raise RunnerError(
            f"{path} contains rows generated under {mismatched}, not under "
            f"the frozen configuration {config_hash}. Mixing them would make "
            f"the comparison a comparison of two configurations.")


def all_complete(report: dict[str, Completeness]) -> bool:
    return bool(report) and all(item.complete for item in report.values())
