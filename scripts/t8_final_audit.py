"""Audit T8 coverage and recompute integration aggregates without generation."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from run_rag_eval_t5r import GEN_ELIGIBLE_CATEGORIES, summarize_variant
from sciencemath.tools.benchmark import summarize, verifier_selftest, load_suite
from sciencemath.evaluation.capacity import migration_decision

OUT = ROOT / 'evaluations/t8'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]


def coverage(preds, expected):
    ids = [p['eval_id'] for p in preds]
    assert len(ids) == len(set(ids)) and set(ids) == expected, 'coverage mismatch'
    assert not any(p.get('error') for p in preds), 'execution errors'


def main():
    result = {'recorded_at': datetime.now(timezone.utc).isoformat(),
              'frozen_suites': {}, 'integration': {}, 'input_sha256': {}}
    for rel in ['evaluations/tool-suite/v1', 'evaluations/rag-suite/v1',
                'evaluations/t8/capacity-suite/v1']:
        directory = ROOT / rel
        checks = read(directory / 'checksum.json')
        lines = [l for l in (directory / 'questions.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
        assert len(lines) == len(checks)
        for line in lines:
            assert checks[json.loads(line)['eval_id']] == hashlib.sha256(line.encode()).hexdigest()
        result['frozen_suites'][rel] = {'questions': len(lines), 'ok': True}
    tool_ids = {r['eval_id'] for r in rows(ROOT / 'evaluations/tool-suite/v1/questions.jsonl')}
    rag_ids = {r['eval_id'] for r in rows(ROOT / 'evaluations/rag-suite/v1/questions.jsonl')
               if r['category'] in GEN_ELIGIBLE_CATEGORIES}
    assert len(tool_ids) == 150 and len(rag_ids) == 58
    for label in ('qwen3-4b-instruct', 'phi4-mini-reasoning'):
        run = OUT / 'runs' / label
        summary = read(run / 't4_arm_summary.json')
        for arm in ('t4_notool', 't4_tool'):
            predictions = rows(run / arm / 'predictions.jsonl')
            coverage(predictions, tool_ids)
            assert all(p['model_id'] == summary['model'] for p in predictions)
        comp = summarize(run / 't4_notool/predictions.jsonl', run / 't4_tool/predictions.jsonl')
        assert comp == summary['comparison'], 'T4 aggregate mismatch'
        rag = {}
        for arm in ('NORAG', 'G'):
            predictions = rows(run / 't5r' / arm / 'predictions.jsonl')
            coverage(predictions, rag_ids)
            config = read(run / 't5r' / arm / 'config.json')
            assert config['model_id'] == summary['model'] and config['adapter'] is None
            metrics = summarize_variant(arm, predictions)
            assert metrics == read(run / 't5r' / arm / 'metrics.json'), 'RAG aggregate mismatch'
            rag[arm] = metrics
        result['integration'][label] = {'t4': comp, 't5r': rag}
    safety = verifier_selftest(load_suite(ROOT / 'evaluations/tool-suite/v1'))
    assert safety['critical_gate'] == 'PASS'
    result['verifier_selftest'] = safety
    recomputed = read(OUT / 'recomputed_metrics.json')
    assert recomputed['all_agree'] and len(recomputed['runs']) == 5
    result['model_only_recomputation_ok'] = True
    reload = read(OUT / 'training_feasibility/reload_verification.json')
    assert all(reload[str(b)]['ok'] for b in (1, 2))
    result['checkpoint_reload'] = reload
    selection = read(OUT / 'pareto_analysis.json')
    vectors = selection['capability_vectors']
    decisions = {}
    for label, old in selection['migration_recommendations'].items():
        decision, reason = migration_decision(vectors[label], vectors['qwen3-1.7b-control'], license_status=old['license_gate'])
        assert decision == old['decision'] == 'DO_NOT_MIGRATE'
        decisions[label] = {'decision': decision, 'reason': reason}
    result['migration_recomputed'] = decisions
    import xml.etree.ElementTree as ET
    tests = {key: 0 for key in ('tests', 'failures', 'errors', 'skipped')}
    for suite in ET.parse(OUT / 'final_tests.xml').getroot().iter('testsuite'):
        for key in tests:
            tests[key] += int(suite.get(key, 0))
    assert tests['tests'] > 0 and tests['failures'] == tests['errors'] == 0
    result['tests'] = tests
    for path in sorted((OUT / 'runs').rglob('*.json*')):
        result['input_sha256'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    result['ok'] = True
    (OUT / 'final_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PASS: 5 capacity runs, 600 T4 predictions, 232 eligible RAG predictions, frozen suites and checkpoint reloads')


if __name__ == '__main__':
    main()
