from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STRATA = Path('/media/hossein/SSD/strarta_stuff/Strata')
STATE = ROOT / 'settings.json'


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def settings():
    return read_json(STATE) if STATE.exists() else {
        'strata_root': str(DEFAULT_STRATA), 'versions': {}, 'default_reasoning': 'xhigh'}


def save_settings(value):
    write_json(STATE, value)


def capture(cmd, cwd=None, timeout=20):
    try:
        p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return {'ok': p.returncode == 0, 'output': p.stdout.strip(), 'code': p.returncode}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'ok': False, 'output': str(e)}


def request_json(url, body=None, timeout=60, api_key=None):
    headers = {'User-Agent': 'StrataBench/1.0', 'Accept': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    # Loopback traffic must not be sent through a user's HTTP proxy.
    from urllib.parse import urlsplit
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if urlsplit(url).hostname in (
        'localhost', '127.0.0.1', '::1') else urllib.request.build_opener()
    with opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as f:
        return json.load(f)


@contextlib.contextmanager
def local_lock(name):
    """OS-owned locks release on crashes; no stale lock cleanup is needed."""
    import fcntl
    path = ROOT / name
    with path.open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another StrataBench operation is running. Let it finish first.') from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def hardware():
    gpu = capture(['nvidia-smi', '--query-gpu=name,memory.total,driver_version',
                   '--format=csv,noheader'])
    ram = {}
    try:
        ram = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines()
                   if line.startswith(('MemTotal:', 'MemAvailable:')))
    except OSError:
        pass
    return {'gpu': gpu, 'ram': ram, 'cpu_count': os.cpu_count(),
            'platform': capture(['uname', '-srmo'])['output']}
