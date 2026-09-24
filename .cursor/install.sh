#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the Mango repository.
#
# Layers installed:
#   * core package  : numpy, PyYAML, sympy  (pip install -e .)
#   * dev tooling   : pytest
#   * ML stack (T2+): torch (CPU build), transformers, peft, accelerate, datasets
#   * RAG stack(T5+): faiss-cpu, sentence-transformers, rank_bm25
#
# Cloud Agent VMs are CPU-only, so torch is installed from the CPU wheel index
# (avoids the ~2.5GB CUDA download). GPU-based QLoRA training still targets the
# 6GB-VRAM machines described in the README (Kaggle/Colab/local RTX); it is not
# run here. The full test suite, dataset pipeline, and deterministic T4 tool
# layer all run without a GPU or network downloads.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# python3-venv provides ensurepip, which the stock image can lack.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-pip build-essential
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip

# Core runtime + dev tooling (declared in pyproject.toml).
pip install -e .
pip install pytest

# ML stack — CPU torch first so the CUDA wheel is never resolved.
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers peft accelerate datasets

# RAG stack.
pip install faiss-cpu sentence-transformers rank_bm25

echo "Mango environment ready. Activate with: source .venv/bin/activate"
