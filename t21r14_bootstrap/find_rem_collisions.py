import json, sys
from pathlib import Path
ROOT = Path(r"C:/Users/allam/Documents/new/model-t21r11-clean-seal")
sys.path.insert(0, str(ROOT / "scripts"))
import t21r13_uniqueness as u13
import t21r14_blind_author as author14
rem = json.loads((ROOT / "evaluations/t21r14/remediation_exclusion.json").read_text(encoding="utf-8"))
remfp = set(rem["dimensions"]["exact_answers"]["fingerprints"])
world_spec, suites_spec = author14.build_specs()
values = set()
for row in suites_spec["rows"]:
    values.update((row.get("gold") or {}).get("expect_answer_contains") or [])
hits = sorted(v for v in values if u13._fingerprint("exact_answers", v) in remfp)
print(json.dumps({"remediation_colliding_answer_values": hits}, indent=2))
