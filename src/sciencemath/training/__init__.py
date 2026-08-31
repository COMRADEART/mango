"""QLoRA training (T3 — not implemented yet).

Planned public surface: build_trainer(cfg, hw_report), train(), save_adapter()
writing to training/adapters/sciencemath-v0.1/ with a full training manifest.
"""
__all__: list[str] = []

_NOT_IMPLEMENTED = (
    "sciencemath.training is planned for milestone T3 (QLoRA). "
    "This import is a placeholder so the package layout exists."
)


def __getattr__(name):
    raise ImportError(_NOT_IMPLEMENTED)