"""Infrastructure checks for the T32 handoff, without loading model weights."""
import json

import pytest

from sciencemath.t32 import selection
from sciencemath.t32.paired import _mcnemar_exact, paired_table


def test_selection_uses_percentage_points_and_normalized_candidate_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(selection, "OUT", tmp_path)
    monkeypatch.setattr(selection.sys, "argv", ["selection"])
    monkeypatch.setattr(selection, "_contamination_ok", lambda c: c in {"t32-A", "t32-B", "t32-C"})
    monkeypatch.setattr(selection, "_manifest_ok", lambda c: True)
    anchors = {"math_dev_mean": .50, "acc_mc_dev": .80, "acc_sciq_dev": .80}
    candidates = {
        "t32-A": {"math_dev_mean": .56, "acc_mc_dev": .78, "acc_sciq_dev": .79},
        "t32-B": {"math_dev_mean": .60, "acc_mc_dev": .75, "acc_sciq_dev": .80},
        "t32-C": {"math_dev_mean": .54, "acc_mc_dev": .80, "acc_sciq_dev": .80},
    }
    for label, metrics in {"base": anchors, "t30-anchor": anchors, **candidates}.items():
        (tmp_path / f"{label}_metrics.json").write_text(json.dumps(metrics))
    assert selection.main() == 0
    result = json.loads((tmp_path / "T32_PHASE8_SELECTION.json").read_text())
    assert result["selected"] == "t32-A"
    assert result["eligible"] == ["t32-A"]
    assert result["candidates"]["t32-A"]["delta_math_dev_mean_vs_t30"] == 6


def test_large_mcnemar_table_stays_finite_and_symmetric():
    assert _mcnemar_exact(1000, 1100) == pytest.approx(.03072070786417)
    assert _mcnemar_exact(1100, 1000) == _mcnemar_exact(1000, 1100)


def test_paired_analysis_rejects_missing_members_and_changed_prompts():
    row = {"content_valid": True, "prompt_sha256": "same"}
    with pytest.raises(ValueError, match="membership"):
        paired_table("t30", "t32-A", "gsm8k", {"one": row}, {})
    with pytest.raises(ValueError, match="Prompt drift"):
        paired_table("t30", "t32-A", "gsm8k", {"one": row},
                     {"one": {**row, "prompt_sha256": "changed"}})


def test_closure_builds_receipts_and_a_verified_pack(tmp_path, monkeypatch):
    from sciencemath.t32 import closure
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(closure, "ROOT", tmp_path)
    pack = tmp_path / "evaluations/t32"
    monkeypatch.setattr(closure, "PACK", pack)
    def put(path, content):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    def obj(path, value):
        put(path, json.dumps(value))
    selection_record = {"selected": "t32-A", "selection_rule_applied": "predeclared", "candidates": {}}
    for tag, name in closure.NAMES.items():
        manifest = {"environment": {"python": "test"}, "dataset": {"checksums": {"train": "hash"}}, "seed": 42}
        obj(f"training/adapters/{name}/training_manifest.json", manifest)
        put(f"training/adapters/{name}/adapter_model.safetensors", "synthetic")
        obj(f"training/t32/candidates/{name}/manifest.json", {"train_sha256": "hash"})
        obj(f"evaluations/t32/development/train_Mango-T32-{tag}-{name.split('-', 2)[2]}.json", {"summary": {"status": "COMPLETE"}})
        selection_record["candidates"][f"t32-{tag}"] = {"acc_gsm8k_dev": .6, "acc_math_dev": .6, "math_dev_mean": .6, "acc_mc_dev": .8, "acc_sciq_dev": .8, "eligible": True}
    obj("evaluations/t32/development/T32_PHASE8_SELECTION.json", selection_record)
    obj("evaluations/t32/manifests/T32_HANDOFF_PRESERVATION.json", {"files": {}})
    obj("evaluations/t32/manifests/T31_FREEZE_RECORD.json", {"t31": {"base_revision": "test"}})
    put("evaluations/t31/SHA256SUMS", "")
    put("evaluations/t32/development/OPS_NOTES.md", "test history")
    hypotheses = {f"H{i}": {"verdict": "TEST"} for i in range(1, 7)}
    obj("evaluations/t32/diagnostics/T32_PHASE2_HYPOTHESES.json", {"hypotheses": hypotheses})
    obj("training/t32/pools/contamination_report.json", {"passed_after_remediation": True})
    xml = '<testsuites><testsuite><testcase classname="test" name="one"/></testsuite></testsuites>'
    put("evaluations/t32/development/regression_junit.xml", xml)
    put("evaluations/t31/recovery/t31_measured_tests_junit.xml", xml)
    pairs = {b: {"base_vs_t32-A": {"n_shared": n, "accuracy_frozen": .5, "accuracy_fresh": .6, "delta_pp": 10},
                 "t30_vs_t32-A": {"n_shared": n, "accuracy_frozen": .5, "accuracy_fresh": .6, "delta_pp": 10}}
             for b, n in closure.BENCHES.items()}
    obj("evaluations/t32/paired/T32_PAIRED_ANALYSIS.json", {"benchmarks": pairs})
    assert closure.main() == 0
    result = closure.read(pack / "manifests/T32_PACK_VERIFICATION.json")
    assert result["sums_ok"]
    assert result["verified_files"] > 10
    report = (pack / "reports/MANGO_T32_MATH_REGRESSION_REMEDIATION_REPORT.md").read_text()
    assert "MANGO_T32_MATH_REMEDIATION_PARTIAL" in report
