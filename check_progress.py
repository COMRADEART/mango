import sys
sys.path.insert(0, 'src')
from sciencemath.tools.benchmark import load_suite, done_eval_ids
from pathlib import Path

SUITE = 'evaluations/tool-suite/v1'
rows = load_suite(SUITE)
print(f'Total questions: {len(rows)}')

done = done_eval_ids(Path('evaluations/t8/runs/qwen3-4b-stabilized-t4/t4_tool/predictions.jsonl'))
print(f'Done: {len(done)}')

todo = [r for r in rows if r['eval_id'] not in done]
print(f'Remaining: {len(todo)}')
if todo:
    print(f'Next: {todo[0]["eval_id"]}')