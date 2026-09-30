"""T31.13 The evidence pack: what was written, and what it hashes to.

The brief asks for deterministic hashes over the evaluation config, the prompt
files, the scorer files, the raw results, the scored results and the summary
report, and for an environment manifest and a dependency record. This module
produces them and, as importantly, states what they are for: the brief is
explicit that hashes "authenticate the run" and are not to be "described as
proof of model capability". A matching digest says the bytes are the bytes that
produced the result; it says nothing about the result being good.

One convention is worth stating. ``SHA256SUMS`` covers every file under the
evidence root except itself, keyed by a POSIX-style path relative to that root,
sorted. That makes the file portable: a third party who copies the directory
can verify it without knowing where it sat on the machine that made it, and
adding a file to the pack changes the manifest rather than silently escaping
it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

from sciencemath.comparability.identity import MODEL_IDENTITIES
from sciencemath.comparability.rows import EVIDENCE_ROOT

CONFIG_DIR = "config"
REPORT_DIR = "reports"
MANIFEST_DIR = "manifests"
SOURCE_DIR = "source"

CONFIG_PATH_NAME = "t31_frozen_config.json"
ENVIRONMENT_NAME = "environment.json"
SUMS_NAME = "SHA256SUMS"
REPORT_NAME = "MANGO_T31_PUBLIC_COMPARABILITY_REPORT.md"
ANALYSIS_NAME = "analysis.json"
CONTAMINATION_NAME = "contamination.json"
HANDOFF_NAME = "t32_diagnostic_handoff.jsonl"
GATES_NAME = "gates.json"

#: The modules that decide what the numbers mean: the prompts both arms are
#: asked, the extractors that read answers out of the generations, the scorers
#: that judge them, the loaders that pin the item sets, and the configuration
#: and identities the whole thing hangs off. The brief requires the pack to
#: contain the prompt templates, the answer extractors and the scorers; they
#: are copied in verbatim rather than only hashed, so a reader can inspect the
#: code that produced a number without hunting a revision.
SOURCE_MODULES: Final = (
    "contract", "identity", "loaders", "prompts", "extractors", "scorers",
    "scoring", "rows", "runner", "config", "analysis", "contamination",
    "gates", "report", "manifest", "pipeline",
)


class ManifestError(RuntimeError):
    """The evidence pack is incomplete, or a recorded hash does not match."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ``base`` is the directory the evidence tree hangs off — the repository root
# in practice — because ``rows.raw_path`` already appends the
# ``evaluations/t31`` suffix. Passing the evidence root itself here would nest
# it a second time and write the pack somewhere nothing reads.
def evidence_root(base: Path | None = None) -> Path:
    return (base or Path(".")) / EVIDENCE_ROOT


def config_path(base: Path | None = None) -> Path:
    return evidence_root(base) / CONFIG_DIR / CONFIG_PATH_NAME


def environment_path(base: Path | None = None) -> Path:
    return evidence_root(base) / MANIFEST_DIR / ENVIRONMENT_NAME


def report_path(base: Path | None = None) -> Path:
    return evidence_root(base) / REPORT_DIR / REPORT_NAME


def analysis_path(base: Path | None = None) -> Path:
    return evidence_root(base) / ANALYSIS_NAME


def contamination_path(base: Path | None = None) -> Path:
    return evidence_root(base) / CONTAMINATION_NAME


def handoff_path(base: Path | None = None) -> Path:
    return evidence_root(base) / HANDOFF_NAME


def gates_path(base: Path | None = None) -> Path:
    return evidence_root(base) / GATES_NAME


def write_artifact(path: Path, artifact: str, payload: dict[str, Any]) -> Path:
    """Write a flat JSON artifact with the repo's schema envelope.

    ``schema_version`` and ``artifact`` are how every other evidence file in
    this repository identifies itself, so a reader can tell at a glance what a
    file is without opening its body.
    """
    from sciencemath.comparability.contract import SCHEMA_VERSION
    from sciencemath.utils.io_utils import write_json

    document = {"schema_version": SCHEMA_VERSION, "artifact": artifact,
                **payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, document, atomic=True)
    return path


def write_lines(path: Path, lines: Iterable[str]) -> Path:
    """Append-free write of a JSONL file: the file is replaced, never grown."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line.rstrip("\n") + "\n")
    temporary.replace(path)
    return path


def chat_template_sha256(tokenizer: Any) -> str:
    """Hash the chat template the prompts are rendered through.

    The chat template is part of the experimental setup as much as the decoding
    settings are — a template change alters what the model is asked, for both
    arms at once — so it is pinned by hash in the frozen configuration rather
    than left to be inferred from a tokenizer revision.
    """
    template = getattr(tokenizer, "chat_template", None)
    if not template:
        raise ManifestError(
            "the tokenizer carries no chat_template, so the rendered prompts "
            "cannot be pinned; refusing to freeze a configuration that does "
            "not record what the model was asked")
    return sha256_text(template)


def suite_hashes(items_by_benchmark: dict[str, Sequence[Any]]) -> dict[str, str]:
    """Per-benchmark hash of the evaluated items, from the loader's own rule."""
    from sciencemath.comparability.loaders import suite_hash

    return {name: suite_hash(list(items))
            for name, items in sorted(items_by_benchmark.items())}


def collect(base: Path | None = None) -> dict[str, str]:
    """Hash every file in the pack, keyed by relative POSIX path.

    ``SHA256SUMS`` is excluded from itself: a manifest that lists its own hash
    cannot be verified, since writing the line changes the file.
    """
    root = evidence_root(base)
    recorded: dict[str, str] = {}
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == SUMS_NAME:
                continue
            if path.suffix == ".tmp":
                continue
            recorded[path.relative_to(root).as_posix()] = sha256_file(path)
    return dict(sorted(recorded.items()))


def source_dir(base: Path | None = None) -> Path:
    return evidence_root(base) / SOURCE_DIR


def snapshot_sources(base: Path | None = None) -> dict[str, str]:
    """Copy the measurement source into the pack, verbatim, and hash it.

    Called before the manifest is written, so the copied modules are covered by
    ``SHA256SUMS`` like every other file in the pack. The copy is a byte-exact
    ``read_bytes``/``write_bytes`` so line endings survive. It records the code
    the pack was built from; the report separately records the commit, so a
    reader can confirm the two agree. Nothing *enforces* that the copied bytes
    are the running bytes — the point is that a repaired extractor or a
    re-rendered option list shows up in the pack instead of leaving the frozen
    configuration hash untouched.
    """
    import sciencemath.comparability as package

    source = Path(package.__file__).parent
    destination = source_dir(base)
    destination.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name in SOURCE_MODULES:
        path = source / f"{name}.py"
        if not path.is_file():                     # pragma: no cover
            continue
        target = destination / f"{name}.py"
        target.write_bytes(path.read_bytes())
        written[f"{SOURCE_DIR}/{name}.py"] = sha256_file(target)
    if not written:
        raise ManifestError(
            f"no source modules were found beside {source}; refusing to write "
            f"a pack that does not contain the code that produced its numbers")
    return written


def write_sums(base: Path | None = None) -> Path:
    """Write ``SHA256SUMS`` over the pack. Sorted, so two runs are diffable.

    Written with LF endings explicitly. The default translates ``\\n`` to
    ``os.linesep``, so on Windows the manifest came out CRLF and the standard
    ``sha256sum -c`` folded the trailing ``\\r`` into each filename, reporting
    every entry absent. The recorded digests are over file *bytes* and are
    unaffected; only the manifest's own line endings are pinned here.
    """
    root = evidence_root(base)
    recorded = collect(base)
    if not recorded:
        raise ManifestError(
            f"refusing to write an empty {SUMS_NAME}: a manifest over no "
            f"files authenticates nothing and reads like a complete pack")
    lines = [f"{digest}  {name}" for name, digest in recorded.items()]
    destination = root / SUMS_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8",
                         newline="\n")
    temporary.replace(destination)
    return destination


def verify_sums(base: Path | None = None) -> tuple[bool, list[str]]:
    """Re-verify the pack against its manifest. Returns (ok, problems)."""
    root = evidence_root(base)
    manifest = root / SUMS_NAME
    if not manifest.exists():
        raise ManifestError(f"no {SUMS_NAME} at {manifest}")
    problems: list[str] = []
    recorded: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        recorded[name.strip()] = digest.strip()

    for name, expected in sorted(recorded.items()):
        path = root / name
        if not path.is_file():
            problems.append(f"{name}: recorded but absent")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"{name}: {actual} != recorded {expected}")

    present = set(collect(base))
    for name in sorted(present - set(recorded)):
        problems.append(f"{name}: present but not in {SUMS_NAME}")
    return (not problems), problems


def environment_record() -> dict[str, Any]:
    """The environment manifest, plus the frozen model identities it belongs to."""
    from sciencemath.comparability.config import environment_manifest

    return {
        "environment": environment_manifest(),
        "models": MODEL_IDENTITIES,
        "note": (
            "Two runs on different library versions are not the same "
            "experiment even when every setting matches; this record is what "
            "makes that difference checkable."
        ),
    }


def dependency_record() -> dict[str, str]:
    """The installed versions of everything the pipeline imports."""
    record: dict[str, str] = {}
    for name in ("torch", "transformers", "datasets", "peft", "accelerate",
                 "sympy", "tokenizers", "safetensors", "huggingface_hub",
                 "numpy", "pytest"):
        try:
            module = __import__(name)
            record[name] = getattr(module, "__version__", "unknown")
        except ImportError:
            record[name] = "absent"
    return record


def read_json(path: Path) -> Any:
    if not path.exists():
        raise ManifestError(f"no artifact at {path}")
    return json.loads(path.read_text(encoding="utf-8"))
