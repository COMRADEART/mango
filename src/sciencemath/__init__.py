"""ScienceMath-v0.1: compact local math/science assistant.

Package layout:
  sciencemath.datasets   - schema, normalization, dedup, splits, leakage, licensing (T1)
  sciencemath.utils      - hardware detection, IO, logging (T0)
  sciencemath.training   - QLoRA training (T3)
  sciencemath.evaluation - base/tuned evaluation + math verifier (T2/T4)
  sciencemath.rag        - Wikipedia ingestion + retrieval (T5)
  sciencemath.tools      - calculator / SymPy tool layer (T4)
  sciencemath.inference  - local chat CLI engine (T6)
"""

__version__ = "0.1.0"

# Canonical dataset field names (single source of truth; see datasets/schema.py)
from sciencemath.datasets.schema import (  # noqa: E402,F401
    REQUIRED_FIELDS,
    OPTIONAL_FIELDS,
    ALL_FIELDS,
)

__all__ = ["__version__", "REQUIRED_FIELDS", "OPTIONAL_FIELDS", "ALL_FIELDS"]