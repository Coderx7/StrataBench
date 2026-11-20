"""Explicitly prepared, revision-pinned benchmark integrations."""
from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv

from .common import ROOT, digest, file_hash, read_json, stamp, write_json, settings, save_settings
from . import common
from .platforms import quiet_options, is_locked

CACHE = ROOT / 'benchmarks'
SPECS = {
    'ifeval': dict(name='IFEval', repo='google-research/google-research', revision='c878a53ec1764bcb91a6178dc5c315202a3b5fa2',
        count=541, split='original 541 prompts', metric='Prompt strict accuracy', size='Small text dataset + isolated Python evaluator',
        description='Verifiable instruction following; official strict and loose metrics.'),
    'bfcl': dict(name='BFCL · Python single-turn', repo='ShishirPatil/gorilla', revision='6ea57973c7a6097fd7c5915698c54c17c5b1b6c8',
        count=1000, split='v4 simple_python, multiple, parallel, parallel_multiple', metric='Python AST accuracy', size='Small text datasets + isolated Python evaluator',
        description='Official Python AST categories. This is a category score, not BFCL overall.'),
    'mmmu': dict(name='MMMU · validation', repo='MMMU-Benchmark/MMMU', revision='b26bdefc7e5e007962fde8f93b2bb53c99c8d13d',
        dataset='MMMU/MMMU', dataset_revision='876ce5cb130f7f7e290ce4d9984357737d4db5cf',
        count=900, split='validation, all 30 subjects', metric='Accuracy', size='900 multimodal questions; image download can take several minutes',
        description='College-level visual understanding and reasoning, with the upstream answer parser.'),
    'writingbench': dict(name='WritingBench', repo='X-PLUG/WritingBench', revision='ae2d5176449b7b769815482641d35926f26793eb',
        count=1000, split='benchmark_all', metric='Rubric score / 100', size='Text dataset; five judge calls per response',
        description='Published writing prompts and per-question rubrics. A separately configured judge is required.'),
    'swebench': dict(name='SWE-bench Lite · optional', repo='SWE-bench/SWE-bench', revision='3f01bd622c0a22c00406139f69a234ef08225f22',
        dataset='princeton-nlp/SWE-bench_Lite', dataset_revision='6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2',
        count=300, split='test', metric='Resolved issues', optional=True, size='Plan for at least 120 GB free in Docker storage; runs can take hours or days',
        description='Real repository issue repair using the official test specification and resolution grader. Off by default.'),
}
BFCL_CATEGORIES = ('simple_python','multiple','parallel','parallel_multiple')


def preferences(state=None):
    state=settings() if state is None else state
    saved=state.get('benchmark_library',{})
    choices=saved.get('enabled_suites',{})
    return {'download_folder':saved.get('download_folder',''),
        'enabled_suites':{key:choices.get(key, bool(state.get('optional_swebench',False)) if key=='swebench' else True) for key in SPECS}}


def storage_root(state=None):
    selected=preferences(state)['download_folder']
    return Path(selected).expanduser().resolve() if selected else CACHE


def library_settings(state=None):
    result=preferences(state);root=storage_root(state)
    result.update(effective_folder=str(root),default_folder=str(CACHE))
    parent=root
    while not parent.exists() and parent!=parent.parent:parent=parent.parent
    try:result['free_bytes']=shutil.disk_usage(parent).free
    except OSError:result['free_bytes']=None
    return result


def configure(data):
    state=settings();prefs=preferences(state)
    if 'download_folder' in data:
        value=data['download_folder']
        if not isinstance(value,str) or len(value)>4096 or any(c in value for c in ('\0','\n','\r')):raise ValueError('Choose a valid benchmark download folder.')
        value=value.strip()
        if value:
            path=Path(value).expanduser()
            if not path.is_absolute():raise ValueError('Use a full folder path, or leave it empty for the app default.')
            if path.exists() and not path.is_dir():raise ValueError('The benchmark download location must be a folder.')
            parent=path
            while not parent.exists() and parent!=parent.parent:parent=parent.parent
            if not parent.is_dir():raise ValueError('The download folder’s parent must be a directory.')
            value=str(path.resolve())
        prefs['download_folder']=value
    if 'enabled_suites' in data:
        choices=data['enabled_suites']
        if not isinstance(choices,dict) or any(key not in SPECS or type(value) is not bool for key,value in choices.items()):raise ValueError('Choose which benchmark suites to include.')
        prefs['enabled_suites'].update(choices)
    state['benchmark_library']=prefs
    state['optional_swebench']=prefs['enabled_suites']['swebench']
    save_settings(state)
    return library_settings(state)


def folder(suite):
    if suite not in SPECS: raise ValueError('Unknown standard benchmark.')
    return storage_root() / suite


def python_path(root, system=None):
    system=system or ('Windows' if os.name=='nt' else 'Linux')
    return root / 'runtime' / ('Scripts/python.exe' if system=='Windows' else 'bin/python')


def enabled(suite, state=None):
    if suite not in SPECS:raise ValueError('Unknown standard benchmark.')
    return preferences(state)['enabled_suites'][suite]


def metadata(suite):
    path=folder(suite)/'ready.json'
    if not path.exists(): return None
    try:
        data=read_json(path)
        if data['revision'] != SPECS[suite]['revision'] or not python_path(folder(suite)).is_file() or not (folder(suite)/'cases.json').is_file(): return None
        return data
    except (OSError,ValueError,KeyError): return None


def operation_status(suite):
    path=folder(suite)/'installation.json'
    try:status=read_json(path)
    except (OSError,ValueError):return {}
    if status.get('state')=='running' and not is_locked(common.ROOT/'.prepare.lock'):
        return {**status,'state':'interrupted','message':'Preparation was interrupted. Choose Retry setup to continue.'}
    return status


def catalog(state=None):
    result=[]
    for key,spec in SPECS.items():
        meta=metadata(key);operation=operation_status(key)
        status='ready' if meta else 'needs_repair' if (folder(key)/'ready.json').exists() else 'not_installed'
        if operation.get('state') in ('running','failed','interrupted'):status=operation['state']
        result.append(dict(id=key,**spec,enabled=enabled(key,state),ready=bool(meta) and status=='ready',status=status,
            operation=operation,folder=str(folder(key)),installed_count=(meta or {}).get('count'),installed_bytes=(meta or {}).get('bytes',0)))
    return result


def progress(suite, action, stage, message, step=0, steps=6, state='running'):
    write_json(folder(suite)/'installation.json',{'suite':suite,'action':action,'stage':stage,'message':message,
        'step':step,'steps':steps,'state':state,'updated':stamp()})
    print(f'Benchmark setup: {stage} ({step}/{steps}) · {message}',flush=True)


def finish_operation(suite,state,message):
    previous=operation_status(suite)
    progress(suite,previous.get('action','prepare'),previous.get('stage','Setup'),message,
        previous.get('step',0),previous.get('steps',6),state)


def verify(suite):
    root=folder(suite);meta=metadata(suite)
    if not meta: raise ValueError('Prepare '+SPECS[suite]['name']+' in the benchmark library first.')
    for path,sha in meta['files'].items():
        p=root/path
        if not p.is_file() or file_hash(p)!=sha: raise RuntimeError('Benchmark files changed; prepare the suite again: '+path)
    return meta


def download(url,path,limit=32*1024*1024):
    req=urllib.request.Request(url,headers={'User-Agent':'StrataBench/1.0'})
    with urllib.request.urlopen(req,timeout=120) as response: data=response.read(limit+1)
    if len(data)>limit: raise ValueError('Benchmark source exceeded its download limit.')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)


def source_files(suite):
    if suite=='ifeval':
        return ['LICENSE']+['instruction_following_eval/'+p for p in ('instructions.py','instructions_util.py','instructions_registry.py','evaluation_lib.py','data/input_data.jsonl')]
    if suite=='mmmu':return ['LICENSE','mmmu/utils/eval_utils.py','mmmu/utils/data_utils.py','mmmu/configs/llava1.5.yaml']
    if suite=='writingbench':return ['LICENSE','prompt.py','benchmark_query/benchmark_all.jsonl']
    if suite=='bfcl':
        base='berkeley-function-call-leaderboard/'
        return ['LICENSE']+[base+'bfcl_eval/'+p for p in (
            'constants/enums.py','constants/type_mappings.py','eval_checker/ast_eval/ast_checker.py',
            'eval_checker/ast_eval/type_convertor/java_type_converter.py','eval_checker/ast_eval/type_convertor/js_type_converter.py',
            *('data/BFCL_v4_'+c+'.json' for c in BFCL_CATEGORIES),
            *('data/possible_answer/BFCL_v4_'+c+'.json' for c in BFCL_CATEGORIES))]
    return ['LICENSE']


def worker(suite, operation, data=None, timeout=600):
    root=folder(suite)
    with tempfile.TemporaryDirectory(prefix='worker-',dir=root) as tmp:
        inp=Path(tmp)/'input.json';out=Path(tmp)/'output.json';write_json(inp,data or {})
        env=dict(os.environ,HF_HOME=str(root/'hf-cache'),NLTK_DATA=str(root/'nltk_data'),PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
        command=[str(python_path(root)),str(ROOT/'stratabench'/'official_worker.py'),suite,operation,str(root),str(inp),str(out)]
        subprocess.run(command,check=True,timeout=timeout,env=env,**quiet_options())
        return read_json(out)


def prepare(suite):
    spec=SPECS[suite]
    if suite=='swebench' and not enabled(suite): raise ValueError('Enable the optional SWE-bench suite in Benchmark library first.')
    root=folder(suite);root.mkdir(parents=True,exist_ok=True)
    try:
        progress(suite,'prepare','Starting','Checking the selected download folder.',1)
        return _prepare(suite,root,spec)
    except BaseException as error:
        state='interrupted' if isinstance(error,(KeyboardInterrupt,SystemExit)) else 'failed'
        finish_operation(suite,state,'Setup stopped. Choose Retry setup to continue.' if state=='interrupted' else str(error))
        raise


def _prepare(suite,root,spec):
    # An interrupted or failed update must never leave a ready marker behind.
    (root/'ready.json').unlink(missing_ok=True)
    print('Preparing '+spec['name']+'. '+spec['size'],flush=True)
    if suite=='swebench':
        # Check Docker without pulling the coding image or any SWE images.
        system=subprocess.check_output(['docker','info','--format','{{.OSType}}'],text=True,**quiet_options()).strip()
        if system!='linux':raise ValueError('SWE-bench requires Docker running in Linux-container mode.')
        if shutil.disk_usage(root).free<120*1024**3: print('Notice: this drive has less than 120 GB free. Docker storage must have sufficient separate space.',flush=True)
    src=root/'source'
    progress(suite,'prepare','Downloading sources','Retrieving pinned benchmark files.',2)
    for path in source_files(suite):
        print('  Source: '+path,flush=True)
        download(f'https://raw.githubusercontent.com/{spec["repo"]}/{spec["revision"]}/{path}',src/path)
    progress(suite,'prepare','Preparing evaluator','Creating a private Python environment.',3)
    venv.EnvBuilder(with_pip=True).create(root/'runtime')
    requirements={'ifeval':['nltk==3.9.2','langdetect==1.0.9','immutabledict==4.2.1','absl-py==2.3.1'],
        'bfcl':[], 'mmmu':['datasets==4.4.1','Pillow==11.3.0','numpy==2.2.6','PyYAML==6.0.3'],
        'writingbench':[], 'swebench':['swebench==3.0.17']}[suite]
    progress(suite,'prepare','Installing evaluator packages','Installing only into this suite’s private environment.',4)
    if requirements:subprocess.run([str(python_path(root)),'-m','pip','install',*requirements],check=True,
        env=dict(os.environ,PIP_CACHE_DIR=str(root/'pip-cache')),**quiet_options())
    progress(suite,'prepare','Preparing dataset','Downloading and arranging the selected dataset. Images may take longer.',5)
    if suite=='swebench':
        # The installed package version and its dependency snapshot form part of provenance.
        result=worker(suite,'prepare',{'spec':spec},timeout=1800)
    else:result=worker(suite,'prepare',{'spec':spec},timeout=3600)
    progress(suite,'prepare','Checking files','Saving checksums and the evaluator package snapshot.',6)
    freeze=subprocess.check_output([str(python_path(root)),'-m','pip','freeze'],text=True,**quiet_options())
    (root/'packages.txt').write_text(freeze,encoding='utf-8')
    files={str(p.relative_to(root)).replace(os.sep,'/'):file_hash(p) for p in src.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    for p in (root/'cases.json',root/'packages.txt'):files[p.name]=file_hash(p)
    info=dict(spec,prepared_at=stamp(),count=result['count'],files=files,bytes=sum((root/p).stat().st_size for p in files))
    write_json(root/'ready.json',info)
    progress(suite,'prepare','Ready','The suite is ready to use.',6,state='complete')
    print(f'{spec["name"]} is ready: {result["count"]} cases. No model weights were changed.',flush=True)


def select(suite, seed, limit=50):
    if type(limit) is not int or not 0<=limit<=100000:raise ValueError('Choose a nonnegative standard sample size; 0 means full split.')
    if not enabled(suite):raise ValueError(SPECS[suite]['name']+' is disabled. Enable it in Benchmark library.')
    verify(suite)
    cases=read_json(folder(suite)/'cases.json')
    cases.sort(key=lambda c:digest([seed,c['id']]))
    if limit:cases=cases[:limit]
    return cases


def check(suite):
    root=folder(suite)
    if not root.exists():raise ValueError('Download and prepare this suite first.')
    try:
        progress(suite,'check','Checking files','Verifying the downloaded data and pinned source files.',1,2)
        meta=verify(suite)
        progress(suite,'check','Checking evaluator','Checking private evaluator dependencies. Nothing is downloaded.',2,2)
        subprocess.run([str(python_path(root)),'-m','pip','check'],check=True,**quiet_options())
        progress(suite,'check','Ready','All benchmark files and evaluator dependencies passed their checks.',2,2,'complete')
        return meta
    except BaseException as error:
        finish_operation(suite,'interrupted' if isinstance(error,(KeyboardInterrupt,SystemExit)) else 'failed',str(error))
        raise


def provenance(suite, cases, limit):
    meta=verify(suite)
    return {'suite':suite,'name':meta['name'],'revision':meta['revision'],'dataset_revision':meta.get('dataset_revision'),
        'source_files':meta['files'],'split':meta['split'],'full_count':meta['count'],'selected_count':len(cases),
        'selection':'full configured split' if len(cases)==meta['count'] else 'seeded sample',
        'metric':meta['metric'],'protocol':'StrataBench generation adapter + pinned upstream evaluator',
        'notice':'Published scores require matching prompts, generation settings, evaluator and agent/judge configuration.'}


def cleanup_run(run_id):
    """Clean only containers labelled for this workspace and this saved run."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}',str(run_id)):return
    owner=hashlib.sha256(str(folder('swebench').resolve()).encode()).hexdigest()[:20]
    result=subprocess.run(['docker','ps','-aq','--filter','label=stratabench.owner='+owner,
        '--filter','label=stratabench.run='+run_id],capture_output=True,text=True,timeout=15,**quiet_options())
    if result.returncode:return
    ids=[line for line in result.stdout.splitlines() if re.fullmatch('[a-f0-9]{12,64}',line)]
    if ids:subprocess.run(['docker','rm','-f',*ids],capture_output=True,timeout=30,**quiet_options())
