"""T3 contamination-gate, domain-balancing, LoRA-attach, manifest and
corpus-verification tests (all CPU-only, no GPU/network)."""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

CORPUS_DIR = REPO_ROOT / "training" / "datasets" / "sciencemath-sft-v1"
SUITE_DIR = REPO_ROOT / "evaluations" / "suite" / "v1"


# ------------------------------------------------------------ contamination
@pytest.mark.skipif(not CORPUS_DIR.exists(), reason="corpus not built")
class TestContaminationGate:
    def test_gate_removes_exact_eval_question(self):
        import build_sft_corpus as bsc
        from sciencemath.utils.io_utils import read_jsonl

        suite_q = read_jsonl(SUITE_DIR / "questions.jsonl")[0]["question"]
        records = [
            {"id": "clean-1", "source": "sciq", "source_id": "s1",
             "question": "Completely unrelated training question about cells?",
             "answer": "mitochondria", "domain": "general_science",
             "target_response": "Answer: \\boxed{mitochondria}"},
            {"id": "leak-1", "source": "gsm8k", "source_id": "99",
             "question": suite_q, "answer": "1",
             "domain": "mathematics",
             "target_response": "Final answer: \\boxed{1}"},
        ]
        kept, report = bsc.contamination_gate(records)
        assert [r["id"] for r in kept] == ["clean-1"]
        assert report["direct_leakage_found"] == 1
        assert report["records_removed"] == 1
        assert report["removed_records"][0]["id"] == "leak-1"
        assert report["removed_records"][0]["kind"] == "direct"
        assert report["passed_after_remediation"] is True

    def test_gate_keeps_unrelated_records_untouched(self):
        import build_sft_corpus as bsc

        records = [{"id": f"clean-{i}", "source": "sciq", "source_id": str(i),
                    "question": f"Training question {i} about distinct topic {i * 7}?",
                    "answer": "a", "domain": "general_science",
                    "target_response": "Answer: \\boxed{a}"}
                   for i in range(5)]
        kept, report = bsc.contamination_gate(records)
        assert len(kept) == 5
        assert report["direct_leakage_found"] == 0
        assert report["near_leakage_found"] == 0
        assert report["records_removed"] == 0

    def test_gate_flags_near_duplicates_above_threshold(self):
        import build_sft_corpus as bsc
        from sciencemath.utils.io_utils import read_jsonl

        suite_q = read_jsonl(SUITE_DIR / "questions.jsonl")[0]["question"]
        # lightly reworded eval question -> near leakage at >= 0.90 Jaccard
        paraphrase = suite_q.replace("?", " ?")
        records = [{"id": "near-1", "source": "gsm8k", "source_id": "x",
                    "question": paraphrase, "answer": "1",
                    "domain": "mathematics",
                    "target_response": "Final answer: \\boxed{1}"}]
        kept, report = bsc.contamination_gate(records)
        assert kept == [] or report["near_leakage_found"] == 1
        assert report["records_removed"] >= 1


# ---------------------------------------------------------- domain balancing
class TestQuotaSampling:
    def _records(self):
        recs = []
        for i in range(20):                                   # general slice
            recs.append({"id": f"synth-{i}", "source": "synthetic-sft-v1",
                         "source_id": f"synth-{i}",
                         "question": f"General drill {i} unique wording {i * 13}?",
                         "answer": "ok", "domain": "scientific_reasoning",
                         "target_response": "Answer: \\boxed{ok}"})
        for i in range(400):                                  # gsm8k pool
            recs.append({"id": f"gsm-{i}", "source": "gsm8k",
                         "source_id": f"gsm-{i}",
                         "question": f"Gsm word problem {i} with numbers {i} and {i + 1}?",
                         "answer": str(i), "domain": "mathematics",
                         "subject": "arithmetic",
                         "target_response": f"Final answer: \\boxed{{{i}}}"})
        for subj in ("algebra", "prealgebra", "geometry",
                     "intermediate_algebra", "precalculus",
                     "counting_and_probability", "number_theory"):
            for i in range(80):
                recs.append({"id": f"math-{subj}-{i}",
                             "source": "math-competition",
                             "source_id": f"math-{subj}-{i}",
                             "question": f"{subj} exercise {i} variant {i * 3}?",
                             "answer": str(i), "domain": "mathematics",
                             "subject": subj,
                             "target_response": f"Final answer: \\boxed{{{i}}}"})
        for i in range(300):                                  # science pool
            recs.append({"id": f"sciq-{i}", "source": "sciq",
                         "source_id": f"sciq-{i}",
                         "question": f"Science fact {i} about topic {i * 5}?",
                         "answer": "a", "domain": "general_science",
                         "subject": "general",
                         "target_response": "Answer: \\boxed{a}"})
        return recs

    def test_general_slice_taken_whole(self):
        from build_sft_corpus import quota_sampling
        chosen, plan = quota_sampling(self._records())
        assert plan["general"] == 20
        assert sum(1 for r in chosen
                   if r["source"] == "synthetic-sft-v1") == 20

    def test_math_quota_follows_mix_ratio(self):
        from build_sft_corpus import quota_sampling
        chosen, plan = quota_sampling(self._records())
        n_math = plan["gsm8k"] + sum(v for k, v in plan.items()
                                     if k.startswith("math:"))
        expected = round(20 * 0.54 / 0.06)                    # 180
        # per-subject integer rounding may drift a few slots; stay within 3%
        assert abs(n_math - expected) <= 5
        # gsm8k share of math ~= the frozen 52%
        assert abs(plan["gsm8k"] / n_math - 0.52) < 0.02

    def test_science_bounded_by_pool_and_mix(self):
        from build_sft_corpus import quota_sampling
        chosen, plan = quota_sampling(self._records())
        expected = round(20 * 0.40 / 0.06)                    # ~133
        assert plan["sciq"] <= len([r for r in self._records()
                                    if r["source"] == "sciq"])
        assert plan["sciq"] == expected

    def test_subject_quotas_respect_pool_limits(self):
        from build_sft_corpus import quota_sampling
        _, plan = quota_sampling(self._records())
        # algebra pool has 80, but its share of ~86 competition slots is ~22
        assert plan["math:algebra"] <= 80
        for subj in ("algebra", "prealgebra", "geometry"):
            assert plan[f"math:{subj}"] > 0

    def test_sampling_is_deterministic(self):
        from build_sft_corpus import quota_sampling
        a, _ = quota_sampling(self._records())
        b, _ = quota_sampling(self._records())
        assert [r["id"] for r in a] == [r["id"] for r in b]


# ------------------------------------------------- corpus verification logic
class TestVerifyCorpus:
    def test_verify_real_frozen_corpus(self):
        if not CORPUS_DIR.exists():
            pytest.skip("corpus not built")
        from sciencemath.training.train import verify_corpus
        res = verify_corpus(CORPUS_DIR)
        assert res["ok"] is True, res
        assert res["files_checked"] >= 5

    def test_verify_detects_tampered_file(self, tmp_path):
        from sciencemath.training.train import verify_corpus
        import hashlib
        data = tmp_path / "train.jsonl"
        data.write_text("a\nb\n", encoding="utf-8")
        (tmp_path / "checksums.json").write_text(json.dumps({
            "train.jsonl": hashlib.sha256(data.read_bytes()).hexdigest()}),
            encoding="utf-8")
        assert verify_corpus(tmp_path)["ok"] is True
        data.write_text("a\nb\nTAMPERED\n", encoding="utf-8")
        res = verify_corpus(tmp_path)
        assert res["ok"] is False and res["mismatched"] == ["train.jsonl"]

    def test_verify_detects_missing_file(self, tmp_path):
        from sciencemath.training.train import verify_corpus
        (tmp_path / "checksums.json").write_text(
            json.dumps({"train.jsonl": "0" * 64}), encoding="utf-8")
        res = verify_corpus(tmp_path)
        assert res["ok"] is False and res["missing"] == ["train.jsonl"]


# ------------------------------------------------------------- LoRA attach
class TestAttachLora:
    def _toy_model(self):
        import torch.nn as nn

        class ToyModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.embed_tokens = nn.Embedding(32, 16)
                for name in ("q_proj", "k_proj", "v_proj", "o_proj",
                             "gate_proj", "up_proj", "down_proj"):
                    setattr(self, name, nn.Linear(16, 16, bias=False))
                self.norm = nn.LayerNorm(16)
                self.lm_head = nn.Linear(16, 32, bias=False)

            def get_input_embeddings(self):
                return self.embed_tokens

            def prepare_inputs_for_generation(self, *args, **kwargs):
                return {}

            def generate(self, *args, **kwargs):
                return None

        return ToyModel()

    def _lora_cfg(self):
        return {"r": 8, "lora_alpha": 16, "lora_dropout": 0.05,
                "target_modules": ["q_proj", "v_proj"]}

    def test_attach_returns_active_peft_model(self):
        peft = pytest.importorskip("peft")
        from sciencemath.training.attach import adapter_active_state, attach_lora

        model = self._toy_model()
        base_q = model.q_proj.weight.detach().clone()
        peft_model = attach_lora(model, self._lora_cfg())
        state = adapter_active_state(peft_model)
        assert state["adapter_active"] is True
        assert state["is_peft_model"] is True

    def test_base_weights_frozen_and_lora_trainable(self):
        pytest.importorskip("peft")
        from sciencemath.training.attach import attach_lora

        peft_model = attach_lora(self._toy_model(), self._lora_cfg())
        trainable = [n for n, p in peft_model.named_parameters() if p.requires_grad]
        assert trainable, "no trainable parameters after attach"
        assert all("lora_" in n for n in trainable)
        frozen = [n for n, p in peft_model.named_parameters()
                  if not p.requires_grad]
        assert any("q_proj.original_module.weight" in n or
                   "q_proj.base_layer.weight" in n for n in frozen)

    def test_targeted_modules_get_adapters(self):
        pytest.importorskip("peft")
        from sciencemath.training.attach import attach_lora

        peft_model = attach_lora(self._toy_model(), self._lora_cfg())
        names = [n for n, _ in peft_model.named_modules()]
        assert any("q_proj.lora_A" in n for n in names)
        assert not any("k_proj.lora_A" in n for n in names)  # not targeted


# -------------------------------------------------------- checkpoint manifest
class TestAdapterManifest:
    def _minimal_config(self):
        corpus_dir = "training/datasets/sciencemath-sft-v1"
        return {
            "corpus": {"version": "sciencemath-sft-v1", "dir": corpus_dir},
            "training": {"seed": 42, "num_train_epochs": 3,
                         "max_seq_length": 1024,
                         "per_device_train_batch_size": 1,
                         "gradient_accumulation_steps": 16,
                         "learning_rate": 1.0e-4},
            "lora": {"r": 32, "lora_alpha": 64, "lora_dropout": 0.05},
            "quantization": {"load_in_4bit": True,
                             "bnb_4bit_quant_type": "nf4"},
        }

    def test_manifest_contains_required_provenance(self):
        if not CORPUS_DIR.exists():
            pytest.skip("corpus not built")
        from sciencemath.training.train import _adapter_manifest

        m = _adapter_manifest(
            repo_root=REPO_ROOT, config=self._minimal_config(),
            model_id="Qwen/Qwen3-1.7B", revision=None,
            corpus_cfg=self._minimal_config()["corpus"],
            train_stats={"kept": 2910, "dropped_too_long": 0},
            val_stats={"kept": 121, "dropped_too_long": 0},
            log_history=[{"loss": 1.2, "step": 100}],
            final_train_loss=1.2, best_eval_loss=1.1,
            peak_vram=4_000_000_000, train_time_s=3600.0,
            n_train=2910, n_val=121, resumed=False, dry_run=False)
        assert m["artifact"] == "ScienceMath-v0.1-T3"
        assert m["base_model"]["model_id"] == "Qwen/Qwen3-1.7B"
        assert m["dataset"]["version"] == "sciencemath-sft-v1"
        assert m["dataset"]["checksums"], "manifest must embed corpus checksums"
        assert m["seed"] == 42
        assert m["adapter_format"] == "PEFT/LoRA (unmerged)"
        assert m["dry_run"] is False
        for key in ("environment", "git_commit", "training_config", "results"):
            assert key in m