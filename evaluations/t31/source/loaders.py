"""T31.3 Benchmark loading — pinned, deterministic, fail-closed.

Three properties matter here and each is a test in its own right.

**Pinned.** Every benchmark is read at an exact dataset revision recorded in
:mod:`sciencemath.comparability.identity`. Names are not identity: a name that
resolves today can resolve to different bytes next month, and an evaluation
that cannot say which bytes it read cannot be reproduced.

**Stable item ids.** An item's id is derived from its content, not from its
position, so it survives a reordering of the dataset, a resume, or a change in
batch size. That is what lets a half-finished run be resumed without silently
shifting which item a stored row refers to — the failure mode where a resume
"completes" a benchmark while quietly scoring the wrong rows.

**Fail-closed.** A benchmark that yields fewer items than its pinned count did
not load, and raising here is the whole point. The brief's non-vacuity rule
bans reporting a rate over an empty or short set; the cheapest place to
enforce that is at the door, before any generation happens.

SciQ needs a note. The ``allenai/sciq`` test split does not ship an option
list — it ships a correct answer and three distractors — so the four options
have to be assembled here. Their order is a sha256-derived permutation seeded
by the item, *not* a random shuffle: it is stable across processes and
machines, identical for both arms, and prevents the correct option from
occupying a fixed position that would let a positional-response bias show up
as accuracy. The permutation is recorded on the item, so the row that stores
the generation also stores the exact option order the model saw.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Final, Mapping

from sciencemath.comparability.contract import BENCHMARKS
from sciencemath.comparability.identity import BENCHMARK_IDENTITIES

#: Prefix for every item id this package mints.
ITEM_ID_PREFIX: Final = "t31-"

#: Salt for the SciQ option permutation. Changing it changes the option order
#: of every SciQ item and therefore every SciQ result; it is fixed here and
#: hashed into the frozen configuration.
OPTION_ORDER_SALT: Final = "t31-sciq-option-order-v1"

_OPTION_LABELS: Final = "ABCDEFGH"


class BenchmarkLoaderError(RuntimeError):
    """A benchmark could not be loaded, or loaded to something unexpected."""


@dataclass(frozen=True)
class EvalItem:
    """One benchmark item, in the exact form both arms will receive it.

    Frozen on purpose: an item is evidence, and evidence that can be mutated
    after the fact is not evidence. ``choices`` is a tuple of ``(label, text)``
    pairs and is empty for the free-form benchmarks.
    """

    item_id: str
    benchmark: str
    split: str
    native_id: str | None
    question: str
    choices: tuple[tuple[str, str], ...]
    gold: str
    gold_label: str | None
    subject: str | None = None
    level: str | None = None
    notes: tuple[str, ...] = ()
    meta: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "benchmark": self.benchmark,
            "split": self.split,
            "native_id": self.native_id,
            "question": self.question,
            "choices": [list(pair) for pair in self.choices],
            "gold": self.gold,
            "gold_label": self.gold_label,
            "subject": self.subject,
            "level": self.level,
            "notes": list(self.notes),
            "meta": dict(self.meta),
        }


def item_id_for(benchmark: str, split: str, seed: str) -> str:
    """Mint a stable id for an item.

    The id is content-addressed over ``benchmark|split|seed``, where ``seed``
    is the benchmark's own native id when it has one and the question text
    when it does not. Both components are included because the same question
    can legitimately appear in two benchmarks, and two different items must
    never share an id — a collision would make resume drop a real item or
    double-count one.
    """
    blob = f"{benchmark}|{split}|{seed}".encode("utf-8")
    return ITEM_ID_PREFIX + benchmark + "-" + hashlib.sha256(blob).hexdigest()[:12]


def suite_hash(items: list[EvalItem]) -> str:
    """Canonical hash over a loaded benchmark, in item-id order.

    This is the hash that goes in the manifest and the frozen configuration.
    If a future run loads even one different question, this changes — which is
    the only reliable way for a reader to know the two runs saw the same
    items.
    """
    ordered = sorted(items, key=lambda item: item.item_id)
    blob = json.dumps([item.to_dict() for item in ordered], sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# per-benchmark normalisation
# ---------------------------------------------------------------------------
def _sciq_options(row: Mapping[str, Any], item_id: str
                  ) -> tuple[tuple[tuple[str, str], ...], str, tuple[str, ...]]:
    """Assemble SciQ's four options in a deterministic, item-seeded order.

    Returns ``(choices, gold_label, notes)``.
    """
    correct = str(row["correct_answer"]).strip()
    raw = [correct, str(row["distractor1"]).strip(),
           str(row["distractor2"]).strip(), str(row["distractor3"]).strip()]

    notes: list[str] = []
    if len({text.casefold() for text in raw}) != len(raw):
        # A distractor identical to the correct answer makes the item
        # unanswerable by construction. Keep the item (dropping it would
        # change the benchmark) but record the defect on the row.
        notes.append("duplicate_option_text")

    order = sorted(range(len(raw)),
                   key=lambda i: hashlib.sha256(
                       f"{OPTION_ORDER_SALT}|{item_id}|{i}".encode("utf-8")
                   ).hexdigest())
    choices = tuple((_OPTION_LABELS[pos], raw[source])
                    for pos, source in enumerate(order))
    gold_label = _OPTION_LABELS[order.index(0)]
    return choices, gold_label, tuple(notes)


_GSM8K_MARKER = re.compile(r"####\s*(.+?)\s*$", re.DOTALL)


def _gsm8k_gold(answer: str) -> tuple[str, tuple[str, ...]]:
    """GSM8K's gold value is the text after the ``####`` marker."""
    match = _GSM8K_MARKER.search(answer)
    if match is None:
        # Not fatal: the raw string is still the reference, and inventing a
        # value here would be worse than recording that the marker was absent.
        return answer.strip(), ("missing_hash_marker",)
    return match.group(1).strip(), ()


def _arc_options(row: Mapping[str, Any]
                 ) -> tuple[tuple[tuple[str, str], ...], str, str | None,
                            tuple[str, ...], dict[str, Any]]:
    """ARC's option labels are not uniform across items, so they are rewritten.

    Measured on the pinned revision: arc_easy's test split labels 2,268 items
    ``A-D`` but 97 items ``1-4``; arc_challenge labels 1,144 ``A-D`` and 21
    ``1-4``. Seven arc_easy items offer only three options and four offer five.

    That is a problem for a *single frozen prompt policy*. The policy asks the
    model to "answer with the single letter of the correct option", and about
    4% of items would then be presented as ``1) text`` — the instruction and
    the item disagree, and items differ from one another in a way that has
    nothing to do with the capability under test. The brief's own extraction
    rule for ARC is "extract one option A/B/C/D".

    So the labels are rewritten to canonical letters in their original order,
    identically for both arms, and the original labels and answer key are kept
    in ``meta`` so the transformation is auditable and reversible. The option
    *text and order* are untouched: this changes how an answer is named, never
    which answer is right.
    """
    raw_labels = [str(label).strip() for label in row["choices"]["label"]]
    texts = [str(text).strip() for text in row["choices"]["text"]]
    notes: list[str] = []

    if len(raw_labels) != len(texts):
        # Malformed pair: keep the shorter, record it, do not invent options.
        depth = min(len(raw_labels), len(texts))
        raw_labels, texts = raw_labels[:depth], texts[:depth]
        notes.append("choice_label_text_mismatch")
    if len(set(raw_labels)) != len(raw_labels):
        notes.append("duplicate_option_labels")
    if len(raw_labels) > len(_OPTION_LABELS):
        notes.append("more_options_than_labels")

    canonical = [_OPTION_LABELS[i] for i in range(len(raw_labels))]
    choices = tuple(zip(canonical, texts))

    answer_key = str(row["answerKey"]).strip()
    keys = [part.strip() for part in re.split(r"[\n,;]+", answer_key)
            if part.strip()]
    mapping = dict(zip(raw_labels, canonical))
    mapped = [mapping[key] for key in keys if key in mapping]

    if len(keys) == 1 and len(mapped) == 1:
        gold_label, gold = mapped[0], mapped[0]
    elif not mapped:
        gold_label, gold = None, answer_key
        notes.append("answer_key_not_in_choices")
    else:
        gold_label, gold = None, answer_key
        notes.append("multiple_answer_keys")
    if raw_labels != canonical:
        notes.append("options_relabelled")

    meta = {
        "gold_source": "answerKey",
        "original_option_labels": raw_labels,
        "original_answer_key": answer_key,
    }
    return choices, gold, gold_label, tuple(notes), meta


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def _load_raw(benchmark: str):
    from datasets import load_dataset

    identity = BENCHMARK_IDENTITIES[benchmark]
    kwargs: dict[str, Any] = {"revision": identity["revision"],
                              "split": identity["split"]}
    try:
        if identity["config"]:
            return load_dataset(identity["repo_id"], identity["config"],
                                **kwargs)
        return load_dataset(identity["repo_id"], **kwargs)
    except Exception as exc:                      # noqa: BLE001 - re-raised
        raise BenchmarkLoaderError(
            f"{benchmark}: could not load {identity['repo_id']} "
            f"@ {identity['revision']}: {type(exc).__name__}: {exc}") from exc


def load_benchmark(benchmark: str) -> list[EvalItem]:
    """Load one benchmark at its pinned revision, or raise.

    Raises rather than returning a short list, because a short list is the
    failure the brief is most concerned about being mistaken for a result.
    """
    if benchmark not in BENCHMARKS:
        raise BenchmarkLoaderError(f"unknown benchmark {benchmark!r}")
    identity = BENCHMARK_IDENTITIES[benchmark]
    split = identity["split"]
    raw = _load_raw(benchmark)

    expected = identity["expected_items"]
    if len(raw) != expected:
        raise BenchmarkLoaderError(
            f"{benchmark}: loaded {len(raw)} items, expected {expected} at "
            f"revision {identity['revision']}. Refusing to score a "
            f"benchmark that did not load.")

    items: list[EvalItem] = []
    for row in raw:
        items.append(_build_item(benchmark, split, dict(row)))

    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        if item.item_id in seen:
            duplicates.add(item.item_id)
        seen.add(item.item_id)
    if duplicates:
        raise BenchmarkLoaderError(
            f"{benchmark}: duplicate item ids {sorted(duplicates)[:5]} — "
            f"resume would silently drop items")
    return items


def _build_item(benchmark: str, split: str, row: Mapping[str, Any]) -> EvalItem:
    notes: tuple[str, ...] = ()

    if benchmark == "gsm8k":
        question = str(row["question"]).strip()
        gold, notes = _gsm8k_gold(str(row["answer"]))
        native_id = None
        seed = question
        choices: tuple[tuple[str, str], ...] = ()
        gold_label = None
        subject = level = None
        meta = {"gold_source": "answer_field_after_hash_marker"}

    elif benchmark == "math500":
        question = str(row["problem"]).strip()
        gold = str(row["answer"]).strip()
        native_id = str(row.get("unique_id") or "") or None
        seed = native_id or question
        choices = ()
        gold_label = None
        subject = str(row.get("subject") or "") or None
        level = str(row.get("level") or "") or None
        meta = {"gold_source": "answer_field"}

    elif benchmark in ("arc_easy", "arc_challenge"):
        question = str(row["question"]).strip()
        native_id = str(row.get("id") or "") or None
        seed = native_id or question
        choices, gold, gold_label, notes, meta = _arc_options(row)
        subject = level = None

    elif benchmark == "sciq":
        question = str(row["question"]).strip()
        native_id = None
        seed = question
        provisional = item_id_for(benchmark, split, seed)
        choices, gold_label, notes = _sciq_options(row, provisional)
        gold = gold_label
        subject = level = None
        meta = {
            "gold_source": "correct_answer",
            "correct_answer_text": str(row["correct_answer"]).strip(),
            "option_order": "sha256-seeded permutation "
                            f"({OPTION_ORDER_SALT})",
            # SciQ's support passage is deliberately NOT put in the prompt.
            # It is an answer key, not part of the question.
            "support_present": bool(str(row.get("support") or "").strip()),
        }

    else:                                          # pragma: no cover
        raise BenchmarkLoaderError(f"unknown benchmark {benchmark!r}")

    return EvalItem(
        item_id=item_id_for(benchmark, split, seed),
        benchmark=benchmark, split=split, native_id=native_id,
        question=question, choices=choices, gold=gold, gold_label=gold_label,
        subject=subject, level=level, notes=notes, meta=meta,
    )


def load_all(benchmarks: tuple[str, ...] | None = None
             ) -> dict[str, list[EvalItem]]:
    """Load every requested benchmark, in the frozen report order."""
    from sciencemath.comparability.contract import BENCHMARK_ORDER

    wanted = benchmarks or BENCHMARK_ORDER
    unknown = [name for name in wanted if name not in BENCHMARKS]
    if unknown:
        raise BenchmarkLoaderError(f"unknown benchmarks {unknown}")
    return {name: load_benchmark(name) for name in wanted}
