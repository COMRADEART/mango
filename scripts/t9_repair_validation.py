"""Validate T9 evidence restoration without training or expensive regressions."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from t9_repro_audit import ROOT, OUT, run, save, sha

sys.path.insert(0, str(ROOT/'src'))
OLD = ROOT/'sciencemath'

def suite_check(relative):
    path = ROOT/relative
    hashes = json.loads((path/'checksum.json').read_text(encoding='utf-8'))
    lines = (path/'questions.jsonl').read_text(encoding='utf-8').splitlines()
    rows = [json.loads(x) for x in lines if x.strip()]
    ids = [r['eval_id'] for r in rows]
    mismatch = [json.loads(x)['eval_id'] for x in lines if x.strip() and
                hashes.get(json.loads(x)['eval_id']) != sha(x.encode())]
    return {'rows':len(rows),'duplicates':[k for k,v in Counter(ids).items() if v>1],
            'missing':sorted(set(hashes)-set(ids)), 'extra':sorted(set(ids)-set(hashes)),
            'mismatched':mismatch,'questions_byte_sha256':sha((path/'questions.jsonl').read_bytes()),
            'ok':not mismatch and len(ids)==len(set(ids)) and set(ids)==set(hashes)}

def recovery_checks():
    recovery = json.loads((OUT/'adapter_recovery.json').read_text())
    manifest = json.loads((ROOT/'training/adapters/sciencemath-v0.1-t3/training_manifest.json').read_text())
    config = json.loads((ROOT/'training/adapters/sciencemath-v0.1-t3/adapter_config.json').read_text())
    header = recovery['candidates'][0]['tensor_inventory']
    shapes = {'q_proj':(2048,2048),'k_proj':(1024,2048),'v_proj':(1024,2048),
              'o_proj':(2048,2048),'gate_proj':(6144,2048),'up_proj':(6144,2048),'down_proj':(2048,6144)}
    expected = {}
    for layer in range(28):
        for module,(outputs,inputs) in shapes.items():
            parent='self_attn' if module in ['q_proj','k_proj','v_proj','o_proj'] else 'mlp'
            prefix=f'base_model.model.model.layers.{layer}.{parent}.{module}'
            expected[prefix+'.lora_A.weight']=[32,inputs]
            expected[prefix+'.lora_B.weight']=[outputs,32]
    inventory_ok = set(header)==set(expected) and all(header[k]['shape']==v for k,v in expected.items())
    datasets={name:{'expected':digest,'actual':sha((OLD/manifest['dataset']['dir']/name).read_bytes())}
              for name,digest in manifest['dataset']['checksums'].items()}
    recovery['identity_checks']={
        'base_model':manifest['base_model'], 'config_base_matches':config['base_model_name_or_path']==manifest['base_model']['model_id'],
        'rank':config['r'],'alpha':config['lora_alpha'],'target_modules':config['target_modules'],
        'expected_tensor_count':392,'keys_and_shapes_match':inventory_ok,
        'dtype_counts':dict(Counter(v['dtype'] for v in header.values())),
        'parameter_count':sum(v['shape'][0]*v['shape'][1] for v in header.values()),
        'training_seed':manifest['seed'],'final_training_step':recovery['trainer_state']['global_step'],
        'selected_checkpoint':recovery['trainer_state']['best_model_checkpoint'],
        'selected_checkpoint_step':recovery['trainer_state']['best_global_step'],
        'selected_eval_loss':recovery['trainer_state']['best_metric'],
        'best_loss_matches_manifest':recovery['trainer_state']['best_metric']==manifest['results']['best_eval_loss'],
        'production_equals_checkpoint_300':recovery['candidates'][0]['sha256']==recovery['candidates'][1]['sha256'],
        'previous_dataset_checksums':datasets, 'all_dataset_checksums_match':all(x['expected']==x['actual'] for x in datasets.values())}
    recovery['historical_weight_sha_search'] = {
        'result':'No original weight SHA found. The candidate hash is newly measured, not historical proof.',
        'inspected':['T3 manifest, adapter config, reload verification, loss history',
                     'prior T3 checkpoints 300, 500, 546 and trainer states',
                     'T3/T5/T6/T7/T8/T8S evaluation metadata and local gate records',
                     'current and previous repository histories and LFS listings'],
        'previous_history_search':run('git','-C','sciencemath','log','--all','--oneline','-S','f57b2fd4','--','.'),
        'current_remote_refs':run('git','ls-remote','--heads','--tags','origin'),
        'current_lfs':run('git','lfs','ls-files','--all','--long'),
        'previous_lfs':run('git','-C','sciencemath','lfs','ls-files','--all','--long'),
        'lfs_configuration':run('git','lfs','env'),
        'ignore_rule':run('git','check-ignore','-v','training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors')}
    recovery['scope']={
        'current_repo':str(ROOT),'previous_repo':str(OLD),
        'searched_project_locations':['training','training/checkpoints','training/adapters','artifacts','evaluations','train_lora','.git/lfs/objects'],
        'wsl':'Ubuntu-24.04: /home and /opt project-directory inventory found no Mango/ScienceMath workspace; /home/allam contains only environment/cache directories. /mnt/c is this Windows filesystem.',
        'backups':'No project backup/export found or mounted in inspected project/workspace and WSL locations. No unmounted export was imported; no unrelated file contents searched.',
        'limitations':'Unknown offline backups and external storage are unavailable. User asked for any original hash or additional known project backup location.'}
    recovery['production_baseline_reproducibility']='BLOCKED'
    recovery['lfs_restoration']={'status':'NOT_ATTEMPTED','reason':'Only PROBABLE_RECOVERY; identity requirement forbids candidate upload/production substitution.',
                                 'remote_object_verified':False,'clean_clone_retrieval':'NOT_RUN'}
    save('adapter_recovery.json',recovery)

def validate():
    recovery_checks()
    stage = ROOT/'training/curriculum/mango-sft-v2/level1'
    stage_evidence = {}
    for name,digest in json.loads((stage/'checksums.json').read_text()).items():
        rel=(stage/name).relative_to(ROOT).as_posix()
        blob=subprocess.check_output(['git','show','HEAD:'+rel],cwd=ROOT)
        current=(stage/name).read_bytes()
        previous=(OLD/rel).read_bytes()
        stage_evidence[name]={'expected':digest,'current':sha(current),'previous':sha(previous),
                              'git_blob':sha(blob),'git_blob_crlf':sha(blob.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')),
                              'same_json_content':json.loads(current)==json.loads(previous) if name.endswith('.json') else
                              [json.loads(x) for x in current.splitlines()]==[json.loads(x) for x in previous.splitlines()],
                              'ok':sha(current)==digest}
    save('level1_corpus_validation.json',stage_evidence)
    assert all(v['ok'] for v in stage_evidence.values())
    replay = json.loads((OUT/'replay_provenance.json').read_text())
    path='training/curriculum/mango-sft-v2/level1/replay.jsonl'
    replay.update({'decision':'CURRENT_FILE_MUTATED','mutation':'LF converted to CRLF during Windows checkout (core.autocrlf=true)',
                   'resolution':'Restored exact committed blob; pinned Level-1 JSONL to LF and JSON metadata to its historical CRLF bytes. checksums.json unchanged.',
                   'restored_sha256':sha((ROOT/path).read_bytes()),'git_history':run('git','log','--all','--format=%H %s','--',path)})
    assert replay['restored_sha256']==replay['expected_sha256']
    save('replay_provenance.json',replay)
    inventory=json.loads((OUT/'test_inventory_reconciliation.json').read_text())
    inventory.pop('test_file_diff',None)
    restored=['tests/test_t8s_finalize.py','tests/test_t8s_metrics.py','tests/test_t8s_pareto.py','tests/test_t8s_repro.py',
              'scripts/t8s_finalize.py','scripts/t8s_metrics.py','scripts/t8s_vectors_pareto.py','src/sciencemath/evaluation/repro.py']
    inventory['restored_files']={p:{'source':'sciencemath/'+p,'source_sha256':sha((OLD/p).read_bytes()),
                                   'restored_sha256':sha((ROOT/p).read_bytes()),
                                   'text_equal':(OLD/p).read_text(encoding='utf-8')==(ROOT/p).read_text(encoding='utf-8'),
                                   'python_source_equal':(OLD/p).read_text(encoding='utf-8-sig')==(ROOT/p).read_text(encoding='utf-8-sig'),
                                   'format_note':'Restored as UTF-8 without BOM and LF; Python source is unchanged.'}
                                for p in restored}
    inventory['source_commits']=run('git','-C','sciencemath','log','--format=%H %s','--',*restored)
    inventory['explanation']={'t8s':737,'earlier_t9_collected':707,'earlier_t9_passed':706,'earlier_t9_failed':1,
                              't9_before_collected':715,'t9_before_passed':714,'t9_before_failed':1,
                              'omitted_t8s_tests':30,'new_t9_tests':8,
                              'cause':'T8S commits exist in nested prior repository but are absent from current main; no deletion in the T9 commit. T9 added eight tests. Replay byte mismatch accounts for the one failure.',
                              'arithmetic':'737 - 30 = 707; 707 + 8 = 715; restore 30 = 745',
                              'renamed':[],'moved':[],'deselected':[],'collection_errors':[],
                              'artifact_conditional_loss':False,'skipped_historical':0,
                              'failed_before':['tests/test_curriculum_core.py::test_stage_corpus_frozen_and_checksummed']}
    inventory['t9_commit_test_diff']=run('git','diff','--name-status','1934e9d^','1934e9d','--','tests','pyproject.toml')
    collection=run(sys.executable,'-m','pytest','--collect-only')
    save('pytest_collect_final.json',collection)
    exact=run(sys.executable,'-m','pytest','--collect-only','-o','addopts=','-q')
    ids=[x for x in exact['stdout'].splitlines() if x.startswith('tests/') and '::' in x]
    inventory['after_nodeids']=ids
    inventory['after_collection']=exact
    inventory['historical_absent_after']=sorted(set(inventory['historical_nodeids'])-set(ids))
    inventory['new_after']=sorted(set(ids)-set(inventory['historical_nodeids']))
    save('test_inventory_reconciliation.json',inventory)
    previous_test=OUT/'pytest_final.json'
    if previous_test.exists() and json.loads(previous_test.read_text()).get('returncode'):
        save('pytest_intermediate_failure.json',json.loads(previous_test.read_text()))
    start=time.perf_counter()
    test=run(sys.executable,'-m','pytest','--junitxml=evaluations/t9/pytest_final.xml')
    test['wall_duration_s']=time.perf_counter()-start
    tree=ET.parse(OUT/'pytest_final.xml')
    suites=tree.findall('.//testsuite')
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
    counts['passed']=counts['tests']-counts['failures']-counts['errors']-counts['skipped']
    counts['collected']=len(ids)
    counts['duration_s']=sum(float(s.get('time',0)) for s in suites)
    test['counts']=counts
    test['summary']=next((l for l in reversed(test['stdout'].splitlines()) if re.search(r'\d+ passed',l)),None)
    save('pytest_final.json',test)
    inventory['after_results']=test
    inventory['failed_after']=[c.get('classname')+'::'+c.get('name') for c in tree.findall('.//testcase') if c.find('failure') is not None]
    inventory['skipped_after']=[c.get('classname')+'::'+c.get('name') for c in tree.findall('.//testcase') if c.find('skipped') is not None]
    save('test_inventory_reconciliation.json',inventory)
    from sciencemath.tools.benchmark import load_suite, verifier_selftest
    safety=verifier_selftest(load_suite(ROOT/'evaluations/tool-suite/v1'))
    save('verifier_safety_final.json',safety)
    suites={p:suite_check(p) for p in ['evaluations/tool-suite/v1','evaluations/rag-suite/v1','evaluations/t8/capacity-suite/v1']}
    # Exact raw bytes and semantic JSON agreement are separately reported.
    baseline={}
    for p in (OLD/'evaluations/t8s').glob('*.json'):
        baseline[p.relative_to(OLD).as_posix()]={'source_sha256':sha(p.read_bytes()),'current_main_present':(ROOT/p.relative_to(OLD)).exists(),
                                               'historical_evidence_only':True}
    t8_expected=json.loads((OUT/'t9_entry_gate.json').read_text())['t8_hashes']
    mapping={'tool_suite':'evaluations/tool-suite/v1/questions.jsonl','rag_suite':'evaluations/rag-suite/v1/questions.jsonl',
             'capacity_suite':'evaluations/t8/capacity-suite/v1/questions.jsonl','recomputed_metrics':'evaluations/t8/recomputed_metrics.json',
             'final_decision':'evaluations/t8/FINAL_DECISION.json'}
    t8={k:{'path':v,'expected':t8_expected[k],'actual':sha((ROOT/v).read_bytes())} for k,v in mapping.items()}
    for v in t8.values():
        v['match']=v['expected']==v['actual']
        blob=subprocess.check_output(['git','show','HEAD:'+v['path']],cwd=ROOT)
        v['git_blob_sha256']=sha(blob)
        v['git_blob_match']=sha(blob)==v['expected']
    save('baseline_hash_validation.json',{'t8':t8,'t8s_local_evidence':baseline,'suites':suites,
                                         'note':'T8S historical files remain in their original workspace; fresh results are never inferred from them.'})
    gpu=run('nvidia-smi','--query-compute-apps=pid,process_name,used_memory','--format=csv,noheader')
    freeze=json.loads((OUT/'pre_repair_state.json').read_text())
    changed={p:{'before':h,'after':sha((ROOT/p).read_bytes())} for p,h in freeze['artifact_sha256'].items()
             if p!='evaluations/t9/T9_FINAL_REPORT.md' and sha((ROOT/p).read_bytes())!=h}
    gate={'milestone':'T9','status':'FAIL','commit':run('git','rev-parse','HEAD')['stdout'].strip(),
          'production_baseline_reproducibility':'BLOCKED','adapter_recovery':'PROBABLE_RECOVERY',
          'production_adapter_loadable':False,'candidate_uploaded':False,
          'replay_checksum_validated':True,'pytest':counts,'pytest_green':test['returncode']==0,
          't4_verifier_safety':safety,'frozen_suites':suites,'t8_baseline_hashes':t8,
          't8s_baseline_hash_validation':'LOCAL_SOURCE_HASHES_RECORDED; independent immutable closure digests unavailable',
          'gpu_jobs':gpu,'no_stale_gpu_jobs':gpu['returncode']==0 and not gpu['stdout'].strip(),
          'frozen_correction_artifacts_changed':changed,
          'blockers':['Recovered T3 candidate has no original cryptographic identity proof; PROBABLE_RECOVERY is insufficient for production.',
                      'T8S closure artifacts are local reference evidence without an independent immutable hash anchor.'],
          'expensive_regressions':'NOT_RUN: Phase 5 explicitly requires STOP when the entry gate fails.',
          'instruction_conflict':'Later missing-adapter fallback requests 4B regressions; the explicit clean-entry STOP requirement is retained, not silently waived.',
          'system_promotion':'BLOCKED_BY_REPRODUCIBILITY','weight_promotion':'NO'}
    if not all(x['match'] for x in t8.values()):
        gate['blockers'].append('Some historical T8 raw-file hashes differ; see byte-level baseline hash validation.')
    save('t9_entry_gate_final.json',gate)
    print(json.dumps({'pytest':counts,'summary':test['summary'],'verifier':safety['critical_gate'],
                      'wrong_probes':safety['wrong_cases'],'baseline_hashes':t8,'entry_gate':'FAIL'},indent=2))

if __name__=='__main__':
    validate()
