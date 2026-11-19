"""SWE-bench container tools and the pinned upstream resolution grader."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid


def owner(root):return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:20]


def client_for(root):
    import docker
    client=docker.from_env(timeout=180)
    if client.info().get('OSType')!='linux':raise ValueError('SWE-bench requires Docker in Linux-container mode.')
    return client


def spec_for(case):
    from swebench.harness.test_spec.test_spec import make_test_spec
    spec=make_test_spec(case['upstream'],namespace='swebench')
    if spec.arch!='x86_64':raise ValueError('This integration requires the upstream x86-64 Linux issue images.')
    return spec


def container_for(root,name):
    if not isinstance(name,str) or not name.startswith('stratabench-swe-'):raise ValueError('Invalid task container.')
    container=client_for(root).containers.get(name)
    if container.labels.get('stratabench.owner')!=owner(root):raise ValueError('This container belongs to another workspace.')
    return container


def create(root,image,run_id=None):
    if not image.startswith('sha256:'):raise ValueError('SWE-bench requires a pinned image ID.')
    client=client_for(root)
    labels={'stratabench.owner':owner(root),'stratabench.suite':'swebench'}
    if run_id:labels['stratabench.run']=run_id
    container=client.containers.create(image,name='stratabench-swe-'+uuid.uuid4().hex,
        command=['/bin/bash','-lc','sleep 14400'],detach=True,network_mode='none',
        cap_drop=['ALL'],security_opt=['no-new-privileges'],mem_limit='4g',memswap_limit='4g',
        nano_cpus=2_000_000_000,pids_limit=256,labels=labels,
        working_dir='/testbed')
    container.start()
    return container


def copy_text(container,path,text):
    content=text.encode();buff=io.BytesIO()
    with tarfile.open(fileobj=buff,mode='w') as tar:
        info=tarfile.TarInfo(Path(path).name);info.size=len(content);info.mode=0o644;tar.addfile(info,io.BytesIO(content))
    container.put_archive(str(Path(path).parent).replace('\\','/'),buff.getvalue())


def execute(container,command,timeout=120):
    if not isinstance(command,str) or len(command)>50000:raise ValueError('Command exceeds 50 KB.')
    import os
    opts={'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0)} if os.name=='nt' else {}
    proc=subprocess.Popen(['docker','exec','-w','/testbed',container.name,'/bin/bash','-lc',command],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**opts)
    output=bytearray();overflow=threading.Event()
    def collect():
        while True:
            block=proc.stdout.read(4096)
            if not block:break
            if len(output)+len(block)>2*1024*1024:overflow.set();proc.kill();break
            output.extend(block)
    thread=threading.Thread(target=collect,daemon=True);thread.start()
    try:
        proc.wait(timeout=timeout);thread.join(5)
        if overflow.is_set():
            container.kill();raise RuntimeError('Task command exceeded 2 MB of output; container stopped.')
        return {'exit_code':proc.returncode,'output':output.decode('utf-8',errors='replace')}
    except subprocess.TimeoutExpired:
        container.kill();proc.kill();raise RuntimeError('Task command timed out; container stopped.')
    finally:
        if proc.poll() is None:proc.kill()
        proc.wait();thread.join(5);proc.stdout.close()


def operation(op,root,data):
    if op=='images':
        import docker
        client=client_for(root);images={}
        for case in data['cases']:
            spec=spec_for(case);print('Preparing SWE-bench image: '+spec.instance_image_key,flush=True)
            try:image=client.images.get(spec.instance_image_key)
            except docker.errors.ImageNotFound:
                image=client.images.pull(spec.instance_image_key)
            images[case['id']]=image.id
        return images
    if op=='verify_images':
        client=client_for(root)
        for image in data['images'].values():client.images.get(image)
        return {'ok':True}
    if op=='open':
        c=create(root,data['image'],data.get('run_id'))
        try:
            result=execute(c,'git status --short && git rev-parse HEAD')
            return {'container':c.name,'repository':result['output']}
        except BaseException:c.remove(force=True);raise
    if op=='close':
        import docker
        try:container_for(root,data['container']).remove(force=True)
        except docker.errors.NotFound:pass
        return {'ok':True}
    if op=='command':
        result=execute(container_for(root,data['container']),data['command'],min(int(data.get('timeout',120)),120))
        result['output']=result['output'][-24000:]
        return result
    if op=='patch':
        c=container_for(root,data['container'])
        result=execute(c,'git add -N . && git -c core.fileMode=false diff --no-ext-diff --binary')
        if len(result['output'].encode())>1024*1024:raise ValueError('Patch exceeds 1 MB.')
        return {'patch':result['output']}
    if op=='evaluate':
        from swebench.harness.grading import get_eval_report
        spec=spec_for(data['case']);patch=data['patch']
        if not patch.strip():return {'resolved':False,'reason':'The agent produced no patch.'}
        c=create(root,data['image'],data.get('run_id'))
        try:
            copy_text(c,'/tmp/stratabench.patch',patch)
            applied=execute(c,'git apply --verbose /tmp/stratabench.patch')
            if applied['exit_code']:
                applied=execute(c,'git apply --verbose --reject /tmp/stratabench.patch')
            if applied['exit_code']:return {'resolved':False,'patch_applied':False,'output':applied['output'][-10000:]}
            copy_text(c,'/tmp/stratabench-eval.sh',spec.eval_script)
            log=execute(c,'/bin/bash /tmp/stratabench-eval.sh',timeout=int(data.get('test_timeout',900)))
            with tempfile.TemporaryDirectory(dir=root) as tmp:
                path=Path(tmp)/'test_output.txt';path.write_text(log['output'],encoding='utf-8')
                prediction={'instance_id':spec.instance_id,'model_name_or_path':'stratabench','model_patch':patch}
                report=get_eval_report(spec,prediction,str(path),include_tests_status=True)[spec.instance_id]
            return {**report,'output':log['output'][-24000:]}
        finally:c.remove(force=True)
    raise ValueError('Unknown SWE-bench operation.')
