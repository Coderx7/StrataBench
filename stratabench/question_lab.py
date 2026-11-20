"""Select intact benchmark questions and save separate, reproducible prompt experiments."""
import copy
from pathlib import Path
import re
import uuid

from . import datasets, prompts
from .common import digest, read_json, write_json


def selection_path(root, id_):
    if not isinstance(id_,str) or not re.fullmatch(r'[a-f0-9]{32}',id_):raise ValueError('Choose a saved question selection.')
    base=(Path(root)/'user-tasks').resolve();path=(base/(id_+'.selection.json')).resolve()
    if not path.is_relative_to(base):raise ValueError('Invalid question selection path.')
    return path


def load_selection(path, profile, seed):
    data=read_json(path)
    if data.get('schema')!=1 or data.get('profile')!=profile or data.get('seed')!=seed:
        raise ValueError('The question selection belongs to a different benchmark or seed. Open Question lab again.')
    if not data.get('cases') or data.get('sha256')!=digest(data['cases']):raise ValueError('The saved question selection changed or is empty.')
    return data


class Library:
    def __init__(self,root):self.root=Path(root);self.catalogs={}

    def browse(self,data):
        token=data.get('catalog')
        if token:
            if token not in self.catalogs:raise ValueError('This question catalog expired. Reload it in Question lab.')
            catalog=self.catalogs[token]
        else:
            profile=data.get('profile','quick')
            if profile not in datasets.PROFILES:raise ValueError('Choose a benchmark.')
            seed=data.get('seed',20261119)
            if type(seed) is not int or not 1<=seed<=2147483547:raise ValueError('Choose a valid seed.')
            cases=datasets.select(profile,seed,standard_limit=0)
            token=uuid.uuid4().hex;catalog={'profile':profile,'seed':seed,'cases':cases}
            self.catalogs[token]=catalog
            while len(self.catalogs)>4:self.catalogs.pop(next(iter(self.catalogs)))
        cases=catalog['cases']
        if data.get('case_id') is not None:
            case=next((c for c in cases if c['id']==data['case_id']),None)
            if case is None:raise ValueError('Choose a question from this catalog.')
            return {'id':case['id'],'prompt':case['prompt'],'answer':case.get('answer'),
                'system_prompt':prompts.system_text(case),'group':case['group'],'difficulty':case['difficulty'],
                'images':case.get('images') or ([case['image']] if case.get('image') else [])}
        query=str(data.get('search','')).strip().casefold()[:300]
        filtered=[c for c in cases if (not query or query in (c['id']+' '+c['prompt']).casefold())
                  and (not data.get('group') or c['group']==data['group'])
                  and (not data.get('difficulty') or c['difficulty']==data['difficulty'])]
        offset=data.get('offset',0)
        if type(offset) is not int or offset<0:raise ValueError('Invalid question page.')
        return {'catalog':token,'profile':catalog['profile'],'total':len(cases),'matched':len(filtered),
            'groups':sorted({c['group'] for c in cases}),'offset':offset,'limit':25,
            'questions':[{'id':c['id'],'preview':c['prompt'][:180],'group':c['group'],'difficulty':c['difficulty']}
                         for c in filtered[offset:offset+25]]}

    def save(self,data):
        catalog=self.catalogs.get(data.get('catalog'))
        if not catalog:raise ValueError('Reload the questions before saving this selection.')
        items=data.get('questions')
        if not isinstance(items,list) or not items or len(items)>10000:raise ValueError('Select between 1 and 10,000 questions.')
        known={c['id']:c for c in catalog['cases']};cases=[];seen=set()
        for item in items:
            if not isinstance(item,dict) or not isinstance(item.get('id'),str) or item['id'] not in known or item['id'] in seen:
                raise ValueError('Choose unique questions from this catalog.')
            case=copy.deepcopy(known[item['id']]);seen.add(item['id'])
            if 'system_override' in item:
                value=item['system_override']
                if not isinstance(value,str) or len(value)>50000:raise ValueError('System prompts must be text of at most 50,000 characters.')
                case['system_override']=value
            cases.append(case)
        id_=uuid.uuid4().hex
        saved={'schema':1,'profile':catalog['profile'],'seed':catalog['seed'],'cases':cases,'sha256':digest(cases)}
        write_json(selection_path(self.root,id_),saved)
        return {'id':id_,'count':len(cases),'profile':catalog['profile'],
                'counts':{level:sum(c['difficulty']==level for c in cases) for level in {c['difficulty'] for c in cases}},
                'edited':sum('system_override' in c for c in cases)}
