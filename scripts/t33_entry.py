"""Read-only historical audit; writes evidence exclusively under T33."""
from pathlib import Path
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evaluations/t33/entry'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git(*args):
    p = subprocess.run(['git', *args], cwd=ROOT, capture_output=True)
    return p.returncode, p.stdout

def failures(path):
    tree = ET.parse(path)
    return {f"{t.get('classname')}::{t.get('name')}":
            (t.find('failure') if t.find('failure') is not None else t.find('error')).text
            for t in tree.iter('testcase')
            if t.find('failure') is not None or t.find('error') is not None}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    head = git('rev-parse', 'HEAD')[1].decode().strip()
    freeze = json.loads((ROOT/'evaluations/t32/manifests/T31_FREEZE_RECORD.json').read_text())
    selected = json.loads((ROOT/'evaluations/t32/final/T32_SELECTED_CANDIDATE_FREEZE.json').read_text())
    report = ROOT/'evaluations/t32/reports/MANGO_T32_MATH_REGRESSION_REMEDIATION_REPORT.md'
    receipt = ROOT/'evaluations/t32/manifests/T32_TRAINING_RECEIPT.json'
    paths = [p for root in ('evaluations/t31','evaluations/t32', 'src/sciencemath/comparability',
                           'src/sciencemath/t32', 'src/sciencemath/state_engine')
             for p in (ROOT/root).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'training/adapters/t32-A-math-restore/adapter_model.safetensors',
              ROOT/'configs/training.yaml', ROOT/'src/sciencemath/utils/io_utils.py']
    frozen = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    assert sha(paths[-3]) == selected['adapter_sha256']
    provenance = {
        't31_final_commit': freeze['t31']['final_commit'],
        't32_branch': 't32-math-remediation',
        't32_final_committed_tip': head,
        't32_final_commit': None,
        't32_final_commit_explanation': 'T32 closure is present as dirty/untracked evidence at this tip; no commit containing the final closure exists. The source snapshot and file hashes identify its actual final state.',
        't32_selected_candidate': selected['selected'],
        't32_adapter_sha256': selected['adapter_sha256'],
        't32_training_receipt_sha256': sha(receipt),
        't32_final_report_sha256': sha(report),
        'report_identity_explanation': 'The Final model identities block references the frozen T31 baseline. Its branch, final_commit and report_sha256 are T31 identities; the separately stated T32 adapter SHA is the T32 model identity.',
        'historical_outputs_modified': False,
    }
    (OUT/'PROVENANCE.json').write_text(json.dumps(provenance, indent=2)+'\n')
    (OUT/'FROZEN_FILES.json').write_text(json.dumps(frozen, indent=2)+'\n')
    (OUT/'entry_git_status.txt').write_bytes(git('status','--porcelain','--untracked-files=normal')[1])
    (OUT/'t32_source_diff.patch').write_bytes(git('diff','HEAD','--','src/sciencemath/t32','scripts/t32_chain.py')[1])
    baseline = failures(ROOT/'evaluations/t31/recovery/t31_measured_tests_junit.xml')
    classification = json.loads((ROOT/'evaluations/t32/reports/T32_REGRESSION_CLASSIFICATION.json').read_text())
    focus = list(classification['new_or_unclassified_failures']) + [
        'tests.test_t31_concurrency::test_readers_never_see_a_half_published_state',
        'tests.test_t31_concurrency::test_concurrent_transitions_are_all_durable']
    comparison = {}
    for test in focus:
        file = test.split('::')[0].replace('.', '/')+'.py'
        rc, old = git('show', freeze['t31']['final_commit']+':'+file)
        rc2, committed = git('show', head+':'+file)
        comparison[test] = {'failed_at_t31_closure': test in baseline,
                            't31_tracked_source_present': rc == 0,
                            't32_tracked_source_present': rc2 == 0,
                            'working_source_sha256': sha(ROOT/file),
                            't31_vs_t32_tracked_source_equal': old == committed if rc == rc2 == 0 else None,
                            'source_note': 'State Engine and tests were already untracked WIP at T33 entry; they are unrelated to T32 model changes.'}
    (OUT/'SOURCE_COMPARISON.json').write_text(json.dumps(comparison, indent=2)+'\n')
    print(json.dumps(provenance, indent=2))
    print('Entry test IDs:', '\n'.join(focus))

if __name__ == '__main__':
    main()
