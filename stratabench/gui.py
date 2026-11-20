"""Local-only GUI server. The existing CLI owns benchmark execution and cleanup."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import contextlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit
import uuid
import webbrowser

from .common import ROOT, capture, hardware, local_lock, read_json, save_settings, settings, write_json
from . import budgets, datasets, versions
from .version_order import apply_order, ordered_names
from .reference_scores import catalog as reference_catalog, reference_rows
from .estimates import TimingHistory
from .platforms import is_locked, process_options, stop_tree, windows, find_python
from . import acquisition
from . import standard_suites
from . import common, diagnostics, format_analysis, prompts, question_lab

ASSETS = ROOT / 'stratabench' / 'web'
INSTANCE = ROOT / '.gui-instance.json'


def benchmark_locked():
    return is_locked(ROOT / '.run.lock')


def setup_status(state, configs):
    has_versions = bool(state.get('versions'))
    return {'show_welcome': not state.get('setup_welcome_seen', False) and not has_versions,
            'source_configured': bool(state.get('strata_source')) or has_versions,
            'has_versions': has_versions, 'has_configs': bool(configs)}


class AnswerIndex:
    """Incremental, read-only index. Never truncate a runner's partial final line."""
    def __init__(self):
        self.files = {}

    def rows(self, path, cases=None, revision=None):
        if not path.exists():
            self.files.pop(path, None)
            return {}
        stat = path.stat()
        index = self.files.get(path)
        if not index or index.get('revision')!=revision or index['inode'] != stat.st_ino or stat.st_size < index['size'] or (
                stat.st_size == index['size'] and stat.st_mtime_ns != index['mtime']):
            index = {'inode': stat.st_ino, 'pos': 0, 'rows': {},'revision':revision}
            self.files[path] = index
        with path.open('rb') as stream:
            stream.seek(index['pos'])
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line.endswith(b'\n'):
                    break
                try:
                    row = json.loads(line)
                    key = (row['case_id'], row['repeat'])
                    status = ('errors' if row.get('error') else 'cutoffs' if row.get('truncated')
                              else 'rated' if row.get('correct') is None and row.get('standard_result',{}).get('suite')=='writingbench'
                              else 'passed' if row.get('correct') else 'incorrect')
                    previous = index['rows'].get(key, {})
                    index['rows'][key] = {'status': status, 'offset': offset, 'bytes': len(line),
                        'format_error':format_analysis.inspect((cases or {}).get(row['case_id'],{}),row),
                        'attempts': previous.get('attempts', 0)+1,
                        'elapsed_seconds': row.get('elapsed_seconds', 0),
                        'unparsed': bool(row.get('unparsed')) and status != 'errors',
                        'json_format': bool(row.get('json_format')),'judge_error':row.get('style_judge',{}).get('status')=='error' or bool(row.get('standard_result',{}).get('judge_error'))}
                except (ValueError, KeyError, TypeError):
                    raise ValueError('A saved answer is damaged. The original file has been preserved.') from None
                index['pos'] = stream.tell()
        index.update(size=stat.st_size, mtime=stat.st_mtime_ns)
        return index['rows']


def result_path(name):
    """Accept result IDs, never arbitrary paths supplied by a web page."""
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,160}', name):
        raise ValueError('Choose a saved run from the list.')
    path = (ROOT / 'results' / name).resolve()
    if not path.is_relative_to((ROOT / 'results').resolve()) or not path.is_dir():
        raise ValueError('That saved run could not be found.')
    return path


def number(data, name, default, minimum, maximum, integer=True):
    value = data.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f'{name.replace("_", " ")} must be a number.')
    try:
        result = int(value) if integer else float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f'Check the value for {name.replace("_", " ")}.') from None
    if not minimum <= result <= maximum:
        raise ValueError(f'{name.replace("_", " ")} must be between {minimum} and {maximum}.')
    return result


def config_catalog():
    items = [x for x in versions.discover() if not x['alias']]
    imported = ROOT / 'user-configs'
    if imported.exists():
        items += versions.discover(imported)
    out = []
    for item in items:
        args = item.pop('args')
        def flag(name):
            i = args.index(name)+1 if name in args else len(args)
            return args[i] if i < len(args) else None
        item.update(context=budgets.context_limit({'args':args}), budget_context_limit=budgets.context_limit({'args':args}), kv=flag('--kv'), spec=flag('--spec'),
                    imported=Path(item['path']).parent == imported)
        item['id'] = item['path']
        item['vision'] = bool(read_json(item['path']).get('vision'))
        out.append(item)
    return out


def run_command(data, validate_judge=True):
    """Only supported structured options can become CLI arguments; there is no shell."""
    profile = data.get('profile', 'quick')
    if profile not in (*datasets.PROFILES, 'custom'):
        raise ValueError('Choose a benchmark preset.')
    reasoning = data.get('reasoning', 'xhigh')
    if reasoning not in ('off', 'low', 'medium', 'high', 'xhigh', 'default'):
        raise ValueError('Choose a reasoning setting.')
    version_state = settings()
    available = version_state['versions']
    selected = data.get('versions', [])
    if not isinstance(selected, list) or not selected or any(x not in available for x in selected):
        raise ValueError('Select at least one prepared Strata version.')
    selected = [name for name in ordered_names(version_state) if name in selected]
    known = {c['id'] for c in config_catalog()}
    configs = data.get('configs', [])
    if not isinstance(configs, list) or not configs or any(x not in known for x in configs):
        raise ValueError('Select at least one model configuration.')
    cmd = ['run', '--versions', *dict.fromkeys(selected), '--configs', *dict.fromkeys(configs),
           '--profile', 'smoke' if profile == 'custom' else profile, '--reasoning', reasoning,
           '--repeats', str(number(data, 'repeats', 1, 1, 100)),
           '--seed', str(number(data, 'seed', 20261119, 1, 2147483547)),
           '--temperature', str(number(data, 'temperature', 0, 0, 2, False)),
           '--timeout', str(number(data, 'timeout', 1800, 10, 86400)),
           '--startup-timeout', str(number(data, 'startup_timeout', 900, 10, 7200))]
    if data.get('max_tokens') not in ('', None, 'auto'):
        cmd += ['--max-tokens', str(number(data, 'max_tokens', 16384, 1, 262144))]
    levels = data.get('difficulties', datasets.DIFFICULTIES)
    if profile not in standard_suites.SPECS and (not isinstance(levels, list) or not levels or any(x not in datasets.DIFFICULTIES for x in levels)):
        raise ValueError('Select at least one difficulty level.')
    if profile not in ('custom',*standard_suites.SPECS) and set(levels) != set(datasets.DIFFICULTIES):
        cmd += ['--only', ','.join(dict.fromkeys(levels))]
    if profile == 'context':
        words = str(data.get('context_words', '2000 8000 16000 32000')).replace(',', ' ').split()
        if not words or len(words) > 12:
            raise ValueError('Choose 1–12 context sizes, separated by spaces.')
        for word in words:
            number({'words': word}, 'words', 2000, 100, 500000)
        cmd += ['--context-words', *words]
    if profile == 'custom':
        name = data.get('tasks_id', '')
        if not re.fullmatch(r'[a-f0-9]{32}\.jsonl', str(name)) or not (ROOT / 'user-tasks' / name).is_file():
            raise ValueError('Choose a custom question file first.')
        cmd += ['--tasks', str(ROOT / 'user-tasks' / name)]
    if data.get('selection_id'):
        path=question_lab.selection_path(ROOT,data['selection_id'])
        question_lab.load_selection(path,profile,int(data.get('seed',20261119)))
        cmd += ['--question-selection',str(path)]
    if profile in standard_suites.SPECS:
        if not standard_suites.enabled(profile,version_state):raise ValueError('Enable '+standard_suites.SPECS[profile]['name']+' in Benchmark library first.')
        if type(data.get('standard_full',False)) is not bool:raise ValueError('Choose a full split or a seeded sample.')
        cmd += ['--standard-limit',str(0 if data.get('standard_full') else number(data,'standard_limit',50,1,100000))]
        if profile=='swebench':cmd += ['--swe-test-timeout',str(number(data,'swe_test_timeout',900,30,3600))]
    if profile in ('tools','coding','swebench'):
        cmd += ['--agent-turns',str(number(data,'agent_turns',30 if profile=='swebench' else 8,1,64 if profile=='swebench' else 32))]
    if profile=='coding':
        image=str(data.get('coding_image','python:3.12-slim'))
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,250}',image):raise ValueError('Invalid coding runtime image.')
        cmd += ['--coding-image',image]
    if validate_judge and (profile=='writingbench' or profile=='writing' and data.get('style_judge_enabled')):
        endpoint=str(data.get('style_judge_endpoint','')).strip();model=str(data.get('style_judge_model','')).strip()
        parsed=urlsplit(endpoint)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or not model or len(model)>200:
            raise ValueError('The writing judge needs an HTTP(S) endpoint without embedded credentials and a model name.')
        cmd += ['--style-judge-endpoint',endpoint,'--style-judge-model',model]
    budget_options=budgets.options_from_form(data)
    if not budget_options['thinking_budgets_default']:
        cmd += ['--thinking-budgets',json.dumps(budget_options['thinking_budgets'])]
    return cmd


class App:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.job = None
        self.judge_keys = {}
        self.proc = None
        self.server = None
        self.closed = False
        self.answers = AnswerIndex()
        self.saved_cases = {}
        self.hardware = hardware()
        self.timing_history = TimingHistory(ROOT)
        self.question_library = question_lab.Library(ROOT)
        self.profiles = []
        self.profile_counts = {}
        self.groups = set()
        names = {'smoke': ('Smoke test', 'A small workflow check across five levels.'),
                 'quick': ('Quick comparison', 'Screen your versions and configs.'),
                 'standard': ('Standard', 'A stronger comparison of your shortlist.'),
                 'deep': ('Deep evaluation', 'More coverage, including all AIME problems.'),
                 'full': ('Full suite', 'Every included question. A substantial run.'),
                 'context': ('Long context', 'Find answers buried in long documents.'),
                 'writing':('Writing style','Writing constraints, with optional independent quality judging.'),
                 'vision':('Vision','Generated visual counting, spatial and chart questions.'),
                 'tools':('Tool use','Bounded, multi-step function-calling workflows.'),
                 'coding':('Agentic coding','Read, edit and test small Python projects in Docker.')}
        for key, (name, description) in names.items():
            try:
                cases = datasets.select(key)
                self.profile_counts[key] = Counter(c['difficulty'] for c in cases)
                self.groups.update(c.get('group','custom') for c in cases)
                count = len(cases)
            except (ValueError, RuntimeError, OSError):
                count = None
            self.profiles.append({'id': key, 'name': name, 'description': description, 'count': count})
        self.public_ready = all(p['count'] is not None for p in self.profiles) and self.public_files_present()
        self.refresh_standard_library()

    def refresh_standard_library(self):
        self.profiles=[p for p in self.profiles if p['id'] not in standard_suites.SPECS]
        for item in standard_suites.catalog():
            self.profile_counts[item['id']]={'unrated':item.get('installed_count') or item['count']}
            if item['enabled']:
                self.profiles.append({'id':item['id'],'name':item['name'],'description':item['description'],
                    'count':item.get('installed_count'),'standard_suite':True,'ready':item['ready'],'optional':item.get('optional',False)})

    def public_files_present(self):
        return (ROOT / 'datasets/sources.lock.json').is_file() and all(
            (ROOT / 'datasets/raw' / name).is_file() for name, *_ in datasets.sources())

    def refresh_public_library(self):
        if self.public_ready or not self.public_files_present():
            return
        for profile in self.profiles:
            if profile['id'] in standard_suites.SPECS:continue
            cases = datasets.select(profile['id'])
            profile['count'] = len(cases)
            self.profile_counts[profile['id']] = Counter(c['difficulty'] for c in cases)
            self.groups.update(c.get('group','custom') for c in cases)
        self.public_ready = True

    def outcomes(self, folder, data=None, summary_only=False):
        """Read the saved plan and latest attempt for every evaluation, including pending work."""
        data = data or {}
        with self.lock:
            manifest = read_json(folder / 'manifest.json')
            case_path = folder / 'cases.json'
            stamp = (case_path.stat().st_mtime_ns, case_path.stat().st_size)
            if self.saved_cases.get(folder, (None,))[0] != stamp:
                self.saved_cases[folder] = (stamp, read_json(case_path))
            cases = self.saved_cases[folder][1]
            counts = dict.fromkeys(('passed', 'incorrect', 'cutoffs', 'errors', 'pending', 'unparsed', 'judge_errors','format_errors'), 0)
            case_map={c['id']:c for c in cases}
            if any(c.get('score_only') for c in cases):counts['rated']=0
            entries, targets = [], []
            for ti, target in enumerate(manifest['targets']):
                target_dir = (folder / target['id']).resolve()
                if not target_dir.is_relative_to(folder.resolve()):
                    raise ValueError('This saved run has an invalid combination folder.')
                path = target_dir / 'answers.jsonl'
                rows = self.answers.rows(path,case_map,stamp)
                targets.append({'id': str(ti), 'label': target['label']})
                for repeat in range(manifest['options']['repeats']):
                    for ci, case in enumerate(cases):
                        row = rows.get((case['id'], repeat), {})
                        status = row.get('status', 'pending')
                        counts[status] += 1
                        if row.get('format_error'):counts['format_errors']+=1
                        if row.get('judge_error'):counts['judge_errors']+=1
                        if row.get('unparsed'):
                            counts['unparsed'] += 1
                        if not summary_only:
                            entries.append({'key': f'{ti}.{ci}.{repeat}', 'case_id': case['id'],
                                'target': str(ti), 'label': target['label'], 'repeat': repeat+1,
                                'group': case.get('group', 'custom'), 'difficulty': case.get('difficulty', 'easy'),
                                'preview': case.get('prompt', '')[:180], 'status': status,
                                'attempts': row.get('attempts', 0), 'elapsed_seconds': row.get('elapsed_seconds'),
                                'unparsed': row.get('unparsed', False),'judge_error':row.get('judge_error',False), '_case': case, '_row': row, '_path': path})
                            entries[-1]['format_error']=row.get('format_error')
            total = sum(counts.get(k,0) for k in ('passed', 'incorrect', 'cutoffs', 'errors', 'pending','rated'))
            owned = bool(self.job and self.job.get('result_id') == folder.name and self.job['state'] in ('running', 'stopping'))
            locked = benchmark_locked()
            active = owned or (manifest['status'] == 'running' and locked)
            remaining = counts['pending'] + counts['errors']
            if manifest['options'].get('profile')=='writingbench':remaining+=counts['judge_errors']
            result = {'id': folder.name, 'counts': counts, 'total': total,
                'completed': total-counts['pending'], 'remaining': remaining, 'active': active,
                'resumable': not active and (remaining > 0 or manifest['status'] != 'complete'),
                'resume_blocked': locked,
                'status': 'interrupted' if manifest['status'] == 'running' and not active else manifest['status']}
            result['failure_reason']=diagnostics.run_reason(manifest,counts,active)
            if summary_only:
                return result
            if data.get('key') is not None:
                entry = next((e for e in entries if e['key'] == data['key']), None)
                if not entry:
                    raise ValueError('Choose a test from this run.')
                row = {}
                if entry['_row']:
                    with entry['_path'].open('rb') as stream:
                        stream.seek(entry['_row']['offset'])
                        row = json.loads(stream.read(entry['_row']['bytes']))
                return {'test': {k: v for k, v in entry.items() if not k.startswith('_')},
                        'case': entry['_case'], 'answer': row,
                        'system_prompts':prompts.system_messages(entry['_case'],row.get('request'))}
            category = data.get('category', 'all')
            if category not in ('all', *counts):
                raise ValueError('Choose a valid test category.')
            query = str(data.get('search', '')).strip().casefold()[:300]
            filtered = [e for e in entries if (category == 'all' or e['status'] == category or category == 'unparsed' and e['unparsed'] or category == 'judge_errors' and e['judge_error'] or category=='format_errors' and e['format_error'])
                and (not data.get('target') or e['target'] == str(data['target']))
                and (not data.get('difficulty') or e['difficulty'] == data['difficulty'])
                and (not data.get('group') or e['group'] == data['group'])
                and (not query or query in (e['case_id']+' '+e['_case'].get('prompt', '')+' '+e['label']).casefold())]
            offset = number(data, 'offset', 0, 0, max(total, 1))
            limit = number(data, 'limit', 30, 1, 100)
            result.update(targets=targets, groups=sorted({e['group'] for e in entries}),
                matched=len(filtered), offset=offset, limit=limit,
                tests=[{k: v for k, v in e.items() if not k.startswith('_')} for e in filtered[offset:offset+limit]])
            return result

    def runs(self):
        items = []
        for path in sorted((ROOT / 'results').glob('*/manifest.json'), reverse=True):
            try:
                m = read_json(path)
                summary_path = path.parent / 'summary.json'
                s = read_json(summary_path) if summary_path.exists() else {}
                ranking = s.get('ranking', [])
                complete = [r for r in ranking if r.get('complete')]
                live = self.outcomes(path.parent, summary_only=True)
                judge=(m['options'].get('style_judge_endpoint'),m['options'].get('style_judge_model'))
                judge_key_needed=bool(m['options'].get('style_judge_key_required') and not (self.judge_keys.get(judge) or os.environ.get('STRATABENCH_JUDGE_API_KEY')))
                items.append({'id': path.parent.name, 'created': m['created'], 'status': m['status'],
                    'profile': m['options']['profile'], 'reasoning': m['options']['reasoning'],
                    'question_selection':m['options'].get('question_selection'),
                    'standard_benchmark':m['options'].get('standard_benchmark'),
                    'repeats': m['options']['repeats'], 'questions': m['case_count'],
                    'combinations': len(m['targets']), 'targets': [t['label'] for t in m['targets']],
                    'best': complete[0] if complete else None,
                    'ranking': ranking, 'judge_key_needed':judge_key_needed,'judge_endpoint':judge[0],'judge_model':judge[1], 'has_report': (path.parent / 'report.html').exists(),
                    'comparison_key': s.get('comparison_key'),
                    'errors': live['counts']['errors'], 'cutoffs': live['counts']['cutoffs'], **live})
            except (ValueError, KeyError, OSError):
                continue
        return items

    def state(self):
        s = settings()
        self.refresh_standard_library()
        with contextlib.suppress(OSError, ValueError, RuntimeError):
            self.refresh_public_library()
        with self.lock:
            job = dict(self.job) if self.job else None
            if job:
                job['elapsed'] = time.time() - job['started_at'] if job['state'] in ('running', 'stopping') else job.get('elapsed', 0)
                if job['kind'] == 'add-version':
                    path = ROOT / 'versions' / job['version'] / 'build.log'
                    if path.exists():
                        with path.open('rb') as f:
                            f.seek(max(0, path.stat().st_size-16000))
                            job['build_log'] = f.read().decode(errors='replace')
        refs = reference_catalog()
        refs['rows'] = reference_rows(self.groups)
        runs = self.runs()
        if job and job.get('result_id') and job['kind'] in ('run', 'resume'):
            saved = next((r for r in runs if r['id'] == job['result_id']), None)
            if saved:
                job.update(completed=saved['completed'], total=saved['total'], counts=saved['counts'],
                           passed=saved['counts']['passed'], failed=saved['counts']['incorrect']+saved['counts']['cutoffs'],
                           errors=saved['counts']['errors'], resumable=saved['resumable'])
        configs = config_catalog()
        return {'versions': [{'name': name, 'kind': s['versions'][name]['kind'], 'created': s['versions'][name].get('created'),
                              'commit': s['versions'][name].get('git', '')[:12]} for name in ordered_names(s)],
                'configs': configs, 'profiles': self.profiles, 'profile_counts': self.profile_counts,
                'thinking_budget_defaults': {p:budgets.defaults(p) for p in (*datasets.PROFILES,'custom')},
                'benchmark_library': standard_suites.catalog(s),
                'benchmark_settings': standard_suites.library_settings(s),
                'hardware': self.hardware, 'runs': runs, 'job': job,
                'failed_operations':diagnostics.failed_operations(ROOT),
                'references': refs, 'version_sort_mode': s.get('version_sort_mode','newest'),
                'strata_root': s['strata_root'], 'default_reasoning': 'xhigh',
                'strata_source': acquisition.preferences(s),
                'setup': setup_status(s, configs),
                'platform': 'Windows' if windows() else 'Linux',
                'datasets_ready': self.public_ready}

    def start(self, kind, command, title, env_overrides=None, **extra):
        with self.lock:
            if self.job and self.job['state'] in ('running', 'stopping'):
                raise ValueError('An operation is already running. Stop it or wait for it to finish.')
            env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
            env['STRATABENCH_SETTINGS_FILE']=str(common.STATE)
            env.update(env_overrides or {})
            secret_values=[self.token,*[v for k,v in env.items() if any(t in k.upper() for t in ('KEY','TOKEN','SECRET'))]]
            job = {'id': uuid.uuid4().hex, 'kind': kind, 'title': title, 'state': 'running',
                   'started_at': time.time(), 'stage': 'Preparing', 'logs': [], 'completed': 0,
                   'passed': 0, 'failed': 0, 'errors': 0, 'total': 0, **extra}
            folder=diagnostics.job_folder(ROOT,job['id'])
            folder.mkdir(parents=True,exist_ok=True)
            log_path=folder/'worker.log'
            log_path.write_text('',encoding='utf-8')
            self.job=job
            diagnostics.save_job(ROOT,job,secret_values)
            try:
                proc = subprocess.Popen([find_python(), str(ROOT / 'bench'), *command], cwd=ROOT,
                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', bufsize=1, **process_options())
            except OSError as error:
                message=diagnostics.redact(str(error),secret_values)
                job.update(state='failed',stage='Could not start the worker',failure_reason=message,elapsed=time.time()-job['started_at'])
                log_path.write_text(message+'\n',encoding='utf-8')
                diagnostics.save_job(ROOT,job,secret_values)
                raise
            self.proc = proc
            threading.Thread(target=self.watch, args=(proc, job, log_path, secret_values), daemon=True).start()
            return {'ok': True, 'job_id': job['id']}

    def watch(self, proc, job, log_path=None, secret_values=()):
        writer=None
        if log_path:
            try:writer=log_path.open('a',encoding='utf-8')
            except OSError as error:job['log_error']=str(error)
        try:
            for raw in proc.stdout:
                raw=diagnostics.redact(raw,secret_values)
                if writer:
                    try:writer.write(raw);writer.flush()
                    except OSError as error:job['log_error']=str(error)
                line = raw.rstrip()
                if not line:
                    continue
                with self.lock:
                    job['logs'] = (job['logs'] + [line])[-350:]
                    if line.startswith('Benchmark setup: '):job['stage']=line.removeprefix('Benchmark setup: ')
                    if line.startswith('Results: '):
                        job['result_id'] = Path(line[9:]).name
                        with contextlib.suppress(OSError,ValueError):diagnostics.save_job(ROOT,job,secret_values)
                    count = re.match(r'(\d+) questions × (\d+) repeat\(s\) × (\d+) combination', line)
                    if count:
                        job['total'] = int(count[1])*int(count[2])*int(count[3])
                    progress = re.match(r'\s*(\d+)/(\d+)\s+(PASS|FAIL|ERROR|RATED)\s+(.+?)\s+\(([\d.]+)s\)', line)
                    if progress:
                        job['completed'] += 1
                        if progress[3]!='RATED':job[{'PASS': 'passed', 'FAIL': 'failed', 'ERROR': 'errors'}[progress[3]]] += 1
                        job['stage'] = 'Evaluating questions'
                        job['last_question'] = progress[4]
                        job['last_result'] = progress[3]
                    elif 'Loading model (' in line:
                        job['stage'] = 'Loading the model'
                    elif 'Ready. Running' in line:
                        job['stage'] = 'Model ready · warming up'
                    elif line.startswith('v') and ' / ' in line:
                        job['current_target'] = line
                    elif 'Downloading' in line:
                        job['stage'] = 'Downloading files'
                    elif 'Building ' in line:
                        job['stage'] = 'Building the engine'
            proc.wait()
        finally:
            if writer:
                try:writer.close()
                except OSError as error:job['log_error']=str(error)
            proc.stdout.close()
            if job['kind'] in ('prepare-suite','check-suite') and job.get('suite') and (job['state']=='stopping' or proc.returncode!=0):
                with contextlib.suppress(OSError,ValueError):
                    previous=standard_suites.operation_status(job['suite'])
                    if previous.get('state') not in ('failed','interrupted'):
                        standard_suites.finish_operation(job['suite'],'interrupted' if job['state']=='stopping' else 'failed',
                            'Setup stopped. Choose Retry setup to continue.' if job['state']=='stopping' else 'Setup failed. Open Activity for details, then choose Retry setup.')
            if job['kind'] in ('run','resume') and job.get('result_id') and job['state']=='stopping':
                with contextlib.suppress(OSError,ValueError,subprocess.SubprocessError):standard_suites.cleanup_run(job['result_id'])
            with self.lock:
                stopped = job['state'] == 'stopping'
                job['state'] = 'stopped' if stopped else 'complete' if proc.returncode == 0 else 'failed'
                if not stopped and job.get('result_id') and job['kind'] in ('run', 'resume'):
                    manifest_path = ROOT / 'results' / job['result_id'] / 'manifest.json'
                    with contextlib.suppress(OSError, ValueError, KeyError):
                        result_state = read_json(manifest_path)['status']
                        if result_state != 'complete':
                            job['state'] = 'stopped' if result_state == 'interrupted' else 'failed'
                            job['failure_reason']=diagnostics.run_reason(read_json(manifest_path))
                job['exit_code'] = proc.returncode
                job['elapsed'] = time.time() - job['started_at']
                job['stage'] = {'stopped': 'Stopped · answers saved', 'complete': 'Complete', 'failed': 'Needs attention'}[job['state']]
                if job['state']=='failed' and (proc.returncode != 0 or not job.get('failure_reason')):
                    job['failure_reason']=diagnostics.reason_from_log(job['logs'],proc.returncode)
                with contextlib.suppress(OSError,ValueError):diagnostics.save_job(ROOT,job,secret_values)
                self.proc = None

    def stop(self):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return {'ok': True}
            proc = self.proc
            self.job['state'] = 'stopping'
            self.job['stage'] = 'Stopping safely · saving answers'
            # Runner catches SIGINT and closes its separately grouped model server in finally.
            if windows():
                threading.Thread(target=stop_tree, args=(proc,), daemon=True).start()
            else:
                stop_tree(proc, interrupt=True)
            return {'ok': True}

    def action(self, route, data):
        if route == '/api/questions':
            with self.lock:return self.question_library.browse(data)
        if route == '/api/question-selection':
            with self.lock:return self.question_library.save(data)
        if route == '/api/setup-welcome':
            with local_lock('.prepare.lock'):
                state = settings()
                state['setup_welcome_seen'] = True
                save_settings(state)
            return {'ok': True}
        if route == '/api/prepare-coding':
            image=str(data.get('image','python:3.12-slim'))
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,250}',image):raise ValueError('Invalid coding runtime image.')
            return self.start('coding-runtime',['prepare-coding','--image',image],'Preparing isolated coding runtime')
        if route == '/api/strata-source':
            with local_lock('.prepare.lock'):
                cfg = acquisition.configure(data)
            return {'ok': True, 'settings': cfg}
        if route == '/api/strata-release':
            cfg = acquisition.validate(data)
            tag = versions.safe_name(str(data.get('tag','latest')).strip())
            release = acquisition.release_info(cfg,tag)
            return {'tag':release['tag_name'], 'assets':[{'name':a['name'],'bytes':a.get('size',0),
                'digest':a.get('digest')} for a in acquisition.compatible_assets(release,cfg)]}
        if route == '/api/strata-detect':
            cfg = acquisition.preferences()
            candidates = [data.get('folder'),cfg['folder'],os.environ.get('STRATABENCH_STRATA_ROOT'),
                os.environ.get('STRATA_HOME'),str(ROOT.parent / 'Strata'),str(Path.home() / 'Strata')]
            import shutil
            found = shutil.which('strata')
            if found:candidates += [str(Path(found).parent),str(Path(found).parent.parent)]
            detected = []
            for value in dict.fromkeys(x for x in candidates if x):
                try:
                    path = Path(value).expanduser().resolve()
                    runtime = acquisition.runtime_source(path)
                    engine = acquisition.local_engine(path)
                    detected.append({'folder':str(path),'server':str(runtime / 'serve/server.py'), 'engine':str(engine)})
                except (ValueError,OSError):
                    continue
            return {'candidates':detected}
        if route == '/api/outcomes':
            return self.outcomes(result_path(data.get('id')), data)
        if route == '/api/version-order':
            with local_lock('.prepare.lock'):
                state = settings()
                apply_order(state, data.get('mode','newest'), data.get('order'))
                save_settings(state)
            return {'ok': True, 'order': ordered_names(state)}
        if route == '/api/budget-compatibility':
            return self.budget_compatibility(data)
        if route == '/api/diagnostics':
            return diagnostics.public_details(diagnostics.collect(ROOT,data,self.job))
        if route == '/api/diagnostic-log':
            return diagnostics.preview(diagnostics.log_source(ROOT,data,self.job))
        if route == '/api/estimate':
            return self.estimate(data)
        if route=='/api/optional-swebench':
            if type(data.get('enabled')) is not bool:raise ValueError('Choose whether to enable SWE-bench.')
            if benchmark_locked() or self.proc and self.proc.poll() is None:raise ValueError('Wait for the current operation before changing benchmark settings.')
            with local_lock('.prepare.lock'):
                standard_suites.configure({'enabled_suites':{'swebench':data['enabled']}})
            return {'ok':True,'enabled':data['enabled']}
        if route in ('/api/benchmark-settings','/api/benchmark-suite'):
            if benchmark_locked() or self.proc and self.proc.poll() is None:raise ValueError('Wait for the current operation before changing benchmark settings.')
            if route.endswith('benchmark-suite'):
                data={'enabled_suites':{data.get('suite'):data.get('enabled')}}
            with local_lock('.prepare.lock'):
                result=standard_suites.configure(data)
            return {'ok':True,'settings':result}
        if route in ('/api/prepare-suite','/api/check-suite'):
            suite=data.get('suite')
            if suite not in standard_suites.SPECS:raise ValueError('Choose a standard suite.')
            if benchmark_locked():raise ValueError('Wait for the active benchmark before changing its downloaded suites.')
            if route.endswith('prepare-suite') and suite=='swebench' and not standard_suites.enabled(suite):raise ValueError('Enable optional SWE-bench before preparing it.')
            action='check-suite' if route.endswith('check-suite') else 'prepare-suite'
            return self.start(action,[action,suite],('Checking ' if action=='check-suite' else 'Preparing ')+standard_suites.SPECS[suite]['name'],suite=suite)
        if route == '/api/run':
            command=run_command(data)
            check=self.budget_compatibility(data)
            if check['invalid']:raise ValueError('Apply the thinking budgets and deselect incompatible configurations before starting.')
            if data.get('profile') in standard_suites.SPECS:standard_suites.verify(data['profile'])
            overrides={}
            if data.get('profile') in ('writing','writingbench') and (data.get('style_judge_enabled') or data.get('profile')=='writingbench') and data.get('style_judge_key'):
                key=data['style_judge_key']
                if not isinstance(key,str) or len(key)>8192:raise ValueError('Invalid judge API key.')
                self.judge_keys[(str(data['style_judge_endpoint']).strip().rstrip('/'),str(data['style_judge_model']).strip())]=key
                overrides['STRATABENCH_JUDGE_API_KEY']=key
            elif data.get('profile') in ('writing','writingbench') and (data.get('style_judge_enabled') or data.get('profile')=='writingbench'):
                key=self.judge_keys.get((str(data.get('style_judge_endpoint','')).strip().rstrip('/'),str(data.get('style_judge_model','')).strip()))
                if key:overrides['STRATABENCH_JUDGE_API_KEY']=key
            return self.start('run', command, 'Benchmark in progress',env_overrides=overrides)
        if route == '/api/stop':
            return self.stop()
        if route == '/api/add-version':
            tag = versions.safe_name(str(data.get('tag', '')).strip())
            if tag in settings()['versions']:
                raise ValueError('This version is already ready to use.')
            jobs = number(data, 'jobs', acquisition.preferences()['build_jobs'], 1, 64)
            return self.start('add-version', ['add-version', tag, '--jobs', str(jobs)], 'Preparing '+tag, version=tag)
        if route == '/api/import-version':
            name = versions.safe_name(str(data.get('name', '')).strip())
            source = Path(str(data.get('source', ''))).expanduser().resolve()
            acquisition.runtime_source(source)
            cmd = ['snapshot', '--name', name, '--source', str(source)]
            for field in ('exe', 'python'):
                if data.get(field):
                    cmd += ['--'+field, str(Path(data[field]).expanduser().absolute())]
            return self.start('snapshot', cmd, 'Importing '+name)
        if route in ('/api/resume', '/api/report'):
            folder = result_path(data.get('id'))
            if route.endswith('report') and benchmark_locked():
                raise ValueError('Wait for the active benchmark to finish or stop before rebuilding a report.')
            progress = {};overrides={}
            if route.endswith('resume'):
                options=read_json(folder/'manifest.json')['options']
                identity=(options.get('style_judge_endpoint'),options.get('style_judge_model'))
                if identity[0]:
                    key=data.get('style_judge_key') or self.judge_keys.get(identity) or os.environ.get('STRATABENCH_JUDGE_API_KEY')
                    if key:
                        if not isinstance(key,str) or len(key)>8192:raise ValueError('Invalid judge API key.')
                        self.judge_keys[identity]=key;overrides['STRATABENCH_JUDGE_API_KEY']=key
                    elif options.get('style_judge_key_required'):
                        raise ValueError('Re-enter the API key for this run’s original writing judge before resuming.')
                saved = self.outcomes(folder, summary_only=True)
                if saved['active'] or saved['resume_blocked']:
                    raise ValueError('A benchmark is already running. Stop it or wait for it to finish before resuming.')
                if not saved['resumable']:
                    raise ValueError('This benchmark is already finished. All saved answers are available to inspect.')
                progress = {'completed': saved['completed'], 'passed': saved['counts']['passed'],
                    'failed': saved['counts']['incorrect']+saved['counts']['cutoffs'],
                    'errors': saved['counts']['errors'], 'total': saved['total']}
            return self.start('resume' if route.endswith('resume') else 'report',
                              ['resume' if route.endswith('resume') else 'report', str(folder)],
                              'Resuming benchmark' if route.endswith('resume') else 'Updating report', result_id=folder.name, env_overrides=overrides, **progress)
        if route == '/api/compare':
            if benchmark_locked():raise ValueError('Wait for the active benchmark to finish or stop before rebuilding a comparison report.')
            ids = data.get('ids', [])
            if not isinstance(ids, list) or len(set(ids)) < 2:
                raise ValueError('Select at least two saved runs to compare.')
            folders = [result_path(x) for x in dict.fromkeys(ids)]
            from .report import comparison_key
            if len({comparison_key(read_json(p / 'manifest.json')) for p in folders}) != 1:
                raise ValueError('These runs use different questions or settings. Select matching runs for a fair comparison.')
            name = 'comparison-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4]
            return self.start('compare', ['compare', *map(str, folders), '--output', str(ROOT / 'results' / name)],
                              'Creating comparison', result_id=name)
        if route == '/api/datasets':
            return self.start('datasets', ['datasets'], 'Preparing public benchmarks')
        if route == '/api/doctor':
            return self.start('doctor', ['doctor'], 'Checking your PC')
        if route == '/api/root':
            path = Path(str(data.get('path', ''))).expanduser().resolve()
            if not (path / 'serve/server.py').exists():
                raise ValueError('This folder does not contain a Strata installation.')
            return self.start('init', ['init', '--strata-root', str(path)], 'Rescanning model configurations')
        if route == '/api/import-file':
            return self.import_file(data)
        if route == '/api/quit':
            if self.proc and self.proc.poll() is None:
                raise ValueError('Stop the active operation before closing the app.')
            threading.Thread(target=self.shutdown, daemon=True).start()
            return {'ok': True}
        raise ValueError('This action is not available.')

    def budget_compatibility(self,data):
        profile=data.get('profile','quick')
        if profile not in (*datasets.PROFILES,'custom'):raise ValueError('Choose a benchmark preset.')
        if data.get('reasoning','xhigh') not in ('off','low','medium','high','xhigh','default'):raise ValueError('Choose a reasoning setting.')
        options=budgets.options_from_form(data)
        selected=data.get('configs',[])
        known={c['id']:c for c in config_catalog()}
        if not isinstance(selected,list) or any(not isinstance(c,str) or c not in known for c in selected):raise ValueError('Choose known model configurations.')
        levels=data.get('difficulties',datasets.DIFFICULTIES)
        if not isinstance(levels,list) or any(l not in datasets.DIFFICULTIES for l in levels):raise ValueError('Choose difficulty levels.')
        if data.get('selection_id'):
            selection=question_lab.load_selection(question_lab.selection_path(ROOT,data['selection_id']),profile,int(data.get('seed',20261119)))
            levels=list({c['difficulty'] for c in selection['cases']})
        elif profile in standard_suites.SPECS:levels=['unrated']
        elif profile=='custom':
            name=data.get('tasks_id','')
            if not re.fullmatch(r'[a-f0-9]{32}\.jsonl',str(name)) or not (ROOT/'user-tasks'/name).is_file():raise ValueError('Choose a custom question file first.')
            levels=list({json.loads(line)['difficulty'] for line in (ROOT/'user-tasks'/name).read_text(encoding='utf-8').splitlines() if line.strip()})
        elif profile=='context':
            words=str(data.get('context_words','2000 8000 16000 32000')).replace(',',' ').split()
            if not words or len(words)>12:raise ValueError('Choose 1–12 context sizes.')
            counts={'medium' if number({'words':w},'words',2000,100,500000)<=8000 else 'very_hard' for w in words}
            levels=[l for l in levels if l in counts]
        elif self.profile_counts.get(profile):levels=[l for l in levels if self.profile_counts[profile].get(l,0)]
        return budgets.compatibility([known[c] for c in dict.fromkeys(selected)],options,levels)

    def estimate(self, data):
        # Reuse run validation, but this endpoint never starts an engine or downloads data.
        run_command({**data,'style_judge_enabled':False},validate_judge=False)
        if data.get('all_suites'):
            result = self.estimate({**data,'all_suites':False})
            result['suites'] = {}
            for key in datasets.PROFILES:
                try:
                    result['suites'][key] = self.estimate({**data,'profile':key,'selection_id':None,'all_suites':False})
                except ValueError as error:
                    result['suites'][key] = {'profile':key,'error':str(error)}
            return result
        profile = data.get('profile','quick')
        selected = set(data.get('versions',[]))
        names = [name for name in ordered_names(settings()) if name in selected]
        configs = {c['id']:c for c in config_catalog()}
        difficulties = set(data.get('difficulties',datasets.DIFFICULTIES))
        options = {**data,**budgets.options_from_form(data)}
        if data.get('selection_id'):
            selection=question_lab.load_selection(question_lab.selection_path(ROOT,data['selection_id']),profile,int(data.get('seed',20261119)))
            counts=Counter(c['difficulty'] for c in selection['cases'])
            difficulties=set(counts)
        elif profile == 'context':
            words = [int(x) for x in str(data.get('context_words','2000 8000 16000 32000')).replace(',',' ').split()]
            counts = Counter()
            for word in words:
                counts['medium' if word<=8000 else 'very_hard'] += 3
            options['context_words_list'] = words
        elif profile == 'custom':
            path = ROOT/'user-tasks'/data['tasks_id']
            counts = Counter(json.loads(line)['difficulty'] for line in path.read_text(encoding='utf-8').splitlines() if line.strip())
            difficulties = set(datasets.DIFFICULTIES)
        else:
            counts = self.profile_counts.get(profile)
            if counts is None:
                raise ValueError('Download this suite before estimating its duration.')
        counts = {k:v for k,v in counts.items() if k in difficulties or profile in standard_suites.SPECS}
        if profile in standard_suites.SPECS and not data.get('standard_full') and not data.get('selection_id'):
            counts={'unrated':min(sum(counts.values()),int(data.get('standard_limit') or 50))}
        if not sum(counts.values()):
            raise ValueError('No questions in this suite match the selected difficulty levels.')
        budgets.validate(options,counts)
        with self.lock:
            self.timing_history.refresh()
            rows = [self.timing_history.estimate(configs[config],name,counts,options)
                    for name in names for config in dict.fromkeys(data['configs'])]
        return {'profile':profile,'questions':sum(counts.values()),'combinations':len(rows),'rows':rows,
                'lower_seconds':sum(r['lower_seconds'] for r in rows),
                'upper_seconds':sum(r['upper_seconds'] for r in rows),
                'notice':'Approximate wall-clock range including loading and warm-up. Builds/downloads are excluded. Unmeasured settings use an RTX 3080 / 64 GB planning baseline; other hardware and long reasoning can differ substantially. Local timing history improves these estimates.'}

    def import_file(self, data):
        kind, content = data.get('kind'), data.get('content')
        if not isinstance(content, str) or len(content.encode()) > 4*1024*1024:
            raise ValueError('Choose a text file smaller than 4 MB.')
        if kind == 'config':
            cfg = json.loads(content.lstrip('\ufeff'))
            if not isinstance(cfg, dict) or not isinstance(cfg.get('args'), list) or not cfg.get('exe'):
                raise ValueError('This file is not a Strata model configuration.')
            if not cfg.get('cwd') or not Path(cfg['cwd']).is_absolute():
                raise ValueError('Imported configs must include an absolute cwd so model paths resolve correctly.')
            filename = re.sub(r'[^a-zA-Z0-9_.-]', '-', str(data.get('name', 'model'))).removesuffix('.json')
            filename = 'strata-' + filename.removeprefix('strata-')[:80] + '-' + uuid.uuid4().hex[:6] + '.json'
            path = ROOT / 'user-configs' / filename
            write_json(path, cfg)
            return {'ok': True, 'id': str(path)}
        if kind == 'tasks':
            from .cli import cases_for
            path = ROOT / 'user-tasks' / (uuid.uuid4().hex+'.jsonl')
            path.parent.mkdir(exist_ok=True)
            path.write_text(content, encoding='utf-8')
            try:
                cases = cases_for('smoke', 20261119, task_file=path)
            except Exception:
                path.unlink()
                raise
            return {'ok': True, 'id': path.name, 'count': len(cases), 'name': str(data.get('name', 'Custom questions'))}
        raise ValueError('Choose a config JSON or question JSONL file.')

    def shutdown(self):
        self.closed = True
        if self.server:
            self.server.shutdown()


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def host_ok(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def authorized(self):
            if not self.host_ok():
                return False
            if secrets.compare_digest(self.headers.get('X-StrataBench-Key', ''), app.token):
                return True
            c = cookies.SimpleCookie()
            with contextlib.suppress(cookies.CookieError):
                c.load(self.headers.get('Cookie', ''))
            return 'stratabench' in c and secrets.compare_digest(c['stratabench'].value, app.token)

        def send(self, code, content, type_='application/json; charset=utf-8', headers=None):
            body = json.dumps(content, ensure_ascii=False).encode() if isinstance(content, (dict, list)) else content
            self.send_response(code)
            self.send_header('Content-Type', type_)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if self.host_ok() and path == '/launch/'+app.token:
                self.send(303, b'', headers={'Location': '/', 'Set-Cookie': 'stratabench='+app.token+'; HttpOnly; SameSite=Strict; Path=/'})
                return
            # Opening the normal local address in a fresh browser must establish its
            # own session. API calls remain authenticated and mutation requests keep
            # their Origin/CSRF checks; no special launch URL is needed for the UI.
            if self.host_ok() and path == '/':
                self.send(200, (ASSETS / 'index.html').read_bytes(), 'text/html; charset=utf-8',
                          headers={'Set-Cookie': 'stratabench='+app.token+'; HttpOnly; SameSite=Strict; Path=/'})
                return
            if not self.authorized():
                self.send(403, {'error': 'Open StrataBench using its desktop launcher.'})
                return
            try:
                if path == '/api/ping':
                    self.send(200, {'app': 'StrataBench'})
                elif path == '/api/state':
                    self.send(200, app.state())
                elif path == '/api/diagnostic-log/download':
                    data={k:v[0] for k,v in parse_qs(urlsplit(self.path).query).items() if len(v)==1}
                    source=diagnostics.log_source(ROOT,data,app.job)
                    self.send_response(200)
                    self.send_header('Content-Type','text/plain; charset=utf-8')
                    self.send_header('Content-Disposition','attachment; filename="stratabench-'+source['id']+'.log"')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.end_headers()
                    with source['_path'].open(encoding='utf-8',errors='replace') as stream:
                        for line in stream:
                            try:self.wfile.write(diagnostics.redact(line).encode('utf-8'))
                            except (BrokenPipeError,ConnectionResetError):break
                elif path.startswith('/files/'):
                    parts = path.split('/')
                    if len(parts) != 4 or parts[3] not in ('report.html', 'summary.json', 'leaderboard.csv', 'reference-scores.csv', 'report.txt','system-prompts.json'):
                        raise ValueError('This report file is not available.')
                    file = result_path(parts[2]) / parts[3]
                    self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                elif path in ('/', '/app.js', '/helpers.js', '/budgets.js', '/outcomes.js', '/setup.js', '/diagnostics.js', '/lab.js', '/style.css', '/icon.svg'):
                    file = ASSETS / ('index.html' if path == '/' else path[1:])
                    self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'text/plain')
                else:
                    self.send(404, {'error': 'Page not found.'})
            except (ValueError, OSError) as e:
                self.send(404, {'error': str(e)})

        def do_POST(self):
            origin = self.headers.get('Origin')
            trusted_origins = (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
            if not self.authorized() or origin and origin not in trusted_origins or self.headers.get('X-StrataBench-Request') != '1':
                self.send(403, {'error': 'This request must come from your StrataBench window.'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 6*1024*1024:
                    raise ValueError('The selected file or request is too large.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected an object.')
                self.send(200, app.action(urlsplit(self.path).path, data))
            except (ValueError, OSError, KeyError, TypeError, RuntimeError) as e:
                self.send(400, {'error': str(e)})
    return Handler


def notify_error(message):
    if windows():
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(message), 'StrataBench', 0x10)
    elif capture(['which', 'zenity'])['ok']:
        subprocess.run(['zenity', '--error', '--title=StrataBench', '--text='+str(message)], check=False)


def launch(open_browser=True, port=18770):
    """A desktop launcher starts/reuses a detached local server and opens the browser."""
    from .common import request_json
    if INSTANCE.exists():
        with contextlib.suppress(OSError, ValueError, KeyError):
            info = read_json(INSTANCE)
            import urllib.request
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(info['url']+'/api/ping', headers={'X-StrataBench-Key': info['token']})
            with opener.open(req, timeout=2) as f:
                if json.load(f).get('app') == 'StrataBench':
                    if open_browser:
                        webbrowser.open(info['url'])
                    return info
    log_path = ROOT / '.gui.log'
    with log_path.open('a') as log:
        process = subprocess.Popen([find_python(), '-m', 'stratabench.gui', '--serve', '--port', str(port)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **process_options())
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError('StrataBench could not start. '+log_path.read_text(errors='replace')[-2000:])
        if INSTANCE.exists():
            with contextlib.suppress(OSError, ValueError, KeyError):
                info = read_json(INSTANCE)
                if info['pid'] == process.pid:
                    if open_browser:
                        webbrowser.open(info['url'])
                    return info
        time.sleep(.1)
    raise RuntimeError('StrataBench is taking too long to start. See '+str(log_path))


def serve(port=18770):
    with local_lock('.gui.lock'):
        app = App()
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), handler(app))
        except OSError:
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(app))
        app.server = server
        write_json(INSTANCE, {'pid': os.getpid(), 'url': f'http://127.0.0.1:{server.server_port}', 'token': app.token})
        INSTANCE.chmod(0o600)
        try:
            server.serve_forever(poll_interval=.25)
        except KeyboardInterrupt:
            app.stop()
        finally:
            if app.proc and app.proc.poll() is None:
                app.stop()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    app.proc.wait(timeout=30)
            server.server_close()
            INSTANCE.unlink(missing_ok=True)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--serve', action='store_true')
    p.add_argument('--port', type=int, default=18770)
    p.add_argument('--no-browser', action='store_true')
    a = p.parse_args()
    try:
        serve(a.port) if a.serve else launch(not a.no_browser, a.port)
    except Exception as e:
        if not a.serve:
            notify_error(str(e))
        raise
