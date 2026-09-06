"""T2 suite integrity tests: checksum verification gates a tampered suite
before any evaluation is allowed to run. Runs offline against synthetic dirs."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from evaluate_base import verify_suite  # noqa: E402
from sciencemath.utils.io_utils import write_json, write_jsonl  # noqa: E402


@pytest.fixture()
def frozen_suite(tmp_path):
    suite = tmp_path / "suite" / "v1"
    suite.mkdir(parents=True)
    questions = [
        {"eval_id": "ev1-a", "question": "2+2?", "expected_answer": "4",
         "category": "arithmetic", "answer_type": "numeric"},
        {"eval_id": "ev1-b", "question": "symbol for sodium?",
         "expected_answer": "Na", "category": "general_science",
         "answer_type": "text"},
    ]
    write_jsonl(suite / "questions.jsonl", questions)
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in suite.iterdir() if p.is_file()}
    write_json(suite / "checksum.json", {
        "suite_version": "sciencemath-eval-v1", "frozen_at": "t",
        "files": files, "immutable": True})
    return suite


def test_verify_clean_suite_passes(frozen_suite):
    report = verify_suite(frozen_suite)
    assert report["verified"] is True
    assert report["problems"] == []


def test_verify_detects_tampered_question_file(frozen_suite):
    # modify questions.jsonl after freezing -> checksum must fail
    ql = frozen_suite / "questions.jsonl"
    data = json.loads(ql.read_text(encoding="utf-8").splitlines()[0])
    data["expected_answer"] = "5"
    lines = ql.read_text(encoding="utf-8").splitlines()
    lines[0] = json.dumps(data, ensure_ascii=False)
    ql.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_suite(frozen_suite)
    assert report["verified"] is False
    assert report["problems"][0]["problem"] == "HASH_MISMATCH"
    assert report["problems"][0]["file"] == "questions.jsonl"


def test_verify_detects_missing_file(frozen_suite):
    (frozen_suite / "questions.jsonl").unlink()
    report = verify_suite(frozen_suite)
    assert report["verified"] is False
    assert report["problems"][0]["problem"] == "MISSING"


def test_verify_reports_extra_unlisted_files(frozen_suite):
    (frozen_suite / "injected.json").write_text("{}", encoding="utf-8")
    report = verify_suite(frozen_suite)
    assert report["verified"] is True          # extra file: reported, not fatal
    assert "injected.json" in report["extra_unlisted_files"]


def test_freeze_refuses_existing_suite(tmp_path, capsys, monkeypatch):
    """build_eval_suite refuses to overwrite an already-frozen suite."""
    import build_eval_suite

    suite = tmp_path / "suite" / "v1"
    suite.mkdir(parents=True)
    (suite / "checksum.json").write_text(
        json.dumps({"frozen_at": "then"}), encoding="utf-8")

    saved = build_eval_suite.SUITE_DIR
    build_eval_suite.SUITE_DIR = suite
    monkeypatch.setattr(sys, "argv", ["build_eval_suite.py"])
    try:
        assert build_eval_suite.main() == 7
    finally:
        build_eval_suite.SUITE_DIR = saved
    out = capsys.readouterr().out
    assert "REFUSED" in out


# -------------------------------------------------- runner resume behavior
def test_done_eval_ids_and_resume_skip(tmp_path):
    from sciencemath.evaluation.runner import done_eval_ids

    pred = tmp_path / "predictions.jsonl"
    assert done_eval_ids(pred) == set()

    pred.write_text(
        '\n{"eval_id": "ev1-a"}\nnot json\n{"eval_id": "ev1-b"}\n',
        encoding="utf-8")
    assert done_eval_ids(pred) == {"ev1-a", "ev1-b"}    # bad line skipped


def test_prediction_writer_flushes_each_record(tmp_path):
    from sciencemath.evaluation.runner import PredictionWriter

    p = tmp_path / "predictions.jsonl"
    w = PredictionWriter(p)
    w.write({"eval_id": "ev1-a", "correct": True})
    w.close()
    assert json.loads(p.read_text(encoding="utf-8").strip())["eval_id"] == \
        "ev1-a"


# ------------------------------------------------------ suite builder logic
def test_sample_plan_counts_and_synthetic_isolation():
    import build_eval_suite as b

    fake = []
    for src, n in (("gsm8k", 100), ("ai2-arc", 100), ("sciq", 100)):
        for i in range(n):
            fake.append({"source": src, "source_id": f"{src}-{i}",
                         "question": f"{src} question {i} about area {i%5}",
                         "subject_raw": "algebra",
                         "category": "x" if src != "math-competition"
                         else "algebra",
                         "answer_type": "numeric", "license": "MIT",
                         "expected_answer": "0", "synthetic": False,
                         "source_split": "test"})
    # mirror load_sources(): synthetic instruction/calibration items are
    # appended BEFORE sampling and must all survive it
    for i, item in enumerate(b.SYNTHETIC_INSTRUCTION):
        fake.append({"source": "synthetic-v1",
                     "source_id": "synth-instr-" + str(i),
                     "question": item["question"], "answer_type": "text",
                     "category": "instruction_following", "license": "MIT",
                     "expected_answer": item["expected_answer"],
                     "synthetic": True, "source_split": "synthetic"})
    for i, item in enumerate(b.SYNTHETIC_CALIBRATION):
        fake.append({"source": "synthetic-v1",
                     "source_id": "synth-calib-" + str(i),
                     "question": item["question"], "answer_type": "text",
                     "category": "uncertainty_calibration", "license": "MIT",
                     "expected_answer": item["expected_answer"],
                     "synthetic": True, "source_split": "synthetic"})

    picked = b.sample_questions(fake, seed=42)
    by_src = {}
    for q in picked:
        by_src[q["source"]] = by_src.get(q["source"], 0) + 1
    assert by_src["gsm8k"] == b.SAMPLE_PLAN["gsm8k"]
    assert by_src["ai2-arc"] == b.SAMPLE_PLAN["ai2-arc"]
    assert by_src["sciq"] == b.SAMPLE_PLAN["sciq"]
    synth = [q for q in picked if q["source"] == "synthetic-v1"]
    assert synth, "synthetic instruction/calibration items must be present"
    assert all(q["synthetic"] is True for q in synth)
    assert {q["category"] for q in synth} <= {
        "instruction_following", "uncertainty_calibration"}


def test_sampling_is_deterministic():
    import build_eval_suite as b

    def pool():
        return [{"source": "gsm8k", "source_id": f"g{i}",
                 "question": f"q{i} {i * 7}", "answer_type": "numeric",
                 "category": "arithmetic", "license": "MIT",
                 "expected_answer": "1", "synthetic": False,
                 "source_split": "test"} for i in range(200)]

    p1 = [q["source_id"] for q in b.sample_questions(pool(), seed=42)]
    p2 = [q["source_id"] for q in b.sample_questions(pool(), seed=42)]
    assert p1 == p2
    assert p1 != [q["source_id"] for q in b.sample_questions(pool(), seed=43)]


def test_stable_seed_no_python_hash():
    import build_eval_suite as b

    assert b._stable_seed("hello") == b._stable_seed("hello")


def test_eval_ids_unique_and_stable():
    import build_eval_suite as b

    qs = [{"source": "s", "source_id": "x1", "question": "why is sky blue?",
           "expected_answer": "a"}]
    b.assign_ids([qs[0]])
    id1 = qs[0]["eval_id"]
    qs2 = [{"source": "s", "source_id": "x1", "question": "why is sky blue?",
            "expected_answer": "a"}]
    b.assign_ids(qs2)
    assert qs2[0]["eval_id"] == id1
    assert id1.startswith("ev1-")


def test_leakage_gate_fails_on_direct(tmp_path, monkeypatch):
    import build_eval_suite as b

    train = [{"id": "t1", "source": "gsm8k", "question": "What is 2 + 2?"}]
    data_dir = tmp_path / "data"
    (data_dir / "train").mkdir(parents=True)
    (data_dir / "train" / "t.jsonl").write_text(
        json.dumps(train[0]) + "\n", encoding="utf-8")
    monkeypatch.setattr(b, "REPO_ROOT", tmp_path)
    # identical question text on both sides: fingerprint collision = leakage
    picked = [{"eval_id": "ev1-x", "source": "gsm8k",
               "question": "What is 2 + 2?"}]
    gate = b.leakage_gate(picked)
    assert gate["passed"] is False and gate["direct_leakage"]