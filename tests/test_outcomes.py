"""Live inspection must never edit a running log or count retry history twice."""
import contextlib
import fcntl
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from stratabench import gui
from stratabench.common import write_json


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'results' / 'run-test'
        self.folder.mkdir(parents=True)
        self.patch = mock.patch.object(gui, 'ROOT', self.root)
        self.patch.start()
        with mock.patch.object(gui, 'hardware', return_value={}), mock.patch.object(gui.datasets, 'select', return_value=[]):
            self.app = gui.App()
        self.cases = [{'id': f'q/{i}', 'prompt': f'Question {i}', 'answer': 42,
                       'difficulty': 'easy' if i<3 else 'hard', 'group': 'arithmetic', 'grader': 'numeric'} for i in range(5)]
        self.manifest = {'created':'2026-11-19T10:00:00+00:00','status':'running', 'case_count':5,
            'options':{'repeats':1,'profile':'smoke','reasoning':'xhigh'},
            'targets':[{'id':'target-a','label':'v1 / Config A'},{'id':'target-b','label':'v2 / Config B'}]}
        write_json(self.folder / 'manifest.json', self.manifest)
        write_json(self.folder / 'cases.json', self.cases)
        (self.folder / 'target-a').mkdir()
        self.path = self.folder / 'target-a' / 'answers.jsonl'
        self.rows = [dict(case_id='q/0',repeat=0,correct=True,content='42',extracted='42',elapsed_seconds=1),
                     dict(case_id='q/1',repeat=0,correct=False,content='41',elapsed_seconds=2),
                     dict(case_id='q/2',repeat=0,correct=False,truncated=True,content='thinking...',unparsed=True),
                     dict(case_id='q/3',repeat=0,correct=False,error='HTTP 503',unparsed=True)]
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in self.rows))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_disjoint_counts_include_missing_targets_and_additional_unparsed_filter(self):
        data = self.app.outcomes(self.folder)
        self.assertEqual(data['counts'],dict(passed=1,incorrect=1,cutoffs=1,errors=1,pending=6,unparsed=1))
        self.assertEqual(data['total'],10)
        self.assertEqual(data['remaining'],7)
        self.assertTrue(data['resumable'])
        self.assertEqual(data['status'],'interrupted')  # recovered stale running manifest
        self.assertEqual(len(self.app.outcomes(self.folder,{'category':'incorrect'})['tests']),1)
        self.assertEqual(self.app.outcomes(self.folder,{'category':'unparsed'})['tests'][0]['status'],'cutoffs')

    def test_partial_line_is_ignored_without_mutation_and_completed_append_is_indexed(self):
        self.app.outcomes(self.folder)
        line=json.dumps(dict(case_id='q/4',repeat=0,correct=True,content='42'))
        with self.path.open('a') as stream: stream.write(line[:15])
        before=self.path.read_bytes()
        self.assertEqual(self.app.outcomes(self.folder)['counts']['pending'],6)
        self.assertEqual(self.path.read_bytes(),before)
        with self.path.open('a') as stream: stream.write(line[15:]+'\n')
        self.assertEqual(self.app.outcomes(self.folder)['counts']['pending'],5)
        self.assertEqual(self.app.outcomes(self.folder,{'key':'0.4.0'})['answer']['content'],'42')

    def test_retry_replaces_error_in_counts_but_retains_attempt_count_and_latest_detail(self):
        self.app.outcomes(self.folder)
        with self.path.open('a') as stream: stream.write(json.dumps(dict(case_id='q/3',repeat=0,correct=True,content='42'))+'\n')
        data=self.app.outcomes(self.folder)
        self.assertEqual(data['counts']['errors'],0)
        self.assertEqual(data['counts']['passed'],2)
        detail=self.app.outcomes(self.folder,{'key':'0.3.0'})
        self.assertEqual(detail['test']['attempts'],2)
        self.assertEqual(detail['answer']['content'],'42')
        self.assertEqual(len(self.path.read_text().splitlines()),5)

    def test_filter_search_pagination_and_detail_never_send_all_raw_answers(self):
        data=self.app.outcomes(self.folder,{'category':'pending','target':'1','difficulty':'easy','search':'Question','offset':1,'limit':1})
        self.assertEqual(data['matched'],3)
        self.assertEqual(len(data['tests']),1)
        self.assertEqual(data['tests'][0]['key'],'1.1.0')
        self.assertNotIn('content',data['tests'][0])
        self.assertFalse(any(k.startswith('_') for k in data['tests'][0]))
        detail=self.app.outcomes(self.folder,{'key':'0.0.0'})
        self.assertEqual(detail['case']['prompt'],'Question 0')
        self.assertEqual(detail['answer']['content'],'42')
        for data in ({'category':'bad'},{'key':'../../etc/passwd'},{'offset':-1},{'limit':101}):
            with self.assertRaises(ValueError): self.app.outcomes(self.folder,data)

    def test_live_lock_and_owned_job_prevent_resume(self):
        with (self.root / '.run.lock').open('w') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            data=self.app.outcomes(self.folder)
            self.assertTrue(data['active'])
            self.assertFalse(data['resumable'])
            with self.assertRaisesRegex(ValueError,'already running'):
                self.app.action('/api/resume',{'id':self.folder.name})
        self.app.job={'result_id':self.folder.name,'state':'stopping'}
        self.assertTrue(self.app.outcomes(self.folder)['active'])

    def test_resume_uses_original_saved_run_and_correct_progress(self):
        with mock.patch.object(self.app,'start',return_value={'ok':True}) as start:
            self.assertTrue(self.app.action('/api/resume',{'id':self.folder.name})['ok'])
            self.assertEqual(start.call_args.args[1],['resume',str(self.folder)])
            self.assertEqual(start.call_args.kwargs['completed'],4)
            self.assertEqual(start.call_args.kwargs['failed'],2)
            self.assertEqual(start.call_args.kwargs['errors'],1)
        self.manifest.update(status='complete')
        write_json(self.folder/'manifest.json',self.manifest)
        self.assertTrue(self.app.outcomes(self.folder)['resumable'])  # missing work remains

    def test_finished_run_cannot_be_resumed_and_log_replacement_is_detected(self):
        self.app.outcomes(self.folder)
        for target in self.manifest['targets']:
            path=self.folder/target['id']/'answers.jsonl';path.parent.mkdir(exist_ok=True)
            path.write_text(''.join(json.dumps(dict(case_id=c['id'],repeat=0,correct=True))+'\n' for c in self.cases))
        self.manifest['status']='complete';write_json(self.folder/'manifest.json',self.manifest)
        self.assertEqual(self.app.outcomes(self.folder)['counts']['passed'],10)
        with self.assertRaisesRegex(ValueError,'already finished'):
            self.app.action('/api/resume',{'id':self.folder.name})

    def test_runs_and_live_job_use_persisted_counts_across_resume(self):
        self.app.job=dict(id='j',kind='resume',state='running',result_id=self.folder.name,started_at=0,completed=100,passed=100)
        with mock.patch.object(gui,'settings',return_value={'versions':{},'strata_root':'/tmp'}),mock.patch.object(gui,'config_catalog',return_value=[]):
            state=self.app.state()
        self.assertEqual(state['job']['completed'],4)
        self.assertEqual(state['job']['passed'],1)
        self.assertEqual(state['job']['counts']['cutoffs'],1)
        self.assertTrue(state['runs'][0]['active'])

    def test_damaged_interior_line_reports_error_and_preserves_original(self):
        self.path.write_bytes(b'bad\n'+self.path.read_bytes())
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'damaged'):self.app.outcomes(self.folder)
        self.assertEqual(self.path.read_bytes(),before)


if __name__=='__main__': unittest.main()
