"""Read-only source forensics; writes investigation records only. No model execution."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from safetensors import safe_open

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evaluations/t9'
OLD = ROOT / 'sciencemath'
def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''): h.update(b)
    return h.hexdigest()
def stamp(t): return datetime.fromtimestamp(t, timezone.utc).isoformat()
def info(p):
    s = p.stat()
    return dict(path=str(p.resolve()), bytes=s.st_size, sha256=sha(p), creation_time_utc=stamp(s.st_birthtime), modification_time_utc=stamp(s.st_mtime), access_time_utc=stamp(s.st_atime))
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def write(name,d): (OUT/name).write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8')
def tensors(p):
    with safe_open(str(p),framework='numpy') as f:
        inv=[dict(name=k,shape=list(f.get_slice(k).get_shape()),dtype=f.get_slice(k).get_dtype()) for k in sorted(f.keys())]
    canonical='\n'.join(x['name']+' | '+json.dumps(x['shape'],separators=(',',':'))+' | '+x['dtype'] for x in inv)+'\n'
    return dict(tensor_count=len(inv),tensor_inventory=inv,tensor_inventory_sha256=hashlib.sha256(canonical.encode()).hexdigest(),canonicalization='UTF-8, sorted names, name | compact JSON shape | safetensors dtype, LF after every row')

def main():
    manifest=read(ROOT/'training/adapters/sciencemath-v0.1-t3/training_manifest.json')
    cp=OLD/'training/checkpoints/sciencemath-v0.1-t3/checkpoint-300'
    state=read(cp/'trainer_state.json')
    finalstate=read(cp.parent/'checkpoint-546/trainer_state.json')
    inventory=dict(path=str(cp),files=[info(p) for p in sorted(cp.iterdir()) if p.is_file()],adapter_config=read(cp/'adapter_config.json'),trainer_state=state,
        state_presence={n:(cp/n).exists() for n in ['optimizer.pt','scheduler.pt','rng_state.pth','training_args.bin']},
        validation=dict(global_step_matches=state['global_step']==300,epoch_matches=abs(state['epoch']-1.649466804265566)<1e-12,eval_loss_matches=state['best_metric']==manifest['results']['best_eval_loss'],max_steps_matches=state['max_steps']==546,log_history_is_manifest_prefix=state['log_history']==manifest['loss_history'][:len(state['log_history'])],final_state_selects_300=finalstate['best_global_step']==300,final_step=finalstate['global_step']),
        caution='Timestamps are secondary evidence; pickle-based states inventoried and hashed but not unpickled.')
    write('checkpoint300_inventory.json',inventory)
    candidates=[]
    for p in sorted(ROOT.rglob('adapter_model.safetensors')):
        if '.git' in p.parts: continue
        d=info(p)
        d['t3_path_candidate']='sciencemath-v0.1-t3' in p.parts
        if d['t3_path_candidate']:
            d.update(tensors(p)); d['adapter_config']=read(p.parent/'adapter_config.json')
        else: d['rejection']='Different run/path (smoke, curriculum, or T8); not a T3 production candidate'
        candidates.append(d)
    a=OLD/'training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors'
    b=cp/'adapter_model.safetensors'
    comparison=[]
    with safe_open(str(a),framework='numpy') as fa,safe_open(str(b),framework='numpy') as fb:
        assert sorted(fa.keys())==sorted(fb.keys())
        for k in sorted(fa.keys()):
            x,y=fa.get_tensor(k),fb.get_tensor(k)
            comparison.append(dict(name=k,shape_equal=x.shape==y.shape,dtype_equal=x.dtype==y.dtype,exact_elementwise_equal=bool(np.array_equal(x,y)),bit_identical=x.tobytes()==y.tobytes(),max_absolute_difference=float(np.max(np.abs(x-y))),differing_elements=int(np.count_nonzero(x!=y))))
    write('t3_tensor_comparison.json',dict(paths=[str(a),str(b)],byte_identical=sha(a)==sha(b),all_tensors_bit_identical=all(x['bit_identical'] for x in comparison),tensors=comparison))
    checks={k:dict(expected=v,actual=sha(OLD/manifest['dataset']['dir']/k)) for k,v in manifest['dataset']['checksums'].items()}
    write('t3_provenance_candidates.json',dict(recorded_at=datetime.now(timezone.utc).isoformat(),candidates=candidates,primary_manifest=info(ROOT/'training/adapters/sciencemath-v0.1-t3/training_manifest.json'),dataset_hash_checks=checks,classification='PROBABLE_RECOVERY',independence='Final adapter and checkpoint are separate surviving files in the same mutable original workspace. No separately archived chain of custody established by this script.'))
    # Search relevant project text; record matching line references without bulk transcript content.
    hits=[]
    pattern=re.compile(r'sha256|SHA-256|adapter_model|safetensors|checkpoint-300|ScienceMath-v0.1-T3|best checkpoint|0\.8474348783493042',re.I)
    for base in [OLD,ROOT/'train_lora',ROOT/'training',ROOT/'evaluations']:
        for directory,dirs,files in os.walk(base):
            dirs[:]=[d for d in dirs if d not in ['.git','.venv','node_modules','__pycache__','t9']]
            for name in files:
                p=Path(directory)/name
                if p.suffix.lower() not in ['.json','.jsonl','.md','.txt','.log','.yaml']: continue
                if p.stat().st_size>30000000: continue
                lines=p.read_text(encoding='utf-8-sig',errors='replace').splitlines()
                matches=[i+1 for i,l in enumerate(lines) if pattern.search(l)]
                if matches:
                    hits.append(dict(**info(p),matching_lines=matches,contains_candidate_digest=any('f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668' in l for l in lines)))
    write('t3_text_log_search.json',dict(pattern=pattern.pattern,files=hits,warning='New hashes in this report are not historical digests.'))
    print(json.dumps(dict(candidate=tensors(a)['tensor_inventory_sha256'],checkpoint_validation=inventory['validation'],candidate_count=len(candidates),text_files=len(hits)),indent=2))

if __name__=='__main__': main()
