"""Evaluation engine (T2).

Public surface:
  build_prompt          - standardized evaluation prompt (content, not template)
  apply_chat_template   - model-specific chat-template wrapping
  extract_answer        - MCQ / numeric / text answer extraction
  classify_failure      - deterministic failure taxonomy
  compute_metrics       - accuracy/latency/token metrics
  load_model_safely     - VRAM-safe model loading + smoke test
  evaluate_model        - resume-capable frozen-suite runner
"""
from sciencemath.evaluation.extraction import (  # noqa: F401
    extract_answer,
    strip_think_block,
    normalize_symbolic,
)
from sciencemath.evaluation.taxonomy import (  # noqa: F401
    classify_failure,
    is_refusal,
)
from sciencemath.evaluation.metrics import compute_metrics  # noqa: F401