from pathlib import Path
p = Path("scripts/t21r12_blind_author.py")
t = p.read_text(encoding="utf-8")
old = 'row["construction_tags"] = ["relation_surface_sensitive"]'
new = 'row["construction_tags"] = ["meta:relation_surface_sensitive"]'
print("found", old in t, "count", t.count(old))
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
# also patch gen_r12_scripts transform
g = Path("t21r12_construct/gen_r12_scripts.py")
gt = g.read_text(encoding="utf-8")
insert = '''    src = src.replace(
        'row["construction_tags"] = ["relation_surface_sensitive"]',
        'row["construction_tags"] = ["meta:relation_surface_sensitive"]',
    )
'''
if insert.strip() not in gt:
    gt = gt.replace("    return src\n\n\ndef write_author", insert + "    return src\n\n\ndef write_author")
    g.write_text(gt, encoding="utf-8", newline="\n")
    print("gen patched")
else:
    print("gen already has patch")
print("done")
