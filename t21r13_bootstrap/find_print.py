from pathlib import Path
for p in Path("scripts").glob("t21r13*.py"):
    t = p.read_text(encoding="utf-8")
    if "prior milestones" in t:
        print("FOUND", p)
    if "unwired" in t:
        print("UNWIRED", p)

