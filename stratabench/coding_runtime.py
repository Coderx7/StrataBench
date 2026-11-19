"""Run generated Python only in resource-limited Linux Docker containers."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import uuid

from .common import capture
from .platforms import quiet_options

DEFAULT_IMAGE='python:3.12-slim'
WORKER = r'''
import contextlib, importlib.util, io, json, sys
p=json.load(sys.stdin)
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec=importlib.util.spec_from_file_location('solution','/work/solution.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        result=getattr(mod,p['function'])(*p['args'])
    print(json.dumps({'value':result},allow_nan=False))
except BaseException as e:
    print(json.dumps({'error':type(e).__name__+': '+str(e)[:500]}))
'''
HARNESS = r'''
import json, pathlib, subprocess, sys
p=json.load(sys.stdin)
pathlib.Path('/work/solution.py').write_text(p['code'],encoding='utf-8')
def same(a,b):
    if type(a) is bool or type(b) is bool:return type(a) is type(b) and a==b
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):return a==b
    if type(a) is not type(b):return False
    if isinstance(a,list):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    if isinstance(a,dict):return a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
    return a==b
results=[]
for test in p['tests']:
    try:
        child=subprocess.run([sys.executable,'-I','-c',p['worker']],
            input=json.dumps({'function':p['function'],'args':test['args']}),
            text=True,capture_output=True,timeout=2)
        result=json.loads(child.stdout)
        ok='value' in result and same(result['value'],test['expected'])
        results.append({'passed':ok,'error':result.get('error') if not ok else None})
    except BaseException as e:results.append({'passed':False,'error':type(e).__name__})
print(json.dumps({'nonce':p['nonce'],'passed':sum(r['passed'] for r in results),'total':len(results),'tests':results}))
'''


def image_id(image=DEFAULT_IMAGE):
    if not isinstance(image,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,250}',image):
        raise ValueError('Use a Docker image name, digest, or local image ID.')
    if not shutil.which('docker'):raise RuntimeError('Agentic coding needs Docker with Linux containers. Configure Docker, then prepare the coding runtime in Setup.')
    os_info=capture(['docker','info','--format','{{.OSType}}'],timeout=8)
    if not os_info['ok'] or os_info['output']!='linux':raise RuntimeError('Start Docker in Linux-container mode before running coding tests.')
    found=capture(['docker','image','inspect','--format','{{.Id}}',image],timeout=8)
    if not found['ok'] or not re.fullmatch(r'sha256:[a-f0-9]{64}',found['output']):
        raise RuntimeError('The coding runtime image is not ready. Use Prepare coding runtime in Setup first.')
    return found['output']


def prepare(image=DEFAULT_IMAGE):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,250}',str(image)):raise ValueError('Invalid Docker image name.')
    subprocess.run(['docker','pull',image],check=True,**quiet_options())
    return image_id(image)


def run_tests(code,function,tests,image,timeout=20):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Coding requires a resolved, pinned Docker image ID.')
    if not isinstance(code,str) or len(code.encode())>100000:return {'passed':0,'total':len(tests),'error':'Source file exceeds 100 KB.'}
    nonce=uuid.uuid4().hex;name='stratabench-code-'+uuid.uuid4().hex
    command=['docker','run','--rm','--pull=never','-i','--name',name,'--label','stratabench.coding=true',
        '--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
        '--memory=256m','--memory-swap=256m','--cpus=1','--pids-limit=64','--user=65534:65534',
        '--tmpfs','/work:rw,nosuid,noexec,size=16m,mode=1777','--tmpfs','/tmp:rw,nosuid,noexec,size=16m,mode=1777',
        '--workdir','/work',image,'python','-I','-c',HARNESS]
    payload={'code':code,'function':function,'tests':tests,'nonce':nonce,'worker':WORKER}
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**quiet_options())
    output=bytearray();overflow=threading.Event()
    def read():
        while True:
            block=proc.stdout.read(4096)
            if not block:break
            if len(output)+len(block)>65536:overflow.set();proc.kill();break
            output.extend(block)
    thread=threading.Thread(target=read,daemon=True);thread.start()
    try:
        proc.stdin.write(json.dumps(payload).encode());proc.stdin.close()
        proc.wait(timeout=timeout);thread.join(timeout=2)
        if overflow.is_set():return {'passed':0,'total':len(tests),'error':'Container output exceeded 64 KB.'}
        for line in output.decode('utf-8',errors='replace').splitlines():
            try:
                result=json.loads(line)
                if result.get('nonce')==nonce:
                    result.pop('nonce');return result
            except (ValueError,AttributeError):pass
        if proc.returncode==125:raise RuntimeError('Docker could not start the isolated test container: '+output.decode(errors='replace')[:500])
        return {'passed':0,'total':len(tests),'error':'Container failed or did not return a valid test result.'}
    except subprocess.TimeoutExpired:
        return {'passed':0,'total':len(tests),'error':'Container exceeded its time limit.'}
    finally:
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,**quiet_options())
        if proc.poll() is None:proc.kill()
        proc.wait(timeout=5);thread.join(timeout=2);proc.stdout.close()
