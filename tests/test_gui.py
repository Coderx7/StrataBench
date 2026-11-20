import contextlib
import io
import json
from pathlib import Path, PureWindowsPath
import tempfile
import threading
import time
import unittest
import shutil
import subprocess
import urllib.error
import urllib.request
from unittest import mock

from stratabench import gui, common


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'results').mkdir()
        self.patches = [mock.patch.object(gui, 'ROOT', self.root),mock.patch.object(common,'ROOT',self.root),
            mock.patch.object(gui, 'hardware', return_value={'gpu': {'ok': True, 'output': 'Test GPU'}}),
            mock.patch.object(gui, 'settings', return_value={'versions': {'v-test': {'kind': 'snapshot'}}, 'strata_root': str(self.root)}),
            mock.patch.object(gui, 'config_catalog', return_value=[{'id': '/config.json','name':'test-iq3_s','model':'iq3_s','context':'262144'}]),
            mock.patch.object(gui.datasets, 'select', return_value=[{'difficulty': 'easy'}])]
        for patch in self.patches:
            patch.start()
        self.app = gui.App()
        self.http = gui.ThreadingHTTPServer(('127.0.0.1', 0), gui.handler(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        if self.app.proc and self.app.proc.poll() is None:
            self.app.stop()
            self.app.proc.wait(timeout=5)
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def request(self, path, data=None, auth=True, origin=None, csrf=True):
        headers = {}
        if auth:
            headers['Cookie'] = 'stratabench='+self.app.token
        if csrf:
            headers['X-StrataBench-Request'] = '1'
        if origin:
            headers['Origin'] = origin
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(self.base+path, data=body, headers=headers)
        return self.opener.open(req, timeout=5)

    def test_local_authentication_required(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request('/api/ping', auth=False)
        self.assertEqual(e.exception.code, 403)
        with self.request('/api/ping') as f:
            self.assertEqual(json.load(f), {'app': 'StrataBench'})

    def test_fresh_browser_gets_full_page_and_its_own_session(self):
        jar = __import__('http.cookiejar', fromlist=['CookieJar']).CookieJar()
        browser = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        with browser.open(self.base+'/', timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'StrataBench', response.read())
            self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        for path in ('/style.css', '/app.js', '/outcomes.js', '/api/ping'):
            with browser.open(self.base+path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertNotEqual(response.headers.get_content_type(), 'application/json' if path.endswith(('.css','.js')) else 'text/html')

    def test_session_bootstrap_rejects_an_untrusted_hostname(self):
        req = urllib.request.Request(self.base+'/', headers={'Host': 'untrusted.example'})
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.opener.open(req, timeout=5)
        self.assertEqual(e.exception.code, 403)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional; only used for this browser-startup regression check')
    def test_browser_startup_reaches_the_api_with_portable_scroll_options(self):
        script = r'''
const vm=require('node:vm'),fs=require('node:fs');
const calls=[];
function element(){return {addEventListener(){},classList:{toggle(){}},dataset:{},textContent:'',innerHTML:''};}
const elements=new Map();
const context={
 document:{querySelector(q){if(!elements.has(q))elements.set(q,element());return elements.get(q);},querySelectorAll(){return [];},addEventListener(){}},
 window:{addEventListener(){},scrollTo(options){if(!['auto','smooth'].includes(options.behavior))throw Error('Unsupported ScrollBehavior');}},
 location:{protocol:'http:',hash:''},
 fetch(url){calls.push(url);return new Promise(()=>{});},setInterval(){return 1;},setTimeout(){return 1;},clearTimeout(){},clearInterval(){},console
};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
if(!calls.includes('/api/state'))throw Error('Application startup never reached the local API');
'''
        result = subprocess.run(['node', '-e', script, str(gui.ASSETS / 'app.js')],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_foreign_origin_and_missing_csrf_header_rejected(self):
        for kwargs in ({'origin': 'https://untrusted.example'}, {'csrf': False}):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.request('/api/stop', {}, **kwargs)
            self.assertEqual(e.exception.code, 403)

    def test_valid_run_uses_structured_arguments_and_xhigh(self):
        with mock.patch.object(self.app, 'start', return_value={'ok': True}) as start:
            with self.request('/api/run', {'versions': ['v-test'], 'configs': ['/config.json']}, origin=self.base) as f:
                self.assertTrue(json.load(f)['ok'])
            command = start.call_args.args[1]
            self.assertEqual(command[command.index('--reasoning')+1], 'xhigh')
            self.assertEqual(command[0], 'run')
            self.assertIn('/config.json', command)

    def test_duration_endpoint_is_read_only_and_covers_all_suites(self):
        with mock.patch.object(self.app,'start') as start:
            with self.request('/api/estimate',{'versions':['v-test'],'configs':['/config.json'],'all_suites':True}) as response:
                data = json.load(response)
            self.assertEqual(len(data['suites']),len(gui.datasets.PROFILES))
            self.assertEqual(data['rows'][0]['config'],'/config.json')
            self.assertGreater(data['lower_seconds'],0)
            self.assertGreaterEqual(data['upper_seconds'],data['lower_seconds'])
            start.assert_not_called()

    def test_order_api_persists_the_preference_without_changing_engines(self):
        with mock.patch.object(gui,'save_settings') as save:
            with self.request('/api/version-order',{'mode':'custom','order':['v-test']}) as response:
                self.assertTrue(json.load(response)['ok'])
            state = save.call_args.args[0]
            self.assertEqual(state['version_sort_mode'],'custom')
            self.assertEqual(state['version_order'],['v-test'])

    def test_source_settings_save_without_downloading_or_building(self):
        source_state={'strata_root':'','versions':{}}
        with mock.patch.object(gui.acquisition,'settings',return_value=source_state), \
                mock.patch.object(gui.acquisition,'save_settings') as save, mock.patch.object(self.app,'start') as start:
            with self.request('/api/strata-source',{'method':'repository','repository':'https://github.com/example/Strata.git',
                    'python_mode':'managed','cuda_architectures':'89','build_jobs':3}) as response:
                self.assertTrue(json.load(response)['ok'])
            self.assertEqual(save.call_args.args[0]['strata_source']['cuda_architectures'],'89')
            self.assertEqual(save.call_args.args[0]['strata_source']['repository'],'https://github.com/example/Strata.git')
            start.assert_not_called()

    def test_release_probe_lists_compatible_assets_without_preparing(self):
        from stratabench.platforms import platform_id
        system,arch=platform_id()
        name=f'strata-engine-1-{system}-{arch}-cuda-cuda12.tar.gz'
        release={'tag_name':'v1','assets':[{'name':name,'size':123,'digest':'sha256:'+'a'*64}]}
        with mock.patch.object(gui.acquisition,'release_info',return_value=release),mock.patch.object(self.app,'start') as start:
            with self.request('/api/strata-release',{'method':'release','tag':'latest'}) as response:
                data=json.load(response)
            self.assertEqual(data['tag'],'v1');self.assertEqual(data['assets'][0]['name'],name)
            start.assert_not_called()

    def test_public_library_refreshes_after_first_download_without_restarting(self):
        self.app.public_ready=False
        with mock.patch.object(self.app,'public_files_present',return_value=True):
            self.app.refresh_public_library()
        self.assertTrue(self.app.public_ready)
        self.assertTrue(all(p['count']==1 for p in self.app.profiles if not p.get('standard_suite')))

    def test_judge_key_is_kept_out_of_commands_and_public_state(self):
        data={'profile':'writing','versions':['v-test'],'configs':['/config.json'],
            'style_judge_enabled':True,'style_judge_endpoint':'http://judge.example/v1',
            'style_judge_model':'fixed-judge','style_judge_key':'test-secret-value'}
        with mock.patch.object(self.app,'start',return_value={'ok':True}) as start:
            self.request('/api/run',data).close()
        self.assertNotIn('test-secret-value',str(start.call_args.args))
        self.assertEqual(start.call_args.kwargs['env_overrides']['STRATABENCH_JUDGE_API_KEY'],'test-secret-value')
        self.assertNotIn('test-secret-value',json.dumps(self.app.state()))

    def test_judge_configuration_and_agent_turn_limits_are_validated_before_start(self):
        base={'versions':['v-test'],'configs':['/config.json']}
        for extra in ({'profile':'tools','agent_turns':0},{'profile':'coding','coding_image':'--privileged'},
                {'profile':'writing','style_judge_enabled':True,'style_judge_endpoint':'file:///tmp/key','style_judge_model':'judge'},
                {'profile':'writing','style_judge_enabled':True,'style_judge_endpoint':'https://user:key@example.com/v1','style_judge_model':'judge'}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):gui.run_command({**base,**extra})

    def test_writing_estimate_works_before_optional_judge_fields_are_filled(self):
        data={'profile':'writing','versions':['v-test'],'configs':['/config.json'],
            'style_judge_enabled':True,'style_judge_endpoint':'','style_judge_model':''}
        with self.request('/api/estimate',data) as response:
            estimate=json.load(response)
        self.assertEqual(estimate['profile'],'writing')
        self.assertEqual(estimate['combinations'],1)
        self.assertGreater(estimate['upper_seconds'],estimate['lower_seconds'])

    def test_standard_sampling_ignores_hidden_difficulty_filters(self):
        base={'profile':'ifeval','versions':['v-test'],'configs':['/config.json'],'difficulties':[],'standard_limit':12}
        sample=gui.run_command(base)
        self.assertEqual(sample[sample.index('--standard-limit')+1],'12');self.assertNotIn('--only',sample)
        full=gui.run_command({**base,'standard_full':True})
        self.assertEqual(full[full.index('--standard-limit')+1],'0')
        for extra in ({'standard_limit':-1},{'standard_full':'yes'}):
            with self.assertRaises(ValueError):gui.run_command({**base,**extra})

    def test_standard_writing_requires_judge_and_keeps_its_key_private(self):
        base={'profile':'writingbench','versions':['v-test'],'configs':['/config.json']}
        with self.assertRaises(ValueError):gui.run_command(base)
        data={**base,'style_judge_endpoint':'http://judge/v1','style_judge_model':'fixed','style_judge_key':'private-key'}
        with mock.patch.object(gui.standard_suites,'verify'),mock.patch.object(self.app,'start',return_value={'ok':True}) as start:
            self.request('/api/run',data).close()
            self.assertNotIn('private-key',str(start.call_args.args))
            self.assertEqual(start.call_args.kwargs['env_overrides']['STRATABENCH_JUDGE_API_KEY'],'private-key')

    def test_unknown_version_and_config_rejected(self):
        with mock.patch.object(self.app, 'start') as start:
            for data in ({'versions': ['v-test'], 'configs': ['/arbitrary.json']},
                         {'versions': ['--help'], 'configs': ['/config.json']}):
                with self.assertRaises(urllib.error.HTTPError) as e:
                    self.request('/api/run', data)
                self.assertEqual(e.exception.code, 400)
            start.assert_not_called()

    def test_invalid_numbers_and_empty_difficulty_rejected(self):
        base = {'versions': ['v-test'], 'configs': ['/config.json']}
        for extra in ({'repeats': 0}, {'temperature': 'NaN'}, {'max_tokens': -1}, {'difficulties': []}):
            with self.assertRaises(ValueError):
                gui.run_command({**base, **extra})

    def test_report_paths_cannot_escape_results(self):
        good = self.root / 'results' / 'run-one'
        good.mkdir()
        self.assertEqual(gui.result_path('run-one'), good)
        (self.root / 'results' / 'escape').symlink_to(self.root)
        for name in ('../settings.json', '/etc/passwd', 'escape'):
            with self.assertRaises(ValueError):
                gui.result_path(name)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/files/run-one/../../settings.json')

    def test_outcome_endpoint_returns_saved_question_and_requires_a_valid_run(self):
        folder = self.root / 'results' / 'test-run'
        folder.mkdir()
        gui.write_json(folder / 'manifest.json', {'status':'interrupted', 'options':{'repeats':1},
            'targets':[{'id':'first','label':'TEST ONLY'}]})
        gui.write_json(folder / 'cases.json', [{'id':'q1','prompt':'What is 6 × 7?',
            'answer':42,'group':'arithmetic','difficulty':'easy'}])
        with self.request('/api/outcomes', {'id':'test-run','category':'pending'}) as response:
            data=json.load(response)
            self.assertEqual(data['counts']['pending'],1)
            self.assertNotIn('case',data)
        with self.request('/api/outcomes', {'id':'test-run','key':'0.0.0'}) as response:
            self.assertEqual(json.load(response)['case']['answer'],42)
        for data in ({'id':'../settings.json'}, {'id':'test-run','key':'bad'}):
            with self.assertRaises(urllib.error.HTTPError): self.request('/api/outcomes', data)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/outcomes', {'id':'test-run'}, auth=False)
        self.assertEqual(error.exception.code,403)

    def test_invalid_custom_questions_are_removed(self):
        with self.assertRaises(ValueError):
            self.app.import_file({'kind': 'tasks', 'content': '{"id":"bad"}'})
        self.assertFalse(list((self.root / 'user-tasks').glob('*.jsonl')))

    def test_imported_config_requires_absolute_working_directory(self):
        relative_paths = ['', '.', '..', 'models', str(Path('models') / 'weights')]
        if gui.windows():
            relative_paths += ['/models', r'\models', r'C:models']
        for cwd in relative_paths:
            with self.subTest(cwd=cwd), self.assertRaises(ValueError):
                self.app.import_file({'kind': 'config', 'content': json.dumps({'exe': 'strata', 'args': [], 'cwd': cwd})})
        self.assertFalse((self.root / 'user-configs').exists())

    def test_imported_config_windows_drive_and_network_paths(self):
        # Exercise Windows path rules on every runner, including Linux.
        with mock.patch.object(gui, 'Path', PureWindowsPath):
            for cwd in ('.', 'models', '/models', r'\models', r'C:models'):
                with self.subTest(cwd=cwd), self.assertRaises(ValueError):
                    self.app.import_file({'kind': 'config', 'content': json.dumps(
                        {'exe': 'strata.exe', 'args': [], 'cwd': cwd})})
            for cwd in (r'C:\models with spaces', r'\\server\share\models'):
                config = {'exe': 'strata.exe', 'args': [], 'cwd': cwd}
                with self.subTest(cwd=cwd):
                    response = self.app.import_file({'kind': 'config', 'content': json.dumps(config)})
                    self.assertEqual(json.loads(Path(response['id']).read_text(encoding='utf-8')), config)

    def test_local_file_import_saves_only_a_copy(self):
        model_folder = self.root / 'models with spaces'
        model_folder.mkdir()
        config = {'exe': str(self.root / 'old build' / 'strata'), 'args': ['--kv', 'q4_0'],
                  'cwd': str(model_folder)}
        source = self.root / 'original-config.json'
        source.write_text(json.dumps(config), encoding='utf-8')
        original = source.read_bytes()
        response = self.app.import_file({'kind': 'config', 'name': '../../config.json',
                                        'content': source.read_text(encoding='utf-8')})
        path = Path(response['id'])
        self.assertEqual(path.parent, self.root / 'user-configs')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), config)
        self.assertNotEqual(path, source)
        self.assertEqual(source.read_bytes(), original)

    def test_background_job_progress_and_safe_stop(self):
        script = self.root / 'bench'
        script.write_text('import time\nprint("2 questions × 1 repeat(s) × 1 combination(s).",flush=True)\n'
                          'print("  1/2 PASS gen/test/1 (0.1s)",flush=True)\ntime.sleep(30)\n')
        self.app.start('doctor', [], 'Test worker')
        deadline = time.time()+5
        while self.app.job['completed'] != 1 and time.time() < deadline:
            time.sleep(.02)
        self.assertEqual(self.app.job['total'], 2)
        self.assertEqual(self.app.job['passed'], 1)
        with self.assertRaises(ValueError):
            self.app.start('doctor', [], 'Second worker')
        self.app.stop()
        deadline = time.time()+5
        while self.app.job['state'] == 'stopping' and time.time() < deadline:
            time.sleep(.02)
        self.assertEqual(self.app.job['state'], 'stopped')


if __name__ == '__main__':
    unittest.main()
