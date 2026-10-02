"""Run closing project tests, preserving historical failures and classifying IDs."""
from collections import Counter
from pathlib import Path
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from t33_build import write
from t33_entry import failures
from t33_train import check_frozen

def main():
    out=ROOT/'evaluations/t33/regression';out.mkdir(parents=True,exist_ok=True)
    junit=out/'project_junit.xml'
    if not junit.exists():
        with (out/'project_log.txt').open('wb') as log:
            p=subprocess.run([sys.executable,'-m','pytest','--basetemp=evaluations/t33/regression/pytest_tmp',
                              '--junitxml=evaluations/t33/regression/project_junit.xml'],cwd=ROOT,
                             env=dict(os.environ,PYTHONPATH='src'),stdout=log,stderr=subprocess.STDOUT)
        print('Project pytest exit',p.returncode,flush=True)
        if not junit.exists():raise RuntimeError('Project suite did not produce a complete JUnit report')
    entry=json.loads((ROOT/'evaluations/t33/entry/REGRESSION_CLASSIFICATION.json').read_text())['failures']
    baseline=failures(ROOT/'evaluations/t31/recovery/t31_measured_tests_junit.xml')
    measured=failures(junit)
    classes={}
    for test,trace in measured.items():
        if test.startswith('tests.test_t33_'):
            cl,reason='T33_ATTRIBUTABLE','T33-specific negative control failed.'
        elif 'PermissionError' in trace and 'state_index.json' in trace:
            cl,reason='ENVIRONMENT_SPECIFIC','Reproduced pre-T33 Windows os.replace interaction in unchanged untracked State Engine WIP.'
        elif test in entry:
            cl,reason=entry[test]['classification'],entry[test]['evidence']
        elif test in baseline:
            cl,reason='PRE_EXISTING','Same test ID failed at T31 closure.'
        else:
            cl,reason='UNKNOWN','New failure requires causal review; not silently attributed to the environment.'
        classes[test]={'classification':cl,'reason':reason,'trace':trace}
    allcases=list(ET.parse(junit).iter('testcase'))
    counts={'total':len(allcases),'passed':sum(t.find('failure') is None and t.find('error') is None and t.find('skipped') is None for t in allcases),
            'failures':sum(t.find('failure') is not None for t in allcases),'errors':sum(t.find('error') is not None for t in allcases),
            'skipped':sum(t.find('skipped') is not None for t in allcases)}
    explicit={}
    for name in ('test_concurrent_observations_lose_nothing_and_never_mix','test_the_event_log_never_gains_a_torn_line','test_readers_never_see_a_half_published_state','test_concurrent_transitions_are_all_durable'):
        key='tests.test_t31_concurrency::'+name
        explicit[key]={'final_measured_result':'FAIL' if key in measured else 'PASS',
                       'final_classification':classes[key]['classification'] if key in classes else entry[key]['classification'],
                       'entry_reproduced':entry[key]['entry_reproduced']}
    record={'measured_counts':counts,'classification_counts':dict(Counter(r['classification'] for r in classes.values())),
            'failures':classes,'explicit_windows_concurrency_classification':explicit,
            'repository_globally_green':not classes,'command':'PYTHONPATH=src python -m pytest --basetemp=evaluations/t33/regression/pytest_tmp --junitxml=evaluations/t33/regression/project_junit.xml'}
    write(out/'CLASSIFICATION.json',record);check_frozen()
    print(json.dumps({'measured_counts':counts,'classification_counts':record['classification_counts']},indent=2))

if __name__=='__main__':main()
