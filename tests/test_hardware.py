"""Hardware detection tests — must pass with or without a GPU present."""
from sciencemath.utils.hardware import detect_hardware, recommend_settings


def test_detection_never_raises():
    report = detect_hardware()
    assert report.platform_name
    assert isinstance(report.cuda_available, bool)


def test_recommendations_cover_settings():
    report = detect_hardware()
    recs = recommend_settings(report)
    for key in ("device", "precision", "per_device_train_batch_size",
                "gradient_accumulation_steps", "max_seq_length"):
        assert key in recs, f"missing recommendation {key}"


def test_6gb_profile_is_conservative():
    """Simulate the target 6 GB GPU and verify conservative QLoRA settings."""
    report = detect_hardware()
    report.cuda_available = True
    report.total_vram_bytes = 6 * 1024 ** 3
    recs = recommend_settings(report)
    assert recs["can_train_qlora"] is True
    assert recs["load_in_4bit"] is True          # 4-bit quantization mandatory
    assert recs["max_model_params_b"] <= 4.0     # 4B ceiling per spec
    assert recs["per_device_train_batch_size"] <= 2


def test_cpu_only_profile_disables_training():
    report = detect_hardware()
    report.cuda_available = False
    report.total_vram_bytes = None
    recs = recommend_settings(report)
    assert recs["device"] == "cpu"
    assert recs["can_train_qlora"] is False


def test_small_vram_disables_training():
    report = detect_hardware()
    report.cuda_available = True
    report.total_vram_bytes = int(2.5 * 1024 ** 3)
    recs = recommend_settings(report)
    assert recs["can_train_qlora"] is False