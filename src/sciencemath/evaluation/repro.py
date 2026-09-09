"""T8S.16 - reproducibility metadata for evaluation manifests.

T8 closure noted that some historical runs record null model revisions.
Historical artifacts are never rewritten. For FUTURE evaluations, manifests
must fail loudly when required reproducibility metadata is missing.

Required metadata (recorded per run):
  model_id              exact HF model id actually loaded
  model_revision        exact snapshot/commit of the weights actually used
  tokenizer_revision    snapshot/commit of the tokenizer actually used
  local_config_hash     sha256 over the model config actually loaded
  generation_config_hash canonical sha256 over the decoding profile
  code_git_commit       git commit of the evaluation code
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REQUIRED_REPRO_FIELDS = (
    "model_id", "model_revision", "tokenizer_revision",
    "local_config_hash", "generation_config_hash", "code_git_commit",
)


class ReproducibilityError(RuntimeError):
    """Raised when a manifest would be written without required
    reproducibility metadata. Fail loudly, never silently.
"""


def validate_reproducibility_metadata(meta: dict, *,
                                      require_revision: bool = True) -> list[str]:
    """Return [] when all required fields are present and non-empty,
    otherwise the list of missing fields. With require_revision=True the
    revision fields are mandatory as well."""
    missing = []
    for field in REQUIRED_REPRO_FIELDS:
        if field in ("model_revision", "tokenizer_revision") \
                and not require_revision:
            continue
        value = meta.get(field)
        if value is None or (isinstance(value, str)
                             and not value.strip()) \
                or str(value).startswith("unresolved"):
            missing.append(field)
    return missing


def assert_reproducible(meta: dict, *, require_revision: bool = True) -> None:
    missing = validate_reproducibility_metadata(
        meta, require_revision=require_revision)
    if missing:
        raise ReproducibilityError(
            "missing required reproducibility metadata: "
            + ", ".join(missing))


def _hf_snapshot_dir(model_id: str) -> Path | None:
    """Local HF cache snapshot dir for model_id (offline, exact for the
    weights that load_model_safely resolves through the cache)."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    repo_dir = hub / ("models--" + model_id.replace("/", "--"))
    ref = repo_dir / "refs" / "main"
    if not ref.exists():
        return None
    commit = ref.read_text(encoding="utf-8").strip()
    snap = repo_dir / "snapshots" / commit
    if snap.is_dir():
        return snap
    return None


def resolve_revision(model_id: str) -> str | None:
    """Exact revision of the weights that a local load resolves to:
    1. the local HF cache snapshot commit (offline-exact),
    2. the HF API sha (network, best-effort).
    Returns None only if neither is available."""
    snap = _hf_snapshot_dir(model_id)
    if snap is not None:
        return snap.name
    try:
        from huggingface_hub import HfApi
        return HfApi().model_info(model_id).sha
    except Exception:  # noqa: BLE001
        return None


def local_config_hash(model_id: str) -> str | None:
    """sha256 of the config.json that the local cache actually loads."""
    snap = _hf_snapshot_dir(model_id)
    if snap is None:
        return None
    cfg = snap / "config.json"
    if not cfg.exists():
        return None
    return hashlib.sha256(cfg.read_bytes()).hexdigest()


def canonical_hash(obj: dict) -> str:
    """Stable sha256 over a canonical JSON serialization."""
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def generation_config_hash(generation: dict) -> str:
    return canonical_hash(dict(generation))


def code_git_commit(repo: Path | None = None) -> str | None:
    repo = repo or Path.cwd()
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                             capture_output=True, text=True,
                             timeout=10).stdout.strip()
        return out or None
    except Exception:  # noqa: BLE001
        return None


def enrich_manifest(manifest: dict, *, model_id: str,
                    generation: dict | None = None,
                    tokenizer_id: str | None = None,
                    repo: Path | None = None,
                    require_revision: bool = True) -> dict:
    """Fill required reproducibility fields into a manifest copy and
    validate. Raises ReproducibilityError when a required field still
    cannot be resolved (future runs fail loudly instead of recording
    null revisions). Existing values are never overwritten."""
    out = dict(manifest)
    out.setdefault("model_id", model_id)
    out.setdefault("model_revision", resolve_revision(model_id))
    out.setdefault("tokenizer_revision",
                   resolve_revision(tokenizer_id or model_id))
    out.setdefault("local_config_hash", local_config_hash(model_id))
    out.setdefault("generation_config_hash",
                   generation_config_hash(generation or {}))
    out.setdefault("code_git_commit", code_git_commit(repo))
    assert_reproducible(out, require_revision=require_revision)
    return out
