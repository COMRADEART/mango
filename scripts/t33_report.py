"""Close only after full measured results, manual trace audit and regressions."""
from pathlib import Path
from collections import Counter
import json
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from t33_build import rows,sha,write
from t33_train import check_frozen
from t33_evaluate import BENCHMARKS

def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))

def main():
    check_frozen()
    protocol=read('evaluations/t33/PROTOCOL.json'); selection=read('evaluations/t33/SELECTION.json');selected=selection['selected']
    scores=read('evaluations/t33/FINAL_SCORES.json');paired=read('evaluations/t33/PAIRED_ANALYSIS.json')
    regress=read('evaluations/t33/regression/CLASSIFICATION.json');trace=read('evaluations/t33/TRACE_REVIEW.json')
    assert trace['review_status']=='COMPLETE'
    freeze=read('evaluations/t33/SELECTED_FREEZE.json')
    assert freeze['adapter_sha256']==sha(ROOT/f'training/adapters/{selected}/adapter_model.safetensors')
    for p,h in freeze['files'].items():assert sha(ROOT/p)==h,f'Selection-freeze drift: {p}'
    receipts={tag:read(f'evaluations/t33/development/train_{tag}.json') for tag in 'ABC'}
    data=read('evaluations/t33/DATA_VERIFICATION.json');contam=read('evaluations/t33/CONTAMINATION.json')
    provenance=read('evaluations/t33/entry/PROVENANCE.json')
    mathfloor=all(scores[b]['delta_vs_t30_pp']>=5-1e-9 and scores[b]['delta_vs_t32_pp']>0 for b in ('gsm8k','math500'))
    preservation={b:scores[b]['delta_vs_t30_pp']>=-2-1e-9 for b in ('arc_easy','arc_challenge','sciq')}
    regression_ok=regress['classification_counts'].get('T33_ATTRIBUTABLE',0)==0 and regress['classification_counts'].get('UNKNOWN',0)==0
    gates={
        'GATE 1':True,'GATE 2':True,'GATE 3':True,'GATE 4':data['status']=='PASS',
        'GATE 5':contam['passed'] and data['canonical_problem_stem_contamination']['removed']==0,
        'GATE 6':data['A_B_derivation_targets_identical'] and data['B_C_data_byte_identical'],
        'GATE 7':all(r['status']=='COMPLETE' and r['reload_ok'] for r in receipts.values()),
        'GATE 8':selection['final_results_used_for_selection'] is False,
        'GATE 9':scores['gsm8k']['n']==1319,'GATE 10':scores['math500']['n']==500,
        'GATE 11':scores['arc_easy']['n']==2376,'GATE 12':scores['arc_challenge']['n']==1172,'GATE 13':scores['sciq']['n']==1000,
        'GATE 14':trace['review_status']=='COMPLETE' and all(len(paired[b])==3 for b in BENCHMARKS),
        'GATE 15':regression_ok}
    if mathfloor and all(preservation.values()) and selection['selected_eligible'] and all(gates.values()):
        status,decision='PASS — REASONING_RESTORATION','MANGO_T33_VERIFIED_DERIVATION_PASS'
    elif any(scores[b]['delta_vs_t32_pp']<0 for b in ('gsm8k','math500')) or any(scores[b]['delta_vs_t30_pp']<-5 for b in preservation):
        status,decision='FAIL — REGRESSION','MANGO_T33_VERIFIED_DERIVATION_FAIL'
    elif mathfloor or any(scores[b]['delta_vs_t30_pp']>=5-1e-9 and scores[b]['delta_vs_t32_pp']>0 for b in ('gsm8k','math500')):
        status,decision='PARTIAL — TRADEOFF','MANGO_T33_VERIFIED_DERIVATION_PARTIAL'
    else:
        status,decision='FAIL — NO_EFFECT','MANGO_T33_VERIFIED_DERIVATION_FAIL'
    if not regression_ok and status.startswith('PASS'):
        status,decision='PARTIAL — REGRESSION_GATE_INCOMPLETE','MANGO_T33_VERIFIED_DERIVATION_PARTIAL'
    names={'gsm8k':'GSM8K','math500':'MATH-500','arc_easy':'ARC-Easy','arc_challenge':'ARC-Challenge','sciq':'SciQ'}
    lines=['# MANGO T33 VERIFIED DERIVATION REPORT','', '## Status','',status+'. `'+decision+'`','',
           '## T32 baseline','',
           'T32 is closed as MANGO_T32_MATH_REMEDIATION_FAIL. Historical generations, prompts, scorer, membership, runtime and evidence remain byte-identical to the T33 entry snapshot. Base/T30/T32 final columns reuse the frozen, item-paired historical scored generations; only T33 final generations are fresh. This is the same reuse methodology documented in T32, not a fresh rerun of historical models.','',
           '## Entry audit','', 'The historical report’s Final model identities block is the T31 baseline identity. T32’s selected adapter identity is separate. T32 closure was uncommitted/untracked at entry: no final closure commit exists. The last committed tip and exact closure-file hashes are recorded below, rather than inventing a final commit.','',
           '```json',json.dumps(provenance,indent=2),'```','',
           'The two new/unclassified IDs were test_concurrent_observations_lose_nothing_and_never_mix and test_the_event_log_never_gains_a_torn_line. Both and the two unresolved closure concurrency IDs were reproduced with Windows state_index.json PermissionError. The State Engine and tests are pre-T33 untracked WIP absent from both historical commits; commit-level source equality cannot be established. Frozen T31 failure IDs, T32 traces, entry source hashes and fresh focused JUnit reports provide the classification evidence. No State Engine redesign was performed. See entry/REGRESSION_CLASSIFICATION.json and SOURCE_COMPARISON.json.','',
           '## Dataset','',
           '1,069 independently exact-checked math problems across all 16 required families; 224 explicitly incorrect/corrected repair pairs; 300 source-gold SciQ direct-response records. Source pool contained 1,152 math candidates: 83 near-development duplicates were removed. Direct factual records rely on legitimate training-source gold labels; they are not claimed to have arithmetic verification.','',
           'A has 1,593 training presentations. B/C each have 1,893; Stage D repeats 300 identical verified derivations, and B/C additionally interleave 300 direct science records. One sequential curriculum pass is used for each candidate, with uninterrupted optimizer/scheduler across stages. Detailed per-family character/token median, p75, p90, p95 and maximum are in development/lengths_A.json, lengths_B.json and lengths_C.json and every training receipt. No target clipping, premise shortening or dropped-overlength record occurred.','',
           'Family counts (unique verified math):','',
           '```json',json.dumps(dict(Counter(r['task_family'] for r in rows(ROOT/'training/t33/verified_math.jsonl'))),indent=2),'```','',
           '## Derivation supervision','',
           'The assistant target numbers each state update, displays its exact expression and value, includes an explicit verification reminder, then closes with Final answer: \\boxed{value}. Prompt tokens are masked; all response tokens carry ordinary causal cross-entropy loss. Repair examples put the deliberately wrong proposal in the user prompt and supervise only the diagnosis and corrected derivation. This is correction SFT, not a preference/DPO loss. All mathematical equations and endpoints are re-evaluated exactly; selected families also use independent equation solving, combinatorial counts or equivalent identities.','',
           '```text',rows(ROOT/'training/t33/candidates/B/train.jsonl')[0]['question'],'','ASSISTANT:',rows(ROOT/'training/t33/candidates/B/train.jsonl')[0]['target_response'],'```','',
           '## Output-mode decoupling','',
           'B/C add natural-language task instructions requesting retained premises, updated intermediate states and a verified endpoint for derive examples. Direct MC prompts request one correct option letter with no derivation; assistant targets contain only that letter. Stage D alternates derivation and direct science records. No runtime routing, hidden-chain product dependency, new special token, final prompt change or scorer change is introduced. A uses natural math/correction prompts and no direct science replay.','',
           '## Candidate A/B/C','',
           '| Candidate | LR | Records | Steps | Train seconds | Adapter SHA-256 |',
           '|---|---:|---:|---:|---:|---|']
    for tag,r in receipts.items():lines.append(f"| {tag} | {r['config']['learning_rate']} | {r['trained_records']} | {r['steps']} | {r['training_seconds']:.1f} | {r['adapter_sha256']} |")
    lines += ['','Qwen3-1.7B pinned revision; T32-A starting LoRA; rank 32, alpha 64, dropout .05, q/k/v/o/gate/up/down; NF4 double quantization, bf16; sequence 2048, batch 1, accumulation 16, seed 42, AdamW, cosine scheduler, 3% warmup, gradient clipping 1.0. C changes only LR from 1e-4 to 3e-5. A/B’s extra MC rows increase total steps; this is explicitly disclosed rather than presented as equal compute.','',
              'An isolated three-step longest-example feasibility test verified memory/throughput before the valid full run. Its exact duration and peak allocation are in FEASIBILITY.json. Full training memory/throughput, dataset hashes, base weight hashes, checkpoint files, complete configs, loss history, environment and resume history are recorded per candidate. No model-only resume is treated as equivalent training. The initial unfinished A attempt was invalidated before development measurement because correction pairs did not isolate the stated error taxonomy. Old data/protocol/logs/checkpoints are preserved; the valid candidate restarted entirely from T32-A with fresh optimizer/scheduler/RNG. See invalid-corpus-v1/INVALIDATION.json.','',
              '| Development suite | T32-A | T33-A | T33-B | T33-C |','|---|---:|---:|---:|---:|']
    metrics={l:read(f'evaluations/t33/development/{l}_metrics.json')['suites'] for l in ('t32-A','t33-A','t33-B','t33-C')}
    for suite in metrics['t32-A']:
        lines.append('| '+suite+' | '+' | '.join(f"{100*metrics[l][suite]['accuracy']:.2f}" for l in metrics)+' |')
    lines += ['','## Candidate selection','',
              'The 560-item development membership and selection rules were frozen before candidate results: +5 pp independently on GSM-style and competition-style versus T32-A; strictly positive short/long math deltas; each MC suite within -2 pp versus T32-A; invalid output <=5% per suite; clean contamination and regressions. Ranking uses the minimum of the two math deltas, then long-math accuracy, then lower invalid-output fraction, then A/B/C order. No final test result enters selection. If none eligible, the predeclared diagnostic fallback selects exactly one but cannot earn PASS.','',
              '```json',json.dumps(selection,indent=2),'```','',
              '## Final identities','',
              'Base revision: 70d244cc86ccca08cf5af4e1e306ecf908b1ad5e. Base weight SHA-256 values: '+json.dumps(receipts['A']['base_weight_files'])+'. T30 revision ad4bac714e442ca5c9b20420847fcadad61a6123; weights f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668. T32 selected t32-A weights '+provenance['t32_adapter_sha256']+'. T33 selected '+selected+' weights '+freeze['adapter_sha256']+'. Full selection/data/training/config freeze: SELECTED_FREEZE.json.','',
              '## Final benchmark table','',
              '| Benchmark | Base | T30 | T32 | T33 | Δ T33 vs T32 | Δ T33 vs T30 | Δ T33 vs Base |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for b,s in scores.items():lines.append('| '+names[b]+' | '+' | '.join(f"{100*s[l]:.2f}" for l in ('base','t30','t32','t33'))+' | '+' | '.join(f"{s['delta_vs_'+l+'_pp']:+.2f}" for l in ('t32','t30','base'))+' |')
    lines += ['','## Math restoration','',
              f'Both math benchmarks meet T30 +5 pp and strictly exceed T32: {mathfloor}. Stretch targets GSM8K >=68%: {scores["gsm8k"]["t33"]>=.68}; MATH-500 >=38%: {scores["math500"]["t33"]>=.38}. These are endpoint accuracy measurements, not proof-level reasoning claims.','',
              '## MC/science preservation','',json.dumps(preservation)+'. Floors are assessed separately at T30 -2 pp. T32 deltas are independently displayed above.','',
              '## Paired analysis','',
              '| Benchmark / reference | Both right | Reference-only right | T33-only right | Both wrong | Δ pp [95% CI] | Exact McNemar p |',
              '|---|---:|---:|---:|---:|---|---:|']
    for b,pp in paired.items():
        for key,r in pp.items():
            t=r['table'];label=r['frozen_arm']
            lines.append(f"| {names[b]} / {label} | {t['both_correct']} | {t[label+'_correct_only']} | {t['t33_correct_only']} | {t['neither_correct']} | {r['delta_pp']:+.2f} {r['delta_pp_normal_95_ci']} | {r['mcnemar_exact_p']:.6g} |")
    lines += ['','Paired differences use the established per-item normal 95% interval and exact two-sided binomial McNemar method; no benchmark pooling.','',
              '## Reasoning metrics','',
              'Each suite separately reports final correctness, output completion, invalid output, truncation, numeric-equation correctness, exact-expression state accuracy, final-answer consistency with an observed final-state equation, and measurement coverage. Output completion means a natural stop with an extractable answer; it does not establish semantic reasoning completion. Final-answer consistency is measured only when the final expected expression is explicitly observed and the extracted endpoint is numeric. The parser only accepts bounded numeric arithmetic; unparseable symbolic work is unmeasured, never silently called correct. Global semantic premise retention and constraint satisfaction are not established by numeric equation matches. See each *_metrics.json and the per-row derivation_audit.','',
              '```json',json.dumps(metrics[selected],indent=2),'```','',
              '| Suite / state | Completion % | Numeric-equation accuracy % | Equations observed | Exact-state accuracy % | Exact-state coverage % | Final consistency % | Consistency observations |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    def percent(value):return 'unmeasured' if value is None else f'{100*value:.2f}'
    for suite in ('math-short','math-medium','math-long','gsm-style','competition-style'):
        for label in ('t32-A',selected):
            m=metrics[label][suite]
            lines.append(f"| {suite} / {label} | {percent(m['completion_fraction'])} | {percent(m['numeric_equation_accuracy'])} | {m['numeric_equations_observed']} | {percent(m['exact_expression_state_accuracy'])} | {percent(m['exact_expression_state_coverage'])} | {percent(m['final_answer_consistency_fraction'])} | {m['final_answer_consistency_observed_count']} |")
    lines += ['','Accuracy of intermediate states is conditional on observed expressions; coverage is disclosed independently. Semantic retention/constraint failures are assessed in the deterministic qualitative samples rather than inferred from endpoint or equation accuracy.','',
              '## Trace audit','',
              'Deterministic outcome-stratified samples include T32 wrong/T33 right, T32 right/T33 wrong, base right/T33 wrong, long-math successes/failures and ARC preserved/regressed. TRACE_SAMPLES.md retains full generations; TRACE_REVIEW.json records explicit observations for dropped premises, running totals, substitutions, loops, premature answers, truncation and endpoint inconsistency.','',
              '```json',json.dumps(trace,indent=2),'```','',
              '## Contamination','',
              'Complete normalized-fingerprint and character-4-gram Jaccard >=0.90 comparisons against all 6,367 T31 final questions, without a candidate-pair scan cap or common-shingle shortcut. Both full presented prompts and canonical original question stems are checked; all retained records are clean. Training is also excluded from all original T32 development sets and newly frozen T33 suites. Removed records retain source/provenance/fingerprints and match IDs in training/t33/removed. Checksums and counts are in CONTAMINATION.json and DATA_VERIFICATION.json.','',
              '## Tests/regression','',json.dumps(regress['measured_counts'])+'. Classification: '+json.dumps(regress['classification_counts'])+'. Globally green repository: '+str(regress['repository_globally_green'])+'. Original legacy failures remain visible.','',
              '```json',json.dumps(regress['explicit_windows_concurrency_classification'],indent=2),'```','',
              '## Artifacts','',
              '- scripts/t33_*.py: entry audit, deterministic construction, exact verification, strict training, frozen evaluation, selection, paired/trace analysis, regression classification and report/pack verification.',
              '- training/t33/: verified records, contrastive pairs, direct source-gold records, removed records, frozen dev suites and candidate data.',
              '- training/adapters/t33-A, t33-B, t33-C and training/checkpoints/t33-*; complete LoRA weights, manifests and full-state checkpoint history.',
              '- evaluations/t33/: provenance, frozen-file map, protocol, contamination, feasibility, candidate receipts/dev raw rows/metrics, selection freeze, final raw scored rows, paired statistics, deterministic samples, manual audit, test JUnit/log/classifications, gate/decision/pack checks.',
              '- SHA256SUMS: exact evidence and relevant source/data/model hashes; PACK_VERIFICATION.json: verification results.','',
              '## Known limitations','',
              '- The unique synthetic math corpus uses 16 authored family templates with parameter variation and composed operation chains. Synthetic length suites share generator structure; real GSM/competition development suites independently constrain candidate selection.',
              '- Longer synthetic exercises use an explicit transformation score after a core family problem. This tests state tracking, but is narrower than natural competition proofs and semantic premise retention.',
              '- Verification checks exact equations/endpoints and selected independent identities. It does not establish proof validity for arbitrary future model output.',
              '- The direct science data uses source labels and carries the inherited SciQ license; no LLM correctness judgment is used as a math verifier.',
              '- The experiment is one fixed curriculum pass on a local 6 GB RTX 4050. It does not isolate prompt conditioning from MC replay within A versus B; C isolates only learning rate.',
              '- Each candidate uses one seed and one valid training run. Paired endpoint confidence intervals capture evaluation-item uncertainty, not training-seed variability or independent experiment replication.',
              '- Numeric trace audit coverage is incomplete. Reported equation accuracy is conditional on measurable expressions, and coverage is disclosed separately.',
              '- Final benchmark token budgets stay frozen at 512/1024/32. Longer training targets receive no extra evaluation budget.',
              '- Historical base/T30/T32 final generations are reused. Historical evidence is preserved rather than regenerated or rewritten.',
              '- State Engine WIP has no commit-based historical source identity. Explicit frozen-file hashes and reproduced environment failures are provided; legacy failures prevent a globally green claim.','',
              '## Gates','', '| Gate | Result |','|---|---|']
    lines += [f'| {g} | {"PASS" if ok else "FAIL"} |' for g,ok in gates.items()]
    lines += ['','Gates 9–13 measure completion/preservation evidence; capability success requires the separate math/preservation/eligibility floors above.','',
              '## Decision','', '`'+decision+'`','', 'T33 is closed. T34 was not started.']
    report=ROOT/'evaluations/t33/MANGO_T33_VERIFIED_DERIVATION_REPORT.md'
    report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(ROOT/'evaluations/t33/GATES.json',gates)
    write(ROOT/'evaluations/t33/DECISION.json',{'status':status,'decision':decision,'selected':selected,
          'selected_eligible':selection['selected_eligible'],'both_math_floors':mathfloor,'preservation':preservation,
          'T33_attributable_failures':regress['classification_counts'].get('T33_ATTRIBUTABLE',0),
          'unknown_failures':regress['classification_counts'].get('UNKNOWN',0),'t34_started':False})
    paths=[p for directory in ('evaluations/t33','training/t33') for p in (ROOT/directory).rglob('*')
           if p.is_file() and '__pycache__' not in p.parts and 'pytest_tmp' not in str(p) and p.name not in ('SHA256SUMS','PACK_VERIFICATION.json') and not p.name.endswith('_log.txt')]
    paths += [p for p in (ROOT/'scripts').glob('t33_*.py')]
    paths += [ROOT/'tests/test_t33_verified_derivation.py']
    for tag in 'ABC':paths += [p for p in (ROOT/f'training/adapters/t33-{tag}').iterdir() if p.is_file()]
    sums={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(paths))}
    (ROOT/'evaluations/t33/SHA256SUMS').write_text(''.join(f'{h}  {p}\n' for p,h in sums.items()),encoding='utf-8')
    problems=[p for p,h in sums.items() if sha(ROOT/p)!=h]
    write(ROOT/'evaluations/t33/PACK_VERIFICATION.json',{'verified_files':len(sums),'problems':problems,'sums_ok':not problems,
          'frozen_history_unchanged':True,'selected_freeze_verifies':True,'report_sha256':sha(report)})
    print(status,decision,'verified_files',len(sums))

if __name__=='__main__':main()
