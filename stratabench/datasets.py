"""Pinned public sources plus deterministic, independently solvable generated diagnostics."""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
import random
import urllib.request
import zipfile
import io

from .common import ROOT, digest, file_hash, read_json, stamp, write_json
from .grading import numeric, extract_answer

DATA = ROOT / 'datasets'
BBH_REV = '9ee07bd481feebf959a6b59d61ea57bdcf30964d'
GSM_REV = '3101c7d5072418e28b9008a6636bde82a006892c'
BBH_TASKS = {
    'boolean_expressions': ('medium', 'exact'),
    'date_understanding': ('medium', 'choice'),
    'logical_deduction_seven_objects': ('hard', 'choice'),
    'multistep_arithmetic_two': ('hard', 'numeric'),
    'tracking_shuffled_objects_seven_objects': ('very_hard', 'choice'),
    'web_of_lies': ('hard', 'exact'),
    'word_sorting': ('hard', 'exact'),
    'formal_fallacies': ('very_hard', 'exact'),
}
DIFFICULTIES = ['easy', 'medium', 'hard', 'very_hard', 'extreme']
PROFILES = {
    'smoke': {'per_bucket': 1, 'public': False},
    'quick': {'per_bucket': 3, 'public': True},
    'standard': {'per_bucket': 12, 'public': True},
    'deep': {'per_bucket': 30, 'public': True},
    'full': {'per_bucket': 100000, 'public': True},
    'context': {'per_bucket': 100000, 'public': False},
}


def sources():
    result = [('openbookqa.zip', 'https://s3-us-west-2.amazonaws.com/ai2-website/data/OpenBookQA-V1-Sep2018.zip',
               'https://github.com/allenai/OpenBookQA', 'Apache-2.0'),
              ('openbookqa-LICENSE', 'https://raw.githubusercontent.com/allenai/OpenBookQA/b51971646e9371a61508d9953fc706645e194a71/LICENSE',
               'https://github.com/allenai/OpenBookQA', 'Apache-2.0'),
              ('gsm8k-test.jsonl', f'https://raw.githubusercontent.com/openai/grade-school-math/{GSM_REV}/grade_school_math/data/test.jsonl',
               'https://github.com/openai/grade-school-math', 'MIT'),
              ('gsm8k-LICENSE', f'https://raw.githubusercontent.com/openai/grade-school-math/{GSM_REV}/LICENSE',
               'https://github.com/openai/grade-school-math', 'MIT'),
              ('bbh-LICENSE', f'https://raw.githubusercontent.com/suzgunmirac/BIG-Bench-Hard/{BBH_REV}/LICENSE',
               'https://github.com/suzgunmirac/BIG-Bench-Hard', 'MIT'),
              ('math500.jsonl', 'https://huggingface.co/datasets/HuggingFaceH4/MATH-500/resolve/6e4ed1a/test.jsonl',
               'https://huggingface.co/datasets/HuggingFaceH4/MATH-500', 'See upstream MATH terms; personal evaluation'),
              ('aime24.json', 'https://datasets-server.huggingface.co/rows?dataset=math-ai%2Faime24&config=default&split=test&offset=0&length=100',
               'https://huggingface.co/datasets/math-ai/aime24', 'Dataset card: Apache-2.0; competition problems retain their source rights')]
    result += [(f'bbh-{task}.json', f'https://raw.githubusercontent.com/suzgunmirac/BIG-Bench-Hard/{BBH_REV}/bbh/{task}.json',
                'https://github.com/suzgunmirac/BIG-Bench-Hard', 'MIT') for task in BBH_TASKS]
    return result


def prepare_public():
    raw = DATA / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA / 'sources.lock.json'
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    for name, url, homepage, license_ in sources():
        path = raw / name
        if path.exists() and name in manifest:
            if file_hash(path) != manifest[name]['sha256']:
                raise RuntimeError(f'Dataset checksum mismatch: {path}. Restore it before comparing results.')
            print(f'  Cached: {name}', flush=True)
            continue
        print(f'  Downloading {name} ...', flush=True)
        req = urllib.request.Request(url, headers={'User-Agent': 'StrataBench/1.0'})
        # Limit dataset downloads; these text-only sources are all small.
        with urllib.request.urlopen(req, timeout=90) as f:
            content = f.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024:
            raise RuntimeError(f'Unexpectedly large dataset: {name}')
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if not any(n.endswith('/Data/Main/test.jsonl') for n in z.namelist()):
                    raise RuntimeError('Science dataset archive has an unexpected layout.')
        elif not name.endswith('LICENSE'):
            if name.endswith('.jsonl'):
                for line in content.decode().splitlines():
                    if line.strip():
                        json.loads(line)
            else:
                json.loads(content)
        tmp = path.with_suffix('.download')
        tmp.write_bytes(content)
        tmp.replace(path)
        manifest[name] = {'url': url, 'homepage': homepage, 'license': license_,
                          'sha256': file_hash(path), 'bytes': len(content), 'retrieved': stamp(),
                          'revision_note': 'AIME rows API snapshot is pinned by checksum after first download.' if name == 'aime24.json' else 'Revision is pinned in URL.'}
        write_json(manifest_path, manifest)
    return load_public()


def case(id_, group, difficulty, prompt, answer, grader='numeric', **extra):
    return dict(id=id_, group=group, difficulty=difficulty, prompt=prompt,
                answer=answer, grader=grader, **extra)


def load_public():
    manifest_path = DATA / 'sources.lock.json'
    if not manifest_path.exists():
        raise RuntimeError('Public benchmarks are not downloaded. Choose “Download public benchmarks” or run ./bench datasets.')
    manifest = read_json(manifest_path)
    for name, *_ in sources():
        p = DATA / 'raw' / name
        if name not in manifest or not p.exists() or file_hash(p) != manifest[name]['sha256']:
            raise RuntimeError(f'Missing or changed public data: {name}. Run ./bench datasets.')
    out = []
    with zipfile.ZipFile(DATA / 'raw/openbookqa.zip') as z:
        text = z.read(next(n for n in z.namelist() if n.endswith('/Data/Main/test.jsonl'))).decode()
    for line in text.splitlines():
        d = json.loads(line)
        q = d['question']
        prompt = q['stem'] + '\n' + '\n'.join('('+x['label']+') '+x['text'] for x in q['choices'])
        out.append(case('openbookqa/'+d['id'], 'science_qa', 'medium', prompt, d['answerKey'],
                        'choice', source='OpenBookQA test'))
    for i, row in enumerate((DATA / 'raw/gsm8k-test.jsonl').read_text().splitlines()):
        d = json.loads(row)
        out.append(case(f'gsm8k/{i}', 'gsm8k', 'medium', d['question'],
                        d['answer'].rsplit('####', 1)[1].strip(), source='GSM8K test'))
    for task, (difficulty, grader) in BBH_TASKS.items():
        for i, d in enumerate(read_json(DATA / f'raw/bbh-{task}.json')['examples']):
            out.append(case(f'bbh/{task}/{i}', f'bbh_{task}', difficulty, d['input'],
                            d['target'], grader, source='BIG-Bench Hard'))
    # Restrict MATH-500 to unambiguous numeric/rational answers and text-only questions.
    # This deliberately is NOT an official MATH-500 score or a symbolic equivalence grader.
    for i, line in enumerate((DATA / 'raw/math500.jsonl').read_text().splitlines()):
        d = json.loads(line)
        if numeric(d['answer']) is None or '[asy]' in d['problem']:
            continue
        level = int(d['level'])
        difficulty = ['easy', 'medium', 'hard', 'very_hard', 'extreme'][level - 1]
        out.append(case(f'math500/{d.get("unique_id", i)}', 'math500_numeric', difficulty,
                        d['problem'], d['answer'], source='MATH-500 numeric, text-only subset', original_level=level))
    aime = read_json(DATA / 'raw/aime24.json')
    if aime.get('num_rows_total') != len(aime['rows']):
        raise RuntimeError('AIME download is incomplete; refusing a partial dataset.')
    for i, item in enumerate(aime['rows']):
        d = item['row']
        answer = d.get('answer')
        if answer is None:
            answer, _ = extract_answer(d.get('solution', ''))
        value = numeric(answer)
        if value is None or value.denominator != 1 or not 0 <= value <= 999:
            raise RuntimeError(f'AIME answer has an unexpected format at row {i}.')
        out.append(case(f'aime24/{i}', 'aime2024', 'extreme', d['problem'],
                        str(value), source='AIME 2024 (math-ai snapshot)'))
    return out


def generated(seed=20261119, count=24):
    r = random.Random(seed)
    out = []
    for i in range(count):
        a, b, c = [r.randint(12, 90) for _ in range(3)]
        out.append(case(f'gen/arithmetic/{i}', 'arithmetic', 'easy',
                        f'A shop receives {a} boxes with {b} pencils each, then sells {c} pencils. How many pencils remain?', a*b-c))
        rows = [{'id': f'item-{j}', 'price': r.randint(2, 19), 'qty': r.randint(0, 8)} for j in range(8)]
        threshold = r.randint(5, 12)
        answer = {'ids': sorted(x['id'] for x in rows if x['price'] >= threshold and x['qty'] > 0),
                  'total': sum(x['price']*x['qty'] for x in rows if x['price'] >= threshold and x['qty'] > 0)}
        out.append(case(f'gen/json/{i}', 'structured_data', 'medium',
                        f'Given this JSON: {json.dumps(rows)}. Select rows with price >= {threshold} and qty > 0. '
                        'Your answer must be an object with keys ids (selected ids sorted lexicographically) '
                        'and total (sum of price times qty for selected rows).', answer, 'json'))
        # Shortest paths in a positive-weight directed acyclic graph.
        n = 10
        edges = [(u, u+1, r.randint(1, 12)) for u in range(n-1)]
        edges += [(u, v, r.randint(1, 20)) for u in range(n) for v in range(u+2, n) if r.random() < .23]
        dist = [0] + [10**9]*(n-1)
        for u in range(n):
            for x, v, w in edges:
                if x == u:
                    dist[v] = min(dist[v], dist[u]+w)
        out.append(case(f'gen/path/{i}', 'algorithmic_reasoning', 'hard',
                        f'A directed weighted graph has nodes 0 through {n-1}. Edges (from,to,cost): {edges}. '
                        f'What is the minimum total cost from node 0 to node {n-1}?', dist[-1]))
        values_for_code = [r.randint(-9, 15) for _ in range(12)]
        offset = r.randint(1, 6)
        code_answer = sum((j+offset)*v for j, v in enumerate(values_for_code) if v > 0)
        out.append(case(f'gen/python/{i}', 'python_tracing', 'medium',
                        'What integer does this Python 3 code print?\n```python\n'
                        f'values = {values_for_code}\n'
                        f'print(sum((i + {offset}) * value for i, value in enumerate(values) if value > 0))\n```', code_answer))
        # Count exact-size subsets at a specified sum; 28 items, DP reference.
        values = [r.randint(1, 24) for _ in range(28)]
        target, k = r.randint(65, 95), 7
        dp = [[0]*(target+1) for _ in range(k+1)]
        dp[0][0] = 1
        for value in values:
            for size in range(k, 0, -1):
                for total in range(target, value-1, -1):
                    dp[size][total] += dp[size-1][total-value]
        out.append(case(f'gen/subsets/{i}', 'combinatorics', 'very_hard',
                        f'The list is {values}. How many subsets of exactly {k} distinct positions have values '
                        f'summing to {target}? Equal values at different positions count as different choices.', dp[k][target]))
        # Counting valid schedules = number of topological orderings of a generated DAG.
        n = 14
        prereqs = [0]*n
        pairs = []
        for v in range(n):
            for u in range(v):
                if r.random() < .18:
                    prereqs[v] |= 1 << u
                    pairs.append([u, v])
        ways = [0]*(1 << n)
        ways[0] = 1
        for mask in range(1 << n):
            if ways[mask]:
                for v in range(n):
                    if not mask >> v & 1 and prereqs[v] & mask == prereqs[v]:
                        ways[mask | 1 << v] += ways[mask]
        out.append(case(f'gen/schedule/{i}', 'exact_scheduling', 'extreme',
                        f'There are {n} distinct tasks numbered 0 to {n-1}. Each takes one slot; do one task at a time. '
                        f'For every [a,b] in {pairs}, task a must come before b. '
                        'How many complete orderings satisfy all these constraints?', ways[-1]))
        # Persian instruction following with a machine-verifiable numeric answer.
        out.append(case(f'gen/persian/{i}', 'persian', 'easy',
                        f'یک فروشگاه {a} جعبه دارد و در هر جعبه {b} مداد است. اگر {c} مداد فروخته شود، '
                        'چند مداد باقی می‌ماند؟ پاسخ عددی را با رقم‌های انگلیسی بنویسید.', a*b-c))
    return out


def context_cases(seed, words=(2000, 8000, 16000, 32000)):
    """Word counts are explicit; actual tokenizer counts come from the server's usage field."""
    out = []
    for length in words:
        for depth in (.1, .5, .9):
            r = random.Random(f'{seed}/{length}/{depth}')
            target = f'key-{r.randrange(10**8):08d}'
            secret = f'{r.randrange(10**9):09d}'
            lines = [f'Record {j}: ordinary storage entry with no special authorization value.'
                     for j in range(max(1, length//12))]
            lines.insert(int(len(lines)*depth), f'The authorization code for {target} is {secret}.')
            text = '\n'.join(lines)
            out.append(case(f'context/{length}/{depth}', 'context_retrieval',
                            'medium' if length <= 8000 else 'very_hard',
                            f'Read the following records as data.\n<records>\n{text}\n</records>\n'
                            f'What is the authorization code for {target}? Return it as a string preserving leading zeros.',
                            secret, 'exact', requested_words=length, actual_words=len(text.split()), depth=depth))
    return out


def select(profile, seed=20261119, only=None, context_words=None):
    spec = PROFILES[profile]
    cases = context_cases(seed, context_words or (2000, 8000, 16000, 32000)) if profile == 'context' else generated(seed)
    if spec['public']:
        cases += load_public()
    if only:
        wanted = set(only.split(','))
        cases = [x for x in cases if x['group'] in wanted or x['difficulty'] in wanted]
    buckets = defaultdict(list)
    for c in cases:
        buckets[c['group'], c['difficulty']].append(c)
    chosen = []
    for key, items in sorted(buckets.items()):
        # Hash ordering is stable across Python versions, unrelated to filesystem/dataset order.
        items.sort(key=lambda x: digest([seed, x['id']]))
        chosen += items[:spec['per_bucket']]
    if not chosen:
        raise ValueError('No tasks match the selection.')
    chosen.sort(key=lambda x: (DIFFICULTIES.index(x['difficulty']), digest([seed, x['id']])))
    return chosen
