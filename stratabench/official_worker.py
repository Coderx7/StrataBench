"""Runs only inside a suite's private Python environment."""
from __future__ import annotations

import ast
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import sys
import types

# Running this file by absolute path must not shadow Hugging Face's datasets
# package with the app's datasets.py module.
sys.path[:]=[p for p in sys.path if Path(p or '.').resolve()!=Path(__file__).resolve().parent]


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
def lines(path):return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]


def case(suite,id_,prompt,answer,**extra):
    return dict(id=suite+'/'+str(id_),group=suite,difficulty='unrated',prompt=prompt,answer=answer,
        grader='upstream',standard_suite=suite,protocol='standard',system=None,**extra)


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def prepare(suite,root,spec):
    src=root/'source';cases=[]
    if suite=='ifeval':
        import nltk
        nltk.download('punkt_tab',download_dir=str(root/'nltk_data'),raise_on_error=True)
        for item in lines(src/'instruction_following_eval/data/input_data.jsonl'):
            cases.append(case(suite,item['key'],item['prompt'],'All supplied instructions followed',upstream=item))
    elif suite=='bfcl':
        base=src/'berkeley-function-call-leaderboard/bfcl_eval/data'
        for category in ('simple_python','multiple','parallel','parallel_multiple'):
            answers={d['id']:d for d in lines(base/'possible_answer'/('BFCL_v4_'+category+'.json'))}
            for item in lines(base/('BFCL_v4_'+category+'.json')):
                if item['id'] not in answers:raise ValueError('BFCL answer missing: '+item['id'])
                cases.append({**case(suite,item['id'],'\n'.join(m['content'] for m in item['question'][0]),answers[item['id']]['ground_truth'],
                    upstream=item,category=category,messages=item['question'][0]),'group':'bfcl_'+category})
    elif suite=='writingbench':
        for item in lines(src/'benchmark_query/benchmark_all.jsonl'):
            if not item.get('checklist'):raise ValueError('WritingBench question has no scoring rubric.')
            cases.append({**case(suite,item['index'],item['query'],'Per-question rubric (1–10 per criterion)',upstream=item),
                'group':'writingbench_'+item.get('domain1','writing'),'score_only':True})
    elif suite=='mmmu':
        from datasets import load_dataset, get_dataset_config_names
        from PIL import Image
        names=get_dataset_config_names(spec['dataset'],revision=spec['dataset_revision'])
        for subject in names:
            print('Downloading MMMU validation: '+subject,flush=True)
            rows=load_dataset(spec['dataset'],subject,split='validation',revision=spec['dataset_revision'],streaming=True)
            for item in rows:
                options=ast.literal_eval(item['options']) if isinstance(item['options'],str) else item['options']
                prompt=item['question'];images=[]
                for index in range(1,8):
                    image=item.get('image_'+str(index))
                    if image is not None:
                        if isinstance(image,dict):image=Image.open(io.BytesIO(image['bytes']))
                        data=io.BytesIO();image.convert('RGB').save(data,format='PNG')
                        images.append('data:image/png;base64,'+base64.b64encode(data.getvalue()).decode())
                choices={chr(65+i):text for i,text in enumerate(options)}
                if item['question_type']=='multiple-choice':
                    prompt+='\n'+'\n'.join(f'({k}) {v}' for k,v in choices.items())+'\nAnswer with the option letter.'
                else:prompt+='\nAnswer with the short answer.'
                cases.append({**case(suite,item['id'],prompt,item['answer'],images=images,requires_vision=True,
                    choices=choices,question_type=item['question_type'],upstream_difficulty=item.get('topic_difficulty')),'group':'mmmu_'+subject})
    elif suite=='swebench':
        from datasets import load_dataset
        for item in load_dataset(spec['dataset'],split='test',revision=spec['dataset_revision']):
            cases.append(case(suite,item['instance_id'],item['problem_statement'],'Issue resolved by official acceptance tests',upstream=dict(item)))
    if not cases or len({c['id'] for c in cases})!=len(cases):raise ValueError('Invalid or empty benchmark data.')
    if len(cases)!=spec['count']:raise ValueError(f'Unexpected benchmark size: {len(cases)}; expected {spec["count"]}.')
    write(root/'cases.json',cases)
    return {'count':len(cases)}


def grade_ifeval(root,data):
    sys.path.insert(0,str(root/'source'))
    from instruction_following_eval import evaluation_lib as lib
    c=data['case'];item=c['upstream'];response=data['content']
    inp=lib.InputExample(key=item['key'],instruction_id_list=item['instruction_id_list'],prompt=item['prompt'],kwargs=item['kwargs'])
    strict=lib.test_instruction_following_strict(inp,{item['prompt']:response})
    loose=lib.test_instruction_following_loose(inp,{item['prompt']:response})
    return {'correct':bool(strict.follow_all_instructions),'extracted':response,
        'metrics':{'prompt_strict':int(strict.follow_all_instructions),'prompt_loose':int(loose.follow_all_instructions),
            'instruction_strict':sum(strict.follow_instruction_list)/len(strict.follow_instruction_list),
            'instruction_loose':sum(loose.follow_instruction_list)/len(loose.follow_instruction_list)},
        'instruction_strict_checks':strict.follow_instruction_list,'instruction_loose_checks':loose.follow_instruction_list,
        'instruction_ids':item['instruction_id_list']}


def grade_bfcl(root,data):
    sys.path.insert(0,str(root/'source/berkeley-function-call-leaderboard'))
    # The official checker reads only underscore_to_dot from model configuration.
    # Supply our adapter's config without importing unrelated inference backends.
    config=types.ModuleType('bfcl_eval.constants.model_config')
    config.MODEL_CONFIG_MAPPING={'stratabench':types.SimpleNamespace(underscore_to_dot=False)}
    sys.modules[config.__name__]=config
    from bfcl_eval.constants.enums import Language
    from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker
    c=data['case'];pred=data['calls']
    result=ast_checker(c['upstream']['function'],pred,c['answer'],Language.PYTHON,c['category'],'stratabench')
    return {'correct':bool(result['valid']),'extracted':pred,'metrics':{'ast_accuracy':int(result['valid'])},'checker':result}


def grade_mmmu(root,data):
    lib=module('mmmu_eval',root/'source/mmmu/utils/eval_utils.py')
    c=data['case'];random.seed(data.get('seed',42))
    if c['question_type']=='multiple-choice':
        pred=lib.parse_multi_choice_response(data['content'],list(c['choices']),c['choices'])
        correct=lib.eval_multi_choice(c['answer'],pred)
    else:
        pred=lib.parse_open_response(data['content']);correct=lib.eval_open(c['answer'],pred)
    return {'correct':bool(correct),'extracted':pred,'metrics':{'accuracy':int(correct)}}


def main(suite,op,root,data):
    if op=='prepare':return prepare(suite,root,data['spec'])
    if op=='grade':return {'ifeval':grade_ifeval,'bfcl':grade_bfcl,'mmmu':grade_mmmu}[suite](root,data)
    if suite=='writingbench' and op=='judge_prompts':
        prompt=module('writingbench_prompts',root/'source/prompt.py')
        return {'system':prompt.evaluate_system,'prompts':[{'name':c['name'],'prompt':prompt.evaluate_prompt.format(
            query=data['case']['prompt'],response=data['content'],criteria=c)} for c in data['case']['upstream']['checklist']]}
    if suite=='swebench':
        runtime=module('swe_runtime',Path(__file__).with_name('swe_runtime.py'))
        return runtime.operation(op,root,data)
    raise ValueError('Unsupported evaluator operation.')


if __name__=='__main__':
    suite,op,root,inp,out=sys.argv[1:]
    with contextlib.redirect_stdout(sys.stderr):result=main(suite,op,Path(root),read(inp))
    write(out,result)
