"""T31.4 Raw and scored rows — the evidence, and the rules that keep it honest.

The brief requires each item to retain benchmark, split, item_id, question,
gold answer, both prompts, model and adapter identifiers, raw generation,
normalized generation, extracted answer, scorer result, correctness, error
category, latency and token counts — and is explicit that "Failures are part
of the evidence": "Do not discard incorrect generations."

Two shapes, deliberately separate
----------------------------------
**Raw rows** are what the model produced, plus everything needed to say under
what conditions. They are the expensive artifact and the only one that cannot
be recomputed — regenerating a row means running the GPU again. Nothing in the
scoring layer may edit them.

**Scored rows** are derived: extraction, scoring, error category. Kept apart
because scoring is a *pure function* of the raw row, so a scoring bug can be
fixed by re-running the scorer over stored generations instead of re-running
the model. If the two were one file, the only fix for a parser bug would be
another multi-hour generation run, and mixing the two would make it impossible
to tell whether a changed number came from the model or from the scorer.

Atomicity, resume, and the vacuity rule
---------------------------------------
A run over 6,367 items per arm takes hours. Anything that can be interrupted
must be resumable, and the thing that makes resume dangerous is *partial
output mistaken for a completed benchmark* — which the brief forbids. So
writes go through a read-merge-deduplicate-write that replaces the file
atomically, a torn file can never leave a half-written row behind, and
``validate_complete`` refuses a benchmark whose rows do not cover exactly the
expected item ids, no matter how many rows are present. A benchmark missing
one item is missing the ability to report a rate over it.

Rows are keyed by ``item_id``, so a re-run after an interruption overwrites the
row it replaces rather than appending a second one; duplicates are refused
rather than averaged over.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

from sciencemath.comparability.contract import ARMS, BENCHMARK_ORDER

#: Where the evidence pack lives. ``evaluations/t31/`` is chosen to sit beside
#: the other milestones and, critically, OUTSIDE ``evaluations/t30/`` — the T30
#: freeze globs ``evaluations/t30/*.json`` non-recursively, so a single file
#: added at that level would change the frozen T30 component set. The brief's
#: instruction not to modify the T30 record is satisfied structurally, not by
#: remembering.
EVIDENCE_ROOT: Final = Path("evaluations") / "t31"

RAW_DIR: Final = "raw"
SCORED_DIR: Final = "scored"


class RowError(RuntimeError):
    """A row file is malformed or a write could not be made safely."""


class CompletenessError(RowError):
    """A benchmark's rows do not cover exactly the expected items.

    Raised, never warned: a benchmark that scored 1,200 of 1,319 items has a
    rate over a different benchmark than the one that was frozen.
    """


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_path(root: Path, arm: str, benchmark: str) -> Path:
    _check_coordinates(arm, benchmark)
    return root / EVIDENCE_ROOT / RAW_DIR / arm / f"{benchmark}.jsonl"


def scored_path(root: Path, arm: str, benchmark: str) -> Path:
    _check_coordinates(arm, benchmark)
    return root / EVIDENCE_ROOT / SCORED_DIR / arm / f"{benchmark}.jsonl"


def _check_coordinates(arm: str, benchmark: str) -> None:
    if arm not in ARMS:
        raise RowError(f"unknown arm {arm!r}; expected one of {ARMS}")
    if benchmark not in BENCHMARK_ORDER:
        raise RowError(f"unknown benchmark {benchmark!r}")


# ---------------------------------------------------------------------------
# the two row shapes
# ---------------------------------------------------------------------------
#: Required keys of a raw row. Asserted on write, so a caller that forgets a
#: field learns immediately rather than at report time.
RAW_FIELDS: Final = (
    "arm", "benchmark", "split", "item_id", "native_id", "question",
    "choices", "gold", "gold_label", "system_prompt", "user_prompt",
    "prompt_sha256", "model_id", "model_revision", "adapter_id",
    "adapter_revision", "adapter_sha256", "config_hash", "enable_thinking",
    "raw_generation", "finish_reason", "latency_s", "prompt_tokens",
    "output_tokens", "generated_at", "error",
)

#: Additional keys a scored row carries, on top of every raw field.
SCORED_FIELDS: Final = (
    "normalized_generation", "extracted_answer", "extraction_status",
    "extraction_tier", "extraction_note", "schema_valid", "content_valid",
    "correct", "error_category", "scorer_tier", "scorer_notes",
    "scorer_agrees", "invalid_output", "truncated",
)


def build_raw_row(item, *, arm: str, system_prompt: str, user_prompt: str,
                  model_id: str, model_revision: str, adapter_id: str | None,
                  adapter_revision: str | None, adapter_sha256: str | None,
                  config_hash: str, enable_thinking: bool,
                  raw_generation: str, finish_reason: str,
                  latency_s: float, prompt_tokens: int, output_tokens: int,
                  error: str | None = None) -> dict[str, Any]:
    """One item's generation, with everything needed to interpret it."""
    row = {
        "arm": arm,
        "benchmark": item.benchmark,
        "split": item.split,
        "item_id": item.item_id,
        "native_id": item.native_id,
        "question": item.question,
        "choices": [[label, text] for label, text in item.choices],
        "gold": item.gold,
        "gold_label": item.gold_label,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_sha256": sha256_text(system_prompt + "\x00" + user_prompt),
        "model_id": model_id,
        "model_revision": model_revision,
        "adapter_id": adapter_id,
        "adapter_revision": adapter_revision,
        "adapter_sha256": adapter_sha256,
        "config_hash": config_hash,
        "enable_thinking": enable_thinking,
        "raw_generation": raw_generation,
        "finish_reason": finish_reason,
        "latency_s": round(float(latency_s), 4),
        "prompt_tokens": int(prompt_tokens),
        "output_tokens": int(output_tokens),
        "generated_at": _utc_now(),
        "error": error,
    }
    missing = [field for field in RAW_FIELDS if field not in row]
    if missing:                                    # pragma: no cover
        raise RowError(f"raw row is missing {missing}")
    return row


def build_scored_row(raw: dict[str, Any], *, normalized_generation: str,
                     extraction, score) -> dict[str, Any]:
    """A raw row plus the deterministic scoring of its generation.

    ``content_valid`` and ``schema_valid`` are recorded independently because
    the brief requires them separated permanently: a response can satisfy the
    protocol and be wrong, and protocol compliance must never be read as
    reasoning success. ``content_valid`` is the capability metric; the report
    never substitutes the other for it.
    """
    row = dict(raw)
    row.update({
        "normalized_generation": normalized_generation,
        "extracted_answer": extraction.answer,
        "extraction_status": extraction.status,
        "extraction_tier": extraction.tier,
        "extraction_note": extraction.note,
        "schema_valid": bool(score.schema_valid),
        "content_valid": bool(score.content_valid),
        "correct": bool(score.content_valid),
        "error_category": score.error_category,
        "scorer_tier": score.scorer_tier,
        "scorer_notes": score.notes,
        "scorer_agrees": bool(score.content_valid),
        "invalid_output": not raw.get("raw_generation", "").strip()
                          or raw.get("finish_reason") == "length",
        "truncated": raw.get("finish_reason") == "length",
    })
    return row


# ---------------------------------------------------------------------------
# reading and writing
# ---------------------------------------------------------------------------
def read_rows(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    """Rows and the 1-based line numbers that could not be parsed.

    Corrupt lines are reported rather than skipped silently: a skipped line is
    a missing item, and a missing item changes the denominator.
    """
    if not path.exists():
        return [], []
    rows: list[dict[str, Any]] = []
    bad: list[int] = []
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad.append(number)
    return rows, bad


def append_rows(path: Path, rows: Sequence[dict[str, Any]],
                *, key: str = "item_id") -> int:
    """Add rows, replacing any row with the same key, atomically.

    Read-merge-deduplicate-write rather than a raw append. A raw append leaves
    two rows for the same item after an interruption, and every downstream
    count then quietly depends on which one a reader picks up. Rewriting
    through a temporary file means the artifact on disk is always either the
    previous complete set or the new one, never a partial line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing, bad = read_rows(path)
    if bad:
        raise RowError(
            f"{path} has unparseable lines {bad}; refusing to rewrite over "
            f"evidence that cannot be read")

    merged: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for row in existing:
        if key not in row:
            raise RowError(f"{path}: existing row lacks {key!r}")
        merged[row[key]] = row
        order.append(row[key])
    written = 0
    for row in rows:
        if key not in row:
            raise RowError(f"new row lacks {key!r}")
        if row[key] not in merged:
            order.append(row[key])
        merged[row[key]] = row
        written += 1

    payload = "".join(json.dumps(merged[k], ensure_ascii=False) + "\n"
                      for k in dict.fromkeys(order))
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return written


def completed_item_ids(rows: Iterable[dict[str, Any]]) -> set[str]:
    """Items with a generation to their name.

    A row that recorded a generation *error* still counts as completed: the
    item was attempted, the failure is evidence, and retrying it forever would
    make an interrupted run unresumable.
    """
    return {str(row["item_id"]) for row in rows if "item_id" in row}


def duplicate_item_ids(rows: Sequence[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        item_id = str(row.get("item_id"))
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)
    return sorted(duplicates)


# ---------------------------------------------------------------------------
# completeness
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Completeness:
    arm: str
    benchmark: str
    expected: int
    present: int
    duplicates: tuple[str, ...]
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    config_hashes: tuple[str, ...]

    @property
    def complete(self) -> bool:
        # ``expected > 0`` is the vacuity guard the brief demands: with no
        # expected items there is nothing to be missing, so the counts alone
        # would call an empty benchmark complete and a later rate over it
        # would be computed on no evidence at all.
        return (self.expected > 0
                and not self.missing and not self.unexpected
                and not self.duplicates and len(self.config_hashes) <= 1
                and self.present == self.expected)

    def to_dict(self) -> dict:
        return {
            "arm": self.arm, "benchmark": self.benchmark,
            "expected": self.expected, "present": self.present,
            "duplicates": list(self.duplicates),
            "missing_count": len(self.missing),
            "missing_head": list(self.missing[:10]),
            "unexpected_count": len(self.unexpected),
            "unexpected_head": list(self.unexpected[:10]),
            "config_hashes": list(self.config_hashes),
            "complete": self.complete,
        }

    def describe(self) -> str:
        problems = []
        if self.expected == 0:
            problems.append("no expected items — an empty benchmark cannot be "
                            "complete")
        if self.missing:
            problems.append(f"{len(self.missing)} items missing "
                            f"(e.g. {', '.join(self.missing[:3])})")
        if self.unexpected:
            problems.append(f"{len(self.unexpected)} rows outside the frozen "
                            f"item set (e.g. {', '.join(self.unexpected[:3])})")
        if self.duplicates:
            problems.append(f"{len(self.duplicates)} duplicate item ids")
        if len(self.config_hashes) > 1:
            problems.append(f"{len(self.config_hashes)} distinct config hashes "
                            f"— these rows were not produced by one "
                            f"configuration")
        if not problems:
            return (f"{self.arm}/{self.benchmark}: complete, "
                    f"{self.present} rows")
        return (f"{self.arm}/{self.benchmark}: INCOMPLETE — "
                + "; ".join(problems))


def validate_complete(rows: Sequence[dict[str, Any]], expected_ids: Iterable[str],
                      *, arm: str, benchmark: str) -> Completeness:
    """Check a benchmark's rows against the frozen item set.

    Returns the detail; use ``require_complete`` when the caller intends to
    report a rate, which is the only case where an incomplete set is fatal.
    """
    expected = {str(item_id) for item_id in expected_ids}
    present_ids = [str(row.get("item_id")) for row in rows]
    present = set(present_ids)
    hashes = tuple(sorted({str(row.get("config_hash")) for row in rows
                           if row.get("config_hash")}))
    return Completeness(
        arm=arm, benchmark=benchmark, expected=len(expected),
        present=len(present),
        duplicates=tuple(duplicate_item_ids(rows)),
        missing=tuple(sorted(expected - present)),
        unexpected=tuple(sorted(present - expected)),
        config_hashes=hashes)


def require_complete(rows: Sequence[dict[str, Any]],
                     expected_ids: Iterable[str], *, arm: str,
                     benchmark: str) -> Completeness:
    """``validate_complete``, but refuse to continue when it fails."""
    report = validate_complete(rows, expected_ids, arm=arm,
                               benchmark=benchmark)
    if not report.complete:
        raise CompletenessError(report.describe())
    return report
