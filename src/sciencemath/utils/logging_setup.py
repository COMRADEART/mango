"""Structured run logging: console + rotating file, plus environment capture
so every experiment records hardware, CUDA, and package versions."""
from __future__ import annotations

import io
import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(log_dir: str | Path | None = None,
                  name: str = "sciencemath",
                  level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:            # idempotent
        return logger
    fmt = logging.Formatter(_FORMAT)
    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / f"{name}.log",
                                 maxBytes=5_000_000, backupCount=5,
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def log_environment(logger: logging.Logger) -> dict:
    """Log and return the environment fingerprint for reproducibility."""
    from sciencemath.utils.hardware import full_report

    hw = full_report()
    env = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "hardware": hw.to_dict(),
    }
    logger.info("environment: %s", env)
    return env


def capture_packages(known: list[str] | None = None) -> dict[str, str]:
    """Best-effort package version lookup; safe under import errors."""
    from importlib import metadata

    known = known or [
        "torch", "transformers", "peft", "accelerate", "bitsandbytes",
        "datasets", "numpy", "sympy", "faiss", "sentence-transformers", "pyyaml",
    ]
    versions: dict[str, str] = {}
    for pkg in known:
        try:
            versions[pkg] = metadata.version(pkg)
        except Exception:
            versions[pkg] = "not-installed"
    return versions


def redirect_output_warnings(stderr: io.TextIOBase | None = None) -> None:
    """Silence noisy transformers warnings at import time where safe."""
    import os
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")