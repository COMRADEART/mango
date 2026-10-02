"""Deterministic exact-arithmetic corpus, contrastive repair and dev freeze."""
from __future__ import annotations
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
import random
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
DATA = ROOT/'training/t33'
EVAL = ROOT/'evaluations/t33'
FAMILIES = ['arithmetic','fractions','percentages','ratios','rates','multi-step word problems',
            'linear equations','systems of equations','algebraic manipulation','sequences',
            'geometry','probability','counting','number theory','basic combinatorics','competition-style algebra']

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')

def rows(p):
    return [json.loads(l) for l in p.read_text(encoding='utf-8-sig').splitlines() if l.strip()]

def jsonl(p, records):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n' for r in records), encoding='utf-8')

def make(family, seed, difficulty):
    import math
    import sympy as s
    rng = random.Random(seed)
    a,b,c = rng.randint(5,35),rng.randint(2,9),rng.randint(2,8)
    steps=[]
    def add(expr, description):
        value=s.simplify(s.sympify(expr))
        assert value.is_number and value.is_finite
        steps.append({'expression':str(expr),'value':str(value),'description':description})
        return value
    if family == 'arithmetic':
        q=f'A stockroom has {a*b} units, receives {a*c} more, and dispatches {b*c}. How many units remain?'
        r=add(f'{a*b}+{a*c}', 'Update stock after arrival')
        r=add(f'{r}-{b*c}', 'Subtract the dispatched stock')
    elif family == 'fractions':
        q=f'A tank contains {a*b*c} liters. One third is removed, then one quarter of the remainder is removed. How many liters remain?'
        r=add(f'{a*b*c}*(1-Rational(1,3))','Retain two thirds after first removal')
        r=add(f'{r}*(1-Rational(1,4))','Remove one quarter of the updated remainder')
    elif family == 'percentages':
        q=f'An item costs {a*100} cents. Apply a {b*5}% discount, then {c}% tax to the discounted price. What is the final price in cents?'
        r=add(f'{a*100}*(1-Rational({b*5},100))','Compute discounted price')
        r=add(f'{r}*(1+Rational({c},100))','Tax applies to discounted price')
    elif family == 'ratios':
        q=f'Red and blue beads are in ratio {b}:{c}. There are {a*(b+c)} beads. Remove {a} red beads. How many red beads remain?'
        r=add(f'{a*(b+c)}/({b}+{c})','Find one ratio unit')
        r=add(f'{r}*{b}-{a}','Compute red beads and update after removal')
    elif family == 'rates':
        q=f'A rider travels {a*b} km at {a} km/h, rests for {c} hours, then travels {a*c} km at {a} km/h. What is total elapsed time in hours?'
        r=add(f'{a*b}/{a}','First travel duration')
        r=add(f'{r}+{c}+{a*c}/{a}','Retain rest and second travel duration')
    elif family == 'multi-step word problems':
        q=f'Ada has {a*b} tokens and Ben has {a*c}. Ada transfers {a} to Ben. Ben earns {b*c} more and spends {c}. How many more tokens does Ada have than Ben now?'
        x=add(f'{a*b}-{a}','Update Ada after transfer')
        y=add(f'{a*c}+{a}+{b*c}-{c}','Update Ben including transferred tokens')
        r=add(f'{x}-({y})','Compare final inventories')
    elif family == 'linear equations':
        q=f'Solve {b}x + {c} = {a*b+c}. Return x.'
        r=add(f'{a*b+c}-{c}','Remove the additive term')
        r=add(f'{r}/{b}','Divide by the coefficient')
        assert s.solve(s.Eq(b*s.Symbol('x')+c,a*b+c),s.Symbol('x')) == [r]
    elif family == 'systems of equations':
        q=f'Positive quantities x,y satisfy x+y={a+b} and {c}x+y={c*a+b}. Find x*y.'
        x=add(f'({c*a+b}-{a+b})/({c}-1)','Subtract equations and solve x')
        y=add(f'{a+b}-{x}','Recover y from retained sum')
        r=add(f'{x}*{y}','Compute requested product')
        assert s.solve([s.Symbol('x')+s.Symbol('y')-(a+b),c*s.Symbol('x')+s.Symbol('y')-(c*a+b)], [s.Symbol('x'),s.Symbol('y')]) == {s.Symbol('x'):x,s.Symbol('y'):y}
    elif family == 'algebraic manipulation':
        q=f'At x={a}, evaluate (x+{b})^2-x^2-{2*b}x+{c}.'
        r=add(f'({a}+{b})**2-{a}**2-{2*b}*{a}','Substitute into all terms')
        r=add(f'{r}+{c}','Retain the final additive term')
    elif family == 'sequences':
        q=f'An arithmetic sequence starts at {a}, increases by {b}, and has {c+5} terms. Find the sum.'
        last=add(f'{a}+({c+5}-1)*{b}','Compute last term from n-1 increments')
        r=add(f'Rational({c+5},2)*({a}+{last})','Use n times the average of endpoints')
        assert r == sum(a+i*b for i in range(c+5))
    elif family == 'geometry':
        q=f'A rectangle measures {a+b} by {b+c}. A square of side {b} is removed, and {c} such identical remaining panels are used. Find total area.'
        r=add(f'({a}+{b})*({b}+{c})-{b}**2','Subtract removed square from rectangle')
        r=add(f'{r}*{c}','Scale remaining area by panel count')
    elif family == 'probability':
        q=f'A bag has {a} red and {b+c} blue balls. Two balls are drawn without replacement. Find the probability both are red as an exact fraction.'
        first=add(f'Rational({a},{a+b+c})','First red probability')
        r=add(f'{first}*Rational({a-1},{a+b+c-1})','Update total and red count after first draw')
        assert r == s.Rational(math.comb(a,2),math.comb(a+b+c,2))
    elif family == 'counting':
        q=f'Among {a+b+c+15} students, {a+b} study art, {b+c} study music, and {b} study both. How many study neither?'
        union=add(f'{a+b}+{b+c}-{b}','Inclusion-exclusion subtracts overlap once')
        r=add(f'{a+b+c+15}-{union}','Subtract union from the whole population')
    elif family == 'number theory':
        q=f'Find the number of positive divisors of 2^{b} * 3^{c}, then exclude the divisor 1. How many remain?'
        r=add(f'({b}+1)*({c}+1)','Count independent exponent choices including zero')
        r=add(f'{r}-1','Remove the specified divisor')
        assert r == s.divisor_count(2**b*3**c)-1
    elif family == 'basic combinatorics':
        q=f'Choose a committee of 3 from {b+4} people, with a specified person required. Then choose its chair from the committee. Count outcomes.'
        r=add(f'binomial({b+3},2)','Choose the two remaining members')
        r=add(f'{r}*3','Each committee has three distinct chair choices')
        assert r == math.comb(b+3,2)*3
    else:
        q=f'Positive real roots x,y have x+y={a+b} and xy={a*b}. Find x^3+y^3.'
        cube=add(f'({a}+{b})**3','Cube the retained sum')
        correction=add(f'3*{a*b}*({a}+{b})','Compute the mixed-term correction')
        r=add(f'{cube}-{correction}','Use the sum-of-cubes identity')
        assert r == a**3+b**3
    # Multi-constraint composition creates genuinely longer state dependencies.
    extra = {'short':0, 'medium':3, 'long':7}[difficulty]
    if extra:
        q+=' Call that result R. Apply these operations in order to R: '
        operations=[]
        for i in range(extra):
            op = ('add','multiply','subtract','divide')[i%4]
            n = rng.randint(2,11)
            symbol={'add':'+','multiply':'*','subtract':'-','divide':'/'}[op]
            operations.append(f'{op} {n}')
            r=add(f'({r}){symbol}{n}',f'Update the current result: {op} {n}')
        q+=', then '.join(operations)+'. Return the final result as an exact number or fraction.'
    check={'expression':str(r), 'value':str(r), 'description':'Verify all preceding operations using exact arithmetic before extracting the endpoint'}
    identifier='t33-synth-'+hashlib.sha256(q.encode()).hexdigest()[:20]
    record={'id':identifier,'problem':q,'question':q,'task_family':family,'reasoning_mode':'derive',
            'verified_steps':steps,'final_answer':str(r),'answer':str(r),
            'verification_status':'EXACT_STEPS_AND_FINAL', 'difficulty':difficulty,
            'source':'t33-exact-generator-v1','license':'MIT',
            'provenance':{'seed':seed,'generator_sha256':sha(__file__), 'independent_verifier':'SymPy exact simplification; family-specific solver/count identity when applicable'},
            'verification_check':check}
    verify(record)
    return record

def verify(record):
    import sympy as s
    for step in record['verified_steps']:
        assert s.simplify(s.sympify(step['expression'])-s.sympify(step['value'])) == 0
    assert s.simplify(s.sympify(record['verified_steps'][-1]['value'])-s.sympify(record['final_answer'])) == 0

def target(r):
    body='\n'.join(f"{i+1}. {p['description']}: {p['expression'].replace('**','^')} = {p['value']}" for i,p in enumerate(r['verified_steps']))
    body+='\nCheck: each state uses the previous updated value; exact operations agree with the requested endpoint.'
    return body+'\nFinal answer: \\boxed{'+r['final_answer']+'}'

def contamination(records, references, label):
    # Complete inverted-index search: no pair cap and no rare-shingle heuristic.
    from sciencemath.datasets.dedup import shingles, jaccard
    from sciencemath.datasets.normalize import text_fingerprint
    sets=[shingles(r['question']) for r in references]
    inv=defaultdict(set)
    fps=defaultdict(list)
    for i,(r,ss) in enumerate(zip(references,sets)):
        fps[text_fingerprint(r['question'])].append(i)
        for gram in ss: inv[gram].add(i)
    kept,removed=[],[]
    for r in records:
        ss=shingles(r['question']); candidates=set()
        direct=fps.get(text_fingerprint(r['question']),[])
        for gram in ss: candidates.update(inv.get(gram,()))
        hit=[]
        for i in candidates:
            if min(len(ss),len(sets[i])) < .90*max(len(ss),len(sets[i])): continue
            similarity=jaccard(ss,sets[i])
            if similarity>=.90: hit.append({'reference_id':references[i]['id'],'similarity':similarity})
        r['fingerprint']=text_fingerprint(r['question'])
        if direct or hit: removed.append({'record':r,'direct':direct,'near':hit})
        else: kept.append(r)
    jsonl(DATA/'removed'/f'{label}.jsonl',removed)
    return kept, {'input_count':len(records),'kept':len(kept),'removed':len(removed),
                  'policy':'normalized fingerprint; complete character-4-gram Jaccard >=0.90; no search cap; all references searched',
                  'reference_count':len(references)}

def main():
    if (EVAL/'PROTOCOL.json').exists():
        raise SystemExit('Refusing to overwrite frozen T33 protocol/data')
    finalrefs=[]
    for b in ('gsm8k','math500','arc_easy','arc_challenge','sciq'):
        finalrefs += [{'id':r['item_id'],'question':r['question']} for r in rows(ROOT/f'evaluations/t31/scored/base/{b}.jsonl')]
    dev=[]
    for name,file,n in [('gsm-style','dev_gsm8k',96),('competition-style','dev_math',96),
                        ('ARC-style MC','dev_arc_easy',64),('ARC-Challenge-style MC','dev_arc_challenge',64),('SciQ-style MC','dev_sciq',96)]:
        suite=sorted(rows(ROOT/f'training/t32/dev_sets/{file}.jsonl'),key=lambda r:r['item_id'])[:n]
        for r in suite: r['suite']=name
        dev+=suite
    for di in ('short','medium','long'):
        for i in range(48):
            r=make(FAMILIES[i%16],900000+i+{'short':0,'medium':1000,'long':2000}[di],di)
            dev.append({'item_id':r['id'],'benchmark':'math500','split':'t33dev','native_id':None,
                        'question':r['question'],'choices':[],'gold':r['final_answer'],'gold_label':None,
                        'subject':r['task_family'],'level':di,'provenance':r['provenance'],
                        'verified_steps':r['verified_steps'],'suite':'math-'+di})
    dev,devcheck=contamination([{**r,'id':r['item_id']} for r in dev],finalrefs,'development_vs_final')
    assert len(dev)==560, 'Development membership must be complete and clean'
    jsonl(DATA/'development.jsonl',dev)
    devrefs=[{'id':r['item_id'],'question':r['question']} for r in dev]
    # Exclude the complete original T32 dev sets, not just the selected subsets.
    for p in (ROOT/'training/t32/dev_sets').glob('dev_*.jsonl'):
        devrefs += [{'id':r['item_id'],'question':r['question']} for r in rows(p)]
    mathrecords=[]
    for f in FAMILIES:
        for i in range(72):
            di=('short','medium','long')[i%3]
            r=make(f,330000+FAMILIES.index(f)*10000+i,di)
            r['curriculum_stage']={'short':'A','medium':'B','long':'C'}[di]
            mathrecords.append(r)
    mathrecords,mathcheck=contamination(mathrecords,finalrefs+devrefs,'math')
    patterns=['forgotten_transfer','running_total','dropped_additive_term','incorrect_substitution',
              'incorrect_count_after_setup','premature_answer','restarted_reasoning']
    repairs=[]
    for index,pattern in enumerate(patterns):
        for i in range(32):
            f=['multi-step word problems','fractions','linear equations','systems of equations',
               'number theory','rates','percentages'][index]
            seed=600000+index*10000+i
            r=make(f,seed,'medium')
            r['id']+='-repair'; r['problem']=r['question']
            # Wrong endpoints are independently rejected, never supervised as correct.
            import sympy as s
            rng=random.Random(seed)
            a,b,c=rng.randint(5,35),rng.randint(2,9),rng.randint(2,8)
            bad_expr=[f'({a*b}-{a})-({a*c}+{b*c}-{c})',
                      f'{a*b*c}*(1-Rational(1,3))-{a*b*c}*Rational(1,4)',
                      f'Rational({a*b+c},{b})',
                      f'{a}*({a+b}-{c}*{a})',
                      f'{b}*{c}-1',
                      r['verified_steps'][0]['expression'],
                      r['verified_steps'][0]['expression']][index]
            badstate=s.simplify(s.sympify(bad_expr))
            badlines=[f'{bad_expr} = {badstate}']
            # Isolate the named core error: carry its wrong state through ALL
            # subsequent score operations instead of adding premature closure.
            if index not in (5,6):
                core_count=len(r['verified_steps'])-3
                for step in r['verified_steps'][core_count:]:
                    original_previous=r['verified_steps'][r['verified_steps'].index(step)-1]['value']
                    expression=step['expression']
                    assert expression.startswith('('+original_previous+')')
                    faulty='('+str(badstate)+')'+expression[len('('+original_previous+')'):]
                    badstate=s.simplify(s.sympify(faulty))
                    badlines.append(f'{faulty} = {badstate}')
            elif index==6:
                # Deliberate restart: apply the last operation to the first
                # subtotal rather than the current state, after showing work.
                badlines=[p['expression']+' = '+p['value'] for p in r['verified_steps'][:-1]]
                last=r['verified_steps'][-1]
                previous=r['verified_steps'][-2]['value']
                faulty='('+r['verified_steps'][0]['value']+')'+last['expression'][len('('+previous+')'):]
                badstate=s.simplify(s.sympify(faulty))
                badlines.append('Restart from the first subtotal: '+faulty+' = '+str(badstate))
            bad=str(badstate)
            explanation=['The transfer must be subtracted from Ada AND added to Ben.',
                         'The second removal acts on the updated remainder, not the initial quantity.',
                         'Subtract the constant before dividing by the coefficient.',
                         'Use y=(x+y)-x in the first equation; do not substitute the second equation coefficient into that relation.',
                         'Exponent choices include zero; count b+1 and c+1 choices independently.',
                         'The proposal stops before the remaining requested operations.',
                         'The proposal restarts from the first subtotal; retain all subsequent updates.'][index]
            if s.sympify(bad)==s.sympify(r['final_answer']):
                continue
            r['contrastive_pair']={'failure_category':pattern,'bad_reasoning':
                '\n'.join(badlines)+f'\nFinal answer: {bad}',
                'bad_final_answer':bad,'corrected_reasoning':target(r),
                'error_explanation':explanation,
                'bad_verified_incorrect':bool(s.sympify(bad)!=s.sympify(r['final_answer']))}
            r['question']=r['problem']+'\nA proposed solution ('+pattern+') is:\n'+r['contrastive_pair']['bad_reasoning']+'\nIdentify and repair the error. Give the complete corrected derivation.'
            r['curriculum_stage']='B'; repairs.append(r)
    repairs,repaircheck=contamination(repairs,finalrefs+devrefs,'repairs')
    # Legitimate SciQ training records already carried by T32, recast answer-only.
    direct=[]
    for r in rows(ROOT/'training/t32/candidates/t32-B-task-balanced/train.jsonl'):
        if r['source']!='t32-mc-sciq-v1': continue
        direct.append({**r,'problem':r['question'],'task_family':'science MC','reasoning_mode':'direct',
                       'verified_steps':[],'final_answer':r['answer'],'verification_status':'SOURCE_GOLD_LABEL',
                       'difficulty':'bounded','provenance':{'source_file':'training/t32/candidates/t32-B-task-balanced/train.jsonl','source_record_id':r['id']},'curriculum_stage':'D'})
    direct,directcheck=contamination(direct,finalrefs+devrefs,'direct')
    assert len(mathrecords)>=1000 and len(repairs)>=200 and len(direct)>=200
    jsonl(DATA/'verified_math.jsonl',mathrecords)
    jsonl(DATA/'contrastive_repairs.jsonl',repairs)
    jsonl(DATA/'direct_science.jsonl',direct)
    common=mathrecords+repairs
    for r in common:
        r['target_response']=(r.get('contrastive_pair',{}).get('error_explanation','')+'\n'+target(r)).strip()
    # Stage D repeats the SAME verified medium/long derivations alongside MC.
    dmath=sorted([r for r in mathrecords if r['difficulty']!='short'],key=lambda r:r['id'])[:len(direct)]
    configs={}
    for tag in 'ABC':
        staged=[]
        for stage in 'ABC':
            part=sorted([r for r in common if r['curriculum_stage']==stage],key=lambda r:r['id'])
            random.Random(42).shuffle(part)
            staged+=part
        dm=[{**r,'id':r['id']+'-D','curriculum_stage':'D'} for r in dmath]
        if tag=='A': staged+=dm
        else:
            for m,d in zip(dm,sorted(direct,key=lambda r:r['id'])): staged += [m,d]
        rendered=[]
        for r in staged:
            rr=dict(r)
            if r['reasoning_mode']=='direct':
                rr['question']=r['question']+'\nAnswer directly with the single correct option letter. Do not provide a derivation.'
                rr['target_response']=r['final_answer']
            elif tag!='A':
                rr['question']=r['question']+'\nShow a concise explicit derivation: retain the premises, update each intermediate state, verify the result, then give the final answer.'
            rendered.append(rr)
        path=DATA/f'candidates/{tag}/train.jsonl'; jsonl(path,rendered)
        configs[tag]={'records':len(rendered),'train_sha256':sha(path),'learning_rate':3e-5 if tag=='C' else 1e-4,
                      'effective_epochs':1, 'seed':42,'sequence_length':2048,
                      'curriculum':dict(Counter(r['curriculum_stage'] for r in rendered)),
                      'lora':{'r':32,'alpha':64,'dropout':.05,'modules':['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj']},
                      'starting_adapter':'training/adapters/t32-A-math-restore','starting_adapter_sha256':sha(ROOT/'training/adapters/t32-A-math-restore/adapter_model.safetensors'),
                      'batch_size':1,'gradient_accumulation':16,'optimizer':'adamw_torch','scheduler':'cosine','warmup_ratio':.03,'quantization':'NF4 double quantization','precision':'bfloat16',
                      'sampling':'sequential frozen curriculum; randomized within each stage with seed 42; optimizer/scheduler uninterrupted across stages'}
    protocol={'experiment':'T33 verified derivation + output-mode decoupling',
              'development_sha256':sha(DATA/'development.jsonl'),'development_suites':dict(Counter(r['suite'] for r in dev)),
              'eligibility':{'gsm-style_delta_vs_t32_A_pp':5.0,'competition-style_delta_vs_t32_A_pp':5.0,
                             'math-short_delta_vs_t32_A_pp':0.0,'math-long_delta_vs_t32_A_pp':0.0,
                             'short_long_comparison':'strictly greater','ARC-style MC_floor_vs_t32_A_pp':-2.0,
                             'ARC-Challenge-style MC_floor_vs_t32_A_pp':-2.0,'SciQ-style MC_floor_vs_t32_A_pp':-2.0,
                             'format_invalid_max_fraction':.05,'contamination_required':True,'t33_attributable_regressions':0},
              'selection':'Eligible candidates: maximize min(gsm delta,competition delta), then math-long accuracy, then lower invalid fraction, then A/B/C order. If none eligible, select exactly one diagnostic candidate by the same order over all three and record INELIGIBLE; cannot earn PASS.',
              'candidates':configs,
              'differences':{'A':'Derivation and correction only; natural prompts; no direct science replay.',
                             'B':'Identical mathematical derivations/corrections plus 300 or fewer re-gated direct science records, explicit task instructions, interleaved Stage D. Extra MC rows increase steps; disclosed data-treatment consequence.',
                             'C':'Exact B data, order, steps and settings; ONLY learning rate 1e-4 -> 3e-5.'},
              'final_floor':{'gsm8k_min_t30_delta_pp':5,'math500_min_t30_delta_pp':5,
                             'both_strictly_exceed_t32':True,'arc_easy_vs_t30_min_pp':-2,'arc_challenge_vs_t30_min_pp':-2,'sciq_vs_t30_min_pp':-2},
              'resume_policy':'Never reconstruct optimizer/scheduler/RNG for an equivalent run. An incomplete attempt is invalid; preserve and restart entire candidate from T32-A under identical frozen recipe.',
              'feasibility_policy':'Run isolated 3 optimizer-step longest-example GPU test at 2048 before full training. Fail closed on any target/premise shortening or clipping. No CPU-only substitute.',
              'validation_policy':'One deterministic curriculum pass; no early stopping or loss-based candidate tuning. Candidate selection exclusively frozen dev metrics.'}
    write(EVAL/'CONTAMINATION.json',{'development':devcheck,'math':mathcheck,'repairs':repaircheck,'direct':directcheck,
                                     'final_reference_count':len(finalrefs),'passed':True,
                                     'reference_hashes':{b:sha(ROOT/f'evaluations/t31/scored/base/{b}.jsonl') for b in ('gsm8k','math500','arc_easy','arc_challenge','sciq')}})
    write(EVAL/'PROTOCOL.json',protocol)
    print(json.dumps({'math':len(mathrecords),'repairs':len(repairs),'direct':len(direct),'development':len(dev),'candidates':{t:c['records'] for t,c in configs.items()}},indent=2))

if __name__=='__main__': main()
