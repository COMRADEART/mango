"""Repeat the import-write audit in a stable copy, away from training logs."""
import json
import os
import shutil
import sys
from pathlib import Path

from t21_protocol.import_audit import dynamic_import_write_audit

root = Path.cwd()
target = root / 'evaluations/t32/development/isolated_import_audit'
target.mkdir(exist_ok=True)
shutil.copytree(root / 't21_protocol', target / 't21_protocol', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
(target / 'scripts').mkdir(exist_ok=True)
helpers = ('t21r_fixtures', 't21r12_fixtures', 't21r13_fixtures', 't21r14_fixtures')
for name in helpers:
    shutil.copy2(root / 'scripts' / f'{name}.py', target / 'scripts' / f'{name}.py')
for name in ('t21r12_exact_design_lib', 't21r13_exact_design_lib', 't21r14_exact_design_lib', 't21r11_uniqueness'):
    shutil.copy2(root / 'scripts' / f'{name}.py', target / 'scripts' / f'{name}.py')
for relative in ('evaluations/t21r11', 'evaluations/t21r12', 'evaluations/t21r13', 'evaluations/t21r14', 'rag/gk_holdout_t21r11'):
    source = root / relative
    if source.exists():
        shutil.copytree(source, target / relative, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.xml', '*log*'))
os.chdir(target)
modules = [f't21_protocol.{p.stem}' for p in sorted((target / 't21_protocol').glob('*.py'))
           if p.stem not in ('__init__', 'doctor')]
result = dynamic_import_write_audit(target, [*modules, *helpers])
result['scope'] = 'Isolated copy of unchanged protocol modules and helper scripts; excludes the actively changing training workspace.'
result['original_failure_mechanism'] = 'The full-workspace snapshot test can count concurrent training/log writes as import side effects.'
(root / 'evaluations/t32/development/isolated_import_audit_result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
sys.exit(0 if result['status'] == 'PASS' else 1)
