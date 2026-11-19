"""Side-by-side engines and their matching Python servers. Never check out the user's repo."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

from .common import ROOT, capture, digest, file_hash, read_json, save_settings, settings, stamp, write_json


def safe_name(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,90}', name):
        raise ValueError('Use a version tag or label containing letters, numbers, dots, underscores and hyphens.')
    return name


def discover(root=None):
    root = Path(root or settings()['strata_root']).resolve()
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
    result['helper_libraries'] = {p.name: file_hash(p) for p in sorted(exe.parent.glob('*.so*')) if p.is_file()}
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
    state = settings()
    source = Path(source or state['strata_root']).resolve()
    exe = Path(exe or source / 'engine/strata').resolve()
    if not exe.is_file() or not (source / 'serve/server.py').is_file():
        raise ValueError('A built Strata engine and serve/server.py are required.')
    build = read_json(exe.parent / 'BUILD.json') if (exe.parent / 'BUILD.json').exists() else {}
    name = safe_name(name or ('v' + build.get('version', 'local')))
    dest = ROOT / 'versions' / name
    if dest.exists():
        raise ValueError(f'{name} already exists. Use it as-is or choose a different label.')
    dest.mkdir(parents=True)
    try:
        shutil.copytree(source / 'serve', dest / 'serve', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (dest / 'tools').mkdir()
        shutil.copy2(source / 'tools/strata_tokenizer.py', dest / 'tools/strata_tokenizer.py')
        (dest / 'engine').mkdir()
        for p in exe.parent.iterdir():
            if p.is_file() and (p.name in (exe.name, 'strata-vision', 'BUILD.json') or '.so' in p.name):
                shutil.copy2(p, dest / 'engine' / ('strata' if p == exe else p.name))
        if (source / 'LICENSE').exists():
            shutil.copy2(source / 'LICENSE', dest / 'LICENSE')
        py = str(Path(python or source / '.venv/bin/python').absolute())
        if not Path(py).exists():
            import sys
            py = sys.executable
        info = {'name': name, 'root': str(dest), 'exe': str(dest / 'engine/strata'),
                'python': py, 'origin': str(source), 'kind': 'snapshot', 'created': stamp(),
                'git': capture(['git', '-C', str(source), 'rev-parse', 'HEAD'])['output'],
                'fingerprint': fingerprint(dest, dest / 'engine/strata')}
        write_json(dest / 'version.json', info)
    except BaseException:
        shutil.rmtree(dest)
        raise
    state['versions'][name] = info
    save_settings(state)
    print(f'Registered {name}: independent engine and matching server snapshot.')
    return info


def extract_tar(archive, dest, strip_top=False):
    dest = Path(dest).resolve()
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            parts = Path(member.name).parts
            if strip_top:
                parts = parts[1:]
            if not parts:
                continue
            member.name = str(Path(*parts))
            target = (dest / member.name).resolve()
            if not target.is_relative_to(dest) or member.issym() or member.islnk() or member.isdev():
                raise ValueError('Unsafe entry in source archive: ' + member.name)
            tf.extract(member, dest, filter='data')


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


def build(tag, jobs=4, extra=(), python=None):
    """Use local Git objects when available; otherwise fetch only into our own bare repository."""
    name = safe_name(tag)
    state = settings()
    dest = ROOT / 'versions' / name
    if name in state['versions']:
        print(f'{name} is already registered.')
        return state['versions'][name]
    dest.mkdir(parents=True, exist_ok=True)
    repo = Path(state['strata_root'])
    resolved = capture(['git', '-C', str(repo), 'rev-parse', '--verify', f'{tag}^{{commit}}'])
    if not resolved['ok']:
        repo = ROOT / 'versions' / '_git'
        if not repo.exists():
            subprocess.run(['git', 'init', '--bare', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'fetch', '--depth=1',
                        'https://github.com/Niko1221/Strata.git', 'refs/tags/' + tag], check=True)
        resolved = capture(['git', '-C', str(repo), 'rev-parse', 'FETCH_HEAD'])
    commit = resolved['output']
    if not resolved['ok'] or not re.fullmatch('[0-9a-f]{40}', commit):
        raise RuntimeError('Could not resolve that Strata version.')
    source_stamp = dest / 'source.json'
    if source_stamp.exists() and read_json(source_stamp)['commit'] != commit:
        raise RuntimeError('Tag now points to different source; choose a new version label.')
    if not source_stamp.exists():
        archive = dest / 'source.tar'
        with archive.open('wb') as f:
            subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar', commit], stdout=f, check=True)
        extract_tar(archive, dest)
        archive.unlink()
        write_json(source_stamp, {'commit': commit})
    if not shutil.which('cmake') or not shutil.which('nvcc'):
        raise RuntimeError('This version needs your existing CMake and CUDA compiler in PATH. Nothing was installed.')
    # Use the exact ggml revision required by this version. A separate source archive avoids a huge Git clone.
    version_file = dest / 'third_party/ggml/VERSION.txt'
    pin = re.search(r'\b[0-9a-f]{40}\b', version_file.read_text()).group() if version_file.exists() else None
    definitions = []
    if pin:
        dep = ROOT / 'versions' / '_dependencies' / pin
        if not (dep / 'ggml/CMakeLists.txt').exists():
            dep.mkdir(parents=True, exist_ok=True)
            tgz = dep.parent / (pin + '.tar.gz')
            download('https://codeload.github.com/ggml-org/llama.cpp/tar.gz/' + pin, tgz)
            extract_tar(tgz, dep, strip_top=True)
            tgz.unlink()
        definitions.append('-DSTRATA_GGML_DIR=' + str(dep))
    flags = ['-DSTRATA_ENABLE_CUDA=ON', '-DSTRATA_BUILD_TESTS=OFF', '-DCMAKE_BUILD_TYPE=Release',
             '-DCMAKE_CUDA_ARCHITECTURES=86', '-DCMAKE_CUDA_COMPILER=' + shutil.which('nvcc'),
             '-DSTRATA_MMQ_KQUANTS=ON', '-DSTRATA_Q6K_EXPERTS=ON', *definitions, *extra]
    log = dest / 'build.log'
    print(f'Building {tag} for RTX 3080 (sm_86), {jobs} jobs. Progress: {log}', flush=True)
    commands = [['cmake', '-S', str(dest), '-B', str(dest / 'build'), *flags],
                ['cmake', '--build', str(dest / 'build'), '--target', 'strata', '-j', str(jobs)]]
    with log.open('a') as f:
        for cmd in commands:
            f.write('\n' + repr(cmd) + '\n')
            f.flush()
            p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
            if p.returncode:
                tail = '\n'.join(log.read_text(errors='replace').splitlines()[-16:])
                raise RuntimeError(f'Build failed. Nothing in your original install changed.\n{tail}\nFull log: {log}')
    (dest / 'engine').mkdir(exist_ok=True)
    shutil.copy2(dest / 'build/strata', dest / 'engine/strata')
    for p in (dest / 'build').rglob('libstrata*.so*'):
        shutil.copy2(p, dest / 'engine' / p.name)
    original_py = Path(state['strata_root']) / '.venv/bin/python'
    import sys
    info = {'name': name, 'root': str(dest), 'exe': str(dest / 'engine/strata'),
            'python': str(python or (original_py if original_py.exists() else sys.executable)),
            'kind': 'built', 'created': stamp(), 'git': commit, 'cmake_flags': flags,
            'ggml_commit': pin, 'fingerprint': fingerprint(dest, dest / 'engine/strata')}
    write_json(dest / 'version.json', info)
    state['versions'][name] = info
    save_settings(state)
    print(f'{name} is ready. Models and packs were reused, not downloaded.')
    return info


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
        vision_exe = Path(version['root']) / 'engine/strata-vision'
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
