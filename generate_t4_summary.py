import sys
sys.path.insert(0, 'src')
from sciencemath.tools.benchmark import load_suite, summarize, router_metrics, verifier_selftest
from pathlib import Path
import json

SUITE = 'evaluations/tool-suite/v1'
out_root = 'evaluations/t8/runs/qwen3-4b-stabilized-t4'

rows = load_suite(SUITE)

comp = summarize(
    out_root + '/t4_notool/predictions.jsonl',
    out_root + '/t4_tool/predictions.jsonl'
)

metrics = {
    'suite': 'mango-tool-eval-v1',
    'model_id': 'Qwen/Qwen3-4B-Instruct-2507',
    'verifier_selftest': verifier_selftest(rows),
    'router_metrics': router_metrics(rows),
    'comparison': comp,
}

with open(out_root + '/t4_arm_summary.json', 'w') as f:
    json.dump(metrics, f, indent=2, ensure_ascii=False)

print('=== T4.5 summary ===')
print('no-tool accuracy :', comp.get('no_tool_accuracy'))
print('tool accuracy    :', comp.get('tool_enabled_accuracy'))
print('delta            :', comp.get('delta'))
print('verdicts         :', comp.get('verdict_counts'))
print('tool usage       :', comp.get('tool_usage'))
vs = metrics['verifier_selftest']
print('false-PASS gate  :', vs['critical_gate'], '(false_pass_rate=' + str(vs['false_pass_rate']) + ')')