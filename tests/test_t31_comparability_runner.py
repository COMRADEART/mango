"""T31 tests, brief categories 11-16 for the runner: capture and resumption.

The runner is where an evaluation most easily produces a number that cannot be
justified, so the properties tested here are the ones that would let that
happen quietly:

* a generation is captured in full, with every field the brief lists, or the
  row is not written;
* an interrupted run resumes by item id, not by position, and never writes the
  same item twice;
* a run that produced fewer items than the frozen suite is refused rather than
  reported as a rate over a shorter benchmark;
* rows from two different frozen configurations are never mixed.

These run against a stub model rather than the 1.7B checkpoint. The properties
under test are properties of the runner, not of the weights, and a unit test
that needed a GPU would not be run often enough to be worth having. The real
weights are exercised by the smoke test and the full run.
"""
from __future__ import annotations

import json

import pytest
import torch

from sciencemath.comparability import runner as R
from sciencemath.comparability.contract import ARM_ADAPTER, ARM_BASE
from sciencemath.comparability.identity import (
    BENCHMARK_IDENTITIES, MODEL_IDENTITIES,
)
from sciencemath.comparability.rows import append_rows, raw_path, read_rows

from t31_comparability_support import item

CONFIG = "c" * 64
EOS = 151645
PAD = 151643


class StubTokenizer:
    """The slice of the HF tokenizer API the runner actually uses."""

    padding_side = "right"
    pad_token_id = PAD
    eos_token_id = EOS
    eos_token = "<|im_end|>"

    def apply_chat_template(self, messages, *, tokenize=False,
                            add_generation_prompt=True, enable_thinking=None):
        body = "".join(m["content"] for m in messages)
        return f"<|im_start|>user\n{body}<|im_end|>\n<|im_start|>assistant\n"

    def __call__(self, texts, *, return_tensors=None, padding=False,
                 add_special_tokens=True):
        # Variable-length prompts, derived from the text so that different
        # prompts really do tokenise to different lengths. Padding and the
        # slice that recovers each generation are then actually exercised.
        rows = [[1] * (sum(map(ord, text)) % 7 + 1) for text in texts]
        width = max(len(row) for row in rows)
        mask = [[0] * (width - len(row)) + [1] * len(row) for row in rows]
        ids = [[PAD] * (width - len(row)) + row for row in rows]
        return {"input_ids": torch.tensor(ids, dtype=torch.long),
                "attention_mask": torch.tensor(mask, dtype=torch.long)}

    def decode(self, ids, skip_special_tokens=True):
        return "text:" + ",".join(str(int(i)) for i in ids)


class StubModel:
    """A deterministic stand-in for a causal LM.

    ``terminate=True`` emits the reply and then the stop token, so the runner
    must label the generation ``stop``. ``terminate=False`` emits exactly the
    token budget and no stop token, so the runner must label it ``length``.
    Emitting the budget either way would make the second case untestable, and
    the first is the case that distinguishes a finished answer from a cut-off
    one.
    """

    def __init__(self, *, reply=(7, 8), terminate=True):
        self.reply = list(reply)
        self.terminate = terminate
        self.calls: list[int] = []

    def parameters(self):
        yield torch.zeros(1)

    def generate(self, input_ids, attention_mask=None, **kwargs):
        self.calls.append(int(input_ids.shape[0]))
        budget = int(kwargs["max_new_tokens"])
        reply = list(self.reply) + [EOS] if self.terminate else [9] * budget
        block = torch.tensor([reply], dtype=torch.long).repeat(
            input_ids.shape[0], 1)
        return torch.cat([input_ids, block], dim=1)


def runtime(arm=ARM_BASE, **model_kwargs) -> R.ArmRuntime:
    return R.ArmRuntime(arm=arm, model=StubModel(**model_kwargs),
                        tokenizer=StubTokenizer())


def items(n: int, benchmark: str = "gsm8k"):
    return [item(benchmark, question=f"Question {i}?", gold=str(i),
                 native_id=f"n{i}") for i in range(n)]


def rows_for(subjects, *, arm=None, batch_size=8, benchmark="gsm8k",
             **model_kwargs) -> list[dict]:
    """Every raw row the runner would produce, across all batches."""
    arm = arm or runtime(**model_kwargs)
    rows: list[dict] = []
    for batch in R.iter_rows(arm, benchmark, subjects, config_hash=CONFIG,
                             batch_size=batch_size):
        rows.extend(batch)
    return rows


# ---------------------------------------------------------------------------
# identities and the adapter guard
# ---------------------------------------------------------------------------
def test_sha256_file_matches_hashlib(tmp_path):
    import hashlib

    target = tmp_path / "blob.bin"
    target.write_bytes(b"t31" * 1000)
    assert R.sha256_file(target) == hashlib.sha256(b"t31" * 1000).hexdigest()


def test_a_missing_snapshot_is_a_clear_refusal(tmp_path, monkeypatch):
    """Resolving the name instead would compare against unpinned bytes."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    with pytest.raises(R.RunnerError, match="not in the local cache"):
        R._hub_snapshot("Qwen/Qwen3-1.7B", "deadbeef")


def test_a_changed_adapter_is_refused_not_warned_about(tmp_path, monkeypatch):
    """A different adapter is a different experiment."""
    identity = MODEL_IDENTITIES["adapter"]
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    snapshot = (tmp_path / "hub" / "models--ComradeRt--Mango-T30-1.7B" /
                "snapshots" / identity["revision"])
    snapshot.mkdir(parents=True)
    (snapshot / identity["weights_file"]).write_bytes(b"not the T30 adapter")
    with pytest.raises(R.RunnerError, match="adapter bytes have changed"):
        R.adapter_snapshot()


def test_an_adapter_that_ships_a_tokenizer_is_refused(tmp_path, monkeypatch):
    """Otherwise the tokenizer stops being a shared constant factor."""
    identity = MODEL_IDENTITIES["adapter"]
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    snapshot = (tmp_path / "hub" / "models--ComradeRt--Mango-T30-1.7B" /
                "snapshots" / identity["revision"])
    snapshot.mkdir(parents=True)
    weights = snapshot / identity["weights_file"]
    weights.write_bytes(b"x")
    monkeypatch.setitem(identity, "weights_sha256", R.sha256_file(weights))
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    with pytest.raises(R.RunnerError, match="ships"):
        R.adapter_snapshot()


def test_an_unknown_arm_is_refused():
    with pytest.raises(R.RunnerError, match="unknown arm"):
        R.load_arm("mango")


def test_the_two_arms_carry_the_identities_the_report_needs():
    base = runtime(ARM_BASE).row_identity()
    adapter = runtime(ARM_ADAPTER).row_identity()
    assert base["adapter_id"] is None and base["adapter_sha256"] is None
    assert base["model_id"] == MODEL_IDENTITIES["base"]["repo_id"]
    assert adapter["adapter_id"] == MODEL_IDENTITIES["adapter"]["repo_id"]
    assert adapter["adapter_sha256"] == \
        MODEL_IDENTITIES["adapter"]["weights_sha256"]
    # The base the adapter was trained on is the base being compared to it.
    assert adapter["model_revision"] == base["model_revision"]


# ---------------------------------------------------------------------------
# category 14 - raw output persistence
# ---------------------------------------------------------------------------
def test_a_raw_row_carries_every_field_the_brief_lists():
    rows = rows_for(items(2), batch_size=2)
    assert len(rows) == 2
    row = rows[0]
    for field in ("benchmark", "split", "item_id", "question", "gold",
                  "system_prompt", "user_prompt", "model_id",
                  "adapter_id", "raw_generation", "config_hash",
                  "latency_s", "prompt_tokens", "output_tokens",
                  "finish_reason", "arm"):
        assert field in row, field
    assert row["raw_generation"] == "text:7,8"
    assert row["finish_reason"] == "stop"
    assert row["arm"] == ARM_BASE


def test_the_prompt_on_the_row_is_the_prompt_that_was_sent():
    subject = items(1)[0]
    row = rows_for([subject], batch_size=1)[0]
    assert row["user_prompt"] == R.prompt_text(subject, "numeric")
    assert subject.question in row["user_prompt"]


def test_the_bare_prompt_is_stored_without_the_chat_template():
    """The row must show what the item asked and what the model received, so
    that the template can be audited separately from the prompt."""
    row = rows_for(items(1), batch_size=1)[0]
    assert "<|im_start|>assistant" not in row["user_prompt"]
    assert row["user_prompt"]


def test_the_stop_token_is_not_part_of_the_recorded_generation():
    row = rows_for(items(1), batch_size=1)[0]
    assert str(EOS) not in row["raw_generation"]


def test_uncertain_generations_are_not_discarded():
    """Failures are part of the evidence, so they are written like any other
    row rather than filtered out before capture."""
    row = rows_for(items(1), batch_size=1, reply=())[0]
    assert row["raw_generation"] == "text:"
    assert row["finish_reason"] == "stop"
    assert row["output_tokens"] == 1


# ---------------------------------------------------------------------------
# generation mechanics
# ---------------------------------------------------------------------------
def test_a_generation_that_hits_the_budget_is_labelled_length():
    arm = runtime(terminate=False)
    generations, reasons, _, counts, _ = R.generate_batch(
        arm, ["hello"], max_new_tokens=3)
    assert reasons == ["length"]
    assert counts == [3]
    assert len(generations[0].split(",")) == 3


def test_a_generation_that_stops_early_is_labelled_stop():
    arm = runtime(terminate=True)
    _, reasons, _, counts, _ = R.generate_batch(arm, ["hello"],
                                                max_new_tokens=10)
    assert reasons == ["stop"]
    # The reply plus the stop token: the stop is counted, not decoded.
    assert counts == [3]


class RaggedModel:
    """One batch in which a row stops early and its neighbour runs the budget.

    This is the shape left padding leaves behind: the rows that finished early
    are filled with pad tokens out to the batch's longest generation, so a
    length measured from the padded width is the batch's length, reported once
    per row. ``StubModel`` cannot exercise it — it gives every row in a batch
    the same reply.
    """

    def __init__(self, *, short=(7, 8)):
        self.short = list(short)

    def parameters(self):
        yield torch.zeros(1)

    def generate(self, input_ids, attention_mask=None, **kwargs):
        budget = int(kwargs["max_new_tokens"])
        pad = int(kwargs["pad_token_id"])
        finished = self.short + [EOS]
        running = [9] * budget
        width = max(len(finished), len(running))
        rows = [finished + [pad] * (width - len(finished)), running]
        block = torch.tensor(rows, dtype=torch.long)
        return torch.cat([input_ids, block], dim=1)


def test_a_row_is_measured_to_its_own_stop_not_the_batchs_longest():
    """The defect this pins: counting from the padded width gives every row in
    a batch the same length, and labels a row that finished cleanly as
    "length" — which then marks it truncated, invalid, and an error of type
    truncated_generation, for an answer it had already finished giving."""
    arm = R.ArmRuntime(arm=ARM_BASE, model=RaggedModel(),
                       tokenizer=StubTokenizer())
    generations, reasons, _, counts, _ = R.generate_batch(
        arm, ["a", "b"], max_new_tokens=6)

    assert reasons == ["stop", "length"]
    assert counts == [3, 6]
    assert len(set(counts)) == 2, "rows in one batch are measured separately"
    # The pad run is not decoded, and neither is the stop.
    assert generations[0] == "text:7,8"
    assert all(str(PAD) not in generation for generation in generations)


def test_the_budget_comes_from_the_frozen_per_benchmark_spec():
    """ARC gets 32 tokens and MATH-500 gets 1024; a runner that used one
    number for all five would truncate some and waste time on others."""
    from sciencemath.comparability.contract import BENCHMARKS

    assert BENCHMARKS["arc_easy"]["max_new_tokens"] == 32
    assert BENCHMARKS["math500"]["max_new_tokens"] == 1024
    assert len({spec["max_new_tokens"] for spec in BENCHMARKS.values()}) > 1


def test_greedy_decoding_is_the_only_mode_used():
    """Sampling would make a difference between arms a difference between
    draws, so the runner must never sample."""
    import inspect

    source = inspect.getsource(R.generate_batch)
    assert "do_sample=False" in source
    assert "num_beams=1" in source


def test_prompt_token_counts_are_per_item_not_per_batch():
    rows = rows_for(items(3), batch_size=3)
    counts = [row["prompt_tokens"] for row in rows]
    assert len(set(counts)) > 1, "prompts differ, so token counts must differ"
    assert all(count > 0 for count in counts)


def test_batching_does_not_change_the_row_set():
    """The paired comparison assumes the same items in the same order."""
    subjects = items(5)
    one = [row["item_id"] for row in rows_for(subjects, batch_size=1)]
    whole = [row["item_id"] for row in rows_for(subjects, batch_size=5)]
    assert one == whole
    assert len(whole) == 5


# ---------------------------------------------------------------------------
# categories 11, 12, 15, 16 - resumption and completeness
# ---------------------------------------------------------------------------
@pytest.fixture()
def small_gsm8k(monkeypatch):
    """Three-item GSM8K, so resumption can be tested without 1,319 rows."""
    monkeypatch.setitem(BENCHMARK_IDENTITIES["gsm8k"], "expected_items", 3)
    return items(3)


def test_a_complete_run_writes_one_row_per_item(tmp_path, small_gsm8k):
    progress = R.run_benchmark(runtime(), "gsm8k", small_gsm8k,
                               config_hash=CONFIG, batch_size=2, root=tmp_path)
    assert progress.complete and progress.generated == 3
    rows, bad = read_rows(raw_path(tmp_path, ARM_BASE, "gsm8k"))
    assert not bad and len(rows) == 3


def test_rerunning_a_complete_benchmark_generates_nothing(
        tmp_path, small_gsm8k):
    """Resumption must be idempotent, or a re-run inflates the evidence."""
    first = R.run_benchmark(runtime(), "gsm8k", small_gsm8k,
                            config_hash=CONFIG, batch_size=2, root=tmp_path)
    model = StubModel()
    second = R.run_benchmark(R.ArmRuntime(arm=ARM_BASE, model=model,
                                          tokenizer=StubTokenizer()),
                             "gsm8k", small_gsm8k, config_hash=CONFIG,
                             batch_size=2, root=tmp_path)
    assert first.generated == 3
    assert second.generated == 0
    assert second.present_before == 3
    assert model.calls == [], "no generation should have been requested"


def test_an_interrupted_run_resumes_without_duplicating(tmp_path,
                                                       small_gsm8k):
    """The failure this prevents: a torn run that counts an item twice."""
    path = raw_path(tmp_path, ARM_BASE, "gsm8k")
    append_rows(path, rows_for(small_gsm8k[:1], batch_size=1))
    rows, _ = read_rows(path)
    assert len(rows) == 1

    progress = R.run_benchmark(runtime(), "gsm8k", small_gsm8k,
                               config_hash=CONFIG, batch_size=2, root=tmp_path)
    assert progress.present_before == 1
    assert progress.generated == 2
    rows, bad = read_rows(path)
    assert not bad
    assert len(rows) == 3
    assert len({row["item_id"] for row in rows}) == 3


def test_resumption_is_by_item_id_not_by_row_count(tmp_path, small_gsm8k):
    """A row for an item the run has already done, however it got there, is
    not generated again — even when the file's rows are out of order."""
    path = raw_path(tmp_path, ARM_BASE, "gsm8k")
    append_rows(path, rows_for([small_gsm8k[2]], batch_size=1))
    model = StubModel()
    progress = R.run_benchmark(R.ArmRuntime(arm=ARM_BASE, model=model,
                                            tokenizer=StubTokenizer()),
                               "gsm8k", small_gsm8k, config_hash=CONFIG,
                               batch_size=1, root=tmp_path)
    assert progress.present_before == 1
    assert progress.generated == 2
    rows, _ = read_rows(path)
    assert {row["item_id"] for row in rows} == \
        {i.item_id for i in small_gsm8k}


def test_different_arms_are_captured_to_different_files(tmp_path,
                                                       small_gsm8k):
    R.run_benchmark(runtime(ARM_BASE), "gsm8k", small_gsm8k,
                    config_hash=CONFIG, batch_size=3, root=tmp_path)
    R.run_benchmark(runtime(ARM_ADAPTER), "gsm8k", small_gsm8k,
                    config_hash=CONFIG, batch_size=3, root=tmp_path)
    base, _ = read_rows(raw_path(tmp_path, ARM_BASE, "gsm8k"))
    adapter, _ = read_rows(raw_path(tmp_path, ARM_ADAPTER, "gsm8k"))
    assert len(base) == len(adapter) == 3
    assert {row["arm"] for row in base} == {ARM_BASE}
    assert {row["arm"] for row in adapter} == {ARM_ADAPTER}
    assert {row["adapter_id"] for row in adapter} == \
        {MODEL_IDENTITIES["adapter"]["repo_id"]}


def test_a_suite_shorter_than_the_pinned_identity_is_refused(
        tmp_path, monkeypatch):
    """A short suite makes every rate a rate over something else."""
    monkeypatch.setitem(BENCHMARK_IDENTITIES["gsm8k"], "expected_items", 10)
    with pytest.raises(R.RunnerError, match="pinned identity says 10"):
        R.run_benchmark(runtime(), "gsm8k", items(3), config_hash=CONFIG,
                        batch_size=3, root=tmp_path)


def test_a_suite_longer_than_the_pinned_identity_is_refused(
        tmp_path, monkeypatch):
    monkeypatch.setitem(BENCHMARK_IDENTITIES["gsm8k"], "expected_items", 2)
    with pytest.raises(R.RunnerError, match="loaded 3 items"):
        R.run_benchmark(runtime(), "gsm8k", items(3), config_hash=CONFIG,
                        batch_size=3, root=tmp_path)


def test_a_short_run_is_reported_as_incomplete(tmp_path, small_gsm8k):
    append_rows(raw_path(tmp_path, ARM_BASE, "gsm8k"),
                rows_for(small_gsm8k[:2], batch_size=2))
    completeness = R.verify_arm("gsm8k", ARM_BASE,
                                [i.item_id for i in small_gsm8k], root=tmp_path)
    assert completeness.complete is False
    assert len(completeness.missing) == 1
    assert "INCOMPLETE" in completeness.describe()


def test_an_empty_run_is_never_complete(tmp_path, small_gsm8k):
    """The vacuity guard: zero rows over a non-empty suite is not 100%."""
    completeness = R.verify_arm("gsm8k", ARM_BASE,
                                [i.item_id for i in small_gsm8k], root=tmp_path)
    assert completeness.present == 0
    assert completeness.complete is False


def test_verify_run_checks_both_arms_and_names_the_missing_one(
        tmp_path, small_gsm8k, monkeypatch):
    for benchmark in ("math500", "arc_easy", "arc_challenge", "sciq"):
        monkeypatch.setitem(BENCHMARK_IDENTITIES[benchmark], "expected_items", 0)
    R.run_benchmark(runtime(ARM_BASE), "gsm8k", small_gsm8k,
                    config_hash=CONFIG, batch_size=3, root=tmp_path)
    report = R.verify_run({"gsm8k": small_gsm8k, "math500": [], "arc_easy": [],
                           "arc_challenge": [], "sciq": []}, root=tmp_path)
    assert report["base:gsm8k"].complete is True
    # The adapter arm was never run, and the report says so rather than
    # reading its absence as a zero.
    assert report["adapter:gsm8k"].complete is False
    assert report["adapter:gsm8k"].present == 0
    assert R.all_complete(report) is False


def test_verify_run_refuses_rows_from_another_configuration(
        tmp_path, small_gsm8k, monkeypatch):
    """Otherwise the comparison is between two configurations, not two arms."""
    for benchmark in ("math500", "arc_easy", "arc_challenge", "sciq"):
        monkeypatch.setitem(BENCHMARK_IDENTITIES[benchmark], "expected_items", 0)
    R.run_benchmark(runtime(ARM_BASE), "gsm8k", small_gsm8k,
                    config_hash="d" * 64, batch_size=3, root=tmp_path)
    with pytest.raises(R.RunnerError, match="not under the frozen"):
        R.verify_run({"gsm8k": small_gsm8k, "math500": [], "arc_easy": [],
                      "arc_challenge": [], "sciq": []}, root=tmp_path,
                     config_hash=CONFIG)


def test_verify_run_refuses_an_item_count_that_contradicts_the_identity(
        tmp_path, small_gsm8k):
    """Verifying against the wrong item set would validate the wrong thing."""
    with pytest.raises(R.RunnerError, match="item ids to verify against"):
        R.verify_run({"gsm8k": small_gsm8k[:2], "math500": [], "arc_easy": [],
                      "arc_challenge": [], "sciq": []}, root=tmp_path)


def test_unreadable_evidence_stops_a_resume_rather_than_being_skipped(
        tmp_path, small_gsm8k):
    path = raw_path(tmp_path, ARM_BASE, "gsm8k")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"item_id": "ok"}\nnot json\n', encoding="utf-8")
    with pytest.raises(R.RunnerError, match="unparseable"):
        R.run_benchmark(runtime(), "gsm8k", small_gsm8k, config_hash=CONFIG,
                        batch_size=3, root=tmp_path)


def test_the_batch_callback_reports_monotonic_progress(tmp_path, small_gsm8k):
    seen: list[tuple[str, int, int]] = []
    R.run_benchmark(runtime(), "gsm8k", small_gsm8k, config_hash=CONFIG,
                    batch_size=1, root=tmp_path,
                    on_batch=lambda b, a, done, total: seen.append((b, done,
                                                                    total)))
    assert [done for _, done, _ in seen] == [1, 2, 3]
    assert {total for _, _, total in seen} == {3}


def test_rows_are_valid_json_lines_on_disk(tmp_path, small_gsm8k):
    R.run_benchmark(runtime(), "gsm8k", small_gsm8k, config_hash=CONFIG,
                    batch_size=2, root=tmp_path)
    path = raw_path(tmp_path, ARM_BASE, "gsm8k")
    for line in path.read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["arm"] == ARM_BASE
