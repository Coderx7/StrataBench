import contextlib
import io
import itertools
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stratabench import datasets, grading, report, runner, versions
from stratabench.common import read_json, write_json


class GradingTests(unittest.TestCase):
    def test_numeric_equivalence(self):
        for value in ('0.5', '.5', '1/2', '1./2.', r'\frac{1}{2}', r'$\dfrac{2}{4}$'):
            self.assertEqual(grading.numeric(value), grading.numeric('0.5'))
        self.assertEqual(grading.numeric('1,234'), 1234)

    def test_no_arbitrary_expressions_or_lists(self):
        for value in ('1,2', '2+2', '__import__("os")', 'Infinity', True, {}, '1/0', '1e999999999'):
            self.assertIsNone(grading.numeric(value))

    def test_exact_large_integers(self):
        c = {'grader': 'numeric', 'answer': 1000000000000000}
        self.assertFalse(grading.grade(c, '{"answer":1000000000000001}')['correct'])

    def test_do_not_score_reasoning_as_answer(self):
        c = {'grader': 'numeric', 'answer': 42}
        self.assertFalse(grading.grade(c, '<think>{"answer":42}')['correct'])
        self.assertFalse(grading.grade(c, '<think>{"answer":42}</think>{"answer":41}')['correct'])
        self.assertFalse(grading.grade(c, 'We first get 42, but must still reason about the result.')['correct'])

    def test_boxed_nested(self):
        c = {'grader': 'numeric', 'answer': '1/2'}
        self.assertTrue(grading.grade(c, r'We obtain \boxed{\frac{1}{2}}.')['correct'])

    def test_json_and_choice(self):
        self.assertTrue(grading.grade({'grader': 'choice', 'answer': '(A)'}, '{"answer":"A"}')['correct'])
        self.assertTrue(grading.grade({'grader': 'json', 'answer': {'ids': ['x'], 'total': 5}},
                                     '{"answer":{"total":5,"ids":["x"]}}')['correct'])
        self.assertFalse(grading.grade({'grader': 'json', 'answer': 1}, '{"answer":true}')['correct'])
        self.assertTrue(grading.grade({'grader': 'json', 'answer': {'answer': 42}},
                                     '{"answer":{"answer":42}}')['correct'])

    def test_cutoff_never_passes(self):
        result = grading.grade({'grader': 'numeric', 'answer': 42}, '{"answer":42}', 'length')
        self.assertFalse(result['correct'])
        self.assertTrue(result['truncated'])

    def test_final_answer_not_incidental_number(self):
        self.assertEqual(grading.extract_answer('There were 99 cases.\nFinal answer: 17')[0], '17')
        self.assertIsNone(grading.extract_answer('In 17 attempts, I found 99 possibilities.\nStill uncertain.')[0])


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = datasets.generated(17, 1)

    def test_generation_determinism_and_unique_ids(self):
        self.assertEqual(self.cases, datasets.generated(17, 1))
        self.assertNotEqual(self.cases, datasets.generated(18, 1))
        self.assertEqual(len({c['id'] for c in self.cases}), len(self.cases))
        self.assertEqual(set(c['difficulty'] for c in self.cases), set(datasets.DIFFICULTIES))

    def test_subset_oracle_independent_meet_in_middle(self):
        import ast
        from collections import Counter
        c = next(c for c in self.cases if c['group'] == 'combinatorics')
        values = ast.literal_eval(c['prompt'].split('The list is ')[1].split('. How')[0])
        target = int(c['prompt'].split('summing to ')[1].split('?')[0])
        a, b = values[:14], values[14:]
        left, right = {}, {}
        for size in range(8):
            left[size] = Counter(map(sum, itertools.combinations(a, size)))
            right[size] = Counter(map(sum, itertools.combinations(b, size)))
        expected = sum(count*right[7-size][target-total] for size in range(8)
                       for total, count in left[size].items())
        self.assertEqual(c['answer'], expected)

    def test_context_preserves_secret_and_positions(self):
        cs = datasets.context_cases(123, (100, 1000))
        self.assertEqual(len(cs), 6)
        for c in cs:
            self.assertEqual(c['prompt'].count(' is '+c['answer']+'.'), 1)
            self.assertEqual(len(c['answer']), 9)

    def test_selection_is_repeatable(self):
        a = datasets.select('smoke', 123)
        self.assertEqual(a, datasets.select('smoke', 123))
        self.assertEqual(len(a), 7)
        self.assertEqual({c['difficulty'] for c in datasets.select('smoke', 123, 'easy')}, {'easy'})

    @unittest.skipUnless((datasets.DATA / 'sources.lock.json').exists() and all((datasets.DATA / 'raw' / name).is_file() for name,*_ in datasets.sources()), 'public cache not downloaded')
    def test_real_public_sources_validate_and_answer_types(self):
        cases = datasets.load_public()
        self.assertEqual(len(cases), 4195)
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        self.assertEqual(sum(c['group'] == 'aime2024' for c in cases), 30)
        for c in cases:
            if c['grader'] == 'numeric':
                self.assertIsNotNone(grading.numeric(c['answer']), c['id'])

    def test_payload_has_xhigh_and_no_solution(self):
        c = {'prompt': 'What is two plus two?', 'difficulty': 'hard', 'answer': 'SECRET_TARGET'}
        options = {'seed': 2, 'temperature': 0, 'reasoning': 'xhigh'}
        p = runner.payload(c, options)
        self.assertEqual(p['reasoning_effort'], 'xhigh')
        self.assertEqual(p['max_tokens'], 8192)
        self.assertNotIn('SECRET_TARGET', json.dumps(p))
        options['reasoning'] = 'default'
        self.assertNotIn('reasoning_effort', runner.payload(c, options))


class ConfigTests(unittest.TestCase):
    def test_copy_preserves_source_and_resolves_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pack').mkdir()
            (root / 'profile.bin').write_bytes(b'profile')
            cfg = {'exe': '/old/strata', 'cwd': str(root), 'args': ['--pack', 'pack', '--kv', 'q4_0',
                   '--expert-profile', 'profile.bin', '--vision', '--expert-profile-save', 'learned.bin'],
                   'vision': {'exe': '/old/vision'}, 'env': {'STRATA_TEST': 'yes'}}
            original = root / 'config.json'
            write_json(original, cfg)
            before = original.read_bytes()
            effective, provenance = versions.effective_config(original, {'exe': '/new/strata', 'root': tmp}, root / 'run', 19000)
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(effective['args'][1], str(root / 'pack'))
            self.assertIn('--vision', effective['args'])
            self.assertNotIn('vision', effective)
            self.assertEqual(effective['env'], cfg['env'])
            self.assertEqual(effective['cwd'], str(root / 'run'))
            self.assertEqual(effective['args'][-1], str(root / 'run/learned.bin'))

    def test_unsafe_archive_rejected(self):
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.tar'
            with tarfile.open(path, 'w') as f:
                member = tarfile.TarInfo('../escape')
                member.size = 1
                f.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                versions.extract_tar(path, Path(tmp) / 'out')


class FakeAPI(BaseHTTPRequestHandler):
    calls = []
    fail_enabled = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.reply({'build_info': 'FAKE TEST SERVER'})

    def reply(self, data, status=200):
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        FakeAPI.calls.append(body)
        prompt = body['messages'][-1]['content']
        if prompt == 'fail' or prompt == 'flaky' and FakeAPI.fail_enabled:
            self.reply({'error': 'planned server failure'}, 503)
            return
        content = '{"answer":42}' if prompt != 'incorrect' else '{"answer":41}'
        self.reply({'choices': [{'message': {'content': content, 'reasoning_content': 'not scored'},
                                'finish_reason': 'length' if prompt == 'cutoff' else 'stop'}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), FakeAPI)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        FakeAPI.calls = []
        FakeAPI.fail_enabled = False
        self.endpoint = f'http://127.0.0.1:{self.http.server_port}/v1'
        self.options = {'seed': 1, 'temperature': 0, 'reasoning': 'xhigh', 'profile': 'smoke',
                        'repeats': 1, 'max_tokens': 100, 'timeout': 3, 'startup_timeout': 3,
                        'port': 18765, 'keep_vision': False, 'model': 'strata'}

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def run_fake(self, prompts):
        cases = [datasets.case(str(i), 'g', 'easy', prompt, 42) for i, prompt in enumerate(prompts)]
        target = {'id': 'fake', 'label': 'TEST ONLY', 'endpoint': self.endpoint}
        with mock.patch.object(runner, 'ROOT', self.root), mock.patch.object(runner, 'hardware', return_value={}), contextlib.redirect_stdout(io.StringIO()):
            folder = runner.run(cases, [target], self.options)
        return folder, cases, target

    def test_end_to_end_accuracy_errors_and_cutoffs(self):
        folder, _, _ = self.run_fake(['correct', 'incorrect', 'cutoff'])
        s = read_json(folder / 'summary.json')['ranking'][0]
        self.assertTrue(s['complete'])
        self.assertEqual(s['correct'], 1)
        self.assertEqual(s['truncated'], 1)
        self.assertEqual(s['accuracy'], 1/3)
        self.assertTrue((folder / 'report.html').exists())
        self.assertTrue((folder / 'leaderboard.csv').exists())
        self.assertEqual(FakeAPI.calls[1]['reasoning_effort'], 'xhigh')

    def test_thinking_caps_are_recorded_and_preserved_on_resume(self):
        from stratabench import budgets
        self.options.update(max_tokens=None,thinking_budgets=budgets.normalize({'easy':1500}),thinking_budgets_default=False)
        folder,cases,target=self.run_fake(['correct'])
        request=FakeAPI.calls[-1]
        self.assertEqual(request['reasoning_budget_tokens'],1500)
        self.assertEqual(request['max_tokens'],2524)
        manifest=read_json(folder/'manifest.json')
        self.assertEqual(manifest['options']['thinking_budgets']['easy'],1500)
        count=len(FakeAPI.calls)
        with mock.patch.object(runner,'ROOT',self.root),contextlib.redirect_stdout(io.StringIO()):runner.run(cases,[target],self.options,str(folder))
        self.assertEqual(len(FakeAPI.calls),count)
        changed={**self.options,'thinking_budgets':{**self.options['thinking_budgets'],'easy':2000}}
        with self.assertRaisesRegex(RuntimeError,'settings changed'):runner.run(cases,[target],changed,str(folder))

    def test_resume_skips_answers_and_refuses_settings_drift(self):
        folder, cases, target = self.run_fake(['correct'])
        count = len(FakeAPI.calls)
        with mock.patch.object(runner, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()):
            runner.run(cases, [target], self.options, folder)
            self.assertEqual(len(FakeAPI.calls), count)
            with self.assertRaisesRegex(RuntimeError, 'Resume refused'):
                runner.run(cases, [target], dict(self.options, reasoning='low'), folder)

    def test_failed_combination_excluded_from_ranking(self):
        folder, _, _ = self.run_fake(['fail', 'correct'])
        summary = read_json(folder / 'summary.json')['ranking'][0]
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['errors'], 1)
        self.assertEqual(summary['answered'], 1)
        self.assertEqual(read_json(folder / 'manifest.json')['status'], 'incomplete')

    def test_resume_retries_server_errors_and_retains_attempt_history(self):
        FakeAPI.fail_enabled = True
        folder, cases, target = self.run_fake(['flaky', 'correct'])
        FakeAPI.fail_enabled = False
        with mock.patch.object(runner, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()):
            runner.run(cases, [target], self.options, folder)
        s = read_json(folder / 'summary.json')['ranking'][0]
        self.assertTrue(s['complete'])
        self.assertEqual(s['correct'], 2)
        self.assertEqual(s['errors'], 0)
        self.assertEqual(len(runner.load_rows(folder / 'fake/answers.jsonl')), 3)

    def test_interrupted_matrix_resumes_pending_repeats_without_rerunning_scored_answers(self):
        cases = [datasets.case(str(i), 'g', 'easy', prompt, 42)
                 for i, prompt in enumerate(['correct', 'incorrect', 'cutoff'])]
        targets = [{'id': name, 'label': name, 'endpoint': self.endpoint} for name in ('first', 'second')]
        options = dict(self.options, repeats=2)
        original = runner.completion
        calls = 0

        def interrupt(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 6:  # one warmup, four saved answers, then an interrupted request
                raise KeyboardInterrupt
            return original(*args, **kwargs)

        with mock.patch.object(runner, 'ROOT', self.root), mock.patch.object(runner, 'hardware', return_value={}), contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(runner, 'completion', side_effect=interrupt):
                folder = runner.run(cases, targets, options)
            self.assertEqual(read_json(folder / 'manifest.json')['status'], 'interrupted')
            before = (folder / 'first/answers.jsonl').read_bytes()
            self.assertEqual(len(runner.load_rows(folder / 'first/answers.jsonl')), 4)
            runner.run(cases, targets, options, folder)
        self.assertTrue((folder / 'first/answers.jsonl').read_bytes().startswith(before))
        rows = [r for target in targets for r in runner.load_rows(folder / target['id'] / 'answers.jsonl')]
        self.assertEqual(len(rows), 12)
        self.assertEqual(sum(bool(r.get('correct')) for r in rows), 4)
        self.assertEqual(sum(bool(r.get('truncated')) for r in rows), 4)
        self.assertEqual(read_json(folder / 'manifest.json')['status'], 'complete')
        self.assertEqual(len(FakeAPI.calls), 15)  # 12 evaluations, three session warmups

    def test_corrupt_tail_recovers_only_last_line(self):
        path = self.root / 'answers.jsonl'
        path.write_text('{"a":1}\n{"b":')
        self.assertEqual(runner.load_rows(path), [{'a': 1}])
        self.assertEqual(path.read_text(), '{"a":1}\n')
        path.write_text('bad\n{"a":1}\n')
        with self.assertRaises(RuntimeError):
            runner.load_rows(path)

    def test_comparison_rejects_mismatched_tasks(self):
        a, _, _ = self.run_fake(['correct'])
        b, _, _ = self.run_fake(['correct', 'incorrect'])
        with self.assertRaises(ValueError):
            report.generate(self.root / 'compare', [a, b])


if __name__ == '__main__':
    unittest.main()
