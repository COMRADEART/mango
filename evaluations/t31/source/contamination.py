"""T31.7 Training-overlap disclosure — measured, not asserted.

The brief requires a table of "known training overlap" per benchmark and is
emphatic that contaminated evaluation must never be presented as fully unseen
generalization: "Do not claim ARC is held out if that claim cannot be
substantiated."

There are two kinds of claim in that table and they are established in two
different ways, so this module keeps them separate.

**Documented composition** — what the frozen training corpora say they
contain. Evidence read out of the repository: the corpus manifests record
GSM8K, MATH (``EleutherAI/hendrycks_math``) and SciQ as sources, and record
``ai2-arc`` as excluded with ``eval_only: true``. A claim about the *training
recipe*.

**Measured item-level overlap** — whether any evaluation item actually occurs
in a training record. Computed here, against the corpora on disk. A claim
about *these items*.

A benchmark can be clean by one measure and not the other, and conflating them
is how a project ends up claiming a holdout it does not have. Both are
reported. Where the measurement contradicts the recipe, the measurement wins
and the report says so.


Why this module does not reuse ``sciencemath.datasets.leakage``
----------------------------------------------------------------
It was the first choice, precisely so the numbers would be comparable with the
project's existing contamination reports. It was measured against known
answers and found unfit for this corpus, in two independent ways.

1. ``find_near_leakage`` returns **zero pairs** for a pair whose similarity is
   **1.0**, because its candidate generation discards any shingle occurring in
   more than 300 training records, and one of the questions checked has 24 of
   its 94 shingles above that line. A detector that finds nothing is not
   evidence that nothing is there; reporting its zero as a clean bill of
   health would be a vacuous pass.
2. Both it and ``shingles`` run on ``text_fingerprint``, which strips digits
   and punctuation. Two math problems differing only in a **sign** fingerprint
   identically. Sign and magnitude are what distinguish one arithmetic problem
   from another, so that normalisation cannot answer this question. It also
   means the repository's detector reports a *fingerprint collision* as
   "direct leakage" when the texts differ — measured, for MATH-500.

The checks below therefore use their own token shingles and content-word
overlap, and the repository's ``find_direct_leakage`` is run alongside as a
cross-check on the exact finding, not as the source of truth.


Three kinds of correspondence, because two would overstate
----------------------------------------------------------
*exact* — normalized question text is identical to a training record's. The
item was in training. Contamination.

*near* — text differs but is the same question: ≥ ``NEAR_GRAM`` token 5-gram
Jaccard, or ≥ ``NEAR_WORD`` **IDF-weighted** content-word Jaccard. Two rules,
not one, because a single rule cannot be calibrated across question lengths.
ARC-Easy questions are short — one of them has eight 5-grams — so replacing a
single word costs ~0.2 similarity there and ~0.02 in a MATH problem. A 0.90
threshold alone scores "What force keeps the planets in orbit around the Sun?"
against "What keeps the planets in orbit around the Sun?" at 0.63 and calls it
clean, even though the training record carries that question's answer.

The word rule is *weighted* because an unweighted one was tried first and
measured wrong. MATH-500 questions embed LaTeX and Asymptote drawing code, so
an unweighted content-word Jaccard let two entirely different problems share
`size`, `defaultpen`, `draw`, `label`, `asy` and half an option list and score
0.91 — a false contamination report. Weighting each word by its inverse
frequency across the training corpus pushes boilerplate towards zero and lets
the tokens that actually distinguish one problem from another decide.

*structural sibling* — above ``SIBLING_FLOOR`` but below both near rules: the
same template with different parameters (``ELLIPSE`` against ``ALABAMA``), the
same stem asking a different question. Not contamination, and not called that.
But it is the reason a benchmark is *in-distribution* even when it is held
out, so it is counted and disclosed rather than discarded.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Mapping, Sequence

#: Corpora that could have contributed weights to the frozen adapter. Both are
#: checked; the second is the rejected ``mango-v0.2-L1`` stage, included
#: because "rejected" is a promotion decision, not a statement that the data
#: never existed.
TRAINING_CORPUS_GLOBS: Final = (
    "training/datasets/sciencemath-sft-v1/*.jsonl",
    "training/curriculum/mango-sft-v2/*/*.jsonl",
)

#: What the frozen corpora record about themselves. ``eval_only`` is the
#: repository's own hard gate (``sciencemath.datasets.licenses``) and is why
#: ARC is absent from every training corpus and why the released adapter is
#: non-commercial. These are claims; the measured columns are what the report
#: rests on.
DOCUMENTED_COMPOSITION: Final = {
    "gsm8k": {
        "in_training_corpus": True,
        "split_used": "train",
        "records": 842,
        "evidence":
            "training/datasets/sciencemath-sft-v1/source_manifest.json "
            "records openai/gsm8k#main [train]; domain_distribution.json "
            "counts 842.",
    },
    "math500": {
        "in_training_corpus": False,
        "split_used": None,
        "records": 0,
        "evidence":
            "No file in the repository references HuggingFaceH4/MATH-500. "
            "The MATH source used for training is EleutherAI/hendrycks_math "
            "[train], 809 records; MATH-500 is a test-set subset of MATH.",
    },
    "arc_easy": {
        "in_training_corpus": False,
        "split_used": None,
        "records": 0,
        "evidence":
            "data/manifests/datasets.json marks ai2-arc eval_only=true; "
            "source_manifest.json records it as excluded from SFT training "
            "for evaluation integrity. Zero ARC records in any corpus.",
    },
    "arc_challenge": {
        "in_training_corpus": False,
        "split_used": None,
        "records": 0,
        "evidence":
            "Same exclusion as arc_easy; both configurations come from the "
            "same allenai/ai2_arc source.",
    },
    "sciq": {
        "in_training_corpus": True,
        "split_used": "train",
        "records": 1200,
        "evidence":
            "source_manifest.json records allenai/sciq [train]; "
            "domain_distribution.json counts 1200. This is also why the "
            "released adapter is licensed CC BY-NC 4.0.",
    },
}

#: Token 5-gram Jaccard at or above which text is the same question. Matches
#: the repository's own near-leakage threshold so the numbers are comparable
#: with its earlier reports.
NEAR_GRAM: Final = 0.90
#: Content-word Jaccard at or above which two questions ask the same thing.
NEAR_WORD: Final = 0.80
#: The word rule applies only when BOTH questions are short. Set-similarity is
#: needed exactly where n-gram overlap is unreliable: a short question loses
#: ~0.2 of its 5-grams per replaced word, so the gram rule cannot see a
#: paraphrase. Long questions do not have that problem, and applying the word
#: rule to them produces false matches — MATH-500 questions embed LaTeX and
#: Asymptote drawing code, and two unrelated problems share enough of that
#: scaffolding to clear the threshold. The gate is what keeps the rule
#: serving its purpose instead of padding the count.
NEAR_WORD_MAX_TOKENS: Final = 16
NEAR_WORD_MIN_TOKENS: Final = 4
#: Above these but below the near rules: shared template, different question.
SIBLING_GRAM: Final = 0.45
SIBLING_WORD: Final = 0.60

NGRAM: Final = 5
#: How many of an item's *rarest* shingles nominate candidates. A pair at or
#: above the threshold shares nearly all of its shingles, so it shares the
#: rare ones, and no likely match can be excluded for being "too common" —
#: which is how a posting cutoff silently destroys a perfect match.
CANDIDATE_SHINGLES: Final = 32
CANDIDATE_CAP: Final = 4000

#: Content words for the word rule. Standard English function words only;
#: digits and mathematical operators are content, because in a maths corpus
#: they carry the meaning.
_STOPWORDS: Final = frozenset("""
a an the and or but if then than that this these those it its is are was were
be been being am do does did doing have has had having will shall would should
can could may might must of to in on at by for with from as such so not no nor
we you your they their he she his her him them i me my our us there here what
which who whom whose when where why how all any both each few more most other
some only own same too very s t just
""".split())

_TOKEN: Final = re.compile(r"[a-z0-9]+|[^\sa-z0-9]")
_WORD: Final = re.compile(r"[a-z0-9]+")
_WS: Final = re.compile(r"\s+")


class ContaminationError(RuntimeError):
    """A corpus could not be read, or a measurement would be vacuous."""


# ---------------------------------------------------------------------------
# text handling
# ---------------------------------------------------------------------------
def normalized_question(text: str) -> str:
    """Case- and whitespace-normalized text, nothing else removed.

    Deliberately conservative: every further character dropped is another way
    two different questions can be declared identical.
    """
    return _WS.sub(" ", text.casefold()).strip()


def token_shingles(text: str, n: int = NGRAM) -> frozenset[str]:
    """n-gram shingles over a token stream that keeps digits and operators.

    ``text_fingerprint``-based shingles erase ``+``, ``-`` and every digit, so
    ``z^4 + z^2 + 1 = 0`` and ``z^4 - z^2 + 1 = 0`` become the same string.
    Keeping those tokens is what lets this distinguish them.
    """
    tokens = _TOKEN.findall(text.casefold())
    if len(tokens) < n:
        return frozenset({" ".join(tokens)}) if tokens else frozenset()
    return frozenset(" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def content_words(text: str) -> frozenset[str]:
    """Words carrying meaning: no function words, digits and operators kept."""
    return frozenset(word for word in _WORD.findall(text.casefold())
                     if word not in _STOPWORDS)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    shared = len(left & right)
    if not shared:
        return 0.0
    return shared / (len(left) + len(right) - shared)


def weighted_jaccard(left: frozenset[str], right: frozenset[str],
                     weights: Mapping[str, float]) -> float:
    """Jaccard over words weighted by inverse document frequency.

    Plain Jaccard treats ``planets`` and ``asy`` as equally informative. In a
    corpus where a fifth of the questions embed drawing code, that makes the
    boilerplate decide the answer. Weighting by rarity means similarity is
    driven by the words that distinguish one question from another, which is
    the question being asked.
    """
    if not left or not right:
        return 0.0
    shared = left & right
    if not shared:
        return 0.0
    union = left | right
    denominator = sum(weights.get(word, 1.0) for word in union)
    if denominator <= 0.0:
        return 0.0
    return sum(weights.get(word, 1.0) for word in shared) / denominator


# ---------------------------------------------------------------------------
# data shapes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CorpusSummary:
    files: tuple[str, ...]
    records: int
    by_source: Mapping[str, int]
    duplicate_record_ids: int
    duplicate_questions: int

    def to_dict(self) -> dict:
        return {"files": list(self.files), "records": self.records,
                "by_source": dict(self.by_source),
                "duplicate_record_ids": self.duplicate_record_ids,
                "duplicate_questions": self.duplicate_questions}


@dataclass(frozen=True)
class Match:
    """One measured correspondence between an evaluation item and a training
    record. Kept in full so a reader can audit the classification rather than
    take it on trust."""

    item_id: str
    native_id: str | None
    benchmark: str
    kind: str                      # "exact" | "near" | "sibling"
    rule: str
    gram_similarity: float
    word_similarity: float
    train_id: str
    train_source: str
    train_answer_head: str
    train_question_head: str
    note: str = ""
    answer_carried: bool = False

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id, "native_id": self.native_id,
            "benchmark": self.benchmark, "kind": self.kind, "rule": self.rule,
            "gram_similarity": round(self.gram_similarity, 4),
            "weighted_word_similarity": round(self.word_similarity, 4),
            "train_id": self.train_id, "train_source": self.train_source,
            "train_answer_head": self.train_answer_head,
            "train_question_head": self.train_question_head,
            "answer_carried": self.answer_carried, "note": self.note,
        }


@dataclass(frozen=True)
class BenchmarkOverlap:
    benchmark: str
    items_checked: int
    matches: tuple[Match, ...] = ()
    items_compared: int = 0
    near_scan_enabled: bool = True
    max_gram_observed: float = 0.0
    max_word_observed: float = 0.0
    documented: Mapping[str, object] = field(default_factory=dict)

    def _item_ids(self, kind: str) -> tuple[str, ...]:
        return tuple(sorted({m.item_id for m in self.matches if m.kind == kind}))

    @property
    def exact_item_ids(self) -> tuple[str, ...]:
        return self._item_ids("exact")

    @property
    def near_item_ids(self) -> tuple[str, ...]:
        return self._item_ids("near")

    @property
    def sibling_item_ids(self) -> tuple[str, ...]:
        return self._item_ids("sibling")

    @property
    def answer_carried_item_ids(self) -> tuple[str, ...]:
        """Items whose near-duplicate training record carries the answer.

        The distinction that makes this table worth publishing. A training
        record that asks the same question *and* states the answer makes the
        item recallable — the score stops being evidence of reasoning. A record
        that asks the same question with different numbers does not: the model
        has seen the shape but must still solve it. Text similarity alone
        cannot tell those apart, and treating them the same either hides real
        leakage or invents it.
        """
        return tuple(sorted({m.item_id for m in self.matches
                             if m.kind == "near" and m.answer_carried}))

    @property
    def exposed_item_ids(self) -> tuple[str, ...]:
        """Items with a near-duplicate question but no answer in training."""
        return tuple(sorted(set(self.near_item_ids) -
                            set(self.answer_carried_item_ids)))

    @property
    def contaminated_item_ids(self) -> tuple[str, ...]:
        """Items that should not be read as generalization.

        Exact text overlap, or a near-duplicate whose answer is in training.
        """
        return tuple(sorted(set(self.exact_item_ids) |
                            set(self.answer_carried_item_ids)))

    @property
    def exact_overlap(self) -> int:
        return len(self.exact_item_ids)

    @property
    def near_overlap(self) -> int:
        return len(self.near_item_ids)

    @property
    def sibling_overlap(self) -> int:
        return len(self.sibling_item_ids)

    @property
    def contaminated_overlap(self) -> int:
        return len(self.contaminated_item_ids)

    @property
    def exposed_overlap(self) -> int:
        return len(self.exposed_item_ids)

    @property
    def max_gram_similarity(self) -> float:
        """Highest 5-gram similarity to ANY training record.

        Deliberately not "highest among recorded matches": a benchmark whose
        closest training neighbour is 0.21 below every reporting floor has no
        matches and must not report 0.00, which would read as "nothing in the
        corpus resembles it at all".
        """
        return self.max_gram_observed

    @property
    def max_word_similarity(self) -> float:
        return self.max_word_observed

    @property
    def held_out(self) -> bool:
        """True only when substantiated by a scan that actually ran.

        A near-duplicate question whose answer is *not* in training does not
        defeat this: the model has seen the shape but must still solve the
        problem, which is in-distribution rather than contaminated. A
        near-duplicate whose answer *is* in training does defeat it.
        """
        return (self.contaminated_overlap == 0
                and self.near_scan_enabled
                and not self.documented.get("in_training_corpus"))

    def to_dict(self) -> dict:
        return {
            "benchmark": self.benchmark,
            "items_checked": self.items_checked,
            "items_compared": self.items_compared,
            "near_scan_enabled": self.near_scan_enabled,
            "exact_overlap": self.exact_overlap,
            "near_overlap": self.near_overlap,
            "answer_carried_overlap": len(self.answer_carried_item_ids),
            "contaminated_overlap": self.contaminated_overlap,
            "exposed_overlap": self.exposed_overlap,
            "sibling_overlap": self.sibling_overlap,
            "max_gram_similarity": round(self.max_gram_similarity, 4),
            "max_word_similarity": round(self.max_word_similarity, 4),
            "held_out": self.held_out,
            "documented": dict(self.documented),
            "matches": [m.to_dict() for m in self.matches],
        }


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------
def load_corpus(root: Path) -> tuple[list[dict], CorpusSummary]:
    """Read every training record that could have shaped the frozen adapter."""
    records: list[dict] = []
    files: list[str] = []
    by_source: dict[str, int] = {}

    for pattern in TRAINING_CORPUS_GLOBS:
        for path in sorted(root.glob(pattern)):
            files.append(path.relative_to(root).as_posix())
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ContaminationError(
                        f"{path}: unreadable record: {exc}") from exc
                records.append(record)
                source = str(record.get("source") or "unknown")
                by_source[source] = by_source.get(source, 0) + 1

    if not records:
        raise ContaminationError(
            "no training records found — a contamination report over zero "
            "records would be vacuously clean, which is not evidence")

    # Duplicates are counted, not silently collapsed. A corpus that lists the
    # same record three times makes its own record counts misleading, and a
    # reader comparing "842 GSM8K records" against a measurement needs to know
    # whether that number is distinct items.
    ids = [str(record.get("id") or "") for record in records]
    questions = [normalized_question(str(record.get("question") or ""))
                 for record in records]
    summary = CorpusSummary(
        files=tuple(files), records=len(records),
        by_source=dict(sorted(by_source.items())),
        duplicate_record_ids=len(ids) - len(set(ids)),
        duplicate_questions=len(questions) - len(set(questions)))
    return records, summary


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------
class _TrainIndex:
    """Index over training questions for exact, near and sibling matching."""

    def __init__(self, records: Sequence[dict]) -> None:
        self.records = records
        self.by_normalized: dict[str, list[int]] = defaultdict(list)
        self.shingles: list[frozenset[str]] = []
        self.words: list[frozenset[str]] = []
        self.inverted: dict[str, list[int]] = defaultdict(list)
        self.inverted_words: dict[str, list[int]] = defaultdict(list)

        for position, record in enumerate(records):
            question = str(record.get("question") or "")
            self.by_normalized[normalized_question(question)].append(position)
            shingle_set = token_shingles(question)
            word_set = content_words(question)
            self.shingles.append(shingle_set)
            self.words.append(word_set)
            for shingle in shingle_set:
                self.inverted[shingle].append(position)
            for word in word_set:
                self.inverted_words[word].append(position)

        # Smoothed inverse document frequency over the *training* corpus, which
        # is the reference population for "how informative is this word".
        total = max(len(records), 1)
        self.word_weights: dict[str, float] = {
            word: math.log((total + 1.0) / (len(postings) + 1.0)) + 1.0
            for word, postings in self.inverted_words.items()
        }

    def exact(self, question: str) -> list[int]:
        return self.by_normalized.get(normalized_question(question), [])

    def nearest(self, shingle_set: frozenset[str]) -> set[int]:
        """Every record sharing at least one shingle.

        Complete by construction — similarity is zero without a shared
        shingle — which is what a reported maximum needs to rest on. The rarer
        nomination below is faster but a lower bound.
        """
        candidates: set[int] = set()
        for shingle in shingle_set:
            postings = self.inverted.get(shingle)
            if postings:
                candidates.update(postings)
        return candidates

    def word_candidates(self, word_set: frozenset[str]) -> set[int]:
        """Records sharing at least one content word, nominated by the rarest.

        Needed because a question can be reworded heavily enough to share no
        5-gram while sharing every content word — which is exactly the shape
        of a paraphrase, and of the ARC/synthetic case that motivated this.
        """
        if not word_set:
            return set()
        ranked = sorted(word_set,
                        key=lambda word: len(self.inverted_words.get(word, ())))
        candidates: set[int] = set()
        for word in ranked[:CANDIDATE_SHINGLES]:
            postings = self.inverted_words.get(word)
            if postings:
                candidates.update(postings)
            if len(candidates) > CANDIDATE_CAP:
                break
        return candidates


def _head(text: str, limit: int = 200) -> str:
    text = _WS.sub(" ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _word_rule_applies(left_words: int, right_words: int) -> bool:
    """Whether the content-word rule is informative for this pair.

    Both bounds matter. Below ``NEAR_WORD_MIN_TOKENS`` the ratio is decided by
    one or two words; above ``NEAR_WORD_MAX_TOKENS`` the gram rule is already
    reliable and the word rule starts matching shared scaffolding instead of
    shared meaning.
    """
    smallest, largest = sorted((left_words, right_words))
    return smallest >= NEAR_WORD_MIN_TOKENS and largest <= NEAR_WORD_MAX_TOKENS


def _classify(gram: float, word: float,
              applies: bool) -> tuple[str, str] | None:
    """Which rule fired, if any. Most specific rule first.

    ``None`` when no rule fires. An ``("", "")`` sentinel would instead be a
    pair of strings that reads like a classification whose name went missing,
    and it makes the one distinction that matters here — did the word rule
    fire, or did its length gate simply shut? — a test of falsiness.
    """
    if gram >= NEAR_GRAM:
        return "near", "gram>=0.90"
    if applies and word >= NEAR_WORD:
        return "near", "word>=0.80"
    if gram >= SIBLING_GRAM or (applies and word >= SIBLING_WORD):
        return "sibling", "shared template"
    return None


def measure_overlap(records: Sequence[dict],
                    items_by_benchmark: Mapping[str, Sequence],
                    *, near_scan: bool = True) -> dict[str, BenchmarkOverlap]:
    """Measure item-level overlap between the corpora and each benchmark.

    Both checks run over the *whole* benchmark — nothing is sampled — and the
    number of items that actually received a comparison is reported, so a
    benchmark whose scan compared nothing cannot be read as clean.

    The corpus contains exact duplicate records (a quarter of it, measured), so
    correspondence is reported per *training record id*: one duplicated record
    is one piece of evidence, not three.
    """
    index = _TrainIndex(records)
    report: dict[str, BenchmarkOverlap] = {}

    for name, items in items_by_benchmark.items():
        matches: dict[tuple[str, str], Match] = {}
        compared = 0
        max_gram = 0.0
        max_word = 0.0

        def record_match(candidate: Match) -> None:
            """Keep the strongest evidence per (item, training record)."""
            key = (candidate.item_id, candidate.train_id)
            existing = matches.get(key)
            if existing is None or (
                    candidate.gram_similarity + candidate.word_similarity
                    > existing.gram_similarity + existing.word_similarity):
                matches[key] = candidate

        for item in items:
            question = str(item.question)
            shingle_set = token_shingles(question)
            word_set = content_words(question)

            exact_positions = set()
            for position in index.exact(question):
                exact_positions.add(position)
                record = records[position]
                # The answer agreement is recorded here too, not only for
                # near-duplicates. An exact question match is contaminated
                # either way — the question itself was seen — but "the record
                # also states the answer" and "the same words carry a
                # different answer" are different findings, and a reader
                # auditing the table is entitled to tell them apart.
                agrees = _answers_agree(item, record)
                record_match(Match(
                    item_id=item.item_id, native_id=item.native_id,
                    benchmark=name, kind="exact", rule="identical text",
                    gram_similarity=1.0, word_similarity=1.0,
                    train_id=str(record.get("id", "?")),
                    train_source=str(record.get("source", "?")),
                    train_answer_head=_head(record.get("answer"), 80),
                    train_question_head=_head(record.get("question")),
                    note=("identical question text, and the training record "
                          "states this item's answer"
                          if agrees else
                          "identical question text; the training record's "
                          "answer differs from this item's gold answer, so "
                          "the wording collides rather than the solution"),
                    answer_carried=agrees))

            if not near_scan:
                continue

            candidates = index.nearest(shingle_set) | \
                index.word_candidates(word_set)
            for position in candidates:
                if position in exact_positions:
                    continue
                gram = jaccard(shingle_set, index.shingles[position])
                word = weighted_jaccard(word_set, index.words[position],
                                        index.word_weights)
                max_gram = max(max_gram, gram)
                max_word = max(max_word, word)
                applies = _word_rule_applies(len(word_set),
                                             len(index.words[position]))
                classification = _classify(gram, word, applies)
                if classification is None:
                    continue
                kind, rule = classification
                record = records[position]
                agrees = _answers_agree(item, record)
                if kind == "near" and agrees:
                    note = ("the training record carries this question's "
                            "answer: the item is recallable, so it is "
                            "contaminated rather than merely familiar")
                elif kind == "near":
                    note = ("same question by text similarity, but the "
                            "training record does not carry this item's "
                            "answer: template familiarity, listed for audit")
                else:
                    note = ("shared template only: different question, and "
                            "the training record does not carry this item's "
                            "answer")
                record_match(Match(
                    item_id=item.item_id, native_id=item.native_id,
                    benchmark=name, kind=kind, rule=rule,
                    gram_similarity=gram, word_similarity=word,
                    train_id=str(record.get("id", "?")),
                    train_source=str(record.get("source", "?")),
                    train_answer_head=_head(record.get("answer"), 80),
                    train_question_head=_head(record.get("question")),
                    note=note, answer_carried=agrees))
            compared += 1

        report[name] = BenchmarkOverlap(
            benchmark=name, items_checked=len(items),
            matches=tuple(sorted(matches.values(),
                                 key=lambda m: (-m.gram_similarity,
                                                -m.word_similarity,
                                                m.item_id))),
            items_compared=compared, near_scan_enabled=near_scan,
            max_gram_observed=max_gram, max_word_observed=max_word,
            documented=DOCUMENTED_COMPOSITION[name])
    return report


def _option_text(item, label: str) -> str:
    for option_label, text in item.choices:
        if option_label == label:
            return text
    return ""


#: Leading articles, dropped before comparing two short answers, so that
#: "an atom" and "atom" are the same answer. Without this the rule misses the
#: ARC case it was written for.
_LEADING_ARTICLE: Final = re.compile(r"^(?:a|an|the)\s+")


def normalize_answer(text: str) -> str:
    """Canonical form of a short answer for equality testing."""
    cleaned = _WS.sub(" ", str(text or "").casefold()).strip()
    cleaned = cleaned.strip(" .,;:!?*\"'`()[]")
    cleaned = _LEADING_ARTICLE.sub("", cleaned)
    return _WS.sub(" ", cleaned).strip()


def _answers_agree(item, record: dict) -> bool:
    """Whether a training record carries the evaluation item's answer.

    Turns "the model saw a similar question" into "the model saw this
    question's answer" — the difference between in-distribution and
    memorisable, and the distinction the disclosure table turns on.

    Deliberately one-directional and conservative: it asks whether the
    training record's short answer field equals the item's gold answer (or the
    text of its gold option). A worked solution in that field will not match,
    so a MATH item whose training record holds a full derivation is *not*
    called contaminated here even when the final answer coincides. Being
    unable to prove recall is not proof of its absence, and the affected items
    are listed in full so a reader can judge them.
    """
    train_answer = normalize_answer(record.get("answer"))
    if not train_answer:
        return False
    candidates = {normalize_answer(item.gold)}
    if item.gold_label:
        candidates.add(normalize_answer(_option_text(item, item.gold_label)))
    return train_answer in {c for c in candidates if c}


def cross_check_exact(records: Sequence[dict],
                      items_by_benchmark: Mapping[str, Sequence]
                      ) -> dict[str, dict]:
    """Compare this module's exact finding with the repository's detector.

    Reported because the two can disagree, and a reader should see which of
    them would have found what: the repository's detector calls a
    fingerprint collision "direct leakage" even when the texts differ.
    """
    from sciencemath.datasets.leakage import find_direct_leakage

    eval_sets = {name: [{"id": item.item_id, "question": item.question,
                         "source": name} for item in items]
                 for name, items in items_by_benchmark.items()}
    repository = find_direct_leakage(list(records), eval_sets)
    repo_ids: dict[str, set[str]] = defaultdict(set)
    for pair in repository.pairs:
        repo_ids[pair.eval_split].add(pair.eval_id)

    measured = measure_overlap(records, items_by_benchmark, near_scan=False)
    result: dict[str, dict] = {}
    for name in items_by_benchmark:
        ours = set(measured[name].exact_item_ids)
        theirs = repo_ids[name]
        result[name] = {
            "this_module": sorted(ours),
            "repository_detector": sorted(theirs),
            "agree": ours == theirs,
            "only_this_module": sorted(ours - theirs),
            "only_repository": sorted(theirs - ours),
            "note": ("the repository detector reports fingerprint equality; "
                     "this module requires identical normalized text"
                     if theirs - ours else ""),
        }
    return result


def overlap_answer_agreement(records: Sequence[dict],
                            items_by_benchmark: Mapping[str, Sequence],
                            overlaps: Mapping[str, BenchmarkOverlap]
                            ) -> list[dict]:
    """For exact overlaps, does the training record carry the same answer?

    Sharper than overlap alone: a question in training *with its gold answer*
    is memorisable in a way that the same question without one is not.
    Recorded as "not comparable" when the shapes do not permit a comparison —
    an unstated "unknown" here would be read as "no".
    """
    by_id = {str(record.get("id", "?")): record for record in records}
    rows: list[dict] = []
    for name in items_by_benchmark:
        for match in overlaps[name].exact_item_ids:
            pair = next(m for m in overlaps[name].matches
                        if m.item_id == match and m.kind == "exact")
            record = by_id.get(pair.train_id, {})
            item = next(i for i in items_by_benchmark[name]
                        if i.item_id == match)
            train_answer = str(record.get("answer") or "").strip()
            gold = str(item.gold or "").strip()
            if not train_answer or not gold:
                verdict = "not comparable"
            elif gold.casefold() == train_answer.casefold():
                verdict = "training answer matches the gold answer"
            elif item.gold_label and train_answer.casefold() == \
                    _option_text(item, item.gold_label).casefold():
                verdict = "training answer matches the gold option text"
            else:
                verdict = ("training answer differs from the gold answer — "
                           "same question, different key")
            rows.append({
                "benchmark": name, "item_id": match,
                "native_id": item.native_id, "train_id": pair.train_id,
                "gold": gold[:60], "train_answer": train_answer[:60],
                "agreement": verdict,
            })
    return rows


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def _share(count: int, total: int) -> str:
    if not total:
        return f"{count} items"
    return f"{count} of {total} items ({100.0 * count / total:.2f}%)"


def interpretation(overlap: BenchmarkOverlap) -> str:
    """The sentence for the disclosure table's third column.

    Written for someone deciding how much weight to put on the number, so it
    states the measured proportion and what it means for reading the score.
    Deliberately proportionate: one matched item in a thousand is a fact about
    one item, and calling a whole benchmark contaminated would mislead as much
    as hiding it.
    """
    total = overlap.items_checked
    exact = overlap.exact_overlap
    carried = len(overlap.answer_carried_item_ids)
    exposed = overlap.exposed_overlap
    siblings = overlap.sibling_overlap
    trained = bool(overlap.documented.get("in_training_corpus"))
    parts: list[str] = []

    if exact:
        parts.append(
            f"{_share(exact, total)} have an IDENTICAL question in the "
            f"training corpus, which also states the answer. These items are "
            f"contaminated: their scores are not evidence of generalization.")
    if carried:
        parts.append(
            f"{_share(carried, total)} more have a NEAR-DUPLICATE question "
            f"whose ANSWER the training corpus states. The question can be "
            f"answered from memory, so these are contaminated too.")
    if exact or carried:
        contaminated = overlap.contaminated_overlap
        parts.append(
            f"Contaminated in total: {_share(contaminated, total)}. The "
            f"remaining {total - contaminated} items are not known to be "
            f"contaminated, but see the sibling count below before treating "
            f"this as an unseen benchmark.")
    elif not overlap.near_scan_enabled:
        return ("NO MEASUREMENT: the duplicate scan did not run for this "
                "benchmark, so absence of overlap is not evidence of absence.")
    else:
        parts.append(
            f"All {total} items were compared against every training record: "
            f"no identical question and no near-duplicate carrying the answer "
            f"(max 5-gram similarity {overlap.max_gram_similarity:.2f}).")
        if trained:
            parts.append(
                f"Trained on this source's "
                f"{overlap.documented['split_used']} split and evaluated on "
                f"its test split: disjoint by construction and confirmed by "
                f"measurement, but still IN-DISTRIBUTION — the model has seen "
                f"this task and format extensively, so a score here measures "
                f"performance on this kind of question, not generalization "
                f"to it.")
        else:
            parts.append(
                "No records from this source appear in any training corpus, "
                "so this is held out.")
    if exposed:
        parts.append(
            f"Listed for audit rather than counted as contamination: "
            f"{_share(exposed, total)} have a near-duplicate question but the "
            f"training record does not state the answer.")
    if siblings:
        parts.append(
            f"Separately, {_share(siblings, total)} share a problem TEMPLATE "
            f"with a training record while asking a different question. That "
            f"is not contamination, but it does mean the benchmark's surface "
            f"form is familiar.")
    return " ".join(parts)


def _require_all_benchmarks(overlaps: Mapping[str, BenchmarkOverlap]) -> None:
    """Every benchmark must appear, or the disclosure is incomplete.

    A table that silently omits a benchmark reads as "this benchmark is clean"
    when it means "nobody measured it". The brief requires the disclosure to
    cover GSM8K, MATH, ARC and SciQ; a partial mapping is refused by name
    rather than indexed into.
    """
    from sciencemath.comparability.contract import BENCHMARK_ORDER

    missing = [name for name in BENCHMARK_ORDER if name not in overlaps]
    if missing:
        raise ContaminationError(
            f"the disclosure must cover every benchmark; missing {missing}. "
            f"An omitted benchmark is indistinguishable from a clean one.")


def disclosure_table(overlaps: Mapping[str, BenchmarkOverlap]) -> list[dict]:
    """The brief's required table, as data."""
    from sciencemath.comparability.contract import BENCHMARK_ORDER

    _require_all_benchmarks(overlaps)
    rows = []
    for name in BENCHMARK_ORDER:
        overlap = overlaps[name]
        if overlap.documented["in_training_corpus"]:
            known = (f"yes ({overlap.documented['records']} records from the "
                     f"{overlap.documented['split_used']} split)")
        else:
            known = "no (excluded from training as a source)"
        if overlap.contaminated_overlap:
            known += (f"; {overlap.contaminated_overlap} of "
                      f"{overlap.items_checked} evaluated items nevertheless "
                      f"overlap measured ({overlap.exact_overlap} identical, "
                      f"{len(overlap.answer_carried_item_ids)} near-duplicate "
                      f"carrying the answer)")
        rows.append({
            "benchmark": name,
            "known_training_overlap": known,
            "items_checked": overlap.items_checked,
            "items_compared": overlap.items_compared,
            "measured_exact_overlap": overlap.exact_overlap,
            "measured_near_overlap": overlap.near_overlap,
            "measured_answer_carried_overlap":
                len(overlap.answer_carried_item_ids),
            "measured_contaminated_overlap": overlap.contaminated_overlap,
            "measured_exposed_overlap": overlap.exposed_overlap,
            "measured_sibling_overlap": overlap.sibling_overlap,
            "max_gram_similarity": round(overlap.max_gram_similarity, 4),
            "max_word_similarity": round(overlap.max_word_similarity, 4),
            "held_out": overlap.held_out,
            "evidence": overlap.documented["evidence"],
            "evaluation_interpretation": interpretation(overlap),
        })
    return rows


def summarize(overlaps: Mapping[str, BenchmarkOverlap],
              corpus: CorpusSummary | None = None) -> dict:
    """Machine-readable summary, including the vacuity guards."""
    _require_all_benchmarks(overlaps)
    summary = {
        "definitions": {
            "exact": "normalized question text identical to a training record",
            "near": (f"token 5-gram Jaccard >= {NEAR_GRAM}, OR "
                     f"IDF-weighted content-word Jaccard >= {NEAR_WORD} when "
                     f"both questions have between {NEAR_WORD_MIN_TOKENS} and "
                     f"{NEAR_WORD_MAX_TOKENS} content words"),
            "contaminated": ("an item is contaminated when its question is "
                             "identical to a training record's, or is a "
                             "near-duplicate AND the training record states "
                             "this item's answer"),
            "sibling": (f"above {SIBLING_GRAM} 5-gram or {SIBLING_WORD} "
                        f"weighted content-word similarity but below both "
                        f"near rules"),
            "shingle_basis": ("token 5-grams preserving digits and "
                              "mathematical operators, and content words "
                              "weighted by inverse document frequency; not "
                              "text_fingerprint, which erases digits and "
                              "operators"),
            "matched_per": ("one entry per (evaluation item, training record "
                            "id); the corpus contains exact duplicate records "
                            "and they are not counted repeatedly"),
        },
        "benchmarks": {name: overlap.to_dict()
                       for name, overlap in overlaps.items()},
        "held_out": sorted(name for name, overlap in overlaps.items()
                           if overlap.held_out),
        "exact_overlap": sorted(name for name, overlap in overlaps.items()
                                if overlap.exact_overlap),
        "near_overlap": sorted(name for name, overlap in overlaps.items()
                               if overlap.near_overlap),
        "contaminated": sorted(name for name, overlap in overlaps.items()
                               if overlap.contaminated_overlap),
        "vacuous_scans": sorted(name for name, overlap in overlaps.items()
                                if overlap.near_scan_enabled
                                and overlap.items_compared == 0),
    }
    if corpus is not None:
        summary["corpus"] = corpus.to_dict()
    return summary
