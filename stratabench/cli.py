from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import webbrowser

from .common import ROOT, capture, hardware, local_lock, read_json, save_settings, settings
from . import datasets, versions
from .runner import BUDGETS, make_targets, run


def initialize(root=None):
    state = settings()
    if root:
        state['strata_root'] = str(Path(root).expanduser().resolve())
    save_settings(state)
    if not state['versions'] and state.get('strata_root'):
        from .acquisition import preferences
        cfg = preferences(state)
        if cfg['method'] == 'local':
            versions.snapshot(source=cfg['folder'] or state['strata_root'])
    return settings()


def show_configs():
    found = versions.discover()
    for i, cfg in enumerate(found, 1):
        args = cfg['args']
        def arg(name):
            return args[args.index(name)+1] if name in args and args.index(name)+1 < len(args) else 'default'
        print(f'{i:2}. {cfg["name"]}' + (' (symlink alias)' if cfg['alias'] else ''))
        print(f'    {cfg["model"]} | context {arg("--max-context")} | KV {arg("--kv")} | spec {arg("--spec")}')
    return found


def resolve_configs(values):
    root = Path(settings()['strata_root'])
    found = versions.discover()
    if values == ['all']:
        return [x['path'] for x in found if not x['alias']]
    paths = []
    for value in values:
        p = Path(value).expanduser()
        if not p.is_file():
            name = value if value.endswith('.json') else value+'.json'
            p = root / name
        if not p.is_file():
            raise ValueError('Config not found: ' + value)
        paths.append(str(p.resolve()))
    return list(dict.fromkeys(paths))


def choose(items, title, default='1'):
    if not items:
        raise ValueError('No available choices: ' + title)
    print('\n' + title)
    for i, label in enumerate(items, 1):
        print(f'  {i}. {label}')
    value = input(f'Numbers separated by spaces, or all [{default}]: ').strip() or default
    if value.lower() == 'all':
        return list(range(len(items)))
    try:
        indices = list(dict.fromkeys(int(x)-1 for x in value.replace(',', ' ').split()))
        if any(x < 0 or x >= len(items) for x in indices):
            raise ValueError()
        return indices
    except ValueError:
        raise ValueError('Choose one or more numbers from the list.') from None


def ask_reasoning(default='xhigh'):
    value = input(f'Reasoning: off / low / medium / high / xhigh / default [{default}]: ').strip() or default
    if value not in ('off', 'low', 'medium', 'high', 'xhigh', 'default'):
        raise ValueError('Unknown reasoning setting.')
    return value


def doctor():
    state = settings()
    print('Strata root:', state['strata_root'])
    print('Benchmark folder:', ROOT)
    hw = hardware()
    print('GPU:', hw['gpu']['output'])
    print('RAM:', json.dumps(hw['ram']))
    from .acquisition import preferences
    from .platforms import find_python
    cfg = preferences(state)
    py = next((v['python'] for v in state['versions'].values()), None) or find_python(cfg['folder'] or None, cfg['python'] or None)
    check = capture([py, '-c', 'import jinja2, regex, numpy; print("Strata Python dependencies are available")'])
    print(check['output'])
    for name in ('cmake', 'nvcc', 'git'):
        import shutil
        print(name + ':', shutil.which(name) or 'not found (only needed for adding versions)')
    print('Registered versions:', ', '.join(state['versions']) or 'none')
    print('Discovered configs:', len(versions.discover()))
    print('Public datasets:', 'downloaded' if (ROOT / 'datasets/sources.lock.json').exists() else 'not downloaded; ./bench datasets')
    print('No driver, system package, model or original config is installed or changed by StrataBench.')
    return hw['gpu']['ok'] and check['ok']


def cases_for(profile, seed, only=None, context_words=None, task_file=None):
    if task_file:
        cases = [json.loads(line) for line in Path(task_file).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        if not cases or len({x['id'] for x in cases}) != len(cases):
            raise ValueError('Custom cases need unique ids and at least one question.')
        for c in cases:
            if not all(k in c for k in ('id', 'group', 'difficulty', 'prompt', 'answer', 'grader')):
                raise ValueError('Custom cases need id, group, difficulty, prompt, answer, grader.')
            if c['difficulty'] not in datasets.DIFFICULTIES or c['grader'] not in ('numeric', 'exact', 'choice', 'json'):
                raise ValueError('Unsupported custom difficulty or grader.')
        return cases
    if datasets.PROFILES[profile]['public']:
        try:
            datasets.load_public()
        except RuntimeError:
            datasets.prepare_public()
    return datasets.select(profile, seed, only, context_words)


def show_plan(cases, targets, options):
    print('\nBenchmark plan')
    print('  Questions:', len(cases), '| repeats:', options['repeats'], '| combinations:', len(targets))
    print('  Reasoning:', options['reasoning'], '| temperature:', options['temperature'])
    print('  Difficulty:', ', '.join(f'{k}: {v}' for k, v in Counter(c['difficulty'] for c in cases).items()))
    print('  Groups:', ', '.join(sorted({c['group'] for c in cases})))
    print('  Maximum answer tokens:', options.get('max_tokens') or json.dumps(BUDGETS))
    print('  The answer limit includes thinking. Cutoffs count as failures and are shown separately.')
    print('  Time varies substantially with thinking and SSD reads. Start with smoke or quick.')
    for t in targets:
        print('   •', t['label'])


def execute(args):
    state = settings() if args.endpoint else initialize()
    effort = args.reasoning
    if effort is None:
        effort = ask_reasoning() if sys.stdin.isatty() else 'xhigh'
    options = {'profile': args.profile if not args.tasks else 'custom', 'reasoning': effort,
               'temperature': args.temperature, 'seed': args.seed, 'repeats': args.repeats,
               'max_tokens': args.max_tokens, 'timeout': args.timeout, 'startup_timeout': args.startup_timeout,
               'port': args.port, 'keep_vision': args.keep_vision, 'model': args.model}
    if args.repeats < 1 or args.timeout <= 0 or args.startup_timeout <= 0 or args.temperature < 0:
        raise ValueError('Repeats and timeouts must be positive; temperature must be nonnegative.')
    if args.max_tokens is not None and args.max_tokens < 1:
        raise ValueError('The answer token limit must be positive.')
    cases = cases_for(args.profile, args.seed, args.only, args.context_words, args.tasks)
    if any(c.get('requires_vision') for c in cases):options['keep_vision']=True
    if args.profile in ('tools','coding'):options['agent_turns']=args.agent_turns
    if args.profile=='coding':
        from .coding_runtime import image_id
        options['coding_image_id']=image_id(args.coding_image)
        options['coding_image']=args.coding_image
    if args.style_judge_endpoint:
        from urllib.parse import urlsplit
        parsed=urlsplit(args.style_judge_endpoint)
        if args.profile!='writing' or parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or not args.style_judge_model:
            raise ValueError('The optional writing judge needs a valid endpoint and model, and the Writing suite.')
        options.update(style_judge_endpoint=args.style_judge_endpoint.rstrip('/'),style_judge_model=args.style_judge_model,style_judge_key_required=bool(os.environ.get('STRATABENCH_JUDGE_API_KEY')))
    if args.endpoint:
        from urllib.parse import urlsplit
        if urlsplit(args.endpoint).scheme not in ('http', 'https'):
            raise ValueError('Endpoint must be an http(s) URL ending in /v1.')
        from .common import digest
        target = {'id': digest([args.endpoint, args.label])[:14], 'label': args.label or args.endpoint,
                  'endpoint': args.endpoint.rstrip('/')}
        targets = [target]
    else:
        if not args.configs:
            raise ValueError('Choose --configs CONFIG.json (or use the interactive menu).')
        names = args.versions or list(state['versions'])[:1]
        missing = [name for name in names if name not in state['versions']]
        if missing:
            raise ValueError('Prepare these versions first: ./bench add-version ' + missing[0])
        targets = make_targets([state['versions'][name] for name in names], resolve_configs(args.configs))
    if any(c.get('requires_vision') for c in cases):
        for target in targets:
            if target.get('endpoint'):continue
            config=read_json(target['config'])
            if not config.get('vision') or versions.vision_executable(target['version'],config,target['config']) is None:
                raise ValueError('Vision tests require an image-encoder config and an available strata-vision executable: '+target['label'])
    show_plan(cases, targets, options)
    if args.dry_run:
        return
    with local_lock('.run.lock'):
        return run(cases, targets, options, args.resume)


def resume(folder):
    folder = Path(folder).expanduser().resolve()
    manifest = read_json(folder / 'manifest.json')
    targets = manifest['targets']
    if manifest['options'].get('coding_image_id'):
        from .coding_runtime import image_id
        image_id(manifest['options']['coding_image_id'])
    for target in targets:
        if not target.get('endpoint'):
            new = make_targets([target['version']], [target['config']])[0]
            if new != target:
                raise RuntimeError('The original configuration, tokenizer or model files changed; start a new run.')
    with local_lock('.run.lock'):
        run(read_json(folder / 'cases.json'), targets, manifest['options'], folder)


def menu():
    initialize()
    print('\nStrataBench — local model quality comparisons')
    while True:
        print('\n1  Run benchmarks\n2  Add a Strata version\n3  List versions and model configs\n'
              '4  Resume a run\n5  Open a report\n6  Download public benchmarks\n'
              '7  Check this PC\n8  Compare saved runs\n0  Exit')
        action = input('Choose [1]: ').strip() or '1'
        try:
            if action == '0':
                return
            if action == '1':
                state = settings()
                names = list(state['versions'])
                chosen_v = [names[i] for i in choose(names, 'Versions')]
                configs = [x for x in versions.discover() if not x['alias']]
                chosen_c = [configs[i]['path'] for i in choose([x['name'] for x in configs], 'Model configs')]
                profiles = list(datasets.PROFILES)
                print('\nProfiles: smoke = 7 generated checks; quick = 69; standard = 276; deep = 648; full = 4363; context = long text only.')
                profile = input('Profile [quick]: ').strip() or 'quick'
                if profile not in profiles:
                    raise ValueError('Unknown profile: ' + profile)
                effort = ask_reasoning()
                repeats = int(input('Repeats per question [1] (use 3 for a more reliable comparison): ').strip() or '1')
                limit = input('Answer token limit [auto by difficulty]: ').strip()
                cmd = ['run', '--versions', *chosen_v, '--configs', *chosen_c, '--profile', profile,
                       '--reasoning', effort, '--repeats', str(repeats)]
                if limit:
                    cmd += ['--max-tokens', str(int(limit))]
                if profile == 'context':
                    words = input('Context sizes in words [2000 8000 16000 32000]: ').strip()
                    if words:
                        cmd += ['--context-words', *words.split()]
                print('\nRepeat this run from a terminal with:\n  ./bench ' + shlex.join(cmd))
                execute(parser().parse_args(cmd))
            elif action == '2':
                tag = input('Strata release tag, for example v0.1.44.1: ').strip()
                with local_lock('.prepare.lock'):
                    versions.build(tag)
            elif action == '3':
                for name, version in settings()['versions'].items():
                    print(name, '—', version['kind'], '—', version['root'])
                show_configs()
            elif action in ('4', '5', '8'):
                folders = sorted((ROOT / 'results').glob('*/manifest.json'), reverse=True)
                if not folders:
                    print('No saved benchmark runs yet.')
                    continue
                indices = choose([x.parent.name for x in folders], 'Saved runs')
                if action == '4':
                    if len(indices) != 1:
                        raise ValueError('Choose one run to resume.')
                    resume(folders[indices[0]].parent)
                elif action == '5':
                    from .report import generate
                    for i in indices:
                        folder = folders[i].parent
                        generate(folder)
                        webbrowser.open((folder / 'report.html').as_uri())
                else:
                    from .report import generate
                    output = ROOT / 'results' / ('comparison-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
                    generate(output, [folders[i].parent for i in indices])
                    print(output / 'report.html')
                    webbrowser.open((output / 'report.html').as_uri())
            elif action == '6':
                with local_lock('.prepare.lock'):
                    cases = datasets.prepare_public()
                print(f'{len(cases)} public cases ready; future runs work offline.')
            elif action == '7':
                doctor()
            else:
                print('Choose a listed number.')
        except (ValueError, RuntimeError, OSError, KeyError) as e:
            print('\n' + str(e))


def parser():
    p = argparse.ArgumentParser(description='StrataBench: compare local Strata versions and model configs.')
    sub = p.add_subparsers(dest='command')
    sub.add_parser('gui', help='Open the graphical app in your browser')
    q = sub.add_parser('init', help='Snapshot the current engine and discover configs')
    q.add_argument('--strata-root')
    sub.add_parser('configs', help='List model configs')
    sub.add_parser('versions', help='List prepared versions')
    sub.add_parser('doctor', help='Read-only check of GPU, Python and build tools')
    sub.add_parser('datasets', help='Download/cache public datasets once')
    q = sub.add_parser('add-version', help='Prepare a version using the configured Strata source')
    q.add_argument('tag')
    q.add_argument('--jobs', type=int)
    q.add_argument('--python')
    q.add_argument('--cmake-arg', action='append', default=[], help='Example: --cmake-arg=-DFOO=ON')
    q = sub.add_parser('prepare-coding', help='Download the isolated Python Docker runtime')
    q.add_argument('--image', default='python:3.12-slim')
    q = sub.add_parser('source', help='Show or configure Strata acquisition settings')
    q.add_argument('--method', choices=['local','repository','folder','release'])
    q.add_argument('--repository')
    q.add_argument('--folder')
    q.add_argument('--config-folder')
    q.add_argument('--python')
    q.add_argument('--python-mode', choices=['managed','existing'])
    q.add_argument('--backend', choices=['cuda12','cuda13','hip','sycl'])
    q.add_argument('--asset')
    q.add_argument('--cuda-architectures')
    q.add_argument('--build-jobs', type=int)
    q.add_argument('--allow-unverified', action=argparse.BooleanOptionalAction, default=None)
    q = sub.add_parser('snapshot', help='Copy a separately built engine and its matching server')
    q.add_argument('--name', required=True)
    q.add_argument('--source', required=True)
    q.add_argument('--exe')
    q.add_argument('--python')
    q = sub.add_parser('tasks', help='Show selected case counts without starting a model')
    q.add_argument('--profile', choices=datasets.PROFILES, default='smoke')
    q.add_argument('--seed', type=int, default=20261119)
    q.add_argument('--only')
    q = sub.add_parser('run', help='Run a version × config matrix, one model at a time')
    q.add_argument('--versions', nargs='+')
    q.add_argument('--configs', nargs='+')
    q.add_argument('--profile', choices=datasets.PROFILES, default='quick')
    q.add_argument('--reasoning', choices=['off', 'low', 'medium', 'high', 'xhigh', 'default'])
    q.add_argument('--seed', type=int, default=20261119)
    q.add_argument('--temperature', type=float, default=0.0)
    q.add_argument('--repeats', type=int, default=1)
    q.add_argument('--max-tokens', type=int)
    q.add_argument('--timeout', type=float, default=1800, help='Per-request timeout in seconds')
    q.add_argument('--startup-timeout', type=float, default=900)
    q.add_argument('--port', type=int, default=18765, help='Dedicated loopback benchmark port')
    q.add_argument('--agent-turns', type=int, choices=range(1,33), default=8, help='Maximum model turns per tool/coding task')
    q.add_argument('--coding-image', default='python:3.12-slim')
    q.add_argument('--style-judge-endpoint')
    q.add_argument('--style-judge-model')
    q.add_argument('--keep-vision', action='store_true', help='Also load the image encoder (suite remains text-only)')
    q.add_argument('--model', default='strata', help='API model name (Strata accepts arbitrary names)')
    q.add_argument('--only', help='Comma-separated task groups and/or difficulty levels')
    q.add_argument('--context-words', type=int, nargs='+', help='Context profile sizes in words, not tokens')
    q.add_argument('--tasks', help='Custom task JSONL file')
    q.add_argument('--dry-run', action='store_true')
    q.add_argument('--resume', help='Resume this result folder with identical settings')
    q.add_argument('--endpoint', help='Attach to an already running OpenAI-compatible server, ending in /v1')
    q.add_argument('--label', help='Version/config label for an attached server (user-supplied identity)')
    q = sub.add_parser('resume', help='Resume directly from the saved settings')
    q.add_argument('folder')
    q = sub.add_parser('report', help='Regenerate HTML, CSV and JSON reports')
    q.add_argument('folder')
    q = sub.add_parser('compare', help='Compare saved runs with matching tasks/settings')
    q.add_argument('folders', nargs='+')
    q.add_argument('--output')
    return p


def main():
    p = parser()
    args = p.parse_args()
    try:
        if not args.command:
            if not sys.stdin.isatty():
                p.print_help()
                return 0
            menu()
        elif args.command == 'gui':
            from .gui import launch
            launch()
        elif args.command == 'init':
            with local_lock('.prepare.lock'):
                initialize(args.strata_root)
            show_configs()
        elif args.command == 'prepare-coding':
            from .coding_runtime import prepare
            print('Coding runtime ready: '+prepare(args.image))
        elif args.command == 'source':
            from .acquisition import configure, preferences
            data = {k:v for k,v in vars(args).items() if k != 'command' and v is not None}
            with local_lock('.prepare.lock'):
                cfg = configure(data) if data else preferences()
            print(json.dumps(cfg,indent=2))
        elif args.command == 'configs':
            show_configs()
        elif args.command == 'versions':
            for name, version in settings()['versions'].items():
                print(name, version['root'])
        elif args.command == 'doctor':
            return 0 if doctor() else 1
        elif args.command == 'datasets':
            with local_lock('.prepare.lock'):
                cases = datasets.prepare_public()
            print(f'{len(cases)} public cases ready.')
        elif args.command == 'add-version':
            with local_lock('.prepare.lock'):
                if args.jobs is not None and args.jobs < 1:
                    raise ValueError('Build jobs must be positive.')
                versions.build(args.tag, args.jobs, args.cmake_arg, args.python)
        elif args.command == 'snapshot':
            with local_lock('.prepare.lock'):
                versions.snapshot(args.name, args.source, args.exe, args.python)
        elif args.command == 'run':
            folder = execute(args)
            if folder and read_json(folder / 'manifest.json')['status'] != 'complete':
                return 1
        elif args.command == 'resume':
            resume(args.folder)
        elif args.command == 'tasks':
            cases = cases_for(args.profile, args.seed, args.only)
            print(json.dumps({'cases': len(cases), 'by_group': Counter(x['group'] for x in cases),
                              'by_difficulty': Counter(x['difficulty'] for x in cases)}, indent=2))
        elif args.command in ('report', 'compare'):
            from .report import generate
            if args.command == 'report':
                generate(args.folder)
                print(Path(args.folder).resolve() / 'report.html')
            else:
                output = Path(args.output) if args.output else ROOT / 'results' / ('comparison-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
                generate(output, args.folders)
                print(output.resolve() / 'report.html')
    except KeyboardInterrupt:
        print('\nStopped.')
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as e:
        print('Error: ' + str(e), file=sys.stderr)
        return 1
    return 0
