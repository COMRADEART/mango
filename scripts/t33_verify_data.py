"""Independent audit of original problem stems, steps, targets, and membership."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
from t33_build import rows,sha,write,verify,contamination
from sciencemath.training.sft_format import last_boxed

def main():
    refs=[]
    for b in ('gsm8k','math500','arc_easy','arc_challenge','sciq'):
        refs += [{'id':r['item_id'],'question':r['question']} for r in rows(ROOT/f'evaluations/t31/scored/base/{b}.jsonl')]
    canonical=[]; derivations=0; pairs=0
    for filename in ('verified_math','contrastive_repairs','direct_science'):
        rs=rows(ROOT/f'training/t33/{filename}.jsonl')
        for r in rs:
            q=r['problem'].split('\n\nA)')[0] if r['reasoning_mode']=='direct' else r['problem']
            canonical.append({**r,'question':q})
            if r['reasoning_mode']=='derive':
                verify(r); derivations+=1
                if 'contrastive_pair' in r:
                    import sympy as s
                    p=r['contrastive_pair']
                    assert s.simplify(s.sympify(p['bad_final_answer'])-s.sympify(r['final_answer']))!=0
                    assert last_boxed(p['corrected_reasoning'])==r['final_answer']; pairs+=1
    _,audit=contamination(canonical,refs,'canonical_problem_stems_vs_final')
    assert audit['removed']==0, 'Fail closed: original problem stem contaminates final set'
    protocols=json.loads((ROOT/'evaluations/t33/PROTOCOL.json').read_text())
    for tag in 'ABC':
        path=ROOT/f'training/t33/candidates/{tag}/train.jsonl'; assert sha(path)==protocols['candidates'][tag]['train_sha256']
        rr=rows(path)
        assert [r['curriculum_stage'] for r in rr]==sorted(r['curriculum_stage'] for r in rr)
        for r in rr:
            if r['reasoning_mode']=='derive': assert last_boxed(r['target_response'])==r['final_answer']
            else: assert r['target_response']==r['final_answer'] and r['final_answer'] in 'ABCD'
    b=rows(ROOT/'training/t33/candidates/B/train.jsonl'); c=rows(ROOT/'training/t33/candidates/C/train.jsonl')
    assert b==c
    a=rows(ROOT/'training/t33/candidates/A/train.jsonl')
    assert [(r['id'],r['target_response']) for r in a]==[(r['id'],r['target_response']) for r in b if r['reasoning_mode']=='derive']
    record={'status':'PASS','verified_derivations':derivations,'verified_contrastive_pairs':pairs,
            'canonical_problem_stem_contamination':audit,'B_C_data_byte_identical':sha(ROOT/'training/t33/candidates/B/train.jsonl')==sha(ROOT/'training/t33/candidates/C/train.jsonl'),
            'A_B_derivation_targets_identical':True,'ordered_curriculum':True}
    write(ROOT/'evaluations/t33/DATA_VERIFICATION.json',record); print(json.dumps(record,indent=2))

if __name__=='__main__': main()
