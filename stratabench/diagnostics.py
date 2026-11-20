"""Read saved failure evidence and app-owned logs without changing benchmark results."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from .common import digest, read_json, write_json

PREVIEW_BYTES = 256 * 1024
JOB_FIELDS = ('id','kind','title','state','stage','started_at','elapsed','exit_code','result_id',
              'suite','version','failure_reason','log_error')


def redact(text, values=()):
    values = [*values, *(v for k,v in os.environ.items() if any(t in k.upper() for t in ('API_KEY','ACCESS_TOKEN','SECRET')))]
    text = str(text)
    for value in sorted({v for v in values if isinstance(v,str) and len(v)>=4}, key=len, reverse=True):
        text = text.replace(value, '[redacted]')
    text = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s"\']+', r'\1[redacted]', text)
    return re.sub(r'''(?i)((?:api[_-]?key|access[_-]?token)["']?\s*[:=]\s*["']?)[^\s"',}]+''', r'\1[redacted]', text)


def short_reason(value):
    lines = [line.strip() for line in str(value or '').splitlines() if line.strip()]
    return redact(lines[0])[:240] if lines else ''


def reason_from_log(lines, exit_code=None):
    for line in reversed(lines):
        text = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        if re.search(r'(?:Error|Exception|Failed|FATAL|error)\s*:', text):
            return short_reason(text.removeprefix('Failed: ').strip())
    return f'The benchmark worker exited with code {exit_code}; open the logs for details.' if exit_code else 'The run did not finish. Open the saved errors and logs for details.'


def run_reason(manifest, counts=None, active=False):
    if active or manifest.get('status')=='complete':return ''
    for status in manifest.get('target_status',{}).values():
        if status.get('error'):return short_reason(status['error'])
    if (counts or {}).get('judge_errors'):return 'The writing judge failed to score one or more responses.'
    if (counts or {}).get('errors'):return 'One or more model requests failed. Open details to read the saved errors.'
    return 'The run ended before all evaluations finished; no specific failure was recorded.'


def contained(base, path):
    base, path = Path(base).resolve(), Path(path).resolve()
    if not path.is_relative_to(base):raise ValueError('This diagnostic file is outside its saved operation.')
    return path


def job_folder(root, id_):
    if not isinstance(id_,str) or not re.fullmatch(r'[a-f0-9]{32}',id_):raise ValueError('Choose a saved operation.')
    return contained(root, Path(root)/'.jobs'/id_)


def save_job(root, job, secrets=()):
    folder=job_folder(root,job['id'])
    write_json(folder/'job.json',{k:redact(v,secrets) if isinstance(v,str) else v for k,v in job.items() if k in JOB_FIELDS})


def saved_jobs(root):
    jobs=[]
    for path in (Path(root)/'.jobs').glob('*/job.json'):
        try:
            folder=job_folder(root,path.parent.name)
            data=read_json(contained(folder,path))
            if data.get('id')!=folder.name:continue
            jobs.append(data)
        except (OSError,ValueError,TypeError):continue
    return sorted(jobs,key=lambda j:j.get('started_at',0),reverse=True)


def failed_operations(root):
    return [j for j in saved_jobs(root) if j.get('state')=='failed' and not j.get('result_id')][:10]


def run_folder(root, id_):
    if not isinstance(id_,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,160}',id_):raise ValueError('Choose a saved run.')
    folder=contained(Path(root)/'results',Path(root)/'results'/id_)
    if not folder.is_dir():raise ValueError('This saved run was not found.')
    return folder


def collect(root, data, current_job=None):
    root=Path(root);issues=[];sources=[];run=None;job=None
    if bool(data.get('run'))==bool(data.get('job')):raise ValueError('Choose one saved run or operation.')
    if data.get('job'):
        folder=job_folder(root,data['job'])
        job=read_json(contained(folder,folder/'job.json'))
        if current_job and current_job.get('id')==data['job']:job={**job,**current_job}
        if job.get('id')!=data['job']:raise ValueError('Invalid saved operation.')
        run=job.get('result_id')
    else:run=data['run']
    folder=run_folder(root,run) if run else None

    def issue(label,message):
        if message and len(issues)<100:issues.append({'label':str(label),'message':redact(message)})

    def source(base,path,label):
        try:
            path=contained(base,path)
            if not path.is_file():return
            id_=digest([str(path)])[:24]
            if any(s['id']==id_ for s in sources):return
            sources.append({'id':id_,'label':str(label),'bytes':path.stat().st_size,'_path':path})
        except (OSError,ValueError):return

    jobs=[job] if job else [j for j in saved_jobs(root) if j.get('result_id')==run]
    for saved in jobs:
        base=job_folder(root,saved['id'])
        source(base,base/'worker.log','Activity · '+saved['id'][:8])
        if saved.get('state')=='failed':issue('Attempt '+saved['id'][:8]+' · '+saved.get('title','Worker'),saved.get('failure_reason'))
        if saved.get('log_error'):issue('Activity log could not be fully saved',saved['log_error'])
    manifest={}
    if folder:
        manifest=read_json(folder/'manifest.json')
        for target in manifest.get('targets',[]):
            base=contained(folder,folder/target['id'])
            label=target.get('label',target['id'])
            status=manifest.get('target_status',{}).get(target['id'],{})
            issue(label,status.get('error'))
            answers=contained(base,base/'answers.jsonl')
            latest={}
            if answers.is_file():
                with answers.open(encoding='utf-8') as stream:
                    for line in stream:
                        try:
                            row=json.loads(line)
                            latest[(row['case_id'],row['repeat'])]=row
                        except (ValueError,KeyError,TypeError):continue
            for row in latest.values():
                message=row.get('error') or row.get('standard_result',{}).get('judge_error') or (row.get('style_judge',{}).get('error'))
                if message:issue(f'{label} · {row["case_id"]} · repeat {row["repeat"]+1}',message)
            if base.is_dir():
                for name in ('server.log','engine.log'):
                    for path in sorted(base.rglob(name)):
                        source(base,path,label+' · '+str(path.relative_to(base)).replace(os.sep,'/'))
    reason=short_reason(issues[0]['message']) if issues else run_reason(manifest) if manifest else job.get('failure_reason','')
    if manifest.get('status')=='running':reason='The saved run is marked as running. Available output is shown below.'
    elif job and job.get('state') in ('running','stopping'):reason='This operation is still running. Available output is shown below.'
    if manifest.get('status')=='complete':reason='This run completed. Any errors below belong to saved earlier attempts.'
    return {'title':job.get('title','Benchmark details') if job else 'Benchmark details',
        'reason':reason or 'No operation failure was recorded. Individual test results are available in the test explorer.',
        'issues':issues,'logs':sources,'run':run,'state':job.get('state') if job else manifest.get('status')}


def public_details(details):
    return {**details,'logs':[{k:v for k,v in s.items() if not k.startswith('_')} for s in details['logs']]}


def log_source(root,data,current_job=None):
    details=collect(root,data,current_job)
    source=next((s for s in details['logs'] if s['id']==data.get('log')),None)
    if source is None:raise ValueError('Choose a log from this operation.')
    return source


def preview(source):
    with source['_path'].open('rb') as stream:
        size=source['_path'].stat().st_size
        stream.seek(max(0,size-PREVIEW_BYTES))
        raw=stream.read(PREVIEW_BYTES)
    return {'text':redact(raw.decode('utf-8',errors='replace')),'truncated':size>PREVIEW_BYTES,'bytes':size}
