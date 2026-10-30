"""大组扰动与完整评分重建：候选范围、批量等价、截止与最好解保留。"""
from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch

from problem2.common.encoding import Chromosome, BatchEvaluator, decode, evaluate
from problem2.common.evaluator import Evaluator
from problem2.common.validation import validate_exact
from problem2.stage2.joint_search import free_job_constraints
from problem2.stage2.perturb_rebuild import (
    RebuildConfig, joint_insertions, perturb_selected, repair, run, same_unselected)
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.data = small_data()
        self.reference = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        self.config = RebuildConfig(sizes=(1,2,3), batch_size=16, cache_limit=64, round_seconds=1)

    def test_joint_insertion_set_equals_independent_288_code_filter(self):
        for job in range(3):
            actual = list(joint_insertions(self.reference, job))
            expected = {c for c in codes(3) if free_job_constraints(self.reference, (job,)).satisfies(c)}
            self.assertEqual(len(actual), 18)
            self.assertEqual(set(actual), expected)

    def test_all_trial_codes_score_full_schedule_and_match_scalar(self):
        candidates = [c for j in range(3) for c in joint_insertions(self.reference, j)]
        self.assertEqual(BatchEvaluator(self.data).evaluate(candidates),
                         [evaluate(self.data, c) for c in candidates])
        for code in candidates:
            result = decode(self.data, code)
            validate_exact(self.data, result)
            self.assertEqual(len(result['operations']), 30)

    def test_large_perturbation_preserves_unselected_and_rng_reproducibility(self):
        reference = Chromosome(tuple(range(12)), tuple(reversed(range(12))), (0,1)*6)
        for count in (5,7,9):
            jobs = tuple(range(count))
            candidate = perturb_selected(reference, jobs, random.Random(23))
            candidate.check(12)
            self.assertTrue(same_unselected(reference, candidate, jobs))
            self.assertNotEqual(candidate, reference)
            self.assertEqual(candidate, perturb_selected(reference, jobs, random.Random(23)))

    def test_scalar_and_batch_repair_produce_identical_code(self):
        trial = perturb_selected(self.reference, (0,2), random.Random(23))
        results = []
        for size in (0, 16):
            evaluator = Evaluator(self.data, batch_size=size, cache_limit=32)
            evaluator.cost(self.reference)
            result, diagnostic = repair(trial, (0,2), evaluator, max_passes=5)
            self.assertLessEqual(evaluate(self.data, result), evaluate(self.data, trial))
            self.assertFalse(diagnostic['original_optimality_proven_by_this_run'])
            results.append((result, evaluator.best, evaluator.best_cost))
        self.assertEqual(results[0], results[1])

    def test_finished_batch_best_retained_when_next_batch_times_out(self):
        evaluator = Evaluator(self.data, batch_size=2)
        evaluator.cost(self.reference)
        original = evaluator.batch_evaluator.evaluate
        def expire(candidates):
            scores = original(candidates)
            evaluator.deadline = time.perf_counter()-1
            return scores
        expected = min(evaluate(self.data,c) for c in list(joint_insertions(self.reference, 0))[:2])
        with patch.object(evaluator.batch_evaluator, 'evaluate', side_effect=expire):
            result, diagnostic = repair(self.reference, (0,1,2), evaluator)
        self.assertEqual(diagnostic['termination'], 'time_budget')
        self.assertEqual(evaluator.best_cost, min(evaluate(self.data,self.reference), expected))
        validate_exact(self.data, decode(self.data, evaluator.best))

    def test_run_is_reproducible_and_preserves_monotone_best(self):
        results = []
        with tempfile.TemporaryDirectory() as temp:
            for index in range(2):
                folder = Path(temp)/str(index)
                final = run(self.data, self.reference, folder, self.config,
                            seconds=5, max_rounds=3, save_source=False)
                summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
                self.assertEqual(summary['solver_calls'], 0)
                self.assertLessEqual(summary['cached_codes'], self.config.cache_limit)
                self.assertLessEqual(final['objective'], evaluate(self.data,self.reference))
                values = [r['before'] for r in summary['rows']]+[summary['best']]
                self.assertEqual(values, sorted(values, reverse=True))
                for row in summary['rows']:
                    self.assertEqual(row['best'], evaluate(self.data, Chromosome(
                        tuple(row['best_code']['a']), tuple(row['best_code']['b']), tuple(row['best_code']['machines']))))
                results.append((final, [(r['selected'],r['best_code']) for r in summary['rows']]))
        self.assertEqual(results[0], results[1])

    def test_expired_budget_preserves_reference_without_perturbing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'expired'
            with patch('problem2.stage2.perturb_rebuild.perturb_selected', side_effect=AssertionError('不能扰动')):
                result = run(self.data, self.reference, folder, self.config, seconds=0, save_source=False)
            summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['rounds_completed'], 0)
            self.assertEqual(result['objective'], evaluate(self.data,self.reference))
            self.assertFalse(json.loads((folder/'checkpoint.json').read_text(encoding='utf-8'))['resumable_search_state'])

    def test_error_exports_best_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'error'
            with patch('problem2.stage2.perturb_rebuild.repair', side_effect=RuntimeError('intentional')):
                with self.assertRaises(RuntimeError):
                    run(self.data,self.reference,folder,self.config,seconds=5,save_source=False)
            summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            self.assertFalse(summary['complete'])
            self.assertTrue((folder/'final/result.json').exists())
            self.assertTrue((folder/'failure.json').exists())

    def test_existing_output_and_invalid_parameters_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileExistsError):
                run(self.data,self.reference,Path(temp),self.config,save_source=False)
        for config in (replace(self.config,batch_size=4097),replace(self.config,cache_limit=0),
                       replace(self.config,sizes=()),replace(self.config,round_seconds=float('nan'))):
            with self.assertRaises(ValueError): config.check(3)
        with self.assertRaises(ValueError): list(joint_insertions(self.reference, 3))

    def test_cache_eviction_does_not_change_repair_choice(self):
        outcomes = []
        trial = perturb_selected(self.reference, (0,1,2), random.Random(8))
        for limit in (1, 64):
            evaluator = Evaluator(self.data,cache_limit=limit,batch_size=16)
            evaluator.cost(self.reference)
            code, _ = repair(trial,(0,1,2),evaluator,3)
            outcomes.append((code,evaluator.best,evaluator.best_cost))
            self.assertLessEqual(len(evaluator.cache),limit)
        self.assertEqual(outcomes[0],outcomes[1])


if __name__ == '__main__':
    unittest.main()
