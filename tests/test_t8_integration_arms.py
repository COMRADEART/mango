"""T8.15/T8.16 — integration-arm runner guards (T8.29).

These test the thin T8 wrappers around the frozen T4/T5R machinery:
  - t8_t4_arm.py writes per-candidate outputs under evaluations/t8/runs/
    (never into the frozen tool-suite dir) and generates the no-tool arm
    fresh instead of reusing the 1.7B's frozen predictions.
  - run_rag_eval_t5r.py honours MANGO_EVAL_MODEL: a candidate base model
    is loaded with NO T3 adapter attached.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestT4ArmPaths:
    def test_outputs_stay_under_t8_runs(self):
        """The frozen tool-suite dir must never receive candidate outputs."""
        mod = _load_script("t8_t4_arm.py")
        out_root = mod.RUNS / "some-candidate"
        assert mod.RUNS.resolve().parts[-3:-1] == ("evaluations", "t8")
        assert "tool-suite" not in str(out_root)

    def test_no_tool_arm_uses_fresh_generation(self):
        """Both arms must pass through run_tool_enabled (fresh generation);
        no frozen-prediction reuse path may exist for candidates."""
        src = (REPO_ROOT / "scripts" / "t8_t4_arm.py").read_text(
            encoding="utf-8")
        assert "run_tool_enabled" in src
        assert src.count('("t4_notool", False)') == 1
        assert src.count('("t4_tool", True)') == 1
        assert "reuse_no_tool_predictions" not in src


class TestRagEvalModelOverride:
    @pytest.fixture()
    def t5r(self):
        return _load_script("run_rag_eval_t5r.py")

    def test_candidate_resume_identity_tracks_model_and_budget(self, t5r, monkeypatch):
        monkeypatch.setenv("MANGO_EVAL_MODEL", "candidate-a")
        first = t5r.candidate_provenance()
        monkeypatch.setenv("MANGO_EVAL_MODEL", "candidate-b")
        assert t5r.candidate_provenance() != first
        monkeypatch.setenv("MANGO_EVAL_MODEL", "candidate-a")
        t5r.GENERATION["max_new_tokens"] = 2048
        assert t5r.candidate_provenance() != first
        assert first["generation"]["max_new_tokens"] == 1024
        assert first["adapter"] is None
        monkeypatch.delenv("MANGO_EVAL_MODEL")
        assert t5r.candidate_provenance() == {}

    def test_candidate_load_resets_previous_token_exception(self, t5r, monkeypatch):
        monkeypatch.setattr(
            "sciencemath.evaluation.model_loader.load_model_safely",
            lambda model_id: ("tok", "model", {"ok": True}))
        monkeypatch.setenv("MANGO_EVAL_MODEL", "candidate")
        monkeypatch.setenv("MANGO_EVAL_MAX_TOKENS", "2048")
        t5r.load_model()
        assert t5r.GENERATION["max_new_tokens"] == 2048
        monkeypatch.delenv("MANGO_EVAL_MAX_TOKENS")
        t5r.load_model()
        assert t5r.GENERATION["max_new_tokens"] == 1024

    def test_override_loads_base_model_without_adapter(
            self, t5r, monkeypatch):
        calls = {}

        def fake_load(model_id):
            calls["model_id"] = model_id
            return ("tok", "model", {"ok": True})

        monkeypatch.setattr(
            "sciencemath.evaluation.model_loader.load_model_safely",
            fake_load)
        monkeypatch.setenv("MANGO_EVAL_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
        model, tok = t5r.load_model()
        assert (model, tok) == ("model", "tok")
        assert calls["model_id"] == "Qwen/Qwen3-4B-Instruct-2507"

    def test_no_override_uses_config_and_attaches_adapter(
            self, t5r, monkeypatch, tmp_path):
        """Default behaviour is unchanged: configs/model.yaml + T3 adapter
        (guard against the override accidentally replacing production)."""
        monkeypatch.delenv("MANGO_EVAL_MODEL", raising=False)

        def fake_load(model_id):
            return ("tok", "model", {"ok": True})

        monkeypatch.setattr(
            "sciencemath.evaluation.model_loader.load_model_safely",
            fake_load)
        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()

        class FakePeft:
            @staticmethod
            def from_pretrained(model, path):
                assert Path(path) == adapter_dir

                class _M:
                    def eval(self):
                        return self

                return _M()

        monkeypatch.setitem(sys.modules, "peft",
                            type("M", (), {"PeftModel": FakePeft}))
        monkeypatch.setattr(t5r, "ROOT", tmp_path)
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "model.yaml").write_text(
            "model_id: Qwen/Qwen3-1.7B\n", encoding="utf-8")
        (tmp_path / "configs" / "training.yaml").write_text(
            "training:\n  adapter_output_dir: adapter\n", encoding="utf-8")
        model, tok = t5r.load_model()
        assert model is not "model"          # noqa: F632 — wrapped, not raw
        assert callable(getattr(model, "eval", None))  # eval() was reached
        assert tok == "tok"
