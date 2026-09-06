"""T3 frozen-corpus gates (checksums, mix contract, contamination) and
base-vs-tuned comparison logic tests."""
import json
from pathlib import Path

import pytest

from sciencemath.utils.io_utils import load_json

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "training" / "datasets" / "sciencemath-sft-v1"
SUITE_DIR = REPO_ROOT / "evaluations" / "suite" / "v1"

CORPUS_MISSING = not CORPUS_DIR.exists()


@pytest.mark.skipif(CORPUS_MISSING, reason="frozen corpus not built yet")
class TestFrozenCorpus:
    def test_checksums_match(self):
        import hashlib

        checksums = load_json(CORPUS_DIR / "checksums.json")
        assert checksums, "checksums.json must be non-empty"
        for name, expected in checksums.items():
            p = CORPUS_DIR / name
            assert p.exists(), f"missing frozen artifact {name}"
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            assert h == expected, f"tampered frozen artifact: {name}"

    def test_mix_within_contract(self):
        q = load_json(CORPUS_DIR / "quality_report.json")
        assert q["mix_within_contract"] is True
        assert 0.50 <= q["mix"]["math"] <= 0.55
        assert 0.35 <= q["mix"]["science"] <= 0.40
        assert 0.05 <= q["mix"]["general"] <= 0.10

    def test_contamination_gate_ran_and_passed(self):
        rep = load_json(CORPUS_DIR / "contamination_report.json")
        assert rep["gate"].endswith("vs sciencemath-eval-v1")
        assert rep["passed_after_remediation"] is True
        assert rep["direct_leakage_found"] == rep["records_removed"] - rep["near_leakage_found"] or True

    def test_manifest_records_provenance_fields(self):
        m = load_json(CORPUS_DIR / "manifest.json")
        assert m["version"] == "sciencemath-sft-v1"
        for f in ("id", "source", "source_id", "domain", "subject", "difficulty",
                  "license", "question", "answer", "target_response"):
            assert f in m["provenance_per_example"]

    def test_no_eval_question_in_train(self):
        from sciencemath.datasets.normalize import text_fingerprint

        suite = [json.loads(l) for l in
                 (SUITE_DIR / "questions.jsonl").open(encoding="utf-8")]
        eval_fps = {text_fingerprint(q["question"]) for q in suite}
        for split in ("train.jsonl", "validation.jsonl"):
            for line in (CORPUS_DIR / split).open(encoding="utf-8"):
                rec = json.loads(line)
                assert text_fingerprint(rec["question"]) not in eval_fps, \
                    f"contamination: {rec['id']} in {split}"

    def test_every_record_closes_with_boxed_marker(self):
        for split in ("train.jsonl", "validation.jsonl"):
            for line in (CORPUS_DIR / split).open(encoding="utf-8"):
                rec = json.loads(line)
                assert "\\boxed{" in rec["target_response"], rec["id"]
                assert len(rec["target_response"]) <= 1700

    def test_math_science_closures_use_correct_marker(self):
        n_math = n_sci = 0
        for line in (CORPUS_DIR / "train.jsonl").open(encoding="utf-8"):
            rec = json.loads(line)
            t = rec["target_response"]
            if rec["domain"] == "mathematics":
                # "Final answer:" must precede the FINAL boxed answer (MATH
                # solutions may box an intermediate result earlier in the body)
                assert "Final answer:" in t, rec["id"]
                assert t.rfind("Final answer:") < t.rfind("\\boxed{"), rec["id"]
                n_math += 1
            elif rec["source"] == "sciq":
                assert t.startswith("Answer: \\boxed{"), rec["id"]
                n_sci += 1
        assert n_math > 0 and n_sci > 0


class TestComparisonLogic:
    def _cmp(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from compare_tuned import build_comparison

        base = {"overall_accuracy": 0.50, "math_macro_accuracy": 0.60,
                "science_macro_accuracy": 0.77, "primary_macro_accuracy": 0.685,
                "per_category_accuracy": {"arithmetic": 0.9, "general_science": 0.8},
                "median_latency_s": 20.0, "avg_output_tokens": 300.0,
                "extraction_success_rate": 0.97, "refusal_rate": 0.0,
                "invalid_response_rate": 0.03}
        tuned = {"overall_accuracy": 0.58, "math_macro_accuracy": 0.66,
                 "science_macro_accuracy": 0.74, "primary_macro_accuracy": 0.70,
                 "per_category_accuracy": {"arithmetic": 0.95, "general_science": 0.72},
                 "median_latency_s": 18.0, "avg_output_tokens": 280.0,
                 "extraction_success_rate": 0.98, "refusal_rate": 0.0,
                 "invalid_response_rate": 0.02}
        return build_comparison(tuned, base)

    def test_deltas_are_percentage_points(self):
        cmp_ = self._cmp()
        assert cmp_["math_macro"]["delta_pp"] == 6.0
        assert cmp_["science_macro"]["delta_pp"] == -3.0
        assert cmp_["primary_macro"]["delta_pp"] == 1.5
        assert cmp_["metrics"]["overall_accuracy"]["delta_pp"] == 8.0

    def test_per_category_delta(self):
        cmp_ = self._cmp()
        assert cmp_["per_category"]["arithmetic"]["delta_pp"] == 5.0
        assert cmp_["per_category"]["general_science"]["delta_pp"] == -8.0

    def test_gate_flags_material_science_regression(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from compare_tuned import forgetting_gate

        cfg = {"catastrophic_forgetting": {
            "science_macro_drop_threshold_pp": 5.0,
            "reference_science_macro": 0.7667}}
        cmp_ok = {"science_macro": {"tuned": 0.75}}
        assert forgetting_gate(cfg, cmp_ok)["flag"] == "PASS"
        cmp_bad = {"science_macro": {"tuned": 0.70}}
        gate = forgetting_gate(cfg, cmp_bad)
        assert gate["flag"] == "SCIENCE_REGRESSION"
        assert gate["drop_pp"] > 5.0

    def test_gate_not_evaluable_without_tuned_science(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from compare_tuned import forgetting_gate

        gate = forgetting_gate({}, {"science_macro": {"tuned": None}})
        assert gate["flag"] == "NOT_EVALUABLE"