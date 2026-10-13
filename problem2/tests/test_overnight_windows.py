"""完整无改善扫描、改善后重查，以及失败范围不得作为最优证明。"""
import json
from pathlib import Path
import tempfile
import unittest

from problem2.common.encoding import Chromosome, decode, evaluate
from problem2.experiments.overnight_windows import search_until_exhausted, read
from problem2.experiments.stage1_width_comparison import enumerate_window
from problem2.tests.test_exact_case1 import small_data


class OvernightWindowsTests(unittest.TestCase):
    def fake_solver(self, optimal=True, improve=False):
        def solve(data, reference, restriction, folder, seconds, threads, **kwargs):
            self.assertIsNone(seconds)
            self.assertIsNone(kwargs.get('deadline'))
            self.assertEqual(threads, 4)
            code = reference
            if improve:
                # 小实例完整穷举该允许范围，不伪造改善或删除尚未插回的工件。
                allowed = []
                import itertools
                for a in itertools.permutations(range(data.n)):
                    for b in itertools.permutations(range(data.n)):
                        for m in itertools.product((0, 1), repeat=data.n):
                            c = Chromosome(a, b, m)
                            if restriction.satisfies(c):
                                allowed.append(c)
                code = min(allowed, key=lambda c: evaluate(data, c))
            result = decode(data, code)
            result['proof'] = {'optimal': optimal, 'status': 2 if optimal else 9,
                'scope': 'restricted', 'bound': result['objective'],
                'solver_objective': result['objective'], 'runtime': .01, 'model_sha256': 'mock'}
            return result
        return solve

    def test_all_pairs_checked_without_time_or_round_limit(self):
        data = small_data()
        initial = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        with tempfile.TemporaryDirectory() as temp:
            summary = search_until_exhausted(data, initial, Path(temp), 2, 23,
                                             solver=self.fake_solver())
            self.assertEqual(summary['completed_rounds'], 4)
            self.assertEqual(summary['final_pairs_checked'], 4)
            self.assertTrue(summary['local_optimal_for_this_width'])
            state = read(Path(temp)/'checkpoint.json')
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(len(state['checked_pairs']), 4)

    def test_improvement_restarts_all_pairs_for_new_reference(self):
        data = small_data()
        initial = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        with tempfile.TemporaryDirectory() as temp:
            summary = search_until_exhausted(data, initial, Path(temp), 2, 23,
                                             solver=self.fake_solver(improve=True))
            self.assertGreater(summary['improvements'], 0)
            self.assertLess(summary['best'], evaluate(data, initial))
            self.assertEqual(summary['final_pairs_checked'], 4)
            self.assertGreater(summary['completed_rounds'], 4)
            again = search_until_exhausted(data, initial, Path(temp), 2, 23,
                                           solver=lambda *a, **k: self.fail('已完成不得再次求解'))
            self.assertEqual(again, summary)

    def test_unproven_range_stops_with_pending_checkpoint(self):
        data = small_data()
        initial = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, '未证明'):
                search_until_exhausted(data, initial, Path(temp), 2, 23,
                                       solver=self.fake_solver(optimal=False))
            state = read(Path(temp)/'checkpoint.json')
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['completed_rounds'], 0)
            self.assertIsNotNone(state['pending'])
            summary = search_until_exhausted(data, initial, Path(temp), 2, 23,
                                             solver=self.fake_solver())
            self.assertEqual(summary['completed_rounds'], 4)
            self.assertEqual(summary['final_pairs_checked'], 4)


if __name__ == '__main__':
    unittest.main()
