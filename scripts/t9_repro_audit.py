"""Evidence-only T9 recovery audit; never substitutes weights or frozen hashes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evaluations/t9'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def run(*args):
    p = subprocess.run(args, cwd=ROOT, capture_output=True)
    return {'command': list(args), 'returncode': p.returncode,
            'stdout': p.stdout.decode('utf-8', errors='replace'),
            'stderr': p.stderr.decode('utf-8', errors='replace')}

def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')

def freeze():
    target = OUT / 'pre_repair_state.json'
    if target.exists():
        raise SystemExit('Existing freeze must not be overwritten')
    paths = set(OUT.rglob('*'))
    paths.update(ROOT.glob('src/sciencemath/**/*correction*.py'))
    paths.update([ROOT/'src/sciencemath/tools/router.py', ROOT/'src/sciencemath/evaluation/extraction.py', ROOT/'tests/test_t9_correction.py', ROOT/'scripts/run_t9_correction_eval.py'])
    state = {'recorded_at': datetime.now(timezone.utc).isoformat(),
             'commit': run('git','rev-parse','HEAD'), 'status': run('git','status','--porcelain=v1','--untracked-files=all'),
             'artifact_sha256': {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted(paths) if p.is_file()},
             'existing_metrics': {p.relative_to(ROOT).as_posix():json.loads(p.read_text()) for p in OUT.glob('runs/*/summary.json')}}
    state['firewall_tests'] = run(sys.executable,'-m','pytest','tests/test_t9_correction.py')
    save('pre_repair_state.json',state)
    print(json.dumps(state['firewall_tests']))

def provenance():
    import struct
    import unicodedata
    import xml.etree.ElementTree as ET
    old = ROOT/'sciencemath'
    rel = Path('training/curriculum/mango-sft-v2/level1/replay.jsonl')
    current, previous = (ROOT/rel).read_bytes(), (old/rel).read_bytes()
    git_bytes = subprocess.check_output(['git','show','HEAD:'+rel.as_posix()],cwd=ROOT)
    replay = {'expected_sha256':json.loads((ROOT/rel.parent/'checksums.json').read_text())['replay.jsonl'],
              'current_sha256':sha(current), 'previous_workspace_sha256':sha(previous), 'git_blob_sha256':sha(git_bytes),
              'current_lf_sha256':sha(current.replace(b'\r\n',b'\n')), 'current_crlf_sha256':sha(current.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')),
              'row_counts':[len(current.splitlines()),len(previous.splitlines())],
              'json_rows_equal_in_order':[json.loads(x) for x in current.splitlines()]==[json.loads(x) for x in previous.splitlines()],
              'equal_after_newline_normalization':current.replace(b'\r\n',b'\n')==previous.replace(b'\r\n',b'\n'),
              'final_newline':[current.endswith(b'\n'),previous.endswith(b'\n')],
              'unicode_nfc':[unicodedata.is_normalized('NFC',x.decode()) for x in (current,previous)]}
    save('replay_provenance.json',replay)
    rel = Path('training/adapters/sciencemath-v0.1-t3')
    candidates = []
    for p in [old/rel/'adapter_model.safetensors',*sorted((old/'training/checkpoints/sciencemath-v0.1-t3').glob('*/adapter_model.safetensors'))]:
        data = p.read_bytes()
        n = struct.unpack('<Q',data[:8])[0]
        header = json.loads(data[8:8+n])
        tensors = {k:v for k,v in header.items() if k!='__metadata__'}
        candidates.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha(data),'size':len(data),'tensor_count':len(tensors),'tensor_inventory':tensors})
    metadata = {}
    for name in ['training_manifest.json','reload_verification.json','adapter_config.json','loss_history.json']:
        a,b = (ROOT/rel/name).read_bytes(),(old/rel/name).read_bytes()
        metadata[name]={'current_sha256':sha(a),'old_sha256':sha(b),'json_equal':json.loads(a)==json.loads(b)}
    state=json.loads((old/'training/checkpoints/sciencemath-v0.1-t3/checkpoint-546/trainer_state.json').read_text())
    save('adapter_recovery.json',{'candidates':candidates,'metadata_comparison':metadata,'trainer_state':state,
          'historical_weight_sha256':None,'outcome':'PROBABLE_RECOVERY',
          'reason':'Original production-path weights and checkpoints recovered in prior workspace; historical cryptographic identity not yet established. No candidate copied or uploaded.'})
    collection=run(sys.executable,'-m','pytest','--collect-only','-o','addopts=','-q')
    ids=[x for x in collection['stdout'].splitlines() if x.startswith('tests/') and '::' in x]
    tree=ET.parse(old/'t8s_final_junit.xml')
    historical=[]
    for case in tree.findall('.//testcase'):
        cls=case.get('classname').split('.')
        parts=[]
        while cls and (cls[0]=='tests' or cls[0].startswith('test_')):
            parts.append(cls.pop(0))
        historical.append('/'.join(parts)+'.py::'+'::'.join(cls+[case.get('name')]))
    missing=sorted(set(historical)-set(ids))
    new=sorted(set(ids)-set(historical))
    save('test_inventory_reconciliation.json',{'historical_source':'sciencemath/t8s_final_junit.xml','historical_sha256':sha((old/'t8s_final_junit.xml').read_bytes()),
         'historical_suite_attributes':[x.attrib for x in tree.findall('.//testsuite')], 'historical_nodeids':historical,
         'current_collection':collection,'current_nodeids':ids,'missing_nodeids':missing,'new_nodeids':new,
         'test_file_diff':run('git','diff','--no-index','--stat','sciencemath/tests','tests')})
    print(json.dumps({'replay':replay,'candidate_hashes':[{k:v for k,v in c.items() if k!='tensor_inventory'} for c in candidates],
          'historical':len(historical),'current':len(ids),'missing':missing,'new':new},indent=2))

if __name__ == '__main__':
    provenance() if '--provenance' in sys.argv else freeze()
