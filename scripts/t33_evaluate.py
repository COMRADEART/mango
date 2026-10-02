"""Frozen T31 measurement primitives, with T33-only storage and dev suites."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
from t33_build import rows,sha,write
from t33_train import check_frozen

BENCHMARKS=('gsm8k','math500','arc_easy','arc_challenge','sciq')
BUDGETS={'gsm8k':512,'math500':1024,'arc_easy':32,'arc_challenge':32,'sciq':32}

def expression_audit(text, expected_steps, extracted_answer=None):
    """Conservative numeric equations only; unparseable algebra is unmeasured."""
    from fractions import Fraction
    # An AST evaluator avoids evaluating model text as arbitrary Python/SymPy.
    import ast
    def evaluate(expr):
        node=ast.parse(expr.replace('^','**'),mode='eval').body
        def walk(n):
            if isinstance(n,ast.Constant) and type(n.value) in (int,float): return Fraction(str(n.value))
            if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):
                return walk(n.operand)*(1 if isinstance(n.op,ast.UAdd) else -1)
            if isinstance(n,ast.BinOp):
                a,b=walk(n.left),walk(n.right)
                if isinstance(n.op,ast.Add): return a+b
                if isinstance(n.op,ast.Sub): return a-b
                if isinstance(n.op,ast.Mult): return a*b
                if isinstance(n.op,ast.Div): return a/b
                if isinstance(n.op,ast.Pow) and b.denominator==1 and abs(b)<=20: return a**int(b)
            raise ValueError('unmeasured expression')
        return walk(node)
    parsed=[]
    for lhs,rhs in re.findall(r'(?<![\w.])([\d()+*/^ .-]+?)\s*=\s*(-?\d+(?:\.\d+)?(?:/\d+)?)',text):
        lhs=lhs.strip().lstrip('.').strip()
        if not lhs or len(lhs)>160: continue
        try:
            # Bullet numbers/labels can accidentally join an expression; exclude them.
            if re.search(r'^\d+\.\s+\d',lhs): continue
            valid=evaluate(lhs)==evaluate(rhs)
            parsed.append({'expression':lhs,'value':rhs,'correct':valid})
        except (ValueError,SyntaxError,ZeroDivisionError,OverflowError): continue
    matched=[]
    final_state_equations=[]
    for step in expected_steps:
        compact=re.sub(r'\s+','',step['expression']).replace('**','^')
        equations=[p for p in parsed if re.sub(r'\s+','',p['expression']).replace('**','^')==compact]
        if equations:
            matched.append({'expected':step,'correct':any(p['correct'] for p in equations)})
            if step is expected_steps[-1]: final_state_equations=equations
    consistency=None
    if final_state_equations and extracted_answer not in (None,''):
        try:
            consistency=evaluate(str(extracted_answer))==evaluate(final_state_equations[-1]['value'])
        except (ValueError,SyntaxError,ZeroDivisionError,OverflowError): pass
    return {'numeric_equations_observed':len(parsed),'numeric_equations_correct':sum(p['correct'] for p in parsed),
            'expected_states':len(expected_steps),'exact_expression_states_observed':len(matched),
            'exact_expression_states_correct':sum(m['correct'] for m in matched),
            'numeric_equations':parsed,
            'final_answer_consistency_on_observed_final_state':consistency,
            'premise_retention':'NOT_AUTOMATICALLY_ESTABLISHED; trace audit required',
            'constraint_satisfaction':'Final correctness is measured separately; full semantic constraints require trace audit'}

def metrics(raws, dev):
    grouped=defaultdict(list)
    for r in raws: grouped[r['suite']].append(r)
    out={}
    for suite, rr in grouped.items():
        n=len(rr); parsed=sum(r['derivation_audit']['numeric_equations_observed'] for r in rr)
        states=sum(r['derivation_audit']['exact_expression_states_observed'] for r in rr)
        expected=sum(r['derivation_audit']['expected_states'] for r in rr)
        consistency=[r['derivation_audit']['final_answer_consistency_on_observed_final_state'] for r in rr
                     if r['derivation_audit']['final_answer_consistency_on_observed_final_state'] is not None]
        out[suite]={'n':n,'accuracy':sum(r['content_valid'] is True for r in rr)/n,
                    'truncation_fraction':sum(r['finish_reason']=='length' for r in rr)/n,
                    'invalid_output_fraction':sum(r.get('extracted_answer') in (None,'') for r in rr)/n,
                    'completion_fraction':sum(r['finish_reason']!='length' and r.get('extracted_answer') not in (None,'') for r in rr)/n,
                    'numeric_equations_observed':parsed,'numeric_equation_accuracy':sum(r['derivation_audit']['numeric_equations_correct'] for r in rr)/parsed if parsed else None,
                    'exact_expression_states_observed':states,'exact_expression_state_accuracy':sum(r['derivation_audit']['exact_expression_states_correct'] for r in rr)/states if states else None,
                    'exact_expression_state_coverage':states/expected if expected else None,
                    'final_answer_consistency_observed_count':len(consistency),
                    'final_answer_consistency_fraction':sum(consistency)/len(consistency) if consistency else None,
                    'premise_retention_errors':'unmeasured globally; outcome-stratified qualitative audit only',
                    'arithmetic_state_errors_observed':parsed-sum(r['derivation_audit']['numeric_equations_correct'] for r in rr),
                    'constraint_satisfaction':'endpoint score and exact-state observations; no full-proof claim'}
    assert sum(m['n'] for m in out.values())==len(dev)
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--label',required=True); ap.add_argument('--adapter-dir',required=True); ap.add_argument('--final',action='store_true')
    args=ap.parse_args(); check_frozen()
    from sciencemath.comparability.contract import BENCHMARKS as BCONFIG
    from sciencemath.comparability.loaders import EvalItem,load_benchmark,suite_hash
    from sciencemath.comparability.prompts import prompt_text,render_chat
    from sciencemath.comparability.runner import ArmRuntime,generate_batch,release_arm
    from sciencemath.comparability.scoring import score_row
    from sciencemath.comparability.config import load_frozen
    from sciencemath.comparability.manifest import chat_template_sha256
    from sciencemath.t32.dev_eval import load_candidate
    frozen=load_frozen(ROOT/'evaluations/t31/config/t31_frozen_config.json')
    assert frozen['decoding_primary']['max_new_tokens']==BUDGETS
    protocol_path=ROOT/'evaluations/t33/PROTOCOL.json'
    protocol=json.loads(protocol_path.read_text())
    adapter=Path(args.adapter_dir)
    identity_sha=sha(adapter/'adapter_model.safetensors')
    if args.final:
        freeze=json.loads((ROOT/'evaluations/t33/SELECTED_FREEZE.json').read_text())
        assert freeze['selected']==args.label and freeze['adapter_sha256']==identity_sha
        for p,h in freeze['files'].items(): assert sha(ROOT/p)==h, f'Selection/evidence drift: {p}'
        suites={b:[it.to_dict() for it in load_benchmark(b)] for b in BENCHMARKS}
        for b,rr in suites.items():
            assert suite_hash([EvalItem(**r) for r in rr])==frozen['suite_hashes'][b]
        destination=ROOT/f'evaluations/t33/final/{args.label}'
    else:
        assert sha(ROOT/'training/t33/development.jsonl')==protocol['development_sha256']
        dev=rows(ROOT/'training/t33/development.jsonl')
        suites={'development':dev}; destination=ROOT/f'evaluations/t33/development/{args.label}'
    tok,model,identity=load_candidate(adapter)
    assert chat_template_sha256(tok)==frozen['chat_template_sha256']
    runtime=ArmRuntime(arm=args.label,model=model,tokenizer=tok)
    destination.mkdir(parents=True,exist_ok=True)
    allraw=[]; start_time=time.time()
    for name,rr in suites.items():
        path=destination/f'{name}.jsonl'; prior=rows(path) if path.exists() else []
        known={r['item_id']:r for r in rr}; done={r['item_id'] for r in prior}
        assert len(done)==len(prior) and done<=set(known)
        for r in prior:
            fields={k:known[r['item_id']].get(k) for k in EvalItem.__dataclass_fields__ if k in known[r['item_id']]}
            it=EvalItem(**fields); text=prompt_text(it,BCONFIG[it.benchmark]['kind'])
            assert r['adapter_sha256']==identity_sha and r['config_hash']==frozen['config_sha256']
            assert r['protocol_sha256']==sha(protocol_path)
            assert r['prompt_sha256']==hashlib.sha256(('\x00'+text).encode()).hexdigest()
            assert r['rendered_prompt_sha256']==hashlib.sha256(render_chat(tok,text,enable_thinking=False).encode()).hexdigest()
            assert r['max_new_tokens']==BUDGETS[it.benchmark]
        pending=[r for r in rr if r['item_id'] not in done]
        # Preserve membership order and same benchmark grouping for shared budgets.
        chunks=[]
        for r in pending:
            if not chunks or len(chunks[-1])>=8 or chunks[-1][-1]['benchmark']!=r['benchmark']: chunks.append([])
            chunks[-1].append(r)
        for index,chunk in enumerate(chunks):
            items=[EvalItem(**{k:r[k] for k in EvalItem.__dataclass_fields__ if k in r}) for r in chunk]
            texts=[prompt_text(it,BCONFIG[it.benchmark]['kind']) for it in items]
            chats=[render_chat(tok,t,enable_thinking=False) for t in texts]
            budget=BUDGETS[items[0].benchmark]
            gens,finish,_,out_toks,_=generate_batch(runtime,chats,max_new_tokens=budget)
            fresh=[]
            for r,it,text,chat,gen,fin,ntok in zip(chunk,items,texts,chats,gens,finish,out_toks):
                scored=score_row({'arm':args.label,'benchmark':it.benchmark,'raw_generation':gen,'finish_reason':fin},it)
                row={'item_id':it.item_id,'benchmark':it.benchmark,'suite':r.get('suite',it.benchmark),
                     'model_id':identity['base_repo_id'],'model_revision':identity['base_revision'],
                     'adapter_label':args.label,'adapter_sha256':identity_sha,
                     'prompt_sha256':hashlib.sha256(('\x00'+text).encode()).hexdigest(),
                     'rendered_prompt_sha256':hashlib.sha256(chat.encode()).hexdigest(),
                     'max_new_tokens':budget,'config_hash':frozen['config_sha256'],'protocol_sha256':sha(protocol_path),
                     'raw_generation':gen,'finish_reason':fin,'output_tokens':ntok,
                     'content_valid':scored['content_valid'],'extracted_answer':scored.get('extracted_answer'),
                     'extraction_status':scored.get('extraction_status'),'error_category':scored.get('error_category'),
                     'derivation_audit':expression_audit(gen,r.get('verified_steps',[]),scored.get('extracted_answer'))}
                fresh.append(row)
            with path.open('a',encoding='utf-8',newline='\n') as f:
                for row in fresh: f.write(json.dumps(row,ensure_ascii=False)+'\n')
                f.flush(); os.fsync(f.fileno())
            prior+=fresh
            if index%5==0: print(f'{args.label} {name} {len(prior)}/{len(rr)} elapsed={time.time()-start_time:.1f}s',flush=True)
        assert len(prior)==len(rr)
        allraw+=prior
    release_arm(runtime)
    if not args.final:
        write(ROOT/f'evaluations/t33/development/{args.label}_metrics.json',
              {'identity':identity,'protocol_sha256':sha(protocol_path),'membership_sha256':protocol['development_sha256'],
               'suites':metrics(allraw,dev)})
    print('COMPLETE',args.label,'final' if args.final else 'development',flush=True)

if __name__=='__main__': main()
