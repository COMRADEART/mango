"""License manifest handling and deny-by-default training gating.

data/manifests/datasets.json holds one entry per dataset:
{
  "name": "gsm8k",
  "provider": "huggingface",            # huggingface | kaggle | other
  "reference": "https://huggingface.co/datasets/openai/gsm8k",
  "license": "MIT",
  "license_status": "APPROVED",          # APPROVED | REVIEW_REQUIRED | INCOMPATIBLE
  "license_verified": true,              # link to the actual text was read
  "allows_training_use": true,
  "redistribution_permitted": true,
  "eval_only": false,
  "checked_on": "2026-08-31",
  "notes": "..."
}

RULES (enforced by filter_for_training, not by convention):
  * status != APPROVED, verification false, or training use false
        -> record EXCLUDED from training, reason recorded
  * unknown source (not in manifest at all) -> EXCLUDED
  * eval_only entries can flow into test/validation, never into train.
No pipeline stage may bypass filter_for_training().
"""
from __future__ import annotations

from pathlib import Path

from sciencemath.utils.io_utils import load_json

STATUS_APPROVED = "APPROVED"
STATUS_REVIEW = "REVIEW_REQUIRED"
STATUS_INCOMPATIBLE = "INCOMPATIBLE"
VALID_STATUSES = {STATUS_APPROVED, STATUS_REVIEW, STATUS_INCOMPATIBLE}


def load_dataset_manifest(path: str | Path) -> list[dict]:
    entries = load_json(path)
    if isinstance(entries, dict):
        entries = entries.get("datasets", [])
    problems = []
    for e in entries:
        if e.get("license_status") not in VALID_STATUSES:
            problems.append(f"{e.get('name', '?')}: invalid license_status")
    if problems:
        raise ValueError("datasets.json malformed: " + "; ".join(problems))
    return entries


def manifest_by_name(entries: list[dict]) -> dict[str, dict]:
    return {e.get("name"): e for e in entries}


def license_decision(entry: dict | None) -> tuple[str, str]:
    """Return (decision, reason). Deny by default."""
    if entry is None:
        return "EXCLUDED", "source not present in datasets.json (deny-by-default)"
    if not entry.get("license_verified"):
        return "EXCLUDED", "license not verified (license_verified=false)"
    if entry.get("license_status") != STATUS_APPROVED:
        return "EXCLUDED", f"license_status={entry.get('license_status')}"
    if not entry.get("allows_training_use", False):
        return "EXCLUDED", "allows_training_use=false"
    # APPROVED but eval_only is fine for eval, excluded from training by caller.
    return "ALLOWED", ""


def filter_for_training(records: list[dict], manifest: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split records into (training_ok, excluded). Excluded records keep their
    data for evaluation use where entry.eval_only=true."""
    by_name = manifest_by_name(manifest)
    ok, excluded = [], []
    for rec in records:
        entry = by_name.get(rec.get("source", ""))
        decision, reason = license_decision(entry)
        if decision == "EXCLUDED":
            excluded.append({"id": rec.get("id"), "source": rec.get("source"),
                             "reason": reason,
                             "eval_only_source": bool(entry and entry.get("eval_only")),
                             "record": rec})
        else:
            ok.append(rec)
    return ok, excluded


def is_eval_only_source(source: str, manifest: list[dict]) -> bool:
    return bool(manifest_by_name(manifest).get(source, {}).get("eval_only", False))


def training_sources(manifest: list[dict]) -> set[str]:
    by_name = manifest_by_name(manifest)
    return {name for name, e in by_name.items()
            if license_decision(e)[0] == "ALLOWED" and not e.get("eval_only")}


def write_license_manifest_md(entries: list[dict], out_path: str | Path) -> str:
    lines = [
        "# Dataset License Manifest",
        "",
        "One row per dataset. `Decision` is enforced by "
        "`src/sciencemath/datasets/licenses.py` — the pipeline is deny-by-default.",
        "",
        "| Dataset | Provider | Reference | License | Verified | Training use | "
        "Redistribution | Eval only | Decision | Checked |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        decision, _ = license_decision(e)
        if e.get("eval_only") and decision == "ALLOWED":
            decision = "ALLOWED (eval only)"
        lines.append(
            f"| {e.get('name', '?')} | {e.get('provider', '?')} "
            f"| [{e.get('reference', '')}]({e.get('reference', '')}) "
            f"| {e.get('license', '?')} | {'yes' if e.get('license_verified') else 'no'} "
            f"| {'yes' if e.get('allows_training_use') else 'no'} "
            f"| {'yes' if e.get('redistribution_permitted') else 'no'} "
            f"| {'yes' if e.get('eval_only') else 'no'} "
            f"| {decision} | {e.get('checked_on', '')} |")
    lines += ["", "## Incompatible / unknown", ""]
    bad = [e for e in entries if license_decision(e)[0] == "EXCLUDED"]
    if not bad:
        lines.append("_None._")
    else:
        for e in bad:
            _decision, reason = license_decision(e)
            lines.append(f"- **{e.get('name', '?')}** (status="
                         f"{e.get('license_status')}): {reason}. "
                         f"Excluded from training by default.")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "\n".join(lines)