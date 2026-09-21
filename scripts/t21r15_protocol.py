"""R15 entry point: configuration only; protocol behavior lives in t21_protocol."""
from __future__ import annotations

from t21_protocol.doctor import main


if __name__ == "__main__":
    raise SystemExit(main(["--experiment", "t21r15"]))
