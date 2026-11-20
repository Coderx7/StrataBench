"""Failure evidence stays readable, scoped to owned files, and independent of model setup."""
import json
from pathlib import Path
import tempfile
import unittest

from stratabench import diagnostics
from stratabench.common import write_json


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.folder=self.root/'results/run-test'
        self.target=self.folder/'target';self.session=self.target/'session-1';self.session.mkdir(parents=True)
        self.manifest={'status':'incomplete','targets':[{'id':'target','label':'v1 / model'}],
            'target_status':{'target':{'state':'failed','error':'Strata startup failed: CUDA out of memory'}}}
        write_json(self.folder/'manifest.json',self.manifest)
        (self.session/'server.log').write_text('Starting server\nCUDA out of memory\n',encoding='utf-8')
        (self.session/'engine.log').write_text('Allocation failed\n',encoding='utf-8')
        rows=[{'case_id':'q1','repeat':0,'error':'old failed attempt'},
              {'case_id':'q1','repeat':0,'correct':True},
              {'case_id':'q2','repeat':0,'error':'HTTP 503: engine unavailable'}]
        (self.target/'answers.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')

    def test_legacy_runs_show_actual_errors_and_both_engine_logs(self):
        details=diagnostics.collect(self.root,{'run':'run-test'})
        self.assertIn('CUDA out of memory',details['reason'])
        messages='\n'.join(i['message'] for i in details['issues'])
        self.assertIn('HTTP 503',messages);self.assertNotIn('old failed attempt',messages)
        self.assertEqual(len(details['logs']),2)
        public=diagnostics.public_details(details)
        self.assertTrue(all('_path' not in source for source in public['logs']))
        json.dumps(public)

    def test_activity_errors_survive_restart_even_before_a_run_manifest_exists(self):
        job={'id':'a'*32,'state':'failed','kind':'run','title':'Benchmark in progress','started_at':100,
             'failure_reason':'ValueError: missing model weights','logs':['private in-memory buffer']}
        diagnostics.save_job(self.root,job)
        (diagnostics.job_folder(self.root,job['id'])/'worker.log').write_text('ValueError: missing model weights\n',encoding='utf-8')
        data=diagnostics.public_details(diagnostics.collect(self.root,{'job':job['id']}))
        self.assertIn('missing model weights',data['reason']);self.assertEqual(len(data['logs']),1)
        self.assertEqual(diagnostics.failed_operations(self.root)[0]['id'],job['id'])
        self.assertNotIn('logs',diagnostics.saved_jobs(self.root)[0])

    def test_log_preview_is_bounded_and_full_file_remains_available(self):
        path=self.session/'engine.log'
        for newline in ('\n','\r\n'):
            with self.subTest(newline=repr(newline)):
                original=('first line'+newline+'x'*diagnostics.PREVIEW_BYTES+newline+'last line'+newline).encode('utf-8')
                path.write_bytes(original)
                details=diagnostics.collect(self.root,{'run':'run-test'})
                log=next(s for s in details['logs'] if s['_path']==path)
                result=diagnostics.preview(diagnostics.log_source(self.root,{'run':'run-test','log':log['id']}))
                self.assertTrue(result['truncated'])
                self.assertTrue(result['text'].endswith('last line'+newline))
                self.assertLessEqual(len(result['text'].encode('utf-8')),diagnostics.PREVIEW_BYTES)
                self.assertNotIn('first line',result['text'])
                self.assertEqual(path.read_bytes(),original)

    def test_traversal_and_unknown_log_ids_cannot_read_other_files(self):
        for data in ({'run':'../elsewhere'},{'run':'run-test','job':'a'*32},{'job':'../../settings.json'}):
            with self.subTest(data=data),self.assertRaises(ValueError):diagnostics.collect(self.root,data)
        with self.assertRaises(ValueError):diagnostics.log_source(self.root,{'run':'run-test','log':'../../settings.json'})
        self.manifest['targets'][0]['id']='../../elsewhere';write_json(self.folder/'manifest.json',self.manifest)
        with self.assertRaises(ValueError):diagnostics.collect(self.root,{'run':'run-test'})

    def test_logs_that_link_outside_the_run_are_not_exposed(self):
        external=self.root/'private.log';external.write_text('outside',encoding='utf-8')
        link=self.session/'server.log';link.unlink()
        try:link.symlink_to(external)
        except (OSError,NotImplementedError) as error:self.skipTest(str(error))
        data=diagnostics.collect(self.root,{'run':'run-test'})
        self.assertFalse(any(s['_path']==external for s in data['logs']))

    def test_captured_secrets_and_authorization_headers_are_redacted(self):
        text=diagnostics.redact('key-secret-123\nAuthorization: Bearer abc123\n{"api_key":"another-secret"}', ['key-secret-123'])
        for secret in ('key-secret-123','abc123','another-secret'):self.assertNotIn(secret,text)
        self.assertIn('[redacted]',text)

    def test_completed_resume_does_not_present_an_old_error_as_a_current_failure(self):
        self.manifest['status']='complete';write_json(self.folder/'manifest.json',self.manifest)
        self.assertTrue(diagnostics.collect(self.root,{'run':'run-test'})['reason'].startswith('This run completed'))
