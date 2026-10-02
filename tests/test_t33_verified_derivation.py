"""Negative controls for the experimental data and measurable trace claims."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from t33_build import make,verify
from t33_evaluate import expression_audit

def test_contradictory_intermediate_state_is_rejected():
    record=make('systems of equations',1024,'long')
    record['verified_steps'][1]['value']='-999'
    with pytest.raises(AssertionError): verify(record)

def test_false_endpoint_is_rejected_even_with_correct_steps():
    record=make('probability',2198,'medium')
    record['final_answer']='1'
    with pytest.raises(AssertionError): verify(record)

def test_trace_arithmetic_error_is_measured_without_assuming_semantic_proof():
    result=expression_audit('20 + 5 = 25\n25 - 3 = 25\nFinal answer: 25',[])
    assert result['numeric_equations_observed']==2
    assert result['numeric_equations_correct']==1
    assert result['premise_retention'].startswith('NOT_AUTOMATICALLY_ESTABLISHED')

def test_trace_parser_does_not_execute_model_text(tmp_path):
    marker=tmp_path/'model_text_executed'
    result=expression_audit(f"__import__('pathlib').Path({str(marker)!r}).write_text('bad') = 1",[])
    assert not marker.exists()
    assert result['numeric_equations_observed']==0

def test_endpoint_inconsistency_is_separate_from_arithmetic_correctness():
    steps=[{'expression':'25-3','value':'22','description':'updated count'}]
    result=expression_audit('25 - 3 = 22\nFinal answer: 25',steps,'25')
    assert result['numeric_equations_correct']==1
    assert result['final_answer_consistency_on_observed_final_state'] is False

def test_candidate_c_changes_only_learning_rate():
    import json
    root=Path(__file__).resolve().parents[1]
    cfg=json.loads((root/'evaluations/t33/PROTOCOL.json').read_text())['candidates']
    b,c=dict(cfg['B']),dict(cfg['C'])
    assert b.pop('learning_rate')==1e-4
    assert c.pop('learning_rate')==3e-5
    assert b==c
    assert (root/'training/t33/candidates/B/train.jsonl').read_bytes()==(root/'training/t33/candidates/C/train.jsonl').read_bytes()
