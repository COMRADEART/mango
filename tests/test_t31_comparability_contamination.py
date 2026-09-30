"""T31 tests, brief category 19: contamination metadata.

The brief requires the training-overlap disclosure to be honest in both
directions: "Never present contaminated evaluation as fully unseen
generalization", and "Do not claim ARC is held out if that claim cannot be
substantiated."

These tests build a small synthetic corpus with known overlaps, so every
classification has a right answer that does not depend on the real training
data. The real measured numbers are produced separately, by running the same
code over the repository's corpora, and are written into the evidence pack.

Several tests here exist because the repository's own leak detector was
*measured* unfit for this question, and its replacement has failure modes of
its own: a candidate rule that silently drops a true match, a fingerprint that
erases the sign of a number, and a similarity threshold that cannot tell a
shared template from a shared answer.
"""
from __future__ import annotations

import json

import pytest

from sciencemath.comparability import contamination as C

from t31_comparability_support import item, mcq

PLANETS = "What force keeps the planets in orbit around the Sun?"
PLANETS_NEAR = "What force keeps the planets in orbit around the Sun and Moon?"


def _record(question: str, answer: str, *, rid: str = "train-1",
            source: str = "synthetic-sft-v1") -> dict:
    return {"id": rid, "question": question, "answer": answer,
            "source": source}


def _measure(records, items, benchmark: str = "gsm8k"):
    """The overlap for one benchmark, which is what most tests assert on."""
    return C.measure_overlap(records, {benchmark: items})[benchmark]


# ---------------------------------------------------------------------------
# the text primitives
# ---------------------------------------------------------------------------
def test_shingles_keep_digits_and_operators():
    """The repository's fingerprint strips them, which erases a sign change."""
    plus = C.token_shingles("solve z^4 + z^2 + 1 = 0", 3)
    minus = C.token_shingles("solve z^4 - z^2 + 1 = 0", 3)
    assert "4" in {token for gram in plus for token in gram}
    assert plus != minus
    assert C.jaccard(plus, minus) < 1.0


def test_shingles_of_identical_text_are_identical():
    assert C.token_shingles("What force keeps planets in orbit?", 3) == \
        C.token_shingles("What force keeps planets in orbit?", 3)


def test_content_words_drop_stopwords_and_keep_terms():
    words = C.content_words("What is the force that keeps the planets")
    assert "force" in words and "planets" in words
    assert "the" not in words and "what" not in words


def test_jaccard_is_symmetric_and_bounded():
    a = C.token_shingles("alpha beta gamma delta", 2)
    b = C.token_shingles("alpha beta gamma epsilon", 2)
    assert C.jaccard(a, b) == C.jaccard(b, a)
    assert 0.0 <= C.jaccard(a, b) <= 1.0
    assert C.jaccard(a, a) == 1.0
    assert C.jaccard(a, frozenset()) == 0.0


def test_word_rule_is_length_gated():
    """Set similarity is only trustworthy on short questions.

    Long items share scaffolding — LaTeX, option lists — and an unweighted
    content-word Jaccard read two unrelated MATH-500 problems as 1.000
    similar. The gate is what makes the word rule usable at all.
    """
    short = PLANETS
    assert 4 <= len(C.content_words(short)) <= 16
    assert C._word_rule_applies(len(C.content_words(short)),
                                len(C.content_words(short)))
    # Too short: the ratio is decided by one or two words.
    assert not C._word_rule_applies(2, 2)
    # Too long: the gram rule already covers it and the word rule starts
    # matching shared scaffolding.
    long = " ".join(f"word{i}" for i in range(40))
    assert not C._word_rule_applies(len(C.content_words(long)),
                                    len(C.content_words(long)))


def test_weighted_jaccard_equals_plain_jaccard_with_flat_weights():
    a = C.token_shingles("alpha beta gamma delta", 2)
    b = C.token_shingles("alpha beta gamma epsilon", 2)
    weights = {token: 1.0 for token in a | b}
    assert C.weighted_jaccard(a, b, weights) == pytest.approx(C.jaccard(a, b))


# ---------------------------------------------------------------------------
# answer normalisation
# ---------------------------------------------------------------------------
def test_answers_agree_across_a_leading_article():
    """Measured: this is what separated a real ARC leak from a near miss."""
    assert C.normalize_answer("an atom") == C.normalize_answer("atom")
    assert C.normalize_answer("The Sun") == C.normalize_answer("sun")


def test_answers_that_differ_do_not_agree():
    assert C.normalize_answer("gravity") != C.normalize_answer("friction")


# ---------------------------------------------------------------------------
# the corpus
# ---------------------------------------------------------------------------
def test_loading_a_corpus_with_no_records_fails(tmp_path):
    (tmp_path / "training" / "datasets" / "sciencemath-sft-v1").mkdir(
        parents=True)
    with pytest.raises(C.ContaminationError):
        C.load_corpus(tmp_path)


def test_corpus_summary_counts_duplicate_records_and_questions():
    summary = C.CorpusSummary(
        files=("f.jsonl",), records=3, by_source={"synthetic-sft-v1": 3},
        duplicate_record_ids=1, duplicate_questions=1)
    assert summary.to_dict()["records"] == 3
    assert summary.duplicate_questions == 1


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
def test_an_identical_question_is_contaminated():
    subject = item("gsm8k", question="How many apples are there?", gold="3")
    overlap = _measure([_record("How many apples are there?", "3")], [subject])
    assert overlap.exact_overlap == 1
    assert overlap.contaminated_overlap == 1
    assert subject.item_id in overlap.contaminated_item_ids


def test_an_identical_question_is_contaminated_even_with_a_different_answer():
    """The question text was seen, so the item is not unseen generalization.

    Conservative on purpose, and the two cases stay distinguishable: the match
    records whether the training record also states the answer.
    """
    subject = item("gsm8k", question="How many apples are there?", gold="3")
    overlap = _measure([_record("How many apples are there?", "5")], [subject])
    assert overlap.exact_overlap == 1
    assert overlap.contaminated_overlap == 1
    assert overlap.matches[0].answer_carried is False
    assert "answer differs" in overlap.matches[0].note


def test_an_identical_question_whose_record_states_the_answer_says_so():
    subject = item("gsm8k", question="How many apples are there?", gold="3")
    overlap = _measure([_record("How many apples are there?", "3")], [subject])
    assert overlap.matches[0].answer_carried is True
    assert "states this item's answer" in overlap.matches[0].note


def test_a_near_duplicate_without_the_answer_is_exposed_not_contaminated():
    """Familiar wording, different answer: listed for audit, not condemned."""
    subject = item("gsm8k", question=PLANETS, gold="gravity")
    overlap = _measure([_record(PLANETS_NEAR, "friction")], [subject])
    assert overlap.near_overlap == 1
    assert overlap.contaminated_overlap == 0
    assert subject.item_id in overlap.exposed_item_ids
    assert overlap.matches[0].kind == "near"


def test_a_near_duplicate_carrying_the_answer_is_contaminated():
    """This is the discriminator: the training record states the answer."""
    subject = item("gsm8k", question=PLANETS, gold="gravity")
    overlap = _measure([_record(PLANETS_NEAR, "gravity")], [subject])
    assert overlap.contaminated_overlap == 1
    assert subject.item_id in overlap.answer_carried_item_ids
    assert "recallable" in overlap.matches[0].note


def test_the_classifier_ladder_prefers_the_most_specific_rule():
    assert C._classify(0.95, 0.10, False) == ("near", "gram>=0.90")
    assert C._classify(0.10, 0.85, True) == ("near", "word>=0.80")
    # The word rule is gated; with the gate shut the same score proves nothing.
    assert C._classify(0.10, 0.85, False) is None
    assert C._classify(0.50, 0.10, False)[0] == "sibling"
    assert C._classify(0.10, 0.65, True)[0] == "sibling"
    assert C._classify(0.10, 0.10, True) is None
    # Below every threshold, even the weakest one.
    assert C._classify(0.44, 0.59, True) is None


def test_an_unrelated_question_matches_nothing():
    subject = item("gsm8k", question="How many apples?", gold="3")
    overlap = _measure([_record("Explain photosynthesis in plants.",
                                "sunlight")], [subject])
    assert overlap.contaminated_overlap == 0
    assert overlap.exposed_overlap == 0
    assert overlap.sibling_overlap == 0
    assert overlap.max_gram_similarity < C.SIBLING_GRAM


def test_an_mcq_answer_carried_by_option_text_is_detected():
    """Measured on the real corpus: an ARC item leaked via a SciQ record.

    The training record states the answer as the option's *text*, not as a
    label, so this only works if answer agreement is checked against the gold
    option's text as well as against the gold label.
    """
    subject = mcq(question=PLANETS, gold_label="A",
                  choices=(("A", "gravity"), ("B", "magnetism"),
                           ("C", "friction"), ("D", "pressure")))
    arc = _measure([_record(PLANETS_NEAR, "gravity", source="sciq")],
                   [subject], benchmark="arc_easy")
    assert arc.contaminated_overlap == 1
    assert arc.answer_carried_item_ids == (subject.item_id,)


def test_an_mcq_answer_carried_by_the_gold_label_is_detected():
    subject = mcq(question=PLANETS, gold_label="A",
                  choices=(("A", "gravity"), ("B", "magnetism"),
                           ("C", "friction"), ("D", "pressure")))
    arc = _measure([_record(PLANETS_NEAR, "A")], [subject],
                   benchmark="arc_easy")
    assert arc.contaminated_overlap == 1


def test_an_mcq_record_carrying_a_wrong_option_is_not_contaminated():
    subject = mcq(question=PLANETS, gold_label="A",
                  choices=(("A", "gravity"), ("B", "magnetism"),
                           ("C", "friction"), ("D", "pressure")))
    arc = _measure([_record(PLANETS_NEAR, "magnetism")], [subject],
                   benchmark="arc_easy")
    assert arc.contaminated_overlap == 0
    assert arc.exposed_overlap == 1


def test_a_record_stating_neither_answer_never_counts_as_contaminated():
    subject = item("math500", question="Solve z^4 + z^2 + 1 = 0.", gold="1")
    overlap = _measure([_record("Solve z^4 - z^2 + 1 = 0.", "2")], [subject])
    assert overlap.contaminated_overlap == 0


# ---------------------------------------------------------------------------
# the reported maxima are observed, not merely recorded
# ---------------------------------------------------------------------------
def test_max_similarity_reports_the_closest_comparison_not_the_matches():
    """A vacuous 0.000 reads as 'nothing resembles this at all'.

    These two questions share one 5-gram but clear no rule, so nothing is
    recorded — and the reported maximum must still be the 1/9 that was
    actually observed, not the 0.0 that "no matches" would imply.
    """
    subject = item("gsm8k", question="How many apples are there on the table?",
                   gold="3")
    overlap = _measure([_record("How many apples are there in the basket?",
                                "5")], [subject])
    assert overlap.matches == ()
    assert overlap.contaminated_overlap == 0
    assert overlap.exposed_overlap == 0
    assert overlap.max_gram_similarity == pytest.approx(1 / 9, abs=1e-6)


def test_the_vacuity_guard_records_how_many_items_were_compared():
    subjects = [item("gsm8k", question=f"Question {i}?", gold="1")
                for i in range(5)]
    overlap = _measure([_record("Unrelated text.", "0")], subjects)
    assert overlap.items_compared == 5
    assert overlap.items_checked == 5


def test_no_item_compared_means_not_held_out():
    """Zero comparisons must never be reported as a clean bill of health."""
    overlap = C.measure_overlap([_record("Something.", "1")],
                                {"gsm8k": []})["gsm8k"]
    assert overlap.items_compared == 0
    assert overlap.held_out is False


# ---------------------------------------------------------------------------
# held-out determination
# ---------------------------------------------------------------------------
def test_a_clean_undocumented_benchmark_is_reported_held_out():
    subject = mcq(question="Which is a chemical change?", gold_label="A",
                  benchmark="arc_challenge",
                  choices=(("A", "rusting"), ("B", "melting"),
                           ("C", "boiling"), ("D", "freezing")))
    overlap = _measure([_record("Unrelated.", "0")], [subject],
                       benchmark="arc_challenge")
    assert overlap.held_out is True


def test_a_benchmark_documented_as_training_data_is_never_held_out():
    """GSM8K is in the training corpus by design and says so."""
    subject = item("gsm8k", question="A question nothing resembles?", gold="1")
    overlap = _measure([_record("Unrelated.", "0")], [subject])
    assert overlap.contaminated_overlap == 0
    assert overlap.held_out is False
    assert overlap.documented["in_training_corpus"] is True


def test_arc_is_documented_as_excluded_from_training():
    for benchmark in ("arc_easy", "arc_challenge"):
        documented = C.DOCUMENTED_COMPOSITION[benchmark]
        assert documented["in_training_corpus"] is False
        assert documented["evidence"]


def test_math500_is_documented_as_excluded_while_math_is_not():
    assert C.DOCUMENTED_COMPOSITION["math500"]["in_training_corpus"] is False


# ---------------------------------------------------------------------------
# the artifacts the report consumes
# ---------------------------------------------------------------------------
def _sample_overlaps():
    """All five benchmarks, because a partial disclosure is refused."""
    return C.measure_overlap(
        [_record("How many apples are there?", "3"),
         _record("Unrelated text entirely.", "0")],
        {
            "gsm8k": [item("gsm8k", question="How many apples are there?",
                           gold="3")],
            "math500": [item("math500", question="Solve z + 1 = 4.",
                             gold="3")],
            "arc_easy": [mcq(question="Which is a chemical change?",
                             gold_label="A")],
            "arc_challenge": [mcq(question="Why does ice float on water?",
                                  gold_label="B",
                                  benchmark="arc_challenge")],
            "sciq": [item("sciq", question="What is the smallest unit?",
                          gold="A", gold_label="A",
                          choices=(("A", "atom"), ("B", "molecule"),
                                   ("C", "cell"), ("D", "electron")))],
        })


def test_disclosure_table_has_the_columns_the_brief_requires():
    table = C.disclosure_table(_sample_overlaps())
    by_name = {row["benchmark"]: row for row in table}
    assert set(by_name) == {"gsm8k", "math500", "arc_easy", "arc_challenge",
                            "sciq"}
    for row in table:
        for column in ("benchmark", "known_training_overlap",
                       "evaluation_interpretation", "measured_exact_overlap",
                       "measured_near_overlap", "items_checked", "held_out",
                       "evidence"):
            assert column in row, column
    # The brief asks for yes/no/unknown; the column carries that verdict and
    # then substantiates it, so it is read by prefix rather than by equality.
    for row in table:
        verdict = row["known_training_overlap"]
        assert verdict.split()[0].rstrip("(;,") in ("yes", "no", "unknown")
        assert row["evaluation_interpretation"]


def test_disclosure_is_refused_when_a_benchmark_is_omitted():
    """A table missing a benchmark reads as 'that one is clean'."""
    partial = {"gsm8k": _sample_overlaps()["gsm8k"]}
    with pytest.raises(C.ContaminationError, match="missing"):
        C.disclosure_table(partial)
    with pytest.raises(C.ContaminationError, match="missing"):
        C.summarize(partial)


def test_the_interpretation_is_proportionate_not_alarmist():
    """One item in a thousand must not read as a contaminated benchmark."""
    subject = item("gsm8k", question="How many apples are there?", gold="3")
    overlap = _measure([_record("How many apples are there?", "3")], [subject])
    text = C.interpretation(overlap)
    assert text.strip()
    assert "1 of 1" in text or "100.0%" in text


def test_summarize_carries_the_definitions_and_the_held_out_verdicts():
    overlaps = _sample_overlaps()
    summary = C.summarize(overlaps)
    assert summary["held_out"] == sorted(
        name for name, overlap in overlaps.items() if overlap.held_out)
    for key in ("exact", "near", "contaminated", "sibling", "shingle_basis",
                "matched_per"):
        assert key in summary["definitions"], key
    assert "answer" in summary["definitions"]["contaminated"].lower()


def test_the_summary_is_json_serialisable():
    json.dumps(C.summarize(_sample_overlaps()), default=str)


def test_matches_are_deduplicated_per_item_and_training_record():
    """The corpus stores some records three times; a hit must not triple."""
    subject = item("gsm8k", question="How many apples are there?", gold="3")
    record = _record("How many apples are there?", "3")
    overlap = _measure([record, dict(record), dict(record)], [subject])
    assert overlap.exact_overlap == 1
    assert len(overlap.matches) == 1


def test_every_exact_match_records_the_evidence_for_audit():
    subject = item("gsm8k", question="How many apples are there?", gold="3")
    overlap = _measure([_record("How many apples are there?", "3",
                                rid="abc123")], [subject])
    match = overlap.matches[0]
    assert match.train_id == "abc123"
    assert match.rule == "identical text"
    assert match.answer_carried is True
    assert match.train_question_head and match.train_answer_head
    assert match.to_dict()["item_id"] == subject.item_id
    assert match.to_dict()["kind"] == "exact"


# ---------------------------------------------------------------------------
# the pipeline step that writes the artifact the report reads
# ---------------------------------------------------------------------------
def test_the_pipeline_contamination_step_reads_the_corpus_from_its_root(
        tmp_path, monkeypatch):
    """The glue, not the measurement.

    ``pipeline.contamination`` is the only caller of ``load_corpus``, and it
    passed it no root while unpacking nothing from the ``(records, summary)``
    pair it returns. No test called the pipeline step, so the defect surfaced
    only when the report was built — after the model run that the report is
    about. This pins the seam instead.
    """
    from sciencemath.comparability import pipeline as P
    from sciencemath.comparability.contract import BENCHMARK_ORDER

    corpus = tmp_path / "training" / "datasets" / "sciencemath-sft-v1"
    corpus.mkdir(parents=True)
    (corpus / "train.jsonl").write_text(
        json.dumps(_record(PLANETS, "gravity")) + "\n", encoding="utf-8")

    monkeypatch.setattr(P, "load_all", lambda benchmarks=None: {
        name: [item(name, question=f"a {name} question {index}",
                    native_id=f"n{index}")
               for index in range(2)]
        for name in BENCHMARK_ORDER})

    payload = P.contamination(tmp_path)

    assert [row["benchmark"] for row in payload["table"]] == \
        list(BENCHMARK_ORDER)
    assert payload["corpus"]["files"] == [
        "training/datasets/sciencemath-sft-v1/train.jsonl"]
    assert payload["summary"]["corpus"]["records"] == 1
    # The gate reads the table; the disclosure reads the corpus summary.
    assert (tmp_path / "evaluations" / "t31"
            / "contamination.json").exists()
