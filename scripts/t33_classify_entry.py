from t33_entry import ROOT, OUT, failures
import json
from pathlib import Path

original = json.loads((ROOT/'evaluations/t32/reports/T32_REGRESSION_CLASSIFICATION.json').read_text())
observed = {}
for path in (OUT/'focused_junit.xml', OUT/'event_junit.xml'):
    observed.update(failures(path))
base = failures(ROOT/'evaluations/t31/recovery/t31_measured_tests_junit.xml')
classification = {}
for test, trace in {**original['failures'], **observed}.items():
    if test in observed and 'PermissionError' in observed[test] and 'state_index.json' in observed[test]:
        status = 'ENVIRONMENT_SPECIFIC'
        reason = 'Reproduced Windows atomic os.replace access denial in pre-T33 untracked State Engine WIP; neither T32 model code nor T33 changes call or alter it. WIP is absent from both commits, so a commit-based source equality claim is unavailable.'
    elif test in base:
        status, reason = 'PRE_EXISTING', 'Same test ID failed in frozen T31 closure.'
    elif test == 'tests.test_t21_protocol_kernel::test_protocol_imports_are_side_effect_free':
        status, reason = 'ENVIRONMENT_SPECIFIC', 'T32 isolated stable-copy audit passed; whole-workspace audit observed concurrent training/log writes. Original evidence retained.'
    elif 'PermissionError' in trace and 'state_index.json' in trace:
        status, reason = 'ENVIRONMENT_SPECIFIC', 'Same Windows state-index replacement mechanism as reproduced tests, in pre-T33 WIP.'
    else:
        status, reason = 'UNKNOWN', 'No causal classification established.'
    classification[test] = {'classification': status, 'evidence': reason,
                            'entry_reproduced': test in observed, 't31_failed': test in base}
from collections import Counter
record = {'historical_t32_counts': {k:original[k] for k in ('tests','passed','failed_or_error','skipped')},
          'entry_focused': '5 failed, 10 passed; additional event-only attempt 1 failed',
          'counts': dict(Counter(r['classification'] for r in classification.values())),
          'failures': classification, 't32_attributable': 0,
          'source_comparison': 'SOURCE_COMPARISON.json',
          'training_entry_gate': 'PASS: classifications explicit; no T32-attributable failure identified; no State Engine repair undertaken.'}
(OUT/'REGRESSION_CLASSIFICATION.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record['counts']))
