"""Exercise budget semantics and preflight checks without starting a model."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from stratabench import budgets, cli, gui, runner, datasets, capability_runner
from stratabench.estimates import TimingHistory
from stratabench.common import file_hash, write_json


class ThinkingBudgetTests(unittest.TestCase):
    def options(self,values=None,**extra):
        return {**budgets.options_from_form({'use_default_thinking_budgets':values is None,'thinking_budgets':values}),
                'seed':1,'temperature':0,'timeout':10,**extra}

    def test_defaults_preserve_total_generation_limits_and_leave_answer_space(self):
        options=self.options()
        self.assertEqual(options['thinking_budgets'],dict(easy=1024,medium=3072,hard=7168,very_hard=11264,extreme=15360,unrated=7168))
        for level,total in budgets.OUTPUT_DEFAULTS.items():
            body=runner.payload({'difficulty':level,'prompt':'Test'},options)
            self.assertEqual(body['max_tokens'],total)
            self.assertEqual(body['reasoning_budget_tokens'],total-1024)
        self.assertEqual(budgets.defaults('tools')['extreme'],3072)
        self.assertEqual(budgets.defaults('swebench')['unrated'],3072)

    def test_custom_caps_are_sent_and_answer_room_is_added(self):
        options=self.options({'hard':12000})
        body=runner.payload({'difficulty':'hard','prompt':'Test'},options)
        self.assertEqual(body['reasoning_budget_tokens'],12000)
        self.assertEqual(body['max_tokens'],13024)
        self.assertEqual(body['reasoning_effort'],'xhigh')

    def test_overall_limit_is_respected_and_conflicts_rejected(self):
        options=self.options({'hard':12000},max_tokens=8000)
        with self.assertRaisesRegex(ValueError,'below the overall'):budgets.validate(options,['hard'])
        # Only selected difficulties matter.
        budgets.validate(options,['easy'])
        defaults=budgets.options_from_form({'max_tokens':128})
        self.assertEqual(defaults['thinking_budgets']['extreme'],64)
        budgets.validate(defaults,['extreme'])

    def test_off_ignores_custom_caps_and_legacy_runs_keep_original_requests(self):
        options=self.options({'extreme':900000},reasoning='off')
        body=runner.payload({'difficulty':'extreme','prompt':'Test'},options)
        self.assertEqual(body['reasoning_budget_tokens'],0)
        self.assertEqual(body['reasoning_effort'],'none')
        self.assertEqual(body['max_tokens'],16384)
        options.pop('thinking_budgets');options['reasoning']='xhigh'
        self.assertNotIn('reasoning_budget_tokens',runner.payload({'difficulty':'hard','prompt':'Test'},options))

    def test_invalid_values_do_not_turn_into_requests(self):
        for values in ({'hard':0},{'hard':-1},{'hard':True},{'hard':1.2},{'hard':'NaN'},{'hard':''},{'hard':1000001},{'bogus':100},[]):
            with self.subTest(values=values),self.assertRaises(ValueError):budgets.normalize(values)
        for value in (True,1.5,'1.5',0,262145):
            with self.subTest(value=value),self.assertRaises(ValueError):budgets.options_from_form({'max_tokens':value})
        self.assertEqual(budgets.normalize({'hard':'12345'})['hard'],12345)

    def test_context_limits_support_both_flag_formats_and_not_config_defaults(self):
        for args in (['--max-context','16384'],['--max-context=16384']):
            self.assertEqual(budgets.context_limit({'args':args}),16384)
        config={'args':['--max-context','262144'],'max_tokens':64,'reasoning_budget_tokens':10,'id':'ok','name':'ok'}
        self.assertFalse(budgets.compatibility([config],self.options({'hard':50000}),['hard'])['invalid'])
        self.assertIsNone(budgets.context_limit({'args':['--max-context','unknown']}))

    def test_capacity_check_reports_only_incompatible_selected_configs(self):
        configs=[{'id':'small','name':'Small','context':'128144'},{'id':'large','name':'Large','context':'262144'},{'id':'unknown','name':'Unknown'}]
        result=budgets.compatibility(configs,self.options({'extreme':180000}),['easy','extreme'])
        self.assertEqual([x['id'] for x in result['invalid']],['small'])
        self.assertEqual(result['invalid'][0]['levels'],['extreme'])
        self.assertEqual(result['invalid'][0]['required_tokens'],182048)
        self.assertEqual([x['id'] for x in result['unknown']],['unknown'])
        self.assertFalse(budgets.compatibility(configs,self.options({'extreme':180000}),['easy'])['invalid'])

    def test_custom_agent_budget_is_not_silently_capped_at_4096(self):
        case=datasets.select('tools')[0]
        options=self.options({'easy':12000},profile='tools',agent_turns=1)
        response={'content':'{}','finish_reason':'stop','response':{'choices':[{'message':{'content':'{}'}}]}}
        complete=mock.Mock(return_value=response)
        capability_runner.run_agent(case,runner.payload(case,options),'http://fixture/v1',options,complete=complete)
        body=complete.call_args.args[1]
        self.assertEqual(body['reasoning_budget_tokens'],12000)
        self.assertEqual(body['max_tokens'],13024)

    def test_cli_records_caps_in_saved_options_and_checks_active_levels(self):
        args=cli.parser().parse_args(['run','--endpoint','http://fixture/v1','--reasoning','xhigh','--thinking-budgets','{"easy": 1234}'])
        case={'id':'fixture','difficulty':'easy','group':'fixture','prompt':'Test','answer':42}
        with mock.patch.object(cli,'settings',return_value={}),mock.patch.object(cli,'cases_for',return_value=[case]),mock.patch.object(cli,'local_lock',return_value=contextlib.nullcontext()),mock.patch.object(cli,'run') as run,contextlib.redirect_stdout(io.StringIO()):
            cli.execute(args)
        options=run.call_args.args[2]
        self.assertEqual(options['thinking_budgets']['easy'],1234)
        self.assertFalse(options['thinking_budgets_default'])

    def test_history_requires_matching_thinking_cap_even_if_total_limit_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();config=root/'config.json';write_json(config,{})
            target=root/'results/run/target';target.mkdir(parents=True)
            options=self.options(max_tokens=8192)
            write_json(target.parent/'manifest.json',{'options':options,'targets':[{'id':'target','config':str(config),'config_sha256':file_hash(config),'version':{'name':'v1'}}]})
            (target/'answers.jsonl').write_text(json.dumps({'case_id':'test','repeat':0,'difficulty':'hard','elapsed_seconds':6,'request':{'max_tokens':8192,'reasoning_budget_tokens':7168}})+'\n')
            history=TimingHistory(root);history.refresh();cfg={'id':str(config),'name':'test','context':'262144'}
            self.assertEqual(history.estimate(cfg,'v1',{'hard':1},options)['local_sample_questions'],1)
            other={**options,'thinking_budgets':{**options['thinking_budgets'],'hard':4000}}
            self.assertEqual(history.estimate(cfg,'v1',{'hard':1},other)['local_sample_questions'],0)


class BudgetPreflightTests(unittest.TestCase):
    def setUp(self):
        self.app=gui.App.__new__(gui.App)
        self.app.profile_counts={'quick':{'easy':5,'extreme':1},'smoke':{'easy':1}}
        self.configs=[{'id':'small','name':'Small','context':'8000'},{'id':'large','name':'Large','context':'262144'}]
        self.catalog=mock.patch.object(gui,'config_catalog',return_value=self.configs);self.catalog.start();self.addCleanup(self.catalog.stop)
        self.data={'profile':'quick','configs':['small','large'],'difficulties':['easy','extreme'],'use_default_thinking_budgets':False,'thinking_budgets':{'extreme':180000}}

    def test_read_only_check_does_not_start_or_modify_a_config(self):
        before=json.dumps(self.configs)
        self.assertEqual(self.app.action('/api/budget-compatibility',self.data)['invalid'][0]['id'],'small')
        self.assertEqual(json.dumps(self.configs),before)
        self.assertFalse(self.app.action('/api/budget-compatibility',{**self.data,'difficulties':['easy']})['invalid'])

    def test_standard_category_and_context_difficulties_use_actual_levels(self):
        check=self.app.budget_compatibility({**self.data,'profile':'ifeval','thinking_budgets':{'unrated':180000}})
        self.assertEqual(check['levels'],['unrated']);self.assertEqual(check['invalid'][0]['id'],'small')
        check=self.app.budget_compatibility({**self.data,'profile':'context','context_words':'2000 8000','difficulties':['medium','very_hard'],'thinking_budgets':{'very_hard':180000}})
        self.assertEqual(check['levels'],['medium'])
        self.assertFalse(check['invalid'])

    def test_unknown_config_and_untrusted_task_path_are_rejected(self):
        for changes in ({'configs':['bogus']},{'profile':'custom','tasks_id':'../../elsewhere.jsonl'}):
            with self.assertRaises(ValueError):self.app.budget_compatibility({**self.data,**changes})

    def test_run_refuses_incompatible_configs_before_starting_worker(self):
        with mock.patch.object(gui,'run_command',return_value=['run']),mock.patch.object(gui.App,'start') as start:
            with self.assertRaisesRegex(ValueError,'deselect incompatible'):self.app.action('/api/run',self.data)
            start.assert_not_called()
