import json
from pathlib import Path
import tempfile
import unittest

from stratabench.common import file_hash, write_json
from stratabench.estimates import TimingHistory
from stratabench.reference_scores import catalog, reference_rows
from stratabench.version_order import apply_order, ordered_names


class VersionOrderTests(unittest.TestCase):
    def state(self):
        return {'versions':{name:{} for name in ['v0.1.9','v0.1.40.4','v0.1.40.12','v0.2.0-rc1','v0.2.0']}}

    def test_numeric_versions_and_stable_release(self):
        state = self.state()
        self.assertEqual(ordered_names(state), ['v0.2.0','v0.2.0-rc1','v0.1.40.12','v0.1.40.4','v0.1.9'])
        apply_order(state,'oldest')
        self.assertEqual(ordered_names(state), ['v0.1.9','v0.1.40.4','v0.1.40.12','v0.2.0-rc1','v0.2.0'])

    def test_custom_order_survives_new_arrivals_and_reload(self):
        state = self.state()
        custom = list(state['versions'])
        apply_order(state,'custom',custom)
        state['versions']['v0.3.0'] = {}
        restored = json.loads(json.dumps(state))
        self.assertEqual(ordered_names(restored), custom+['v0.3.0'])
        apply_order(restored,'newest')
        self.assertEqual(ordered_names(restored)[0],'v0.3.0')

    def test_invalid_or_stale_order_is_rejected(self):
        state = self.state()
        for order in ([],['v0.1.9']*5,['missing'],None):
            with self.assertRaises(ValueError):
                apply_order(state,'custom',order)


class ReferenceTests(unittest.TestCase):
    def test_default_score_has_verified_model_precision_and_provenance(self):
        refs = catalog()
        self.assertEqual(refs['model'],'Qwen/Qwen3.8-Flash-Next')
        self.assertEqual(refs['precision'],'BF16')
        gsm = reference_rows(['gsm8k'])[0]
        self.assertTrue(gsm['available'])
        self.assertEqual(gsm['score_percent'],96.92)
        self.assertEqual(gsm['weight_precision'],'BF16')
        self.assertFalse(gsm['directly_comparable'])
        self.assertIn('5-shot',gsm['method'])
        self.assertIn(gsm['source_revision'],gsm['source'])

    def test_no_invented_reference_for_custom_or_mismatched_datasets(self):
        for row in reference_rows(['custom','math500_numeric','aime2024','bbh_web_of_lies']):
            self.assertFalse(row['available'])
            self.assertIsNone(row['score_percent'])
            self.assertTrue(row['reason'])


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root/'config.json'
        write_json(self.path,{'args':[],'model_name':'iq3_s'})
        self.config = {'id':str(self.path),'name':'strata-iq3_s','model':'iq3_s','context':'262144'}
        self.history = TimingHistory(self.root)
        self.options = {'reasoning':'xhigh','repeats':1,'max_tokens':None,'timeout':1800,'startup_timeout':900}

    def tearDown(self):
        self.tmp.cleanup()

    def estimate(self,counts,options=None,config=None,version='v1'):
        return self.history.estimate(config or self.config,version,counts,options or self.options)

    def test_duration_scales_with_questions_repeats_and_config(self):
        small = self.estimate({'medium':10})
        large = self.estimate({'medium':100})
        repeated = self.estimate({'medium':10},{**self.options,'repeats':3})
        disk = self.estimate({'medium':10},config={**self.config,'model':'unsloth-q4_k_xl','name':'strata-q4_k_xl'})
        self.assertGreater(large['lower_seconds'],small['lower_seconds'])
        self.assertGreater(repeated['upper_seconds'],small['upper_seconds'])
        self.assertGreater(disk['upper_seconds'],small['upper_seconds'])
        self.assertEqual(small['local_sample_questions'],0)
        self.assertIn('not measured',small['basis'])

    def test_reasoning_and_output_budget_affect_estimate(self):
        high = self.estimate({'hard':20})
        off = self.estimate({'hard':20},{**self.options,'reasoning':'off'})
        capped = self.estimate({'hard':20},{**self.options,'max_tokens':128})
        self.assertGreater(high['upper_seconds'],off['upper_seconds'])
        self.assertGreater(high['upper_seconds'],capped['upper_seconds'])

    def test_history_is_scoped_by_version_reasoning_config_and_difficulty(self):
        folder = self.root/'results/run';target=folder/'target'
        target.mkdir(parents=True)
        write_json(folder/'manifest.json',{'options':self.options,'targets':[{'id':'target','config':str(self.path),
            'config_sha256':file_hash(self.path),'version':{'name':'v1'}}]})
        rows = [{'case_id':str(i),'repeat':0,'difficulty':'easy','elapsed_seconds':5+i,
                 'request':{'max_tokens':2048},'correct':True} for i in range(3)]
        rows.append({'case_id':'timeout','repeat':0,'difficulty':'easy','elapsed_seconds':1800,'error':'timeout'})
        (target/'answers.jsonl').write_text('\n'.join(json.dumps(x) for x in rows))
        self.history.refresh()
        measured = self.estimate({'easy':10})
        self.assertEqual(measured['local_sample_questions'],3)
        self.assertEqual(measured['measured_difficulties'],['easy'])
        self.assertEqual(self.estimate({'hard':10})['local_sample_questions'],0)
        self.assertEqual(self.estimate({'easy':10},version='v2')['local_sample_questions'],0)
        self.assertEqual(self.estimate({'easy':10},{**self.options,'reasoning':'off'})['local_sample_questions'],0)
        write_json(self.path,{'changed':True})
        self.assertEqual(self.estimate({'easy':10})['local_sample_questions'],0)

    def test_context_includes_prompt_reading_and_capacity_notice(self):
        short = self.estimate({'very_hard':3},{**self.options,'context_words_list':[16000]})
        long = self.estimate({'very_hard':3},{**self.options,'context_words_list':[100000]},
                             config={**self.config,'context':'32768'})
        self.assertGreater(long['upper_seconds'],short['upper_seconds'])
        self.assertTrue(long['warnings'])


if __name__ == '__main__':
    unittest.main()
