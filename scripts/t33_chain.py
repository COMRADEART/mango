"""Serial experiment; no T34, no runtime modifications, no recipe tuning."""
from pathlib import Path
import argparse
import ctypes
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evaluations/t33'

def run(name,script,*args):
    log=OUT/f'{name}_log.txt'
    with log.open('ab') as f:
        p=subprocess.run([sys.executable,'-u',str(ROOT/'scripts'/script),*args],cwd=ROOT,
                         env=dict(os.environ,PYTHONPATH='src',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1'),stdout=f,stderr=subprocess.STDOUT)
    print(name,'exit',p.returncode,flush=True)
    if p.returncode: raise SystemExit(p.returncode)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--wait-pid',type=int);args=ap.parse_args()
    if args.wait_pid:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x00100000,False,args.wait_pid)
        if handle:
            print('Waiting for existing A training PID',args.wait_pid,flush=True)
            try:
                while kernel.WaitForSingleObject(handle,30000)==258: pass
            finally:kernel.CloseHandle(handle)
        if not (OUT/'development/train_A.json').exists():
            raise RuntimeError('Initial A run exited without receipt; inspect interruption before restarting')
    for tag in 'ABC':
        run('train_'+tag,'t33_train.py','--candidate',tag)
        if tag=='A':
            run('baseline_development','t33_evaluate.py','--label','t32-A','--adapter-dir','training/adapters/t32-A-math-restore')
        run('development_'+tag,'t33_evaluate.py','--label','t33-'+tag,'--adapter-dir','training/adapters/t33-'+tag)
    run('selection','t33_select.py')
    selected=json.loads((OUT/'SELECTION.json').read_text())['selected']
    run('final','t33_evaluate.py','--label',selected,'--adapter-dir','training/adapters/'+selected,'--final')
    run('analysis','t33_analyze.py')
    print('Locked evaluation and analysis complete. Manual trace review and final regression classification remain.',flush=True)

if __name__=='__main__':main()
