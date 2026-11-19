"""Original, deterministic capability diagnostics; not official leaderboard replicas."""
from __future__ import annotations

import base64
import json
import random
import re
import struct
import zlib

LEVELS = ('easy','medium','hard','very_hard','extreme')
STYLE_SYSTEM = 'Follow the writing brief precisely. Return only the requested writing, without meta-commentary or a JSON wrapper.'


def item(id_, group, difficulty, prompt, answer, grader='numeric', **extra):
    return dict(id=id_,group=group,difficulty=difficulty,prompt=prompt,answer=answer,grader=grader,**extra)


def writing_cases(seed):
    cases=[]
    for level,difficulty in enumerate(LEVELS):
        lower,upper=40+level*25,80+level*30
        briefs=[('professional','Write a professional project update for colleagues. Start with the exact title "Project update" on its own line. Use exactly 3 bullet points beginning "- ". Include the phrases "deadline" and "next step". Avoid the words "awesome", "obviously", and "leverage".',
                 {'title':'Project update','bullets':3,'required':['deadline','next step'],'forbidden':['awesome','obviously','leverage']}),
            ('friendly','Write a friendly apology to a customer about a delayed delivery. Include "sorry" and "thank you". Do not use "your fault", "obviously", "guarantee", or "unfortunately".',
                 {'required':['sorry','thank you'],'forbidden':['your fault','obviously','guarantee','unfortunately']}),
            ('instructions',f'Write clear instructions for preparing a shared meeting room. Start with the exact title "Quick start" on its own line. Use exactly {3+level} numbered steps, starting at 1 with the format "1. ". Do not use "simply", "just", or "leverage".',
                 {'title':'Quick start','numbered':3+level,'required':[],'forbidden':['simply','just','leverage']}),
            ('neutral','Rewrite this complaint in a neutral, evidence-focused style: "This terrible product always fails and the team never listens." Include "observed" and "improve". Do not use "terrible", "always", "never", or "incompetent".',
                 {'required':['observed','improve'],'forbidden':['terrible','always','never','incompetent']})]
        for kind,brief,rules in briefs:
            rules.update(min_words=lower,max_words=upper,forbidden_extra=['as an ai','as a language model'])
            if level>=2:rules['max_sentence_words']=35-level*2
            if level>=3:rules['required'] += ['available evidence']
            if level==4:rules['paragraphs_min']=2
            prompt=brief+f' Use {lower}–{upper} words, counting the title and list markers as words.'
            if 'max_sentence_words' in rules:prompt+=f' Keep every sentence to at most {rules["max_sentence_words"]} words.'
            if level>=3:prompt+=' Include the exact phrase "available evidence".'
            if level==4:prompt+=' Separate the writing into at least 2 blocks using a blank line.'
            cases.append(item(f'writing/{kind}/{difficulty}','writing_'+kind,difficulty,prompt,'All writing constraints satisfied','writing',
                protocol='writing',rules=rules,system=STYLE_SYSTEM,source='StrataBench original writing diagnostic'))
    return cases


def writing_grade(content,finish_reason,rules):
    text=re.sub(r'<think>.*?</think>','',content or '',flags=re.S).strip()
    if '<think>' in text:text=''
    try:
        obj=json.loads(text)
        if isinstance(obj,dict) and isinstance(obj.get('answer'),str):text=obj['answer']
    except (ValueError,TypeError):pass
    words=text.split();lines=text.splitlines();folded=text.casefold()
    checks=[{'rule':'word_count','passed':rules['min_words']<=len(words)<=rules['max_words'],'actual':len(words),
             'expected':f'{rules["min_words"]}–{rules["max_words"]}'}]
    if rules.get('title'):checks.append({'rule':'title','passed':bool(lines) and lines[0].strip()==rules['title']})
    if 'bullets' in rules:checks.append({'rule':'bullet_count','passed':len(re.findall(r'^- ',text,re.M))==rules['bullets']})
    if 'numbered' in rules:
        numbers=[int(x) for x in re.findall(r'^(\d+)\. ',text,re.M)]
        checks.append({'rule':'numbered_steps','passed':numbers==list(range(1,rules['numbered']+1))})
    for phrase in rules.get('required',[]):checks.append({'rule':'include: '+phrase,'passed':phrase.casefold() in folded})
    for phrase in rules.get('forbidden',[])+rules.get('forbidden_extra',[]):
        checks.append({'rule':'avoid: '+phrase,'passed':not re.search(r'(?<!\w)'+re.escape(phrase)+r'(?!\w)',folded)})
    if rules.get('max_sentence_words'):
        sentences=re.split(r'[.!?]+(?:\s+|$)',text)
        checks.append({'rule':'sentence_length','passed':max((len(s.split()) for s in sentences),default=0)<=rules['max_sentence_words']})
    if rules.get('paragraphs_min'):checks.append({'rule':'text_blocks','passed':len(re.split(r'\n\s*\n',text))>=rules['paragraphs_min']})
    truncated=finish_reason in ('length','max_tokens','max_output_tokens')
    return {'correct':bool(text) and all(c['passed'] for c in checks) and not truncated,'extracted':text,
        'unparsed':not bool(text),'truncated':truncated,'json_format':False,
        'constraint_score':sum(c['passed'] for c in checks)/len(checks),'constraint_checks':checks}


def png(width,height,pixels):
    def chunk(tag,data):return struct.pack('!I',len(data))+tag+data+struct.pack('!I',zlib.crc32(tag+data)&0xffffffff)
    rows=b''.join(b'\0'+bytes(pixels[y*width*3:(y+1)*width*3]) for y in range(height))
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(data).decode('ascii')


def vision_cases(seed):
    rng=random.Random(seed);cases=[];width,height=360,280
    colors={'red':(213,45,55),'blue':(30,94,210),'green':(36,151,80),'yellow':(235,193,28)}
    for level,difficulty in enumerate(LEVELS):
        for kind in ('count','spatial','chart','grid'):
            pixels=bytearray([250]*(width*height*3))
            def rect(x,y,w,h,color):
                for yy in range(max(0,y),min(height,y+h)):
                    for xx in range(max(0,x),min(width,x+w)):
                        i=(yy*width+xx)*3;pixels[i:i+3]=bytes(color)
            if kind=='count':
                count=3+level*3;labels=[rng.choice(list(colors)) for _ in range(count)]
                labels[0]='red'
                for i,color in enumerate(labels):rect(22+(i%6)*55,30+(i//6)*75,26,26,colors[color])
                answer=labels.count('red');prompt='How many red squares are in the image? Ignore squares of other colors.'
            elif kind=='spatial':
                labels=rng.sample(list(colors),4)
                for i,color in enumerate(labels):rect(75+(i%2)*140,45+(i//2)*130,65,65,colors[color])
                answer=labels[2];prompt='What color is the square in the lower-left position? Answer with one color name.'
            elif kind=='chart':
                values=rng.sample(range(2,11),4)
                for i,value in enumerate(values):rect(40+i*75,240-value*19,38,value*19,list(colors.values())[i])
                answer=values.index(max(values))+1;prompt='The image shows four vertical bars. Counting bars from the left starting at 1, which bar is tallest?'
                if level>=2:
                    sorted_indices=sorted(range(4),key=lambda i:values[i]);answer=sorted_indices[-2]+1
                    prompt='Counting bars from the left starting at 1, which bar is second-tallest?'
            else:
                size=3+level;labels=[rng.choice(['red','blue','green']) for _ in range(size*size)]
                step=min(38,230//size)
                for i,color in enumerate(labels):rect(40+(i%size)*step,20+(i//size)*step,step-6,step-6,colors[color])
                answer=sum(labels[i]=='blue' for i in range(size*size) if i//size>=size//2)
                prompt=f'The image is a {size} by {size} grid. Count the blue squares in rows {size//2+1} through {size}, numbering rows from top to bottom.'
            cases.append(item(f'vision/{kind}/{difficulty}','vision_'+kind,difficulty,prompt,answer,
                'exact' if isinstance(answer,str) else 'numeric',image=png(width,height,pixels),requires_vision=True,
                source='StrataBench original generated visual diagnostic'))
    return cases


def tool_cases(seed):
    rng=random.Random(seed);cases=[]
    for level,difficulty in enumerate(LEVELS):
        for sample in range(3):
            name=f'Customer {rng.randrange(1000,9999)}';customer=f'C{rng.randrange(10000,99999)}'
            orders=[{'id':f'O{i}','amount_cents':rng.randrange(5,40)*20,'status':'cancelled' if i%4==0 else 'paid',
                     'year':2025 if i%3==0 else 2026} for i in range(4+level*3)]
            filtered=[o for o in orders if (level<1 or o['status']=='paid') and (level<2 or o['year']==2026)]
            tax=0 if level<3 else rng.choice([5,10,15]);expected=sum(o['amount_cents'] for o in filtered)*(100+tax)//100
            prompt=f'Find the orders for {name} using the supplied tools. '
            prompt+=('Include only paid orders. ' if level>=1 else 'Include every order. ')
            if level>=2:prompt+='Include only orders from 2026. '
            if level>=3:prompt+='Look up the tax rate for region North and apply it. '
            prompt+='Use total_order_amount to calculate the final total in cents. Return the final integer in {"answer": ...}.'
            cases.append(item(f'tools/orders/{difficulty}/{sample}','tool_workflows',difficulty,prompt,expected,
                protocol='tools',tool_scenario={'name':name,'customer_id':customer,'orders':orders,'tax_percent':tax,
                    'selected_amounts':[o['amount_cents'] for o in filtered]},source='StrataBench original tool workflow'))
    return cases


def coding_cases(seed):
    # Projects include visible examples and separate hidden acceptance cases.
    specs=[('add','add(a, b)','Return the sum of two integers.','return a - b',
        [[a,b] for a,b in [(1,2),(0,0),(-4,7),(99,1),(-8,-3),(1000,-999)]],lambda a,b:a+b),
      ('even','is_even(n)','Return whether an integer is even.','return n % 2 == 1',[[n] for n in [0,1,2,-2,99,100]],lambda n:n%2==0),
      ('dedupe','dedupe(values)','Remove duplicates while preserving the first occurrence order.','return sorted(set(values))',
        [[[3,1,3,2]], [[]], [[2,2]], [[-1,0,-1]], [[4,3,2,1,4]], [[5,1,5,2,1]]],lambda values:list(dict.fromkeys(values))),
      ('median','median(values)','Return the median of a nonempty numeric list, averaging the middle pair for even length.','return sorted(values)[len(values)//2]',
        [[[1,2]], [[4]], [[3,1,2]], [[9,1,3,7]], [[-5,-1]], [[1,1,2,2,100,200]]],
        lambda values:((sorted(values)[(len(values)-1)//2]+sorted(values)[len(values)//2])/2)),
      ('intervals','merge_intervals(intervals)','Merge overlapping or touching closed intervals and return them sorted by start. Empty input returns [].','return sorted(intervals)',
        [[[[1,3],[2,4]]], [[]], [[[5,7],[1,2]]], [[[1,2],[2,3],[8,9]]], [[[1,9],[2,3]]], [[[4,5],[1,2],[2,4]]]],None),
      ('balanced','balanced(text)','Return whether parentheses, square brackets and braces are properly nested. Ignore other characters.','return text.count("(") == text.count(")")',
        [[s] for s in ['([])','([)]','','{a[b(c)]}','(()','x]']],None),
      ('knapsack','knapsack(weights, values, capacity)','Return the maximum total value using each item at most once with total weight <= capacity.','return sum(values)',
        [[[2,3],[3,4],3], [[],[],5], [[1,2,3],[2,5,6],4], [[4,5],[9,10],3], [[2,2,2],[1,7,4],4], [[1,3,4],[2,6,7],5]],None),
      ('edit_distance','edit_distance(a, b)','Return Levenshtein edit distance using insertions, deletions and substitutions of cost 1.','return abs(len(a)-len(b))',
        [[a,b] for a,b in [('cat','cut'),('','abc'),('kitten','sitting'),('same','same'),('ab','ba'),('saturday','sunday')]],None),
      ('cache','lru(capacity, operations)','Simulate an LRU cache. operations are ["put",key,value] or ["get",key]. Return get results, using -1 for misses. Gets and puts refresh recency. Capacity 0 stores nothing.','return []',
        [[2,[['put',1,10],['put',2,20],['get',1],['put',3,30],['get',2],['get',3]]], [0,[['put',1,2],['get',1]]],
         [1,[['put',1,2],['put',1,3],['get',1]]], [2,[['get',9],['put',9,4],['get',9]]]],None),
      ('weighted_schedule','weighted_schedule(jobs)','Return maximum total profit from non-overlapping jobs [start,end,profit]. A job ending at t can precede one starting at t. Empty input returns 0.','return sum(j[2] for j in jobs)',
        [[[[1,3,5],[2,5,6],[3,6,5]]], [[]], [[[1,2,3],[2,3,4],[1,3,9]]], [[[0,5,10],[1,2,4],[2,3,4],[3,4,4]]]],None)]
    def reference(name,args):
        if name=='intervals':
            out=[]
            for start,end in sorted(args[0]):
                if out and start<=out[-1][1]:out[-1][1]=max(end,out[-1][1])
                else:out.append([start,end])
            return out
        if name=='balanced':
            stack=[]
            for c in args[0]:
                if c in '([{':stack.append(c)
                elif c in ')]}':
                    if not stack or stack.pop()!='([{'[')]}'.index(c)]:return False
            return not stack
        if name=='knapsack':
            weights,values,capacity=args;dp=[0]*(capacity+1)
            for weight,value in zip(weights,values):
                for c in range(capacity,weight-1,-1):dp[c]=max(dp[c],dp[c-weight]+value)
            return dp[-1]
        if name=='edit_distance':
            a,b=args;row=list(range(len(b)+1))
            for i,x in enumerate(a,1):
                nxt=[i]
                for j,y in enumerate(b,1):nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
                row=nxt
            return row[-1]
        if name=='cache':
            from collections import OrderedDict
            capacity,operations=args;cache=OrderedDict();out=[]
            for op in operations:
                if op[0]=='get':
                    out.append(cache.get(op[1],-1))
                    if op[1] in cache:cache.move_to_end(op[1])
                elif capacity:
                    cache[op[1]]=op[2];cache.move_to_end(op[1])
                    if len(cache)>capacity:cache.popitem(last=False)
            return out
        jobs=sorted(args[0],key=lambda j:j[1]);dp=[0]
        for i,(start,end,profit) in enumerate(jobs):
            compatible=max((j+1 for j in range(i) if jobs[j][1]<=start),default=0)
            dp.append(max(dp[-1],dp[compatible]+profit))
        return dp[-1]
    cases=[];rng=random.Random(seed)
    for index,(name,signature,brief,bug,inputs,oracle) in enumerate(specs):
        inputs=list(inputs)
        for _ in range(12):
            if name=='add':args=[rng.randint(-1000,1000),rng.randint(-1000,1000)]
            elif name=='even':args=[rng.randint(-1000,1000)]
            elif name in ('dedupe','median'):args=[[rng.randint(-9,9) for _ in range(rng.randint(1,12))]]
            elif name=='intervals':args=[[[v,v+rng.randint(1,5)] for v in [rng.randint(0,15) for _ in range(6)]]]
            elif name=='balanced':args=[''.join(rng.choice('()[]{}abc') for _ in range(10))]
            elif name=='knapsack':args=[[rng.randint(1,7) for _ in range(6)],[rng.randint(0,20) for _ in range(6)],rng.randint(0,15)]
            elif name=='edit_distance':args=[''.join(rng.choice('abc') for _ in range(rng.randrange(8))) for _ in range(2)]
            elif name=='cache':args=[rng.randrange(4),[(['put',rng.randrange(4),rng.randrange(20)] if rng.random()<.6 else ['get',rng.randrange(4)]) for _ in range(12)]]
            else:args=[[[v,v+rng.randint(1,5),rng.randint(1,20)] for v in [rng.randint(0,15) for _ in range(7)]]]
            inputs.append(args)
        tests=[{'args':args,'expected':oracle(*args) if oracle else reference(name,args)} for args in inputs]
        function=signature.split('(')[0];public=tests[:2];difficulty=LEVELS[index//2]
        files={'solution.py':f'def {signature}:\n    {bug}\n','README.md':brief,
               'tests/test_public.json':json.dumps(public,indent=2)}
        cases.append(item(f'coding/{name}','agentic_coding',difficulty,
            'Fix the Python project using the file tools. '+brief+' Read the files, edit solution.py, and run the public tests. '
            'Only solution.py can be edited. Finish after testing; separate hidden tests determine correctness.',
            'All hidden acceptance tests pass','agentic',protocol='coding',coding={'files':files,'function':function,'public_tests':public,'hidden_tests':tests[2:]},
            source='StrataBench original miniature coding project'))
    return cases


def select(profile,seed):
    return {'writing':writing_cases,'vision':vision_cases,'tools':tool_cases,'coding':coding_cases}[profile](seed)
