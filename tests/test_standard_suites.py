import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from pathlib import PureWindowsPath
from unittest import mock

from stratabench import standard_suites as suites, standard_runner, swe_runtime, report, runner, cli
from stratabench.common import read_json,write_json,file_hash


class StandardSuiteTests(unittest.TestCase):
    def test_private_python_layouts_match_windows_and_linux(self):
        self.assertEqual(str(suites.python_path(PureWindowsPath('D:/Benchmark files/bfcl'),'Windows')),
            r'D:\Benchmark files\bfcl\runtime\Scripts\python.exe')
        self.assertEqual(suites.python_path(Path('/tmp/benchmark files/bfcl'),'Linux'),Path('/tmp/benchmark files/bfcl/runtime/bin/python'))

    def test_failed_setup_is_persisted_and_offers_retry_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(suites,'CACHE',Path(tmp)),mock.patch.object(suites,'settings',return_value={}), \
                mock.patch.object(suites,'download'),mock.patch.object(suites.venv,'EnvBuilder') as builder:
            builder.return_value.create.side_effect=RuntimeError('Cannot create private evaluator')
            with self.assertRaisesRegex(RuntimeError,'private evaluator'):suites.prepare('bfcl')
            state=next(s for s in suites.catalog({}) if s['id']=='bfcl')
            self.assertEqual(state['status'],'failed');self.assertFalse(state['ready'])
            self.assertIn('private evaluator',state['operation']['message'])
            self.assertEqual(read_json(Path(tmp)/'bfcl/installation.json')['state'],'failed')

    def test_interrupted_setup_is_detected_without_creating_or_downloading_files(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(suites,'CACHE',Path(tmp)),mock.patch.object(suites,'settings',return_value={}), \
                mock.patch.object(suites,'is_locked',return_value=False),mock.patch.object(suites,'download') as download:
            write_json(Path(tmp)/'bfcl/installation.json',{'state':'running','stage':'Preparing evaluator','step':3,'steps':6})
            state=next(s for s in suites.catalog({}) if s['id']=='bfcl')
            self.assertEqual(state['status'],'interrupted');self.assertIn('Retry setup',state['operation']['message'])
            download.assert_not_called()

    def test_check_installation_uses_the_private_environment_and_no_network(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(suites,'CACHE',Path(tmp)),mock.patch.object(suites,'settings',return_value={}), \
                mock.patch.object(suites,'verify',return_value={'count':1}),mock.patch.object(suites.subprocess,'run') as run, \
                mock.patch.object(suites,'download') as download:
            root=Path(tmp)/'bfcl';root.mkdir()
            suites.check('bfcl')
            self.assertEqual(run.call_args.args[0],[str(suites.python_path(root)),'-m','pip','check'])
            self.assertEqual(read_json(root/'installation.json')['state'],'complete');download.assert_not_called()

    def test_swe_is_disabled_and_never_prepared_implicitly(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(suites,'CACHE',Path(tmp)), \
                mock.patch.object(suites,'settings',return_value={}),mock.patch.object(suites,'download') as download, \
                mock.patch.object(suites,'worker') as worker,mock.patch.object(suites.subprocess,'run') as process:
            self.assertFalse(suites.enabled('swebench',{}))
            for action in (lambda:suites.prepare('swebench'),lambda:suites.select('swebench',1)):
                with self.assertRaisesRegex(ValueError,'Enable|disabled'):action()
            self.assertEqual(list(Path(tmp).iterdir()),[])
            download.assert_not_called();worker.assert_not_called();process.assert_not_called()
            self.assertTrue(all(suites.enabled(s,{}) for s in suites.SPECS if s!='swebench'))

    def test_swe_does_not_pull_images_for_an_invalid_version(self):
        args=cli.parser().parse_args(['run','--profile','swebench','--versions','missing','--configs','missing.json','--reasoning','off'])
        c={'id':'swebench/fixture','difficulty':'unrated','group':'swebench','prompt':'Issue','answer':'Resolved'}
        with mock.patch.object(cli,'initialize',return_value={'versions':{}}),mock.patch.object(cli,'cases_for',return_value=[c]), \
                mock.patch.object(suites,'provenance',return_value={}),mock.patch.object(suites,'worker') as worker:
            with self.assertRaisesRegex(ValueError,'Prepare these versions'):cli.execute(args)
            worker.assert_not_called()

    def test_swe_dry_run_never_pulls_images_or_starts_a_model(self):
        args=cli.parser().parse_args(['run','--profile','swebench','--endpoint','http://fixture/v1','--dry-run','--reasoning','off'])
        c={'id':'swebench/fixture','difficulty':'unrated','group':'swebench','prompt':'Issue','answer':'Resolved'}
        with mock.patch.object(cli,'settings',return_value={'versions':{}}),mock.patch.object(cli,'cases_for',return_value=[c]), \
                mock.patch.object(suites,'provenance',return_value={}),mock.patch.object(suites,'worker') as worker,mock.patch.object(cli,'run') as run:
            cli.execute(args);worker.assert_not_called();run.assert_not_called()

    def test_samples_are_identical_for_same_seed_and_full_split_is_explicit(self):
        cases=[dict(id=str(i)) for i in range(40)]
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(suites,'CACHE',Path(tmp)),mock.patch.object(suites,'verify'):
            write_json(Path(tmp)/'ifeval/cases.json',cases)
            a=suites.select('ifeval',42,8);b=suites.select('ifeval',42,8)
            self.assertEqual(a,b);self.assertEqual(len(a),8)
            self.assertNotEqual(a,suites.select('ifeval',43,8))
            self.assertEqual(len(suites.select('ifeval',42,0)),40)

    def test_source_mutation_blocks_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(suites,'CACHE',Path(tmp)):
            root=Path(tmp)/'ifeval';root.mkdir();p=root/'source.py';p.write_text('original')
            meta={'files':{'source.py':file_hash(p)}}
            with mock.patch.object(suites,'metadata',return_value=meta):
                suites.verify('ifeval');p.write_text('changed')
                with self.assertRaisesRegex(RuntimeError,'changed'):suites.verify('ifeval')

    def test_standard_payload_preserves_prompt_and_multimodal_images(self):
        c={'id':'mmmu/a','difficulty':'unrated','prompt':'Original question <image 1>','standard_suite':'mmmu','system':None,
            'images':['data:image/png;base64,AAA','data:image/png;base64,BBB']}
        body=runner.payload(c,{'seed':1,'temperature':0,'reasoning':'xhigh'})
        self.assertEqual([m['role'] for m in body['messages']],['user'])
        self.assertEqual(body['messages'][0]['content'][0]['text'],c['prompt'])
        self.assertEqual(len(body['messages'][0]['content']),3)
        self.assertEqual(body['reasoning_effort'],'xhigh')
        saved=runner.stored_request(c,body)
        self.assertEqual(saved['messages'][0]['content'][1]['image_url']['url'],'case-image:0')
        self.assertIn('data_url_sha256',saved['messages'][0]['content'][1]['image_url'])
        self.assertEqual(body['messages'][0]['content'][1]['image_url']['url'],c['images'][0])

    def test_bfcl_api_schema_and_real_tool_calls_reach_checker(self):
        c={'standard_suite':'bfcl','messages':[{'role':'user','content':'Question'}],
            'upstream':{'function':[{'name':'area.triangle','parameters':{'type':'dict','properties':{'base':{'type':'float'}}}}]}}
        response={'content':'','finish_reason':'tool_calls','response':{'choices':[{'message':{'tool_calls':[
            {'id':'c1','function':{'name':'area_triangle','arguments':'{"base":10}'}}]}}]},'elapsed_seconds':1}
        with mock.patch.object(runner,'completion',return_value=response),mock.patch.object(suites,'worker',return_value={'correct':True,'metrics':{'ast_accuracy':1}}) as grade:
            result=standard_runner.evaluate(c,{'messages':[]},'http://localhost/v1',{'timeout':10,'seed':1})
            self.assertTrue(result['correct'])
            self.assertEqual(grade.call_args.args[2]['calls'],[{'area.triangle':{'base':10}}])
            function=result['request']['tools'][0]['function']
            self.assertEqual(function['parameters']['type'],'object')
            self.assertEqual(function['parameters']['properties']['base']['type'],'number')

    def test_writingbench_judge_uses_official_prompts_and_has_no_binary_threshold(self):
        c={'standard_suite':'writingbench','prompt':'Write a report','upstream':{'checklist':[]}}
        prompts={'system':'Published system','prompts':[{'name':'clarity','prompt':'Published rubric'},{'name':'style','prompt':'Second rubric'}]}
        responses=[{'content':json.dumps({'score':score,'reason':'Evidence'}),'finish_reason':'stop','response':{}} for score in (6,8)]
        opts={'style_judge_endpoint':'http://judge/v1','style_judge_model':'fixed-judge','timeout':20}
        with mock.patch.object(suites,'worker',return_value=prompts),mock.patch.object(runner,'completion',side_effect=responses) as complete:
            result=standard_runner.judge_writingbench(c,'Response',opts)
            self.assertIsNone(result['correct']);self.assertEqual(result['score'],.7)
            self.assertEqual(result['metrics']['rubric_score_100'],70)
            self.assertEqual(complete.call_args.args[1]['messages'][1]['content'],'Second rubric')
        with mock.patch.object(suites,'worker',return_value=prompts),mock.patch.object(runner,'completion',side_effect=OSError('offline')):
            result=standard_runner.judge_writingbench(c,'Response',opts)
            self.assertIn('judge_error',result);self.assertIsNone(result['score'])

    def test_cutoff_writing_is_not_sent_to_judge(self):
        response={'content':'unfinished','finish_reason':'length','response':{},'elapsed_seconds':1}
        with mock.patch.object(runner,'completion',return_value=response),mock.patch.object(standard_runner,'judge_writingbench') as judge:
            r=standard_runner.evaluate({'standard_suite':'writingbench','score_only':True},{},'local',{'timeout':20,'seed':1})
            self.assertTrue(r['truncated']);self.assertIsNone(r['standard_result']['score']);judge.assert_not_called()

    def test_ifeval_instruction_scores_use_micro_denominators(self):
        cases=[{'upstream':{'instruction_id_list':['a']}},{'upstream':{'instruction_id_list':['b','c','d']}}]
        rows={0:{'standard_result':{'score':1,'metrics':{'prompt_strict':1},'instruction_strict_checks':[True]}},
            1:{'standard_result':{'score':0,'metrics':{'prompt_strict':0},'instruction_strict_checks':[False,False,False]}}}
        m=report.standard_metrics(cases,rows,1,{'standard_benchmark':{'suite':'ifeval','metric':'Prompt strict','selection':'full configured split'}})
        self.assertEqual(m['primary_value'],50);self.assertEqual(m['metrics']['instruction_strict'],.25)

    def test_writing_metrics_report_coverage_without_zero_accuracy(self):
        c=[{},{}];rows={0:{'standard_result':{'score':.8,'metrics':{'rubric_score_100':80}}},
            1:{'standard_result':{'score':None,'judge_error':'offline'}}}
        result=report.standard_metrics(c,rows,1,{'standard_benchmark':{'suite':'writingbench','metric':'Rubric /100','selection':'seeded sample'}})
        self.assertEqual(result['primary_value'],80);self.assertEqual(result['scored'],1);self.assertEqual(result['judge_errors'],1)

    def test_swe_containers_have_no_network_host_mounts_or_privileges(self):
        client=mock.Mock();container=client.containers.create.return_value
        with mock.patch.object(swe_runtime,'client_for',return_value=client):swe_runtime.create(Path('/tmp/test'),'sha256:'+'a'*64)
        kwargs=client.containers.create.call_args.kwargs
        self.assertEqual(kwargs['network_mode'],'none');self.assertEqual(kwargs['cap_drop'],['ALL'])
        self.assertEqual(kwargs['mem_limit'],'4g');self.assertEqual(kwargs['pids_limit'],256)
        self.assertNotIn('volumes',kwargs);self.assertNotIn('mounts',kwargs);self.assertNotIn('privileged',kwargs)
        container.start.assert_called_once()

    def test_swe_container_ownership_is_checked_before_commands(self):
        client=mock.Mock();client.containers.get.return_value.labels={'stratabench.owner':'another-workspace'}
        with mock.patch.object(swe_runtime,'client_for',return_value=client):
            with self.assertRaisesRegex(ValueError,'another workspace'):swe_runtime.container_for(Path('/tmp/test'),'stratabench-swe-id')
            with self.assertRaisesRegex(ValueError,'Invalid'):swe_runtime.container_for(Path('/tmp/test'),'someone-elses-container')

    def test_swe_test_spec_matches_the_pinned_package_interface(self):
        def make_test_spec(instance,namespace=None):return mock.Mock(arch='x86_64',instance_id=instance['instance_id'],namespace=namespace)
        modules={'swebench':mock.Mock(),'swebench.harness':mock.Mock(),'swebench.harness.test_spec':mock.Mock(),
            'swebench.harness.test_spec.test_spec':mock.Mock(make_test_spec=make_test_spec)}
        with mock.patch.dict('sys.modules',modules):
            spec=swe_runtime.spec_for({'upstream':{'instance_id':'fixture'}})
            self.assertEqual(spec.namespace,'swebench');self.assertEqual(spec.arch,'x86_64')

    def test_stop_cleanup_is_scoped_to_one_workspace_and_run(self):
        result=mock.Mock(returncode=0,stdout='a'*12+'\nnot-an-id\n')
        with mock.patch.object(suites.subprocess,'run',return_value=result) as process:
            suites.cleanup_run('20261119-123456-swebench-abcdef')
            query=process.call_args_list[0].args[0]
            self.assertTrue(any(s.startswith('label=stratabench.owner=') for s in query))
            self.assertIn('label=stratabench.run=20261119-123456-swebench-abcdef',query)
            self.assertEqual(process.call_args_list[1].args[0],['docker','rm','-f','a'*12])

    def test_swe_grading_uses_a_fresh_container_and_pinned_official_grader(self):
        fake=mock.Mock();fake.instance_id='repo__issue-1';fake.eval_script='official test patch and test command'
        container=mock.Mock();upstream_grader=mock.Mock(return_value={fake.instance_id:{'resolved':True}})
        modules={'swebench':mock.Mock(),'swebench.harness':mock.Mock(),'swebench.harness.grading':mock.Mock(get_eval_report=upstream_grader)}
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('sys.modules',modules),mock.patch.object(swe_runtime,'spec_for',return_value=fake), \
                mock.patch.object(swe_runtime,'create',return_value=container) as create,mock.patch.object(swe_runtime,'copy_text') as copy_text, \
                mock.patch.object(swe_runtime,'execute',return_value={'exit_code':0,'output':'acceptance output'}):
            result=swe_runtime.operation('evaluate',Path(tmp),{'case':{},'image':'sha256:123','patch':'model patch'})
            self.assertTrue(result['resolved']);create.assert_called_once();container.remove.assert_called_once_with(force=True)
            self.assertIn(mock.call(container,'/tmp/stratabench-eval.sh',fake.eval_script),copy_text.call_args_list)
            self.assertEqual(upstream_grader.call_args.args[1]['model_patch'],'model patch')

    def test_actual_cached_ifeval_and_bfcl_checkers(self):
        if not suites.metadata('ifeval') or not suites.metadata('bfcl'):self.skipTest('Optional prepared evaluators are absent.')
        c=read_json(suites.folder('bfcl')/'cases.json')[0]
        calls=[{name:{k:v[0] for k,v in args.items()} for name,args in item.items()} for item in c['answer']]
        self.assertTrue(suites.worker('bfcl','grade',{'case':c,'calls':calls})['correct'])
        self.assertFalse(suites.worker('bfcl','grade',{'case':c,'calls':[]})['correct'])
        c=read_json(suites.folder('ifeval')/'cases.json')[0]
        result=suites.worker('ifeval','grade',{'case':c,'content':'Deliberately incomplete.'})
        self.assertFalse(result['correct']);self.assertIn('prompt_loose',result['metrics'])

    def test_actual_cached_mmmu_choice_and_open_answer_checkers(self):
        if not suites.metadata('mmmu'):self.skipTest('Optional MMMU evaluator is absent.')
        cases=read_json(suites.folder('mmmu')/'cases.json')
        self.assertEqual(len(cases),900)
        for kind in ('multiple-choice','open'):
            c=next(c for c in cases if c['question_type']==kind or kind=='open' and c['question_type']=='open-ended')
            self.assertTrue(c['images'])
            content='('+c['answer']+')' if kind=='multiple-choice' else str(c['answer'])
            result=suites.worker('mmmu','grade',{'case':c,'content':content,'seed':42})
            self.assertTrue(result['correct'],c['id'])

    def test_failed_judging_resumes_without_regenerating_the_writing(self):
        c={'id':'writingbench/1','group':'writingbench','difficulty':'unrated','prompt':'Write a report',
            'answer':'Published rubric','standard_suite':'writingbench','system':None,'protocol':'standard','score_only':True}
        benchmark={'suite':'writingbench','name':'WritingBench','metric':'Rubric score / 100','selection':'full configured split',
            'split':'fixture','selected_count':1,'full_count':1,'notice':'Fixture protocol','revision':'a'*40}
        options={'profile':'writingbench','seed':1,'temperature':0,'reasoning':'off','repeats':1,'timeout':10,
            'standard_benchmark':benchmark,'style_judge_endpoint':'http://judge/v1','style_judge_model':'fixed'}
        answer={'content':'The saved writing.','finish_reason':'stop','response':{'choices':[{'message':{'role':'assistant','content':'The saved writing.'}}]},'elapsed_seconds':1,'usage':{}}
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(runner,'ROOT',Path(tmp)), \
                mock.patch.object(runner,'hardware',return_value={}),mock.patch.object(runner,'request_json',side_effect=OSError('no props')), \
                mock.patch.object(runner,'completion',return_value=answer) as complete, \
                mock.patch.object(standard_runner,'judge_writingbench',return_value={'correct':None,'score':None,'metrics':{},'judge_error':'offline'}):
            folder=runner.run([c],[{'id':'target','label':'Fixture','endpoint':'http://fixture/v1'}],options)
            self.assertEqual(read_json(folder/'manifest.json')['status'],'incomplete')
            self.assertEqual(complete.call_count,2) # Warm-up and one writing generation.
            complete.reset_mock()
            with mock.patch.object(standard_runner,'judge_writingbench',return_value={'correct':None,'score':.8,'metrics':{'rubric_score_100':80}}):
                runner.run([c],[{'id':'target','label':'Fixture','endpoint':'http://fixture/v1'}],options,resume=folder)
            self.assertEqual(complete.call_count,1) # Only the common unscored warm-up.
            self.assertEqual(read_json(folder/'manifest.json')['status'],'complete')
            result=read_json(folder/'standard-metrics.json')['results'][0]
            self.assertEqual(result['primary_value'],80);self.assertTrue(result['complete'])
            summary=read_json(folder/'summary.json')['ranking'][0]
            self.assertIsNone(summary['accuracy']);self.assertIsNone(summary['correct'])
            self.assertIsNone(summary['groups']['writingbench']['accuracy']);self.assertIsNone(summary['wilson_95'])


if __name__=='__main__':unittest.main()
