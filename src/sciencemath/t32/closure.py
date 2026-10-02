"""Build the T32 receipt and evidence report from completed measurements."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path('.')
PACK = ROOT / 'evaluations/t32'
NAMES = {'A': 't32-A-math-restore', 'B': 't32-B-task-balanced', 'C': 't32-C-conservative'}
BENCHES = {'gsm8k': 1319, 'math500': 500, 'arc_easy': 2376, 'arc_challenge': 1172, 'sciq': 1000}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def regression(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    failures = {f"{t.get('classname')}::{t.get('name')}":
                '\n'.join((e.text or '') for e in t if e.tag in ('failure', 'error'))
                for t in cases if any(e.tag in ('failure', 'error') for e in t)}
    skipped = sum(any(e.tag == 'skipped' for e in t) for t in cases)
    return {'tests': len(cases), 'passed': len(cases) - len(failures) - skipped,
            'failed_or_error': len(failures), 'skipped': skipped, 'failures': failures}


def main():
    selection = read(PACK / 'development/T32_PHASE8_SELECTION.json')
    label = selection['selected']
    if set(selection['candidates']) != {'t32-A', 't32-B', 't32-C'} or any(c.get('missing') for c in selection['candidates'].values()):
        raise ValueError('All three candidate development evaluations are required')
    paired = read(PACK / 'paired/T32_PAIRED_ANALYSIS.json')
    preserved = read(PACK / 'manifests/T32_HANDOFF_PRESERVATION.json')
    drift = [p for p, expected in preserved['files'].items() if not Path(p).is_file() or sha(p) != expected]
    # Verify the original published T31 pack too, independent of handoff hashes.
    t31_root = ROOT / 'evaluations/t31'
    for line in (t31_root / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        path = t31_root / name
        if not path.is_file() or sha(path) != expected:
            drift.append(str(path))
    if drift:
        write(PACK / 'manifests/T32_FREEZE_DRIFT.json', {'changed': drift})
        raise ValueError(f'Frozen evidence drift: {drift}')

    receipts = {}
    for tag, name in NAMES.items():
        adapter = ROOT / 'training/adapters' / name
        manifest = read(adapter / 'training_manifest.json')
        summary = read(PACK / f'development/train_Mango-T32-{tag}-{name.split("-", 2)[2]}.json')
        receipts[tag] = {'manifest': manifest, 'run': summary, 'adapter_sha256': sha(adapter / 'adapter_model.safetensors'),
                         'mixture_manifest': read(ROOT / 'training/t32/candidates' / name / 'manifest.json')}
    write(PACK / 'manifests/T32_TRAINING_RECEIPT.json', {'candidates': receipts,
          'selected': label, 'hardware_host': platform.node(),
          'operational_history': (PACK / 'development/OPS_NOTES.md').read_text(),
          'training_command': 'PYTHONPATH=src python -u scripts/t32_chain.py',
          'selected_adapter_sha256': receipts[label[-1]]['adapter_sha256']})

    current = regression(PACK / 'development/regression_junit.xml')
    baseline = regression(ROOT / 'evaluations/t31/recovery/t31_measured_tests_junit.xml')
    old = set(baseline['failures'])
    existing = {k: v for k, v in current['failures'].items() if k in old}
    new = {k: v for k, v in current['failures'].items() if k not in old}
    reviewed = {}
    rerun_path = PACK / 'development/recovery_focused_junit.xml'
    if rerun_path.exists():
        rerun = regression(rerun_path)
        passed_ids = {f"{t.get('classname')}::{t.get('name')}" for t in ET.parse(rerun_path).getroot().iter('testcase')
                      if not any(e.tag in ('failure', 'error', 'skipped') for e in t)}
        for key in list(new):
            if key.startswith('tests.test_t31_concurrency::') and key in passed_ids and 'PermissionError' in new[key]:
                reviewed[key] = {'classification': 'Intermittent Windows atomic-file-replacement access failure; passed the focused rerun without source changes.',
                                 'original_failure': new.pop(key), 'rerun_artifact': str(rerun_path)}
    import_audit_path = PACK / 'development/isolated_import_audit_result.json'
    import_key = 'tests.test_t21_protocol_kernel::test_protocol_imports_are_side_effect_free'
    if import_key in new and import_audit_path.exists() and read(import_audit_path).get('status') == 'PASS':
        reviewed[import_key] = {'classification': 'Whole-workspace write-snapshot interference during active training. Isolated unchanged protocol and fixtures passed with zero writes.',
                                'original_failure': new.pop(import_key), 'rerun_artifact': str(import_audit_path)}
    reg = {**current, 'baseline_counts': {k: v for k, v in baseline.items() if k != 'failures'},
           'preexisting_failed_test_ids': list(existing), 'new_or_unclassified_failures': new,
           'reviewed_environment_or_concurrency_failures': reviewed,
           'classification_note': 'Matching test IDs are present in the frozen T31 closure run. Newly failing IDs require review; absence from that baseline does not alone prove T32 causation.',
           'command': 'PYTHONPATH=src python -m pytest --basetemp=tests/.pytest_tmp_t32_handoff --junitxml=evaluations/t32/development/regression_junit.xml'}
    write(PACK / 'reports/T32_REGRESSION_CLASSIFICATION.json', reg)

    table, identical = {}, {}
    for b, expected_n in BENCHES.items():
        pairs = paired['benchmarks'][b]
        bp, tp = pairs['base_vs_' + label], pairs['t30_vs_' + label]
        if bp['n_shared'] != expected_n or tp['n_shared'] != expected_n:
            raise ValueError(f'Incomplete final {b}')
        identical[b] = bool(bp.get('membership_and_prompts_identical')) and bool(tp.get('membership_and_prompts_identical'))
        table[b] = {'base': bp['accuracy_frozen'], 't30': tp['accuracy_frozen'], 't32': tp['accuracy_fresh'],
                    'delta_vs_t30_pp': tp['delta_pp'], 'delta_vs_base_pp': bp['delta_pp']}
    write(PACK / 'final/T32_FINAL_SCORES.json', table)
    math_ok = all(table[b]['delta_vs_t30_pp'] >= 5 for b in ('gsm8k', 'math500'))
    preserved_gains = {b: table[b]['t32'] - table[b]['base'] >= .5 * (table[b]['t30'] - table[b]['base']) for b in ('arc_easy', 'arc_challenge')}
    preserved_gains['sciq'] = table['sciq']['t32'] >= table['sciq']['base'] - .01
    gain_ok = all(preserved_gains.values())
    any_math = any(table[b]['delta_vs_t30_pp'] >= 5 for b in ('gsm8k', 'math500'))
    materially_worse = any(table[b]['delta_vs_t30_pp'] <= -5 for b in BENCHES)
    outcome = 'REMEDIATION_SUCCESS' if math_ok and gain_ok else 'TRADEOFF' if any_math else 'REGRESSION' if materially_worse else 'NO_EFFECT'
    # Predeclared token mapping (directive "Status: PASS / PARTIAL / FAIL";
    # DEV_PROTOCOL §7): PASS iff BOTH math benchmarks >= +5.0 pp vs T30 AND
    # the preservation floor holds; PARTIAL iff material math restoration
    # stands without full success (tradeoffs reported as tradeoffs, never
    # averaged away and never graded up to PASS); FAIL otherwise (NO_EFFECT
    # or REGRESSION). The gate-failure cap below is the only PASS downgrade.
    status = ('PASS' if math_ok and gain_ok
              else 'PARTIAL' if any_math else 'FAIL')
    decision = 'MANGO_T32_MATH_REMEDIATION_' + status
    hypotheses = read(PACK / 'diagnostics/T32_PHASE2_HYPOTHESES.json')['hypotheses']
    contamination = read(ROOT / 'training/t32/pools/contamination_report.json')
    # Gate-15 evidence: every evidence file present and hashable at gate
    # time (the pack re-hash below covers the report and gate results too).
    hash_problems = []
    evidence = [p for p in PACK.rglob('*') if p.is_file()
                and p.name not in ('SHA256SUMS', 'T32_PACK_VERIFICATION.json',
                                   'chain_log.txt', 'chain_error.txt', 'closure_log.txt')]
    for name in NAMES.values():
        evidence += sorted(p for p in (ROOT / 'training/t32/candidates' / name).rglob('*') if p.is_file())
        evidence += sorted(p for p in (ROOT / 'training/adapters' / name).rglob('*') if p.is_file())
    for p in evidence:
        try:
            sha(p)
        except OSError as exc:
            hash_problems.append(f'{p}: {exc}')
    gates = {1: not drift, 2: len(hypotheses) >= 6,
             3: contamination.get('passed_after_remediation') is True,
             4: all(r['mixture_manifest'].get('train_sha256') for r in receipts.values()),
             5: len(receipts) == 3, 6: bool(selection.get('selection_rule_applied')),
             # Gates 7-12 are computed, not promised: each benchmark's fresh
             # arm must join the frozen rows completely and with identical
             # prompts (paired_table raises on any membership mismatch).
             7: identical.get('gsm8k', False), 8: identical.get('math500', False),
             9: identical.get('arc_easy', False), 10: identical.get('arc_challenge', False),
             11: identical.get('sciq', False),
             12: all(identical.values()) and len(identical) == len(BENCHES),
             13: all(r['manifest'].get('environment') for r in receipts.values()),
             14: not new, 15: not hash_problems}
    if not all(gates.values()) and status == 'PASS':
        status, decision = 'PARTIAL', 'MANGO_T32_MATH_REMEDIATION_PARTIAL'
    write(PACK / 'reports/T32_GATE_RESULTS.json', {'gates': {str(k): 'PASS' if v else 'FAIL' for k, v in gates.items()},
          'status': status, 'decision': decision, 'capability_outcome': outcome, 'preservation': preserved_gains})
    lines = ['# MANGO T32 MATH REGRESSION REMEDIATION REPORT', '', '## Status', '',
             f'{status} — {outcome}. `{decision}`', '', '## T31 baseline', '',
             'T31 remains closed. Base and T30 columns reuse its frozen model-only scored generations. T32 generations are fresh, with identical prompts, membership, budgets, decoder and scorer.', '',
             '## Root-cause analysis', '']
    for h, v in hypotheses.items():
        lines += [f'### {h}', '', str(v.get('verdict')), '',
                  str(v.get('detail') or v.get('evidence') or ''),
                  '', 'Evidence for: ' + json.dumps(v.get('for', []), ensure_ascii=False),
                  '', 'Evidence against: ' + json.dumps(v.get('against', []), ensure_ascii=False), '']
    lines += ['## Training changes', '',
              'A adds verified math to the frozen T30 corpus and uses two epochs. B adds task-conditional protocol and MC examples to A. C keeps the exact T30 corpus and three epochs, with learning rate reduced from 1e-4 to 3e-5. The same 1.7B base and LoRA architecture are used throughout.', '',
              'See `manifests/T32_TRAINING_RECEIPT.json` for exact configs, dataset counts, seeds, software, duration, quantization and weight hashes.', '',
              '## Candidate ablation', '', '| Candidate | GSM8K dev | Math dev | Math mean | MC dev | SciQ dev | Eligible |', '|---|---:|---:|---:|---:|---:|---|']
    for c, m in selection['candidates'].items():
        lines.append('| ' + c + ' | ' + ' | '.join(f'{100*m[k]:.2f}' for k in ('acc_gsm8k_dev', 'acc_math_dev', 'math_dev_mean', 'acc_mc_dev', 'acc_sciq_dev')) + f" | {m['eligible']} |")
    lines += ['', '## Candidate selection', '', f"`{label}`: {selection['selection_rule_applied']}. Eligibility and tie-break thresholds were declared before training in `development/DEV_PROTOCOL.md`.", '',
              '## Final model identities', '', json.dumps(read(PACK / 'manifests/T31_FREEZE_RECORD.json')['t31'], indent=2), '',
              f"T32 adapter SHA-256: `{receipts[label[-1]]['adapter_sha256']}`.", '',
              '## Final benchmark table', '', '| Benchmark | Base % | T30 % | T32 % | Δ vs T30 pp | Δ vs base pp |', '|---|---:|---:|---:|---:|---:|']
    for b, m in table.items():
        lines.append(f"| {b} | {m['base']*100:.2f} | {m['t30']*100:.2f} | {m['t32']*100:.2f} | {m['delta_vs_t30_pp']:+.2f} | {m['delta_vs_base_pp']:+.2f} |")
    review_path = PACK / 'reports/T32_QUALITATIVE_REVIEW.json'
    review_text = (json.dumps(read(review_path), indent=2, ensure_ascii=False)
                   if review_path.exists() else 'Qualitative review pending.')
    lines += ['', '## Paired analysis', '', 'Exact McNemar tests and paired-delta normal 95% intervals are recorded per benchmark in `paired/T32_PAIRED_ANALYSIS.json`. Intervals use the variance of per-item paired correctness differences; no scores are pooled.', '',
              '## Math restoration', '', f"GSM8K: {table['gsm8k']['delta_vs_t30_pp']:+.2f} pp. MATH-500: {table['math500']['delta_vs_t30_pp']:+.2f} pp. Both meet the +5 pp floor: {math_ok}.", '',
              '## Capability preservation', '', json.dumps(preserved_gains), '',
              '## Trace audit', '', f'`final/T32_TRACE_AUDIT_{label}.md` contains deterministic samples of T30-wrong/T32-right, T30-right/T32-wrong and base-right/T32-wrong for both math and ARC benchmarks.', '', review_text, '',
              '## Contamination audit', '', json.dumps(contamination, indent=2), '',
              '## Tests', '', reg['command'], '', f"{current['passed']} passed, {current['failed_or_error']} failures/errors, {current['skipped']} skipped.", '',
              '## Regression classification', '', f'{len(existing)} failed test IDs also failed in the T31 closure run; {len(reviewed)} were reviewed as environment/concurrency failures with passing isolated or focused checks; {len(new)} remain new or unclassified. Original failures are retained. Details: `reports/T32_REGRESSION_CLASSIFICATION.json`.', '',
              '## Artifacts', '', 'Diagnostics, development rows and selection, fresh final generations with scored fields, paired analysis, trace samples, frozen candidate manifests, training receipt, gate results and SHA256SUMS are retained. Final raw text is preserved on every scored row.', '',
              '## Known limitations', '',
              'The base/T30 arms reuse historical frozen generations rather than fresh runs. The development protocol omitted a model-generated schema-validity metric, so schema preservation is not established. Diagnostic hypotheses are observational and the explicit-derivation probe uses a selected failure set. Paired normal intervals are approximate. Training checkpoint interruptions and restart history are disclosed in the operational notes and receipt. Candidate B resumed model weights at step 500 with recreated optimizer, scheduler and RNG after interruption at step 574; its altered optimization history limits interpretation as a pure mixture ablation. Outcome-stratified trace samples have been reviewed; they are not prevalence estimates. Frozen endpoint scores do not validate intermediate reasoning, and sampled T30 gold-matching answers sometimes contain invalid derivations. Root-cause labels are observational interpretations rather than causal proof. The final focused concurrency check passed nine tests and failed two with Windows os.replace PermissionError in unchanged frozen state-index publication; see reports/T32_CONCURRENCY_REVIEW.json. These remain unresolved and the regression gate fails.', '',
              '## Gate results', '', '| Gate | Result |', '|---|---|']
    lines += [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in gates.items()]
    lines += ['', '## Decision', '', f'`{decision}`', '']
    report = PACK / 'reports/MANGO_T32_MATH_REGRESSION_REMEDIATION_REPORT.md'
    report.write_text('\n'.join(lines), encoding='utf-8')
    # Hash the evidence and external candidate files. Omit the live orchestration log.
    files = sorted(p for p in PACK.rglob('*') if p.is_file()
                   and p.name not in ('SHA256SUMS', 'T32_PACK_VERIFICATION.json', 'closure_log.txt')
                   and not p.name.startswith('chain_') and '__pycache__' not in p.parts)
    for name in NAMES.values():
        files += sorted(p for p in (ROOT / 'training/t32/candidates' / name).rglob('*') if p.is_file())
        files += sorted(p for p in (ROOT / 'training/adapters' / name).rglob('*') if p.is_file())
    sums = {p.as_posix(): sha(p) for p in files}
    (PACK / 'SHA256SUMS').write_text(''.join(f'{digest}  {p}\n' for p, digest in sums.items()), encoding='utf-8')
    problems = [p for p, digest in sums.items() if sha(p) != digest]
    write(PACK / 'manifests/T32_PACK_VERIFICATION.json', {'verified_files': len(sums), 'problems': problems, 'sums_ok': not problems, 'frozen_files_unchanged': True})
    print(decision, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
