"""质量搜索的全局下降、工作解/最好解分离、接受门槛与中断保留。"""
from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch

from problem2.common.encoding import Chromosome,decode,evaluate
from problem2.common.evaluator import Evaluator
from problem2.common.validation import validate_exact
from problem2.stage2.iterated_search import SearchConfig,PhaseEvaluator,acceptance,perturb,full_descent,run
from problem2.stage2.perturb_rebuild import same_unselected
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes


class Draw:
    def __init__(self,value):self.value=value
    def random(self):return self.value


class IteratedTests(unittest.TestCase):
    def setUp(self):
        self.data=small_data()
        self.reference=Chromosome((0,1,2),(0,1,2),(0,1,0))
        self.config=SearchConfig(sizes=(1,2,3),batch_size=16,cache_limit=128,
            startup_seconds=.5,round_seconds=.5)

    def test_worse_acceptance_and_cap_are_separate_from_best(self):
        self.assertTrue(acceptance(100,102,100,20,.03,Draw(0))['accepted'])
        self.assertFalse(acceptance(100,104,100,20,.03,Draw(0))['accepted'])
        self.assertFalse(acceptance(100,102,100,20,.03,Draw(1))['accepted'])
        self.assertTrue(acceptance(102,101,100,20,.03,Draw(1))['accepted'])

    def test_phase_tracker_does_not_confuse_global_and_current_candidates(self):
        population=list(codes(3))
        best=min(population,key=lambda c:evaluate(self.data,c))
        worst=max(population,key=lambda c:evaluate(self.data,c))
        middle=next(c for c in population if evaluate(self.data,best)<evaluate(self.data,c)<evaluate(self.data,worst))
        evaluator=Evaluator(self.data,batch_size=16)
        evaluator.cost(best)
        tracker=PhaseEvaluator(evaluator,worst)
        tracker.cost(middle)
        self.assertEqual(evaluator.best,best)
        self.assertEqual(tracker.best,middle)

    def test_four_perturbations_keep_valid_complete_codes(self):
        for mode in ('mild_a','mild_b','machines','strong'):
            candidate=perturb(self.reference,(0,2),mode,random.Random(23))
            candidate.check(3)
            self.assertNotEqual(candidate,self.reference)
            validate_exact(self.data,decode(self.data,candidate))
            self.assertTrue(same_unselected(self.reference,candidate,(0,2)))
            if mode=='mild_a':self.assertEqual(candidate.b,self.reference.b)
            if mode=='mild_b':self.assertEqual(candidate.a,self.reference.a)
            if mode=='machines':self.assertEqual((candidate.a,candidate.b),(self.reference.a,self.reference.b))

    def test_full_descent_releases_previously_unselected_jobs(self):
        evaluator=Evaluator(self.data,batch_size=16)
        evaluator.cost(self.reference)
        outside=[]
        original=evaluator.costs
        def record(candidates):
            for trial,value in original(candidates):
                if not same_unselected(self.reference,trial,(0,)):outside.append(trial)
                yield trial,value
        with patch.object(evaluator,'costs',side_effect=record):
            candidate,info=full_descent(self.reference,evaluator,time.perf_counter()+2,random.Random(23))
        self.assertTrue(info['all_jobs'])
        self.assertTrue(info['basic_complete'])
        self.assertLess(evaluate(self.data,candidate),evaluate(self.data,self.reference))
        self.assertTrue(outside)

    def test_accepted_worse_working_solution_continues_but_best_is_kept(self):
        population=list(codes(3))
        reference=min(population,key=lambda c:evaluate(self.data,c))
        worse=next(c for c in population if evaluate(self.data,c)>evaluate(self.data,reference))
        def candidate(initial,evaluator,deadline,rng):
            evaluator.cost(worse)
            return worse,{'all_jobs':True}
        cfg=replace(self.config,startup_seconds=0,temperature_scale=10,worse_cap=10,restart_stall=10)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'run'
            with patch('problem2.stage2.iterated_search.full_descent',side_effect=candidate),patch.object(random.Random,'random',return_value=0):
                final=run(self.data,reference,folder,cfg,seconds=5,max_rounds=2,save_source=False)
            summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(final['objective'],evaluate(self.data,reference))
            self.assertGreaterEqual(summary['accepted_worse'],1)
            self.assertEqual(summary['rows'][1]['base_code'],summary['rows'][0]['current_code'])
            self.assertGreater(summary['rows'][0]['current'],summary['rows'][0]['best'])

    def test_seeded_run_retains_monotone_best_and_reproduces(self):
        outcomes=[]
        with tempfile.TemporaryDirectory() as temp:
            for index in range(2):
                folder=Path(temp)/str(index)
                result=run(self.data,self.reference,folder,self.config,seconds=5,max_rounds=4,save_source=False)
                summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
                values=[r['before_best'] for r in summary['rows']]+[summary['best']]
                self.assertEqual(values,sorted(values,reverse=True))
                self.assertEqual(summary['solver_calls'],0)
                self.assertLessEqual(summary['cached_codes'],self.config.cache_limit)
                outcomes.append((result,[(r['mode'],r['selected'],r['current_code']) for r in summary['rows']]))
        self.assertEqual(outcomes[0],outcomes[1])

    def test_expired_budget_keeps_reference_without_perturbing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'expired'
            with patch('problem2.stage2.iterated_search.perturb',side_effect=AssertionError('expired')):
                final=run(self.data,self.reference,folder,self.config,seconds=0,save_source=False)
            self.assertEqual(final['objective'],evaluate(self.data,self.reference))
            self.assertEqual(json.loads((folder/'summary.json').read_text(encoding='utf-8'))['rounds'],0)

    def test_failure_retains_best_complete_schedule(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'error'
            with patch('problem2.stage2.iterated_search.full_descent',side_effect=RuntimeError('intentional')):
                with self.assertRaises(RuntimeError):
                    run(self.data,self.reference,folder,self.config,seconds=5,save_source=False)
            self.assertFalse(json.loads((folder/'summary.json').read_text(encoding='utf-8'))['complete'])
            validate_exact(self.data,json.loads((folder/'final/result.json').read_text(encoding='utf-8')))

    def test_existing_folder_and_invalid_config_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileExistsError):
                run(self.data,self.reference,Path(temp),self.config,save_source=False)
        for cfg in (replace(self.config,temperature_scale=0),replace(self.config,worse_cap=-1),
                    replace(self.config,cooling=2),replace(self.config,batch_size=5000)):
            with self.assertRaises(ValueError):cfg.check(3)

    def test_equal_candidate_is_accepted_without_random_draw(self):
        result=acceptance(100,100,100,20,.03,Draw(1))
        self.assertTrue(result['accepted'])
        self.assertIsNone(result['draw'])

    def test_expired_phase_registers_known_complete_candidate_and_restores_deadline(self):
        evaluator=Evaluator(self.data)
        evaluator.cost(self.reference)
        better=min(codes(3),key=lambda c:evaluate(self.data,c))
        expired=time.perf_counter()-1
        evaluator.deadline=expired
        tracker=PhaseEvaluator(evaluator,better)
        self.assertEqual(evaluator.best,better)
        self.assertEqual(evaluator.best_cost,tracker.best_cost)
        self.assertEqual(evaluator.deadline,expired)


if __name__=='__main__':unittest.main()
