from pathlib import Path
import re
p = Path("scripts/t21r13_fixtures.py")
text = p.read_text(encoding="utf-8")
# Find the module-level build section starting at Prior exclusion comment
marker = "# Prior exclusion + R11 fingerprints"
idx = text.find(marker)
if idx < 0:
    # try R13 variant
    marker = "# Prior exclusion"
    idx = text.find(marker)
if idx < 0:
    raise SystemExit("marker not found")
# Ensure functions remain at module level; wrap from marker to EOF
head = text[:idx].rstrip() + "\n\n"
body = text[idx:]
if "if __name__" in body:
    print("already gated")
else:
    indented = "\n".join(
        ("    " + line if line.strip() else line) for line in body.splitlines()
    )
    text2 = head + "if __name__ == \"__main__\":\n" + indented + "\n"
    p.write_text(text2, encoding="utf-8", newline="\n")
    print("wrapped", idx)
# verify import no longer writes
print("done")
