from pathlib import Path
import json
import re

CONSTRUCTION_TOKEN = "T21R12_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
SEAL_TOKEN = "T21R12_BLIND_SEAL_AUTHORIZED"
SCRIPTS = Path("scripts")
OUT = Path("evaluations/t21r12")

def adapt(src_name, dst_name):
    text = (SCRIPTS / src_name).read_text(encoding="utf-8")
    for a, b in [
        ("T21R11", "T21R12"),
        ("t21r11", "t21r12"),
        ("r11b", "r12b"),
        ("R11", "R12"),
        ("mango-r11b-v1", "mango-r12b-v1"),
        ("mango-t21r11-", "mango-t21r12-"),
        ("gk_holdout_t21r11", "gk_holdout_t21r12"),
        ("pre11q-", "pre12q-"),
    ]:
        text = text.replace(a, b)
    text = text.replace("T21R12_BLIND_CONSTRUCTION_AUTHORIZED", CONSTRUCTION_TOKEN)
    text = re.sub(
        r'AUTHORIZATION_PHRASE = "[^"]+"',
        'AUTHORIZATION_PHRASE = "%s"' % CONSTRUCTION_TOKEN,
        text,
        count=1,
    )
    (SCRIPTS / dst_name).write_text(text, encoding="utf-8", newline="\n")
    print("wrote", dst_name)

for src, dst in [
    ("t21r11_run_eval.py", "t21r12_run_eval.py"),
    ("t21r11_official_eval.py", "t21r12_official_eval.py"),
    ("t21r11_preconstruction.py", "t21r12_preconstruction.py"),
    ("t21r11_spec_author.py", "t21r12_spec_author.py"),
]:
    adapt(src, dst)

r11 = Path("evaluations/t21r11/remediation_provenance.json")
r12 = OUT / "remediation_provenance.json"
if not r12.exists():
    if r11.exists():
        raw = r11.read_text(encoding="utf-8")
        raw = raw.replace("T21R11", "T21R12").replace("t21r11", "t21r12")
        data = json.loads(raw)
        data["artifact"] = "T21R12_REMEDIATION_PROVENANCE"
        r12.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print("wrote remediation_provenance from R11")
    else:
        excl = json.loads((OUT / "remediation_exclusion.json").read_text(encoding="utf-8"))
        data = {
            "artifact": "T21R12_REMEDIATION_PROVENANCE",
            "version": "t21r12-v1",
            "source": "OPEN_REMEDIATION_MATERIAL",
            "notes": "Provenance mirror for freeze binding",
            "remediation_exclusion_keys": sorted(excl.keys())[:40],
        }
        r12.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print("wrote minimal remediation_provenance")
else:
    print("remediation_provenance already present")

freeze = SCRIPTS / "t21r12_freeze_holdout.py"
ft = freeze.read_text(encoding="utf-8")
ft = ft.replace('SCHEMA_VERSION = "t21r11-seal-v1"', 'SCHEMA_VERSION = "t21r12-seal-v1"')
if "t21r12_blind_author.py" not in ft:
    ft = ft.replace(
        '"t21r12_spec_author.py",',
        '"t21r12_spec_author.py", "t21r12_blind_author.py", '
        '"t21r12_exact_design_lib.py", "t21r12_fixtures.py",',
    )
for extra in [
    "exact_design_schema.json",
    "exact_design_tag_vocabulary.json",
    "contract_gate_coverage.json",
    "test_failure_adjudication.json",
    "current_test_applicability.json",
    "real_blind_construction_readiness.json",
    "T21R11_CLOSURE.json",
]:
    token = '"%s"' % extra
    if token not in ft:
        ft = ft.replace(
            '"evaluator_freeze.json",',
            '"evaluator_freeze.json",\n    %s,' % token,
        )
freeze.write_text(ft, encoding="utf-8", newline="\n")
print("freeze inputs updated")
