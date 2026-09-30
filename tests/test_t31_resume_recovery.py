"""T31 adapter SciQ resume-recovery guarantees (six directed tests).

The original T31 run was interrupted in the adapter SciQ arm at 320/1000. The
resume path is the runner's already-pinned resume-by-item-id mechanics; this
module adds the recovery-directed proofs the recovery brief asks for before a
GPU run is allowed:

* **A** — completed rows survive resume byte-identically, even though the
  file is rewritten by the atomic read-merge-dedup-write;
* **B** — exactly the missing items are generated, never the completed ones;
* **C** — resuming a completed file generates nothing (idempotence);
* **D** — an interruption *during* a resume costs nothing and completes
  cleanly on the next resume;
* **E** — resuming one arm never touches the other arm's files;
* **F** — resuming one benchmark never touches sibling benchmark files.

These run against a stub model, like ``test_t31_comparability_runner.py``:
the properties are properties of the runner and the row store, and a test that
needed a GPU would not be run often enough to be worth having. The real
weights are exercised by the resumed run itself, and the pre-resume merge
rehearsal against the production evidence tree runs before it.
"""
from __future__ import annotations

import pytest
import torch

from sciencemath.comparability import runner as R
from sciencemath.comparability.contract import ARM_ADAPTER, ARM_BASE
from sciencemath.comparability.identity import BENCHMARK_IDENTITIES
from sciencemath.comparability.rows import append_rows, raw_path, read_rows

from t31_comparability_support import item

CONFIG = "c" * 64
EOS = 151645
PAD = 151643


class StubTokenizer:
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
        rows = [[1] * (sum(map(ord, text)) % 7 + 1) for text in texts]
        width = max(len(row) for row in rows)
        mask = [[0] * (width - len(row)) + [1] * len(row) for row in rows]
        ids = [[PAD] * (width - len(row)) + row for row in rows]
        return {"input_ids": torch.tensor(ids, dtype=torch.long),
                "attention_mask": torch.tensor(mask, dtype=torch.long)}

    def decode(self, ids, skip_special_tokens=True):
        return "text:" + ",".join(str(int(i)) for i in ids)


class StubModel:
    """Reply tokens are configurable so a resumed row differs from its
    pre-interruption sibling and the check cannot pass by accident."""

    def __init__(self, *, reply=(7, 8)):
        self.reply = list(reply)
        self.calls: list[int] = []

    def parameters(self):
        yield torch.zeros(1)

    def generate(self, input_ids, attention_mask=None, **kwargs):
        self.calls.append(int(input_ids.shape[0]))
        block = torch.tensor([self.reply + [EOS]], dtype=torch.long).repeat(
            input_ids.shape[0], 1)
        return torch.cat([input_ids, block], dim=1)


class CrashingModel(StubModel):
    """Writes ``fail_after`` batches, then raises: an interruption
    *mid-resume*, after some batches have already been appended."""

    def __init__(self, *, fail_after: int, reply=(7, 8)):
        super().__init__(reply=reply)
        self.fail_after = fail_after

    def generate(self, input_ids, attention_mask=None, **kwargs):
        if len(self.calls) >= self.fail_after:
            raise RuntimeError("simulated interruption")
        return super().generate(input_ids, attention_mask=attention_mask,
                                **kwargs)


def runtime(arm, model) -> R.ArmRuntime:
    return R.ArmRuntime(arm=arm, model=model, tokenizer=StubTokenizer())


def items(n: int, benchmark: str = "gsm8k"):
    return [item(benchmark, question=f"Question {i}?", gold=str(i),
                 native_id=f"n{i}") for i in range(n)]


def seed_partial(path, subjects, *, arm, model, batch_size=2) -> list[str]:
    """Persist rows through the *production* write path, so the byte-preservation
    check compares like with like (iter_rows -> append_rows)."""
    ids = []
    for batch in R.iter_rows(runtime(arm, model), subjects[0].benchmark,
                             subjects, config_hash=CONFIG, batch_size=batch_size):
        append_rows(path, batch)
        ids.extend(row["item_id"] for row in batch)
    return ids


def file_bytes(path):
    return path.read_text(encoding="utf-8")


@pytest.fixture()
def suite(monkeypatch, request):
    """A small suite registered under a benchmark name, with the pinned
    expected count patched the same way every resume test does."""
    n = getattr(request, "param", 6)
    monkeypatch.setitem(BENCHMARK_IDENTITIES["gsm8k"], "expected_items", n)
    return items(n)


# ---------------------------------------------------------------------------
# Test A — completed rows survive resume byte-identically
# ---------------------------------------------------------------------------
def test_a_completed_rows_survive_resume_byte_identical(tmp_path, suite):
    path = raw_path(tmp_path, ARM_ADAPTER, "gsm8k")
    before = seed_partial(path, suite[:4], arm=ARM_ADAPTER, model=StubModel())
    original_lines = file_bytes(path).splitlines()
    assert len(original_lines) == 4

    resumed = R.run_benchmark(runtime(ARM_ADAPTER, StubModel(reply=(9, 9))),
                              "gsm8k", suite, config_hash=CONFIG,
                              batch_size=2, root=tmp_path)
    lines = file_bytes(path).splitlines()
    assert len(lines) == 6
    # Byte-identical, not merely semantically equal: line i is unchanged for
    # every row that pre-dated the resume.
    assert lines[:4] == original_lines
    rows, _ = read_rows(path)
    assert [row["item_id"] for row in rows[:4]] == before
    assert resumed.present_before == 4 and resumed.generated == 2


# ---------------------------------------------------------------------------
# Test B — only the missing ids execute
# ---------------------------------------------------------------------------
def test_b_only_missing_ids_execute(tmp_path, suite):
    path = raw_path(tmp_path, ARM_ADAPTER, "gsm8k")
    seed_partial(path, suite[:4], arm=ARM_ADAPTER, model=StubModel())
    completed_ids = {row["item_id"] for row in read_rows(path)[0]}

    model = StubModel(reply=(4, 5))
    R.run_benchmark(runtime(ARM_ADAPTER, model), "gsm8k", suite,
                    config_hash=CONFIG, batch_size=2, root=tmp_path)
    # 2 missing items at batch_size 2: exactly one batch of two, and not one
    # generate() call more.
    assert model.calls == [2]
    rows, _ = read_rows(path)
    newly = [row for row in rows if row["item_id"] not in completed_ids]
    assert sorted(row["item_id"] for row in newly) == sorted(
        it.item_id for it in suite if it.item_id not in completed_ids)
    # The new rows are genuinely new generations, distinguishable from the
    # pre-resume rows they must not regenerate.
    assert all(row["raw_generation"] == "text:4,5" for row in newly)


# ---------------------------------------------------------------------------
# Test C — resuming a completed benchmark generates nothing
# ---------------------------------------------------------------------------
def test_c_second_resume_generates_nothing(tmp_path, suite):
    path = raw_path(tmp_path, ARM_ADAPTER, "gsm8k")
    R.run_benchmark(runtime(ARM_ADAPTER, StubModel()), "gsm8k", suite,
                    config_hash=CONFIG, batch_size=2, root=tmp_path)
    model = StubModel()
    result = R.run_benchmark(runtime(ARM_ADAPTER, model), "gsm8k", suite,
                             config_hash=CONFIG, batch_size=2, root=tmp_path)
    assert result.generated == 0 and result.present_before == 6
    assert model.calls == []
    assert duplicate_free(path)


def duplicate_free(path) -> bool:
    rows, _ = read_rows(path)
    ids = [row["item_id"] for row in rows]
    return len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Test D — interruption during a resume, then completed by a later resume
# ---------------------------------------------------------------------------
def test_d_interrupted_resume_completes_cleanly(tmp_path, suite):
    path = raw_path(tmp_path, ARM_ADAPTER, "gsm8k")
    seed_partial(path, suite[:2], arm=ARM_ADAPTER, model=StubModel())
    original_lines = file_bytes(path).splitlines()

    # The first missing batch lands (4 rows present), then the interruption
    # takes the process before the second; the last two rows are unwritten.
    with pytest.raises(RuntimeError, match="interruption"):
        R.run_benchmark(runtime(ARM_ADAPTER, CrashingModel(fail_after=1)),
                        "gsm8k", suite, config_hash=CONFIG, batch_size=2,
                        root=tmp_path)
    lines = file_bytes(path).splitlines()
    assert lines[:2] == original_lines
    assert len(lines) == 4

    final = R.run_benchmark(runtime(ARM_ADAPTER, StubModel(reply=(3, 3))),
                            "gsm8k", suite, config_hash=CONFIG, batch_size=2,
                            root=tmp_path)
    assert final.complete and final.present_before == 4 and \
        final.generated == 2
    assert duplicate_free(path)
    rows, _ = read_rows(path)
    assert [row["item_id"] for row in rows[:2]] == \
        [it.item_id for it in suite[:2]]


# ---------------------------------------------------------------------------
# Test E — arm isolation: resuming the adapter never touches the base arm
# ---------------------------------------------------------------------------
def test_e_arm_isolation_base_files_untouched(tmp_path, suite):
    base_path = raw_path(tmp_path, ARM_BASE, "gsm8k")
    seed_partial(base_path, suite, arm=ARM_BASE, model=StubModel())
    base_before = file_bytes(base_path)

    adapter_path = raw_path(tmp_path, ARM_ADAPTER, "gsm8k")
    seed_partial(adapter_path, suite[:3], arm=ARM_ADAPTER, model=StubModel())
    R.run_benchmark(runtime(ARM_ADAPTER, StubModel()), "gsm8k", suite,
                    config_hash=CONFIG, batch_size=2, root=tmp_path)

    assert file_bytes(base_path) == base_before


# ---------------------------------------------------------------------------
# Test F — benchmark isolation: resuming sciq never touches sibling files
# ---------------------------------------------------------------------------
def test_f_benchmark_isolation_siblings_untouched(tmp_path, suite, monkeypatch):
    # The benchmark under resume and its sibling, both present with data.
    monkeypatch.setitem(BENCHMARK_IDENTITIES["sciq"], "expected_items", 4)
    sciq_items = items(4, benchmark="sciq")

    adapter_path = raw_path(tmp_path, ARM_ADAPTER, "gsm8k")
    seed_partial(adapter_path, suite, arm=ARM_ADAPTER, model=StubModel())
    sibling_before = file_bytes(adapter_path)

    R.run_benchmark(runtime(ARM_ADAPTER, StubModel()), "sciq", sciq_items,
                    config_hash=CONFIG, batch_size=2, root=tmp_path)

    assert file_bytes(adapter_path) == sibling_before
    rows, _ = read_rows(raw_path(tmp_path, ARM_ADAPTER, "sciq"))
    assert len(rows) == 4