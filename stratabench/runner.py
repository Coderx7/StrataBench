from __future__ import annotations

import contextlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error

from .common import ROOT, digest, file_hash, hardware, read_json, request_json, stamp, write_json
from .platforms import process_options, stop_tree
from .grading import grade
from .versions import effective_config, fingerprint, vision_executable

SYSTEM = ('Solve the task accurately. You may reason before answering. End with a JSON object '
          'with exactly one key, "answer", containing your final answer. For a multiple-choice '
          'question use only the option label; for a numeric question use a number or a numeric '
          'string; for a structured answer use the requested object or list as the answer value. '
          'Do not include an explanation inside the answer value.')
BUDGETS = {'easy': 2048, 'medium': 4096, 'hard': 8192, 'very_hard': 12288, 'extreme': 16384}


def payload(case, options, repeat=0):
    body = {'model': options.get('model', 'strata'), 'stream': False,
            'messages': [{'role': 'system', 'content': case.get('system',SYSTEM)}, {'role': 'user', 'content': case['prompt']}],
            'temperature': options['temperature'], 'top_p': 1.0,
            'seed': options['seed'] + repeat,
            'max_tokens': options.get('max_tokens') or BUDGETS[case['difficulty']]}
    if case.get('image'):
        body['messages'][1]['content']=[{'type':'text','text':case['prompt']},{'type':'image_url','image_url':{'url':case['image']}}]
    effort = options.get('reasoning', 'xhigh')
    if effort != 'default':
        body['reasoning_effort'] = 'none' if effort == 'off' else effort
    return body


def is_port_free(port):
    with socket.socket() as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def stop_process(proc):
    stop_tree(proc)


@contextlib.contextmanager
def server(version, config_path, work, options):
    port = options['port']
    if not is_port_free(port):
        raise RuntimeError(f'Benchmark port {port} is busy. Choose --port with another number.')
    cfg, provenance = effective_config(config_path, version, work, port, options.get('keep_vision', False))
    work = Path(work)
    env = os.environ.copy()
    # Keep bytecode, transient files, and automatic library tuning outputs in the run folder.
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['TMPDIR'] = str(work)
    env['TMP'] = str(work)
    env['TEMP'] = str(work)
    env['XDG_CACHE_HOME'] = str(work / 'cache')
    env.pop('STRATA_API_KEY', None)
    cfg.pop('api_key', None)
    cfg.pop('before_load', None)
    cfg.pop('slot_save_path', None)
    cfg['idle_unload_s'] = 0
    cfg['fit_max_tokens'] = False
    write_json(work / 'effective-config.json', cfg)
    command = [version['python'], str(Path(version['root']) / 'serve/server.py'),
               '--engine', 'strata', '--config', str(work / 'effective-config.json'),
               '--host', '127.0.0.1', '--port', str(port)]
    write_json(work / 'launch.json', {'command': command, 'config_provenance': provenance})
    base = f'http://127.0.0.1:{port}'
    started = time.monotonic()
    with (work / 'server.log').open('a') as log:
        proc = subprocess.Popen(command, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
                                **process_options())
        try:
            last_notice = started
            while True:
                if proc.poll() is not None:
                    tail = '\n'.join((work / 'server.log').read_text(errors='replace').splitlines()[-12:])
                    raise RuntimeError(f'Strata exited during startup (code {proc.returncode}).\n{tail}\nSee {work / "engine.log"}')
                try:
                    health = request_json(base + '/health', timeout=2)
                    if health.get('status') == 'ok' and health.get('loaded', True):
                        break
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                now = time.monotonic()
                if now - started > options['startup_timeout']:
                    raise TimeoutError(f'Strata did not become ready. See {work / "server.log"} and engine.log.')
                if now - last_notice > 20:
                    print(f'  Loading model ({int(now-started)}s); details: {work / "server.log"}', flush=True)
                    last_notice = now
                time.sleep(.5)
            props = {}
            with contextlib.suppress(OSError, ValueError, http.client.HTTPException):
                props = request_json(base + '/props', timeout=5)
            yield base + '/v1', {'health': health, 'props': props, 'startup_seconds': time.monotonic()-started,
                                'effective_config': cfg, 'provenance': provenance}
        finally:
            stop_process(proc)


def completion(endpoint, body, timeout, api_key=None):
    started = time.monotonic()
    raw = request_json(endpoint.rstrip('/') + '/chat/completions', body, timeout, api_key)
    elapsed = time.monotonic() - started
    choices = raw.get('choices', [])
    if not choices:
        raise ValueError('Server returned no choices: ' + json.dumps(raw)[:500])
    choice = choices[0]
    message = choice.get('message') or {}
    content = message.get('content')
    if isinstance(content, list):
        content = ''.join(x.get('text', '') for x in content if isinstance(x, dict))
    if content is not None and not isinstance(content, str):
        raise ValueError('Server returned a non-text content field.')
    return {'response': raw, 'content': content or '',
            'finish_reason': choice.get('finish_reason'), 'usage': raw.get('usage') or {},
            'elapsed_seconds': elapsed}


def load_rows(path):
    if not Path(path).exists():
        return []
    rows = []
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    for i, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except ValueError:
            if i != len(lines)-1:
                raise RuntimeError(f'Corrupt result line {i+1}: {path}') from None
            # An interrupted disk write is recoverable; discard only the final partial record.
            Path(path).write_text('\n'.join(lines[:i]) + ('\n' if i else ''), encoding='utf-8')
    return rows


def append_row(path, row):
    with Path(path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def protocol_hash():
    return digest({p.name: file_hash(p) for p in (ROOT / 'stratabench').glob('*.py') if p.name != 'gui.py'})


def make_targets(versions, configs):
    targets = []
    for version in versions:
        # Re-read engine/server files to detect changes to a registered version.
        observed = fingerprint(version['root'], version['exe'])
        if observed != version['fingerprint']:
            raise RuntimeError(f'Files for {version["name"]} changed after registration. Snapshot under a new label.')
        for path in configs:
            path = Path(path).resolve()
            cfg = read_json(path)
            tokenizer = Path(cfg.get('cwd') or path.parent) / cfg.get('tokenizer', '')
            tok_hashes = {p.name: file_hash(p) for p in tokenizer.glob('*') if p.is_file() and p.suffix in ('.json', '.txt', '.jinja')}
            # Weight files are huge; record their size/mtime, not an expensive full scan of every 100 GB model.
            inputs = []
            args = cfg['args']
            for flag in ('--native', '--ple-gguf', '--expert-profile'):
                if flag in args and args.index(flag)+1 < len(args):
                    p = Path(cfg.get('cwd') or path.parent) / args[args.index(flag)+1]
                    if p.exists():
                        st = p.stat()
                        entry = {'flag': flag, 'path': str(p), 'bytes': st.st_size, 'mtime_ns': st.st_mtime_ns}
                        if st.st_size < 16*1024*1024:
                            entry['sha256'] = file_hash(p)
                        inputs.append(entry)
            vision=cfg.get('vision') or {}
            for key in ('mmproj','model'):
                if vision.get(key):
                    vp=(Path(cfg.get('cwd') or path.parent)/vision[key]).resolve()
                    if vp.is_file():
                        stat=vp.stat();inputs.append({'flag':'vision.'+key,'path':str(vp),'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns})
            vision_exe=vision_executable(version,cfg,path)
            if vision and vision_exe is not None:tok_hashes['vision_engine']=file_hash(vision_exe)
            identity = {'version': version, 'config': str(path), 'config_sha256': file_hash(path),
                        'tokenizer_hashes': tok_hashes, 'input_metadata': inputs}
            id_ = digest(identity)[:14]
            targets.append({'id': id_, 'label': version['name'] + ' / ' + path.stem, **identity})
    return targets


def run(cases, targets, options, resume=None):
    env = {k: v for k, v in os.environ.items() if (k.startswith(('STRATA_', 'CUDA_', 'OMP_', 'MKL_'))
            or k in ('LD_LIBRARY_PATH',)) and not any(x in k for x in ('KEY', 'TOKEN', 'SECRET'))}
    signature = digest({'cases': cases, 'targets': targets, 'options': options,
                        'protocol': protocol_hash(), 'engine_environment': env})
    if resume:
        folder = Path(resume).resolve()
        manifest = read_json(folder / 'manifest.json')
        if manifest['signature'] != signature:
            raise RuntimeError('Resume refused: tasks, code, versions, configs, environment or run settings changed. '
                               'Use the exact original command/settings, or start a new run.')
        manifest['resumed_at'] = stamp()
    else:
        from datetime import datetime
        folder = ROOT / 'results' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + options['profile'] + '-' + signature[:6])
        folder.mkdir(parents=True, exist_ok=False)
        manifest = {'schema': 1, 'signature': signature, 'created': stamp(), 'options': options,
                    'targets': targets, 'cases_sha256': digest(cases), 'case_count': len(cases),
                    'protocol_sha256': protocol_hash(), 'hardware': hardware(), 'environment': env,
                    'status': 'running', 'target_status': {}}
        write_json(folder / 'cases.json', cases)
    write_json(folder / 'manifest.json', manifest)
    print(f'Results: {folder}\n{len(cases)} questions × {options["repeats"]} repeat(s) × {len(targets)} combination(s).', flush=True)
    api_key = os.environ.get('STRATABENCH_API_KEY')
    try:
        for target in targets:
            target_dir = folder / target['id']
            target_dir.mkdir(exist_ok=True)
            rows_path = target_dir / 'answers.jsonl'
            rows = load_rows(rows_path)
            latest = {(x['case_id'], x['repeat']): x for x in rows}
            # Transport/server failures can be retried on resume; scored wrong/cutoff answers are kept.
            done = {key for key, row in latest.items() if not row.get('error')}
            total = len(cases)*options['repeats']
            if len(done) == total:
                manifest['target_status'][target['id']] = {'state': 'complete'}
                continue
            print('\n' + target['label'], flush=True)
            status = manifest['target_status'][target['id']] = {'state': 'running'}
            write_json(folder / 'manifest.json', manifest)
            try:
                if target.get('endpoint'):
                    session = contextlib.nullcontext((target['endpoint'], {'external': True,
                        'note': 'Version/config identity is user supplied; external server is never started or stopped.'}))
                else:
                    attempt = target_dir / ('session-' + str(time.time_ns()))
                    session = server(target['version'], target['config'], attempt, options)
                with session as (endpoint, info):
                    if target.get('endpoint'):
                        with contextlib.suppress(OSError, ValueError, http.client.HTTPException):
                            info['props'] = request_json(endpoint.removesuffix('/v1') + '/props', timeout=10, api_key=api_key)
                    write_json(target_dir / 'session.json', info)
                    print('  Ready. Running one request at a time.', flush=True)
                    # Identical, unscored warm-up before every managed or attached session.
                    warmup = payload({'prompt': 'Reply with Ready.', 'difficulty': 'easy'}, options)
                    warmup.update(max_tokens=64, reasoning_effort='none')
                    write_json(target_dir / 'warmup.json', completion(endpoint, warmup, options['timeout'], api_key))
                    errors = 0
                    for repeat in range(options['repeats']):
                        for c in cases:
                            if (c['id'], repeat) in done:
                                continue
                            body = payload(c, options, repeat)
                            started = time.monotonic()
                            row = {'case_id': c['id'], 'repeat': repeat, 'difficulty': c['difficulty'],
                                   'group': c['group'], 'expected': c['answer'], 'request': body, 'at': stamp()}
                            fatal = False
                            try:
                                if c.get('protocol') in ('tools','coding'):
                                    from .capability_runner import run_agent
                                    row.update(run_agent(c,body,endpoint,options,api_key))
                                else:
                                    row.update(completion(endpoint, body, options['timeout'], api_key))
                                    row.update(grade(c, row['content'], row['finish_reason']))
                                if c.get('protocol')=='writing' and options.get('style_judge_endpoint') and not row.get('truncated'):
                                    from .capability_runner import judge_writing
                                    row['style_judge']=judge_writing(c,row['content'],options,os.environ.get('STRATABENCH_JUDGE_API_KEY'))
                                errors = 0
                            except (OSError, ValueError, http.client.HTTPException) as e:
                                detail = str(e)
                                if isinstance(e, urllib.error.HTTPError):
                                    detail += ': ' + e.read(4096).decode(errors='replace')
                                row.update(error=detail, correct=False, elapsed_seconds=time.monotonic()-started,
                                           truncated=False, unparsed=True, json_format=False)
                                errors += 1
                                # A disconnected/timeout request may still be generating. Do not queue another one.
                                fatal = not isinstance(e, urllib.error.HTTPError) or e.code >= 500
                            append_row(rows_path, row)
                            done.add((c['id'], repeat))
                            label = 'ERROR' if row.get('error') else 'PASS' if row['correct'] else 'FAIL'
                            print(f'  {len(done)}/{total} {label:5s} {c["id"]} ({row["elapsed_seconds"]:.1f}s)', flush=True)
                            if fatal or errors >= 3:
                                raise RuntimeError('Stopping this combination after a server failure; saved answers can be resumed.')
                    status.update(state='complete', finished=stamp())
            except (OSError, ValueError, RuntimeError, http.client.HTTPException) as e:
                status.update(state='failed', error=str(e), finished=stamp())
                print('  Failed: ' + str(e), flush=True)
            finally:
                write_json(folder / 'manifest.json', manifest)
                from .report import generate
                generate(folder)
        manifest['status'] = 'complete' if all(s['state'] == 'complete' for s in manifest['target_status'].values()) else 'incomplete'
    except KeyboardInterrupt:
        manifest['status'] = 'interrupted'
        print('\nStopped. Completed answers are saved. Resume from the menu or with --resume.', flush=True)
    finally:
        manifest['updated'] = stamp()
        write_json(folder / 'manifest.json', manifest)
        from .report import generate
        generate(folder)
    print(f'\nOpen {folder / "report.html"}', flush=True)
    return folder
