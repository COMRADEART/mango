import json, sys
from pathlib import Path
ROOT = Path(r"C:/Users/allam/Documents/new/model-t21r11-clean-seal")
sys.path.insert(0, str(ROOT / "scripts"))
import t21r13_uniqueness as u13
reg = json.loads((ROOT / "evaluations/t21r14/prior_exclusion.json").read_text(encoding="utf-8"))
rem = json.loads((ROOT / "evaluations/t21r14/remediation_exclusion.json").read_text(encoding="utf-8"))
fp13 = set()
for m, block in reg["milestones"].items():
    fp13 |= set(block["dimensions"]["exact_answers"]["fingerprints"])
remfp = set(rem["dimensions"]["exact_answers"]["fingerprints"])
forbidden = fp13 | remfp
years = [str(y) for y in range(1000, 2200)]
clear = [y for y in years if u13._fingerprint("exact_answers", y) not in forbidden]
# find a 64-run of consecutive clear years
best = None
run = []
for y in clear:
    if run and int(y) == int(run[-1]) + 1:
        run.append(y)
    else:
        run = [y]
    if len(run) >= 64 and best is None:
        best = run[:64]
print(json.dumps({"clear_band": best[:1] + ["..."] + best[-1:], "band_start": best[0], "band_end": best[-1]}, indent=2))
