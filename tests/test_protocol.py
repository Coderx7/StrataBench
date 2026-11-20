"""Resume compatibility must preserve measurement identity and saved evidence."""
import copy
import socket
import os
from pathlib import Path
import tempfile
import unittest

from stratabench import protocol, runner
from stratabench.common import ROOT, digest, read_json


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.cases=[{'id':'q1','prompt':'What is 6*7?','answer':42}]
        self.targets=[{'id':'t1','label':'Model A'}]
        self.options={'reasoning':'xhigh','seed':1,'port':18765}
        self.env={'STRATA_TEST_SETTING':'1'}
        self.current=protocol.code_hash(ROOT)
        self.legacy=read_json(protocol.COMPATIBILITY_FILE)['compatible_protocols'][0]['previous'][1]
        self.manifest={'cases_sha256':digest(self.cases),'targets':self.targets,'options':self.options,
                       'environment':self.env,'protocol_sha256':self.legacy}
        self.manifest['signature']=protocol.signature(self.cases,self.targets,self.options,self.legacy,self.env)

    def validate(self,**overrides):
        args=dict(manifest=self.manifest,cases=self.cases,targets=self.targets,options=self.options,
                  environment=self.env,current_protocol=self.current)
        protocol.validate_resume(**(args|overrides))

    def test_all_reviewed_legacy_revisions_match_this_execution_code(self):
        entry=read_json(protocol.COMPATIBILITY_FILE)['compatible_protocols'][0]
        self.assertEqual(entry['current'],self.current,
                         'Execution changed: review compatibility before updating the migration catalog.')
        for previous in entry['previous']:
            with self.subTest(previous=previous):self.assertTrue(protocol.compatible(previous,self.current))
        self.validate()

    def test_unknown_or_changed_execution_code_is_not_implicitly_compatible(self):
        for saved,current in [('unknown',self.current),(self.legacy,'changed-code')]:
            with self.subTest(saved=saved,current=current):
                self.assertFalse(protocol.compatible(saved,current))
        with self.assertRaisesRegex(RuntimeError,'execution or scoring code changed'):
            self.validate(current_protocol='changed-code')
        self.assertFalse(protocol.compatible(self.legacy,self.current,[{'system_override':'Previously unsupported field'}]))

    def test_precise_drift_reasons_do_not_expose_environment_values(self):
        changes=[('cases',[{'id':'q1','answer':41}],'questions'),
                 ('targets',[{'id':'changed'}],'model configurations'),
                 ('options',dict(self.options,reasoning='low'),'run settings changed.*reasoning'),
                 ('environment',{'STRATA_TEST_SETTING':'private-value'},'engine environment.*STRATA_TEST_SETTING')]
        original=copy.deepcopy(self.manifest)
        for key,value,reason in changes:
            with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,reason) as error:
                self.validate(**{key:value})
            self.assertNotIn('private-value',str(error.exception))
        self.assertEqual(original,self.manifest)

    def test_a_modified_signature_is_not_repaired_or_overwritten(self):
        self.manifest['signature']='altered'
        with self.assertRaisesRegex(RuntimeError,'fingerprint does not match'):self.validate()
        self.assertEqual(self.manifest['signature'],'altered')

    def test_presentation_updates_do_not_change_execution_hash_but_new_evaluators_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'stratabench';folder.mkdir()
            (folder/'runner.py').write_text('measurement = 1\n',encoding='utf-8')
            before=protocol.code_hash(tmp)
            for name in protocol.PRESENTATION_MODULES:
                (folder/name).write_text('presentation = 2\n',encoding='utf-8')
            self.assertEqual(before,protocol.code_hash(tmp))
            (folder/'grading.py').write_text('score = 0\n',encoding='utf-8')
            self.assertNotEqual(before,protocol.code_hash(tmp))
            before=protocol.code_hash(tmp)
            (folder/'new_evaluator.py').write_text('score = 1\n',encoding='utf-8')
            self.assertNotEqual(before,protocol.code_hash(tmp))


class PortProbeTests(unittest.TestCase):
    def test_a_live_listener_is_never_available(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            listener.bind(('127.0.0.1',0));listener.listen()
            self.assertFalse(runner.is_port_free(listener.getsockname()[1]))

    @unittest.skipIf(os.name=='nt','POSIX reuse matches the managed server; Windows keeps exclusive probes')
    def test_a_closed_reusable_server_does_not_block_the_next_combination(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
            with socket.create_connection(('127.0.0.1',port),timeout=2) as client:
                connection,_=listener.accept()
                with connection:
                    connection.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1),b'')
        self.assertTrue(runner.is_port_free(port))
