"""核对全位置插入范围、信息选择及小实例的受限最优值。"""
from collections import Counter
import itertools
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from problem2.common.data import CaseData
from problem2.common.encoding import Chromosome, evaluate, code_from_result
from problem2.common.annealing_records import model_counts
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_free_jobs import choose_jobs
from problem2.stage2.joint_search import free_job_constraints
from problem2.tests.test_exact_case1 import small_data


class FreeJobsTests(unittest.TestCase):
    def test_long_distance_insertion_and_machine_change_allowed(self):
        ref = Chromosome((0, 1, 2, 3, 4), (4, 3, 2, 1, 0), (0, 0, 0, 0, 0))
        restriction = free_job_constraints(ref, (1, 3))
        moved = Chromosome((1, 0, 2, 4, 3), (1, 4, 2, 0, 3), (0, 1, 0, 1, 0))
        self.assertTrue(restriction.satisfies(ref))
        self.assertTrue(restriction.satisfies(moved))
        self.assertFalse(restriction.satisfies(Chromosome((1, 0, 4, 2, 3), moved.b, moved.machines)))
        self.assertFalse(restriction.satisfies(Chromosome(moved.a, moved.b, (1, 1, 0, 1, 0))))

    def test_free_jobs_cannot_create_full_model(self):
        code = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        for jobs in ((), (0, 0), (0, 1, 2), (3,)):
            with self.assertRaises(ValueError):
                free_job_constraints(code, jobs)

    def test_archive_signal_selects_changed_jobs(self):
        data = CaseData(2, tuple(f'J{i+1}' for i in range(6)), ((1,)*10,)*6, ((0,)*6,)*6)
        ref = Chromosome(tuple(range(6)), tuple(range(6)), (0,)*6)
        other = Chromosome((5, 1, 2, 3, 4, 0), ref.b, ref.machines)
        with patch('problem2.experiments.stage1_free_jobs.critical_weights',
                   return_value={'A': Counter(), 'B': Counter()}):
            jobs, details = choose_jobs(data, ref, [ref, other], 'guided', 1, random.Random(11), set())
        self.assertEqual(jobs, (0, 5))
        self.assertEqual(details['policy'], 'archive')

    def test_random_does_not_use_archive_or_critical_scores(self):
        data = small_data()
        code = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        rng, seen, selected = random.Random(7), set(), []
        with patch('problem2.experiments.stage1_free_jobs.critical_weights', side_effect=AssertionError):
            for iteration in range(3):
                selected.append(choose_jobs(data, code, [], 'random', iteration, rng, seen)[0])
            self.assertIsNone(choose_jobs(data, code, [], 'random', 3, rng, seen))
        self.assertEqual(set(selected), {(0, 1), (0, 2), (1, 2)})


def integration():
    data = small_data()
    ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
    all_codes = [Chromosome(a, b, m) for a in itertools.permutations(range(3))
                 for b in itertools.permutations(range(3)) for m in itertools.product((0, 1), repeat=3)]
    for jobs in ((0,), (0, 1)):
        restriction = free_job_constraints(ref, jobs)
        allowed = [c for c in all_codes if restriction.satisfies(c)]
        expected = min(evaluate(data, c) for c in allowed)
        with tempfile.TemporaryDirectory(prefix='problem2-free-jobs-test-') as temp:
            result = optimize_once(data, ref, restriction, Path(temp)/'round', 30, 2,
                                   strengthen=True, compact=True)
            self_count = model_counts(restriction)['binary_variables']
            assert result['proof']['optimal']
            assert abs(result['objective']-expected) <= 1e-4
            assert result['proof']['reduction']['binary_variables'] == self_count
            assert restriction.satisfies(code_from_result(result, 3))
            validate_exact(data, result)
            print(f'free={jobs}, allowed={len(allowed)}, optimum={expected}, binaries={self_count}')


if __name__ == '__main__':
    if '--integration' in sys.argv:
        integration()
    else:
        unittest.main()
