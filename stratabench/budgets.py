"""Thinking caps, total generation limits, and declared-context planning checks."""
from __future__ import annotations

import re

OUTPUT_DEFAULTS={'easy':2048,'medium':4096,'hard':8192,'very_hard':12288,'extreme':16384,'unrated':8192}
ANSWER_RESERVE=1024
PROMPT_RESERVE=1024
MAX_THINKING=1_000_000
AGENT_PROFILES=('tools','coding','swebench')


def default_output(level,profile=None):
    value=OUTPUT_DEFAULTS[level]
    return min(value,4096) if profile in AGENT_PROFILES else value


def defaults(profile=None,max_tokens=None):
    values={}
    for level in OUTPUT_DEFAULTS:
        total=int(max_tokens) if max_tokens not in (None,'','auto') else default_output(level,profile)
        reserve=min(ANSWER_RESERVE,max(1,total//2))
        values[level]=max(1,min(default_output(level,profile)-ANSWER_RESERVE,total-reserve))
    return values


def normalize(values,profile=None,max_tokens=None):
    if not isinstance(values,dict) or any(key not in OUTPUT_DEFAULTS for key in values):
        raise ValueError('Thinking budgets must map difficulty levels to whole token counts.')
    result=defaults(profile,max_tokens)
    for level,value in values.items():
        if isinstance(value,str) and re.fullmatch(r'[0-9]+',value):value=int(value)
        if type(value) is not int or not 1<=value<=MAX_THINKING:
            raise ValueError(f'The {level.replace("_"," ")} thinking budget must be a whole number from 1 to {MAX_THINKING:,}.')
        result[level]=value
    return result


def options_from_form(data):
    use_defaults=data.get('use_default_thinking_budgets',True)
    if type(use_defaults) is not bool:raise ValueError('Choose default or custom thinking budgets.')
    profile=data.get('profile','quick');maximum=data.get('max_tokens')
    if maximum not in (None,'','auto'):
        if isinstance(maximum,bool) or not re.fullmatch(r'[0-9]+',str(maximum)) or not 1<=int(maximum)<=262144:raise ValueError('The overall answer token limit must be a whole number from 1 to 262,144.')
        maximum=int(maximum)
    else:maximum=None
    values=defaults(profile,maximum) if use_defaults else normalize(data.get('thinking_budgets'),profile,maximum)
    return {'profile':profile,'reasoning':data.get('reasoning','xhigh'),'max_tokens':maximum,
        'thinking_budgets_default':use_defaults,'thinking_budgets':values}


def thinking_limit(options,level):
    if options.get('reasoning')=='off':return 0
    values=options.get('thinking_budgets')
    return values[level] if values is not None else None


def output_limit(options,level):
    if options.get('max_tokens') not in (None,'','auto'):return int(options['max_tokens'])
    if options.get('thinking_budgets') is not None and not options.get('thinking_budgets_default',False) and options.get('reasoning')!='off':
        return options['thinking_budgets'][level]+ANSWER_RESERVE
    # Saved pre-budget runs and the default UI keep their original output limits.
    return default_output(level,options.get('profile'))


def validate(options,levels):
    for level in levels:
        thought=thinking_limit(options,level)
        if thought and thought>=output_limit(options,level):
            raise ValueError(f'The {level.replace("_"," ")} thinking budget must be below the overall answer token limit. Increase that limit or reduce this thinking budget.')


def context_limit(config):
    args=config.get('args',[]);value=None
    for index,arg in enumerate(args):
        if arg=='--max-context' and index+1<len(args):value=args[index+1]
        elif isinstance(arg,str) and arg.startswith('--max-context='):value=arg.split('=',1)[1]
    if value is None:value=config.get('budget_context_limit') or config.get('context')
    try:
        parsed=int(value)
        return parsed if parsed>0 else None
    except (TypeError,ValueError,OverflowError):return None


def compatibility(configs,options,levels):
    levels=list(dict.fromkeys(levels));validate(options,levels)
    output={level:output_limit(options,level) for level in levels}
    required={level:value+PROMPT_RESERVE for level,value in output.items()}
    invalid=[];unknown=[]
    for config in configs:
        limit=context_limit(config);entry={'id':config.get('id') or config.get('path'),
            'name':config.get('name','Model config'),'context_limit':limit}
        if limit is None:unknown.append(entry);continue
        exceeded=[level for level,value in required.items() if value>limit]
        if exceeded:invalid.append({**entry,'levels':exceeded,'required_tokens':max(required[level] for level in exceeded)})
    return {'invalid':invalid,'unknown':unknown,'levels':levels,'required_tokens':required,
        'thinking_budgets':options.get('thinking_budgets'),'output_budgets':output,
        'answer_reserve_tokens':ANSWER_RESERVE,'prompt_reserve_tokens':PROMPT_RESERVE,
        'notice':'Checks use declared context windows and reserve 1,024 tokens for the prompt. Long prompts, images and multi-turn histories can need more; Strata checks the actual request at runtime.'}
