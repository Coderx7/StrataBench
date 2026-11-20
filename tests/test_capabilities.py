import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from stratabench import capability_cases as cases, capability_runner as agents, coding_runtime, datasets, grading, runner, report, versions
from stratabench.common import read_json


def response(content='',calls=None,finish='stop'):
    message={'role':'assistant','content':content}
    if calls:message['tool_calls']=calls
    return {'content':content,'finish_reason':finish,'elapsed_seconds':.01,'usage':{'completion_tokens':10},
        'response':{'choices':[{'message':message,'finish_reason':finish}]}}


def call(name,args):return {'id':'test-'+name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.options={'seed':1,'temperature':0,'reasoning':'xhigh','max_tokens':None,'timeout':10,'agent_turns':8,
            'coding_image_id':'sha256:'+'a'*64,'profile':'tools','repeats':1}

    def test_all_new_suites_are_deterministic_and_cover_five_levels(self):
        for profile,count in [('writing',20),('vision',20),('tools',15),('coding',10)]:
            with self.subTest(profile=profile):
                a=datasets.select(profile,123);self.assertEqual(a,datasets.select(profile,123));self.assertEqual(len(a),count)
                self.assertEqual({c['difficulty'] for c in a},set(cases.LEVELS))
                self.assertEqual(len({c['id'] for c in a}),count)
        self.assertEqual(len(datasets.select('smoke')),7)

    def test_vision_requests_contain_real_png_bytes_without_answer_leakage(self):
        case=cases.vision_cases(12)[0];payload=runner.payload(case,self.options)
        content=payload['messages'][1]['content'];self.assertEqual(content[0]['text'],case['prompt'])
        self.assertEqual(content[1]['image_url']['url'],case['image'])
        import base64
        self.assertTrue(base64.b64decode(case['image'].split(',')[1]).startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertNotIn('answer',content[1]['image_url'])

    def test_writing_rules_measure_partial_compliance_and_reject_cutoffs(self):
        case={'grader':'writing','rules':{'min_words':2,'max_words':8,'required':['hello'],'forbidden':['leverage']}}
        good=grading.grade(case,'hello there','stop');self.assertTrue(good['correct']);self.assertEqual(good['constraint_score'],1)
        bad=grading.grade(case,'hello leverage','stop');self.assertFalse(bad['correct']);self.assertGreater(bad['constraint_score'],0)
        self.assertFalse(grading.grade(case,'hello there','length')['correct'])
        self.assertFalse(grading.grade(case,'<think>hello there','stop')['correct'])

    def test_numbered_steps_and_word_boundaries_are_checked(self):
        rules={'min_words':1,'max_words':50,'numbered':2,'forbidden':['just']}
        self.assertTrue(cases.writing_grade('1. Adjust the chair.\n2. Continue.','stop',rules)['correct'])
        self.assertFalse(cases.writing_grade('1. Start.\n3. Continue.','stop',rules)['correct'])

    def tool_completion(self,case,invalid=False,forever=False):
        scenario=case['tool_scenario']
        script=[call('find_customer',{'name':scenario['name']}),call('list_orders',{'customer_id':scenario['customer_id']}),
            call('tax_rate',{'region':'North'}),call('total_order_amount',{'amounts':scenario['selected_amounts'],'tax_percent':scenario['tax_percent']})]
        if invalid:script.insert(0,call('host_shell',{'command':'not executed'}))
        queue=iter(script)
        def complete(*args):
            tc=script[0] if forever else next(queue,None)
            return response(calls=[tc],finish='tool_calls') if tc else response(json.dumps({'answer':case['answer']}))
        return complete

    def test_tool_workflow_requires_real_calls_and_correct_filtered_inputs(self):
        case=cases.tool_cases(1)[-1]
        row=agents.run_agent(case,runner.payload(case,self.options),'http://test/v1',self.options,complete=self.tool_completion(case))
        self.assertTrue(row['correct']);self.assertEqual(row['tool_calls'],4);self.assertEqual(row['tool_errors'],0)
        self.assertEqual(row['usage']['completion_tokens'],50)
        self.assertIn('tools',row['request']);self.assertEqual(row['request']['max_tokens'],4096)
        self.assertEqual(row['agent_trace'][1]['role'],'tool')
        row=agents.run_agent(case,runner.payload(case,self.options),'http://test/v1',self.options,complete=lambda *a:response(json.dumps({'answer':case['answer']})))
        self.assertFalse(row['correct'])

    def test_unknown_tools_and_turn_limits_are_model_failures(self):
        case=cases.tool_cases(1)[0]
        row=agents.run_agent(case,runner.payload(case,self.options),'http://test/v1',self.options,complete=self.tool_completion(case,invalid=True))
        self.assertFalse(row['correct']);self.assertEqual(row['tool_errors'],1)
        row=agents.run_agent(case,runner.payload(case,self.options),'http://test/v1',self.options,complete=self.tool_completion(case,forever=True))
        self.assertFalse(row['correct']);self.assertTrue(row['agent_budget_exhausted']);self.assertEqual(row['agent_turns'],8)

    def test_coding_file_tools_cannot_read_or_write_host_paths(self):
        case=cases.coding_cases(1)[0];files=dict(case['coding']['files'])
        for name,args in [('read_file',{'path':'../../settings.json'}),('write_file',{'path':'../outside.py','content':'bad'})]:
            with self.assertRaises(ValueError):agents.dispatch(case,name,args,files,self.options)
        self.assertEqual(files,case['coding']['files'])
        self.assertGreater(len(case['coding']['hidden_tests']),len(case['coding']['public_tests']))

    def test_agentic_coding_saves_the_patch_and_runs_hidden_acceptance_tests(self):
        case=cases.coding_cases(1)[0]
        sequence=iter([call('read_file',{'path':'solution.py'}),call('write_file',{'path':'solution.py','content':'def add(a,b):\n return a+b\n'}),call('run_tests',{})])
        def complete(*args):
            tc=next(sequence,None);return response(calls=[tc],finish='tool_calls') if tc else response('Done')
        with mock.patch.object(agents,'run_tests',side_effect=lambda code,function,tests,image:{'passed':len(tests),'total':len(tests)}) as run:
            result=agents.run_agent(case,runner.payload(case,self.options),'http://test/v1',self.options,complete=complete)
        self.assertTrue(result['correct']);self.assertIn('return a+b',result['final_files']['solution.py'])
        self.assertEqual(run.call_args.args[2],case['coding']['hidden_tests'])

    def test_configured_vision_encoder_is_preserved_when_a_version_has_no_bundled_encoder(self):
        from stratabench.common import write_json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();(root/'encoder').write_bytes(b'helper');(root/'projector.gguf').write_bytes(b'weights')
            cfg={'exe':'unused','cwd':str(root),'args':[],'vision':{'exe':'encoder','mmproj':'projector.gguf'}}
            path=root/'config.json';write_json(path,cfg)
            version={'root':str(root/'version'),'exe':str(root/'version/engine/strata')}
            effective,provenance=versions.effective_config(path,version,root/'session',1234,True)
            self.assertEqual(effective['vision']['exe'],str(root/'encoder'))
            self.assertTrue(any('sha256' in change for change in provenance['overrides']))

    def test_judge_ratings_and_failures_are_separate_from_rule_correctness(self):
        case=cases.writing_cases(1)[0];options={**self.options,'style_judge_endpoint':'http://judge/v1','style_judge_model':'fixed-judge'}
        scores={k:4 for k in ('clarity','tone','coherence','effectiveness')}
        with mock.patch.object(runner,'completion',return_value=response(json.dumps({'scores':scores,'reason':'Clear'}))):
            result=agents.judge_writing(case,'Writing',options,'not stored')
        self.assertEqual(result['average'],4);self.assertNotIn('not stored',json.dumps(result))
        with mock.patch.object(runner,'completion',side_effect=TimeoutError('Judge unavailable')):
            result=agents.judge_writing(case,'Writing',options)
        self.assertEqual(result['status'],'error');self.assertNotIn('correct',result)

    def test_writing_run_persists_both_scores_in_reports(self):
        case={'id':'writing/test','group':'writing_test','difficulty':'easy','prompt':'Say hello in 2–8 words.',
            'answer':'All rules satisfied','grader':'writing','protocol':'writing',
            'rules':{'min_words':2,'max_words':8,'required':['hello'],'forbidden':[]}}
        options={**self.options,'profile':'writing','style_judge_endpoint':'http://judge/v1','style_judge_model':'fixed'}
        scores={k:3 for k in ('clarity','tone','coherence','effectiveness')}
        def complete(endpoint,*args):return response(json.dumps({'scores':scores,'reason':'Acceptable'})) if 'judge' in endpoint else response('hello there')
        with tempfile.TemporaryDirectory() as directory,mock.patch.object(runner,'ROOT',Path(directory)),\
                mock.patch.object(runner,'hardware',return_value={}),mock.patch.object(runner,'request_json',return_value={}),\
                mock.patch.object(runner,'completion',side_effect=complete),contextlib.redirect_stdout(io.StringIO()):
            folder=runner.run([case],[{'id':'fake','label':'test','endpoint':'http://test/v1'}],options)
            summary=read_json(folder/'summary.json')['ranking'][0]
            self.assertEqual(summary['accuracy'],1);self.assertEqual(summary['constraint_score'],1)
            self.assertEqual(summary['style_judge_score'],3);self.assertEqual(summary['style_judge_count'],1)
            self.assertIn('Capability diagnostics',(folder/'report.html').read_text())


class DockerRuntimeTests(unittest.TestCase):
    def test_container_command_has_no_host_mounts_and_limits_resources(self):
        process=mock.Mock();process.stdout=io.BytesIO(b'{"nonce":"testnonce","passed":1,"total":1}\n')
        process.stdin=io.BytesIO();process.poll.return_value=0;process.returncode=0
        with mock.patch.object(coding_runtime.uuid,'uuid4',side_effect=[mock.Mock(hex='testnonce'),mock.Mock(hex='testname')]),\
                mock.patch.object(coding_runtime.subprocess,'Popen',return_value=process) as popen,\
                mock.patch.object(coding_runtime.subprocess,'run'):
            result=coding_runtime.run_tests('def add(a,b): return a+b','add',[{'args':[1,2],'expected':3}],'sha256:'+'a'*64)
        command=popen.call_args.args[0]
        for flag in ('--network=none','--read-only','--cap-drop=ALL','--memory=256m','--cpus=1','--pids-limit=64','--pull=never'):
            self.assertIn(flag,command)
        self.assertNotIn('-v',command);self.assertNotIn('--mount',command);self.assertEqual(result['passed'],1)

    @unittest.skipUnless(os.environ.get('STRATABENCH_DOCKER_TEST_IMAGE'),'Set STRATABENCH_DOCKER_TEST_IMAGE to an existing Python image for container integration checks')
    def test_real_container_accepts_correct_code_and_rejects_incorrect_or_hanging_code(self):
        image=coding_runtime.image_id(os.environ['STRATABENCH_DOCKER_TEST_IMAGE'])
        tests=[{'args':[1,2],'expected':3},{'args':[-4,8],'expected':4}]
        self.assertEqual(coding_runtime.run_tests('def add(a,b): return a+b','add',tests,image)['passed'],2)
        self.assertEqual(coding_runtime.run_tests('def add(a,b): return a-b','add',tests,image)['passed'],0)
        result=coding_runtime.run_tests('def add(a,b):\n while True: pass','add',tests[:1],image,timeout=8)
        self.assertEqual(result['passed'],0)


if __name__=='__main__':unittest.main()
