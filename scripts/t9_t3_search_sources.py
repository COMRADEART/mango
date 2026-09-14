"""Bounded project provenance search; no unrelated transcript contents retained."""
import json, os, re
from pathlib import Path
from t9_t3_provenance import ROOT, OUT, info, write

pat=re.compile(r'checkpoint-300|0\.8474348783493042|f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668|(?:sha256|SHA-256).{0,100}(?:adapter|safetensors)',re.I)
records=[]
for dirname in ['sessions','archived_sessions']:
    for p in (Path.home()/'.codex'/dirname).rglob('*.jsonl'):
        with p.open(encoding='utf-8',errors='replace') as f:
            first=f.readline()
            try: meta=json.loads(first)
            except ValueError: continue
            cwd=meta.get('payload',{}).get('cwd','')
            if 'documents\\new\\model' not in cwd.lower().replace('/','\\'): continue
            matches=[]
            for i,line in enumerate(f,2):
                if not pat.search(line): continue
                try: d=json.loads(line)
                except ValueError: continue
                # Only retain references and matching literal terms, not tool payloads.
                matches.append(dict(line=i,timestamp=d.get('timestamp'),terms=sorted(set(m.group(0) for m in pat.finditer(line)))))
        if matches: records.append(dict(**info(p),session_cwd=cwd,matches=matches))
write('t3_codex_log_search.json',records)

roots=[Path('C:/Users/allam/Documents/new/model'),Path('C:/AI'),Path('G:/My Drive/project'),Path('G:/My Drive/ai_models'),Path('G:/My Drive/localai')]
found=[]; errors=[]
names={'adapter_model.safetensors','trainer_state.json','optimizer.pt','scheduler.pt','rng_state.pth','training_args.bin','adapter_config.json'}
for base in roots:
    hits=[]
    for directory,dirs,files in os.walk(base,onerror=lambda e:errors.append(str(e))):
        dirs[:]=[d for d in dirs if d not in ['.git','.venv','node_modules','__pycache__']]
        for name in files:
            if name in names or re.search(r'(mango|sciencemath|wsl|ubuntu|backup).*\.(zip|tar|gz|7z|vhdx)$',name,re.I): hits.append(str(Path(directory)/name))
    found.append(dict(root=str(base),exists=base.exists(),files=hits))
lfs=[]
for root in [ROOT,ROOT/'sciencemath']:
    store=root/'.git/lfs/objects'
    matches=[]
    for p in store.rglob('*'):
        if p.is_file() and (p.name=='f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668' or p.stat().st_size==139512976): matches.append(info(p))
    lfs.append(dict(store=str(store),exists=store.exists(),matching_objects=matches))
write('t3_search_scope.json',dict(project_roots=found,errors=errors,lfs=lfs,discovery=['C:/ drive top-level; user Documents/new workspace names; Desktop and Downloads project/archive names','G:/ and H:/ top-level; G:/Other computers/My Laptop/Documents and Desktop folder names','G:/My Drive/project/WSL-Backup exists but is empty','Ubuntu-24.04 /home /opt /srv /mnt/wsl project/backup directory discovery returned no matches; /mnt/c is the same Windows storage'],limitations=['No unrelated personal-folder recursive content scan','Offline/unmounted/deleted backups are unavailable','Cloud listings establish only currently exposed files; no provider revision-history access']))
print(json.dumps(dict(project_log_files=len(records),roots=len(found),errors=errors,lfs=lfs),indent=2))
