"""Prepare isolated Strata runtimes from a local build, Git source, or portable release."""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import tarfile
from urllib.parse import quote, urlsplit
import urllib.request
import zipfile

from .common import ROOT, capture, digest, file_hash, save_settings, settings, stamp, write_json
from .platforms import executable, find_python, platform_id, python_in, windows, quiet_options

OFFICIAL_REPOSITORY = 'https://github.com/Niko1221/Strata.git'
METHODS = ('local', 'repository', 'folder', 'release')


def preferences(state=None):
    state = settings() if state is None else state
    root = state.get('strata_root', '')
    return {'method':'local' if root else 'release', 'repository':OFFICIAL_REPOSITORY,
        'folder':root, 'config_folder':root, 'python':'',
        'python_mode':'existing' if state.get('versions') else 'managed', 'build_jobs':4,
        'cuda_architectures':'native', 'backend':'cuda12', 'asset':'auto',
        'allow_unverified':False, 'cmake_args':[], **state.get('strata_source', {})}


def repository_url(value):
    value = str(value).strip().rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Enter an HTTPS Git repository URL without credentials or query parameters.')
    return value


def github_repo(url):
    parsed = urlsplit(repository_url(url))
    path = parsed.path.removesuffix('.git').strip('/')
    if parsed.hostname != 'github.com' or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', path):
        raise ValueError('Portable releases require a GitHub repository URL such as https://github.com/Niko1221/Strata.git.')
    return path


def validate(data, state=None):
    cfg = {**preferences(state), **{k:v for k,v in data.items() if k in preferences(state)}}
    if cfg['method'] not in METHODS:
        raise ValueError('Choose an existing build, a repository, a source folder, or a portable release.')
    cfg['repository'] = repository_url(cfg['repository'])
    if cfg['method'] == 'release':
        github_repo(cfg['repository'])
    for key in ('folder','config_folder','python'):
        if not isinstance(cfg[key], str):
            raise ValueError('Folder and Python paths must be text.')
        cfg[key] = str(Path(cfg[key]).expanduser().resolve()) if cfg[key].strip() else ''
    if cfg['method'] in ('local','folder') and not Path(cfg['folder'] or '/__missing__').is_dir():
        raise ValueError('Choose an existing Strata folder.')
    if cfg['config_folder'] and not Path(cfg['config_folder']).is_dir():
        raise ValueError('The model configuration folder does not exist.')
    if cfg['python'] and not Path(cfg['python']).is_file():
        raise ValueError('The Python executable does not exist.')
    if cfg['python_mode'] not in ('existing','managed'):
        raise ValueError('Choose existing Python or an isolated Python environment.')
    if isinstance(cfg['build_jobs'],bool) or not str(cfg['build_jobs']).isdigit() or not 1 <= int(cfg['build_jobs']) <= 64:
        raise ValueError('Build jobs must be between 1 and 64.')
    cfg['build_jobs'] = int(cfg['build_jobs'])
    if not re.fullmatch(r'(?:native|all|all-major|[0-9]+(?:-(?:real|virtual))?(?:;[0-9]+(?:-(?:real|virtual))?)*)',str(cfg['cuda_architectures'])):
        raise ValueError('Use native, all-major, or CUDA architecture numbers such as 86 or 86;89.')
    if cfg['backend'] not in ('cuda12','cuda13','hip','sycl'):
        raise ValueError('Choose CUDA 12, CUDA 13, HIP, or SYCL for portable binaries.')
    if not isinstance(cfg['asset'],str) or '/' in cfg['asset'] or '\\' in cfg['asset']:
        raise ValueError('Select a release asset by its filename.')
    if not isinstance(cfg['allow_unverified'],bool):
        raise ValueError('The checksum preference must be on or off.')
    if not isinstance(cfg['cmake_args'],list) or any(not isinstance(x,str) or not x.startswith('-D') for x in cfg['cmake_args']):
        raise ValueError('Extra CMake options must be a list of -DNAME=value entries.')
    return cfg


def configure(data):
    state = settings()
    cfg = validate(data,state)
    state['strata_source'] = cfg
    state['strata_root'] = cfg['config_folder'] or (cfg['folder'] if cfg['method'] in ('local','folder') else '')
    save_settings(state)
    return cfg


def runtime_source(folder):
    folder = Path(folder)
    for candidate in (folder, folder / 'terminal'):
        if (candidate / 'serve/server.py').is_file() and (candidate / 'tools/strata_tokenizer.py').is_file():
            return candidate
    raise ValueError('The Strata folder must contain serve/server.py and tools/strata_tokenizer.py (directly or inside terminal/).')


def local_engine(folder, explicit=None):
    folder = Path(folder)
    if explicit:
        candidates = [Path(explicit).expanduser().resolve()]
    else:
        name = executable()
        candidates = [folder / 'engine' / name, folder / name, folder / 'bin' / name,
            folder / 'build' / name, folder / 'build/Release' / name, folder / 'engine/build/Release' / name,
            folder / 'engine/build' / name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError(f'No {executable()} engine was found. Build Strata first or choose the engine executable explicitly.')


def copy_runtime(source, dest):
    source, dest = runtime_source(source), Path(dest)
    for name in ('serve','tools','strata_cli','strata_control','data'):
        path = source / name
        if path.is_dir():
            shutil.copytree(path,dest / name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.git','*.gguf','*.pack'))
    for name in ('requirements.txt','strata.py','LICENSE'):
        if (source / name).is_file():
            shutil.copy2(source / name,dest / name)
    return source


def copy_engine(binary, dest, search=None):
    binary, dest = Path(binary), Path(dest)
    dest.mkdir(parents=True,exist_ok=True)
    target = dest / executable()
    shutil.copy2(binary,target)
    if not windows():
        target.chmod(target.stat().st_mode | 0o111)
    source = Path(search or binary.parent)
    for path in source.rglob('*'):
        if not path.is_file() or path == binary:
            continue
        if path.name in ('BUILD.json',executable('strata-vision')) or '.so' in path.name or path.suffix.lower() in ('.dll','.dylib'):
            out = dest / path.name
            if out.exists() and file_hash(out) != file_hash(path):
                raise ValueError('Conflicting helper libraries in the engine package: '+path.name)
            shutil.copy2(path,out)
    return target


def unpack(archive, dest, strip_top=False):
    """Materialize regular files and internal file links; never create filesystem links."""
    dest = Path(dest).resolve()
    links = []
    def target(name):
        normalized = name.replace('\\','/')
        if PureWindowsPath(name).drive or normalized.startswith('/') or '..' in PurePosixPath(normalized).parts or ':' in normalized or any(PureWindowsPath(p).is_reserved() or p.endswith((' ','.')) for p in PurePosixPath(normalized).parts):
            raise ValueError('Unsafe path in Strata archive: '+name)
        parts = PurePosixPath(normalized).parts[1:] if strip_top else PurePosixPath(normalized).parts
        path = dest.joinpath(*parts)
        if not path.resolve().is_relative_to(dest):
            raise ValueError('Unsafe path in Strata archive: '+name)
        return path if parts else None
    def defer(path, name, hard=False):
        normalized = name.replace('\\','/')
        if PureWindowsPath(name).drive or normalized.startswith('/') or ':' in normalized:
            raise ValueError('Unsafe link in Strata archive: '+name)
        source = target(normalized) if hard else (path.parent / normalized).resolve()
        if not source or not source.is_relative_to(dest) or source == path:
            raise ValueError('Unsafe link in Strata archive: '+name)
        links.append((path,source))
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            members = [(m,target(m.filename)) for m in package.infolist()]
            for member,path in members:
                if path is None:continue
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    defer(path,package.read(member).decode('utf-8'));continue
                if member.is_dir():path.mkdir(parents=True,exist_ok=True);continue
                path.parent.mkdir(parents=True,exist_ok=True)
                with package.open(member) as inp,path.open('wb') as out:shutil.copyfileobj(inp,out)
    else:
        with tarfile.open(archive) as package:
            members = [(m,target(m.name)) for m in package.getmembers()]
            if any(not (m.isfile() or m.isdir() or m.issym() or m.islnk()) for m,_ in members):
                raise ValueError('Special files are not supported in Strata archives.')
            for member,path in members:
                if path is None:continue
                if member.issym() or member.islnk():
                    defer(path,member.linkname,hard=member.islnk());continue
                if member.isdir():path.mkdir(parents=True,exist_ok=True);continue
                path.parent.mkdir(parents=True,exist_ok=True)
                with package.extractfile(member) as inp,path.open('wb') as out:shutil.copyfileobj(inp,out)
                if not windows():path.chmod(member.mode & 0o777)
    # Shared-library archives often use versioned file aliases. Copy their bytes
    # after regular files exist; unresolved/cyclic links and directory links fail.
    while links:
        pending = []
        for path,source in links:
            if not source.is_file():
                pending.append((path,source));continue
            path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,path)
        if len(pending) == len(links):
            raise ValueError('Unresolved or cyclic file link in Strata archive.')
        links = pending


def get_json(url):
    request = urllib.request.Request(url,headers={'User-Agent':'StrataBench','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=45) as response:
        import json
        return json.load(response)


def release_info(cfg, tag):
    repo = github_repo(cfg['repository'])
    suffix = 'latest' if tag == 'latest' else 'tags/'+quote(tag,safe='')
    try:
        return get_json(f'https://api.github.com/repos/{repo}/releases/{suffix}')
    except OSError as error:
        raise ValueError('Could not read that GitHub release. Check the repository, release tag, connection, and GitHub API rate limit. '+str(error)) from None


def compatible_assets(release, cfg, host=None):
    system,arch = host or platform_id()
    result = []
    for asset in release.get('assets',[]):
        name = asset['name'].lower()
        if not (name.endswith(('.zip','.tar.gz','.tgz')) and 'strata' in name):continue
        if not ('engine' in name or re.match(r'strata-(?:windows|linux)',name)):continue
        if system not in name:continue
        aliases = ('x86_64','x64','amd64') if arch == 'x86_64' else ('aarch64','arm64')
        if not any(x in name for x in aliases):continue
        backend = cfg['backend']
        if backend in ('hip','sycl') and backend not in name:continue
        if backend == 'cuda12' and 'cuda12' not in name:continue
        if backend == 'cuda13' and 'cuda13' not in name:continue
        result.append(asset)
    return result


def source_tree(cfg, ref, dest):
    if not shutil.which('git'):
        raise RuntimeError('Git is needed for a source build. Install Git or choose a portable release.')
    if cfg['method'] == 'folder':
        repo = Path(cfg['folder'])
        resolved = capture(['git','-C',str(repo),'rev-parse','--verify',ref+'^{commit}'])
        if not resolved['ok']:
            raise ValueError('That revision is not present in the source folder. Fetch it in that repository first, or use repository mode.')
    else:
        repo = ROOT / 'versions/_git' / digest(cfg['repository'])[:16]
        if not repo.exists():
            repo.parent.mkdir(parents=True,exist_ok=True)
            try:
                subprocess.run(['git','clone','--mirror','--filter=blob:none','--',cfg['repository'],str(repo)],check=True, **quiet_options())
            except BaseException:
                shutil.rmtree(repo,ignore_errors=True)
                raise
        subprocess.run(['git','-C',str(repo),'fetch','--depth=1','origin',ref],check=True, **quiet_options())
        resolved = capture(['git','-C',str(repo),'rev-parse','--verify','FETCH_HEAD^{commit}'])
    commit = resolved['output']
    if not re.fullmatch(r'[a-f0-9]{40,64}',commit):raise RuntimeError('Could not resolve the source revision.')
    archive = dest.parent / 'source.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git','-C',str(repo),'archive','--format=tar',commit],stdout=stream,check=True, **quiet_options())
    unpack(archive,dest);archive.unlink()
    return commit


def python_runtime(cfg, source, dest):
    interpreter = find_python(source,cfg['python'])
    if cfg['python_mode'] == 'existing':
        check = capture([interpreter,'-c','import jinja2, regex, numpy'],timeout=30)
        if not check['ok']:
            raise RuntimeError('Strata Python dependencies are missing. Choose an isolated Python environment in Setup, or provide a Python environment containing Strata runtime dependencies. '+check['output'])
        return interpreter
    environment = dest / '.venv'
    print('Preparing isolated Python runtime (no global packages are changed).',flush=True)
    subprocess.run([interpreter,'-m','venv',str(environment)],check=True, **quiet_options())
    python = str(python_in(environment))
    requirements = runtime_source(source) / 'requirements.txt'
    args = ['-r',str(requirements)] if requirements.is_file() else ['jinja2>=3.1','regex','numpy']
    subprocess.run([python,'-m','pip','install','--disable-pip-version-check',*args],check=True, **quiet_options())
    return python


def prepare(ref, jobs=None, extra=(), python=None):
    from . import versions
    state = settings()
    if ref in state['versions']:
        return state['versions'][ref]
    cfg = validate(preferences(state))
    if python:cfg['python'] = python
    if cfg['method'] == 'local':
        return versions.snapshot(versions.safe_name(ref),cfg['folder'],python=cfg['python'] or None)
    release = release_info(cfg,ref) if cfg['method'] == 'release' else None
    name = versions.safe_name(release['tag_name'] if release else ref)
    state = settings()
    if name in state['versions']:
        print(name+' is already registered.',flush=True);return state['versions'][name]
    dest = ROOT / 'versions' / name
    if dest.exists():
        marker = dest / '.preparing.json'
        from .common import read_json
        if not marker.is_file() or read_json(marker) != {'name':name,'schema':1}:
            raise ValueError('An unregistered folder already uses that version label. Rename it before retrying; its files have been preserved.')
        backup = ROOT / 'versions/_failed' / (name+'-'+stamp().replace(':','-'))
        backup.parent.mkdir(parents=True,exist_ok=True)
        dest.rename(backup)
        print('Preserved interrupted preparation in '+str(backup),flush=True)
    dest.mkdir(parents=True)
    write_json(dest / '.preparing.json',{'name':name,'schema':1})
    try:
        source = dest / 'source'
        if release:
            info = prepare_release(cfg,release,source,dest)
        else:
            commit = source_tree(cfg,ref,source)
            binary,flags = build_source(source,dest,cfg,jobs or cfg['build_jobs'],extra)
            info = {'kind':'built','git':commit,'cmake_flags':flags}
            copy_runtime(source,dest)
            copy_engine(binary,dest / 'engine',dest / 'build')
        if (source / 'LICENSE').exists():shutil.copy2(source / 'LICENSE',dest / 'LICENSE')
        py = python_runtime(cfg,source,dest)
        engine = dest / info.pop('engine_relative_path', str(Path('engine') / executable()))
        info.update(name=name,root=str(dest),exe=str(engine),python=py,created=stamp(),
                    repository=cfg['repository'],acquisition=cfg['method'],fingerprint=versions.fingerprint(dest,engine))
        write_json(dest / 'version.json',info)
        state = settings();state['versions'][name] = info;save_settings(state)
        (dest / '.preparing.json').unlink(missing_ok=True)
        print(name+' is ready. Your model weights were not downloaded or changed.',flush=True)
        return info
    except BaseException:
        # Retain diagnostics outside the version directory so a failed attempt can be retried.
        logs = ROOT / 'versions/_failed' / (name+'-'+stamp().replace(':','-'))
        if (dest / 'build.log').exists():
            logs.mkdir(parents=True,exist_ok=True);shutil.copy2(dest / 'build.log',logs / 'build.log')
        shutil.rmtree(dest)
        raise


def build_source(source, dest, cfg, jobs, extra):
    from .versions import download
    if not shutil.which('cmake') or not shutil.which('nvcc'):
        raise RuntimeError('A CUDA source build needs CMake, nvcc (the CUDA Toolkit), and a C++ compiler. Choose portable binaries to skip compilation.')
    build_root = source if (source / 'CMakeLists.txt').exists() else source / 'engine'
    if not (build_root / 'CMakeLists.txt').is_file():raise ValueError('This revision has no supported Strata CMake project.')
    definitions = []
    pin_file = build_root / 'third_party/ggml/VERSION.txt'
    match = re.search(r'\b[0-9a-f]{40}\b',pin_file.read_text(encoding='utf-8')) if pin_file.exists() else None
    if match:
        pin = match.group();dep = ROOT / 'versions/_dependencies' / pin
        if not (dep / 'ggml/CMakeLists.txt').exists():
            dep.mkdir(parents=True,exist_ok=True);archive = dep.parent / (pin+'.tar.gz')
            download('https://codeload.github.com/ggml-org/llama.cpp/tar.gz/'+pin,archive)
            unpack(archive,dep,strip_top=True);archive.unlink()
        definitions.append('-DSTRATA_GGML_DIR='+str(dep))
    flags = ['-DSTRATA_ENABLE_CUDA=ON','-DSTRATA_BUILD_TESTS=OFF','-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_CUDA_ARCHITECTURES='+cfg['cuda_architectures'],'-DCMAKE_CUDA_COMPILER='+shutil.which('nvcc'),
        '-DSTRATA_MMQ_KQUANTS=ON','-DSTRATA_Q6K_EXPERTS=ON',*definitions,*cfg['cmake_args'],*extra]
    log = dest / 'build.log'
    print(f'Building {dest.name}, CUDA architecture {cfg["cuda_architectures"]}, {jobs} jobs. Progress: {log}',flush=True)
    with log.open('w',encoding='utf-8') as stream:
        for command in (['cmake','-S',str(build_root),'-B',str(dest / 'build'),*flags],
                ['cmake','--build',str(dest / 'build'),'--config','Release','--target','strata','--parallel',str(jobs)]):
            stream.write(repr(command)+'\n');stream.flush()
            subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True, **quiet_options())
    candidates = list((dest / 'build').rglob(executable()))
    if not candidates:raise RuntimeError('CMake finished without producing a Strata executable.')
    return candidates[0],flags


def prepare_release(cfg, release, source, dest):
    from .versions import download
    assets = compatible_assets(release,cfg)
    selected = [a for a in assets if a['name'] == cfg['asset']] if cfg['asset'] not in ('','auto') else assets
    if len(selected) != 1:
        raise ValueError('Choose one compatible portable engine asset in Setup. This release may not offer your selected OS/backend; a source build is another option.')
    asset = selected[0]
    checksum = asset.get('digest','') or ''
    expected = checksum[7:].lower() if checksum.startswith('sha256:') else None
    if not expected:
        sum_asset = next((a for a in release.get('assets',[]) if re.fullmatch(r'SHA256(?:SUMS)?(?:\.txt)?',a['name'],re.I)),None)
        if sum_asset:
            sums = dest / 'checksums.txt';download(sum_asset['browser_download_url'],sums)
            for line in sums.read_text(encoding='utf-8').splitlines():
                escaped = re.escape(asset['name'])
                match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?'+escaped,line.strip())
                bsd = re.fullmatch(r'SHA256\s*\('+escaped+r'\)\s*=\s*([0-9a-fA-F]{64})',line.strip(),re.I)
                if match or bsd:
                    expected = (match or bsd).group(1).lower();break

    if not expected and not cfg['allow_unverified']:
        raise ValueError('This asset has no published SHA-256 digest. Use a source build, or explicitly enable packages without a published checksum in Setup.')
    cache = ROOT / 'versions/_downloads';cache.mkdir(parents=True,exist_ok=True)
    archive = cache / (digest([cfg['repository'],release['tag_name'],asset['name'],expected])[:16]+'-'+asset['name'])
    if not archive.exists():download(asset['browser_download_url'],archive)
    observed = file_hash(archive)
    if expected and observed != expected:
        archive.unlink();raise ValueError('The release checksum did not match. The downloaded package was removed; nothing was run.')
    repo = github_repo(cfg['repository'])
    commit = get_json(f'https://api.github.com/repos/{repo}/commits/'+quote(release['tag_name'],safe=''))['sha']
    if not re.fullmatch(r'[a-f0-9]{40,64}',commit):raise ValueError('GitHub returned an invalid source commit.')
    source_archive = dest / 'source.tar.gz'
    download(f'https://codeload.github.com/{repo}/tar.gz/{commit}',source_archive)
    source_hash = file_hash(source_archive);unpack(source_archive,source,strip_top=True);source_archive.unlink()
    copy_runtime(source,dest)
    extracted = dest / 'package';unpack(archive,extracted)
    engines = list(extracted.rglob(executable()))
    if len(engines) != 1:raise ValueError('The portable package must contain exactly one Strata engine executable.')
    engine_relative = Path('engine') / engines[0].relative_to(extracted)
    # Keep DLLs, backend data, tuning tables and relative library paths together.
    shutil.copytree(extracted,dest / 'engine')
    if not windows():(dest / engine_relative).chmod((dest / engine_relative).stat().st_mode | 0o111)
    shutil.rmtree(extracted)
    print('Portable engine installed with matching server source from '+commit[:12]+'.',flush=True)
    return {'kind':'release','git':commit,'release_tag':release['tag_name'],'asset':asset['name'],
        'asset_url':asset['browser_download_url'],'asset_sha256':observed,'checksum_verified':bool(expected),
        'source_archive_sha256':source_hash,'engine_relative_path':str(engine_relative)}
