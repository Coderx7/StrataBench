"""Exercise persisted settings and first-run state without touching a real installation."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from stratabench import acquisition, common, gui, versions


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_file = self.root / 'settings.json'
        self.patches = [mock.patch.object(common, 'ROOT', self.root),
            mock.patch.object(common, 'STATE', self.state_file),
            mock.patch.object(common, 'DEFAULT_STRATA', ''),
            mock.patch.object(gui, 'ROOT', self.root),
            mock.patch.object(acquisition, 'ROOT', self.root),
            mock.patch.object(versions, 'ROOT', self.root),
            mock.patch.object(gui, 'hardware', return_value={'gpu': {'ok': False, 'output':'Test hardware'}, 'ram':{}, 'cpu_count':2}),
            mock.patch.object(gui.datasets, 'select', return_value=[])]
        for patch in self.patches: patch.start()
        self.app = gui.App()
        self.server = gui.ThreadingHTTPServer(('127.0.0.1', 0), gui.handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        for patch in reversed(self.patches): patch.stop()
        self.temp.cleanup()

    def request(self, route, data=None, auth=True, csrf=True):
        headers = {'Content-Type':'application/json'}
        if auth: headers['X-StrataBench-Key'] = self.app.token
        if csrf: headers['X-StrataBench-Request'] = '1'
        request = urllib.request.Request(self.url+route, headers=headers,
            data=None if data is None else json.dumps(data).encode('utf-8'))
        with self.opener.open(request, timeout=5) as response: return json.load(response)

    def test_fresh_launch_requests_welcome_without_creating_settings_or_starting_workers(self):
        with mock.patch.object(self.app, 'start') as start:
            state = self.request('/api/state')
        self.assertTrue(state['setup']['show_welcome'])
        self.assertFalse(state['setup']['source_configured'])
        self.assertFalse(state['setup']['has_versions'])
        self.assertFalse(state['setup']['has_configs'])
        self.assertFalse(self.state_file.exists())
        start.assert_not_called()

    def test_example_settings_still_show_welcome_until_acknowledged(self):
        common.write_json(self.state_file, {'versions':{}, 'strata_source':acquisition.preferences({'versions':{}})})
        self.assertTrue(self.request('/api/state')['setup']['show_welcome'])

    def test_welcome_acknowledgment_survives_app_restart_without_marking_setup_ready(self):
        self.request('/api/setup-welcome', {})
        restarted = gui.App().state()['setup']
        self.assertFalse(restarted['show_welcome'])
        self.assertFalse(restarted['source_configured'])
        self.assertFalse(restarted['has_versions'])
        self.assertFalse(restarted['has_configs'])

    def test_dismissing_welcome_preserves_source_versions_and_other_preferences(self):
        original = {'strata_root':str(self.root), 'versions':{}, 'default_reasoning':'high',
            'version_sort_mode':'custom', 'strata_source':{'method':'local','folder':str(self.root)}}
        common.write_json(self.state_file, original)
        self.request('/api/setup-welcome', {})
        expected = {**original, 'setup_welcome_seen':True}
        self.assertEqual(common.read_json(self.state_file), expected)

    def test_existing_installations_do_not_get_the_first_run_dialog(self):
        common.write_json(self.state_file, {'strata_root':str(self.root),
            'versions':{'v-existing':{'kind':'snapshot'}}})
        setup = self.request('/api/state')['setup']
        self.assertFalse(setup['show_welcome'])
        self.assertTrue(setup['has_versions'])
        self.assertTrue(setup['source_configured'])
        self.assertFalse(setup['has_configs'])

    def test_all_four_source_methods_persist_without_preparing_or_losing_versions(self):
        config_folder = self.root / 'model configs'; config_folder.mkdir()
        source_folder = self.root / 'Strata source'; source_folder.mkdir()
        python = self.root / 'custom-python'; python.write_bytes(b'not executed')
        for method in acquisition.METHODS:
            with self.subTest(method=method):
                original = {'strata_root':'', 'versions':{'v-existing':{'kind':'snapshot','identity':'preserved'}},
                    'setup_welcome_seen':True, 'default_reasoning':'xhigh', 'version_order':['v-existing']}
                common.write_json(self.state_file, original)
                data = {'method':method,'repository':'https://github.com/example/Strata.git',
                    'folder':str(source_folder), 'config_folder':str(config_folder), 'python':str(python),
                    'python_mode':'existing', 'build_jobs':'3', 'cuda_architectures':'86;89',
                    'backend':'cuda13', 'asset':'chosen-engine.zip', 'allow_unverified':True,
                    'cmake_args':['-DOPTION=ON','-DSECOND=OFF']}
                with mock.patch.object(self.app,'start') as start, mock.patch.object(acquisition,'prepare') as prepare:
                    response = self.request('/api/strata-source', data)
                saved = common.read_json(self.state_file)
                self.assertTrue(response['ok'])
                self.assertEqual(saved['strata_source'], {**data, 'build_jobs':3})
                self.assertEqual(saved['strata_root'], str(config_folder))
                self.assertEqual(saved['versions'], original['versions'])
                self.assertEqual(saved['version_order'], original['version_order'])
                self.assertTrue(saved['setup_welcome_seen'])
                self.assertEqual(gui.App().state()['strata_source'], saved['strata_source'])
                start.assert_not_called(); prepare.assert_not_called()

    def test_invalid_settings_leave_the_saved_file_unchanged(self):
        original = {'strata_root':'', 'versions':{}, 'setup_welcome_seen':True}
        common.write_json(self.state_file, original)
        before = self.state_file.read_bytes()
        invalid = [{'method':'local','folder':str(self.root/'missing')},
            {'method':'folder','folder':str(self.root/'missing')},
            {'repository':'https://user:password@github.com/example/Strata'},
            {'config_folder':str(self.root/'missing')}, {'python':str(self.root/'missing-python')},
            {'build_jobs':65}, {'cuda_architectures':'86;--other'}, {'backend':'unknown'},
            {'python_mode':'global-install'}, {'allow_unverified':'true'}, {'cmake_args':'-DFOO=ON'},
            {'asset':'../outside.zip'}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/api/strata-source', data)
            self.assertEqual(error.exception.code,400)
            self.assertEqual(self.state_file.read_bytes(),before)

    def test_settings_and_welcome_endpoints_require_authentication_and_csrf_header(self):
        for route in ('/api/strata-source','/api/setup-welcome'):
            for options in ({'auth':False},{'csrf':False}):
                with self.subTest(route=route,options=options), self.assertRaises(urllib.error.HTTPError) as error:
                    self.request(route,{},**options)
                self.assertEqual(error.exception.code,403)
        self.assertFalse(self.state_file.exists())

    def test_discovered_configs_complete_the_setup_checklist(self):
        folder = self.root / 'configs'; folder.mkdir()
        common.write_json(folder / 'strata-test.json',{'exe':'unused','args':[],'cwd':str(folder),'model_name':'Test model'})
        common.write_json(self.state_file,{'versions':{'v-existing':{'kind':'snapshot'}},
            'strata_root':str(folder),'strata_source':{'method':'local','folder':str(folder),'config_folder':str(folder)}})
        setup = self.request('/api/state')['setup']
        self.assertTrue(setup['source_configured'] and setup['has_versions'] and setup['has_configs'])


if __name__ == '__main__': unittest.main()
