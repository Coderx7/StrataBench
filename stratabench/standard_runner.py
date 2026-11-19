"""Generation adapters and upstream metric records for standard suites."""
from __future__ import annotations

import copy
import http.client
import json
import os
import time

from . import standard_suites as suites


def json_schema(schema):
    if isinstance(schema,list):return [json_schema(s) for s in schema]
    if not isinstance(schema,dict):return schema
    out={k:json_schema(v) for k,v in schema.items()}
    if out.get('type') in ('dict','tuple','float','any'):
        mapped={'dict':'object','tuple':'array','float':'number','any':None}[out['type']]
        if mapped:out['type']=mapped
        else:out.pop('type')
    return out


def bfcl_request(case,body):
    body=copy.deepcopy(body)
    body['messages']=copy.deepcopy(case['messages'])
    functions=case['upstream']['function'];names={f['name'].replace('.','_'):f['name'] for f in functions}
    if len(names)!=len(functions):raise ValueError('Function names collide after API normalization.')
    body['tools']=[{'type':'function','function':{**json_schema(f),'name':f['name'].replace('.','_')}} for f in functions]
    body['tool_choice']='auto'
    return body,names


def evaluate(case,body,endpoint,options,api_key=None,saved=None,run_id=None):
    from .runner import completion
    suite=case['standard_suite'];started=time.monotonic();names={}
    if suite=='swebench':return run_swe(case,body,endpoint,options,api_key,run_id)
    if suite=='bfcl':body,names=bfcl_request(case,body)
    result=copy.deepcopy(saved) if saved else completion(endpoint,body,options['timeout'],api_key)
    result.update(request=body,unparsed=False,json_format=False,truncated=result.get('finish_reason') in ('length','max_tokens','max_output_tokens'))
    if suite=='writingbench' and result['truncated']:
        grade={'correct':None,'score':None,'metrics':{},'cutoff':True}
    elif suite=='writingbench':
        grade=judge_writingbench(case,result['content'],options)
    else:
        data={'case':{k:v for k,v in case.items() if k!='images'},'content':result['content'],'seed':options['seed']}
        if suite=='bfcl':
            calls=result['response']['choices'][0]['message'].get('tool_calls') or [];decoded=[]
            try:
                for call in calls:
                    f=call['function'];args=json.loads(f['arguments'])
                    if f['name'] not in names or not isinstance(args,dict):raise ValueError('Invalid function call.')
                    decoded.append({names[f['name']]:args})
            except (ValueError,TypeError,KeyError):decoded=[];result['unparsed']=True
            data['calls']=decoded;result['tool_calls']=len(calls)
        grade=suites.worker(suite,'grade',data)
        grade['score']=int(grade['correct'])
    result['correct']=grade.get('correct')
    result['extracted']=grade.get('extracted',result['content'])
    if result['truncated']:
        result['correct']=None if case.get('score_only') else False
        grade.update(score=None if case.get('score_only') else 0,cutoff=True)
        grade['metrics']={key:0 for key in grade.get('metrics',{})}
        for key in ('instruction_strict_checks','instruction_loose_checks'):
            if key in grade:grade[key]=[False]*len(grade[key])
    result['standard_result']={'suite':suite,**grade}
    if saved:result['judge_retry_seconds']=time.monotonic()-started
    else:result['elapsed_seconds']=time.monotonic()-started
    return result


def judge_writingbench(case,content,options):
    from .runner import completion
    marker='</think>\n\n'
    if marker in content:content=content[content.find(marker)+len(marker):]
    prompts=suites.worker('writingbench','judge_prompts',{'case':case,'content':content})
    ratings=[];started=time.monotonic()
    try:
        for item in prompts['prompts']:
            body={'model':options['style_judge_model'],'temperature':1.0,'top_p':0.95,'max_tokens':2048,'stream':False,
                'messages':[{'role':'system','content':prompts['system']},{'role':'user','content':item['prompt']}]}
            answer=completion(options['style_judge_endpoint'],body,min(options['timeout'],300),os.environ.get('STRATABENCH_JUDGE_API_KEY'))
            text=answer['content'].strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
            value=json.loads(text)
            if type(value.get('score')) is not int or not 1<=value['score']<=10 or not isinstance(value.get('reason'),str):raise ValueError('WritingBench judge must return a score from 1 to 10 and a reason.')
            if answer.get('finish_reason') in ('length','max_tokens','max_output_tokens'):raise ValueError('WritingBench judge response was cut off.')
            ratings.append({'criterion':item['name'],**value,'response':answer['response']})
        score=sum(r['score'] for r in ratings)/len(ratings)
        return {'correct':None,'score':score/10,'metrics':{'rubric_score_100':score*10},'ratings':ratings,
            'judge':{'model':options['style_judge_model'],'endpoint':options['style_judge_endpoint']},'judge_seconds':time.monotonic()-started}
    except (OSError,ValueError,KeyError,TypeError,http.client.HTTPException) as error:
        return {'correct':None,'score':None,'metrics':{},'ratings':ratings,'judge_error':str(error),
            'judge':{'model':options['style_judge_model'],'endpoint':options['style_judge_endpoint']},'judge_seconds':time.monotonic()-started}


def run_swe(case,body,endpoint,options,api_key=None,run_id=None):
    from .runner import completion
    from .capability_runner import tool
    image=options['swe_images'][case['id']];session=suites.worker('swebench','open',{'image':image,'run_id':run_id});name=session['container']
    started=time.monotonic();trace=[];usage={};last={};body=copy.deepcopy(body)
    body['messages']=[{'role':'system','content':'You fix software issues in a Linux repository at /testbed. Use the terminal tool to inspect files, edit the code, and run tests. Changes stay inside this task container. Do not modify tests to hide failures. Finish with a short summary after implementing the fix.'},
        {'role':'user','content':case['prompt']}]
    body['tools']=[tool('terminal','Run a bash command in the isolated repository container. No network or host folders are available.',{'command':{'type':'string'}},['command'])]
    body['tool_choice']='auto'
    if options.get('max_tokens') is None:body['max_tokens']=4096
    first=copy.deepcopy(body)
    try:
        for turn in range(options.get('agent_turns',30)):
            last=completion(endpoint,body,options['timeout'],api_key)
            for k,v in last.get('usage',{}).items():
                if type(v) in (int,float):usage[k]=usage.get(k,0)+v
            message=last['response']['choices'][0].get('message') or {};calls=message.get('tool_calls') or []
            trace.append({'turn':turn+1,'role':'assistant','content':last['content'],'tool_calls':calls})
            if not calls or last['finish_reason'] in ('length','max_tokens','max_output_tokens'):break
            if not isinstance(calls,list) or len(calls)>8:raise ValueError('Invalid or excessive terminal tool calls.')
            assistant={'role':'assistant','content':message.get('content') or '', 'tool_calls':calls}
            if message.get('reasoning_content'):assistant['reasoning_content']=message['reasoning_content']
            body['messages'].append(assistant)
            for call in calls:
                try:
                    args=json.loads(call['function']['arguments'])
                    if call['function']['name']!='terminal' or set(args)!= {'command'}:raise ValueError('Expected the terminal tool and a command.')
                    result=suites.worker('swebench','command',{'container':name,'command':args['command']},timeout=150)
                except (ValueError,KeyError,TypeError) as error:result={'error':str(error)}
                trace.append({'turn':turn+1,'role':'tool','name':'terminal','result':result})
                body['messages'].append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result)})
        patch=suites.worker('swebench','patch',{'container':name})['patch']
    finally:suites.worker('swebench','close',{'container':name})
    grade=suites.worker('swebench','evaluate',{'case':case,'patch':patch,'image':image,'run_id':run_id,'test_timeout':options.get('swe_test_timeout',900)},timeout=options.get('swe_test_timeout',900)+90)
    truncated=last.get('finish_reason') in ('length','max_tokens','max_output_tokens')
    correct=bool(grade.get('resolved')) and not truncated
    return {**last,'correct':correct,'truncated':truncated,'unparsed':False,'json_format':False,'extracted':patch,
        'elapsed_seconds':time.monotonic()-started,'request':first,'usage':usage,'agent_trace':trace,
        'agent_turns':sum(t['role']=='assistant' for t in trace),'tool_calls':sum(t['role']=='tool' for t in trace),
        'standard_result':{'suite':'swebench','correct':correct,'score':int(correct),'metrics':{'resolved':int(correct)},
            'evaluation':grade,'patch':patch,'image_id':image,'agent':'stratabench-terminal-v1'}}
