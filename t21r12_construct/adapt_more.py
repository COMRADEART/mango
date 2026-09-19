from pathlib import Path
import re
CONSTRUCTION_TOKEN = "T21R12_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
SCRIPTS = Path("scripts")

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
    ("t21r11_static_semantics.py", "t21r12_static_semantics.py"),
    ("t21r11_static_gold_audit.py", "t21r12_static_gold_audit.py"),
    ("t21r11_retrieval_mirror.py", "t21r12_retrieval_mirror.py"),
]:
    adapt(src, dst)
