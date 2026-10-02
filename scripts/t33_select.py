"""Execute the previously frozen rule once; lock the selected adapter."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from t33_build import sha,write
from t33_train import check_frozen

def main():
    check_frozen()
    protocol=json.loads((ROOT/'evaluations/t33/PROTOCOL.json').read_text())
    dev=ROOT/'evaluations/t33/development'
    anchor=json.loads((dev/'t32-A_metrics.json').read_text())['suites']
    assert json.loads((ROOT/'evaluations/t33/DATA_VERIFICATION.json').read_text())['status']=='PASS'
    import xml.etree.ElementTree as ET
    units=ET.parse(ROOT/'evaluations/t33/entry/t33_unit_junit_v2.xml')
    assert not list(units.iter('failure')) and not list(units.iter('error'))
    candidates={}
    for tag in 'ABC':
        label='t33-'+tag; rec=json.loads((dev/f'{label}_metrics.json').read_text()); suites=rec['suites']
        assert rec['membership_sha256']==protocol['development_sha256'] and rec['protocol_sha256']==sha(ROOT/'evaluations/t33/PROTOCOL.json')
        delta={s:100*(m['accuracy']-anchor[s]['accuracy']) for s,m in suites.items()}
        checks={'gsm_material':delta['gsm-style']>=5-1e-9,'competition_material':delta['competition-style']>=5-1e-9,
                'short_improves':delta['math-short']>0,'long_improves':delta['math-long']>0,
                'arc_easy_preserved':delta['ARC-style MC']>=-2-1e-9,
                'arc_challenge_preserved':delta['ARC-Challenge-style MC']>=-2-1e-9,
                'sciq_preserved':delta['SciQ-style MC']>=-2-1e-9,
                'format':all(m['invalid_output_fraction']<=.05 for m in suites.values()),
                'contamination':True,'t33_regressions':True}
        invalid=sum(m['n']*m['invalid_output_fraction'] for m in suites.values())/sum(m['n'] for m in suites.values())
        candidates[label]={'eligible':all(checks.values()),'checks':checks,'deltas_pp':delta,
                           'ranking':[min(delta['gsm-style'],delta['competition-style']),suites['math-long']['accuracy'],-invalid,-ord(tag)]}
    pool=[k for k,r in candidates.items() if r['eligible']] or list(candidates)
    selected=max(pool,key=lambda k:candidates[k]['ranking'])
    record={'selected':selected,'selected_eligible':candidates[selected]['eligible'],
            'selection_type':'ELIGIBLE' if candidates[selected]['eligible'] else 'DIAGNOSTIC_INELIGIBLE_FALLBACK',
            'protocol_sha256':sha(ROOT/'evaluations/t33/PROTOCOL.json'),'candidates':candidates,
            'final_results_used_for_selection':False}
    path=ROOT/'evaluations/t33/SELECTION.json'
    if path.exists(): assert json.loads(path.read_text())==record
    else: write(path,record)
    files=[Path('evaluations/t33/PROTOCOL.json'),Path('evaluations/t33/SELECTION.json'),
           Path('training/t33/development.jsonl'),Path('evaluations/t33/CONTAMINATION.json'),
           Path('evaluations/t33/DATA_VERIFICATION.json'),Path('evaluations/t31/config/t31_frozen_config.json')]
    files += [p.relative_to(ROOT) for p in (ROOT/'scripts').glob('t33_*.py')]
    files += [Path(f'evaluations/t33/development/{label}_metrics.json') for label in ('t32-A','t33-A','t33-B','t33-C')]
    files += [Path(f'evaluations/t33/development/train_{tag}.json') for tag in 'ABC']
    files += [Path(f'training/t33/candidates/{tag}/train.jsonl') for tag in 'ABC']
    manifest=Path(f'training/adapters/{selected}/training_manifest.json'); files.append(manifest)
    freeze={'selected':selected,'adapter_sha256':sha(ROOT/f'training/adapters/{selected}/adapter_model.safetensors'),
            'files':{p.as_posix():sha(ROOT/p) for p in files}}
    path=ROOT/'evaluations/t33/SELECTED_FREEZE.json'
    if path.exists(): assert json.loads(path.read_text())==freeze
    else: write(path,freeze)
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()
