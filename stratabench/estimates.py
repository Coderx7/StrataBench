"""Planning ranges, calibrated conservatively from this machine's saved answer timings."""
from collections import defaultdict
import math
from pathlib import Path
import statistics

from .common import ROOT, digest, file_hash, read_json
from . import budgets
from .runner import BUDGETS

# Deliberately broad output-token assumptions: these are not model-quality measurements.
TOKEN_RANGES = {
    'off': [(32,160),(80,500),(150,1200),(300,2500),(500,5000)],
    'low': [(80,450),(200,1200),(500,2800),(1000,5500),(1500,10000)],
    'medium': [(100,700),(400,2200),(1000,5000),(2000,9000),(3500,15000)],
    'xhigh': [(120,1100),(700,3500),(1800,7500),(3500,12000),(6000,16384)],
}
LEVELS = list(BUDGETS)


def effort(value):
    return 'xhigh' if value in ('high','xhigh',None) else value


def rates(config):
    """RTX 3080 / 64 GB planning assumptions, not measured performance claims."""
    text = (str(config.get('model',''))+' '+str(config.get('name',''))).lower()
    if 'qwen36' in text or 'qwen3.6' in text:
        return (25.,65.)
    if 'q4_k_xl' in text:
        return (3.,10.)
    if 'iq4_xs' in text:
        return (6.,24.)
    if 'q3_k_xl' in text:
        return (8.,30.)
    if 'iq3_xxs' in text:
        return (18.,50.)
    if 'iq3_s' in text:
        return (15.,40.)
    return (5.,35.)


def timing_scope(options):
    profile=options.get('profile')
    if profile not in ('writing','vision','tools','coding','ifeval','bfcl','mmmu','writingbench','swebench'):return ''
    judge=bool(options.get('style_judge_enabled',bool(options.get('style_judge_endpoint'))))
    from .standard_suites import SPECS
    revision=options.get('standard_benchmark',{}).get('revision') or SPECS.get(profile,{}).get('revision')
    return digest({'profile':profile,'turns':int(options.get('agent_turns',8)) if profile in ('tools','coding','swebench') else None,
        'coding_image':options.get('coding_image','python:3.12-slim') if profile=='coding' else None,
        'judge':(options.get('style_judge_endpoint'),options.get('style_judge_model')) if (judge and profile=='writing' or profile=='writingbench') else None,
        'standard_revision':revision})


class TimingHistory:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.signature = None
        self.samples = defaultdict(dict)
        self.startups = defaultdict(list)
        self.last_check = 0

    def refresh(self):
        import time
        if time.monotonic()-self.last_check < 15:
            return
        self.last_check = time.monotonic()
        manifests = sorted((self.root/'results').glob('*/manifest.json'))
        files = manifests + sorted((self.root/'results').glob('*/*/answers.jsonl')) + sorted((self.root/'results').glob('*/*/session.json'))
        signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files if p.is_file())
        if signature == self.signature:
            return
        samples, startups = defaultdict(dict), defaultdict(list)
        for path in manifests:
            try:
                manifest = read_json(path)
                options = manifest['options']
                for target in manifest['targets']:
                    if target.get('endpoint'):
                        continue
                    config = target['config']
                    key = (config, target.get('config_sha256'), target['version']['name'], effort(options.get('reasoning')),timing_scope(options))
                    session = path.parent/target['id']/'session.json'
                    if session.exists():
                        seconds = read_json(session).get('startup_seconds')
                        if isinstance(seconds,(int,float)) and seconds>0:
                            startups[(config,target.get('config_sha256'),target['version']['name'])].append(seconds)
                    answers = path.parent/target['id']/'answers.jsonl'
                    if not answers.exists():
                        continue
                    # Retain the latest attempt; repeated copies of a smoke question are not independent coverage.
                    latest = {}
                    with answers.open(encoding='utf-8') as f:
                        for line in f:
                            try:
                                row = __import__('json').loads(line)
                                latest[(row['case_id'],row['repeat'])] = row
                            except (ValueError,KeyError):
                                continue
                    for row in latest.values():
                        seconds = row.get('elapsed_seconds')
                        if row.get('error') or not isinstance(seconds,(int,float)) or not 0<seconds<86400:
                            continue
                        level = row.get('difficulty')
                        if level in LEVELS:
                            sample = {'seconds': seconds, 'budget': row.get('request',{}).get('max_tokens'),'thinking':row.get('request',{}).get('reasoning_budget_tokens')}
                            samples[(key,level)][row['case_id']] = sample
            except (OSError,ValueError,KeyError,TypeError):
                continue
        self.samples,self.startups,self.signature = samples,startups,signature

    def estimate(self, config, version, counts, options):
        path = str(Path(config['id']).resolve())
        sha = file_hash(path) if Path(path).is_file() else None
        reasoning = effort(options.get('reasoning','xhigh'))
        slow,fast = rates(config)
        lower,upper = 0.,0.
        known_questions,measured_levels = 0,[]
        repeat = max(1,int(options.get('repeats',1)))
        max_tokens = options.get('max_tokens')
        max_tokens = int(max_tokens) if max_tokens not in (None,'','auto') else None
        timeout = float(options.get('timeout') or 1800)
        context_words = options.get('context_words_list',[])
        for index,level in enumerate(LEVELS):
            n = counts.get(level,0)
            if not n:
                continue
            agent=options.get('profile') in ('tools','coding','swebench')
            turns=int(options.get('agent_turns',8)) if agent else 1
            budget = budgets.output_limit(options,level)
            thinking = budgets.thinking_limit(options,level)
            token_low,token_high = TOKEN_RANGES.get(reasoning,TOKEN_RANGES['xhigh'])[min(index,2) if level=='unrated' else index]
            if thinking and options.get('thinking_budgets') is not None and not options.get('thinking_budgets_default',False):token_high=max(token_high,thinking)
            generation_cap=min(budget,thinking+budgets.ANSWER_RESERVE) if thinking else budget
            lo = min(token_low,generation_cap)/fast + 1
            hi = min(token_high,generation_cap)/slow + 6
            if agent:lo*=min(3,turns);hi*=turns
            judged=options.get('profile')=='writingbench' or options.get('profile')=='writing' and options.get('style_judge_enabled',bool(options.get('style_judge_endpoint')))
            if judged:lo+=3;hi+=300
            if options.get('profile')=='writingbench':lo+=12;hi+=1200
            if options.get('profile')=='swebench':lo+=60;hi+=float(options.get('swe_test_timeout',900))
            if context_words:
                # These records tokenize differently from math: include a broad long-prompt read-time range.
                relevant = [w for w in context_words if ('medium' if w<=8000 else 'very_hard')==level]
                if relevant:
                    lo += statistics.mean(relevant)*1.3/1000
                    hi += statistics.mean(relevant)*2.2/80
            else:
                matches = self.samples.get(((path,sha,version,reasoning,timing_scope(options)),level),{})
                valid = [s['seconds'] for s in matches.values() if s.get('budget')==budget and s.get('thinking')==thinking]
                if valid:
                    median = statistics.median(valid)
                    known_questions += len(valid)
                    measured_levels.append(level)
                    # Small/easy-only samples cannot predict hard reasoning; only adjust that same level.
                    lo,hi = (min(valid)*.6,max(median*2,max(valid)*1.25)) if len(valid)<5 else (min(valid)*.75,max(valid)*1.5)
            judge_cap=(1500 if options.get('profile')=='writingbench' else 300) if judged else 0
            test_cap=float(options.get('swe_test_timeout',900)) if options.get('profile')=='swebench' else 0
            lower += min(lo,timeout*turns+judge_cap+test_cap)*n*repeat
            upper += min(max(lo,hi),timeout*turns+judge_cap+test_cap)*n*repeat
        startups = self.startups.get((path,sha,version),[])
        boot_low,boot_high = (max(20,min(startups)*.7),max(startups)*1.8) if startups else (45,300)
        startup_cap = float(options.get('startup_timeout') or 900)
        lower += min(boot_low+3,startup_cap)
        upper += min(boot_high+30,startup_cap)
        warnings = []
        context = int(config.get('context') or 0)
        if context_words and context and max(context_words)*2.2+(max_tokens or 12288)>context:
            warnings.append('Some requested documents may exceed this config’s context window.')
        return {'version':version,'config':config['id'],'name':config['name'],
            'lower_seconds':round(lower),'upper_seconds':round(max(lower,upper)),
            'local_sample_questions':known_questions,'measured_difficulties':measured_levels,
            'basis':'Local timings for matching difficulties + planning assumptions' if known_questions else 'Planning assumptions; not measured for this combination',
            'warnings':warnings}
