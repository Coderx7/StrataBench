from __future__ import annotations

from collections import defaultdict
import csv
import html
import json
from pathlib import Path
import random
import statistics

from .common import digest, read_json, write_json
from .reference_scores import catalog as reference_catalog, reference_rows


def wilson(success, n):
    if not n:
        return [0, 1]
    z, p = 1.96, success/n
    center = (p + z*z/(2*n))/(1+z*z/n)
    half = z*((p*(1-p)/n + z*z/(4*n*n))**.5)/(1+z*z/n)
    return [max(0, center-half), min(1, center+half)]


def latest_rows(path):
    from .runner import load_rows
    return {(r['case_id'], r['repeat']): r for r in load_rows(path)}


def comparison_key(manifest):
    return digest({'cases': manifest['cases_sha256'], 'options': manifest['options'],
                   'protocol': manifest['protocol_sha256'], 'environment': manifest.get('environment', {})})


def standard_metrics(cases,rows,repeats,options):
    benchmark=options.get('standard_benchmark')
    if not benchmark:return None
    suite=benchmark['suite'];planned=len(cases)*repeats
    scored=[r['standard_result'] for r in rows.values() if r.get('standard_result',{}).get('score') is not None and not r.get('error')]
    metrics={}
    for key in sorted({k for r in scored for k in r.get('metrics',{})}):
        metrics[key]=sum(r.get('metrics',{}).get(key,0) for r in scored)/(len(scored) if suite=='writingbench' and scored else planned)
    if suite=='ifeval':
        n=sum(len(c['upstream']['instruction_id_list']) for c in cases)*repeats
        for mode in ('strict','loose'):
            metrics['instruction_'+mode]=sum(sum(r.get('instruction_'+mode+'_checks',[])) for r in scored)/n
    if suite=='writingbench':
        value=sum(r['score'] for r in scored)/len(scored)*100 if scored else None
    else:value=sum(r['score'] for r in scored)/planned*100
    return {'suite':suite,'primary_name':benchmark['metric'],'primary_value':value,
        'metrics':metrics,'scored':len(scored),'planned':planned,'selection':benchmark['selection'],
        'judge_errors':sum(bool(r.get('standard_result',{}).get('judge_error')) for r in rows.values()),
        'notice':'Writing quality is the mean of successfully judged responses; incomplete coverage is not ranked.' if suite=='writingbench' else 'Errors, cutoffs and missing responses earn zero in the planned denominator.'}


def ranking_score(summary):
    standard=summary.get('standard_metrics')
    return (standard.get('primary_value') or 0)/100 if standard else summary['macro_accuracy']


def summarize(folder):
    folder = Path(folder)
    manifest = read_json(folder / 'manifest.json')
    cases = read_json(folder / 'cases.json')
    repeats = manifest['options']['repeats']
    quality_only=any(c.get('score_only') for c in cases)
    total = len(cases)*repeats
    summaries = []
    for target in manifest['targets']:
        rows = latest_rows(folder / target['id'] / 'answers.jsonl')
        expected_keys = {(c['id'], r) for c in cases for r in range(repeats)}
        rows = {k: v for k, v in rows.items() if k in expected_keys}
        groups, levels = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        per_case = {}
        for c in cases:
            successes = sum(bool(rows.get((c['id'], rep), {}).get('correct')) for rep in range(repeats))
            groups[c['group']][0] += successes
            groups[c['group']][1] += repeats
            levels[c['difficulty']][0] += successes
            levels[c['difficulty']][1] += repeats
            per_case[c['id']] = successes/repeats
            if quality_only:
                scores=[rows.get((c['id'],rep),{}).get('standard_result',{}).get('score') for rep in range(repeats)]
                scores=[score for score in scores if score is not None]
                per_case[c['id']]=statistics.mean(scores) if scores else None
        correct = sum(bool(r.get('correct')) for r in rows.values())
        elapsed = sum(r.get('elapsed_seconds', 0) for r in rows.values())
        tokens = sum(r.get('usage', {}).get('completion_tokens', 0) or 0 for r in rows.values())
        latencies = sorted(r.get('elapsed_seconds', 0) for r in rows.values())
        state = manifest.get('target_status', {}).get(target['id'], {})
        complete = len(rows) == total and state.get('state') == 'complete'
        standard=standard_metrics(cases,rows,repeats,manifest['options'])
        if standard and standard['suite']=='writingbench':complete=complete and standard['scored']==total
        groups = {k: {'correct': v[0], 'total': v[1], 'accuracy': v[0]/v[1]} for k, v in groups.items()}
        levels = {k: {'correct': v[0], 'total': v[1], 'accuracy': v[0]/v[1]} for k, v in levels.items()}
        if quality_only:
            for value in [*groups.values(),*levels.values()]:value.update(correct=None,accuracy=None)
        writing=[r for r in rows.values() if 'constraint_score' in r]
        judged=[r['style_judge'] for r in rows.values() if r.get('style_judge',{}).get('status')=='complete']
        capability={'constraint_score':statistics.mean(r['constraint_score'] for r in writing) if writing else None,
            'style_judge_score':statistics.mean(j['average'] for j in judged) if judged else None,
            'style_judge_count':len(judged),'style_judge_errors':sum(r.get('style_judge',{}).get('status')=='error' for r in rows.values()),
            'tool_calls':sum(r.get('tool_calls',0) for r in rows.values()),
            'tool_errors':sum(r.get('tool_errors',0) for r in rows.values())}
        summaries.append({**capability,'standard_metrics':standard,'id': target['id'], 'label': target['label'], 'folder': str(folder),
            'complete': complete, 'state': state.get('state', 'pending'), 'failure': state.get('error'),
            'planned': total, 'answered': len(rows), 'correct': None if quality_only else correct, 'accuracy': None if quality_only else correct/total,
            'macro_accuracy': None if quality_only else statistics.mean(v['accuracy'] for v in groups.values()),
            'wilson_95': None if quality_only else wilson(correct, total), 'groups': groups, 'difficulty': levels,
            'errors': sum(bool(r.get('error')) for r in rows.values()),
            'truncated': sum(bool(r.get('truncated')) for r in rows.values()),
            'unparsed': sum(bool(r.get('unparsed')) for r in rows.values()),
            'json_format': sum(bool(r.get('json_format')) for r in rows.values()),
            'elapsed_seconds': elapsed, 'completion_tokens': tokens,
            'effective_tokens_per_second': tokens/elapsed if elapsed and tokens else None,
            'median_latency': statistics.median(latencies) if latencies else None,
            'p95_latency': latencies[min(len(latencies)-1, int(.95*len(latencies)))] if latencies else None,
            'per_case': per_case, 'external': bool(target.get('endpoint'))})
    return manifest, cases, summaries


def paired(a, b, cases, draws=1500):
    """Paired, stratified bootstrap. Resample questions, retaining all repeats of a question together."""
    buckets = defaultdict(list)
    for c in cases:
        buckets[c['group']].append(a['per_case'][c['id']] - b['per_case'][c['id']])
    rng = random.Random(707)
    samples = sorted(statistics.mean(sum(rng.choices(values, k=len(values)))/len(values)
                     for values in buckets.values()) for _ in range(draws))
    lo, hi = samples[int(.025*draws)], samples[int(.975*draws)]
    return {'a': a['label'], 'b': b['label'], 'delta': a['macro_accuracy']-b['macro_accuracy'],
            'interval_95': [lo, hi], 'interpretation': 'uncertain' if lo <= 0 <= hi else 'a ahead' if lo > 0 else 'b ahead'}


def pct(x):
    return '—' if x is None else f'{100*x:.1f}%'


def generate(folder, sources=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    sources = [Path(x) for x in sources] if sources else [folder]
    collected = [summarize(x) for x in sources]
    keys = {comparison_key(m) for m, _, _ in collected}
    if len(keys) != 1:
        raise ValueError('These runs use different questions, settings, environments or scoring code. Compare matching runs only.')
    manifest, cases, _ = collected[0]
    summaries = [s for _, _, ss in collected for s in ss]
    # Same combination in multiple runs: keep the latest complete run, or latest incomplete run if none complete.
    unique = {}
    for s in sorted(summaries, key=lambda s: (s['complete'], s['folder'])):
        unique[s['id']] = s
    summaries = sorted(unique.values(), key=lambda s: (s['complete'], ranking_score(s), s['accuracy']), reverse=True)
    completed = [s for s in summaries if s['complete']]
    quality_only=any(c.get('score_only') for c in cases)
    comparisons = [paired(completed[0], other, cases) for other in completed[1:]] if completed and not quality_only else []
    refs = reference_catalog()
    refs['rows'] = reference_rows(c['group'] for c in cases)
    summary = {'method': 'equal weight per task group; reference/constraint/acceptance-test scoring; failed/missing answers score zero; optional judge ratings separate',
               'comparison_key': next(iter(keys)), 'options': manifest['options'],
               'case_count': len(cases), 'sources': [str(x) for x in sources],
               'ranking': summaries, 'paired_comparisons': comparisons, 'original_model_reference':refs}
    if manifest['options'].get('standard_benchmark'):
        summary['method']='Pinned upstream primary metric with the recorded StrataBench generation adapter; sampled/full coverage labelled explicitly; writing rubric quality has separate scored coverage and no binary threshold.'
    write_json(folder / 'summary.json', summary)
    if manifest['options'].get('standard_benchmark'):
        write_json(folder/'standard-metrics.json',{'benchmark':manifest['options']['standard_benchmark'],
            'results':[{'label':s['label'],'complete':s['complete'],**s['standard_metrics']} for s in summaries]})
        with (folder/'standard-metrics.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f);writer.writerow(['combination','metric','value','scored','planned','selection','complete'])
            for s in summaries:
                m=s['standard_metrics'];writer.writerow([s['label'],m['primary_name'],m['primary_value'],m['scored'],m['planned'],m['selection'],s['complete']])
                for k,v in m['metrics'].items():writer.writerow([s['label'],k,v,m['scored'],m['planned'],m['selection'],s['complete']])
    fields = ['label', 'complete', 'macro_accuracy', 'accuracy', 'correct', 'answered', 'planned',
              'errors', 'truncated', 'unparsed', 'elapsed_seconds', 'completion_tokens',
              'effective_tokens_per_second', 'median_latency', 'p95_latency', 'constraint_score','style_judge_score','style_judge_count','style_judge_errors','tool_calls','tool_errors','folder']
    with (folder / 'leaderboard.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(summaries)
    with (folder / 'reference-scores.csv').open('w', newline='', encoding='utf-8') as f:
        fields = ['group','original_model','reference_score_percent','weight_precision','kv_precision',
                  'publisher','source','method','directly_comparable','availability_note']
        fields += ['local_percent: '+s['label'] for s in summaries]
        writer = csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for reference in refs['rows']:
            group = reference['group']
            row = {'group':group,'original_model':refs['model'],
                'reference_score_percent':reference.get('score_percent'),
                'weight_precision':reference.get('weight_precision') or 'Not available',
                'kv_precision':reference.get('kv_precision'), 'publisher':reference.get('publisher'),
                'source':reference.get('source'),'method':reference.get('method'), 'directly_comparable':False,
                'availability_note':reference.get('comparison_note') or reference.get('reason')}
            row.update({'local_percent: '+s['label']:None if s['groups'][group]['accuracy'] is None else round(s['groups'][group]['accuracy']*100,4) for s in summaries})
            writer.writerow(row)
    e = lambda value: html.escape(str(value))
    rows = []
    for rank, s in enumerate(summaries, 1):
        rate = f'{s["effective_tokens_per_second"]:.1f}' if s['effective_tokens_per_second'] else '—'
        rows.append('<tr>' + ''.join(f'<td>{x}</td>' for x in [str(rank) if s['complete'] else '—',
            e(s['label']) + (' <span class="badge">attached server</span>' if s['external'] else ''),
            pct(s['macro_accuracy']), pct(s['accuracy']), f'{s["answered"]}/{s["planned"]}',
            str(s['errors']), str(s['truncated']), rate, f'{s["elapsed_seconds"]/60:.1f}',
            '<span class="ok">complete</span>' if s['complete'] else '<span class="bad">'+e(s['state'])+'</span>']) + '</tr>')
    group_names = sorted({c['group'] for c in cases})
    reference_table = []
    for reference in refs['rows']:
        group = reference['group']
        value = f'{reference["score_percent"]:.2f}%' if reference['available'] else 'Not available'
        explanation = reference.get('comparison_note') or reference.get('reason')
        source = ('<a href="'+e(reference['source'])+'">'+e(reference['publisher'])+'</a>') if reference.get('source') else '—'
        reference_table.append('<tr><td>'+e(group)+'</td><td>'+value+'</td><td>'+e(reference.get('weight_precision') or '—')+
            '</td>'+''.join('<td>'+pct(s['groups'][group]['accuracy'])+'</td>' for s in summaries)+
            '<td>'+source+'<br>'+e(reference.get('method') or '')+'<br>'+e(explanation)+'</td></tr>')
    group_rows = []
    for s in summaries:
        group_rows.append('<tr><td>'+e(s['label'])+'</td>'+''.join(
            '<td>'+pct(s['groups'][g]['accuracy'])+'</td>' for g in group_names)+'</tr>')
    level_order = ['easy', 'medium', 'hard', 'very_hard', 'extreme']
    levels = [x for x in level_order if any(c['difficulty'] == x for c in cases)]
    level_rows = ['<tr><td>'+e(s['label'])+'</td>'+''.join('<td>'+pct(s['difficulty'][d]['accuracy'])+'</td>' for d in levels)+'</tr>' for s in summaries]
    pairs = ['<li>'+e(p['a'])+' versus '+e(p['b'])+f': {100*p["delta"]:+.1f} percentage points; '
             f'paired 95% interval [{100*p["interval_95"][0]:+.1f}, {100*p["interval_95"][1]:+.1f}]; '+e(p['interpretation'])+'</li>' for p in comparisons]
    details = []
    for s in summaries:
        for row in latest_rows(Path(s['folder']) / s['id'] / 'answers.jsonl').values():
            if row.get('correct'):
                continue
            c = next((x for x in cases if x['id'] == row['case_id']), {})
            prompt = c.get('prompt', '')
            if len(prompt) > 12000:
                prompt = prompt[:5000] + '\n[Long prompt shortened in report; full prompt is in cases.json]\n' + prompt[-3000:]
            details.append('<details><summary>'+e(s['label'])+' · '+e(row['case_id'])+' · repeat '+str(row['repeat']+1)+
                (' · ERROR' if row.get('error') else ' · CUTOFF' if row.get('truncated') else '')+'</summary>'+
                '<h4>Question</h4><pre>'+e(prompt)+'</pre><h4>Expected</h4><pre>'+e(json.dumps(row['expected'], ensure_ascii=False))+
                '</pre><h4>Answer</h4><pre>'+e(row.get('content', row.get('error', '')))+
                '</pre><p>Extracted: '+e(row.get('extracted'))+'</p></details>')
    best = ('Highest observed complete score: ' + completed[0]['label'] + ' (' + (f'{ranking_score(completed[0])*100:.2f} / 100' if quality_only else pct(ranking_score(completed[0]))) + ').') if completed else 'No complete run yet. Incomplete runs are excluded from ranking.'
    doc = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StrataBench comparison</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#101721;color:#e2e9f2;font:15px/1.6 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:42px 28px}h1{font-size:36px;margin:0}h2{margin-top:38px;font-size:23px}p{max-width:1000px;color:#b7c5d8}.hero{padding:22px 26px;background:#19283a;border-left:4px solid #52d5bf;border-radius:10px;margin:24px 0}.hero p{margin:4px 0}.table{overflow-x:auto}table{width:100%;border-collapse:collapse;background:#16202d;font-variant-numeric:tabular-nums}th,td{padding:12px;text-align:left;border-bottom:1px solid #2c3a4c}th{color:#9bb1cd;white-space:nowrap}tbody tr:hover{background:#1f3044}.ok{color:#6ae1b3}.bad{color:#ffac8c}.badge{font-size:11px;color:#b8c3df}code,pre{background:#0b121c;border-radius:6px}code{padding:3px 6px}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px}details{border:1px solid #2c3a4c;border-radius:8px;margin:12px 0;padding:12px 18px}summary{cursor:pointer}a{color:#6edec8}button,input{font:inherit;background:#1c2e43;border:1px solid #3d5370;border-radius:6px;padding:8px 12px;color:inherit}input{width:min(700px,100%)}.muted{font-size:13px;color:#94a7c1}
</style><main><h1>StrataBench</h1><p>Output quality across Strata versions and model configurations.</p>'''
    doc += '<div class="hero"><strong>'+e(best)+'</strong><p>'+e(str(len(cases)))+' questions · '+e(manifest['options']['profile'])+' · reasoning '+e(manifest['options']['reasoning'])+' · '+e(manifest['options']['repeats'])+' repeat(s)</p></div>'
    if manifest['options'].get('standard_benchmark'):
        b=manifest['options']['standard_benchmark']
        doc+='<h2>'+e(b['name'])+' · '+e(b['selection'])+'</h2><p>'+e(b['split'])+' · '+str(b['selected_count'])+'/'+str(b['full_count'])+' cases. '+e(b['notice'])+'</p>'
        doc+='<p>Source revision: <code>'+e(b['revision'])+'</code>. Dataset revision: <code>'+e(b.get('dataset_revision') or 'same source revision')+'</code>. Original categories are preserved; no difficulty ratings are invented.</p>'
        doc+='<div class="table"><table><thead><tr><th>Combination</th><th>'+e(b['metric'])+'</th><th>Scored / planned</th><th>Judge errors</th></tr></thead><tbody>'+''.join('<tr><td>'+e(s['label'])+'</td><td>'+('—' if s['standard_metrics']['primary_value'] is None else f"{s['standard_metrics']['primary_value']:.2f}")+'</td><td>'+str(s['standard_metrics']['scored'])+'/'+str(s['standard_metrics']['planned'])+'</td><td>'+str(s['standard_metrics']['judge_errors'])+'</td></tr>' for s in summaries)+'</tbody></table></div><p><a href="standard-metrics.json">All standard metrics (JSON)</a> · <a href="standard-metrics.csv">Standard metrics (CSV)</a>. These metrics use the pinned upstream checker with the recorded StrataBench generation adapter.</p>'
    doc += '<p>Standard benchmark runs rank by their named primary metric. Diagnostic runs rank by equal weight per task group. Only complete evaluations are ranked. Small differences need more questions and repeated runs.</p>'
    if not quality_only:doc += '<h2>Comparison</h2><div class="table"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in ['Rank','Version / config','Balanced score','Accuracy','Answered','Errors','Cutoffs','Output tok/s¹','Minutes','Status'])+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    doc += '<p class="muted">¹ Completion tokens divided by total request time, including prompt processing and reasoning when the server includes it in usage. This is end-to-end throughput, not pure decode speed. Missing usage is not estimated.</p>'
    if any(s['constraint_score'] is not None or s['tool_calls'] for s in summaries):
        doc += '<h2>Capability diagnostics</h2><p>Strict correctness is separate from the proportion of writing rules satisfied and optional subjective judge ratings. Compare judge ratings only with the same judge and rubric. These original diagnostics are not official IFEval, BFCL, vision or SWE-bench scores.</p>'
        doc += '<div class="table"><table><thead><tr><th>Combination</th><th>Writing rules</th><th>Judge / 5</th><th>Judged answers</th><th>Judge errors</th><th>Tool calls</th><th>Tool errors</th></tr></thead><tbody>'+''.join('<tr><td>'+e(s['label'])+'</td><td>'+(pct(s['constraint_score']) if s['constraint_score'] is not None else '—')+'</td><td>'+(f"{s['style_judge_score']:.2f}" if s['style_judge_score'] is not None else '—')+'</td><td>'+str(s['style_judge_count'])+'</td><td>'+str(s['style_judge_errors'])+'</td><td>'+str(s['tool_calls'])+'</td><td>'+str(s['tool_errors'])+'</td></tr>' for s in summaries)+'</tbody></table></div>'
    if not quality_only:
        doc += '<h2>Difficulty</h2><div class="table"><table><thead><tr><th>Combination</th>'+''.join('<th>'+e(x)+'</th>' for x in levels)+'</tr></thead><tbody>'+''.join(level_rows)+'</tbody></table></div>'
        doc += '<h2>Task groups</h2><div class="table"><table><thead><tr><th>Combination</th>'+''.join('<th>'+e(g)+'</th>' for g in group_names)+'</tr></thead><tbody>'+''.join(group_rows)+'</tbody></table></div>'
    if not quality_only:
        doc += '<h2>Original model references</h2><p>'+e(refs['model'])+' · '+e(refs['precision_note'])+'</p><p>'+e(refs['notice'])+'</p>'
        doc += '<div class="table"><table><thead><tr><th>Dataset / group</th><th>Published original score</th><th>Weight precision</th>'+''.join('<th>Local: '+e(s['label'])+'</th>' for s in summaries)+'<th>Source and comparison limits</th></tr></thead><tbody>'+''.join(reference_table)+'</tbody></table></div>'
        doc += '<p>Checked '+e(refs['checked_on'])+'. <a href="reference-scores.csv">Download references and local scores as CSV</a>. No synthetic original-model overall score is computed.</p>'
    doc += '<h2>Paired uncertainty</h2><p>Question-level paired bootstrap, stratified by task group, with repeats kept together (1,500 resamples). This measures uncertainty on this task mix, not universal model ability. Tiny suites and all-identical outcomes can give overly narrow intervals.</p><ul>'+(''.join(pairs) or '<li>Complete at least two combinations to compare.</li>')+'</ul>'
    doc += '<h2>Inspect failures</h2><input id="filter" placeholder="Filter by version, config or task"><div id="failures">'+(''.join(details) or '<p>No saved failures.</p>')+'</div>'
    doc += '<h2>How to interpret this</h2><p>These are local zero-shot diagnostic scores. Public tasks may have appeared in model training. MATH-500 uses only numeric/rational answers and text-only questions; no official MATH-500 score is claimed. Generated difficulty labels are approximate; AIME provides competition-level problems. Algorithm tasks test reasoning about code and algorithms, not execution of generated programs. Persian arithmetic is a narrow language check. The separate capability suites measure explicit writing constraints with optional quality judging, generated visual tasks, controlled tool workflows and miniature Docker-isolated Python repairs. They do not establish broad real-world writing, vision or autonomous software-engineering ability.</p>'
    doc += '<p>Read <a href="summary.json">summary.json</a> or <a href="leaderboard.csv">leaderboard.csv</a> for machine-readable scores. Full responses, requests, settings and exact questions remain in each result folder.</p>'
    doc += '<details><summary>Run settings</summary><pre>'+e(json.dumps(manifest['options'], indent=2))+'</pre></details>'
    doc += '<script>document.querySelector("#filter").addEventListener("input",e=>{const q=e.target.value.toLowerCase();document.querySelectorAll("#failures details").forEach(d=>d.hidden=!d.textContent.toLowerCase().includes(q))});</script></main></html>'
    (folder / 'report.html').write_text(doc, encoding='utf-8')
    lines = ['StrataBench — '+best, '', 'Balanced score | Accuracy | Answers | Combination']
    lines += [f'{pct(s["macro_accuracy"]):>6} | {pct(s["accuracy"]):>6} | {s["answered"]}/{s["planned"]} | {s["label"]}' + ('' if s['complete'] else ' [incomplete]') for s in summaries]
    lines += ['', 'Original-model references (context only; different evaluation protocols):']
    lines += [f'{r["group"]}: {r["score_percent"]:.2f}% ({r["weight_precision"]}); {r["source"]}' if r['available'] else r['group']+': not available — '+r['reason'] for r in refs['rows']]
    (folder / 'report.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary
