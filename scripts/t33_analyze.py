"""Four-state final scores, exact paired statistics and deterministic trace pack."""
from collections import defaultdict
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from t33_build import rows,sha,write
from t33_evaluate import BENCHMARKS
from sciencemath.t32.paired import correct_map,paired_table
from t33_train import check_frozen

def main():
    check_frozen()
    selected=json.loads((ROOT/'evaluations/t33/SELECTION.json').read_text())['selected']
    allmaps={};scores={};paired={};samples=[]
    for b in BENCHMARKS:
        maps={'base':correct_map(ROOT/f'evaluations/t31/scored/base/{b}.jsonl'),
              't30':correct_map(ROOT/f'evaluations/t31/scored/adapter/{b}.jsonl'),
              't32':correct_map(ROOT/f'evaluations/t32/final/t32-A/{b}.jsonl'),
              't33':correct_map(ROOT/f'evaluations/t33/final/{selected}/{b}.jsonl')}
        assert all(set(m)==set(maps['base']) for m in maps.values())
        allmaps[b]=maps; n=len(maps['base'])
        scores[b]={'n':n,**{label:sum(r['content_valid'] is True for r in m.values())/n for label,m in maps.items()}}
        scores[b].update({f'delta_vs_{label}_pp':100*(scores[b]['t33']-scores[b][label]) for label in ('base','t30','t32')})
        paired[b]={label+'_vs_t33':paired_table(label,'t33',b,maps[label],maps['t33']) for label in ('base','t30','t32')}
        if b=='sciq':continue
        groups={'t32_wrong_t33_right':lambda i:not maps['t32'][i]['content_valid'] and maps['t33'][i]['content_valid'],
                't32_right_t33_wrong':lambda i:maps['t32'][i]['content_valid'] and not maps['t33'][i]['content_valid'],
                'base_right_t33_wrong':lambda i:maps['base'][i]['content_valid'] and not maps['t33'][i]['content_valid']}
        if b.startswith('arc'):
            groups={'ARC_preserved':lambda i:maps['t32'][i]['content_valid'] and maps['t33'][i]['content_valid'],
                    'ARC_regressed':lambda i:maps['t32'][i]['content_valid'] and not maps['t33'][i]['content_valid']}
        for group,predicate in groups.items():
            ids=[i for i in sorted(maps['base']) if predicate(i)]
            for iid in ids[:2]:
                samples.append({'group':group,'benchmark':b,'item_id':iid,'question':maps['base'][iid]['question'],
                                'gold':maps['base'][iid].get('gold'),
                                'population':len(ids),'arms':{a:{k:m[iid].get(k) for k in ('raw_generation','finish_reason','content_valid','extracted_answer','output_tokens')} for a,m in maps.items()}})
    devrows=rows(ROOT/f'evaluations/t33/development/{selected}/development.jsonl')
    devitems={r['item_id']:r for r in rows(ROOT/'training/t33/development.jsonl')}
    for correct in (True,False):
        rr=sorted([r for r in devrows if r['suite']=='math-long' and r['content_valid'] is correct],key=lambda r:r['item_id'])
        for r in rr[:2]:
            samples.append({'group':'long_math_success' if correct else 'long_math_failure','benchmark':'math-long','item_id':r['item_id'],
                            'question':devitems[r['item_id']]['question'],'gold':devitems[r['item_id']]['gold'],
                            'population':len(rr),'arms':{'t33':r},'verified_steps':devitems[r['item_id']]['verified_steps']})
    write(ROOT/'evaluations/t33/FINAL_SCORES.json',scores)
    write(ROOT/'evaluations/t33/PAIRED_ANALYSIS.json',paired)
    write(ROOT/'evaluations/t33/TRACE_SAMPLES.json',{'sampling':'Lexicographically smallest two item IDs per nonempty outcome group, after selected adapter frozen; final tests not used for selection.',
                                                  'samples':samples,'limitations':'Outcome-stratified qualitative observations; not representative error prevalence.'})
    lines=['# T33 deterministic trace audit samples','']
    for r in samples:
        lines.extend([f"## {r['benchmark']} / {r['group']} / {r['item_id']}",'',r['question'],'',f"Gold: {r['gold']}",''])
        for a,g in r['arms'].items():lines.extend([f"### {a}: correct={g['content_valid']}, finish={g['finish_reason']}",'',g['raw_generation'],''])
    (ROOT/'evaluations/t33/TRACE_SAMPLES.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(scores,indent=2))

if __name__=='__main__':main()
