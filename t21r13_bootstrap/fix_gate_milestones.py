from pathlib import Path
import re
p = Path('scripts/t21r13_construction_gate.py')
t = p.read_text(encoding='utf-8')
t2, n = re.subn(
    r'(add\("L5_exclusion", "historical_milestones",\s*\n\s*context\.get\("historical_milestones"\), )12(,[\s\n]*context\.get\("historical_milestones"\) == )12\)',
    r'\g<1>13\g<2>13)',
    t,
    count=1,
)
print('replacements', n)
if n != 1:
    raise SystemExit('replace failed')
p.write_text(t2, encoding='utf-8', newline='\n')
print('ok')
