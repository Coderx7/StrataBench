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
from urllib.parse import unquote, urlsplit
import uuid
import webbrowser

from .common import ROOT, capture, hardware, local_lock, read_json, save_settings, settings, write_json
from . import datasets, versions
from .version_order import apply_order, ordered_names
from .reference_scores import catalog as reference_catalog, reference_rows
from .estimates import TimingHistory
from .platforms import is_locked, process_options, stop_tree, windows, find_python
from . import acquisition

ASSETS = ROOT / 'stratabench' / 'web'
INSTANCE = ROOT / '.gui-instance.json'


def benchmark_locked():
    return is_locked(ROOT / '.run.lock')


class AnswerIndex:
    """Incremental, read-only index. Never truncate a runner's partial final line."""
    def __init__(self):
        self.files = {}

    def rows(self, path):
        if not path.exists():
            self.files.pop(path, None)
            return {}
        stat = path.stat()
        index = self.files.get(path)
        if not index or index['inode'] != stat.st_ino or stat.st_size < index['size'] or (
                stat.st_size == index['size'] and stat.st_mtime_ns != index['mtime']):
            index = {'inode': stat.st_ino, 'pos': 0, 'rows': {}}
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
                              else 'passed' if row.get('correct') else 'incorrect')
                    previous = index['rows'].get(key, {})
                    index['rows'][key] = {'status': status, 'offset': offset, 'bytes': len(line),
                        'attempts': previous.get('attempts', 0)+1,
                        'elapsed_seconds': row.get('elapsed_seconds', 0),
                        'unparsed': bool(row.get('unparsed')) and status != 'errors',
                        'json_format': bool(row.get('json_format'))}
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
        item.update(context=flag('--max-context'), kv=flag('--kv'), spec=flag('--spec'),
                    imported=Path(item['path']).parent == imported)
        item['id'] = item['path']
        out.append(item)
    return out


def run_command(data):
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
    if not isinstance(levels, list) or not levels or any(x not in datasets.DIFFICULTIES for x in levels):
        raise ValueError('Select at least one difficulty level.')
    if profile != 'custom' and set(levels) != set(datasets.DIFFICULTIES):
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
    return cmd


class App:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.job = None
        self.proc = None
        self.server = None
        self.closed = False
        self.answers = AnswerIndex()
        self.saved_cases = {}
        self.hardware = hardware()
        self.timing_history = TimingHistory(ROOT)
        self.profiles = []
        self.profile_counts = {}
        self.groups = set()
        names = {'smoke': ('Smoke test', 'A small workflow check across five levels.'),
                 'quick': ('Quick comparison', 'Screen your versions and configs.'),
                 'standard': ('Standard', 'A stronger comparison of your shortlist.'),
                 'deep': ('Deep evaluation', 'More coverage, including all AIME problems.'),
                 'full': ('Full suite', 'Every included question. A substantial run.'),
                 'context': ('Long context', 'Find answers buried in long documents.')}
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

    def public_files_present(self):
        return (ROOT / 'datasets/sources.lock.json').is_file() and all(
            (ROOT / 'datasets/raw' / name).is_file() for name, *_ in datasets.sources())

    def refresh_public_library(self):
        if self.public_ready or not self.public_files_present():
            return
        for profile in self.profiles:
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
            counts = dict.fromkeys(('passed', 'incorrect', 'cutoffs', 'errors', 'pending', 'unparsed'), 0)
            entries, targets = [], []
            for ti, target in enumerate(manifest['targets']):
                target_dir = (folder / target['id']).resolve()
                if not target_dir.is_relative_to(folder.resolve()):
                    raise ValueError('This saved run has an invalid combination folder.')
                path = target_dir / 'answers.jsonl'
                rows = self.answers.rows(path)
                targets.append({'id': str(ti), 'label': target['label']})
                for repeat in range(manifest['options']['repeats']):
                    for ci, case in enumerate(cases):
                        row = rows.get((case['id'], repeat), {})
                        status = row.get('status', 'pending')
                        counts[status] += 1
                        if row.get('unparsed'):
                            counts['unparsed'] += 1
                        if not summary_only:
                            entries.append({'key': f'{ti}.{ci}.{repeat}', 'case_id': case['id'],
                                'target': str(ti), 'label': target['label'], 'repeat': repeat+1,
                                'group': case.get('group', 'custom'), 'difficulty': case.get('difficulty', 'easy'),
                                'preview': case.get('prompt', '')[:180], 'status': status,
                                'attempts': row.get('attempts', 0), 'elapsed_seconds': row.get('elapsed_seconds'),
                                'unparsed': row.get('unparsed', False), '_case': case, '_row': row, '_path': path})
            total = sum(counts[k] for k in ('passed', 'incorrect', 'cutoffs', 'errors', 'pending'))
            owned = bool(self.job and self.job.get('result_id') == folder.name and self.job['state'] in ('running', 'stopping'))
            locked = benchmark_locked()
            active = owned or (manifest['status'] == 'running' and locked)
            remaining = counts['pending'] + counts['errors']
            result = {'id': folder.name, 'counts': counts, 'total': total,
                'completed': total-counts['pending'], 'remaining': remaining, 'active': active,
                'resumable': not active and (remaining > 0 or manifest['status'] != 'complete'),
                'resume_blocked': locked,
                'status': 'interrupted' if manifest['status'] == 'running' and not active else manifest['status']}
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
                        'case': entry['_case'], 'answer': row}
            category = data.get('category', 'all')
            if category not in ('all', *counts):
                raise ValueError('Choose a valid test category.')
            query = str(data.get('search', '')).strip().casefold()[:300]
            filtered = [e for e in entries if (category == 'all' or e['status'] == category or category == 'unparsed' and e['unparsed'])
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
                items.append({'id': path.parent.name, 'created': m['created'], 'status': m['status'],
                    'profile': m['options']['profile'], 'reasoning': m['options']['reasoning'],
                    'repeats': m['options']['repeats'], 'questions': m['case_count'],
                    'combinations': len(m['targets']), 'targets': [t['label'] for t in m['targets']],
                    'best': complete[0] if complete else None,
                    'ranking': ranking, 'has_report': (path.parent / 'report.html').exists(),
                    'comparison_key': s.get('comparison_key'),
                    'errors': live['counts']['errors'], 'cutoffs': live['counts']['cutoffs'], **live})
            except (ValueError, KeyError, OSError):
                continue
        return items

    def state(self):
        s = settings()
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
        return {'versions': [{'name': name, 'kind': s['versions'][name]['kind'], 'created': s['versions'][name].get('created'),
                              'commit': s['versions'][name].get('git', '')[:12]} for name in ordered_names(s)],
                'configs': config_catalog(), 'profiles': self.profiles, 'profile_counts': self.profile_counts,
                'hardware': self.hardware, 'runs': runs, 'job': job,
                'references': refs, 'version_sort_mode': s.get('version_sort_mode','newest'),
                'strata_root': s['strata_root'], 'default_reasoning': 'xhigh',
                'strata_source': acquisition.preferences(s),
                'platform': 'Windows' if windows() else 'Linux',
                'datasets_ready': self.public_ready}

    def start(self, kind, command, title, **extra):
        with self.lock:
            if self.job and self.job['state'] in ('running', 'stopping'):
                raise ValueError('An operation is already running. Stop it or wait for it to finish.')
            env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
            proc = subprocess.Popen([find_python(), str(ROOT / 'bench'), *command], cwd=ROOT,
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1, **process_options())
            self.proc = proc
            self.job = {'id': uuid.uuid4().hex, 'kind': kind, 'title': title, 'state': 'running',
                        'started_at': time.time(), 'stage': 'Preparing', 'logs': [], 'completed': 0,
                        'passed': 0, 'failed': 0, 'errors': 0, 'total': 0, **extra}
            threading.Thread(target=self.watch, args=(proc, self.job), daemon=True).start()
            return {'ok': True, 'job_id': self.job['id']}

    def watch(self, proc, job):
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                with self.lock:
                    job['logs'] = (job['logs'] + [line])[-350:]
                    if line.startswith('Results: '):
                        job['result_id'] = Path(line[9:]).name
                    count = re.match(r'(\d+) questions × (\d+) repeat\(s\) × (\d+) combination', line)
                    if count:
                        job['total'] = int(count[1])*int(count[2])*int(count[3])
                    progress = re.match(r'\s*(\d+)/(\d+)\s+(PASS|FAIL|ERROR)\s+(.+?)\s+\(([\d.]+)s\)', line)
                    if progress:
                        job['completed'] += 1
                        job[{'PASS': 'passed', 'FAIL': 'failed', 'ERROR': 'errors'}[progress[3]]] += 1
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
            proc.stdout.close()
            with self.lock:
                stopped = job['state'] == 'stopping'
                job['state'] = 'stopped' if stopped else 'complete' if proc.returncode == 0 else 'failed'
                if not stopped and job.get('result_id') and job['kind'] in ('run', 'resume'):
                    manifest_path = ROOT / 'results' / job['result_id'] / 'manifest.json'
                    with contextlib.suppress(OSError, ValueError, KeyError):
                        result_state = read_json(manifest_path)['status']
                        if result_state != 'complete':
                            job['state'] = 'stopped' if result_state == 'interrupted' else 'failed'
                job['exit_code'] = proc.returncode
                job['elapsed'] = time.time() - job['started_at']
                job['stage'] = {'stopped': 'Stopped · answers saved', 'complete': 'Complete', 'failed': 'Needs attention'}[job['state']]
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
        if route == '/api/estimate':
            return self.estimate(data)
        if route == '/api/run':
            return self.start('run', run_command(data), 'Benchmark in progress')
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
            progress = {}
            if route.endswith('resume'):
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
                              'Resuming benchmark' if route.endswith('resume') else 'Updating report', result_id=folder.name, **progress)
        if route == '/api/compare':
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

    def estimate(self, data):
        # Reuse run validation, but this endpoint never starts an engine or downloads data.
        run_command(data)
        if data.get('all_suites'):
            result = self.estimate({**data,'all_suites':False})
            result['suites'] = {}
            for key in datasets.PROFILES:
                try:
                    result['suites'][key] = self.estimate({**data,'profile':key,'all_suites':False})
                except ValueError as error:
                    result['suites'][key] = {'profile':key,'error':str(error)}
            return result
        profile = data.get('profile','quick')
        selected = set(data.get('versions',[]))
        names = [name for name in ordered_names(settings()) if name in selected]
        configs = {c['id']:c for c in config_catalog()}
        difficulties = set(data.get('difficulties',datasets.DIFFICULTIES))
        options = dict(data)
        if profile == 'context':
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
        counts = {k:v for k,v in counts.items() if k in difficulties}
        if not sum(counts.values()):
            raise ValueError('No questions in this suite match the selected difficulty levels.')
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
                elif path.startswith('/files/'):
                    parts = path.split('/')
                    if len(parts) != 4 or parts[3] not in ('report.html', 'summary.json', 'leaderboard.csv', 'reference-scores.csv', 'report.txt'):
                        raise ValueError('This report file is not available.')
                    file = result_path(parts[2]) / parts[3]
                    self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                elif path in ('/', '/app.js', '/helpers.js', '/outcomes.js', '/setup.js', '/style.css', '/icon.svg'):
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
