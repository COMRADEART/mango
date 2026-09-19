from pathlib import Path
import re
p = Path("scripts/t21r12_official_eval.py")
text = p.read_text(encoding="utf-8")
old = '''    status = str(closure.get("status") or "")
    if status in {
        "CLOSED_INVALID_UNEVALUATED_HOLDOUT",
        "INVALID_UNEVALUATED_HOLDOUT",
    } or "INVALID_UNEVALUATED_HOLDOUT" in status:'''
new = '''    status = str(closure.get("status") or "")
    refuse_statuses = {
        "CLOSED_INVALID_UNEVALUATED_HOLDOUT",
        "INVALID_UNEVALUATED_HOLDOUT",
        "CLOSED_NON_PROMOTIONAL_CONSTRUCTION_INFRASTRUCTURE_FAILURE",
    }
    if (
        status in refuse_statuses
        or "INVALID_UNEVALUATED_HOLDOUT" in status
        or "CONSTRUCTION_INFRASTRUCTURE_FAILURE" in status
        or status.startswith("CLOSED_")
    ):'''
if old not in text:
    raise SystemExit("refuse block not found")
text = text.replace(old, new)
# Also update defect message to include NO_VALID_SEALED_HOLDOUT
text = text.replace(
    '"T21R12 holdout is CLOSED_INVALID_UNEVALUATED_HOLDOUT; "\n'
    '                "official evaluation is permanently refused"',
    '"NO_VALID_SEALED_HOLDOUT; "\n'
    '                f"T21R12 closure status={status}; official evaluation is permanently refused"',
)
p.write_text(text, encoding="utf-8", newline="\n")
print("refuse patched")
