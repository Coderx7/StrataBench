"""Side-by-side engines and their matching Python servers. Never check out the user's repo."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import re
import shutil
import urllib.request

from .common import ROOT, capture, digest, file_hash, read_json, save_settings, settings, stamp, write_json


def safe_name(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,90}', name):
        raise ValueError('Use a version tag or label containing letters, numbers, dots, underscores and hyphens.')
    return name


def discover(root=None):
    if root is None:
        state = settings()
        root = state.get('strata_source',{}).get('config_folder') or state.get('strata_root')
    if not root:
        return []
    root = Path(root).expanduser().resolve()
    out = []
    for path in sorted(root.glob('strata-*.json')):
        try:
            cfg = read_json(path)
            if isinstance(cfg.get('args'), list) and cfg.get('exe'):
                out.append({'name': path.stem, 'path': str(path), 'model': cfg.get('model_name', ''),
                            'args': cfg['args'], 'alias': path.is_symlink()})
        except (ValueError, OSError):
            continue
    return out


def fingerprint(root, exe):
    root, exe = Path(root), Path(exe)
    result = {'engine_sha256': file_hash(exe),
              'server_sha256': file_hash(root / 'serve/server.py')}
    result['server_tree_sha256'] = digest({str(p.relative_to(root)): file_hash(p)
        for p in sorted((root / 'serve').rglob('*'))
        if p.is_file() and p.suffix in ('.py', '.jinja', '.json')})
    result['helper_libraries'] = {p.name: file_hash(p) for p in sorted(exe.parent.iterdir())
        if p.is_file() and ('.so' in p.name or p.suffix.lower() in ('.dll','.dylib'))}
    tokenizer_module = root / 'tools/strata_tokenizer.py'
    if tokenizer_module.exists():
        result['tokenizer_module_sha256'] = file_hash(tokenizer_module)
    for name in ('chat_template.jinja', 'frontend.py'):
        p = root / 'serve' / name
        if p.exists():
            result[name + '_sha256'] = file_hash(p)
    build = exe.parent / 'BUILD.json'
    if build.exists():
        result['build'] = read_json(build)
    return result


def snapshot(name=None, source=None, exe=None, python=None):
    from .acquisition import copy_engine, copy_runtime, local_engine, preferences, python_runtime
    from .platforms import executable
    state = settings()
    cfg = preferences(state)
    source = Path(source or cfg['folder'] or state['strata_root']).expanduser().resolve()
    exe = local_engine(source, exe)
    build = read_json(exe.parent / 'BUILD.json') if (exe.parent / 'BUILD.json').exists() else {}
    name = safe_name(name or ('v' + build.get('version', 'local')))
    dest = ROOT / 'versions' / name
    if dest.exists():
        raise ValueError(f'{name} already exists. Use it as-is or choose a different label.')
    dest.mkdir(parents=True)
    try:
        copy_runtime(source, dest)
        engine = copy_engine(exe, dest / 'engine')
        if (source / 'LICENSE').exists():
            shutil.copy2(source / 'LICENSE', dest / 'LICENSE')
        if python: cfg['python'] = python
        py = python_runtime(cfg, source, dest)
        info = {'name': name, 'root': str(dest), 'exe': str(engine),
                'python': py, 'origin': str(source), 'kind': 'snapshot', 'created': stamp(),
                'git': capture(['git', '-C', str(source), 'rev-parse', 'HEAD'])['output'],
                'fingerprint': fingerprint(dest, engine)}
        write_json(dest / 'version.json', info)
    except BaseException:
        shutil.rmtree(dest)
        raise
    state['versions'][name] = info
    save_settings(state)
    print(f'Registered {name}: independent engine and matching server snapshot.')
    return info


def extract_tar(archive, dest, strip_top=False):
    from .acquisition import unpack
    unpack(archive, dest, strip_top)


def download(url, dest):
    print('Downloading ' + url, flush=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'StrataBench/1.0'})
    tmp = Path(str(dest) + '.download')
    try:
        with urllib.request.urlopen(req, timeout=120) as response, tmp.open('wb') as f:
            shutil.copyfileobj(response, f)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def build(tag, jobs=None, extra=(), python=None):
    from .acquisition import prepare
    return prepare(tag, jobs, extra, python)


def effective_config(source_path, version, work, port, keep_vision=False):
    """Copy all model settings, make relative input paths absolute, relocate known writable outputs."""
    source_path, work = Path(source_path).resolve(), Path(work).resolve()
    cfg = copy.deepcopy(read_json(source_path))
    original = copy.deepcopy(cfg)
    old_cwd = Path(cfg.get('cwd') or source_path.parent).resolve()
    args = list(cfg['args'])
    if not all(isinstance(x, str) for x in args):
        raise ValueError('Config args must be a list of strings.')
    work.mkdir(parents=True, exist_ok=True)
    changes = []
    for i, arg in enumerate(args):
        if i and not arg.startswith('--') and args[i-1].startswith('--'):
            flag = args[i-1]
            if flag in ('--expert-profile-save', '--dump-routing', '--trace-file', '--stats-file'):
                args[i] = str(work / Path(arg).name)
                changes.append(f'{flag} output relocated')
            elif (old_cwd / arg).exists() and not os.path.isabs(arg):
                args[i] = str((old_cwd / arg).resolve())
    for flag in ('--pack', '--native', '--ple-gguf', '--mtp', '--expert-profile'):
        if flag in args:
            index = args.index(flag) + 1
            if index >= len(args) or not Path(args[index]).exists():
                raise ValueError(f'Missing input for {flag}: {args[index:index+1]}')
    cfg['args'] = args
    cfg['exe'] = version['exe']
    cfg['cwd'] = str(work)
    cfg['port'] = port
    cfg['host'] = '127.0.0.1'
    cfg['log'] = str(work / 'engine.log')
    cfg['lazy_load'] = False
    cfg.pop('args_written', None)
    # No tool integrations are involved in these single-turn quality tests.
    for key in ('mcp', 'mcp_servers', 'mcp_config', 'shared', 'settings_file'):
        cfg.pop(key, None)
    for key in ('tokenizer', 'chat_template'):
        if isinstance(cfg.get(key), str) and (old_cwd / cfg[key]).exists():
            cfg[key] = str((old_cwd / cfg[key]).resolve())
    if cfg.get('expert_profile_save'):
        src = old_cwd / cfg['expert_profile_save']
        dst = work / 'learned-profile.bin'
        if src.is_file():
            shutil.copy2(src, dst)
        cfg['expert_profile_save'] = str(dst)
        changes.append('learned profile copied and its output relocated')
    if not keep_vision:
        cfg.pop('vision', None)
        # Keep engine --vision: it is a tested engine allocation setting in the supplied config.
        changes.append('image encoder disabled for text suite; engine --vision flag preserved')
    elif cfg.get('vision'):
        from .platforms import executable
        vision_exe = Path(version['exe']).parent / executable('strata-vision')
        if not vision_exe.exists():
            raise ValueError('This version has no vision binary. Omit --keep-vision for text benchmarks.')
        cfg['vision']['exe'] = str(vision_exe)
        for key in ('mmproj', 'model'):
            if cfg['vision'].get(key):
                cfg['vision'][key] = str((old_cwd / cfg['vision'][key]).resolve())
    libs = [str(Path(version['exe']).parent)] + cfg.get('lib_dirs', [])
    build_lib = Path(version['root']) / 'build'
    if build_lib.exists():
        libs.append(str(build_lib))
    cfg['lib_dirs'] = list(dict.fromkeys(libs))
    write_json(work / 'effective-config.json', cfg)
    return cfg, {'original': original, 'overrides': changes,
                 'source': str(source_path), 'source_sha256': file_hash(source_path)}
