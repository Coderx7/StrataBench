"""Question selection, effective prompts and read-only format explanations."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from stratabench import datasets, format_analysis, prompts, question_lab, runner, standard_runner
from stratabench.common import read_json, write_json


class FormatAnalysisTests(unittest.TestCase):
    def test_word_sorting_array_is_explained_without_changing_grade(self):
        from stratabench.grading import grade
        words='blackstone feed figural giveth hecatomb hunt incense middle obstinacy pasty pestle plume sinkhole spavin statutory tel toothpaste undulate'
        case=datasets.case('bbh/word_sorting/61','bbh_word_sorting','hard','Sort these words.',words,'exact')
        content=json.dumps({'answer':words.split()})
        strict=grade(case,content);self.assertFalse(strict['correct'])
        row={**strict,'content':content};before=copy.deepcopy(row)
        explanation=format_analysis.inspect(case,row)
        self.assertEqual(explanation['normalized'],words)
        self.assertIn('JSON array',explanation['reason']);self.assertEqual(row,before)
        for altered in (words.split()[::-1],words.split()[:-1],words.split()+['extra']):
            self.assertIsNone(format_analysis.inspect(case,{'correct':False,'content':json.dumps({'answer':altered})}))

    def test_cutoffs_errors_thinking_and_arbitrary_prose_do_not_become_format_only(self):
        case=datasets.case('word','bbh_word_sorting','hard','Sort','a b','exact')
        for row in ({'correct':False,'content':'{"answer":["a","b"]}','truncated':True},
                    {'correct':False,'content':'{"answer":["a","b"]}','error':'timeout'},
                    {'correct':False,'content':'<think>{"answer":["a","b"]}'},
                    {'correct':False,'content':'First a then b is probably right.'}):
            self.assertIsNone(format_analysis.inspect(case,row))
        self.assertIsNotNone(format_analysis.inspect(case,{'correct':False,'content':'1. a\n2. b'}))

    def test_numeric_arrays_and_encoded_objects_require_exact_equivalence(self):
        case={'grader':'numeric','answer':42}
        self.assertIsNotNone(format_analysis.inspect(case,{'correct':False,'content':'{"answer":[42]}'}))
        for value in ([41],[True],[42,42]):
            self.assertIsNone(format_analysis.inspect(case,{'correct':False,'content':json.dumps({'answer':value})}))
        case={'grader':'json','answer':{'count':2}}
        self.assertIsNotNone(format_analysis.inspect(case,{'correct':False,'content':json.dumps({'answer':'{"count":2}'})}))
        self.assertIsNone(format_analysis.inspect(case,{'correct':False,'content':json.dumps({'answer':'{"count":"2"}'})}))


class QuestionLabTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.library=question_lab.Library(self.root)
        self.cases=[datasets.case('q'+str(i),'group'+str(i%2),'easy' if i%2 else 'hard','Question '+str(i),42) for i in range(35)]

    def catalog(self):
        with mock.patch.object(question_lab.datasets,'select',return_value=self.cases):
            return self.library.browse({'profile':'quick','seed':17})

    def test_browse_filters_pages_and_shows_effective_system_prompt(self):
        data=self.catalog();token=data['catalog']
        self.assertEqual(data['total'],35);self.assertEqual(len(data['questions']),25)
        self.assertNotIn('answer',data['questions'][0])
        self.assertEqual(len(self.library.browse({'catalog':token,'offset':25})['questions']),10)
        filtered=self.library.browse({'catalog':token,'group':'group1','difficulty':'easy','search':'Question 1'})
        self.assertTrue(all(q['group']=='group1' for q in filtered['questions']))
        detail=self.library.browse({'catalog':token,'case_id':'q1'})
        self.assertEqual(detail['answer'],42);self.assertEqual(detail['system_prompt'],prompts.SYSTEM)

    def test_selection_preserves_originals_records_empty_override_and_checks_identity(self):
        before=copy.deepcopy(self.cases);token=self.catalog()['catalog']
        saved=self.library.save({'catalog':token,'questions':[{'id':'q1','system_override':''},{'id':'q2'}]})
        path=question_lab.selection_path(self.root,saved['id'])
        selection=question_lab.load_selection(path,'quick',17)
        self.assertEqual([c['id'] for c in selection['cases']],['q1','q2'])
        self.assertEqual(selection['cases'][0]['system_override'],'')
        self.assertNotIn('system_override',selection['cases'][1]);self.assertEqual(self.cases,before)
        self.assertEqual(saved['edited'],1)
        with self.assertRaisesRegex(ValueError,'different benchmark'):question_lab.load_selection(path,'vision',17)
        changed=read_json(path);changed['cases'][0]['answer']=99;write_json(path,changed)
        with self.assertRaisesRegex(ValueError,'changed'):question_lab.load_selection(path,'quick',17)

    def test_unknown_duplicate_and_forged_questions_are_rejected(self):
        token=self.catalog()['catalog']
        for questions in ([{'id':'missing'}],[{'id':'q1'},{'id':'q1'}],[{'id':'q1','system_override':None}],[]):
            with self.subTest(questions=questions),self.assertRaises(ValueError):self.library.save({'catalog':token,'questions':questions})
        with self.assertRaises(ValueError):question_lab.selection_path(self.root,'../../file')
        with self.assertRaises(ValueError):self.library.browse({'catalog':'expired'})

    def test_standard_selection_keeps_its_evaluator_and_is_labelled_as_an_experiment(self):
        from stratabench import cli,standard_suites
        case=datasets.case('ifeval/1','ifeval','unrated','Follow instructions','All instructions','upstream',
                           standard_suite='ifeval',system=None,protocol='standard')
        with mock.patch.object(datasets,'select',return_value=[case]):catalog=self.library.browse({'profile':'ifeval','seed':17})
        saved=self.library.save({'catalog':catalog['catalog'],'questions':[{'id':case['id'],'system_override':'Be precise.'}]})
        args=cli.parser().parse_args(['run','--endpoint','http://127.0.0.1:1/v1','--profile','ifeval','--seed','17','--reasoning','off',
            '--question-selection',str(question_lab.selection_path(self.root,saved['id']))])
        with mock.patch.object(cli,'settings',return_value={}),mock.patch.object(cli,'local_lock',return_value=contextlib.nullcontext()),\
             mock.patch.object(standard_suites,'provenance',return_value={'suite':'ifeval','selection':'seeded sample','notice':'Pinned evaluator.'}),\
             mock.patch.object(cli,'run') as run,contextlib.redirect_stdout(io.StringIO()):cli.execute(args)
        selected=run.call_args.args[0];options=run.call_args.args[2]
        self.assertEqual(selected[0]['grader'],'upstream');self.assertEqual(selected[0]['standard_suite'],'ifeval')
        self.assertEqual(options['standard_benchmark']['selection'],'custom question selection')
        self.assertIn('not a published benchmark score',options['standard_benchmark']['notice'])


class EffectivePromptTests(unittest.TestCase):
    options={'temperature':0,'seed':17,'reasoning':'xhigh','max_tokens':4096}

    def test_default_requests_preserve_existing_prompt_contracts(self):
        plain=datasets.case('q','math','easy','Question',42)
        self.assertEqual(runner.payload(plain,self.options)['messages'],[
            {'role':'system','content':runner.SYSTEM},{'role':'user','content':'Question'}])
        for suite in ('ifeval','mmmu','writingbench'):
            case={**plain,'standard_suite':suite,'system':None}
            self.assertEqual(runner.payload(case,self.options)['messages'],[{'role':'user','content':'Question'}])
        writing={**plain,'system':'Return only writing.'}
        self.assertEqual(runner.payload(writing,self.options)['messages'][0]['content'],'Return only writing.')
        for value in ('',None):
            self.assertEqual(runner.payload({**plain,'system':value},self.options)['messages'][0],{'role':'system','content':value})

    def test_override_and_empty_prompt_reach_vision_bfcl_and_swe_adapters(self):
        plain=datasets.case('q','math','easy','Question',42)
        for override in ('Be concise.',''):
            case={**plain,'system_override':override,'images':['data:image/png;base64,abc'],'standard_suite':'mmmu','system':None}
            request=runner.payload(case,self.options)
            self.assertEqual(prompts.system_text(case,request),override)
            self.assertEqual(request['messages'][-1]['content'][1]['image_url']['url'],case['images'][0])
            bfcl={**plain,'standard_suite':'bfcl','messages':[{'role':'system','content':'Upstream'},{'role':'user','content':'Call function'}],
                  'upstream':{'function':[{'name':'tool','parameters':{}}]},'system_override':override}
            adapted,_=standard_runner.bfcl_request(bfcl,runner.payload(bfcl,self.options))
            self.assertEqual(prompts.system_text(bfcl,adapted),override)
            self.assertEqual(adapted['messages'][-1]['content'],'Call function')
            swe={**plain,'standard_suite':'swebench','system_override':override}
            self.assertEqual(prompts.system_text(swe),override)

    def test_recorded_messages_take_precedence_over_inferred_defaults(self):
        case={'prompt':'Question'}
        request={'messages':[{'role':'system','content':'Actually sent'},{'role':'user','content':'Question'}]}
        self.assertEqual(prompts.system_text(case,request),'Actually sent')
        self.assertEqual(prompts.system_messages(case,{'messages':[{'role':'user','content':'Question'}]}),[])


class ReportEvidenceTests(unittest.TestCase):
    def test_old_answers_gain_format_explanations_and_prompt_exports_without_rescoring(self):
        from stratabench import report
        from stratabench.common import digest
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();case=datasets.case('bbh/word_sorting/61','bbh_word_sorting','hard','Sort b a','a b','exact')
            write_json(root/'cases.json',[case])
            write_json(root/'manifest.json',{'cases_sha256':digest([case]),'protocol_sha256':'old-protocol',
                'options':{'profile':'quick','reasoning':'xhigh','repeats':1},
                'targets':[{'id':'target','label':'Version / config'}],'target_status':{'target':{'state':'complete'}}})
            path=root/'target/answers.jsonl';path.parent.mkdir()
            row={'case_id':case['id'],'repeat':0,'expected':'a b','correct':False,'content':'{"answer":["a","b"]}',
                'extracted':['a','b'],'request':{'messages':[{'role':'system','content':'Exact <prompt>'},{'role':'user','content':'Sort b a'}]}}
            path.write_text(json.dumps(row)+'\n',encoding='utf-8');before=path.read_bytes()
            result=report.generate(root)
            self.assertEqual(result['ranking'][0]['accuracy'],0)
            self.assertEqual(result['ranking'][0]['format_errors'],1)
            self.assertEqual(path.read_bytes(),before)
            html=(root/'report.html').read_text(encoding='utf-8')
            for text in ('System prompts by benchmark','Correct content, wrong format','JSON array','Exact &lt;prompt&gt;'):
                self.assertIn(text,html)
            self.assertNotIn('Exact <prompt>',html)
            self.assertEqual(read_json(root/'system-prompts.json')[0]['messages'][0]['content'],'Exact <prompt>')
