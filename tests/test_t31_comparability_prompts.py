"""T31 tests, brief categories 3, 4, 5: prompts and the frozen configuration.

- 3  deterministic prompts
- 4  base/adapter prompt equality
- 5  frozen decoding configuration

Category 4 is the one that matters most. The brief's central experimental rule
is that the only difference between the two arms is the weights, and a prompt
difference is the easiest way to violate it while every row still looks
well-formed. These tests attack it from the structural side (the prompt
function cannot be asked for an arm-specific prompt) and from the recorded
side (two rows for one item carry byte-identical prompts).
"""
from __future__ import annotations

import inspect
import json

import pytest

from sciencemath.comparability import config as cfg
from sciencemath.comparability import prompts
from sciencemath.comparability.contract import ARM_ADAPTER, ARM_BASE, BENCHMARKS

from t31_comparability_support import item, kind_of, mcq, raw_row


# ---------------------------------------------------------------------------
# category 3 — deterministic prompts
# ---------------------------------------------------------------------------
def test_prompt_is_deterministic_across_calls():
    subject = mcq()
    assert prompts.prompt_text(subject, "multiple_choice") == \
        prompts.prompt_text(subject, "multiple_choice")


def test_prompt_differs_when_the_question_differs():
    a = mcq(question="Which one?")
    b = mcq(question="Which other one?")
    assert prompts.prompt_text(a, "multiple_choice") != \
        prompts.prompt_text(b, "multiple_choice")


def test_prompt_includes_every_option_label_and_text():
    subject = mcq(choices=(("A", "sunlight"), ("B", "water"),
                           ("C", "soil"), ("D", "air")))
    text = prompts.prompt_text(subject, "multiple_choice")
    for label, option in subject.choices:
        assert f"{label}) {option}" in text


def test_prompt_is_a_pure_function_of_the_item():
    """No arm, no clock, no random state — the signature says so."""
    signature = inspect.signature(prompts.prompt_text)
    assert list(signature.parameters) == ["item", "kind"]


def test_prompt_module_exposes_no_arm_parameter_anywhere():
    """A function that *could* build an arm-specific prompt would be asked to."""
    source = inspect.getsource(prompts)
    for parameter in inspect.signature(prompts.prompt_text).parameters:
        assert "arm" not in parameter
    assert "ARM_BASE" not in source and "ARM_ADAPTER" not in source


def test_system_prompt_is_the_same_empty_string_for_both_arms():
    assert prompts.SYSTEM_PROMPT == ""
    row_base = raw_row(item(), ARM_BASE)
    row_adapter = raw_row(item(), ARM_ADAPTER)
    assert row_base["system_prompt"] == row_adapter["system_prompt"] == ""


@pytest.mark.parametrize("benchmark", sorted(BENCHMARKS))
def test_every_benchmark_has_a_prompt_policy_for_its_kind(benchmark):
    kind = BENCHMARKS[benchmark]["kind"]
    assert kind in prompts.PROMPT_POLICY


def test_numeric_prompt_asks_for_the_benchmark_marker_not_a_style():
    text = prompts.prompt_text(item(), "numeric")
    assert "#### " in text
    # The instruction must not ask for reasoning in a particular style; that
    # is the kind of sentence that becomes tunable.
    assert "step by step" not in text.lower()


def test_math_prompt_asks_for_the_boxed_marker():
    text = prompts.prompt_text(item("math500"), "math")
    assert "\\boxed{}" in text


def test_prompt_policy_hash_is_stable_and_content_addressed():
    assert prompts.prompt_policy_hash() == prompts.prompt_policy_hash()
    assert len(prompts.prompt_policy_hash()) == 64


def test_prompt_policy_hash_changes_when_the_policy_changes(monkeypatch):
    before = prompts.prompt_policy_hash()
    monkeypatch.setitem(prompts.PROMPT_POLICY, "numeric",
                        prompts.PROMPT_POLICY["numeric"] + " Answer now.")
    assert prompts.prompt_policy_hash() != before


# ---------------------------------------------------------------------------
# category 4 — base/adapter prompt equality
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("subject", [
    item(),                         # numeric
    item("math500"),                # math
    mcq(),                          # multiple choice
])
def test_both_arms_record_identical_prompts_for_one_item(subject):
    base = raw_row(subject, ARM_BASE)
    adapter = raw_row(subject, ARM_ADAPTER)
    assert base["user_prompt"] == adapter["user_prompt"]
    assert base["system_prompt"] == adapter["system_prompt"]
    assert base["prompt_sha256"] == adapter["prompt_sha256"]
    assert base["item_id"] == adapter["item_id"]


def test_the_only_recorded_difference_between_arms_is_the_identity():
    """Field-by-field: everything but arm/identity/output must be equal."""
    subject = mcq()
    base = raw_row(subject, ARM_BASE)
    adapter = raw_row(subject, ARM_ADAPTER)
    permitted = {"arm", "model_id", "model_revision", "adapter_id",
                 "adapter_revision", "adapter_sha256", "raw_generation",
                 "generated_at", "latency_s", "output_tokens",
                 "finish_reason", "error", "prompt_tokens"}
    differing = {key for key in base
                 if key not in permitted and base[key] != adapter[key]}
    assert differing == set()


# ---------------------------------------------------------------------------
# category 5 — frozen decoding configuration
# ---------------------------------------------------------------------------
def test_primary_arm_is_greedy_and_sampling_is_off():
    decoding = cfg.decoding_policy(thinking=False)
    assert decoding["do_sample"] is False
    assert decoding["num_beams"] == 1
    assert decoding["repetition_penalty"] == 1.0
    # Greedy: sampling-only knobs are recorded as unset rather than invented.
    assert decoding["temperature"] is None
    assert decoding["top_p"] is None
    assert decoding["top_k"] is None


def test_thinking_differs_from_primary_in_exactly_one_flag():
    primary = cfg.decoding_policy(thinking=False)
    thinking = cfg.decoding_policy(thinking=True)
    differing = {key for key in primary
                 if primary[key] != thinking.get(key)}
    assert differing == {"enable_thinking", "max_new_tokens"}
    assert primary["enable_thinking"] is False
    assert thinking["enable_thinking"] is True


def test_thinking_arm_gets_a_larger_budget_for_every_benchmark():
    primary = cfg.decoding_policy(thinking=False)["max_new_tokens"]
    thinking = cfg.decoding_policy(thinking=True)["max_new_tokens"]
    assert set(primary) == set(thinking) == set(BENCHMARKS)
    for name in primary:
        assert thinking[name] == primary[name] * 4


def test_stop_tokens_are_recorded():
    assert cfg.STOP_TOKEN_IDS == (151645,)
    assert cfg.decoding_policy()["stop_token_ids"] == [151645]


def test_decoding_policy_covers_every_benchmark_budget():
    budgets = cfg.decoding_policy()["max_new_tokens"]
    for name, spec in BENCHMARKS.items():
        assert budgets[name] == spec["max_new_tokens"]


# ---------------------------------------------------------------------------
# category 21 — hash generation
# ---------------------------------------------------------------------------
def _sample_config(**overrides):
    base = cfg.frozen_config(suite_hashes={"gsm8k": "a" * 64},
                             chat_template_sha256="b" * 64)
    base.update(overrides)
    return base


def test_config_hash_is_stable_for_identical_content():
    assert cfg.config_hash(_sample_config()) == \
        cfg.config_hash(_sample_config())


def test_config_hash_ignores_its_own_recorded_digest():
    config = _sample_config()
    with_digest = {**config, "config_sha256": "deadbeef"}
    assert cfg.config_hash(config) == cfg.config_hash(with_digest)


def test_config_hash_changes_when_any_setting_changes():
    baseline = cfg.config_hash(_sample_config())
    assert cfg.config_hash(_sample_config(experimental_variable="other")) \
        != baseline
    shifted = cfg.frozen_config(suite_hashes={"gsm8k": "c" * 64},
                                chat_template_sha256="b" * 64)
    assert cfg.config_hash(shifted) != baseline


def test_config_records_the_environment_and_the_prompt_policy():
    config = _sample_config()
    assert config["prompt_policy_hash"] == prompts.prompt_policy_hash()
    assert "torch" in config["environment"]
    assert config["suite_hashes"] == {"gsm8k": "a" * 64}


def test_config_records_both_models_and_every_benchmark():
    config = _sample_config()
    assert set(config["models"]) == {"base", "adapter"}
    assert set(config["benchmarks"]) == set(BENCHMARKS)


def test_freeze_writes_once_and_then_refuses_to_change(tmp_path):
    path = tmp_path / "frozen.json"
    digest = cfg.freeze(path, _sample_config())
    assert path.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["config_sha256"] == digest
    # Freezing the identical configuration again is a no-op, not an error.
    assert cfg.freeze(path, _sample_config()) == digest


def test_freeze_refuses_a_different_configuration(tmp_path):
    path = tmp_path / "frozen.json"
    cfg.freeze(path, _sample_config())
    with pytest.raises(cfg.ConfigError, match="refusing to overwrite"):
        cfg.freeze(path, _sample_config(experimental_variable="changed"))


def test_load_frozen_detects_drift(tmp_path):
    path = tmp_path / "frozen.json"
    cfg.freeze(path, _sample_config())
    assert cfg.load_frozen(path)["config_sha256"]
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["decoding_primary"]["do_sample"] = True
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="drifted"):
        cfg.load_frozen(path)


def test_load_frozen_requires_a_recorded_digest(tmp_path):
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps({"schema_version": "x"}), encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="no config_sha256"):
        cfg.load_frozen(path)


def test_load_frozen_rejects_a_missing_file(tmp_path):
    with pytest.raises(cfg.ConfigError, match="no frozen configuration"):
        cfg.load_frozen(tmp_path / "absent.json")


def test_kind_of_benchmark_is_the_policy_selector():
    assert kind_of(mcq()) == "multiple_choice"
    assert kind_of(item()) == "numeric"
