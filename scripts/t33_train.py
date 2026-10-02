"""Pinned QLoRA, strict tokenization and uninterrupted sequential curriculum."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'scripts'))
from t33_build import rows, sha, write

BASE='Qwen/Qwen3-1.7B'
REVISION='70d244cc86ccca08cf5af4e1e306ecf908b1ad5e'

def check_frozen():
    frozen=json.loads((ROOT/'evaluations/t33/entry/FROZEN_FILES.json').read_text())
    changed=[p for p,h in frozen.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
    if changed: raise RuntimeError(f'Frozen historical drift: {changed}')

def quantiles(values):
    values=sorted(values)
    return {name:values[max(0,math.ceil(p*len(values))-1)] for name,p in
            [('median',.5),('p75',.75),('p90',.9),('p95',.95),('max',1)]}

def features(tok, records):
    from sciencemath.training.sft_data import render_example, render_prompt, build_labels
    out=[]; lengths=defaultdict(lambda:defaultdict(list))
    for r in records:
        prompt=tok(render_prompt(tok,r['question']),add_special_tokens=False)['input_ids']
        full=tok(render_example(tok,r['question'],r['target_response']),add_special_tokens=False)['input_ids']
        if full[:len(prompt)]!=prompt: raise RuntimeError('Chat response boundary mismatch')
        if len(full)>2048: raise RuntimeError(f'Overflow: {r["id"]}, {len(full)} tokens. No clipping permitted.')
        out.append({'input_ids':full,'labels':build_labels(full,len(prompt)),'attention_mask':[1]*len(full)})
        lengths[r['task_family']]['target_characters'].append(len(r['target_response']))
        lengths[r['task_family']]['target_tokens'].append(len(full)-len(prompt))
        lengths[r['task_family']]['full_sequence_tokens'].append(len(full))
    stats={family:{kind:quantiles(v) for kind,v in kinds.items()} for family,kinds in lengths.items()}
    return out,stats

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--candidate',choices=list('ABC'),default='B'); ap.add_argument('--feasibility',action='store_true')
    args=ap.parse_args()
    check_frozen()
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments, set_seed
    from torch.utils.data import SequentialSampler
    from sciencemath.training.attach import attach_lora, adapter_active_state
    from sciencemath.training.train import _load_parent_adapter, _environment
    from sciencemath.training.sft_data import SFTCollator
    from sciencemath.evaluation.model_loader import quantization_config
    if not torch.cuda.is_available(): raise RuntimeError('CUDA required; CPU substitute refused')
    tag=args.candidate
    protocol_path=ROOT/'evaluations/t33/PROTOCOL.json'
    protocol=json.loads(protocol_path.read_text()); cfg=protocol['candidates'][tag]
    dataset=ROOT/f'training/t33/candidates/{tag}/train.jsonl'
    assert sha(dataset)==cfg['train_sha256']
    records=rows(dataset)
    tok=AutoTokenizer.from_pretrained(BASE,revision=REVISION,local_files_only=True)
    tok.pad_token=tok.pad_token or tok.eos_token
    feats,lengths=features(tok,records)
    write(ROOT/f'evaluations/t33/development/lengths_{tag}.json',{'families':lengths,'records':len(feats),'truncation_count':0,'question_shortened':0,'dropped':0})
    pilot=ROOT/'training/t33/feasibility'
    checkpoint=pilot/'checkpoints' if args.feasibility else ROOT/f'training/checkpoints/t33-{tag}'
    adapter=pilot/'adapter' if args.feasibility else ROOT/f'training/adapters/t33-{tag}'
    receipt=ROOT/('evaluations/t33/FEASIBILITY.json' if args.feasibility else f'evaluations/t33/development/train_{tag}.json')
    if receipt.exists():
        old=json.loads(receipt.read_text())
        if old.get('status')=='COMPLETE' and old.get('adapter_sha256')==sha(adapter/'adapter_model.safetensors'):
            print('Verified complete receipt; training skipped'); return
        raise RuntimeError('Existing receipt requires explicit investigation')
    restart_history=[]
    if checkpoint.exists() and any(checkpoint.iterdir()):
        checkpoint.resolve().relative_to(ROOT)
        archived=checkpoint.with_name(checkpoint.name+'-INVALID-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
        archived.resolve().relative_to(ROOT); checkpoint.rename(archived)
        write(ROOT/f'evaluations/t33/development/invalid_{archived.name}.json',{'status':'INVALID_INTERRUPTED','preserved_path':str(archived),'policy':'Whole candidate restarted from frozen T32-A; not called an equivalent resume'})
        restart_history.append({'preserved_checkpoint_path':str(archived),
                                'invalid_prior_run':True,'restart_from':'T32-A',
                                'full_optimizer_scheduler_rng_restarted':True,
                                'equivalent_resume_claimed':False})
    if args.feasibility:
        feats=sorted(feats,key=lambda r:len(r['input_ids']),reverse=True)[:3]
    set_seed(42)
    torch.cuda.reset_peak_memory_stats()
    model=AutoModelForCausalLM.from_pretrained(BASE,revision=REVISION,local_files_only=True,
        quantization_config=quantization_config('bfloat16'),device_map='auto',trust_remote_code=False)
    model.config.use_cache=False
    lora={'r':32,'lora_alpha':64,'lora_dropout':.05,'target_modules':cfg['lora']['modules']}
    model=attach_lora(model,lora)
    parent=_load_parent_adapter(model,ROOT/cfg['starting_adapter'],lora)
    if not parent.get('ok'): raise RuntimeError(parent)
    assert adapter_active_state(model)['adapter_active']
    class CurriculumTrainer(Trainer):
        def _get_train_sampler(self, train_dataset=None):
            return SequentialSampler(train_dataset if train_dataset is not None else self.train_dataset)
    total=3 if args.feasibility else math.ceil(len(feats)/16)
    trainargs=TrainingArguments(output_dir=str(checkpoint),num_train_epochs=1,max_steps=3 if args.feasibility else -1,
        per_device_train_batch_size=1,gradient_accumulation_steps=1 if args.feasibility else 16,
        learning_rate=cfg['learning_rate'],warmup_steps=max(1,round(.03*total)),weight_decay=.01,
        lr_scheduler_type='cosine',max_grad_norm=1.,seed=42,data_seed=42,gradient_checkpointing=True,
        bf16=True,logging_steps=1 if args.feasibility else 10,save_steps=3 if args.feasibility else 25,
        save_total_limit=3,eval_strategy='no',remove_unused_columns=False,label_names=['labels'],
        report_to=[],dataloader_num_workers=0,optim='adamw_torch')
    trainer=CurriculumTrainer(model=model,args=trainargs,train_dataset=feats,data_collator=SFTCollator(tok.pad_token_id))
    start=time.time(); trainer.train(); elapsed=time.time()-start
    adapter.mkdir(parents=True,exist_ok=True); model.save_pretrained(adapter)
    history=trainer.state.log_history
    peak=torch.cuda.max_memory_allocated()
    manifest={'status':'COMPLETE','candidate':tag,'feasibility':args.feasibility,'base_repo':BASE,'base_revision':REVISION,
              'base_weight_files':{p.name:sha(p) for p in Path(model.config._name_or_path).glob('*.safetensors')} if Path(model.config._name_or_path).is_dir() else {},
              'starting_adapter':cfg['starting_adapter'],'starting_adapter_sha256':cfg['starting_adapter_sha256'],
              'dataset_sha256':sha(dataset),'protocol_sha256':sha(protocol_path),
              'dataset_records':len(records),'trained_records':len(feats),
              'family_counts':dict(Counter(r['task_family'] for r in records)),
              'stage_counts':dict(Counter(r['curriculum_stage'] for r in records)),
              'target_length_statistics':lengths,'truncation':0,'question_shortened':0,
              'config':cfg,'effective_gradient_accumulation':1 if args.feasibility else 16,
              'steps':trainer.state.global_step,'epochs':trainer.state.epoch,
              'hardware':torch.cuda.get_device_name(0),'peak_vram_bytes':peak,
              'training_seconds':elapsed,'records_per_second':len(feats)/elapsed,
              'environment':_environment(),'checkpoint_history':[],
              'resume_history':[],'restart_history':restart_history,
              'prior_corpus_invalidation':json.loads((ROOT/'evaluations/t33/invalid-corpus-v1/INVALIDATION.json').read_text(encoding='utf-8-sig')) if tag=='A' and not args.feasibility else None,
              'log_history':history,'completed_utc':datetime.now(timezone.utc).isoformat(),
              'adapter_sha256':sha(adapter/'adapter_model.safetensors')}
    from sciencemath.comparability.runner import _hub_snapshot
    basepath=_hub_snapshot(BASE,REVISION)
    manifest['base_weight_files']={p.name:sha(p) for p in basepath.glob('*.safetensors')}
    for cp in sorted(checkpoint.glob('checkpoint-*')):
        manifest['checkpoint_history'].append({'path':str(cp),'files':{p.name:sha(p) for p in cp.iterdir() if p.is_file()}})
    write(adapter/'training_manifest.json',manifest)
    del trainer,model; gc.collect(); torch.cuda.empty_cache()
    # Independent fresh load; original training allocation released first.
    from peft import PeftModel
    fresh=AutoModelForCausalLM.from_pretrained(BASE,revision=REVISION,local_files_only=True,
        quantization_config=quantization_config('bfloat16'),device_map='auto')
    fresh=PeftModel.from_pretrained(fresh,adapter); fresh.eval()
    inputs=tok('2 + 2 =',return_tensors='pt').to(fresh.device)
    with torch.no_grad(): logits=fresh(**inputs).logits
    manifest['reload_ok']=bool(torch.isfinite(logits).all().item())
    if not manifest['reload_ok']: raise RuntimeError('Reload produced nonfinite logits')
    write(receipt,manifest)
    print(json.dumps({k:manifest[k] for k in ('status','candidate','steps','peak_vram_bytes','training_seconds','records_per_second','adapter_sha256','reload_ok')},indent=2),flush=True)

if __name__=='__main__': main()
